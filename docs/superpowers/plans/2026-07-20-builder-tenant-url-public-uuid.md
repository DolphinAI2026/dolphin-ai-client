# Builder Tenant URL Public UUID Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Builder 的全部租户上下文页面增加显式 `tenantId=${tenantPublicId}`，支持授权租户动态切换，并发布包含既有 Code Bearer 修复的可验证单镜像版本。

**Architecture:** 数据层为 `Tenant` 增加 nullable、唯一的公共 UUID；当前 writer 使用 UUID v4，历史或旧 writer 的 NULL 使用固定 namespace UUID v5 严格补齐。前端以 JWT `tid` 为服务端租户权威，以 URL UUID 为显式导航上下文；跨租户时先取得候选 Token，再用显式 Authorization 调 `/auth/me` 验证数字 ID 与 UUID，最后提交浏览器状态。发布继续使用现有单镜像 StatefulSet，通过不可变 digest、逐 Pod imageID/build SHA、Edge smoke 形成证据。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy Async、Pytest、Vue 3、Pinia、Vue Router、TypeScript、Vitest、Playwright 1.61.1、Bash、Docker、GitLab CI、Kubernetes。

## Global Constraints

- URL query key 固定为 `tenantId`，值为小写、连字符 UUID。
- `tenants.id` 和 JWT `tid` 继续使用数字 ID；UUID 不是授权凭据。
- `POST /auth/switch-tenant` 保持现有 `Token` 响应，不新增 switch DTO 或 `tenant_epoch`。
- 候选 `/auth/me` 的数字 ID 与 UUID 都匹配前，不得覆盖源 token、user 或 URL。
- `current_app` 不是本 phase 的租户权威，不新增 `/auth/me` slot 同步。
- `Tenant.public_id` 在本 phase 保持 nullable；已有非空值永不重写。
- 当前 writer 生成 UUID v4；NULL reconciliation 使用 namespace `13ad9ef8-0005-5fc9-a95d-ac66f5c431ed` 的 UUID v5。
- 平台管理、租户管理、桌面设置等 `tenantContext: none` 路由不得保留 `tenantId`。
- Code 外层 URL 保留 `tenantId` 和 `agent`；Runtime 上游 URL 不接收 `tenantId`。
- E2E Playwright 唯一 owner 是根 `package.json`，精确版本 `1.61.1`。
- 构建 SHA 固定来自 `git rev-parse HEAD` 或 `CI_COMMIT_SHA`，并注入 `VITE_BUILD_SHA`。
- 发布部署使用 `${BUILDER_IMAGE_REPOSITORY}@${digest}`，backend 与 `copy-frontend-dist` 必须同 digest。
- 不新增浏览器事件 endpoint、专用 auth metrics registry 或平行发布入口。
- 所有生产代码遵循 RED -> GREEN -> REFACTOR；每个任务独立提交。

---

### Task 1: Tenant 公共 UUID 数据层与严格 reconciliation

**Files:**
- Create: `backend/app/tenant_public_id.py`
- Modify: `backend/app/models/tenant.py`
- Modify: `backend/app/database.py`
- Create: `backend/tests/test_tenant_public_id.py`
- Create: `backend/tests/test_tenant_public_id_migration.py`
- Create: `backend/tests/integration/run_tenant_public_id_dialects.sh`
- Modify: `.gitlab-ci.yml`

**Interfaces:**
- Produces: `new_tenant_public_id() -> str`
- Produces: `historical_tenant_public_id(tenant_id: int) -> str`
- Produces: `async reconcile_tenant_public_ids(conn) -> TenantPublicIdReconciliation`
- Produces: `async ensure_tenant_public_id(session: AsyncSession, tenant: Tenant) -> str`
- Produces: `python -m app.tenant_public_id reconcile --verify-only-after-write`

- [ ] **Step 1: Write failing model/default tests**

```python
def test_new_tenant_public_id_is_uuid4():
    value = new_tenant_public_id()
    parsed = UUID(value)
    assert parsed.version == 4
    assert value == str(parsed)

def test_historical_tenant_public_id_is_stable_uuid5():
    assert historical_tenant_public_id(42) == historical_tenant_public_id(42)
    assert UUID(historical_tenant_public_id(42)).version == 5
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && python -m pytest -q tests/test_tenant_public_id.py`

Expected: FAIL because `app.tenant_public_id` and `Tenant.public_id` do not exist.

- [ ] **Step 3: Implement UUID helpers and nullable model field**

