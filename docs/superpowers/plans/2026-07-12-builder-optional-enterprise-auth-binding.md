# Builder Optional Enterprise Auth Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仅修改 Builder 的前提下，支持可配置的默认登录源，以及由平台管理员维护的 Control Plane/aPaaS 企业账号多对多绑定；绑定关闭或不可用时不阻断主登录。

**Architecture:** 认证适配器保持现状，新增 Builder 内部的企业账号、绑定和 token 解析服务。登录先完成默认认证，再以 best-effort 方式刷新绑定侧凭据；业务路由显式向 Control Plane 调用传入绑定 token，系统任务才允许使用全局 service token。

**Tech Stack:** FastAPI、SQLAlchemy Async、Pydantic Settings、Fernet、pytest、Vue 3、TypeScript、Element Plus、Vitest

---

## File Map

- `backend/app/config.py`: 声明默认认证源和可选绑定开关，保留 `coding` 兼容别名。
- `backend/app/models/enterprise_auth.py`: 企业账号和多对多绑定 ORM 模型。
- `backend/app/models/__init__.py`: 注册新模型。
- `backend/app/database.py`: 启动时确保新表进入 metadata。
- `backend/app/services/enterprise_auth.py`: 规范化、绑定解析、凭据加解密、连接测试和登录后 best-effort 刷新。
- `backend/app/routes/enterprise_auth.py`: 平台管理员 CRUD、测试连接和绑定接口。
- `backend/app/routes/auth/login.py`: 默认认证完成后调用可选绑定刷新，不改变主登录成败。
- `backend/app/routes/code_runtime.py`: 按当前登录上下文解析 Control Plane token。
- `backend/app/code_runtime/service.py`: 接受显式用户 token；全局 service token 仅在 `system_request=True` 时使用。
- `backend/app/main.py`: 注册企业认证管理路由。
- `backend/.env.example`: 添加两个有注释的可选配置项。
- `backend/tests/test_enterprise_auth_models.py`: 模型约束测试。
- `backend/tests/test_enterprise_auth_service.py`: 绑定选择、歧义和 best-effort 测试。
- `backend/tests/test_enterprise_auth_routes.py`: 平台管理员权限和 CRUD 测试。
- `backend/tests/test_auth_provider_modes.py`: `control_plane` 别名和登录不阻断测试。
- `backend/tests/test_code_runtime_service.py`: 用户 token 与 system service token 边界测试。
- `backend/tests/test_code_runtime_routes.py`: 路由显式注入绑定 token 测试。
- `frontend/src/api/enterpriseAuth.ts`: 管理接口类型和客户端。
- `frontend/src/components/platform/EnterpriseAuthBindingsPanel.vue`: 账号、连接测试和绑定管理界面。
- `frontend/src/views/PlatformTenants.vue`: 在平台管理中增加“认证绑定”页签。
- `frontend/src/components/platform/EnterpriseAuthBindingsPanel.spec.ts`: 关键交互测试。

### Task 1: 配置和数据模型

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/models/enterprise_auth.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_enterprise_auth_models.py`

- [ ] **Step 1: 写失败的配置和模型测试**

```python
from sqlalchemy import inspect as sa_inspect

from app.config import settings
from app.models.enterprise_auth import EnterpriseAuthAccount, EnterpriseAuthBinding


def test_enterprise_auth_binding_defaults_are_optional():
    assert settings.auth_account_binding_enabled is False


