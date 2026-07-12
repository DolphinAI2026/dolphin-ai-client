# Builder Control Plane And aPaaS Federated Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Design spec: `docs/superpowers/specs/2026-07-11-builder-control-plane-apaas-federated-auth-design.md`

Phase: `docs/phases/2026-07-11-builder-control-plane-apaas-federated-auth.md`

Supersedes: `docs/superpowers/plans/2026-07-09-builder-ai-unified-auth.md` 中“platform 可继续 local、Control Plane 只负责 runtime”的旧方向。

**Goal:** 让 Builder 同时支持 Control Plane 和 aPaaS 登录，并把两条链路统一转换为可直接访问 Control Plane 的用户 access/refresh token。

**Architecture:** Builder Backend 作为 BFF 编排登录和绑定，浏览器只持有 Builder session。Control Plane OAuth 与 aPaaS federation 均调用 `/api/builder-auth/**`；认证 Provider 保存绑定事实。Builder 使用独立加密 credential store 保存 Control Plane refresh token，所有用户业务请求携带用户 token、`X-Tenant-Id` 和 `X-Auth-Provider: builder-control-plane`。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic v2, httpx, Fernet helpers, Vue 3, Pinia, Vitest, pytest.

---

## Global Constraints

- 当前工作区已有未提交认证改动；执行时先读取并保留这些改动，不得 reset、checkout 或覆盖。
- 登录 Provider 对外名称只使用 `control_plane`、`apaas`；`platform`、`coding` 仅用于一次性兼容迁移。
- aPaaS 与 Control Plane 绑定事实只来自 Control Plane/SDK 响应。
- Builder 不把 binding mode 作为可由浏览器篡改的请求字段；SDK 按受信 client 配置执行最终策略。
- 浏览器不接触 Control Plane refresh token。
- 用户业务请求不得回退 `DOLPHIN_CODE_CONTROL_PLANE_TOKEN`。
- tenant switch 只更新选中的 tenant/header，不调用 Control Plane `switch-tenant`。
- 配置字段均为可选部署项；模板注释必须写明允许值、默认值和生效条件。

### Task 1: Migrate Builder Auth Settings To Canonical Provider Names

**Files:**
- Modify: `backend/app/builder_auth/settings.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/routes/auth/settings.py`
- Modify: `backend/tests/test_builder_auth_settings.py`
- Modify: `backend/tests/test_auth_provider_modes.py`
- Modify: `frontend/src/api/authSettings.ts`

- [ ] Write failing tests for canonical `control_plane|apaas`, legacy `platform|coding` migration, default-provider validation and binding policy validation.
- [ ] Replace the settings model with:

```python
class ApaasBindingSettings(BaseModel):
    mode: Literal["verify_control_plane", "username_auto"] = "verify_control_plane"
    fallback: Literal["verify_control_plane", "disabled"] = "verify_control_plane"

class BuilderAuthSettings(BaseModel):
    default_login_provider: Literal["control_plane", "apaas"] = "control_plane"
    enabled_login_providers: list[Literal["control_plane", "apaas"]] = ["control_plane"]
```

- [ ] Migrate loaded legacy values:
  - `platform` -> `control_plane`
  - platform `mode=coding` -> `control_plane`
  - platform `mode=local` is deprecated and must not remain an enabled production provider.
- [ ] Keep environment-over-database precedence observable, but emit source and legacy-migration diagnostics without secrets.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest \
  backend/tests/test_builder_auth_settings.py \
  backend/tests/test_auth_provider_modes.py -q
```

- [ ] Commit:

```bash
git add backend/app/builder_auth/settings.py backend/app/config.py \
  backend/app/routes/auth/settings.py backend/tests/test_builder_auth_settings.py \
  backend/tests/test_auth_provider_modes.py frontend/src/api/authSettings.ts