```python
TENANT_PUBLIC_ID_NAMESPACE = UUID("13ad9ef8-0005-5fc9-a95d-ac66f5c431ed")

def new_tenant_public_id() -> str:
    return str(uuid4())

def historical_tenant_public_id(tenant_id: int) -> str:
    return str(uuid5(TENANT_PUBLIC_ID_NAMESPACE, f"tenant:{int(tenant_id)}"))

public_id: Mapped[Optional[str]] = mapped_column(
    String(36),
    nullable=True,
    unique=True,
    index=True,
    default=new_tenant_public_id,
)
```

- [ ] **Step 4: Verify GREEN**

Run: `cd backend && python -m pytest -q tests/test_tenant_public_id.py`

Expected: PASS.

- [ ] **Step 5: Write failing reconciliation tests**

```python
@pytest.mark.asyncio
async def test_reconcile_adds_nullable_column_and_backfills_stable_uuid5(sqlite_engine):
    result = await run_reconciliation(sqlite_engine, legacy_rows=[(1, "a"), (2, "b")])
    assert result.null_count == 0
    assert result.filled_count == 2
    assert await public_ids(sqlite_engine) == [
        historical_tenant_public_id(1),
        historical_tenant_public_id(2),
    ]

@pytest.mark.asyncio
async def test_reconcile_fills_null_inserted_by_old_writer_without_changing_existing_value(sqlite_engine):
    original = str(uuid4())
    await seed_public_id(sqlite_engine, tenant_id=1, public_id=original)
    await old_writer_insert(sqlite_engine, tenant_id=2, public_id=None)
    await reconcile(sqlite_engine)
    assert await public_id(sqlite_engine, 1) == original
    assert await public_id(sqlite_engine, 2) == historical_tenant_public_id(2)
```

- [ ] **Step 6: Verify migration RED**

Run: `cd backend && python -m pytest -q tests/test_tenant_public_id_migration.py`

Expected: FAIL because strict reconciliation is missing.

- [ ] **Step 7: Implement strict expand/reconcile and CLI**

```python
@dataclass(frozen=True)
class TenantPublicIdReconciliation:
    scanned_count: int
    filled_count: int
    null_count: int
    conflict_tenant_ids: tuple[int, ...]

async def reconcile_tenant_public_ids(conn) -> TenantPublicIdReconciliation:
    await _ensure_nullable_column(conn)
    rows = (await conn.execute(text(
        "SELECT id, public_id FROM tenants ORDER BY id"
    ))).mappings().all()
    for row in rows:
        if row["public_id"] is None:
            await conn.execute(
                text("UPDATE tenants SET public_id=:public_id WHERE id=:id AND public_id IS NULL"),
                {"id": row["id"], "public_id": historical_tenant_public_id(row["id"])},
            )
    await _validate_uuid_values_and_conflicts(conn)
    await _ensure_unique_index(conn)
    return await _reconciliation_result(conn, scanned_count=len(rows))
```

`init_db()` 在通用 best-effort DDL 之前调用该 helper；CLI 复用同一函数并只输出计数和冲突数字 ID。

- [ ] **Step 8: Verify SQLite GREEN**

Run: `cd backend && python -m pytest -q tests/test_tenant_public_id.py tests/test_tenant_public_id_migration.py`

Expected: PASS.

- [ ] **Step 9: Add real MySQL/PostgreSQL runner and CI job**

```bash
docker run -d --rm --name "$mysql_name" -e MYSQL_ROOT_PASSWORD=test -e MYSQL_DATABASE=builder mysql:8.4
docker run -d --rm --name "$pg_name" -e POSTGRES_PASSWORD=test -e POSTGRES_DB=builder postgres:16
trap 'docker rm -f "$mysql_name" "$pg_name" >/dev/null 2>&1 || true' EXIT
run_dialect mysql "$mysql_url"
echo "mysql=passed"
run_dialect postgresql "$postgres_url"
echo "postgresql=passed"
```

GitLab job 使用 Docker CLI image + DinD service，运行固定 runner 并保留三种方言通过标识。

- [ ] **Step 10: Verify dialect runner**

Run: `cd backend && docker info >/dev/null && bash tests/integration/run_tenant_public_id_dialects.sh`

Expected: `sqlite=passed`, `mysql=passed`, `postgresql=passed`.

- [ ] **Step 11: Commit**