def test_enterprise_auth_models_register_required_columns():
    account_columns = {column.name for column in sa_inspect(EnterpriseAuthAccount).columns}
    binding_columns = {column.name for column in sa_inspect(EnterpriseAuthBinding).columns}

    assert {
        "provider", "base_url", "tenant_ref", "tenant_name", "account",
        "password_enc", "access_token_enc", "refresh_token_enc",
        "token_expires_at", "status", "last_verified_at", "last_error",
        "created_by", "created_at", "updated_at",
    }.issubset(account_columns)
    assert {
        "left_account_id", "right_account_id", "priority", "enabled",
        "created_by", "created_at", "updated_at",
    }.issubset(binding_columns)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd backend && pytest tests/test_enterprise_auth_models.py -q`

Expected: FAIL，提示 `auth_account_binding_enabled` 或 `app.models.enterprise_auth` 不存在。

- [ ] **Step 3: 实现配置和 ORM 模型**

在 `Settings` 中加入：

```python
    # Optional. Default login authority: "apaas" or "control_plane".
    # Legacy "coding" is accepted as an alias of "control_plane".
    auth_provider: str = ""
    # Optional. When false, Builder never queries enterprise account bindings.
    auth_account_binding_enabled: bool = False
```

创建两个模型，写入前将 URL 去尾斜杠、账号去首尾空格，并在服务层保证绑定 ID 按小到大保存：

```python
class EnterpriseAuthAccount(Base):
    __tablename__ = "enterprise_auth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider", "base_url", "tenant_ref", "account",
            name="uq_enterprise_auth_account_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account: Mapped[str] = mapped_column(String(200), nullable=False)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="unverified", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class EnterpriseAuthBinding(Base):
    __tablename__ = "enterprise_auth_bindings"
    __table_args__ = (
        UniqueConstraint(
            "left_account_id", "right_account_id",
            name="uq_enterprise_auth_binding_pair",
        ),
        CheckConstraint("left_account_id <> right_account_id", name="ck_enterprise_auth_binding_distinct"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    left_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enterprise_auth_accounts.id", ondelete="CASCADE"), nullable=False
    )
    right_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enterprise_auth_accounts.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
```

在 `app.models.__init__` 和 `init_db()` 中显式 import 新模型。

- [ ] **Step 4: 运行模型测试**

Run: `cd backend && pytest tests/test_enterprise_auth_models.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/app/models/enterprise_auth.py backend/app/models/__init__.py backend/app/database.py backend/tests/test_enterprise_auth_models.py
git commit -m "feat(auth): add enterprise binding models"
```

### Task 2: 绑定解析和凭据服务

**Files:**
- Create: `backend/app/services/enterprise_auth.py`
- Test: `backend/tests/test_enterprise_auth_service.py`

- [ ] **Step 1: 写失败的绑定选择测试**

```python
@pytest.mark.asyncio
async def test_resolve_target_account_selects_unique_first_priority(db_session):
    source, first, later = await seed_accounts(db_session)
    await seed_binding(db_session, source, first, priority=10)
    await seed_binding(db_session, source, later, priority=100)

    result = await resolve_bound_account(
        db_session,
        source_provider="apaas",
        source_base_url=source.base_url,
        source_tenant_ref=source.tenant_ref,
        source_account=source.account,
        target_provider="control_plane",
    )

    assert result.account.id == first.id
    assert result.code == "OK"


@pytest.mark.asyncio
async def test_resolve_target_account_rejects_equal_top_priority(db_session):
    source, first, second = await seed_accounts(db_session)
    await seed_binding(db_session, source, first, priority=10)
    await seed_binding(db_session, source, second, priority=10)

    result = await resolve_bound_account(
        db_session,
        source_provider="apaas",
        source_base_url=source.base_url,
        source_tenant_ref=source.tenant_ref,
        source_account=source.account,
        target_provider="control_plane",
    )

    assert result.account is None
    assert result.code == "ENTERPRISE_AUTH_BINDING_AMBIGUOUS"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd backend && pytest tests/test_enterprise_auth_service.py -q`

Expected: FAIL，提示 `resolve_bound_account` 不存在。

- [ ] **Step 3: 实现规范化、解析和 token 安全边界**

实现以下稳定接口：

```python
@dataclass
class BindingResolution:
    account: EnterpriseAuthAccount | None
    code: str
    message: str = ""


def normalize_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    return "control_plane" if provider == "coding" else provider


def normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


async def resolve_bound_account(
    db: AsyncSession,
    *,
    source_provider: str,
    source_base_url: str,
    source_tenant_ref: str,
    source_account: str,
    target_provider: str,
) -> BindingResolution:
    # 精确找到来源账号，再查询双向绑定。
    # 只保留 enabled 且目标 provider 匹配的账号。
    # priority 升序；最小 priority 对应多条账号时返回 AMBIGUOUS。
```

token 仅通过以下函数进出数据库：

```python
def set_account_tokens(
    account: EnterpriseAuthAccount,
    *,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    account.access_token_enc = encrypt_password(access_token)
    account.refresh_token_enc = encrypt_password(refresh_token) if refresh_token else None
    account.token_expires_at = expires_at
    account.status = "connected"
    account.last_verified_at = datetime.utcnow()
    account.last_error = None


def read_access_token(account: EnterpriseAuthAccount) -> str | None:
    return decrypt_password(account.access_token_enc) if account.access_token_enc else None
```

禁止 API 响应返回 `password_enc`、`access_token_enc`、`refresh_token_enc` 或解密后的值。

- [ ] **Step 4: 实现连接测试和登录后 best-effort 刷新**

服务提供可 monkeypatch 的 provider 登录函数：

```python
async def authenticate_enterprise_account(account: EnterpriseAuthAccount) -> None:
    password = decrypt_password(account.password_enc) if account.password_enc else ""
    if account.provider == "control_plane":
        identity = await login_to_coding_control_plane(account.account, password)
        set_account_tokens(
            account,
            access_token=identity.access_token,
            refresh_token=identity.refresh_token,
        )
        return
    if account.provider == "apaas":
        client = APaaSClient(base_url=account.base_url, tenant_id=account.tenant_ref)
        payload = await client.login(account.account, password)
        token = str(payload.get("token") or "").strip()
        if not token:
            raise EnterpriseAuthError("ENTERPRISE_AUTH_ACCOUNT_INVALID", "aPaaS 未返回 token")
        set_account_tokens(account, access_token=token)
        return
    raise EnterpriseAuthError("ENTERPRISE_AUTH_ACCOUNT_INVALID", "不支持的认证源")
```

`refresh_bound_account_after_login(...)` 捕获目标侧全部异常，写入 `status="error"` 和 `last_error`，提交后返回状态对象；不得抛出导致主登录失败的异常。

- [ ] **Step 5: 运行服务测试**

Run: `cd backend && pytest tests/test_enterprise_auth_service.py -q`

Expected: PASS，覆盖关闭开关、不存在绑定、唯一最高优先级、同优先级歧义、目标登录失败不抛出。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/enterprise_auth.py backend/tests/test_enterprise_auth_service.py
git commit -m "feat(auth): resolve enterprise account bindings"
```

### Task 3: 平台管理员管理 API

**Files:**
- Create: `backend/app/routes/enterprise_auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_enterprise_auth_routes.py`

- [ ] **Step 1: 写失败的权限和 CRUD 测试**

```python
def test_enterprise_auth_accounts_require_platform_admin(client, tenant_admin_token):
    response = client.get(
        "/api/enterprise-auth/accounts",
        headers={"Authorization": f"Bearer {tenant_admin_token}"},
    )
    assert response.status_code == 403


def test_create_account_masks_secrets(client, platform_admin_token):
    response = client.post(
        "/api/enterprise-auth/accounts",
        headers={"Authorization": f"Bearer {platform_admin_token}"},
        json={
            "provider": "control_plane",
            "base_url": "https://cp.example.com/",
            "tenant_ref": "enterprise-a",
            "tenant_name": "企业 A",
            "account": "admin",
            "password": "secret",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["base_url"] == "https://cp.example.com"
    assert body["has_password"] is True
    assert "password" not in body
    assert "password_enc" not in body
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd backend && pytest tests/test_enterprise_auth_routes.py -q`

Expected: FAIL，路由返回 404。

- [ ] **Step 3: 实现账号 CRUD 和连接测试**

路由前缀为 `/enterprise-auth`，所有端点使用：

```python
ctx: Annotated[AuthContext, Depends(require_platform_admin)]
```

实现：

```text
GET    /accounts
POST   /accounts
PUT    /accounts/{account_id}
DELETE /accounts/{account_id}
POST   /accounts/{account_id}/test
```

账号响应固定使用：

```python
class EnterpriseAuthAccountView(BaseModel):
    id: int
    provider: Literal["apaas", "control_plane"]
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
```

重复账号捕获 `IntegrityError`，回滚后返回 HTTP 409：

```json
{"code":"ENTERPRISE_AUTH_ACCOUNT_DUPLICATE","message":"相同认证源、地址、租户和账号已存在"}
```

- [ ] **Step 4: 实现绑定 CRUD**

实现：

```text
GET    /bindings
POST   /bindings
PUT    /bindings/{binding_id}
DELETE /bindings/{binding_id}
```

创建前执行：

```python
left_id, right_id = sorted((data.left_account_id, data.right_account_id))
if left.provider == right.provider:
    raise api_error(400, "ENTERPRISE_AUTH_ACCOUNT_INVALID", "绑定两侧必须来自不同认证源")
```

重复 pair 返回 HTTP 409 `ENTERPRISE_AUTH_BINDING_DUPLICATE`。

- [ ] **Step 5: 注册路由并运行测试**

在 `app.routes` import 列表和 `include_router` 中加入 `enterprise_auth`。

Run: `cd backend && pytest tests/test_enterprise_auth_routes.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/app/routes/enterprise_auth.py backend/app/main.py backend/tests/test_enterprise_auth_routes.py
git commit -m "feat(auth): add enterprise binding admin api"
```

### Task 4: 默认登录源和登录后可选换票

**Files:**
- Modify: `backend/app/routes/auth/login.py`
- Test: `backend/tests/test_auth_provider_modes.py`

- [ ] **Step 1: 写失败的兼容别名和不阻断测试**

```python
def test_control_plane_provider_is_canonical(monkeypatch):
    _set_auth_provider(monkeypatch, "control_plane")
    assert auth_routes._auth_provider() == "control_plane"


@pytest.mark.asyncio
async def test_secondary_binding_failure_does_not_fail_control_plane_login(
    db_session, monkeypatch
):
    _set_auth_provider(monkeypatch, "control_plane")
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(auth_routes, "login_to_coding_control_plane", fake_cp_login)

    async def fail_secondary_refresh(**_kwargs):
        raise RuntimeError("secondary unavailable")

    monkeypatch.setattr(auth_routes, "refresh_bound_account_after_login", fail_secondary_refresh)

    response = await login(UserLogin(username="admin", password="password"), db_session)
    assert response.access_token
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd backend && pytest tests/test_auth_provider_modes.py -q`

Expected: FAIL，`control_plane` 不在允许值中或 secondary 异常向外传播。

- [ ] **Step 3: 规范化默认认证源**

```python
def _auth_provider() -> str:
    provider = normalize_provider((getattr(settings, "auth_provider", "") or "").strip())
    provider = {"self": "local", "own": "local", "native": "local", "builtin": "local"}.get(
        provider, provider
    )
    if provider not in ("", "local", "apaas", "control_plane"):
        raise HTTPException(
            status_code=500,
            detail="AUTH_PROVIDER must be one of local, apaas, control_plane",
        )
    return provider
```

`coding` 经 `normalize_provider()` 继续映射为 `control_plane`。

- [ ] **Step 4: 主登录成功后调用 best-effort 绑定刷新**

Control Plane 登录保留当前 `login_to_coding_control_plane()`，但不再把明文 token 写成新的绑定事实。创建 Builder 用户后：

```python
try:
    await refresh_bound_account_after_login(
        db,
        source_provider="control_plane",
        source_base_url=control_plane_base_url(),
        source_tenant_ref=str(tenant.tenant_code),
        source_account=identity.username,
        target_provider="apaas",
    )
except Exception:
    logger.exception("enterprise auth secondary refresh failed after control-plane login")
```

aPaaS 登录在确定 `selected.apaas_tenant_id_str` 后调用同一服务，来源字段为：

```python
source_provider="apaas"
source_base_url=settings.apaas_base_url
source_tenant_ref=selected.apaas_tenant_id_str or ""
source_account=username
target_provider="control_plane"
```

只有 `AUTH_ACCOUNT_BINDING_ENABLED=true` 时服务才查询数据库。无绑定、歧义和目标侧失败均只记录状态，不改变 `LoginResponse`。

- [ ] **Step 5: 运行认证模式测试**

Run: `cd backend && pytest tests/test_auth_provider_modes.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/app/routes/auth/login.py backend/tests/test_auth_provider_modes.py
git commit -m "feat(auth): refresh optional binding after login"
```

### Task 5: Control Plane 业务请求使用绑定 token

**Files:**
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/app/routes/code_runtime.py`
- Test: `backend/tests/test_code_runtime_service.py`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: 写失败的请求头边界测试**

```python
def test_control_plane_headers_prefer_explicit_user_token(monkeypatch):
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "service-token")

    headers = service._control_plane_headers(control_plane_token="bound-user-token")

    assert headers["Authorization"] == "Bearer bound-user-token"


def test_control_plane_headers_use_service_token_only_for_system_request(monkeypatch):
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "service-token")

    assert "Authorization" not in service._control_plane_headers()
    assert service._control_plane_headers(system_request=True)["Authorization"] == "Bearer service-token"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd backend && pytest tests/test_code_runtime_service.py -q`

Expected: FAIL，函数不接受 `control_plane_token` 或仍默认使用 service token。

- [ ] **Step 3: 修改 service 的显式 token 接口**

```python
def _control_plane_headers(
    authorization_header: str | None = None,
    *,
    control_plane_token: str | None = None,
    system_request: bool = False,
    include_content_type: bool = False,
    delegated_context: Any | None = None,
    shell_session_id: int | None = None,
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"} if include_content_type else {}
    token = str(control_plane_token or "").strip()
    if not token and system_request:
        token = (
            os.getenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "").strip()
            or (settings.dolphin_code_control_plane_token or "").strip()
        )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # authorization_header 只允许已经是 Control Plane token 的兼容调用显式传入；
    # Builder JWT 不再由 route 层传给 Control Plane。
