from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import AuthContext, require_platform_admin
from app.models import EnterpriseAuthAccount, EnterpriseAuthBinding
from app.services.enterprise_auth import (
    ENTERPRISE_AUTH_ACCOUNT_INVALID,
    STATUS_DISABLED,
    STATUS_UNVERIFIED,
    EnterpriseAuthError,
    _record_account_auth_failure,
    authenticate_enterprise_account,
    base_url_origin_changed,
    lock_enterprise_auth_accounts,
    lock_enterprise_auth_bindings,
    normalize_provider,
    set_account_password,
    validate_enterprise_base_url,
)


router = APIRouter(prefix="/enterprise-auth", tags=["enterprise-auth"])

Provider = Literal["apaas", "control_plane"]
BaseUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
TenantRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
TenantName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=255),
]
AccountName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
Password = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
]

ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND = "ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND"
ENTERPRISE_AUTH_ACCOUNT_DUPLICATE = "ENTERPRISE_AUTH_ACCOUNT_DUPLICATE"
ENTERPRISE_AUTH_BINDING_NOT_FOUND = "ENTERPRISE_AUTH_BINDING_NOT_FOUND"
ENTERPRISE_AUTH_BINDING_DUPLICATE = "ENTERPRISE_AUTH_BINDING_DUPLICATE"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnterpriseAuthAccountCreate(StrictInput):
    provider: Provider
    base_url: BaseUrl
    tenant_ref: TenantRef
    tenant_name: TenantName | None = None
    account: AccountName
    password: Password
    enabled: bool = True

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"apaas", "control_plane"}:
            raise ValueError("provider must be apaas or control_plane")
        return normalize_provider(normalized)

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        try:
            return validate_enterprise_base_url(value)
        except EnterpriseAuthError as exc:
            raise ValueError(exc.message) from None

    @field_validator("tenant_name")
    @classmethod
    def _normalize_tenant_name(cls, value: str | None) -> str | None:
        return value or None


class EnterpriseAuthAccountUpdate(StrictInput):
    provider: Provider | None = None
    base_url: BaseUrl | None = None
    tenant_ref: TenantRef | None = None
    tenant_name: TenantName | None = None
    account: AccountName | None = None
    password: Password | None = None
    enabled: bool | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in {"apaas", "control_plane"}:
            raise ValueError("provider must be apaas or control_plane")
        return normalize_provider(normalized)

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_enterprise_base_url(value)
        except EnterpriseAuthError as exc:
            raise ValueError(exc.message) from None

    @field_validator("tenant_name")
    @classmethod
    def _normalize_tenant_name(cls, value: str | None) -> str | None:
        return value or None


class EnterpriseAuthBindingCreate(StrictInput):
    left_account_id: int = Field(gt=0)
    right_account_id: int = Field(gt=0)
    priority: int = Field(default=100, ge=0)
    enabled: bool = True


class EnterpriseAuthBindingUpdate(StrictInput):
    left_account_id: int | None = Field(default=None, gt=0)
    right_account_id: int | None = Field(default=None, gt=0)
    priority: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


class EnterpriseAuthAccountView(BaseModel):
    id: int
    provider: Provider
    base_url: str
    tenant_ref: str
    tenant_name: str | None
    account: str
    has_password: bool
    has_access_token: bool
    status: str
    last_verified_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class EnterpriseAuthAccountSummary(BaseModel):
    id: int
    provider: Provider
    base_url: str
    tenant_ref: str
    tenant_name: str | None
    account: str
    status: str


class EnterpriseAuthBindingView(BaseModel):
    id: int
    left_account_id: int
    right_account_id: int
    priority: int
    enabled: bool
    left_account: EnterpriseAuthAccountSummary
    right_account: EnterpriseAuthAccountSummary
    created_at: datetime
    updated_at: datetime


class EnterpriseAuthStatusView(BaseModel):
    auth_provider: str
    binding_enabled: bool


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _account_not_found() -> HTTPException:
    return _api_error(
        status.HTTP_404_NOT_FOUND,
        ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND,
        "企业认证账号不存在",
    )


def _binding_not_found() -> HTTPException:
    return _api_error(
        status.HTTP_404_NOT_FOUND,
        ENTERPRISE_AUTH_BINDING_NOT_FOUND,
        "企业认证绑定不存在",
    )


