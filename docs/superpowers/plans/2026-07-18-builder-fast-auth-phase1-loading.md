# Builder 首屏性能 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 去掉 Code 应用首屏的重复应用查询和 Runtime 历史 fan-out，使应用页与左栏共享一次上游请求，并让 `/code/rail/history` 只读取 Builder 数据库。

**Architecture:** 前端新增 tenant-scoped Code 应用缓存 Store，应用页和 Rail Sidebar 通过同一 singleflight 请求读取数据。后端在 Runtime 会话创建、激活时持久化轻量快照，Rail History 一次查询 Builder 数据库组装结果，不再同步访问任何 Runtime；现有单沙箱 Runtime API 保留给用户主动操作时使用。

**Tech Stack:** Vue 3、Pinia 3、TypeScript 5.9、Vitest 4、FastAPI、SQLAlchemy Async、SQLite/MySQL、pytest。

**Design spec:** `docs/superpowers/specs/2026-07-18-builder-fast-auth-multi-sandbox-cache-design.md`

## Global Constraints

- 本阶段只实施设计文档 Phase 1，不修改 Kubernetes Secret、Control Plane workspace lifecycle 或 Runtime 凭据协议。
- 登录鉴权、租户隔离和现有应用可见范围保持不变，不新增应用、项目或工作区权限判断。
- Code 应用缓存 key 必须包含当前 `tenant_id`；Phase 2 引入 `tenant_epoch` 时通过已预留参数扩展，不重写 Store。
- 应用页和 Rail Sidebar 使用完全相同的请求参数 `{ pageSize: 100 }`，同一租户同一时刻最多一个上游请求。
- `/api/code/rail/history` 首屏请求对 Runtime 的请求数必须为 0，延迟不能随历史沙箱数量线性增长。
- Runtime 会话快照只保存展示字段和状态，不保存 token、Cookie、workspace URL 或其他凭据。
- 现有 `/code-runtime/{shell}/shell/agent-sessions` 主动读取接口继续保留，本阶段不增加全量后台刷新。
- Runtime 会话快照写入失败必须使对应创建或激活事务失败，不能向用户返回成功但丢失外栏历史。
- 指标标签只允许固定 `stage` 和 `result`，不得包含 user、tenant、application、workspace、sandbox 或 session 标识。
- 验证按 L0 静态、L1 API、L2 Chromium 顺序执行；任一级失败立即修复，不继续扩大验证范围。

---

## File Map

### Create

- `frontend/src/stores/codeApplications.ts`：Code 应用 tenant-scoped TTL cache、singleflight 和显式失效。
- `frontend/src/stores/codeApplications.spec.ts`：请求合并、租户隔离、TTL 和强制刷新单元测试。

### Modify

- `frontend/src/views/Apps.vue`：Code 模式通过共享 Store 加载和强制刷新应用。
- `frontend/src/views/Apps.codeMode.spec.ts`：约束应用页不再直接调用 Code 应用列表 API。
- `frontend/src/components/v2/RailSidebar.vue`：Code 应用数通过共享 Store加载；首挂载任务并行执行。
- `frontend/src/components/v2/RailSidebar.spec.ts`：约束左栏不再直接穿透应用列表 API。
- `backend/app/models/ai_chat.py`：为 `CodeRuntimeAgentSession` 增加展示快照字段。
- `backend/app/database.py`：为既有 SQLite/MySQL 表幂等增加快照列。
- `backend/app/routes/code_runtime.py`：写入快照、DB-only Rail History、阶段耗时指标。
- `backend/app/code_runtime/sandbox_metrics.py`：增加低基数 Builder 阶段耗时 summary。
- `backend/tests/test_code_runtime_service.py`：模型和启动迁移契约。
- `backend/tests/test_code_runtime_routes.py`：快照写入、DB-only history、零 Runtime 调用和指标测试。

---

### Task 1: Code 应用共享 Store

**Files:**
- Create: `frontend/src/stores/codeApplications.ts`
- Create: `frontend/src/stores/codeApplications.spec.ts`

**Interfaces:**
- Consumes: `codeRuntimeApi.listApplications(params)`。
- Produces:
  - `CodeApplicationCacheScope = { tenantId: number | string; tenantEpoch?: number }`
  - `load(scope, params, options): Promise<CodeApplicationListResponse>`
  - `invalidateTenant(tenantId): void`
  - `clear(): void`

- [ ] **Step 1: 编写并发请求合并和租户隔离失败测试**

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { codeRuntimeApi, type CodeApplicationListResponse } from '@/api/codeRuntime'
import { useCodeApplicationsStore } from './codeApplications'

function page(tenant: string): CodeApplicationListResponse {
  return {
    items: [{
      id: `${tenant}-app`,
      external_application_id: `${tenant}-app`,
      app_name: `${tenant} App`,
      app_code: `${tenant}_app`,
      source: 'd-ai-code',
      app_type: 'ai-code',
      status: 'ready',
      models: 0,
      forms: 0,
      roles: 0,
      dicts: 0,
    }],
    page: 1,
    pageSize: 100,
    total: 1,
    source: 'd-ai-code',
  }
}