```

为 `list_code_applications`、`create_code_application`、`default_workspace_open` 和 `open_code_session` 增加 `control_plane_token` 参数并向下传递。

- [ ] **Step 4: 路由层解析绑定 token**

在 `enterprise_auth` 服务中提供：

```python
async def resolve_provider_token_for_context(
    db: AsyncSession,
    ctx: AuthContext,
    target_provider: str,
) -> str | None:
    # 绑定关闭时，control_plane 登录用户可兼容读取自身现有 coding_access_token；
    # 绑定开启时优先解析当前来源账号的绑定目标，并解密目标 token。
```

为 `/code/applications` 和 `/code/applications` POST 增加 `db` 依赖，并调用：

```python
control_plane_token = await resolve_provider_token_for_context(db, ctx, "control_plane")
if not control_plane_token:
    raise HTTPException(
        status_code=403,
        detail={
            "code": "ENTERPRISE_AUTH_BINDING_UNAVAILABLE",
            "message": "当前账号没有可用的 Control Plane 认证绑定",
        },
    )
```

`open_code_runtime_session()` 也把该 token 传给 `open_code_session()`。不得把 Builder 请求头中的 JWT 继续转发给 Control Plane。

- [ ] **Step 5: 运行 service 和 route 测试**

Run: `cd backend && pytest tests/test_code_runtime_service.py tests/test_code_runtime_routes.py -q`

Expected: PASS，且断言业务请求使用绑定 token、未绑定时返回明确错误、system request 才使用全局 token。

- [ ] **Step 6: 提交**

```bash
git add backend/app/code_runtime/service.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py
git commit -m "fix(auth): use bound token for control plane requests"
```

### Task 6: 平台管理认证绑定界面

**Files:**
- Create: `frontend/src/api/enterpriseAuth.ts`
- Create: `frontend/src/components/platform/EnterpriseAuthBindingsPanel.vue`
- Modify: `frontend/src/views/PlatformTenants.vue`
- Test: `frontend/src/components/platform/EnterpriseAuthBindingsPanel.spec.ts`

- [ ] **Step 1: 写失败的组件行为测试**

```typescript
import { describe, expect, it, vi } from 'vitest'
import { enterpriseAuthApi } from '@/api/enterpriseAuth'