```bash
git add backend/app/tenant_public_id.py backend/app/models/tenant.py backend/app/database.py \
  backend/tests/test_tenant_public_id.py backend/tests/test_tenant_public_id_migration.py \
  backend/tests/integration/run_tenant_public_id_dialects.sh .gitlab-ci.yml
git commit -m "feat(auth): add tenant public UUID reconciliation"
```

### Task 2: Auth UUID 投影与停用租户 token 拒绝

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/auth/login.py`
- Modify: `backend/app/routes/auth/tenants_admin.py`
- Modify: `backend/app/deps.py`
- Modify: `backend/tests/test_auth_switch_tenant.py`
- Create: `backend/tests/test_tenant_url_auth.py`

**Interfaces:**
- Consumes: `ensure_tenant_public_id(session, tenant) -> str`
- Produces: `UserInfo.tenant_public_id: str | None`
- Produces: `TenantOption.tenant_public_id: str`
- Preserves: `POST /auth/switch-tenant -> Token`

- [ ] **Step 1: Write failing schema and endpoint tests**

```python
@pytest.mark.asyncio
async def test_me_returns_current_tenant_public_id(client, tenant_user_token, tenant):
    response = await client.get("/api/auth/me", headers=bearer(tenant_user_token))
    assert response.status_code == 200
    assert response.json()["tenant_public_id"] == tenant.public_id

@pytest.mark.asyncio
async def test_switch_tenant_response_remains_token_only(client, token, target_tenant):
    response = await client.post(
        "/api/auth/switch-tenant",
        headers=bearer(token),
        json={"tenant_id": target_tenant.id},
    )
    assert set(response.json()) == {"access_token", "token_type"}
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && python -m pytest -q tests/test_tenant_url_auth.py tests/test_auth_switch_tenant.py`

Expected: FAIL on missing UUID fields.

- [ ] **Step 3: Add additive schemas and projection helpers**

```python
class UserInfo(BaseModel):
    # existing fields...
    tenant_public_id: Optional[str] = None

class TenantOption(BaseModel):
    tenant_id: int
    tenant_name: str
    tenant_code: str
    tenant_public_id: str

async def _tenant_option(db: AsyncSession, tenant: Tenant) -> TenantOption:
    return TenantOption(
        tenant_id=tenant.id,
        tenant_name=tenant.tenant_name,
        tenant_code=tenant.tenant_code,
        tenant_public_id=await ensure_tenant_public_id(db, tenant),
    )
```

替换 login、多租户选择、`/auth/me/tenants` 和 `/auth/me` 的所有 `TenantOption`/`UserInfo` 构造点。

- [ ] **Step 4: Add inactive tenant token tests**

```python
@pytest.mark.asyncio
async def test_header_auth_rejects_disabled_tenant_token(...):
    await disable_tenant(db_session, tenant.id)
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(credentials_for(token), db_session)
    assert exc.value.status_code == 403

@pytest.mark.asyncio
async def test_query_token_auth_rejects_disabled_tenant_token(...):
    await disable_tenant(db_session, tenant.id)
    with pytest.raises(ValueError, match="Tenant is inactive"):
        await get_auth_context_from_token(token)
```

- [ ] **Step 5: Verify RED for inactive token**

Run: `cd backend && python -m pytest -q tests/test_tenant_url_auth.py -k inactive`

Expected: FAIL because platform-admin and membership paths do not verify `Tenant.status`.

- [ ] **Step 6: Implement shared active-tenant check**

```python
async def _require_active_tenant(db: AsyncSession, tenant_id: int) -> Tenant:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.status == 1))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=403, detail="目标租户不可用")
    return tenant
```

两条认证路径在任何 tenant-scoped return 前调用该 helper；token 字符串路径把 HTTP 错误归一化为 `ValueError("Tenant is inactive")`。

- [ ] **Step 7: Verify GREEN**

Run: `cd backend && python -m pytest -q tests/test_tenant_public_id.py tests/test_tenant_public_id_migration.py tests/test_tenant_url_auth.py tests/test_auth_switch_tenant.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/auth/login.py \
  backend/app/routes/auth/tenants_admin.py backend/app/deps.py \
  backend/tests/test_auth_switch_tenant.py backend/tests/test_tenant_url_auth.py
git commit -m "feat(auth): project tenant public UUIDs"
```

### Task 3: 候选 Token 验证与跨标签页收敛

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/utils/request.ts`
- Modify: `frontend/src/api/auth.ts`
- Modify: `frontend/src/stores/user.ts`
- Create: `frontend/src/utils/request.explicitAuth.spec.ts`
- Create: `frontend/src/stores/user.tenantSwitch.spec.ts`

