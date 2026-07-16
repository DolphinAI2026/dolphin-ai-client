# Builder AI Unified Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `apaas-builder-ai` 自己成为 Builder 登录策略、账号源和 Builder/Code 产品开关的配置中心。后台可配置默认登录方式为 `apaas` 或 `platform`，可同时启用另一组账号作为第二登录入口，并分别控制 Builder 和 Code 是否开放。

**Architecture:** 登录发生在 `apaas-builder-ai` 后端。`builder-ai` 使用本地 `system_settings` 保存运行时鉴权配置，登录成功后投影到现有 `User/Tenant/UserTenant/AuthContext`。`control-plane` 不承担 Builder 登录策略中心职责，只负责沙箱、工作区打开、runtime service token、delegated identity headers 和 Agent Runtime entry token 等运行时边界。`agent-runtime` 继续只信 entry token/cookie，不直接信浏览器用户 token。

**Tech Stack:** FastAPI + SQLAlchemy + Vue 3 + Pinia + Axios in `apaas-builder-ai`; Spring Boot sandbox/workspace APIs in `control-plane`; Go HTTP auth middleware in `agent-runtime`; App Seed SDK auth contract as reference runtime implementation.

---

## 影响面

这次改动以 `apaas-builder-ai` 为主，涉及这些边界：

- Builder 后端登录配置：`backend/app/models/system_setting.py`、新增 `backend/app/builder_auth/**`、`backend/app/routes/auth/login.py`、新增鉴权配置路由。
- Builder 后端鉴权上下文：`backend/app/auth.py`、`backend/app/deps.py`、依赖 `AuthContext` 的业务路由。
- Builder Web 前端：`frontend/src/views/Login.vue`、`frontend/src/stores/user.ts`、`frontend/src/utils/request.ts`、`frontend/src/router/index.ts`。
- Builder Admin 嵌入页：`frontend/src/views/PlatformAdminEmbed.vue`、`admin-spa/src/api/client.ts`、`admin-spa/src/stores/auth.ts`。
- Code 页面和 Code runtime 代理：`backend/app/code_runtime/service.py`、`backend/app/routes/code_runtime.py`、`frontend/src/api/codeRuntime.ts`。
- aPaaS 账号与外部凭据：`backend/app/routes/apaas.py`、`backend/app/routes/applications/*`、`backend/app/routes/generation_steps.py`、`backend/app/routes/mcp_platform.py`。
- Control Plane 运行时边界：只确认 workspace open、service token、delegated headers、runtime entry token，不新增 Builder 登录策略。
- Agent Runtime：`agent-runtime/internal/http/auth.go`、`agent-runtime/internal/application/runtime_auth.go`、`agent-runtime/internal/http/runtime_auth_handlers.go`。
- 部署与本地配置：`README.md`、`.env.local` 示例，说明登录配置来自 builder 后台而不是 control-plane 后台。

## 目标登录策略模型

`apaas-builder-ai` 后台配置必须能表达：

- **默认登录源**：`default_login_provider = "apaas" | "platform"`。登录页默认选中这一项。
- **启用登录源**：`enabled_login_providers` 至少包含默认登录源；如果同时包含两项，登录页显示两种账号入口。
- **Builder/Code 能力开关**：`products.builder.enabled`、`products.code.enabled`。前端隐藏入口，后端 API 同步校验。
- **aPaaS 登录配置**：aPaaS base URL、tenant 绑定、认证方式、必要 secret 保存在 builder 后台配置，公开配置接口不返回 secret。
- **platform 登录配置**：由 builder-ai 后端封装 `PlatformAuthProvider`，可以对接平台认证服务，也可以先复用现有 builder 本地账号体系作为 platform 账号源。
- **另一组账号**：非默认 provider 只要被启用，就作为第二登录入口；默认 aPaaS 时可启用 platform 账号，默认 platform 时可启用 aPaaS 账号。

统一后按这个身份模型收敛：