vi.mock('@/api/enterpriseAuth', () => ({
  enterpriseAuthApi: {
    listAccounts: vi.fn().mockResolvedValue([]),
    listBindings: vi.fn().mockResolvedValue([]),
  },
}))

describe('EnterpriseAuthBindingsPanel', () => {
  it('loads accounts and bindings on mount', async () => {
    const { mount } = await import('@vue/test-utils')
    const Panel = (await import('./EnterpriseAuthBindingsPanel.vue')).default
    mount(Panel)
    await Promise.resolve()
    expect(enterpriseAuthApi.listAccounts).toHaveBeenCalled()
    expect(enterpriseAuthApi.listBindings).toHaveBeenCalled()
  })
})
```

若仓库未安装 `@vue/test-utils`，不新增测试框架依赖；改为测试抽出的纯函数 `canonicalBindingPair()` 和 API 类型，并以 `npm run build` 作为组件集成验证。

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd frontend && npm test -- EnterpriseAuthBindingsPanel.spec.ts`

Expected: FAIL，API 或组件不存在；若缺测试工具则按上一步的纯函数方案调整测试。

- [ ] **Step 3: 实现类型化 API**

```typescript
export type EnterpriseAuthProvider = 'apaas' | 'control_plane'

export interface EnterpriseAuthAccount {
  id: number
  provider: EnterpriseAuthProvider
  base_url: string
  tenant_ref: string
  tenant_name?: string | null
  account: string
  has_password: boolean
  has_access_token: boolean
  status: string
  last_verified_at?: string | null
  last_error?: string | null
}

export const enterpriseAuthApi = {
  listAccounts: () => request.get<any, EnterpriseAuthAccount[]>('/enterprise-auth/accounts'),
  createAccount: (data: EnterpriseAuthAccountInput) =>
    request.post<any, EnterpriseAuthAccount>('/enterprise-auth/accounts', data),
  updateAccount: (id: number, data: EnterpriseAuthAccountInput) =>
    request.put<any, EnterpriseAuthAccount>(`/enterprise-auth/accounts/${id}`, data),
  deleteAccount: (id: number) => request.delete(`/enterprise-auth/accounts/${id}`),
  testAccount: (id: number) => request.post(`/enterprise-auth/accounts/${id}/test`),
  listBindings: () => request.get<any, EnterpriseAuthBinding[]>('/enterprise-auth/bindings'),
  createBinding: (data: EnterpriseAuthBindingInput) =>
    request.post<any, EnterpriseAuthBinding>('/enterprise-auth/bindings', data),
  updateBinding: (id: number, data: Partial<EnterpriseAuthBindingInput>) =>
    request.put<any, EnterpriseAuthBinding>(`/enterprise-auth/bindings/${id}`, data),
  deleteBinding: (id: number) => request.delete(`/enterprise-auth/bindings/${id}`),
}
```