**Interfaces:**
- Produces: `authApi.getMeWithToken(candidateToken: string, signal?: AbortSignal): Promise<User>`
- Produces: `userStore.switchTenantContext(targetTenantId: number, targetTenantPublicId: string, destination: string): Promise<void>`
- Produces: storage-event alignment guarded by `storageAlignmentGeneration`

- [ ] **Step 1: Write failing explicit Authorization test**

```typescript
it('preserves an explicit Authorization header over localStorage token', async () => {
  localStorage.setItem('token', 'source-token')
  const config = await runRequestInterceptor({
    headers: { Authorization: 'Bearer candidate-token' },
  })
  expect(config.headers.Authorization).toBe('Bearer candidate-token')
})
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm exec -- vitest run src/utils/request.explicitAuth.spec.ts`

Expected: FAIL because the interceptor overwrites the header.

- [ ] **Step 3: Implement explicit auth precedence**

```typescript
const existingAuthorization = config.headers?.Authorization
if (!existingAuthorization) {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
}
```

`getMeWithToken` passes `{ headers: { Authorization: `Bearer ${candidateToken}` }, signal }`.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend && npm exec -- vitest run src/utils/request.explicitAuth.spec.ts`

Expected: PASS.

- [ ] **Step 5: Write failing candidate commit tests**

```typescript
it('keeps source state when candidate /auth/me UUID mismatches', async () => {
  seedSourceSession('source-token', sourceUser)
  mockSwitchToken('candidate-token')
  mockCandidateMe({ ...targetUser, tenant_public_id: 'wrong-uuid' })
  await expect(store.switchTenantContext(2, targetUuid, targetPath)).rejects.toThrow()
  expect(localStorage.getItem('token')).toBe('source-token')
  expect(store.user).toEqual(sourceUser)
})

it('commits token and user only after candidate numeric ID and UUID match', async () => {
  mockSwitchToken('candidate-token')
  mockCandidateMe({ ...targetUser, tenant_id: 2, tenant_public_id: targetUuid })
  await store.switchTenantContext(2, targetUuid, targetPath)
  expect(localStorage.getItem('token')).toBe('candidate-token')
  expect(store.user?.tenant_public_id).toBe(targetUuid)
})
```

- [ ] **Step 6: Verify switch RED**

Run: `cd frontend && npm exec -- vitest run src/stores/user.tenantSwitch.spec.ts`

Expected: FAIL because `switchTenantContext` is missing and `switchTenant` commits too early.

- [ ] **Step 7: Implement candidate validation and side-effect adapter**

```typescript
const candidate = await authApi.switchTenant(targetTenantId)
const candidateUser = await authApi.getMeWithToken(candidate.access_token)
if (
  candidateUser.tenant_id !== targetTenantId
  || candidateUser.tenant_public_id !== targetTenantPublicId
) {
  throw new Error('tenant candidate mismatch')
}
setToken(candidate.access_token)
user.value = candidateUser
try { localStorage.removeItem('ai-builder-tabs-v1') } catch {}
window.location.replace(destination)
```

保留 `switchTenant` 作为兼容 wrapper，内部从 `availableTenants` 找 UUID 后调用稳定接口。

- [ ] **Step 8: Add storage-event race tests and implementation**

```typescript
it('drops a stale event-token response after a newer token wins', async () => {
  const slowB = deferred<User>()
  mockMeWithToken('token-b', slowB.promise)
  fireStorageEvent('token-b')
  mockMeWithToken('token-a', Promise.resolve(userA))
  localStorage.setItem('token', 'token-a')
  fireStorageEvent('token-a')
  slowB.resolve(userB)
  await flushPromises()
  expect(store.user).toEqual(userA)
})
```

实现递增 generation、AbortController、event token 精确比较和目标模式首页 `replace`。

- [ ] **Step 9: Verify GREEN**

Run: `cd frontend && npm exec -- vitest run src/utils/request.explicitAuth.spec.ts src/stores/user.tenantSwitch.spec.ts`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/utils/request.ts frontend/src/api/auth.ts \
  frontend/src/stores/user.ts frontend/src/utils/request.explicitAuth.spec.ts \
  frontend/src/stores/user.tenantSwitch.spec.ts
git commit -m "feat(auth): validate tenant switch candidates"
```

