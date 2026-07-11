from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.config import settings
from app.database import get_db
from app.deps import AuthContext, get_auth_context, require_platform_admin
from app.models import EnterpriseAuthAccount, EnterpriseAuthBinding
from app.services.enterprise_auth import (
    ENTERPRISE_AUTH_ACCOUNT_INVALID,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_UNVERIFIED,
    EnterpriseAuthError,
    authenticate_enterprise_account,
    base_url_origin_changed,
    claim_enterprise_auth_generation,
    lock_enterprise_auth_account_graph,
    lock_enterprise_auth_accounts,
    lock_enterprise_auth_bindings,
    normalize_provider,
    persist_enterprise_auth_claim_result,
    set_account_password,
    validate_enterprise_base_url,
)


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
ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND = "ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND"
ENTERPRISE_AUTH_ACCOUNT_DUPLICATE = "ENTERPRISE_AUTH_ACCOUNT_DUPLICATE"
ENTERPRISE_AUTH_ACCOUNT_CHANGED = "ENTERPRISE_AUTH_ACCOUNT_CHANGED"
ENTERPRISE_AUTH_BINDING_NOT_FOUND = "ENTERPRISE_AUTH_BINDING_NOT_FOUND"
ENTERPRISE_AUTH_BINDING_DUPLICATE = "ENTERPRISE_AUTH_BINDING_DUPLICATE"
ENTERPRISE_AUTH_BINDING_CHANGED = "ENTERPRISE_AUTH_BINDING_CHANGED"
ENTERPRISE_AUTH_AUTHENTICATION_REQUIRED = (
    "ENTERPRISE_AUTH_AUTHENTICATION_REQUIRED"
)
ENTERPRISE_AUTH_VALIDATION_ERROR = "ENTERPRISE_AUTH_VALIDATION_ERROR"
_BINDING_WRITE_LOCK_MAX_ATTEMPTS = 2


class EnterpriseAuthValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class EnterpriseAuthErrorResponse(BaseModel):
    code: str
    message: str
    errors: list[EnterpriseAuthValidationIssue] | None = None


class EnterpriseAuthAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


ENTERPRISE_AUTH_ERROR_RESPONSES = {
    error_status: {
        "model": EnterpriseAuthErrorResponse,
        "description": "Enterprise authentication administration error",
    }
    for error_status in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
}

router = APIRouter(
    prefix="/enterprise-auth",
    tags=["enterprise-auth"],
    responses=ENTERPRISE_AUTH_ERROR_RESPONSES,
)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnterpriseAuthAccountCreate(StrictInput):
    provider: Provider
    base_url: BaseUrl
    tenant_ref: TenantRef
    tenant_name: TenantName | None = None
    account: AccountName
    password: SecretStr
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

    @field_validator("password", mode="before")
    @classmethod
    def _preserve_password(cls, value: object) -> object:
        return SecretStr(value) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: SecretStr) -> SecretStr:
        raw_password = value.get_secret_value()
        if not 1 <= len(raw_password) <= 4096 or not raw_password.strip():
            raise ValueError("password must be non-empty and at most 4096 characters")
        return value


class EnterpriseAuthAccountUpdate(StrictInput):
    provider: Provider | None = None
    base_url: BaseUrl | None = None
    tenant_ref: TenantRef | None = None
    tenant_name: TenantName | None = None
    account: AccountName | None = None
    password: SecretStr | None = None
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

    @field_validator("password", mode="before")
    @classmethod
    def _preserve_password(cls, value: object) -> object:
        return SecretStr(value) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw_password = value.get_secret_value()
        if not 1 <= len(raw_password) <= 4096 or not raw_password.strip():
            raise ValueError("password must be non-empty and at most 4096 characters")
        return value


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


def _api_error(
    status_code: int,
    code: str,
    message: str,
) -> EnterpriseAuthAPIError:
    return EnterpriseAuthAPIError(status_code, code, message)


