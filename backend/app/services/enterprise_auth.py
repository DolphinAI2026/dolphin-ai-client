from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import and_, or_, select, update

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


def validate_enterprise_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip()
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError:
        raise _account_invalid() from None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _account_invalid()
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def base_url_origin_changed(old_base_url: str, new_base_url: str) -> bool:
    def origin(base_url: str) -> tuple[str, str, int]:
        parsed = urlsplit(validate_enterprise_base_url(base_url))
        default_port = 443 if parsed.scheme == "https" else 80
        return parsed.scheme, str(parsed.hostname or "").lower(), parsed.port or default_port

    return origin(old_base_url) != origin(new_base_url)


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


def _account_tokens_are_readable(account: Any) -> bool:
    if account.status != STATUS_CONNECTED:
        return False
    expires_at = account.token_expires_at
    if expires_at is None:
        return True
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at > now


def read_access_token(account: Any) -> str | None:
    if not _account_tokens_are_readable(account) or not account.access_token_enc:
        return None
    return crypto.decrypt_password(account.access_token_enc)


def read_refresh_token(account: Any) -> str | None:
    if not _account_tokens_are_readable(account) or not account.refresh_token_enc:
        return None
    return crypto.decrypt_password(account.refresh_token_enc)


async def resolve_bound_account(
    db: Any,
    source_provider: str,
    source_base_url: str,
    source_tenant_ref: str,
    source_account: str,
    target_provider: str,
    lock: bool = False,
) -> BindingResolution:
    normalized_source_provider = normalize_provider(source_provider)
    normalized_target_provider = normalize_provider(target_provider)
    normalized_source_base_url = normalize_base_url(source_base_url)
    normalized_source_tenant_ref = str(source_tenant_ref or "").strip()
    normalized_source_account = str(source_account or "").strip()
    source_statement = select(EnterpriseAuthAccount).where(
        EnterpriseAuthAccount.provider == normalized_source_provider,
        EnterpriseAuthAccount.base_url == normalized_source_base_url,
        EnterpriseAuthAccount.tenant_ref == normalized_source_tenant_ref,
        EnterpriseAuthAccount.account == normalized_source_account,
        EnterpriseAuthAccount.status != STATUS_DISABLED,
    )
    source = (
        await db.execute(source_statement)
    ).scalar_one_or_none()
    if source is None:
        return BindingResolution(
            account=None,
            code=ENTERPRISE_AUTH_BINDING_NOT_FOUND,
            message="Enterprise account binding not found",
        )

    if lock:
        related_pair_statement = select(
            EnterpriseAuthBinding.left_account_id,
            EnterpriseAuthBinding.right_account_id,
        ).where(
            or_(
                EnterpriseAuthBinding.left_account_id == source.id,
                EnterpriseAuthBinding.right_account_id == source.id,
            )
        )
        related_pairs = (await db.execute(related_pair_statement)).all()
        related_account_ids = {source.id}
        for left_account_id, right_account_id in related_pairs:
            related_account_ids.update((left_account_id, right_account_id))
        account_ids = sorted(related_account_ids)
        locked_accounts = (
            await db.execute(
                select(EnterpriseAuthAccount)
                .where(EnterpriseAuthAccount.id.in_(account_ids))
                .order_by(EnterpriseAuthAccount.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalars().all()
        locked_bindings = (
            await db.execute(
                select(EnterpriseAuthBinding)
                .where(
                    or_(
                        EnterpriseAuthBinding.left_account_id == source.id,
                        EnterpriseAuthBinding.right_account_id == source.id,
                    )
                )
                .order_by(
                    EnterpriseAuthBinding.left_account_id.asc(),
                    EnterpriseAuthBinding.right_account_id.asc(),
                )
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalars().all()
        accounts_by_id = {account.id: account for account in locked_accounts}
        locked_source = accounts_by_id.get(source.id)
        if (
            locked_source is None
            or locked_source.provider != normalized_source_provider
            or locked_source.base_url != normalized_source_base_url
            or locked_source.tenant_ref != normalized_source_tenant_ref
            or locked_source.account != normalized_source_account
            or locked_source.status == STATUS_DISABLED
        ):
            return BindingResolution(
                account=None,
                code=ENTERPRISE_AUTH_BINDING_NOT_FOUND,
                message="Enterprise account binding not found",
            )

        rows = []
        for binding in locked_bindings:
            if not binding.enabled:
                continue
            if binding.left_account_id == locked_source.id:
                target_id = binding.right_account_id
            elif binding.right_account_id == locked_source.id:
                target_id = binding.left_account_id
            else:
                continue
            target = accounts_by_id.get(target_id)
            if (
                target is None
                or target.provider != normalized_target_provider
                or target.status == STATUS_DISABLED
            ):
                continue
            rows.append((target, binding.priority))
        rows.sort(key=lambda row: row[1])
    else:
        target_statement = (
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
        rows = (await db.execute(target_statement)).all()
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
        base_url = validate_enterprise_base_url(account.base_url)
        if provider == PROVIDER_CONTROL_PLANE:
            result = await login_to_coding_control_plane(
                account.account,
                password,
                base_url=base_url,
            )
            access_token = str(result.access_token or "").strip()
            refresh_token = str(result.refresh_token or "").strip() or None
        else:
            client = APaaSClient(
                base_url=base_url,
                tenant_id=account.tenant_ref,
                verify_tls=True,
                record_call_logs=False,
            )
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


def _binding_unavailable(account: Any | None = None) -> BindingResolution:
    return BindingResolution(
        account=account,
        code=ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
        message="Enterprise account binding is unavailable",
    )


async def _rollback(db: Any) -> bool:
    try:
        await db.rollback()
        return True
    except Exception:
        return False


async def _record_account_auth_failure(
    db: Any,
    account_id: int,
    error_message: str,
) -> Any | None:
    try:
        result = await db.execute(
            update(EnterpriseAuthAccount)
            .where(
                EnterpriseAuthAccount.id == account_id,
                EnterpriseAuthAccount.status != STATUS_DISABLED,
            )
            .values(
                status=STATUS_ERROR,
                last_error=error_message,
            )
            .execution_options(synchronize_session=False)
        )
    except Exception:
        await _rollback(db)
        return None
    if result.rowcount != 1:
        await _rollback(db)
        try:
            return await db.get(EnterpriseAuthAccount, account_id)
        except Exception:
            await _rollback(db)
            return None
    try:
        await db.commit()
    except Exception:
        await _rollback(db)
        return None
    try:
        account = await db.get(EnterpriseAuthAccount, account_id)
        if account is not None:
            await db.refresh(account)
        return account
    except Exception:
        await _rollback(db)
        return None


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
        await _rollback(db)
        return _binding_unavailable()
    if resolution.account is None:
        return resolution

    target_account_id = resolution.account.id
    try:
        await authenticate_enterprise_account(resolution.account)
        access_token = crypto.decrypt_password(resolution.account.access_token_enc)
        refresh_token = (
            crypto.decrypt_password(resolution.account.refresh_token_enc)
            if resolution.account.refresh_token_enc
            else None
        )
        expires_at = resolution.account.token_expires_at
    except Exception:
        await _rollback(db)
        failed_account = await _record_account_auth_failure(
            db,
            target_account_id,
            "Enterprise account authentication failed",
        )
        return _binding_unavailable(failed_account)

    if not await _rollback(db):
        return _binding_unavailable()

    try:
        revalidated = await resolve_bound_account(
            db,
            source_provider,
            source_base_url,
            source_tenant_ref,
            source_account,
            target_provider,
            lock=True,
        )
    except Exception:
        await _rollback(db)
        return _binding_unavailable()
    if (
        revalidated.account is None
        or revalidated.account.id != target_account_id
    ):
        await _rollback(db)
        return _binding_unavailable()

    target_account = revalidated.account
    try:
        await db.refresh(target_account)
    except Exception:
        await _rollback(db)
        return _binding_unavailable()
    if target_account.status == STATUS_DISABLED:
        await _rollback(db)
        return _binding_unavailable()

    try:
        persistence_result = await db.execute(
            update(EnterpriseAuthAccount)
            .where(
                EnterpriseAuthAccount.id == target_account_id,
                EnterpriseAuthAccount.status != STATUS_DISABLED,
            )
            .values(
                access_token_enc=crypto.encrypt_password(access_token),
                refresh_token_enc=(
                    crypto.encrypt_password(refresh_token)
                    if refresh_token
                    else None
                ),
                token_expires_at=expires_at,
                status=STATUS_CONNECTED,
                last_verified_at=datetime.now(UTC).replace(tzinfo=None),
                last_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        if persistence_result.rowcount != 1:
            await _rollback(db)
            return _binding_unavailable()
        await db.commit()
    except Exception:
        await _rollback(db)
        failed_account = await _record_account_auth_failure(
            db,
            target_account_id,
            "Enterprise account credential persistence failed",
        )
        return _binding_unavailable(failed_account)
    try:
        persisted_account = await db.get(EnterpriseAuthAccount, target_account_id)
        if persisted_account is None:
            return _binding_unavailable()
        await db.refresh(persisted_account)
        return BindingResolution(
            account=persisted_account,
            code=OK,
            message="Enterprise account binding refreshed",
        )
    except Exception:
        await _rollback(db)
        return _binding_unavailable()