describe('code applications store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('joins concurrent requests for the same tenant and params', async () => {
    let resolveRequest!: (value: CodeApplicationListResponse) => void
    const upstream = new Promise<CodeApplicationListResponse>((resolve) => {
      resolveRequest = resolve
    })
    const list = vi.spyOn(codeRuntimeApi, 'listApplications').mockReturnValue(upstream)
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3 }

    const first = store.load(scope, { pageSize: 100 })
    const second = store.load(scope, { pageSize: 100 })
    expect(list).toHaveBeenCalledTimes(1)

    resolveRequest(page('tenant-3'))
    await expect(first).resolves.toEqual(page('tenant-3'))
    await expect(second).resolves.toEqual(page('tenant-3'))
  })

  it('never shares cached pages across tenants', async () => {
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockResolvedValueOnce(page('tenant-2'))
      .mockResolvedValueOnce(page('tenant-3'))
    const store = useCodeApplicationsStore()

    await expect(store.load({ tenantId: 2 }, { pageSize: 100 }))
      .resolves.toEqual(page('tenant-2'))
    await expect(store.load({ tenantId: 3 }, { pageSize: 100 }))
      .resolves.toEqual(page('tenant-3'))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('uses the fresh TTL cache and supports an explicit refresh', async () => {
    const list = vi.spyOn(codeRuntimeApi, 'listApplications')
      .mockResolvedValueOnce(page('first'))
      .mockResolvedValueOnce(page('refreshed'))
    const store = useCodeApplicationsStore()
    const scope = { tenantId: 3, tenantEpoch: 0 }

    await store.load(scope, { pageSize: 100 })
    await expect(store.load(scope, { pageSize: 100 })).resolves.toEqual(page('first'))
    await expect(store.load(scope, { pageSize: 100 }, { force: true }))
      .resolves.toEqual(page('refreshed'))
    expect(list).toHaveBeenCalledTimes(2)
  })
})
```

- [ ] **Step 2: 运行测试确认 Store 尚不存在**

Run:

```bash
cd frontend
npm test -- src/stores/codeApplications.spec.ts
```

Expected: FAIL，错误包含 `Cannot find module './codeApplications'`。

- [ ] **Step 3: 实现 tenant-scoped TTL cache 和 singleflight**

```ts
import { defineStore } from 'pinia'
import {
  codeRuntimeApi,
  type CodeApplicationListResponse,
} from '@/api/codeRuntime'

export interface CodeApplicationCacheScope {
  tenantId: number | string
  tenantEpoch?: number
}

export interface CodeApplicationLoadOptions {
  force?: boolean
}

type CodeApplicationListParams = Parameters<typeof codeRuntimeApi.listApplications>[0]

interface CacheEntry {
  tenantId: string
  loadedAt: number
  page: CodeApplicationListResponse
}

const CACHE_TTL_MS = 5_000

function normalizeParams(params: CodeApplicationListParams = {}) {
  return {
    keyword: String(params.keyword || '').trim(),
    provisionStatus: String(params.provisionStatus || '').trim(),
    page: Number(params.page || 1),
    pageSize: Number(params.pageSize || 100),
  }
}

function cacheKey(
  scope: CodeApplicationCacheScope,
  params: CodeApplicationListParams,
): string {
  const normalized = normalizeParams(params)
  return JSON.stringify({
    tenantId: String(scope.tenantId),
    tenantEpoch: Number(scope.tenantEpoch || 0),
    ...normalized,
  })
}

export const useCodeApplicationsStore = defineStore('codeApplications', () => {
  const cache = new Map<string, CacheEntry>()
  const inflight = new Map<string, Promise<CodeApplicationListResponse>>()

  function refresh(
    scope: CodeApplicationCacheScope,
    params: CodeApplicationListParams = {},
  ): Promise<CodeApplicationListResponse> {
    const key = cacheKey(scope, params)
    const joined = inflight.get(key)
    if (joined) return joined

    const normalized = normalizeParams(params)
    const pending = codeRuntimeApi.listApplications(normalized)
      .then((page) => {
        cache.set(key, {
          tenantId: String(scope.tenantId),
          loadedAt: Date.now(),
          page,
        })
        return page
      })
      .finally(() => {
        if (inflight.get(key) === pending) inflight.delete(key)
      })
    inflight.set(key, pending)
    return pending
  }

  function load(
    scope: CodeApplicationCacheScope,
    params: CodeApplicationListParams = {},
    options: CodeApplicationLoadOptions = {},
  ): Promise<CodeApplicationListResponse> {
    const key = cacheKey(scope, params)
    const cached = cache.get(key)
    if (
      !options.force
      && cached
      && Date.now() - cached.loadedAt < CACHE_TTL_MS
    ) {
      return Promise.resolve(cached.page)
    }
    return refresh(scope, params)
  }

  function invalidateTenant(tenantId: number | string): void {
    const expected = String(tenantId)
    for (const [key, entry] of cache.entries()) {
      if (entry.tenantId === expected) cache.delete(key)
    }
  }

  function clear(): void {
    cache.clear()
    inflight.clear()
  }

  return { load, invalidateTenant, clear }
})
```

- [ ] **Step 4: 运行 Store 测试**

Run:

```bash
cd frontend
npm test -- src/stores/codeApplications.spec.ts
```

Expected: 3 tests PASS。

- [ ] **Step 5: 提交共享 Store**

```bash
git add frontend/src/stores/codeApplications.ts frontend/src/stores/codeApplications.spec.ts
git commit -m "feat(code): share tenant scoped application loads"
```

---

### Task 2: 应用页和 Rail Sidebar 接入同一请求

**Files:**
- Modify: `frontend/src/views/Apps.vue:376-418,985-1014`
- Modify: `frontend/src/views/Apps.codeMode.spec.ts`
- Modify: `frontend/src/components/v2/RailSidebar.vue:1-115,360-377`
- Modify: `frontend/src/components/v2/RailSidebar.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `useCodeApplicationsStore().load(...)`。
- Produces: Code 模式应用页和左栏对 `{ tenantId, tenantEpoch: 0, pageSize: 100 }` 使用同一个 singleflight key。