- **Builder session token**：由 `apaas-builder-ai` 签发，浏览器保存 access token，必要时再补 refresh token。
- **登录 provider**：token 或 session 内记录 `auth_source = "apaas" | "platform"`，用于审计、展示和后续凭据解析。
- **Builder local projection**：现有 `users`、`tenants`、`user_tenants` 保留，作为本地资源归属、租户选择、权限 guard 和历史数据映射。
- **租户上下文**：前端保存 `selectedTenantId`，普通 API 用 `X-Builder-Tenant-Id` 传入；SSE/download 这类不能带 header 的入口使用短期 `builder_capability_token`。
- **Code runtime embed token**：继续由 builder 后端签发短期 iframe 能力票，换 HttpOnly proxy cookie 后访问 runtime。
- **Agent runtime entry token**：继续由 control-plane/runtime token 体系签发和轮换，runtime 只信 entry token/cookie。
- **aPaaS token**：仅作为 aPaaS provider 验证账号、绑定外部租户和后续访问 aPaaS API 的材料，不作为 Builder 浏览器 session 的主 token。

## File Structure

- Create: `backend/app/builder_auth/__init__.py`
  导出 builder 鉴权配置、provider 和 identity 类型。
- Create: `backend/app/builder_auth/settings.py`
  基于 `SystemSetting` 保存 `builder_auth_settings`，提供缓存、加解密、公开投影和校验。
- Create: `backend/app/builder_auth/identity.py`
  定义 `BuilderIdentity`、`ProviderLoginResult`、本地 user/tenant projection 函数。
- Create: `backend/app/builder_auth/providers.py`
  定义 `AuthProvider` 接口、provider registry、provider enabled/default 校验。
- Create: `backend/app/builder_auth/apaas_provider.py`
  实现 aPaaS 用户名密码验证和 aPaaS 用户/租户到 builder 本地身份的映射。
- Create: `backend/app/builder_auth/platform_provider.py`
  实现 platform 账号验证。第一阶段可复用 builder 本地账号，后续可替换成平台认证服务 client。
- Create: `backend/app/routes/auth/settings.py`
  提供公开登录配置接口和管理员保存接口。
- Modify: `backend/app/routes/auth/login.py`
  根据 builder 后台配置选择 provider，不再用 `.env AUTH_PROVIDER` 决定登录模式。
- Modify: `backend/app/config.py`
  保留本地启动兜底项和 secret，不新增默认登录源或产品开关 env 真源。
- Modify: `backend/app/auth.py`
  保留 JWT helper，并明确区分 browser session token 与短期 capability token。
- Modify: `backend/app/deps.py`
  `get_auth_context` 解析 builder session、`auth_source` 和 `X-Builder-Tenant-Id`。
- Create: `frontend/src/api/authSettings.ts`
  拉取公开登录配置。
- Modify: `frontend/src/views/Login.vue`
  按后台配置展示默认登录入口和第二账号入口。
- Modify: `frontend/src/stores/user.ts`
  保存 session、用户、租户和 `authSource`。
- Modify: `frontend/src/utils/request.ts`
  注入 `Authorization`、`X-Builder-Tenant-Id`，统一处理 401。
- Modify: `admin-spa/src/api/client.ts`
  读取 builder session token 和 tenant header。
- Modify: `backend/app/code_runtime/service.py`
  调 control-plane 时继续使用 service token 或 delegated identity，不要求 control-plane 理解 Builder 登录策略。
- Modify: `backend/app/routes/code_runtime.py`
  proxy cookie 只接受短期 capability token，不接受原始浏览器 session token。
- Modify: `agent-runtime/internal/http/auth.go`
  保持 entry-token 认证；补测试确认浏览器用户 token 不能直接访问 sandbox。

---

### Task 0: Builder Auth Runtime Settings

**Files:**
- Create: `backend/app/builder_auth/settings.py`
- Create: `backend/app/routes/auth/settings.py`
- Test: `backend/tests/test_builder_auth_settings.py`
- Test: `backend/tests/test_auth_settings_routes.py`

- [ ] **Step 1: Write the failing settings tests**