### Task 4: Tenant URL resolver 与路由挂载门

**Files:**
- Create: `frontend/src/router/tenantUrlGuard.ts`
- Create: `frontend/src/router/tenantUrlGuard.spec.ts`
- Create: `frontend/src/router/meta.d.ts`
- Modify: `frontend/src/router/index.ts`

**Interfaces:**
- Consumes: `userStore.switchTenantContext(...)`
- Produces: `normalizeTenantPublicId(raw: unknown): string | null`
- Produces: `classifyTenantTarget(input): TenantResolutionDecision`
- Produces: `resolveTenantUrl(to, userStore, modeStore): Promise<RouteLocationRaw | true | false>`

- [ ] **Step 1: Write failing pure resolver tests**

```typescript
it.each([
  ['missing', undefined, { kind: 'canonicalize' }],
  ['same', currentUuid, { kind: 'continue' }],
  ['accessible other', targetUuid, { kind: 'switch' }],
  ['invalid', '123', { kind: 'reject', reason: 'invalid' }],
  ['unknown', unknownUuid, { kind: 'reject', reason: 'inaccessible' }],
])('%s tenant target', (_name, raw, expected) => {
  expect(classifyTenantTarget({
    rawTenantId: raw,
    currentTenantPublicId: currentUuid,
    availableTenants,
  })).toMatchObject(expected)
})
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm exec -- vitest run src/router/tenantUrlGuard.spec.ts`

Expected: FAIL because the resolver module is missing.

- [ ] **Step 3: Implement pure classification**

```typescript
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

export function normalizeTenantPublicId(raw: unknown): string | null {
  const value = Array.isArray(raw) ? raw[0] : raw
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return UUID_RE.test(normalized) ? normalized : null
}
```

返回 union：`continue | canonicalize | switch | reject | remove`，不在纯函数中访问 Router、Pinia 或 DOM。

- [ ] **Step 4: Add route classification tests**

```typescript
it('requires every authenticated route to declare tenantContext', () => {
  const missing = router.getRoutes().filter(
    route => route.meta.requiresAuth && !route.meta.tenantContext,
  )
  expect(missing.map(route => route.path)).toEqual([])
})
```

- [ ] **Step 5: Verify route meta RED**

Run: `cd frontend && npm exec -- vitest run src/router/tenantUrlGuard.spec.ts -t tenantContext`

Expected: FAIL listing unclassified routes.

- [ ] **Step 6: Add typed route metadata and classify all routes**

```typescript
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    tenantContext?: 'required' | 'none'
  }
}
```

所有受保护业务路由设 `required`；`/platform-admin/**`、`/admin/tenants`、`/desktop-setup`、`/desktop-unavailable` 设 `none`；`/code` 父路由设 `required` 供子路由继承。

- [ ] **Step 7: Integrate resolver before permission/page loading**

```typescript
if (to.meta.requiresAuth) {
  const tenantResolution = await resolveTenantUrl(to, userStore, modeStore)
  if (tenantResolution !== true) {
    next(tenantResolution)
    return
  }
}
```

缺 UUID 使用 replace 保留 path/query/hash；目标其他租户写 30 秒 marker 后调用 store；非法/无权目标进入当前模式首页并携带当前 UUID。

- [ ] **Step 8: Verify GREEN**

Run: `cd frontend && npm exec -- vitest run src/router/tenantUrlGuard.spec.ts`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/router/tenantUrlGuard.ts frontend/src/router/tenantUrlGuard.spec.ts \
  frontend/src/router/meta.d.ts frontend/src/router/index.ts
git commit -m "feat(router): enforce tenant UUID URLs"
```

### Task 5: 登录、多租户选择、侧边栏与 Code URL 集成

**Files:**
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/views/TenantSelect.vue`
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Modify: `frontend/src/composables/railSessions.ts`
- Modify: `frontend/src/views/CodeConversationPage.vue`
- Modify: `frontend/src/views/Login.spec.ts`
- Modify: `frontend/src/components/v2/RailSidebar.spec.ts`
- Modify: `frontend/src/composables/railSessions.spec.ts`
- Modify: `frontend/src/views/CodeConversationPage.spec.ts`
- Modify: `frontend/src/views/codeFrameLifecycle.spec.ts`

**Interfaces:**
- Consumes: `TenantOption.tenant_public_id`
- Consumes: `switchTenantContext(targetTenantId, targetUuid, destination)`
- Preserves: existing `selection_token + tenant_id` request body