def _account_view(account: EnterpriseAuthAccount) -> EnterpriseAuthAccountView:
    return EnterpriseAuthAccountView(
        id=account.id,
        provider=account.provider,
        base_url=account.base_url,
        tenant_ref=account.tenant_ref,
        tenant_name=account.tenant_name,
        account=account.account,
        has_password=bool(account.password_enc),
        has_access_token=bool(account.access_token_enc),
        status=account.status,
        last_verified_at=account.last_verified_at,
        last_error=account.last_error,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _account_summary(
    account: EnterpriseAuthAccount,
) -> EnterpriseAuthAccountSummary:
    return EnterpriseAuthAccountSummary(
        id=account.id,
        provider=account.provider,
        base_url=account.base_url,
        tenant_ref=account.tenant_ref,
        tenant_name=account.tenant_name,
        account=account.account,
        status=account.status,
    )


def _binding_view(
    binding: EnterpriseAuthBinding,
    accounts_by_id: dict[int, EnterpriseAuthAccount],
) -> EnterpriseAuthBindingView:
    left = accounts_by_id.get(binding.left_account_id)
    right = accounts_by_id.get(binding.right_account_id)
    if left is None or right is None:
        raise _account_not_found()
    return EnterpriseAuthBindingView(
        id=binding.id,
        left_account_id=binding.left_account_id,
        right_account_id=binding.right_account_id,
        priority=binding.priority,
        enabled=binding.enabled,
        left_account=_account_summary(left),
        right_account=_account_summary(right),
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


async def _lock_account(
    db: AsyncSession,
    account_id: int,
) -> EnterpriseAuthAccount:
    accounts = await lock_enterprise_auth_accounts(db, [account_id])
    if not accounts:
        raise _account_not_found()
    return accounts[0]


def _accounts_by_id(
    accounts: list[EnterpriseAuthAccount],
    expected_ids: set[int],
) -> dict[int, EnterpriseAuthAccount]:
    accounts_by_id = {account.id: account for account in accounts}
    if set(accounts_by_id) != expected_ids:
        raise _account_not_found()
    return accounts_by_id


def _validate_binding_accounts(
    left_id: int,
    right_id: int,
    accounts_by_id: dict[int, EnterpriseAuthAccount],
) -> None:
    if left_id == right_id:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "绑定两侧不能是同一账号",
        )
    if accounts_by_id[left_id].provider == accounts_by_id[right_id].provider:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "绑定两侧必须来自不同认证源",
        )


async def _load_binding_accounts(
    db: AsyncSession,
    bindings: list[EnterpriseAuthBinding],
) -> dict[int, EnterpriseAuthAccount]:
    account_ids = sorted(
        {
            account_id
            for binding in bindings
            for account_id in (
                binding.left_account_id,
                binding.right_account_id,
            )
        }
    )
    if not account_ids:
        return {}
    accounts = (
        await db.execute(
            select(EnterpriseAuthAccount)
            .where(EnterpriseAuthAccount.id.in_(account_ids))
            .order_by(EnterpriseAuthAccount.id.asc())
        )
    ).scalars().all()
    return {account.id: account for account in accounts}


@router.get("/status", response_model=EnterpriseAuthStatusView)
async def get_enterprise_auth_status(
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
) -> EnterpriseAuthStatusView:
    provider = str(settings.auth_provider or "").strip().lower()
    if provider in {"apaas", "coding", "control_plane"}:
        provider = normalize_provider(provider)
    return EnterpriseAuthStatusView(
        auth_provider=provider,
        binding_enabled=bool(settings.auth_account_binding_enabled),
    )


@router.get("/accounts", response_model=list[EnterpriseAuthAccountView])
async def list_enterprise_auth_accounts(
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EnterpriseAuthAccountView]:
    accounts = (
        await db.execute(
            select(EnterpriseAuthAccount).order_by(EnterpriseAuthAccount.id.asc())
        )
    ).scalars().all()
    return [_account_view(account) for account in accounts]