```python
async def test_save_and_load_builder_auth_settings_hide_secrets(db_session):
    settings = BuilderAuthSettings(
        default_login_provider="apaas",
        enabled_login_providers=["apaas", "platform"],
        products=ProductSwitches(builder=ProductSwitch(enabled=True), code=ProductSwitch(enabled=False)),
        providers={
            "apaas": ProviderSettings(label="aPaaS 账号", enabled=True, config={"base_url": "http://apaas", "secret": "s1"}),
            "platform": ProviderSettings(label="平台账号", enabled=True, config={"mode": "local"}),
        },
    )
    await save_builder_auth_settings(db_session, settings, updated_by_user_id=1)

    loaded = await get_builder_auth_settings(db_session)
    public = loaded.to_public()

    assert loaded.default_login_provider == "apaas"
    assert public.products.code.enabled is False
    assert "s1" not in public.model_dump_json()
    assert "secret" not in public.model_dump_json()
```

- [ ] **Step 2: Run the failing tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_settings.py -q`
Expected: FAIL because `builder_auth.settings` does not exist.

- [ ] **Step 3: Implement `BuilderAuthSettings` storage**

Use existing `SystemSetting` and the same pattern as `backend/app/mcp_keys.py`:

```text
setting key: builder_auth_settings
cache ttl: 5 seconds
secret fields: encrypted inside value_enc by existing encrypt/decrypt helpers
```

Validation rules:

- `default_login_provider` must be `apaas` or `platform`.
- `enabled_login_providers` must include `default_login_provider`.
- `enabled_login_providers` can only contain `apaas` and `platform`.
- At least one of `products.builder.enabled` or `products.code.enabled` must be true.
- Public projection must include provider labels and enabled/default flags, but no provider secret.

- [ ] **Step 4: Add public and admin routes**

Routes:

```text
GET /api/auth/settings/public
GET /api/admin/auth/settings
PUT /api/admin/auth/settings
```

Rules:

- Public route can be called before login and returns only safe display config.
- Admin routes require existing admin permission.
- Admin save must validate the full config before writing `SystemSetting`.

- [ ] **Step 5: Run the tests**

Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_builder_auth_settings.py backend/tests/test_auth_settings_routes.py -q
```

Expected: PASS.

---

### Task 1: Provider Interface And Identity Projection

**Files:**
- Create: `backend/app/builder_auth/identity.py`
- Create: `backend/app/builder_auth/providers.py`
- Test: `backend/tests/test_builder_auth_identity.py`
- Test: `backend/tests/test_builder_auth_providers.py`

- [ ] **Step 1: Write the failing identity and registry tests**

```python
def test_provider_registry_uses_default_when_provider_not_requested():
    settings = fake_settings(default_login_provider="apaas", enabled_login_providers=["apaas", "platform"])
    registry = AuthProviderRegistry({"apaas": fake_provider("apaas"), "platform": fake_provider("platform")})
    assert registry.resolve(settings, requested_provider=None).name == "apaas"


def test_provider_registry_rejects_disabled_secondary_provider():
    settings = fake_settings(default_login_provider="apaas", enabled_login_providers=["apaas"])
    registry = AuthProviderRegistry({"apaas": fake_provider("apaas"), "platform": fake_provider("platform")})
    with pytest.raises(LoginProviderDisabled):
        registry.resolve(settings, requested_provider="platform")
```

- [ ] **Step 2: Run the failing tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_identity.py backend/tests/test_builder_auth_providers.py -q`
Expected: FAIL because provider interface and identity projection do not exist.

- [ ] **Step 3: Implement identity contracts**

Create:

```python
class BuilderIdentity(BaseModel):
    external_user_id: str
    username: str
    display_name: str | None = None
    auth_source: Literal["apaas", "platform"]
    roles: set[str] = set()
    external_tenant_id: str | None = None
    raw: dict[str, object] | None = None

class ProviderLoginResult(BaseModel):
    identity: BuilderIdentity
    external_access_token: str | None = None
    external_refresh_token: str | None = None
    expires_at: datetime | None = None