async def require_enterprise_auth_admin(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    try:
        return await require_platform_admin(ctx)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        raise _api_error(
            status.HTTP_403_FORBIDDEN,
            "ENTERPRISE_AUTH_ADMIN_REQUIRED",
            "需要平台管理员权限",
        ) from None


async def enterprise_auth_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    if not _is_enterprise_auth_path(request.url.path):
        return await request_validation_exception_handler(request, exc)
    errors = [
        {
            key: error[key]
            for key in ("loc", "msg", "type")
            if key in error
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": ENTERPRISE_AUTH_VALIDATION_ERROR,
            "message": "请求参数校验失败",
            "errors": errors,
        },
    )


async def enterprise_auth_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if not _is_enterprise_auth_path(request.url.path):
        return await http_exception_handler(request, exc)

    detail = str(exc.detail or "")
    missing_credentials = (
        exc.status_code == status.HTTP_401_UNAUTHORIZED
        or (
            exc.status_code == status.HTTP_403_FORBIDDEN
            and detail
            in {
                "Not authenticated",
                "Invalid authentication credentials",
            }
        )
    )
    if missing_credentials:
        code = ENTERPRISE_AUTH_AUTHENTICATION_REQUIRED
        message = "需要有效的认证凭证"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "ENTERPRISE_AUTH_ADMIN_REQUIRED"
        message = "需要平台管理员权限"
    else:
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message},
        headers=exc.headers,
    )


