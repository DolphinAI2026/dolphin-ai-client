from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import ipaddress
import json
import unicodedata
from typing import Any, Iterable
from urllib.parse import urlsplit

import idna
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import OperationalError

from app import crypto
from app.apaas_client import APaaSClient
from app.code_runtime.auth import login_to_coding_control_plane
from app.config import settings
from app.models import (
    APaaSUserCredential,
    EnterpriseAuthAccount,
    EnterpriseAuthBinding,
)
from app.models.tenant import Tenant

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

_LOCKED_BINDING_RESOLUTION_MAX_ATTEMPTS = 2
_ACCOUNT_GRAPH_LOCK_MAX_ATTEMPTS = 2
_AUTH_GENERATION_CLAIM_MAX_ATTEMPTS = 5
_AUTH_GENERATION_CLAIM_RETRY_DELAY_SECONDS = 0.01


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


@dataclass(frozen=True)
class ProviderTokenResolution:
    token: str | None
    base_url: str | None
    code: str
    message: str


@dataclass(frozen=True)
class LockedAccountGraph:
    account: Any | None
    accounts_by_id: dict[int, Any]
    bindings: list[Any]


@dataclass(repr=False)
class EnterpriseAuthCredentialSnapshot:
    id: int
    provider: str
    base_url: str
    tenant_ref: str
    account: str
    password_enc: str | None
    credential_fingerprint: str
    access_token_enc: str | None = None
    refresh_token_enc: str | None = None
    token_expires_at: datetime | None = None
    status: str = STATUS_UNVERIFIED
    last_verified_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class EnterpriseAuthGenerationClaim:
    account_id: int
    generation: int
    credential_fingerprint: str
    credentials: EnterpriseAuthCredentialSnapshot


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
    return validate_enterprise_base_url(base_url)