```

Projection rules:

- Upsert local `User` by `(account_source, external_user_id)` when available.
- Fall back to `(account_source, username)` only when provider has no stable external id.
- Ensure user has at least one active `Tenant` and `UserTenant` membership.
- Preserve existing local ids so historical projects, sessions and code runtime records stay attached.

- [ ] **Step 4: Run the tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_identity.py backend/tests/test_builder_auth_providers.py -q`
Expected: PASS.

---

### Task 2: aPaaS And Platform Login Providers

**Files:**
- Create: `backend/app/builder_auth/apaas_provider.py`
- Create: `backend/app/builder_auth/platform_provider.py`
- Test: `backend/tests/test_builder_auth_apaas_provider.py`
- Test: `backend/tests/test_builder_auth_platform_provider.py`

- [ ] **Step 1: Write failing provider tests**

```python
async def test_platform_provider_can_use_existing_local_account(db_session):
    await create_local_user(db_session, username="ops", password="secret")
    provider = PlatformAuthProvider(mode="local")
    result = await provider.login(db_session, username="ops", password="secret")
    assert result.identity.auth_source == "platform"
    assert result.identity.username == "ops"


async def test_apaas_provider_maps_external_user(httpx_mock, db_session):
    httpx_mock.add_response(json={"userId": "u-1", "username": "alice", "tenantId": "t-1", "accessToken": "a1"})
    provider = ApaasAuthProvider(base_url="http://apaas")
    result = await provider.login(db_session, username="alice", password="secret")
    assert result.identity.auth_source == "apaas"
    assert result.identity.external_user_id == "u-1"
```

- [ ] **Step 2: Run failing tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_apaas_provider.py backend/tests/test_builder_auth_platform_provider.py -q`
Expected: FAIL because providers do not exist.

- [ ] **Step 3: Implement `PlatformAuthProvider`**

First implementation:

- `mode="local"` uses existing builder local username/password validation.
- Result `auth_source="platform"`.
- Does not use `control-plane` as login strategy owner.
- Keep a constructor-level extension point for later `mode="remote"` platform auth service without changing route contracts.

- [ ] **Step 4: Implement `ApaasAuthProvider`**

Rules:

- Validate username/password against configured aPaaS endpoint.
- Persist external token only in encrypted credential storage, not in browser session payload.
- Return normalized `BuilderIdentity`.
- Do not store raw aPaaS password.

- [ ] **Step 5: Run provider tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_apaas_provider.py backend/tests/test_builder_auth_platform_provider.py -q`
Expected: PASS.

---

### Task 3: Login Route Uses Builder Settings

**Files:**
- Modify: `backend/app/routes/auth/login.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_builder_auth_login_routes.py`

- [ ] **Step 1: Write failing route tests**

```python
async def test_login_uses_default_provider_from_builder_settings(async_client, db_session):
    await save_builder_auth_settings(db_session, fake_settings(default_login_provider="apaas", enabled_login_providers=["apaas", "platform"]))
    response = await async_client.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert response.status_code == 200
    assert response.json()["auth_source"] == "apaas"


async def test_login_can_use_enabled_secondary_provider(async_client, db_session):
    await save_builder_auth_settings(db_session, fake_settings(default_login_provider="apaas", enabled_login_providers=["apaas", "platform"]))
    response = await async_client.post("/api/auth/login", json={"username": "ops", "password": "secret", "login_provider": "platform"})
    assert response.status_code == 200
    assert response.json()["auth_source"] == "platform"


async def test_login_rejects_disabled_provider(async_client, db_session):
    await save_builder_auth_settings(db_session, fake_settings(default_login_provider="apaas", enabled_login_providers=["apaas"]))
    response = await async_client.post("/api/auth/login", json={"username": "ops", "password": "secret", "login_provider": "platform"})
    assert response.status_code in {400, 403}
```