- [ ] **Step 1: 修改源码契约测试，禁止两个组件直接请求 Code 应用列表**

在 `frontend/src/views/Apps.codeMode.spec.ts` 将 Code 应用加载断言替换为：

```ts
it('loads Code applications through the shared tenant-scoped store', () => {
  expect(appsSource).toContain("from '@/stores/codeApplications'")
  expect(appsSource).toContain('codeApplications.load')
  expect(appsSource).toContain('tenantId: user.tenantId')
  expect(appsSource).not.toContain('codeMode ? codeRuntimeApi.listApplications')
})
```

在 `frontend/src/components/v2/RailSidebar.spec.ts` 将 “keeps Code application count” 测试替换为：

```ts
it('uses the shared tenant-scoped Code application store', () => {
  expect(railSidebarSource).toContain("from '@/stores/codeApplications'")
  expect(railSidebarSource).toContain('codeApplications.load')
  expect(railSidebarSource).toContain('tenantId: user.tenantId')
  expect(railSidebarSource).not.toContain('codeRuntimeApi.listApplications')
})

it('starts independent rail loads in parallel', () => {
  expect(railSidebarSource).toContain('Promise.allSettled([')
  expect(railSidebarSource).toContain('loadRailApps()')
  expect(railSidebarSource).toContain('user.fetchAvailableTenants()')
  expect(railSidebarSource).toContain('loadRailSessions()')
})
```

- [ ] **Step 2: 运行源码契约测试确认失败**

Run:

```bash
cd frontend
npm test -- src/views/Apps.codeMode.spec.ts src/components/v2/RailSidebar.spec.ts
```

Expected: FAIL，因为组件仍直接调用 `codeRuntimeApi.listApplications` 且挂载时串行等待。

- [ ] **Step 3: 应用页接入共享 Store**

在 `Apps.vue` 增加：

```ts
import { useCodeApplicationsStore } from '@/stores/codeApplications'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const codeApplications = useCodeApplicationsStore()
```

把 `refreshApps` 改为：

```ts
async function refreshApps(forceCode = false) {
  const seq = ++refreshAppsSeq
  const codeMode = isCodeMode.value
  loading.value = true
  try {
    const codeList = codeMode
      ? codeApplications.load(
          { tenantId: user.tenantId || 0, tenantEpoch: 0 },
          { pageSize: 100 },
          { force: forceCode },
        )
      : applicationApi.list({ include_remote: false, app_type: 'low-code' })
    const [list, conversations] = await Promise.all([
      codeList,
      codeMode
        ? Promise.resolve([])
        : conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => []),
    ])
    if (seq !== refreshAppsSeq || codeMode !== isCodeMode.value) return
    apps.value = Array.isArray(list) ? list : (list?.items || [])
    appHistoryMap.value = buildAppHistoryMap(
      Array.isArray(conversations) ? conversations : [],
    )
  } catch (error) {
    if (seq !== refreshAppsSeq || codeMode !== isCodeMode.value) return
    handleError(error, { fallback: '应用列表加载失败' })
  } finally {
    if (seq === refreshAppsSeq) loading.value = false
  }
}
```

把 Code 模式工具栏刷新按钮改为：

```vue
<button
  v-if="isCodeMode"
  class="btn btn-secondary apps-toolbar-action"
  type="button"
  @click="refreshApps(true)"
>
```

把创建 Code 应用后的调用改为：

```ts
await refreshApps(true)
```

- [ ] **Step 4: Rail Sidebar 接入共享 Store并并行首挂载任务**

增加：

```ts
import { useCodeApplicationsStore } from '@/stores/codeApplications'

const codeApplications = useCodeApplicationsStore()
```

把 Code 模式 `loadRailApps` 分支改为：

```ts
if (mode === 'code') {
  const page = await codeApplications.load(
    { tenantId: user.tenantId || 0, tenantEpoch: 0 },
    { pageSize: 100 },
  )
  if (seq !== railAppsSeq || mode !== currentMode.value) return
  const items = page?.items || []
  appCount.value = Number(page?.total ?? items.length)
  appNameById.value = new Map()
  return
}
```