- [ ] **Step 1: Write failing login and selection tests**

```typescript
it('auto-selects the tenant whose public UUID matches the redirect', () => {
  const target = resolveLoginTenant(
    '/code/session?tenantId=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    tenants,
  )
  expect(target?.tenant_id).toBe(2)
})

it('never submits tenant_public_id in TenantSelectRequest', () => {
  expect(authSource).toContain('{ selection_token: selectionToken, tenant_id: tenantId }')
  expect(authSource).not.toContain('tenant_public_id:')
})
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm exec -- vitest run src/views/Login.spec.ts`

Expected: FAIL because redirect UUID is not consumed.

- [ ] **Step 3: Implement safe redirect target mapping**

```typescript
const redirect = safeRedirectPath(route.query.redirect)
const targetUuid = tenantIdFromRedirect(redirect)
const targetTenant = result.tenants?.find(
  tenant => tenant.tenant_public_id === targetUuid,
)
```

登录多租户分支把原 redirect 和租户列表传给 TenantSelect；TenantSelect 在目标存在时自动调用现有数字 ID 选择接口，否则保持人工选择或拒绝。

- [ ] **Step 4: Write failing sidebar tests**

```typescript
it('uses tenant_public_id as option value and enters the current mode home', () => {
  expect(sidebarSource).toContain('tenant.tenant_public_id')
  expect(sidebarSource).toContain('MODE_META[currentMode.value].home')
})
```

- [ ] **Step 5: Implement sidebar UUID switch**

```typescript
async function selectTenant(targetPublicId: string) {
  const tenant = tenantOptions.value.find(item => item.tenant_public_id === targetPublicId)
  if (!tenant || tenant.tenant_id === user.tenantId) return
  const destination = withTenantId(MODE_META[currentMode.value].home, targetPublicId)
  await user.switchTenantContext(tenant.tenant_id, targetPublicId, destination)
}
```

- [ ] **Step 6: Add Code URL preservation tests**

```typescript
it('preserves tenantId while changing agent', () => {
  expect(nextAgentQuery({ tenantId: tenantUuid, agent: 'old' }, 'new')).toEqual({
    tenantId: tenantUuid,
    agent: 'new',
  })
})
```

Rail session targets and Code page `router.replace` operations copy existing query and only replace/remove `agent`.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
cd frontend
npm exec -- vitest run \
  src/views/Login.spec.ts \
  src/components/v2/RailSidebar.spec.ts \
  src/composables/railSessions.spec.ts \
  src/views/CodeConversationPage.spec.ts \
  src/views/codeFrameLifecycle.spec.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/Login.vue frontend/src/views/TenantSelect.vue \
  frontend/src/components/v2/RailSidebar.vue frontend/src/composables/railSessions.ts \
  frontend/src/views/CodeConversationPage.vue frontend/src/views/Login.spec.ts \
  frontend/src/components/v2/RailSidebar.spec.ts frontend/src/composables/railSessions.spec.ts \
  frontend/src/views/CodeConversationPage.spec.ts frontend/src/views/codeFrameLifecycle.spec.ts
git commit -m "feat(ui): preserve tenant UUID navigation"
```

### Task 6: Build SHA、单一 Playwright owner 与自包含浏览器 E2E

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/index.html`
- Modify: `deploy/docker/Dockerfile`
- Create: `tests/e2e/builder-tenant-url-public-uuid-fixture.sh`
- Create: `tests/e2e/builder-tenant-url-public-uuid.spec.mjs`
- Create: `backend/tests/test_tenant_url_build_contract.py`

**Interfaces:**
- Produces: `<meta name="builder-build-sha" content="${BUILD_SHA}">`
- Produces: `BROWSER_CHANNEL=chromium|msedge bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh`

- [ ] **Step 1: Write failing build contract tests**

```python
def test_root_package_is_only_playwright_owner(repo_root):
    root = json.loads((repo_root / "package.json").read_text())
    frontend = json.loads((repo_root / "frontend/package.json").read_text())
    assert root["devDependencies"]["playwright"] == "1.61.1"
    assert "playwright" not in frontend.get("dependencies", {})

def test_dockerfile_passes_vite_build_sha(repo_root):
    text = (repo_root / "deploy/docker/Dockerfile").read_text()
    assert "ARG VITE_BUILD_SHA" in text
    assert "ENV VITE_BUILD_SHA=${VITE_BUILD_SHA}" in text
```

- [ ] **Step 2: Verify RED**