- [ ] **Step 2: Run failing tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_login_routes.py -q`
Expected: FAIL because `/auth/login` still uses env `AUTH_PROVIDER`.

- [ ] **Step 3: Update login request and response**

Request supports optional provider:

```json
{
  "username": "alice",
  "password": "secret",
  "login_provider": "apaas"
}
```

Response preserves current compatibility fields and adds:

```json
{
  "access_token": "<builder-session-token>",
  "token_type": "bearer",
  "auth_source": "apaas",
  "requires_tenant_selection": false,
  "tenants": []
}
```

Rules:

- Missing `login_provider` uses `default_login_provider`.
- Disabled provider returns stable error code.
- `.env AUTH_PROVIDER` is no longer the runtime source of truth. Keep it only as a migration fallback when `builder_auth_settings` has not been initialized.

- [ ] **Step 4: Run login tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_login_routes.py -q`
Expected: PASS.

---

### Task 4: AuthContext And Tenant Guard

**Files:**
- Modify: `backend/app/auth.py`
- Modify: `backend/app/deps.py`
- Test: `backend/tests/test_builder_auth_deps.py`

- [ ] **Step 1: Write failing AuthContext tests**

```python
async def test_get_auth_context_uses_selected_tenant_header(async_client, builder_session_token):
    response = await async_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {builder_session_token}", "X-Builder-Tenant-Id": "12"},
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == 12
```

- [ ] **Step 2: Run failing tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_deps.py -q`
Expected: FAIL where tenant header and `auth_source` are not part of the existing context.

- [ ] **Step 3: Implement context parsing**

Rules:

- Decode builder session token.
- Resolve local user by token subject.
- Resolve tenant from `X-Builder-Tenant-Id`, then default membership, then first active membership.
- Reject tenant ids where the user has no active membership.
- Include `auth_source` in `AuthContext` for audit and credential resolution.

- [ ] **Step 4: Run targeted backend tests**

Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_builder_auth_deps.py backend/tests/test_code_runtime_routes.py -q
```

Expected: PASS.

---

### Task 5: Frontend Login Modes And Product Switches

