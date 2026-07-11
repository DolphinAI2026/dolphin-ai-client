from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select

from app import crypto
from app.apaas_client import APaaSClient
from app.code_runtime.auth import login_to_coding_control_plane
from app.config import settings
from app.models import EnterpriseAuthAccount, EnterpriseAuthBinding

PROVIDER_APAAS = "apaas"
PROVIDER_CONTROL_PLANE = "control_plane"

STATUS_UNVERIFIED = "unverified"
STATUS_CONNECTED = "connected"
STATUS_ERROR = "error"
STATUS_DISABLED = "disabled"

OK = "OK"
DISABLED = "DISABLED"
ENTERPRISE_AUTH_ACCOUNT_INVALID = "ENTERPRISE_AUTH_ACCOUNT_INVALID"
ENTERPRISE_AUTH_BINDING_NOT_FOUND = "ENTERPRISE_AUTH_BINDING_NOT_FOUND"
ENTERPRISE_AUTH_BINDING_AMBIGUOUS = "ENTERPRISE_AUTH_BINDING_AMBIGUOUS"
ENTERPRISE_AUTH_BINDING_UNAVAILABLE = "ENTERPRISE_AUTH_BINDING_UNAVAILABLE"


class EnterpriseAuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BindingResolution:
    account: Any | None
    code: str
    message: str


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "coding":
        normalized = PROVIDER_CONTROL_PLANE
    if normalized not in {PROVIDER_APAAS, PROVIDER_CONTROL_PLANE}:
        raise EnterpriseAuthError(
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "Unsupported enterprise auth provider",
        )
    return normalized


def normalize_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def set_account_password(account: Any, password: str | None) -> None:
    if password:
        account.password_enc = crypto.encrypt_password(password)


def set_account_tokens(
    account: Any,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    account.access_token_enc = crypto.encrypt_password(access_token)
    account.refresh_token_enc = (
        crypto.encrypt_password(refresh_token) if refresh_token else None
    )
    account.token_expires_at = expires_at
    account.status = STATUS_CONNECTED
    account.last_verified_at = datetime.now(UTC).replace(tzinfo=None)
    account.last_error = None


def read_access_token(account: Any) -> str | None:
    if not account.access_token_enc:
        return None
    return crypto.decrypt_password(account.access_token_enc)


def read_refresh_token(account: Any) -> str | None:
    if not account.refresh_token_enc:
        return None
    return crypto.decrypt_password(account.refresh_token_enc)


async def resolve_bound_account(
    db: Any,
    source_provider: str,
    source_base_url: str,
    source_tenant_ref: str,
    source_account: str,
    target_provider: str,
) -> BindingResolution:
    normalized_source_provider = normalize_provider(source_provider)
    normalized_target_provider = normalize_provider(target_provider)
    source = (
        await db.execute(
            select(EnterpriseAuthAccount).where(
                EnterpriseAuthAccount.provider == normalized_source_provider,
                EnterpriseAuthAccount.base_url == normalize_base_url(source_base_url),
                EnterpriseAuthAccount.tenant_ref == str(source_tenant_ref or "").strip(),
                EnterpriseAuthAccount.account == str(source_account or "").strip(),
                EnterpriseAuthAccount.status != STATUS_DISABLED,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        return BindingResolution(
            account=None,
            code=ENTERPRISE_AUTH_BINDING_NOT_FOUND,
            message="Enterprise account binding not found",
        )

    rows = (
        await db.execute(
            select(EnterpriseAuthAccount, EnterpriseAuthBinding.priority)
            .join(
                EnterpriseAuthBinding,
                or_(
                    and_(
                        EnterpriseAuthBinding.left_account_id == source.id,
                        EnterpriseAuthBinding.right_account_id
                        == EnterpriseAuthAccount.id,
                    ),
                    and_(
                        EnterpriseAuthBinding.right_account_id == source.id,
                        EnterpriseAuthBinding.left_account_id
                        == EnterpriseAuthAccount.id,
                    ),
                ),
            )
            .where(
                EnterpriseAuthBinding.enabled.is_(True),
                EnterpriseAuthAccount.provider == normalized_target_provider,
                EnterpriseAuthAccount.status != STATUS_DISABLED,
            )
            .order_by(EnterpriseAuthBinding.priority.asc())
        )
    ).all()
    if not rows:
        return BindingResolution(
            account=None,
            code=ENTERPRISE_AUTH_BINDING_NOT_FOUND,
            message="Enterprise account binding not found",
        )

    minimum_priority = rows[0][1]
    minimum_rows = [row for row in rows if row[1] == minimum_priority]
    if len(minimum_rows) != 1:
        return BindingResolution(
            account=None,
            code=ENTERPRISE_AUTH_BINDING_AMBIGUOUS,
            message="Enterprise account binding is ambiguous",
        )
    return BindingResolution(
        account=minimum_rows[0][0],
        code=OK,
        message="Enterprise account binding resolved",
    )


def _account_invalid() -> EnterpriseAuthError:
    return EnterpriseAuthError(
        ENTERPRISE_AUTH_ACCOUNT_INVALID,
        "Enterprise account credentials are invalid",
    )


async def authenticate_enterprise_account(account: Any) -> Any:
    if not account.password_enc:
        raise _account_invalid()
    try:
        password = crypto.decrypt_password(account.password_enc)
        provider = normalize_provider(account.provider)
        base_url = normalize_base_url(account.base_url)
        if provider == PROVIDER_CONTROL_PLANE:
            result = await login_to_coding_control_plane(
                account.account,
                password,
                base_url=base_url,
            )
            access_token = str(result.access_token or "").strip()
            refresh_token = str(result.refresh_token or "").strip() or None
        else:
            client = APaaSClient(base_url=base_url, tenant_id=account.tenant_ref)
            login_result = await client.login(account.account, password)
            access_token = (
                str(login_result.get("token") or "").strip()
                if isinstance(login_result, dict)
                else ""
            )
            refresh_token = None
        if not access_token:
            raise _account_invalid()
        set_account_tokens(account, access_token, refresh_token=refresh_token)
        return account
    except EnterpriseAuthError:
        raise
    except Exception:
        raise _account_invalid() from None


async def refresh_bound_account_after_login(
    db: Any,
    source_provider: str,
    source_base_url: str,
    source_tenant_ref: str,
    source_account: str,
    target_provider: str,
) -> BindingResolution:
    if not settings.auth_account_binding_enabled:
        return BindingResolution(
            account=None,
            code=DISABLED,
            message="Enterprise account binding is disabled",
        )

    try:
        resolution = await resolve_bound_account(
            db,
            source_provider,
            source_base_url,
            source_tenant_ref,
            source_account,
            target_provider,
        )
    except Exception:
        return BindingResolution(
            account=None,
            code=ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
            message="Enterprise account binding is unavailable",
        )
    if resolution.account is None:
        return resolution

    try:
        await authenticate_enterprise_account(resolution.account)
        await db.commit()
        return resolution
    except Exception:
        resolution.account.status = STATUS_ERROR
        resolution.account.last_error = "Enterprise account authentication failed"
        try:
            await db.commit()
        except Exception:
            pass
        return BindingResolution(
            account=resolution.account,
            code=ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
            message="Enterprise account binding is unavailable",
        )