@router.post(
    "/accounts",
    response_model=EnterpriseAuthAccountView,
    status_code=status.HTTP_201_CREATED,
)
async def create_enterprise_auth_account(
    data: EnterpriseAuthAccountCreate,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthAccountView:
    account = EnterpriseAuthAccount(
        provider=data.provider,
        base_url=data.base_url,
        tenant_ref=data.tenant_ref,
        tenant_name=data.tenant_name,
        account=data.account,
        status=STATUS_UNVERIFIED if data.enabled else STATUS_DISABLED,
        created_by=ctx.user.id,
    )
    set_account_password(account, data.password)
    db.add(account)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _api_error(
            status.HTTP_409_CONFLICT,
            ENTERPRISE_AUTH_ACCOUNT_DUPLICATE,
            "相同认证源、地址、租户和账号已存在",
        ) from None
    await db.refresh(account)
    return _account_view(account)


@router.put(
    "/accounts/{account_id}",
    response_model=EnterpriseAuthAccountView,
)
async def update_enterprise_auth_account(
    account_id: int,
    data: EnterpriseAuthAccountUpdate,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthAccountView:
    account = await _lock_account(db, account_id)
    await lock_enterprise_auth_bindings(db, account_id=account_id)

    provider = data.provider if data.provider is not None else account.provider
    base_url = data.base_url if data.base_url is not None else account.base_url
    tenant_ref = (
        data.tenant_ref if data.tenant_ref is not None else account.tenant_ref
    )
    account_name = data.account if data.account is not None else account.account
    identity_requires_password = (
        provider != account.provider
        or account_name != account.account
        or base_url_origin_changed(account.base_url, base_url)
    )
    if identity_requires_password and data.password is None:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "认证源、账号或地址来源变化时必须重新提供密码",
        )

    credentials_changed = (
        provider != account.provider
        or base_url != account.base_url
        or tenant_ref != account.tenant_ref
        or account_name != account.account
        or data.password is not None
    )
    was_disabled = account.status == STATUS_DISABLED

    account.provider = provider
    account.base_url = base_url
    account.tenant_ref = tenant_ref
    account.account = account_name
    if "tenant_name" in data.model_fields_set:
        account.tenant_name = data.tenant_name
    if data.password is not None:
        set_account_password(account, data.password)

    if credentials_changed:
        account.access_token_enc = None
        account.refresh_token_enc = None
        account.token_expires_at = None
        account.last_verified_at = None
        account.last_error = None

    remains_disabled = data.enabled is False or (
        data.enabled is None and was_disabled
    )
    if remains_disabled:
        account.status = STATUS_DISABLED
    elif credentials_changed or was_disabled:
        account.status = STATUS_UNVERIFIED

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _api_error(
            status.HTTP_409_CONFLICT,
            ENTERPRISE_AUTH_ACCOUNT_DUPLICATE,
            "相同认证源、地址、租户和账号已存在",
        ) from None
    await db.refresh(account)
    return _account_view(account)


@router.delete("/accounts/{account_id}")
async def delete_enterprise_auth_account(
    account_id: int,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool | int]:
    account = await _lock_account(db, account_id)
    await lock_enterprise_auth_bindings(db, account_id=account_id)
    await db.execute(
        delete(EnterpriseAuthBinding).where(
            (EnterpriseAuthBinding.left_account_id == account_id)
            | (EnterpriseAuthBinding.right_account_id == account_id)
        )
    )
    await db.delete(account)
    await db.commit()
    return {"ok": True, "deleted_id": account_id}


@router.post(
    "/accounts/{account_id}/test",
    response_model=EnterpriseAuthAccountView,
)
async def test_enterprise_auth_account(
    account_id: int,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthAccountView:
    account = await _lock_account(db, account_id)
    if account.status == STATUS_DISABLED:
        await db.rollback()
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "企业认证账号已禁用",
        )
    try:
        await authenticate_enterprise_account(account)
        await db.commit()
        await db.refresh(account)
        return _account_view(account)
    except Exception:
        await db.rollback()
        await _record_account_auth_failure(
            db,
            account_id,
            "企业认证账号验证失败",
        )
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "企业认证账号验证失败",
        ) from None


@router.get("/bindings", response_model=list[EnterpriseAuthBindingView])
async def list_enterprise_auth_bindings(
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EnterpriseAuthBindingView]:
    bindings = (
        await db.execute(
            select(EnterpriseAuthBinding).order_by(
                EnterpriseAuthBinding.priority.asc(),
                EnterpriseAuthBinding.left_account_id.asc(),
                EnterpriseAuthBinding.right_account_id.asc(),
            )
        )
    ).scalars().all()
    accounts_by_id = await _load_binding_accounts(db, list(bindings))
    return [_binding_view(binding, accounts_by_id) for binding in bindings]