**Files:**
- Create: `frontend/src/api/authSettings.ts`
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/stores/user.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/utils/request.ts`
- Test: `frontend/src/views/Login.spec.ts`
- Test: `frontend/src/stores/user.spec.ts`
- Test: `frontend/src/router/index.spec.ts`

- [ ] **Step 1: Write failing frontend tests**

```ts
it('selects the configured default provider and shows enabled secondary provider', async () => {
  mockPublicAuthSettings({
    defaultLoginProvider: 'apaas',
    enabledLoginProviders: ['apaas', 'platform'],
    products: { builder: { enabled: true }, code: { enabled: false } },
  })
  const wrapper = mount(Login)
  await flushPromises()
  expect(wrapper.find('[data-test="login-provider-apaas"]').classes()).toContain('active')
  expect(wrapper.find('[data-test="login-provider-platform"]').exists()).toBe(true)
})
```

- [ ] **Step 2: Run failing frontend tests**

Run:

```bash
cd frontend && npm run test -- src/views/Login.spec.ts src/stores/user.spec.ts src/router/index.spec.ts
```

Expected: FAIL because login settings API and UI mode switching do not exist.

- [ ] **Step 3: Implement public settings fetch**

Rules:

- Fetch `GET /api/auth/settings/public` before rendering login form.
- Show only enabled providers.
- Default active tab equals `defaultLoginProvider`.
- Submit `login_provider` with login request.
- Store `authSource`, product switches and selected tenant in user store.

- [ ] **Step 4: Enforce product switches in frontend**

Rules:

- `products.builder.enabled=false` blocks Builder routes and shows a clear unavailable state after login.
- `products.code.enabled=false` hides Code nav and prevents Code route entry.
- Frontend hiding is only UX; backend checks remain authoritative.

- [ ] **Step 5: Run frontend tests**

Run:

```bash
cd frontend && npm run test -- src/views/Login.spec.ts src/stores/user.spec.ts src/router/index.spec.ts
```

Expected: PASS.

---

### Task 6: Backend Product Switch Guards

**Files:**
- Create: `backend/app/builder_auth/product_guard.py`
- Modify: `backend/app/routes/code_runtime.py`
- Modify: Builder page/API route dependencies that serve Builder-only capabilities
- Test: `backend/tests/test_builder_auth_product_guard.py`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: Write failing guard tests**

```python
async def test_code_runtime_open_rejects_when_code_disabled(async_client, db_session, auth_headers):
    await save_builder_auth_settings(db_session, fake_settings(products={"builder": True, "code": False}))
    response = await async_client.post("/api/code-runtime/apps/app-1/open", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CODE_DISABLED"
```

- [ ] **Step 2: Run failing tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_product_guard.py backend/tests/test_code_runtime_routes.py -q`
Expected: FAIL because product switches are not enforced server-side.

- [ ] **Step 3: Implement guards**

Rules:

- Code runtime open/list/proxy bootstrap APIs require `products.code.enabled=true`.
- Builder-only APIs require `products.builder.enabled=true` where disabling Builder must block the feature, not just hide navigation.
- Guard reads cached builder auth settings.
- Return stable error codes: `BUILDER_DISABLED` and `CODE_DISABLED`.

- [ ] **Step 4: Run guard tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_builder_auth_product_guard.py backend/tests/test_code_runtime_routes.py -q`
Expected: PASS.

---

### Task 7: Code Runtime And Control Plane Boundary

**Files:**
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/app/routes/code_runtime.py`
- Modify: `frontend/src/api/codeRuntime.ts`
- Test: `backend/tests/test_code_runtime_service.py`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: Write boundary tests**

```python
async def test_workspace_open_keeps_service_or_delegated_headers(respx_mock):
    route = respx_mock.post("http://cp/api/applications/app-1/workspace/open").respond(
        200,
        json={"specReviewUrl": "http://runtime/builder/"},
    )
    await default_workspace_open(
        "app-1",
        authorization_header=None,
        delegated_context=fake_auth_context(auth_source="apaas"),
    )
    assert "Authorization" in route.calls.last.request.headers or "X-Delegated-User-Id" in route.calls.last.request.headers


async def test_proxy_rejects_raw_builder_session_token(async_client, builder_session_token):
    response = await async_client.get(
        "/api/code-runtime/1/builder/",
        headers={"Authorization": f"Bearer {builder_session_token}"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run boundary tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py -q`
Expected: PASS if the current boundary already holds; otherwise FAIL and implement the minimal correction.

- [ ] **Step 3: Keep control-plane out of login strategy**

Rules:

- `control-plane` receives service token or delegated identity for workspace/runtime actions.
- `control-plane` does not decide Builder login provider.
- Code runtime iframe access still uses short-lived `dolphin_token` and HttpOnly proxy cookie.
- Raw Builder browser session token cannot access `/api/code-runtime/{session_id}/**` proxy.

- [ ] **Step 4: Run Code runtime tests**

Run: `backend/venv/bin/python -m pytest backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py -q`
Expected: PASS.

---

### Task 8: aPaaS Credential Binding Cleanup

**Files:**
- Modify: `backend/app/routes/apaas.py`
- Modify: `backend/app/routes/applications/crud.py`
- Modify: `backend/app/routes/applications/generate.py`
- Modify: `backend/app/routes/generation_steps.py`
- Modify: `backend/app/routes/mcp_platform.py`
- Test: `backend/tests/test_apaas_credentials.py`

- [ ] **Step 1: Write failing credential resolver tests**

```python
async def test_apaas_token_resolves_from_user_tenant_credential(db_session):
    ctx = fake_auth_context(user_id=10, tenant_id=20, auth_source="apaas")
    credential = await resolve_apaas_credential(db_session, ctx)
    assert credential.local_tenant_id == 20
    assert credential.token == "tenant-token"
```

- [ ] **Step 2: Run failing test**

Run: `backend/venv/bin/python -m pytest backend/tests/test_apaas_credentials.py -q`
Expected: FAIL because routes still read user-level aPaaS token fields directly.

- [ ] **Step 3: Add credential resolver**

Resolver order:

1. Per-user per-local-tenant encrypted aPaaS credential created by `ApaasAuthProvider`.
2. `PlatformEnv` tenant binding where the operation is environment-scoped.
3. Legacy `User.apaas_token` only during migration.

Rules:

- Do not use aPaaS token as Builder session token.
- Do not store raw aPaaS password.
- Do not leak external tokens in `/api/auth/me`.

- [ ] **Step 4: Replace direct token reads**

Replace direct `ctx.user.apaas_token` usage in listed route files with `resolve_apaas_credential(db, ctx)`.

- [ ] **Step 5: Run credential and application tests**

Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_apaas_credentials.py backend/tests/test_applications.py backend/tests/test_generation_steps.py -q
```

Expected: PASS.

---

### Task 9: Admin SPA Embedded Auth

**Files:**
- Modify: `frontend/src/views/PlatformAdminEmbed.vue`
- Modify: `admin-spa/src/api/client.ts`
- Modify: `admin-spa/src/stores/auth.ts`
- Test: `frontend/src/views/PlatformAdminEmbed.spec.ts`
- Test: `admin-spa/src/api/client.spec.ts`

- [ ] **Step 1: Write failing tests for unified builder session keys**

```ts
it('admin api reads builder session token before legacy token', async () => {
  localStorage.setItem('builder.auth.accessToken', 'builder-token')
  localStorage.setItem('token', 'legacy-token')
  await apiGet('/auth/me')
  expect(lastHeaders().Authorization).toBe('Bearer builder-token')
})
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd frontend && npm run test -- src/views/PlatformAdminEmbed.spec.ts
cd admin-spa && npm run test -- src/api/client.spec.ts
```

Expected: FAIL because admin currently reads `admin_token || token`.

- [ ] **Step 3: Update embedded admin auth**

Rules:

- Prefer `builder.auth.accessToken`.
- Include `X-Builder-Tenant-Id` when available.
- Keep `token/admin_token` fallback only for migration.
- Do not pass the primary token in iframe URL; use same-origin storage or a short bootstrap capability token.

- [ ] **Step 4: Run tests**

Run:

```bash
cd frontend && npm run test -- src/views/PlatformAdminEmbed.spec.ts
cd admin-spa && npm run test -- src/api/client.spec.ts
```

Expected: PASS.

---

### Task 10: Agent Runtime Boundary Tests

**Files:**
- Modify: `agent-runtime/internal/http/auth.go`
- Modify: `agent-runtime/internal/http/auth_test.go`
- Modify: `agent-runtime/internal/http/runtime_auth_handlers_test.go`

- [ ] **Step 1: Write or confirm tests that raw Builder session token is not enough**

```go
func TestSandboxAuthRejectsRawBuilderBearerWithoutEntryToken(t *testing.T) {
    handler := withSandboxAuth(AuthConfig{
        Mode: "token",
        Token: "entry-token",
    }, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusNoContent)
    }))
    req := httptest.NewRequest(http.MethodGet, "/builder/", nil)
    req.Header.Set("Authorization", "Bearer builder-session-token")
    rr := httptest.NewRecorder()
    handler.ServeHTTP(rr, req)
    if rr.Code != http.StatusUnauthorized {
        t.Fatalf("status=%d, want 401", rr.Code)
    }
}
```

- [ ] **Step 2: Run boundary tests**

Run: `go test ./internal/http -run 'TestSandboxAuthRejectsRawBuilderBearerWithoutEntryToken|TestRotateEntryToken'`
Expected: PASS if boundary already holds; otherwise FAIL and implement the minimal guard.

- [ ] **Step 3: Keep runtime token flows unchanged**

Rules:

- `/api/internal/auth/token/rotate` continues to require runtime API token.
- Browser Builder session token never rotates entry tokens directly.
- Sandbox browser entry remains entry token/cookie based.

- [ ] **Step 4: Run runtime auth tests**

Run: `go test ./internal/http ./internal/application -run 'Auth|Token'`
Expected: PASS.

---

### Task 11: Migration And README

**Files:**
- Modify: `README.md`
- Create: `backend/scripts/migrate_builder_auth_projection.py`
- Test: `backend/tests/test_builder_auth_migration.py`

- [ ] **Step 1: Write migration tests**

```python
async def test_projection_migration_is_idempotent(db_session):
    first = await migrate_builder_auth_projection(db_session)
    second = await migrate_builder_auth_projection(db_session)
    assert first.created_users >= 0
    assert second.created_users == 0