把串行挂载逻辑改为：

```ts
onMounted(() => {
  void Promise.allSettled([
    loadRailApps(),
    user.fetchAvailableTenants(),
    loadRailSessions(),
  ])
  window.addEventListener('click', closeTenantMenu)
  window.addEventListener('code-rail-refresh', refreshCodeRail)
})
```

- [ ] **Step 5: 运行前端聚焦测试和构建**

Run:

```bash
cd frontend
npm test -- src/stores/codeApplications.spec.ts src/views/Apps.codeMode.spec.ts src/components/v2/RailSidebar.spec.ts
npm run build
```

Expected: 聚焦测试 PASS，`vue-tsc` 和 Vite build PASS。

- [ ] **Step 6: 提交前端接入**

```bash
git add frontend/src/views/Apps.vue frontend/src/views/Apps.codeMode.spec.ts frontend/src/components/v2/RailSidebar.vue frontend/src/components/v2/RailSidebar.spec.ts
git commit -m "perf(code): deduplicate application loading"
```

---

### Task 3: 持久化 Runtime 会话展示快照

**Files:**
- Modify: `backend/app/models/ai_chat.py:128-155`
- Modify: `backend/app/database.py:248-256`
- Modify: `backend/app/routes/code_runtime.py:640-685,850-925`
- Modify: `backend/tests/test_code_runtime_service.py`
- Modify: `backend/tests/test_code_runtime_routes.py`

**Interfaces:**
- Produces:
  - `CodeRuntimeAgentSession.title`
  - `summary`
  - `state`
  - `model`
  - `runtime_created_at`
  - `runtime_updated_at`
  - `last_active_at`
  - `deleted_at`
  - `capability_stale`
  - `codex_session_resumable`
  - `_remember_runtime_agent_session(..., snapshot: dict[str, Any] | None = None)`

- [ ] **Step 1: 编写模型列和快照写入失败测试**

在 `backend/tests/test_code_runtime_service.py` 增加：

```py
def test_code_runtime_agent_session_model_has_rail_snapshot_columns():
    from app.models.ai_chat import CodeRuntimeAgentSession

    columns = {column.name for column in sa_inspect(CodeRuntimeAgentSession).columns}
    assert {
        "title",
        "summary",
        "state",
        "model",
        "runtime_created_at",
        "runtime_updated_at",
        "last_active_at",
        "deleted_at",
        "capability_stale",
        "codex_session_resumable",
    }.issubset(columns)
```

在 `backend/tests/test_code_runtime_routes.py` 增加：

```py
@pytest.mark.asyncio
async def test_remember_runtime_agent_session_persists_rail_snapshot(db_session):
    from app.routes.code_runtime import _remember_runtime_agent_session

    session, binding, _rows = await _seed_browser_runtime(db_session)
    await _remember_runtime_agent_session(
        db_session,
        session,
        binding,
        "runtime-1",
        {
            "runtimeSessionId": "runtime-1",
            "title": "实现登录",
            "summary": "完成认证链路",
            "state": "waiting_input",
            "model": "gpt-5",
            "createdAt": "2026-07-18T01:00:00Z",
            "updatedAt": "2026-07-18T01:05:00Z",
            "lastActiveAt": "2026-07-18T01:06:00Z",
            "deletedAt": None,
            "capabilityStale": False,
            "codexSessionResumable": True,
        },
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.runtime_session_id == "runtime-1"
            )
        )
    ).scalar_one()
    assert row.title == "实现登录"
    assert row.summary == "完成认证链路"
    assert row.state == "waiting_input"
    assert row.model == "gpt-5"
    assert row.last_active_at.isoformat() == "2026-07-18T01:06:00"
    assert row.capability_stale is False
    assert row.codex_session_resumable is True
```

- [ ] **Step 2: 运行聚焦测试确认失败**

Run:

```bash
cd backend
pytest -q tests/test_code_runtime_service.py::test_code_runtime_agent_session_model_has_rail_snapshot_columns tests/test_code_runtime_routes.py::test_remember_runtime_agent_session_persists_rail_snapshot
```

Expected: FAIL，模型缺少快照字段且 helper 不接受 `snapshot`。

- [ ] **Step 3: 扩展 SQLAlchemy 模型**

在 `backend/app/models/ai_chat.py` 的 SQLAlchemy import 增加 `Boolean`，并在 `CodeRuntimeAgentSession` 中加入：

```py
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    runtime_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    runtime_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    capability_stale: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    codex_session_resumable: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
```

- [ ] **Step 4: 增加既有数据库幂等迁移**

在 `backend/app/database.py` 的启动迁移列表中加入：

```py
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN title VARCHAR(300)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN summary TEXT",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN state VARCHAR(40)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN model VARCHAR(120)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN runtime_created_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN runtime_updated_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN last_active_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN deleted_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN capability_stale BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN codex_session_resumable BOOLEAN NOT NULL DEFAULT TRUE",
```