Run: `cd backend && python -m pytest -q tests/test_tenant_url_build_contract.py`

Expected: FAIL on duplicate/versioned Playwright and missing Docker build arg.

- [ ] **Step 3: Consolidate Playwright and add build meta**

```json
{
  "devDependencies": {
    "@tauri-apps/cli": "^2.11.2",
    "playwright": "1.61.1"
  }
}
```

```html
<meta name="builder-build-sha" content="%VITE_BUILD_SHA%">
```

Docker frontend stage adds:

```dockerfile
ARG VITE_BUILD_SHA
ENV VITE_BUILD_SHA=${VITE_BUILD_SHA}
RUN test -n "${VITE_BUILD_SHA}" && node_modules/.bin/vite build
```

- [ ] **Step 4: Verify build contract GREEN**

Run: `cd backend && python -m pytest -q tests/test_tenant_url_build_contract.py`

Expected: PASS.

- [ ] **Step 5: Write E2E fixture and scenario**

Fixture computes:

```bash
BUILD_SHA="$(git rev-parse HEAD)"
VITE_BUILD_SHA="$BUILD_SHA" npm --prefix frontend run build
meta_sha="$(sed -n 's/.*name=\"builder-build-sha\" content=\"\\([0-9a-f]\\{40\\}\\)\".*/\\1/p' frontend/dist/index.html)"
[ "$meta_sha" = "$BUILD_SHA" ]
```

它创建 SQLite fixtures，启动 backend 和构建产物静态服务，传递当前/目标/停用租户 UUID、Code session 和 Agent session，并 trap 清理。

Playwright 场景断言：旧 URL canonicalize、授权跨租户只 switch 一次、无权目标无业务请求、两个标签页最终收敛、Code activate 只走 `/api/code/sessions/.../activate` 且无 401。

- [ ] **Step 6: Verify Chromium and Edge**

Run:

```bash
npm ci
npm --prefix frontend ci
npm exec -- playwright install chromium msedge
BROWSER_CHANNEL=chromium bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh
BROWSER_CHANNEL=msedge bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh
```

Expected: both PASS; logs contain the exact build SHA and no credentials.

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json frontend/package.json frontend/package-lock.json \
  frontend/index.html deploy/docker/Dockerfile tests/e2e/builder-tenant-url-public-uuid-fixture.sh \
  tests/e2e/builder-tenant-url-public-uuid.spec.mjs backend/tests/test_tenant_url_build_contract.py
git commit -m "test(e2e): verify tenant UUID deep links"
```

### Task 7: 不可变 digest 发布与逐 Pod smoke

**Files:**
- Create: `scripts/verify_builder_tenant_url_smoke.sh`
- Modify: `scripts/deploy_online_latest_kubesphere.sh`
- Modify: `.gitlab-ci.yml`
- Create: `tests/release/test_builder_tenant_url_smoke.sh`

**Interfaces:**
- Consumes: `BUILDER_IMAGE=${BUILDER_IMAGE_REPOSITORY}@${digest}`
- Produces: release completion only after `release_builder_browser_smoke`
- Produces: per-Pod backend/init imageID and web-sidecar build SHA proof

- [ ] **Step 1: Write failing shell contract tests**

```bash
assert_contains '.gitlab-ci.yml' '--metadata-file build/metadata.json'
assert_contains '.gitlab-ci.yml' 'release_builder_browser_smoke:'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'initContainerStatuses'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'builder-build-sha'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'msedge'
```

- [ ] **Step 2: Verify RED**

Run: `bash tests/release/test_builder_tenant_url_smoke.sh`

Expected: FAIL because helper/job/digest chain do not exist.

- [ ] **Step 3: Emit and deploy immutable digest**

Build job:

```bash
buildctl-daemonless.sh build ... --metadata-file build/metadata.json
digest="$(python3 -c 'import json; print(json.load(open("build/metadata.json"))["containerimage.digest"])')"
printf 'BUILDER_IMAGE=%s@%s\n' "${BUILDER_IMAGE_REPOSITORY}" "${digest}" > build/release.env
printf 'DEPLOYED_REVISION=%s\n' "${CI_COMMIT_SHA}" >> build/release.env
```

Deployment job uses the digest value for backend and dist initContainer.

- [ ] **Step 4: Implement shared smoke helper**

```bash
backend_image_id="$(pod_status_image_id "$pod" "$KUBE_BACKEND_CONTAINER")"
init_image_id="$(pod_init_status_image_id "$pod" "$KUBE_DIST_INIT_CONTAINER")"
[ "$(normalize_digest "$backend_image_id")" = "$expected_digest" ]
[ "$(normalize_digest "$init_image_id")" = "$expected_digest" ]
pod_html="$(kubectl -n "$KUBE_NAMESPACE" exec "$pod" -c "$KUBE_WEB_CONTAINER" -- \
  wget -qO- http://127.0.0.1/ai-builder/)"