def validate_enterprise_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip()
    if any(
        character.isspace()
        or unicodedata.category(character).startswith("C")
        for character in raw
    ):
        raise _account_invalid()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
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
    if port is not None and not 1 <= port <= 65535:
        raise _account_invalid()
    raw_hostname = (
        parsed.hostname
        .translate(str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."}))
        .rstrip(".")
    )
    if not raw_hostname:
        raise _account_invalid()
    try:
        ip_address = ipaddress.ip_address(raw_hostname)
    except ValueError:
        try:
            hostname = idna.encode(
                raw_hostname,
                uts46=True,
                std3_rules=True,
            ).decode("ascii").lower()
        except (idna.IDNAError, UnicodeError):
            raise _account_invalid() from None
    else:
        hostname = ip_address.compressed.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    path = _remove_url_dot_segments(parsed.path).rstrip("/")
    return f"{parsed.scheme.lower()}://{hostname}{port_suffix}{path}"


def _remove_url_dot_segments(path: str) -> str:
    input_buffer = str(path or "")
    output_buffer = ""
    while input_buffer:
        if input_buffer.startswith("../"):
            input_buffer = input_buffer[3:]
        elif input_buffer.startswith("./"):
            input_buffer = input_buffer[2:]
        elif input_buffer.startswith("/./"):
            input_buffer = "/" + input_buffer[3:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = "/" + input_buffer[4:]
            output_buffer = output_buffer.rsplit("/", 1)[0]
        elif input_buffer == "/..":
            input_buffer = "/"
            output_buffer = output_buffer.rsplit("/", 1)[0]
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            separator_index = input_buffer.find(
                "/",
                1 if input_buffer.startswith("/") else 0,
            )
            if separator_index < 0:
                output_buffer += input_buffer
                input_buffer = ""
            else:
                output_buffer += input_buffer[:separator_index]
                input_buffer = input_buffer[separator_index:]
    return output_buffer


def base_url_origin_changed(old_base_url: str, new_base_url: str) -> bool:
    def origin(base_url: str) -> tuple[str, str, int]:
        parsed = urlsplit(validate_enterprise_base_url(base_url))
        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port
        return (
            parsed.scheme,
            str(parsed.hostname or "").lower(),
            default_port if port is None else port,
        )

    return origin(old_base_url) != origin(new_base_url)


async def lock_enterprise_auth_accounts(
    db: Any,
    account_ids: Iterable[int],
) -> list[EnterpriseAuthAccount]:
    """Lock enterprise accounts in the global account-id order."""
    normalized_ids = sorted({int(account_id) for account_id in account_ids})
    if not normalized_ids:
        return []
    result = await db.execute(
        select(EnterpriseAuthAccount)
        .where(EnterpriseAuthAccount.id.in_(normalized_ids))
        .order_by(EnterpriseAuthAccount.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    return list(result.scalars().all())


async def lock_enterprise_auth_bindings(
    db: Any,
    *,
    account_id: int | None = None,
    pairs: Iterable[tuple[int, int]] = (),
) -> list[EnterpriseAuthBinding]:
    """Lock related binding rows after account locks, in canonical pair order."""
    conditions = []
    if account_id is not None:
        normalized_account_id = int(account_id)
        conditions.append(
            or_(
                EnterpriseAuthBinding.left_account_id == normalized_account_id,
                EnterpriseAuthBinding.right_account_id == normalized_account_id,
            )
        )
    for first_id, second_id in sorted(
        {
            tuple(sorted((int(first_id), int(second_id))))
            for first_id, second_id in pairs
        }
    ):
        conditions.append(
            and_(
                EnterpriseAuthBinding.left_account_id == first_id,
                EnterpriseAuthBinding.right_account_id == second_id,
            )
        )
    if not conditions:
        return []
    result = await db.execute(
        select(EnterpriseAuthBinding)
        .where(or_(*conditions))
        .order_by(
            EnterpriseAuthBinding.left_account_id.asc(),
            EnterpriseAuthBinding.right_account_id.asc(),
        )
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    return list(result.scalars().all())


async def lock_enterprise_auth_account_graph(
    db: Any,
    account_id: int,
) -> LockedAccountGraph:
    normalized_account_id = int(account_id)
    for attempt in range(_ACCOUNT_GRAPH_LOCK_MAX_ATTEMPTS):
        related_pairs = (
            await db.execute(
                select(
                    EnterpriseAuthBinding.left_account_id,
                    EnterpriseAuthBinding.right_account_id,
                )
                .where(
                    or_(
                        EnterpriseAuthBinding.left_account_id
                        == normalized_account_id,
                        EnterpriseAuthBinding.right_account_id
                        == normalized_account_id,
                    )
                )
                .order_by(
                    EnterpriseAuthBinding.left_account_id.asc(),
                    EnterpriseAuthBinding.right_account_id.asc(),
                )
            )
        ).all()
        discovered_account_ids = {normalized_account_id}
        for left_account_id, right_account_id in related_pairs:
            discovered_account_ids.update((left_account_id, right_account_id))

        locked_accounts = await lock_enterprise_auth_accounts(
            db,
            discovered_account_ids,
        )
        locked_bindings = await lock_enterprise_auth_bindings(
            db,
            account_id=normalized_account_id,
        )
        locked_endpoint_ids = {
            endpoint_id
            for binding in locked_bindings
            for endpoint_id in (
                binding.left_account_id,
                binding.right_account_id,
            )
        }
        accounts_by_id = {account.id: account for account in locked_accounts}
        if normalized_account_id not in accounts_by_id:
            return LockedAccountGraph(
                account=None,
                accounts_by_id=accounts_by_id,
                bindings=list(locked_bindings),
            )
        endpoint_drifted = bool(
            locked_endpoint_ids - discovered_account_ids
            or discovered_account_ids - set(accounts_by_id)
        )
        if endpoint_drifted:
            await db.rollback()
            if attempt + 1 < _ACCOUNT_GRAPH_LOCK_MAX_ATTEMPTS:
                continue
            raise EnterpriseAuthError(
                ENTERPRISE_AUTH_ACCOUNT_INVALID,
                "Enterprise account bindings changed concurrently",
            )
        return LockedAccountGraph(
            account=accounts_by_id.get(normalized_account_id),
            accounts_by_id=accounts_by_id,
            bindings=list(locked_bindings),
        )
    raise EnterpriseAuthError(
        ENTERPRISE_AUTH_ACCOUNT_INVALID,
        "Enterprise account bindings changed concurrently",
    )


def enterprise_auth_credential_fingerprint(account: Any) -> str:
    credential_values = [
        str(account.provider),
        str(account.base_url),
        str(account.tenant_ref),
        str(account.account),
        str(account.password_enc or ""),
    ]
    serialized = json.dumps(
        credential_values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def snapshot_enterprise_auth_credentials(
    account: Any,
) -> EnterpriseAuthCredentialSnapshot:
    return EnterpriseAuthCredentialSnapshot(
        id=int(account.id),
        provider=str(account.provider),
        base_url=str(account.base_url),
        tenant_ref=str(account.tenant_ref),
        account=str(account.account),
        password_enc=account.password_enc,
        credential_fingerprint=enterprise_auth_credential_fingerprint(account),
    )


def _sqlite_database_is_locked(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower()


async def claim_enterprise_auth_generation(
    db: Any,
    account_id: int,
) -> EnterpriseAuthGenerationClaim | None:
    normalized_account_id = int(account_id)
    if not await _rollback(db):
        raise RuntimeError("enterprise auth generation claim rollback failed")
    for attempt in range(_AUTH_GENERATION_CLAIM_MAX_ATTEMPTS):
        try:
            result = await db.execute(
                update(EnterpriseAuthAccount)
                .where(
                    EnterpriseAuthAccount.id == normalized_account_id,
                    EnterpriseAuthAccount.status != STATUS_DISABLED,
                )
                .values(
                    auth_generation=EnterpriseAuthAccount.auth_generation + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                await db.rollback()
                return None
            account = (
                await db.execute(
                    select(EnterpriseAuthAccount)
                    .where(EnterpriseAuthAccount.id == normalized_account_id)
                    .execution_options(
                        populate_existing=True,
                        autoflush=False,
                    )
                )
            ).scalar_one_or_none()
            if account is None or account.status == STATUS_DISABLED:
                await db.rollback()
                return None
            credentials = snapshot_enterprise_auth_credentials(account)
            claim = EnterpriseAuthGenerationClaim(
                account_id=normalized_account_id,
                generation=int(account.auth_generation),
                credential_fingerprint=credentials.credential_fingerprint,
                credentials=credentials,
            )
            await db.commit()
            return claim
        except OperationalError as exc:
            await _rollback(db)
            if (
                _sqlite_database_is_locked(exc)
                and attempt + 1 < _AUTH_GENERATION_CLAIM_MAX_ATTEMPTS
            ):
                await asyncio.sleep(
                    _AUTH_GENERATION_CLAIM_RETRY_DELAY_SECONDS
                    * (attempt + 1)
                )
                continue
            raise
        except Exception:
            await _rollback(db)
            raise
    return None


def _claim_matches_account(
    claim: EnterpriseAuthGenerationClaim,
    account: Any,
) -> bool:
    return bool(
        account is not None
        and int(account.id) == claim.account_id
        and account.status != STATUS_DISABLED
        and int(account.auth_generation) == claim.generation
        and enterprise_auth_credential_fingerprint(account)
        == claim.credential_fingerprint
    )


def _claim_credential_conditions(
    claim: EnterpriseAuthGenerationClaim,
) -> tuple[Any, ...]:
    credentials = claim.credentials
    return (
        EnterpriseAuthAccount.id == claim.account_id,
        EnterpriseAuthAccount.status != STATUS_DISABLED,
        EnterpriseAuthAccount.auth_generation == claim.generation,
        EnterpriseAuthAccount.provider == credentials.provider,
        EnterpriseAuthAccount.base_url == credentials.base_url,
        EnterpriseAuthAccount.tenant_ref == credentials.tenant_ref,
        EnterpriseAuthAccount.account == credentials.account,
        EnterpriseAuthAccount.password_enc == credentials.password_enc,
    )


async def persist_enterprise_auth_claim_result(
    db: Any,
    claim: EnterpriseAuthGenerationClaim,
    *,
    authenticated: EnterpriseAuthCredentialSnapshot | None = None,
    error_message: str | None = None,
) -> Any | None:
    if (authenticated is None) == (error_message is None):
        raise ValueError("exactly one enterprise auth result is required")
    if authenticated is not None:
        values = {
            "access_token_enc": authenticated.access_token_enc,
            "refresh_token_enc": authenticated.refresh_token_enc,
            "token_expires_at": authenticated.token_expires_at,
            "status": authenticated.status,
            "last_verified_at": authenticated.last_verified_at,
            "last_error": authenticated.last_error,
        }
    else:
        values = {
            "status": STATUS_ERROR,
            "last_error": str(error_message),
        }
    result = await db.execute(
        update(EnterpriseAuthAccount)
        .where(*_claim_credential_conditions(claim))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        return None
    await db.commit()
    account = await db.get(EnterpriseAuthAccount, claim.account_id)
    if account is not None:
        await db.refresh(account)
    return account


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

    attempts = _LOCKED_BINDING_RESOLUTION_MAX_ATTEMPTS if lock else 1
    for attempt in range(attempts):
        source = (
            await db.execute(source_statement)
        ).scalar_one_or_none()
        if source is None:
            return BindingResolution(
                account=None,
                code=ENTERPRISE_AUTH_BINDING_NOT_FOUND,
                message="Enterprise account binding not found",
            )

        if not lock:
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
                    EnterpriseAuthAccount.provider
                    == normalized_target_provider,
                    EnterpriseAuthAccount.status != STATUS_DISABLED,
                )
                .order_by(EnterpriseAuthBinding.priority.asc())
            )
            rows = (await db.execute(target_statement)).all()
            break

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
        locked_endpoint_ids = {
            account_id
            for binding in locked_bindings
            for account_id in (
                binding.left_account_id,
                binding.right_account_id,
            )
        }
        if locked_endpoint_ids - related_account_ids:
            await db.rollback()
            if attempt + 1 < attempts:
                continue
            return BindingResolution(
                account=None,
                code=ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
                message="Enterprise account binding is unavailable",
            )

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
        break
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


async def resolve_provider_token_for_context(
    db: Any,
    ctx: Any,
    target_provider: str,
) -> str | None:
    resolution = await resolve_provider_token_resolution_for_context(
        db,
        ctx,
        target_provider,
    )
    return resolution.token


def _provider_token_unavailable(
    *,
    base_url: str | None = None,
    message: str = "Enterprise account binding is unavailable",
) -> ProviderTokenResolution:
    return ProviderTokenResolution(
        token=None,
        base_url=base_url,
        code=ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
        message=message,
    )


def _provider_token_not_found(
    message: str = "Enterprise account binding not found",
) -> ProviderTokenResolution:
    return ProviderTokenResolution(
        token=None,
        base_url=None,
        code=ENTERPRISE_AUTH_BINDING_NOT_FOUND,
        message=message,
    )


def _validate_provider_token_base_url(
    token: str,
    token_base_url: str,
    expected_base_url: str | None,
) -> ProviderTokenResolution:
    try:
        normalized_token_base_url = validate_enterprise_base_url(token_base_url)
        normalized_expected_base_url = (
            validate_enterprise_base_url(expected_base_url)
            if expected_base_url is not None
            else None
        )
    except Exception:
        return _provider_token_unavailable(
            message="Control Plane token 签发地址无效",
        )
    if (
        normalized_expected_base_url is not None
        and normalized_token_base_url != normalized_expected_base_url
    ):
        return _provider_token_unavailable(
            base_url=normalized_token_base_url,
            message="Control Plane token 签发地址与当前服务地址不一致",
        )
    return ProviderTokenResolution(
        token=token,
        base_url=normalized_token_base_url,
        code=OK,
        message="Control Plane token resolved",
    )


async def resolve_provider_token_resolution_for_context(
    db: Any,
    ctx: Any,
    target_provider: str,
    *,
    expected_base_url: str | None = None,
) -> ProviderTokenResolution:
    try:
        normalized_target_provider = normalize_provider(target_provider)
        if normalized_target_provider != PROVIDER_CONTROL_PLANE:
            return _provider_token_not_found()

        user = getattr(ctx, "user", None)
        account_source = str(
            getattr(user, "account_source", "") or ""
        ).strip().lower()
        if account_source == "coding":
            token = str(
                getattr(user, "coding_access_token", "") or ""
            ).strip()
            if not token:
                return _provider_token_not_found(
                    "Control Plane login token not found",
                )
            token_base_url = str(
                getattr(user, "coding_base_url", "") or ""
            ).strip()
            if not token_base_url:
                return _provider_token_unavailable(
                    message="Control Plane token 签发地址不可用",
                )
            return _validate_provider_token_base_url(
                token,
                token_base_url,
                expected_base_url,
            )

        if (
            account_source != PROVIDER_APAAS
            or not settings.auth_account_binding_enabled
        ):
            return _provider_token_not_found()

        local_tenant_id = getattr(ctx, "tenant_id", None)
        credential = None
        if getattr(user, "id", None) and local_tenant_id:
            credential = (
                await db.execute(
                    select(APaaSUserCredential).where(
                        APaaSUserCredential.user_id == int(user.id),
                        APaaSUserCredential.local_tenant_id
                        == int(local_tenant_id),
                    )
                )
            ).scalar_one_or_none()

        source_base_url = str(
            getattr(credential, "base_url", None)
            or getattr(user, "apaas_base_url", None)
            or settings.apaas_base_url
            or ""
        ).strip()
        source_tenant_ref = str(
            getattr(credential, "apaas_tenant_id", None)
            or getattr(ctx, "apaas_tenant_id", None)
            or getattr(user, "apaas_tenant_id", None)
            or ""
        ).strip()
        if not source_tenant_ref:
            if local_tenant_id:
                source_tenant_ref = str(
                    (
                        await db.execute(
                            select(Tenant.apaas_tenant_id_str).where(
                                Tenant.id == int(local_tenant_id)
                            )
                        )
                    ).scalar_one_or_none()
                    or ""
                ).strip()
        source_account = str(
            getattr(credential, "account", None)
            or getattr(user, "username", "")
            or ""
        ).strip()
        if not source_base_url or not source_tenant_ref or not source_account:
            return _provider_token_not_found()

        resolution = await resolve_bound_account(
            db,
            PROVIDER_APAAS,
            source_base_url,
            source_tenant_ref,
            source_account,
            normalized_target_provider,
        )
        if resolution.code != OK or resolution.account is None:
            return ProviderTokenResolution(
                token=None,
                base_url=None,
                code=resolution.code,
                message=resolution.message,
            )
        target_base_url = str(
            getattr(resolution.account, "base_url", "") or ""
        ).strip()
        try:
            token = str(read_access_token(resolution.account) or "").strip()
        except Exception:
            return _provider_token_unavailable(
                base_url=target_base_url or None,
            )
        if not token:
            return _provider_token_unavailable(
                base_url=target_base_url or None,
            )
        return _validate_provider_token_base_url(
            token,
            target_base_url,
            expected_base_url,
        )
    except Exception:
        await _rollback(db)
        return _provider_token_unavailable()


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

    try:
        claim = await claim_enterprise_auth_generation(
            db,
            resolution.account.id,
        )
    except Exception:
        await _rollback(db)
        return _binding_unavailable()
    if claim is None:
        return _binding_unavailable()

    try:
        authenticated = await authenticate_enterprise_account(
            claim.credentials
        )
        authentication_failed = False
    except Exception:
        authenticated = None
        authentication_failed = True

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
        if (
            revalidated.account is None
            or not _claim_matches_account(claim, revalidated.account)
        ):
            await _rollback(db)
            return _binding_unavailable()
    except Exception:
        await _rollback(db)
        return _binding_unavailable()

    if authentication_failed:
        try:
            failed_account = await persist_enterprise_auth_claim_result(
                db,
                claim,
                error_message="Enterprise account authentication failed",
            )
        except Exception:
            await _rollback(db)
            return _binding_unavailable()
        return _binding_unavailable(failed_account)

    try:
        persisted_account = await persist_enterprise_auth_claim_result(
            db,
            claim,
            authenticated=authenticated,
        )
        if persisted_account is None:
            return _binding_unavailable()
        return BindingResolution(
            account=persisted_account,
            code=OK,
            message="Enterprise account binding refreshed",
        )
    except Exception:
        await _rollback(db)
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
            if (
                revalidated.account is None
                or not _claim_matches_account(claim, revalidated.account)
            ):
                await _rollback(db)
                return _binding_unavailable()
            failed_account = await persist_enterprise_auth_claim_result(
                db,
                claim,
                error_message=(
                    "Enterprise account credential persistence failed"
                ),
            )
            return _binding_unavailable(failed_account)
        except Exception:
            await _rollback(db)
            return _binding_unavailable()