在 `backend/tests/test_database_postgresql_compat.py` 增加源码契约：

```py
def test_code_runtime_agent_session_snapshot_has_startup_migrations():
    import inspect
    from app import database

    source = inspect.getsource(database.init_db)
    assert "ALTER TABLE code_runtime_agent_sessions ADD COLUMN title" in source
    assert "ALTER TABLE code_runtime_agent_sessions ADD COLUMN last_active_at" in source
    assert "ALTER TABLE code_runtime_agent_sessions ADD COLUMN codex_session_resumable" in source
```

- [ ] **Step 5: 实现快照归一化和 upsert**

在 `backend/app/routes/code_runtime.py` 增加 import：

```py
from datetime import datetime
```

增加 helper：

```py
def _runtime_snapshot_text(value: Any, limit: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _runtime_snapshot_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)
```

把 `_remember_runtime_agent_session` 签名和末尾更新为：

```py
async def _remember_runtime_agent_session(
    db: AsyncSession,
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    runtime_session_id: str,
    snapshot: dict[str, Any] | None = None,
) -> None:
    runtime_id = str(runtime_session_id or "").strip()
    if not runtime_id:
        return
    existing = (
        await db.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == int(session.id),
                CodeRuntimeAgentSession.runtime_session_id == runtime_id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        existing = CodeRuntimeAgentSession(
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            app_id=int(session.app_id) if session.app_id else None,
            session_id=session.id,
            external_application_id=binding.external_application_id,
            runtime_session_id=runtime_id,
        )
        db.add(existing)

    existing.tenant_id = session.tenant_id
    existing.user_id = session.user_id
    existing.app_id = int(session.app_id) if session.app_id else None
    existing.external_application_id = binding.external_application_id
    existing.workspace_id = binding.workspace_id
    existing.sandbox_instance_id = binding.sandbox_instance_id

    payload = snapshot if isinstance(snapshot, dict) else {}
    existing.title = _runtime_snapshot_text(payload.get("title"), 300) or existing.title
    existing.summary = _runtime_snapshot_text(payload.get("summary")) or existing.summary
    existing.state = _runtime_snapshot_text(payload.get("state"), 40) or existing.state
    existing.model = _runtime_snapshot_text(payload.get("model"), 120) or existing.model
    existing.runtime_created_at = (
        _runtime_snapshot_time(payload.get("createdAt")) or existing.runtime_created_at
    )
    existing.runtime_updated_at = (
        _runtime_snapshot_time(payload.get("updatedAt")) or existing.runtime_updated_at
    )
    existing.last_active_at = (
        _runtime_snapshot_time(payload.get("lastActiveAt")) or existing.last_active_at
    )
    if "deletedAt" in payload:
        existing.deleted_at = _runtime_snapshot_time(payload.get("deletedAt"))
    if "capabilityStale" in payload:
        existing.capability_stale = bool(payload["capabilityStale"])
    if "codexSessionResumable" in payload:
        existing.codex_session_resumable = bool(payload["codexSessionResumable"])
```

- [ ] **Step 6: 创建和激活会话时传入 Runtime payload**

修改两处调用：

```py
await _remember_runtime_agent_session(
    db, session, binding, runtime_session_id, payload
)
```

```py
await _remember_runtime_agent_session(
    db, session, binding, activated_id, payload
)
```

- [ ] **Step 7: 运行快照和迁移测试**

Run:

```bash
cd backend
pytest -q \
  tests/test_code_runtime_service.py::test_code_runtime_agent_session_model_has_rail_snapshot_columns \
  tests/test_code_runtime_routes.py::test_remember_runtime_agent_session_persists_rail_snapshot \
  tests/test_database_postgresql_compat.py::test_code_runtime_agent_session_snapshot_has_startup_migrations
```

Expected: 3 tests PASS。

- [ ] **Step 8: 提交快照持久化**

```bash
git add backend/app/models/ai_chat.py backend/app/database.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py backend/tests/test_database_postgresql_compat.py
git commit -m "feat(code): persist runtime rail snapshots"
```

---

### Task 4: Rail History 改为 DB-only

**Files:**
- Modify: `backend/app/routes/code_runtime.py:520-575,741-840`
- Modify: `backend/tests/test_code_runtime_routes.py:725-1126`

**Interfaces:**
- Consumes: Task 3 的 `CodeRuntimeAgentSession` 快照列。
- Produces: `GET /api/code/rail/history` 保持 `{ "apps": [...] }` 响应结构，但请求内不调用 `_runtime_json_request*`。

- [ ] **Step 1: 把 Runtime fan-out 测试改为零 Runtime 调用测试**

用以下测试替换 `test_list_code_runtime_rail_history_uses_short_runtime_timeout`：