[ "$(extract_build_sha "$pod_html")" = "$DEPLOYED_REVISION" ]
```

随后在一个 Ready Pod 执行 reconciliation CLI，使用受控账号登录/选择租户/候选 token 验证，并用根 Playwright 1.61.1 Edge 打开目标 Code 深链接。

- [ ] **Step 5: Wire existing release owners**

`scripts/deploy_online_latest_kubesphere.sh` 在 `rollout_and_verify` 后调用 helper。

GitLab:

```yaml
release_builder_browser_smoke:
  stage: release
  needs:
    - job: release_and_update_server
      artifacts: true
  image: mcr.microsoft.com/playwright:v1.61.1-noble
  script:
    - npm ci
    - npm exec -- playwright install msedge
    - bash scripts/verify_builder_tenant_url_smoke.sh
```

job 安装固定 `kubectl 1.30.7`；缺少 Kubeconfig、测试账号、目标租户、Code session 或 Edge 时失败。

- [ ] **Step 6: Verify GREEN**

Run:

```bash
bash -n scripts/verify_builder_tenant_url_smoke.sh scripts/deploy_online_latest_kubesphere.sh
bash tests/release/test_builder_tenant_url_smoke.sh
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/verify_builder_tenant_url_smoke.sh scripts/deploy_online_latest_kubesphere.sh \
  .gitlab-ci.yml tests/release/test_builder_tenant_url_smoke.sh
git commit -m "ci(release): gate tenant UUID deployment"
```

### Task 8: 全量验证、Builder 投影同步与发布准备

**Files:**
- Modify only if implementation changed formal contracts:
  - `docs/superpowers/specs/2026-07-20-builder-tenant-url-public-uuid-design.md`
  - `docs/solutions/l3/business/*.md`
  - `docs/assets/builder/**`

**Interfaces:**
- Consumes all prior task outputs.
- Produces clean branch, passing review, and publish-ready digest pipeline.

- [ ] **Step 1: Run fixed backend verification**

```bash
cd backend
python -m pytest -q \
  tests/test_tenant_public_id.py \
  tests/test_tenant_public_id_migration.py \
  tests/test_tenant_url_auth.py \
  tests/test_auth_switch_tenant.py \
  tests/test_tenant_url_build_contract.py
bash tests/integration/run_tenant_public_id_dialects.sh
```

Expected: all tests and three dialect markers pass.

- [ ] **Step 2: Run fixed frontend verification**

```bash
cd frontend
npm ci
npm exec -- vitest run \
  src/router/tenantUrlGuard.spec.ts \
  src/stores/user.tenantSwitch.spec.ts \
  src/utils/request.explicitAuth.spec.ts \
  src/views/codeFrameLifecycle.spec.ts \
  src/views/Login.spec.ts \
  src/components/v2/RailSidebar.spec.ts \
  src/composables/railSessions.spec.ts \
  src/views/CodeConversationPage.spec.ts \
  --reporter=verbose
VITE_BUILD_SHA="$(git -C .. rev-parse HEAD)" npm run build
```

Expected: all tests pass and build emits exact SHA meta.

- [ ] **Step 3: Run both browser channels**

```bash
cd ..
npm ci
npm exec -- playwright install chromium msedge
BROWSER_CHANNEL=chromium bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh
BROWSER_CHANNEL=msedge bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh
```

Expected: both PASS with zero Code activation 401.

- [ ] **Step 4: Run release contract and Builder doctors**

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
agentic-spec doctor --workspace "$(pwd)"
git diff --check
```

Expected: PASS and clean diagnostics.

- [ ] **Step 5: Request broad code review and fix Critical/Important findings**

Review scope is the branch merge-base through HEAD, with special attention to auth, migration, router races, shell secret handling, and deployment rollback.

- [ ] **Step 6: Commit any review fixes**

```bash
git add -u
git commit -m "fix: address tenant URL review findings"
```

- [ ] **Step 7: Confirm clean state**

Run: `git status --short`

Expected: no output.