```

- [ ] **Step 2: Add rollout modes to docs**

Document:

```text
builder auth settings:
  default_login_provider=apaas|platform
  enabled_login_providers=[apaas] | [platform] | [apaas,platform]
  products.builder.enabled=true|false
  products.code.enabled=true|false

builder compatibility env:
  BUILDER_AUTH_ACCEPT_LEGACY_JWT=1   # migration only
  BUILDER_AUTH_ACCEPT_LEGACY_JWT=0   # cutover
```

- [ ] **Step 3: Add local run docs**

Document required services:

```text
apaas-builder-ai backend :8000
apaas-builder-ai frontend :5173
control-plane :8080 for workspace/runtime APIs only
agent-runtime sandbox runtime :61137 or control-plane managed runtime URL
```

The README must explicitly say Builder login provider and Builder/Code switches are configured in `apaas-builder-ai`后台配置, not in `control-plane`.

- [ ] **Step 4: Run migration tests and docs checks**

Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_builder_auth_migration.py -q
git diff --check -- README.md docs/superpowers/plans/2026-07-09-builder-ai-unified-auth.md
```

Expected: PASS.

---

## Verification Matrix

- Public config: `GET /api/auth/settings/public` returns default login provider, enabled providers, Builder/Code switches and no secrets.
- Admin config: admin can save `apaas` default, `platform` default and both providers enabled; invalid configs are rejected.
- Builder login: default `apaas` login and default `platform` login both return Builder session token.
- Secondary accounts: enabled non-default provider can log in; disabled provider fails with stable error.
- `/api/auth/me`: returns local user, tenant, `authSource`, and never returns raw aPaaS tokens, passwords, RSA private keys or provider secrets.
- Tenant switch: updates selected tenant and reloads tenant-scoped data; it does not mint a separate token type unless a short capability token is needed.
- Product switches: `products.builder.enabled=false` blocks Builder routes/APIs; `products.code.enabled=false` blocks Code routes/APIs.
- Admin embed: `admin-spa` uses the same Builder session token and tenant header.
- Code app list/open: builder continues to call control-plane with service token or delegated identity; control-plane does not decide login provider.
- Code runtime iframe: raw Builder session token cannot access `/api/code-runtime/**`; only short capability token/cookie can.
- Agent runtime: raw Builder session token cannot access sandbox; entry token/cookie still works.
- aPaaS operations: routes resolve per-user per-tenant credential, not a global mutable `User.apaas_token`.
- Legacy rollout: `BUILDER_AUTH_ACCEPT_LEGACY_JWT=1` keeps existing builder JWT sessions working during migration.

## Risk Notes

- The biggest data risk is identity drift between builder local user id, aPaaS user id, platform user id and Dolphin Code user id.
- The biggest product risk is only hiding Builder/Code in the frontend. Backend API guards must enforce the same switches.
- The biggest security risk is accidentally treating browser session token as sandbox entry token. Keep capability tokens and entry tokens separate.
- The biggest compatibility risk is SSE/download routes that cannot send headers. Use short capability tokens for those paths only.
- Do not remove legacy JWT until migration metrics show no active legacy Builder sessions.

## Execution Order

1. Task 0 adds builder-owned runtime auth settings and product switches.
2. Tasks 1-3 add provider contracts and make `/auth/login` use builder settings.
3. Task 4 updates backend AuthContext and tenant guard.
4. Tasks 5-6 migrate frontend login modes and enforce product switches on backend.
5. Task 7 confirms Code runtime and control-plane boundaries remain runtime-only.
6. Task 8 cleans aPaaS credential usage.
7. Task 9 aligns admin embedded auth.
8. Task 10 confirms agent runtime entry-token boundary.
9. Task 11 documents migration and local operation.