```py
@pytest.mark.asyncio
async def test_list_code_runtime_rail_history_is_database_only(db_session, monkeypatch):
    import app.routes.code_runtime as code_runtime_routes
    from app.routes.code_runtime import list_code_runtime_rail_history

    session, binding, _rows = await _seed_browser_runtime(db_session)
    binding.runtime_session_id = "runtime-current"
    db_session.add(CodeRuntimeAgentSession(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="crm",
        runtime_session_id="runtime-current",
        title="数据库快照",
        state="waiting_input",
        capability_stale=False,
        codex_session_resumable=True,
    ))
    await db_session.commit()

    async def unexpected_runtime_call(*_args, **_kwargs):
        raise AssertionError("rail history must not call Runtime")

    monkeypatch.setattr(
        code_runtime_routes,
        "_runtime_json_request_for_session",
        unexpected_runtime_call,
    )
    monkeypatch.setattr(
        code_runtime_routes,
        "_runtime_session_detail_or_none",
        unexpected_runtime_call,
    )

    result = await list_code_runtime_rail_history(_request(), _ctx(), db_session)

    assert result["apps"][0]["sessions"][0]["runtimeSessionId"] == "runtime-current"
    assert result["apps"][0]["sessions"][0]["title"] == "数据库快照"
    assert result["apps"][0]["sessions"][0]["current"] is True
```

- [ ] **Step 2: 运行测试确认当前实现仍访问 Runtime**

Run:

```bash
cd backend
pytest -q tests/test_code_runtime_routes.py::test_list_code_runtime_rail_history_is_database_only
```

Expected: FAIL，错误为 `rail history must not call Runtime`。

- [ ] **Step 3: 增加数据库快照序列化 helper**

在 `backend/app/routes/code_runtime.py` 增加：

```py
def _runtime_agent_snapshot_item(
    row: CodeRuntimeAgentSession,
    current_runtime_id: str,
) -> dict[str, Any]:
    created_at = row.runtime_created_at or row.created_at
    updated_at = row.runtime_updated_at or row.updated_at
    last_active_at = row.last_active_at or updated_at
    return {
        "runtimeSessionId": row.runtime_session_id,
        "title": row.title or row.summary or "未命名会话",
        "summary": row.summary,
        "state": row.state or "waiting_input",
        "model": row.model,
        "createdAt": created_at.isoformat() if created_at else None,
        "updatedAt": updated_at.isoformat() if updated_at else None,
        "lastActiveAt": last_active_at.isoformat() if last_active_at else None,
        "current": row.runtime_session_id == current_runtime_id,
        "deletedAt": row.deleted_at.isoformat() if row.deleted_at else None,
        "capabilityStale": bool(row.capability_stale),
        "codexSessionResumable": bool(row.codex_session_resumable),
    }
```

- [ ] **Step 4: 一次查询全部快照并替换 Rail History 循环**

保留现有 session/binding 查询、应用过滤和 dedupe 逻辑。在进入应用循环前增加：

```py
    shell_session_ids = [int(session.id) for session, _binding in rows]
    snapshot_rows = []
    if shell_session_ids:
        snapshot_rows = (
            await db.execute(
                select(CodeRuntimeAgentSession)
                .where(
                    CodeRuntimeAgentSession.tenant_id == ctx.tenant_id,
                    CodeRuntimeAgentSession.user_id == ctx.user.id,
                    CodeRuntimeAgentSession.session_id.in_(shell_session_ids),
                    CodeRuntimeAgentSession.deleted_at.is_(None),
                )
                .order_by(
                    CodeRuntimeAgentSession.last_active_at.desc(),
                    CodeRuntimeAgentSession.updated_at.desc(),
                    CodeRuntimeAgentSession.id.desc(),
                )
            )
        ).scalars().all()
    snapshots_by_shell: dict[int, list[CodeRuntimeAgentSession]] = {}
    for snapshot in snapshot_rows:
        snapshots_by_shell.setdefault(int(snapshot.session_id), []).append(snapshot)
```

把原有 `try: payload = await _runtime_json_request_for_session(...)` 整段替换为：

```py
        current_runtime_id = str(binding.runtime_session_id or "").strip() if binding else ""
        app["sessions"] = [
            _runtime_agent_snapshot_item(snapshot, current_runtime_id)
            for snapshot in snapshots_by_shell.get(int(session.id), [])
        ]
        if binding and current_runtime_id and not any(
            item["runtimeSessionId"] == current_runtime_id
            for item in app["sessions"]
        ):
            app["sessions"].insert(
                0,
                _runtime_session_placeholder(
                    binding,
                    current_runtime_id,
                    session.title,
                ),
            )
```

删除该 endpoint 末尾无数据变更的：

```py
await db.commit()
```

- [ ] **Step 5: 调整已有 Rail History 测试数据源**

将以下测试改为直接插入 `CodeRuntimeAgentSession` 快照，不再 monkeypatch Runtime 列表或 detail：

```text
test_list_code_runtime_rail_history_returns_opened_app_agent_sessions
test_list_code_runtime_rail_history_filters_sessions_by_shell_scope
test_list_code_runtime_rail_history_excludes_sessions_scoped_to_other_shells
test_list_code_runtime_rail_history_includes_current_empty_session_placeholder
test_list_code_runtime_rail_history_uses_current_session_detail_when_list_filters_it
```

其中：