git commit -m "feat(auth): canonicalize builder login providers"
```

### Task 2: Add A Typed Control Plane Builder Auth Client

**Files:**
- Create: `backend/app/builder_auth/control_plane_client.py`
- Create: `backend/app/builder_auth/models.py`
- Create: `backend/tests/test_control_plane_builder_auth_client.py`
- Modify: `backend/app/code_runtime/auth.py`

- [ ] Write failing httpx mock tests for OAuth login, refresh, me, federation exchange, bind and revoke.
- [ ] Implement only the approved paths under `/api/builder-auth/**`. Do not call old Control Plane `/api/auth/login-key|authorize|login|token|refresh`.
- [ ] Preserve PKCE/state validation and RSA password encryption from `backend/app/code_runtime/auth.py`, then reduce that module to compatibility imports or remove it after callers migrate.
- [ ] Parse errors by stable `code`, not only HTTP status:

```python
class ControlPlaneAuthError(Exception):
    code: str
    status_code: int
    trace_id: str | None
```

- [ ] The client base URL comes only from server config. Federation calls never accept a browser-supplied Control Plane or aPaaS URL.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_control_plane_builder_auth_client.py -q
```

- [ ] Commit:

```bash
git add backend/app/builder_auth backend/app/code_runtime/auth.py \
  backend/tests/test_control_plane_builder_auth_client.py
git commit -m "feat(auth): add control plane builder auth client"
```

### Task 3: Add Encrypted Control Plane Credential Storage

**Files:**
- Create: `backend/app/models/auth_credential.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database.py`
- Create: `backend/app/builder_auth/credential_store.py`
- Create: `backend/tests/test_control_plane_credential_store.py`

- [ ] Write failing tests for encrypted at-rest values, access/refresh separation, expiry, rotation version, atomic replacement and legacy migration.
- [ ] Add:

```python
class UserAuthCredential(Base):
    __tablename__ = "user_auth_credentials"
    # unique(user_id, provider, credential_type)
```

Fields: `user_id`, `provider`, `credential_type`, `value_enc`, `expires_at`, `rotation_version`, `created_at`, `updated_at`.

- [ ] Use existing `encrypt_password`/`decrypt_password`; repository/service APIs return tokens only to auth orchestration and Control Plane request code.
- [ ] Migrate non-empty `users.coding_access_token` and `users.coding_refresh_token` to provider `control_plane`, verify decryptability, then null legacy fields. Migration is idempotent and never logs values.
- [ ] Stop all new writes to `coding_access_token` / `coding_refresh_token`.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_control_plane_credential_store.py -q
```

- [ ] Commit:

```bash
git add backend/app/models backend/app/database.py backend/app/builder_auth/credential_store.py \
  backend/tests/test_control_plane_credential_store.py
git commit -m "feat(auth): encrypt control plane user credentials"
```

### Task 4: Orchestrate Control Plane Account Login

**Files:**
- Modify: `backend/app/routes/auth/login.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_auth_provider_modes.py`
- Create: `backend/tests/test_control_plane_login_flow.py`

- [ ] Write failing tests proving `login_provider=control_plane` calls the new client, creates/updates a local projection by stable Control Plane user ID, stores encrypted tokens and returns only a Builder session token.
- [ ] Replace `_coding_login_response` and `login_to_coding_control_plane` usage with `ControlPlaneBuilderAuthClient.login`.
- [ ] Local projection rules:
  - primary key is stable Control Plane user ID;
  - username is a display/login snapshot;
  - no automatic merge with an aPaaS local user by username;
  - tenant options come from verified Control Plane response.
- [ ] Remove production `platform_mode=local`. Keep a clearly deprecated migration path only until stored settings are normalized.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest \
  backend/tests/test_auth_provider_modes.py \
  backend/tests/test_control_plane_login_flow.py -q
```

- [ ] Commit:

```bash
git add backend/app/routes/auth/login.py backend/app/schemas.py \
  backend/tests/test_auth_provider_modes.py backend/tests/test_control_plane_login_flow.py
git commit -m "feat(auth): login builder users through control plane"
```

### Task 5: Exchange aPaaS Login For Control Plane Tokens

**Files:**
- Modify: `backend/app/routes/auth/login.py`
- Create: `backend/app/builder_auth/federation.py`
- Create: `backend/tests/test_apaas_control_plane_federation.py`
- Modify: `backend/tests/test_auth_login_error_boundary.py`

- [ ] Write failing tests for existing binding, `username_auto`, `ACCOUNT_BINDING_REQUIRED`, fallback disabled, invalid token, conflict, ambiguous account and upstream unavailable.
- [ ] After the existing aPaaS login obtains a verified token and stable identity, call:

```text
POST /api/builder-auth/federation/apaas/exchange
```

Do not create a local cross-provider binding by username.

- [ ] On `TOKEN_ISSUED`, persist Control Plane credentials and create the Builder session.
- [ ] On `ACCOUNT_BINDING_REQUIRED`, return a structured Builder login result containing only the short-lived challenge and safe aPaaS identity snapshot:

```json
{
  "binding_required": true,
  "binding_challenge": "...",
  "auth_source": "apaas",
  "error_code": "ACCOUNT_BINDING_REQUIRED"
}
```

- [ ] If configured fallback is `disabled`, expose the stable failure and do not launch Control Plane verification UI.
- [ ] Replace the old `/exchange-apaas-token` behavior that directly issues a Builder JWT from a local `apaas_user_id` match. Keep a compatibility route only if it delegates to the new federation service.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest \
  backend/tests/test_apaas_control_plane_federation.py \
  backend/tests/test_auth_login_error_boundary.py -q
```

- [ ] Commit:

```bash
git add backend/app/routes/auth/login.py backend/app/builder_auth/federation.py \
  backend/tests/test_apaas_control_plane_federation.py \
  backend/tests/test_auth_login_error_boundary.py
git commit -m "feat(auth): exchange apaas identities through control plane"
```

### Task 6: Complete Manual Binding And Revoke

**Files:**
- Create: `backend/app/routes/auth/federation.py`
- Modify: `backend/app/routes/auth/__init__.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_auth_federation_routes.py`

- [ ] Write failing route tests for manual bind, expired/replayed challenge, cross-user proof, current-user revoke and re-login after revoke.
- [ ] Add BFF routes:

```text
POST /api/auth/federation/apaas/bind
POST /api/auth/federation/apaas/revoke
```

`bind` performs the Control Plane OAuth proof through the server-side client, then submits the challenge and proof token to Control Plane. It never accepts/stores a plaintext Control Plane password beyond the request lifetime.

- [ ] `revoke` requires the current Builder session, forwards the current user Control Plane token, deletes local Control Plane credentials after confirmed revoke, and invalidates the Builder session.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_auth_federation_routes.py -q
```

- [ ] Commit:

```bash
git add backend/app/routes/auth/federation.py backend/app/routes/auth/__init__.py \
  backend/app/main.py backend/tests/test_auth_federation_routes.py
git commit -m "feat(auth): complete and revoke apaas bindings"
```

### Task 7: Refresh Tokens And Use User Identity For Control Plane Calls

**Files:**
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/app/routes/code_runtime.py`
- Create: `backend/app/builder_auth/control_plane_session.py`
- Modify: `backend/tests/test_code_runtime_service.py`
- Modify: `backend/tests/test_code_runtime_routes.py`
- Create: `backend/tests/test_control_plane_session_refresh.py`

- [ ] Write failing tests proving user requests load the current user's encrypted token, refresh near expiry, persist the rotated refresh token, and send:

```http
Authorization: Bearer <user-access-token>
X-Tenant-Id: <verified-control-plane-tenant-id>
X-Auth-Provider: builder-control-plane
```

- [ ] Remove service-token priority from user-request `_control_plane_headers`. Keep a separate explicit system-task helper for the few operations that are genuinely system-owned.
- [ ] Refresh is serialized per user/provider. If credential persistence fails after upstream rotation, invalidate local credentials and require re-login; never retry with the old refresh token or service token.
- [ ] Tenant switch only changes the selected tenant used in subsequent headers.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest \
  backend/tests/test_control_plane_session_refresh.py \
  backend/tests/test_code_runtime_service.py \
  backend/tests/test_code_runtime_routes.py -q
```

- [ ] Commit:

```bash
git add backend/app/builder_auth/control_plane_session.py \
  backend/app/code_runtime/service.py backend/app/routes/code_runtime.py \
  backend/tests/test_control_plane_session_refresh.py \
  backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py
git commit -m "feat(auth): call control plane with current user tokens"
```

### Task 8: Update Login UI And Binding States

**Files:**
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/views/Login.spec.ts`
- Modify: `frontend/src/stores/user.ts`
- Create: `frontend/src/stores/user.spec.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/authSettings.ts`

- [ ] Write failing component/store tests for configured provider tabs, default selection, binding-required state, manual verification form, disabled fallback, stable errors and successful resume.
- [ ] Display only configured `control_plane` and `apaas` entries. Do not display `coding`, `platform mode` or local production login.
- [ ] When `binding_required=true`, keep the short-lived challenge in memory, render the Control Plane verification step, and clear it on success/cancel/expiry.
- [ ] Do not store Control Plane access/refresh tokens in `localStorage`, Pinia persistence or URL parameters.
- [ ] Run:

```bash
npm --prefix frontend test -- --run \
  src/views/Login.spec.ts \
  src/stores/user.spec.ts
```

- [ ] Commit:

```bash
git add frontend/src/views/Login.vue frontend/src/views/Login.spec.ts \
  frontend/src/stores/user.ts frontend/src/types/index.ts frontend/src/api/authSettings.ts
git commit -m "feat(auth): add federated binding login experience"
```

### Task 9: Add Commented Optional Configuration Templates

**Files:**
- Modify: `README.md`
- Modify: `deploy/customer/backend.env.template`
- Modify: `deploy/k8s/dev.env`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_builder_auth_settings.py`

- [ ] Replace the old single `AUTH_PROVIDER` template section with commented optional settings:

```dotenv
# 可选项。可选值：control_plane、apaas。
# 默认值：control_plane；必须包含在 BUILDER_AUTH_ENABLED_LOGIN_PROVIDERS 中。
BUILDER_AUTH_DEFAULT_LOGIN_PROVIDER=control_plane

# 可选项。逗号分隔，可选值：control_plane、apaas；至少一个。
# 默认值：control_plane。
BUILDER_AUTH_ENABLED_LOGIN_PROVIDERS=control_plane,apaas

# 可选项。可选值：verify_control_plane、username_auto。
# 默认值：verify_control_plane。
BUILDER_AUTH_APAAS_BINDING_MODE=verify_control_plane

# 可选项。可选值：verify_control_plane、disabled。
# 仅在 MODE=username_auto 且自动绑定失败时生效；默认 verify_control_plane。
BUILDER_AUTH_APAAS_BINDING_FALLBACK=verify_control_plane

# 可选项。启用 control_plane 登录或 aPaaS federation 时必填。
DOLPHIN_CODE_CONTROL_PLANE_URL=
```

- [ ] Mark `AUTH_PROVIDER`, fixed Control Plane username/password and user-request service token fallback as deprecated migration-only options.
- [ ] Add tests that comments/defaults stay aligned with Pydantic settings.
- [ ] Run:

```bash
backend/venv/bin/python -m pytest backend/tests/test_builder_auth_settings.py -q
git diff --check
```

- [ ] Commit:

```bash
git add README.md deploy/customer/backend.env.template deploy/k8s/dev.env \
  backend/app/config.py backend/tests/test_builder_auth_settings.py
git commit -m "docs(auth): document optional federated auth settings"
```

### Task 10: End-To-End Verification And Compatibility Cleanup

- [ ] Run backend auth and Control Plane call tests:

```bash
backend/venv/bin/python -m pytest \
  backend/tests/test_builder_auth_settings.py \
  backend/tests/test_auth_provider_modes.py \
  backend/tests/test_control_plane_builder_auth_client.py \
  backend/tests/test_control_plane_login_flow.py \
  backend/tests/test_apaas_control_plane_federation.py \
  backend/tests/test_auth_federation_routes.py \
  backend/tests/test_control_plane_session_refresh.py \
  backend/tests/test_auth_switch_tenant.py \
  backend/tests/test_code_runtime_service.py \
  backend/tests/test_code_runtime_routes.py -q
```

- [ ] Run frontend tests and build:

```bash
npm --prefix frontend test -- --run src/views/Login.spec.ts
npm --prefix frontend run build
```

- [ ] Run a three-service E2E matrix:
  - Control Plane login.
  - aPaaS existing binding.
  - aPaaS `username_auto`.
  - aPaaS `verify_control_plane`.
  - refresh rotation.
  - legal and illegal tenant switch.
  - revoke and subsequent denial.
- [ ] Confirm no Control Plane token is present in browser storage, logs or error responses.
- [ ] Remove compatibility code only after the E2E matrix passes; otherwise keep it explicitly deprecated with no user-request service-token fallback.
- [ ] Run `agentic-coding-review` against the design spec and record any cross-repo deviation in product-design.