- [ ] **Step 4: 实现管理面板**

面板包含两个无嵌套卡片的区域：

1. 账号表：认证源、地址、租户、账号、连接状态、最后校验时间；操作为编辑、测试、删除。
2. 绑定表：左账号、右账号、优先级、启用开关；操作为编辑、删除。

账号对话框必须满足：

```text
认证源：下拉，仅 aPaaS / Control Plane
服务地址：必填 URL
租户标识：必填
租户名称：可选
管理员账号：必填
管理员密码：创建必填；编辑留空表示不修改
```

密码输入使用 `show-password`，列表绝不显示密码/token。绑定对话框仅允许选择不同 provider 的账号。

- [ ] **Step 5: 集成到平台管理**

在 `PlatformTenants.vue` 顶层加入页签：

```vue
<el-tabs v-model="activeTab" class="platform-admin-tabs">
  <el-tab-pane label="租户管理" name="tenants">
    <!-- 保持现有租户管理内容 -->
  </el-tab-pane>
  <el-tab-pane label="认证绑定" name="enterprise-auth">
    <EnterpriseAuthBindingsPanel />
  </el-tab-pane>
</el-tabs>
```

页签切换不影响现有租户表、抽屉和对话框状态。

- [ ] **Step 6: 运行前端测试和构建**