```text
shell scope
  为两个不同 session_id 分别插入快照，每个 app 只返回自己的行。

excludes other shells
  为其它 shell 插入同名 runtime_session_id，不得出现在当前 shell。

current empty placeholder
  只设置 binding.runtime_session_id，不插入对应快照，返回标题为 shell title 的 placeholder。

uses current session detail
  重命名为 test_list_code_runtime_rail_history_prefers_persisted_current_snapshot；
  为 current runtime_session_id 插入带标题快照，断言返回该快照且 current=true，
  不再调用 _runtime_session_detail_or_none。
```

- [ ] **Step 6: 运行全部 Code Runtime route 测试**

Run:

```bash
cd backend
pytest -q tests/test_code_runtime_routes.py
```

Expected: PASS，并且测试输出中不存在对 Rail History 2 秒 Runtime timeout 的断言。

- [ ] **Step 7: 提交 DB-only history**

```bash
git add backend/app/routes/code_runtime.py backend/tests/test_code_runtime_routes.py
git commit -m "perf(code): serve rail history from database"
```

---

### Task 5: 增加低基数阶段耗时指标

**Files:**
- Modify: `backend/app/code_runtime/sandbox_metrics.py`
- Modify: `backend/app/routes/code_runtime.py:1-90,261-279,741-840`
- Modify: `backend/tests/test_code_runtime_routes.py`

**Interfaces:**
- Produces:
  - `builder_stage_duration_seconds_count{stage,result}`
  - `builder_stage_duration_seconds_sum{stage,result}`
  - 固定 stage：`applications_shared_load | rail_history_db`
  - 固定 result：`success | failure`

- [ ] **Step 1: 编写指标标签和渲染测试**

在 `backend/tests/test_code_runtime_routes.py` 增加：

```py
def test_builder_stage_metrics_use_only_bounded_labels():
    from app.code_runtime.sandbox_metrics import SandboxAuthMetricsRegistry

    metrics = SandboxAuthMetricsRegistry()
    metrics.record_builder_stage("rail_history_db", "success", 0.125)
    rendered = metrics.render()

    assert (
        'builder_stage_duration_seconds_count{result="success",stage="rail_history_db"} 1'
        in rendered
    )
    assert (
        'builder_stage_duration_seconds_sum{result="success",stage="rail_history_db"} 0.125'
        in rendered
    )
    assert "tenant" not in rendered
    assert "session_id" not in rendered
```

- [ ] **Step 2: 运行指标测试确认失败**

Run:

```bash
cd backend
pytest -q tests/test_code_runtime_routes.py::test_builder_stage_metrics_use_only_bounded_labels
```

Expected: FAIL，`SandboxAuthMetricsRegistry` 没有 `record_builder_stage`。

- [ ] **Step 3: 实现固定标签阶段指标**

在 `backend/app/code_runtime/sandbox_metrics.py` 增加：

```py
_BUILDER_STAGES = ("applications_shared_load", "rail_history_db")
_BUILDER_STAGE_RESULTS = ("success", "failure")
```

在 `__init__` 中加入：

```py
        self._builder_stage_count: dict[str, float] = {}
        self._builder_stage_sum: dict[str, float] = {}
        for stage, result in product(_BUILDER_STAGES, _BUILDER_STAGE_RESULTS):
            labels = {"stage": stage, "result": result}
            self._builder_stage_count[_series(
                "builder_stage_duration_seconds_count", **labels
            )] = 0.0
            self._builder_stage_sum[_series(
                "builder_stage_duration_seconds_sum", **labels
            )] = 0.0
```

增加方法：

```py
    def record_builder_stage(
        self,
        stage: str,
        result: str,
        duration_seconds: float,
    ) -> None:
        stage = _label(stage, _BUILDER_STAGES, "rail_history_db")
        result = _label(result, _BUILDER_STAGE_RESULTS, "failure")
        labels = {"stage": stage, "result": result}
        count_key = _series("builder_stage_duration_seconds_count", **labels)
        sum_key = _series("builder_stage_duration_seconds_sum", **labels)
        self._builder_stage_count[count_key] += 1
        self._builder_stage_sum[sum_key] += max(0.0, float(duration_seconds))
```

在 `snapshot()` 合并两个 map，并在 `render()` 增加：

```py
            "# TYPE builder_stage_duration_seconds summary",
```

- [ ] **Step 4: 包裹 applications 和 Rail History endpoint**

在 `backend/app/routes/code_runtime.py` 增加：

```py
import time
```

`list_code_runtime_applications` 使用：

```py
    started = time.monotonic()
    try:
        authorization, auth_provider = await _control_plane_request_auth(request, ctx, db)
        result = await list_code_applications(
            keyword=keyword,
            provision_status=provision_status,
            page=page,
            page_size=page_size,
            authorization_header=authorization,
            delegated_context=ctx,
            auth_provider=auth_provider,
        )
    except Exception:
        sandbox_auth_metrics.record_builder_stage(
            "applications_shared_load", "failure", time.monotonic() - started
        )
        raise
    sandbox_auth_metrics.record_builder_stage(
        "applications_shared_load", "success", time.monotonic() - started
    )
    return result
```