async def enterprise_auth_api_exception_handler(
    _request: Request,
    exc: EnterpriseAuthAPIError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


def _is_enterprise_auth_path(path: str) -> bool:
    return (
        path == "/enterprise-auth"
        or path.startswith("/enterprise-auth/")
        or path == "/api/enterprise-auth"
        or path.startswith("/api/enterprise-auth/")
    )


def _account_not_found() -> EnterpriseAuthAPIError:
    return _api_error(
        status.HTTP_404_NOT_FOUND,
        ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND,
        "企业认证账号不存在",
    )


def _binding_not_found() -> EnterpriseAuthAPIError:
    return _api_error(
        status.HTTP_404_NOT_FOUND,
        ENTERPRISE_AUTH_BINDING_NOT_FOUND,
        "企业认证绑定不存在",
    )


def _account_changed() -> EnterpriseAuthAPIError:
    return _api_error(
        status.HTTP_409_CONFLICT,
        ENTERPRISE_AUTH_ACCOUNT_CHANGED,
        "企业认证账号凭据发生并发变化",
    )


def _binding_changed() -> EnterpriseAuthAPIError:
    return _api_error(
        status.HTTP_409_CONFLICT,
        ENTERPRISE_AUTH_BINDING_CHANGED,
        "企业认证绑定发生并发变化",
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


async def _lock_binding_for_write(
    db: AsyncSession,
    binding_id: int,
    *,
    requested_left_id: int | None = None,
    requested_right_id: int | None = None,
) -> tuple[
    EnterpriseAuthBinding,
    dict[int, EnterpriseAuthAccount],
    list[EnterpriseAuthBinding],
    int,
    int,
]:
    for attempt in range(_BINDING_WRITE_LOCK_MAX_ATTEMPTS):
        current = (
            await db.execute(
                select(EnterpriseAuthBinding)
                .where(EnterpriseAuthBinding.id == binding_id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one_or_none()
        if current is None:
            raise _binding_not_found()

        current_pair = (
            current.left_account_id,
            current.right_account_id,
        )
        desired_pair = tuple(
            sorted(
                (
                    requested_left_id
                    if requested_left_id is not None
                    else current_pair[0],
                    requested_right_id
                    if requested_right_id is not None
                    else current_pair[1],
                )
            )
        )
        left_id, right_id = desired_pair
        if left_id == right_id:
            raise _api_error(
                status.HTTP_400_BAD_REQUEST,
                ENTERPRISE_AUTH_ACCOUNT_INVALID,
                "绑定两侧不能是同一账号",
            )

        account_ids = {*current_pair, *desired_pair}
        locked_accounts = await lock_enterprise_auth_accounts(db, account_ids)
        accounts_by_id = _accounts_by_id(locked_accounts, account_ids)
        locked_bindings = await lock_enterprise_auth_bindings(
            db,
            pairs=[current_pair, desired_pair],
        )
        binding = next(
            (item for item in locked_bindings if item.id == binding_id),
            None,
        )
        if binding is not None:
            return binding, accounts_by_id, locked_bindings, left_id, right_id

        await db.rollback()
        latest = (
            await db.execute(
                select(EnterpriseAuthBinding)
                .where(EnterpriseAuthBinding.id == binding_id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one_or_none()
        if latest is None:
            raise _binding_not_found()
        await db.rollback()
        if attempt + 1 >= _BINDING_WRITE_LOCK_MAX_ATTEMPTS:
            raise _binding_changed()
    raise _binding_changed()


@router.get("/status", response_model=EnterpriseAuthStatusView)
async def get_enterprise_auth_status(
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
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
    set_account_password(account, data.password.get_secret_value())
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthAccountView:
    try:
        graph = await lock_enterprise_auth_account_graph(db, account_id)
    except EnterpriseAuthError:
        raise _account_changed() from None
    account = graph.account
    if account is None:
        raise _account_not_found()

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
    if provider != account.provider:
        for binding in graph.bindings:
            other_account_id = (
                binding.right_account_id
                if binding.left_account_id == account_id
                else binding.left_account_id
            )
            other_account = graph.accounts_by_id.get(other_account_id)
            if other_account is None or other_account.provider == provider:
                raise _api_error(
                    status.HTTP_400_BAD_REQUEST,
                    ENTERPRISE_AUTH_ACCOUNT_INVALID,
                    "修改认证源会使已有绑定两侧认证源相同",
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
        set_account_password(account, data.password.get_secret_value())

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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthAccountView:
    try:
        claim = await claim_enterprise_auth_generation(db, account_id)
    except Exception:
        raise _account_changed() from None
    if claim is None:
        account = await db.get(EnterpriseAuthAccount, account_id)
        if account is None:
            raise _account_not_found()
        if account.status == STATUS_DISABLED:
            raise _api_error(
                status.HTTP_400_BAD_REQUEST,
                ENTERPRISE_AUTH_ACCOUNT_INVALID,
                "企业认证账号已禁用",
            )
        raise _account_changed()

    authentication_failed = False
    try:
        tested_credentials = await authenticate_enterprise_account(
            claim.credentials
        )
    except Exception:
        authentication_failed = True
        tested_credentials = None

    if authentication_failed:
        try:
            current = await persist_enterprise_auth_claim_result(
                db,
                claim,
                error_message="企业认证账号验证失败",
            )
        except Exception:
            await db.rollback()
            raise _account_changed() from None
        if current is None:
            raise _account_changed()
        raise _api_error(
            status.HTTP_400_BAD_REQUEST,
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "企业认证账号验证失败",
        ) from None

    try:
        current = await persist_enterprise_auth_claim_result(
            db,
            claim,
            authenticated=tested_credentials,
        )
    except Exception:
        await db.rollback()
        raise _account_changed() from None
    if current is None:
        raise _account_changed()
    return _account_view(current)


@router.get("/bindings", response_model=list[EnterpriseAuthBindingView])
async def list_enterprise_auth_bindings(
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseAuthBindingView:
    (
        binding,
        accounts_by_id,
        locked_bindings,
        left_id,
        right_id,
    ) = await _lock_binding_for_write(
        db,
        binding_id,
        requested_left_id=data.left_account_id,
        requested_right_id=data.right_account_id,
    )
    _validate_binding_accounts(left_id, right_id, accounts_by_id)
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
    ctx: Annotated[AuthContext, Depends(require_enterprise_auth_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool | int]:
    binding, _accounts_by_id_map, _bindings, _left_id, _right_id = (
        await _lock_binding_for_write(
            db,
            binding_id,
        )
    )
    await db.delete(binding)
    await db.commit()
    return {"ok": True, "deleted_id": binding_id}