@router.post(
    "/bindings",
    response_model=EnterpriseAuthBindingView,
    status_code=status.HTTP_201_CREATED,
)
async def create_enterprise_auth_binding(
    data: EnterpriseAuthBindingCreate,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthBindingView:
    left_id, right_id = sorted((data.left_account_id, data.right_account_id))
    if left_id == right_id:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "绑定两侧不能是同一账号",
        )
    locked_accounts = await lock_enterprise_auth_accounts(db, [left_id, right_id])
    accounts_by_id = _accounts_by_id(locked_accounts, {left_id, right_id})
    _validate_binding_accounts(left_id, right_id, accounts_by_id)
    existing = await lock_enterprise_auth_bindings(
        db,
        pairs=[(left_id, right_id)],
    )
    if existing:
        raise _api_error(
            status.HTTP_409_CONFLICT,
            ENTERPRISE_AUTH_BINDING_DUPLICATE,
            "相同账号对已存在绑定",
        )

    binding = EnterpriseAuthBinding(
        left_account_id=left_id,
        right_account_id=right_id,
        priority=data.priority,
        enabled=data.enabled,
        created_by=ctx.user.id,
    )
    db.add(binding)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _api_error(
            status.HTTP_409_CONFLICT,
            ENTERPRISE_AUTH_BINDING_DUPLICATE,
            "相同账号对已存在绑定",
        ) from None
    await db.refresh(binding)
    return _binding_view(binding, accounts_by_id)


@router.put(
    "/bindings/{binding_id}",
    response_model=EnterpriseAuthBindingView,
)
async def update_enterprise_auth_binding(
    binding_id: int,
    data: EnterpriseAuthBindingUpdate,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthBindingView:
    current = (
        await db.execute(
            select(EnterpriseAuthBinding).where(
                EnterpriseAuthBinding.id == binding_id
            )
        )
    ).scalar_one_or_none()
    if current is None:
        raise _binding_not_found()

    requested_left = (
        data.left_account_id
        if data.left_account_id is not None
        else current.left_account_id
    )
    requested_right = (
        data.right_account_id
        if data.right_account_id is not None
        else current.right_account_id
    )
    left_id, right_id = sorted((requested_left, requested_right))
    if left_id == right_id:
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "绑定两侧不能是同一账号",
        )

    account_ids = {
        current.left_account_id,
        current.right_account_id,
        left_id,
        right_id,
    }
    locked_accounts = await lock_enterprise_auth_accounts(db, account_ids)
    accounts_by_id = _accounts_by_id(locked_accounts, account_ids)
    _validate_binding_accounts(left_id, right_id, accounts_by_id)
    locked_bindings = await lock_enterprise_auth_bindings(
        db,
        pairs=[
            (current.left_account_id, current.right_account_id),
            (left_id, right_id),
        ],
    )
    binding = next(
        (item for item in locked_bindings if item.id == binding_id),
        None,
    )
    if binding is None:
        raise _binding_not_found()
    if any(
        item.id != binding_id
        and item.left_account_id == left_id
        and item.right_account_id == right_id
        for item in locked_bindings
    ):
        raise _api_error(
            status.HTTP_409_CONFLICT,
            ENTERPRISE_AUTH_BINDING_DUPLICATE,
            "相同账号对已存在绑定",
        )

    binding.left_account_id = left_id
    binding.right_account_id = right_id
    if data.priority is not None:
        binding.priority = data.priority
    if data.enabled is not None:
        binding.enabled = data.enabled
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _api_error(
            status.HTTP_409_CONFLICT,
            ENTERPRISE_AUTH_BINDING_DUPLICATE,
            "相同账号对已存在绑定",
        ) from None
    await db.refresh(binding)
    return _binding_view(binding, accounts_by_id)


@router.delete("/bindings/{binding_id}")
async def delete_enterprise_auth_binding(
    binding_id: int,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool | int]:
    current = (
        await db.execute(
            select(EnterpriseAuthBinding).where(
                EnterpriseAuthBinding.id == binding_id
            )
        )
    ).scalar_one_or_none()
    if current is None:
        raise _binding_not_found()
    pair = (current.left_account_id, current.right_account_id)
    locked_accounts = await lock_enterprise_auth_accounts(db, pair)
    _accounts_by_id(locked_accounts, set(pair))
    locked_bindings = await lock_enterprise_auth_bindings(db, pairs=[pair])
    binding = next(
        (item for item in locked_bindings if item.id == binding_id),
        None,
    )
    if binding is None:
        raise _binding_not_found()
    await db.delete(binding)
    await db.commit()
    return {"ok": True, "deleted_id": binding_id}