`list_code_runtime_rail_history` 使用同一结构，stage 为 `rail_history_db`；成功路径在 return 前记录，异常路径记录 failure 后原样抛出。

- [ ] **Step 5: 运行指标和 endpoint 测试**

Run:

```bash
cd backend
pytest -q \
  tests/test_code_runtime_routes.py::test_builder_stage_metrics_use_only_bounded_labels \
  tests/test_code_runtime_routes.py::test_list_code_runtime_rail_history_is_database_only
```

Expected: PASS。

- [ ] **Step 6: 提交指标**

```bash
git add backend/app/code_runtime/sandbox_metrics.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_routes.py
git commit -m "obs(code): measure first screen stages"
```

---

### Task 6: 分级验证与本地性能验收

**Files:**
- Verify only; no source file changes expected.

**Interfaces:**
- Consumes: Tasks 1-5 完成后的 Builder API 和前端。
- Produces: L0、L1、L2 验收证据，确认 Phase 1 可独立上线。

- [ ] **Step 1: L0 前端静态、类型和聚焦单测**

Run:

```bash
cd frontend
npm test -- \
  src/stores/codeApplications.spec.ts \
  src/views/Apps.codeMode.spec.ts \
  src/components/v2/RailSidebar.spec.ts
npm run build
```

Expected: tests PASS，TypeScript build PASS。

- [ ] **Step 2: L0/L1 后端模型、迁移和 API 测试**

Run:

```bash
cd backend
pytest -q \
  tests/test_code_runtime_service.py \
  tests/test_database_postgresql_compat.py \
  tests/test_code_runtime_routes.py
```

Expected: PASS。

- [ ] **Step 3: 启动现有 `remote-infra` 本地 Profile**

Run:

```bash
cd /home/shitou/worktrees/d-ai-code/platform-integration/dev-stack-orchestrator
./dev-stack status --profile remote-infra
./dev-stack up --profile remote-infra
```

Expected:

```text
control-plane  running
builder-api    running
builder-web    running
```

- [ ] **Step 4: L1 请求计数验收**

用 Chromium 打开 `/ai-builder/code/apps`，清空 Network 后刷新一次。验收：

```text
GET /api/code/applications  总数 = 1
GET /api/code/rail/history 总数 = 1
Rail History 触发的 /api/agent/sessions 请求总数 = 0
```

同时读取内部指标：

```bash
curl -fsS http://127.0.0.1:8000/api/code/internal/sandbox-auth-metrics \
  | rg 'builder_stage_duration_seconds_(count|sum)'
```

Expected: `applications_shared_load` 和 `rail_history_db` 的 success count 均增加。

- [ ] **Step 5: L2 Chromium 租户和首屏验收**

在真实 Chromium 中：

```text
1. 登录 admin。
2. 切到 admin 的组织。
3. 打开 Code 应用列表，确认应用行和左栏应用数一致。
4. 打开任一有历史会话的 Code 应用，确认左栏会话仍可进入。
5. 切到默认组织并返回 Code 应用列表，确认不显示 admin 的组织数据。
6. 切回 admin 的组织，确认应用恢复且没有 TENANT_FORBIDDEN。
```

性能目标：

```text
应用首批数据 P95 < 1.5s
Rail History 不随历史沙箱数量增长
页面不出现 Runtime 401 导致的等待或错误提示
```

- [ ] **Step 6: 全量前端和后端回归**

Run:

```bash
cd frontend
npm test
cd ../backend
pytest -q
```

Expected: 全部 PASS。若全量后端测试受外部服务用例影响，必须单独列出失败测试名和外部依赖错误，Tasks 1-5 的聚焦测试必须全部通过。

- [ ] **Step 7: 最终提交检查**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: 只有计划外用户改动可以保持未提交；本计划拥有的代码和测试均已进入独立提交。

---

## Phase 1 Done Definition

1. 同一租户进入 `/code/apps` 时，应用页和 Rail Sidebar 合计只产生一次 `/api/code/applications` 请求。
2. `/api/code/rail/history` 不调用 Runtime，不再出现历史沙箱 401 串行等待。
3. Runtime 会话创建和激活成功后，Builder 数据库存在可展示快照。
4. 没有快照的当前 Runtime 会话使用本地 placeholder，首屏不反查 Runtime。
5. 切租户后不会复用另一租户的 Code 应用缓存。
6. 应用列表和 Rail History 阶段指标可从现有内部 metrics endpoint 读取，且不含高基数或敏感标签。
7. Phase 1 聚焦测试、前端 build 和真实 Chromium 租户切换通过。
8. 本阶段没有修改 Secret、Launch Ticket、workspace open 或多 iframe 缓存逻辑。

## Deferred Plans

后续独立计划按设计文档继续：

1. Phase 2：`/api/auth/bootstrap`、`tenant_epoch`、无整页 reload 切租户。
2. Phase 3：Control Plane Launch Ticket、Agent Runtime exchange、Builder Browser Session fast path、移除 ready workspace per-open Secret rotation。
3. Phase 4：normal/performance 配置、Browser Frame LRU 和 Server Warm Sandbox LRU。