Run: `cd frontend && npm test -- EnterpriseAuthBindingsPanel.spec.ts && npm run build`

Expected: Vitest PASS，`vue-tsc` 和 Vite build PASS。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/api/enterpriseAuth.ts frontend/src/components/platform/EnterpriseAuthBindingsPanel.vue frontend/src/components/platform/EnterpriseAuthBindingsPanel.spec.ts frontend/src/views/PlatformTenants.vue
git commit -m "feat(auth): manage enterprise account bindings"
```

### Task 7: 配置注释、回归和最终验证

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`

- [ ] **Step 1: 补充可选配置注释**

```dotenv
# Optional. Default login authority: apaas or control_plane.
# Legacy value "coding" remains accepted as a compatibility alias.
AUTH_PROVIDER=apaas

# Optional. Default false.
# false: only AUTH_PROVIDER login is used; Builder does not query account bindings.
# true: after primary login, Builder best-effort refreshes the bound secondary credential.
AUTH_ACCOUNT_BINDING_ENABLED=false
```

README 只说明 Builder 配置和行为，不写 SDK/Control Plane 改造步骤。

- [ ] **Step 2: 运行后端定向测试**

Run:

```bash
cd backend
pytest \
  tests/test_enterprise_auth_models.py \
  tests/test_enterprise_auth_service.py \
  tests/test_enterprise_auth_routes.py \
  tests/test_auth_provider_modes.py \
  tests/test_coding_auth_adapter.py \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行前端测试和构建**

Run:

```bash
cd frontend
npm test -- EnterpriseAuthBindingsPanel.spec.ts
npm run build
```

Expected: PASS。

- [ ] **Step 4: 检查改动范围**

Run:

```bash
git status --short
git diff --stat HEAD~7..HEAD
git diff --check
```

Expected:

- 仅 Builder 仓库有改动。
- 不包含 SDK 或 Control Plane 源码改动。
- 无明文密码/token、尾随空格或冲突标记。

- [ ] **Step 5: 提交文档**

```bash
git add backend/.env.example README.md
git commit -m "docs(auth): document optional account bindings"
```

- [ ] **Step 6: 最终全量相关验证**

Run:

```bash
cd backend && pytest tests/test_auth_provider_modes.py tests/test_coding_auth_adapter.py tests/test_code_runtime_service.py tests/test_code_runtime_routes.py tests/test_enterprise_auth_models.py tests/test_enterprise_auth_service.py tests/test_enterprise_auth_routes.py -q
cd ../frontend && npm test -- EnterpriseAuthBindingsPanel.spec.ts && npm run build
```

Expected: 全部 PASS。
