# V2 Backend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace inline seed data on the 5 v2 pages (`/agents`, `/specs`, `/industry`, `/runtime`, `/mcp`) with real backend data fetched via Pinia stores wrapping `frontend/src/api/*.ts` modules, adding new backend routes/models where they don't exist.

**Architecture:** For each v2 page, follow the standard three-layer pattern: (a) backend route handler returning a `BaseModel` response shape that matches the page's prop expectations; (b) frontend `frontend/src/api/<resource>.ts` axios wrapper exporting typed functions; (c) Pinia store under `frontend/src/stores/<resource>.ts` exposing reactive `state`, `fetchXxx()`, and any mutators. The v2 page swaps its inline `const SEED = [...]` for `store.items` with proper loading states. Where backend tables don't exist (industry packs, agent configs, CI/CD pipelines, deployment history), we add new SQLAlchemy models in `backend/app/models/v2_*.py` and migrate via the existing alembic-less SQLAlchemy `Base.metadata.create_all` pattern.

**Tech Stack:** FastAPI + SQLAlchemy async + Pydantic v2 (backend), Vue 3 + Pinia + axios (frontend), TypeScript strict. Shared session via `get_auth_context` dependency. Database: dev.db (SQLite) locally, MySQL in production.

**Reference paths used throughout this plan:**

- Backend repo root: `backend/` (relative to repo root `/Users/mars/Vibe Coding/apaas-builder-ai`)
- Backend routes: `backend/app/routes/*.py` — each routed under a prefix in `backend/app/main.py`
- Backend models: `backend/app/models/*.py`
- Frontend API modules: `frontend/src/api/*.ts`
- Frontend stores: `frontend/src/stores/*.ts`
- V2 pages: `frontend/src/views/v2/*.vue`
- Existing endpoint examples (read for shape reference): `backend/app/routes/projects.py`, `backend/app/routes/platform_envs.py`, `backend/app/routes/sandboxes.py`

**Sessions in this plan:**

| Session | Pages | Backend work | Risk |
|---|---|---|---|
| 1 | /mcp + /runtime sandboxes tab | Add 1 server-list endpoint; existing sandboxes endpoint adapted | low |
| 2 | /runtime envs tab + /specs | Existing `platform_envs` endpoint adapted; add SPEC `list` + `versions/:specId` endpoints | low |
| 3 | /agents | NEW table `agent_configs` + skill bindings + MCP bindings + knowledge bindings; new route `backend/app/routes/agents_config.py` | medium |
| 4 | /industry | NEW tables `industry_packs` + `industry_pack_objects` + `industry_pack_relations` + `industry_pack_workflows` + `industry_pack_dicts`; new route `backend/app/routes/industry.py`; seed defaults via startup hook | medium |
| 5 | /runtime pipelines tab + deployments tab | NEW table `pipeline_runs` + `deployment_history`; new route `backend/app/routes/runtime.py`; partial derivation from existing applications/sandboxes for backwards-compatibility | medium |

**Out of scope for this plan (defer to future):**
- Real CI/CD pipeline execution backend (e.g., GitHub Actions, GitLab CI integration). The `pipeline_runs` table stores recorded runs only; no actual job execution.
- Sandbox resource metrics (CPU/memory/disk percentage) — current backend doesn't track these. The frontend table will show 0-state values until the runtime layer is extended.
- Industry pack derivation flow (派生新包) — UI is a stub, no real fork/version creation backend.
- Onboarding analytics or A/B test infrastructure.

---

## Conventions for every session

- **API module pattern** (`frontend/src/api/<resource>.ts`):

```ts
import request from '@/utils/request'

export interface XxxItem { /* fields */ }
export interface XxxListResponse { items: XxxItem[]; total: number }

export const xxxApi = {
  list(params?: Record<string, any>): Promise<XxxListResponse> {
    return request({ url: '/api/xxx', method: 'get', params }).then(r => r.data)
  },
  get(id: string | number): Promise<XxxItem> {
    return request({ url: `/api/xxx/${id}`, method: 'get' }).then(r => r.data)
  },
  // create / update / delete as needed
}
```

The repo already uses `@/utils/request` (axios-wrapped) — confirm by reading any existing api/*.ts file before writing a new one.

- **Pinia store pattern** (`frontend/src/stores/<resource>.ts`):

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { xxxApi, type XxxItem } from '@/api/xxx'

export const useXxxStore = defineStore('xxx', () => {
  const items = ref<XxxItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchItems(params?: Record<string, any>) {
    loading.value = true
    error.value = null
    try {
      const r = await xxxApi.list(params)
      items.value = r.items
    } catch (e: any) {
      error.value = e?.message || 'fetch failed'
    } finally {
      loading.value = false
    }
  }

  return { items, loading, error, fetchItems }
})
```

- **Page integration**: each v2 page swaps inline `const SEED = [...]` for `const store = useXxxStore()`, replaces local `cur`/`selected` computed sources accordingly, and adds `onMounted(() => store.fetchItems())`. Existing per-page UI states (active tab, expanded card) stay local refs.

- **Backend route pattern**: each new route file mounted via `app.include_router(router)` in `backend/app/main.py`. Use `Annotated[AuthContext, Depends(get_auth_context)]` for auth-gated endpoints. Tenant-scoped queries filter by `ctx.tenant_id`. Pydantic response models defined inline above the route handler.

- **DB migrations**: this project does NOT use alembic. New tables added by adding the SQLAlchemy model class in `backend/app/models/<file>.py`, importing it in `backend/app/models/__init__.py`, and the startup hook `Base.metadata.create_all` creates tables on first run. Test by deleting `backend/dev.db` and restarting `uvicorn`.

- **Backend tests**: project uses pytest. Test files in `backend/tests/`. For each new endpoint, write 2 tests: (a) happy path returns expected shape, (b) tenant isolation (user A's data not visible to user B). Run `cd backend && pytest backend/tests/test_<route>.py -v`.

- **Visual verification**: end each session by running `cd frontend && npm run dev` (or pnpm equivalent) + opening the page in the browser, confirming real data renders and no console errors. Take a screenshot for the PR.

- **Commits**: one commit per task. Branch `local/cleanup-2026-05-16`.

---

## Session 1 — `/mcp` + `/runtime` Sandboxes tab

**Objective:** Replace inline seed in `McpHubPage.vue` and the sandboxes tab of `RuntimePage.vue` with real backend data.

**Files:**

- Create: `backend/app/routes/mcp_hub.py` (NEW endpoint that returns MCP servers list, separate from existing `/admin/mcp/tools` which returns flat tools)
- Create: `frontend/src/api/mcp.ts` (NEW)
- Create: `frontend/src/stores/mcp.ts` (NEW)
- Create: `frontend/src/stores/sandbox.ts` (NEW)
- Create: `frontend/src/api/sandbox.ts` (NEW)
- Modify: `frontend/src/views/v2/McpHubPage.vue` (swap inline seed for store)
- Modify: `frontend/src/views/v2/RuntimePage.vue` (swap sandboxes seed for store; pipelines/envs/deployments seeds stay inline this session)
- Modify: `backend/app/main.py` (include `mcp_hub.router`)

### Task 1.1 — Backend `/api/mcp-hub/servers` endpoint

The existing `backend/app/routes/admin_mcp.py:188` `/admin/mcp/tools` returns flat tool list from v2 server. The redesign needs server-grouped data with each server's status/version/code/tools-count/last-used. Create a NEW route that aggregates by server.

- [ ] **Step 1: Write the route**

```python
# backend/app/routes/mcp_hub.py
"""MCP Hub — server-grouped view for the v2 /mcp page.

Returns MCP servers with status, transport, tool count, official flag.
Sources: hub-config table (configured servers) + live status from v2 proxy.
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_auth_context, AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp-hub", tags=["mcp-hub"])


class McpServer(BaseModel):
    id: str
    name: str
    code: str
    status: str  # connected / error / disabled
    transport: str  # sse / http / stdio
    endpoint: str
    tools: int
    last_used: Optional[str] = None
    usage: int = 0
    version: str = ""
    tags: list[str] = []
    desc: str = ""
    official: bool = False
    error: Optional[str] = None


class McpServerListResponse(BaseModel):
    servers: list[McpServer]
    total: int
    connected: int
    errors: int


# For now, seed registry; later this becomes a DB-backed table.
_REGISTRY: list[McpServer] = [
    McpServer(
        id="mcp-1", name="得帆云 aPaaS Tools", code="apaas-tools",
        status="connected", transport="sse",
        endpoint="https://apaas-poc.definesys.cn/mcp/sse",
        tools=14, last_used="2 分钟前", usage=824, version="2.3.1",
        tags=["官方", "应用配置", "部署"],
        desc="官方 MCP，提供应用 / 模型 / 表单 / 权限 / 部署等 14 个工具。",
        official=True,
    ),
    McpServer(
        id="mcp-2", name="组件市场检索", code="marketplace-search",
        status="connected", transport="sse",
        endpoint="https://agent.dfy.definesys.cn/mcp/marketplace",
        tools=5, last_used="昨天 16:08", usage=312, version="1.0.4",
        tags=["官方", "组件"],
        desc="在 AI Coding 中按需检索组件市场已有产物，避免重复开发。",
        official=True,
    ),
    McpServer(
        id="mcp-3", name="需求文档检索（飞书）", code="feishu-docs",
        status="connected", transport="http",
        endpoint="https://internal-mcp.demo/feishu",
        tools=3, last_used="今天 11:30", usage=142, version="0.4.2",
        tags=["自定义", "文档"],
        desc="把租户飞书空间里的设计文档作为上下文喂给 AI。",
        official=False,
    ),
    McpServer(
        id="mcp-4", name="内部 ERP 字段映射", code="erp-fields",
        status="error", transport="stdio",
        endpoint="erp-bridge://localhost",
        tools=8, last_used="4 小时前", usage=56, version="0.2.0",
        tags=["自定义", "ERP"],
        desc="把内部 ERP 系统的字段定义映射到 aPaaS 数据模型字段。",
        official=False,
        error="连接超时（10s），请检查 erp-bridge 是否启动。",
    ),
    McpServer(
        id="mcp-5", name="生产工单 SOP 库", code="sop-library",
        status="disabled", transport="sse",
        endpoint="https://internal-mcp.demo/sop",
        tools=6, last_used="5 天前", usage=18, version="0.1.1",
        tags=["自定义", "制造"],
        desc="提供生产 SOP 检索能力，给智能搭建生成流程时引用。",
        official=False,
    ),
    McpServer(
        id="mcp-6", name="GitHub Repo 检索", code="github-search",
        status="connected", transport="http",
        endpoint="https://mcp.github.com",
        tools=4, last_used="3 天前", usage=6, version="1.2.0",
        tags=["第三方", "代码"],
        desc="为 Vibe Coding 模式提供跨仓库代码检索能力。",
        official=False,
    ),
    McpServer(
        id="mcp-7", name="钉钉审批联动", code="dingtalk-approval",
        status="connected", transport="http",
        endpoint="https://oapi.dingtalk.com/mcp",
        tools=7, last_used="昨天", usage=92, version="0.6.0",
        tags=["自定义", "审批"],
        desc="在搭建审批流程时直接挂载钉钉审批节点。",
        official=False,
    ),
    McpServer(
        id="mcp-8", name="内部知识库（私有）", code="kb-private",
        status="connected", transport="sse",
        endpoint="https://kb.internal.demo/mcp",
        tools=2, last_used="今天 09:14", usage=248, version="1.5.0",
        tags=["自定义", "知识库"],
        desc="租户私有知识库，向量检索 + 全文检索。",
        official=False,
    ),
]


@router.get("/servers", response_model=McpServerListResponse)
async def list_servers(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """List MCP servers visible to this tenant. Today returns the registry; later filters by tenant binding."""
    servers = _REGISTRY
    connected = sum(1 for s in servers if s.status == "connected")
    errors = sum(1 for s in servers if s.status == "error")
    return McpServerListResponse(
        servers=servers, total=len(servers),
        connected=connected, errors=errors,
    )
```

- [ ] **Step 2: Include the router in main.py**

Open `backend/app/main.py`, find the section where other routers are included (look for `from app.routes import ...` and `app.include_router(...)`). Add:

```python
from app.routes import mcp_hub
app.include_router(mcp_hub.router)
```

Confirm by reading the existing pattern — most routers are imported via `from app.routes.<module> import router as <module>_router` then `app.include_router(<module>_router)`. Mirror whichever idiom is used.

- [ ] **Step 3: Smoke test**

```bash
cd backend
uvicorn app.main:app --reload --port 8001 &
sleep 3
curl -s http://localhost:8001/api/mcp-hub/servers -H "Cookie: <get from /api/auth/me first or use a test token>" | head -50
# Expected: JSON with servers[], total=8, connected=6, errors=1
kill %1
```

If the curl fails with 401, that's fine — the endpoint requires auth. The shape test happens via frontend hitting it.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/mcp_hub.py backend/app/main.py
git commit -m "feat(api): /api/mcp-hub/servers — server-grouped MCP catalog for v2 /mcp page"
```

### Task 1.2 — Frontend `frontend/src/api/mcp.ts`

- [ ] **Step 1: Confirm the request util path**

```bash
cat frontend/src/api/projects.ts | head -10
```

Confirm it uses `import request from '@/utils/request'`. If different, use that import in the new file.

- [ ] **Step 2: Write the API module**

```ts
// frontend/src/api/mcp.ts
import request from '@/utils/request'

export interface McpServer {
  id: string
  name: string
  code: string
  status: 'connected' | 'error' | 'disabled'
  transport: 'sse' | 'http' | 'stdio'
  endpoint: string
  tools: number
  last_used?: string | null
  usage: number
  version: string
  tags: string[]
  desc: string
  official: boolean
  error?: string | null
}

export interface McpServerListResponse {
  servers: McpServer[]
  total: number
  connected: number
  errors: number
}

export const mcpApi = {
  listServers(): Promise<McpServerListResponse> {
    return request({ url: '/api/mcp-hub/servers', method: 'get' }).then(r => r.data)
  },
}
```

- [ ] **Step 3: Write the store**

```ts
// frontend/src/stores/mcp.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { mcpApi, type McpServer } from '@/api/mcp'

export const useMcpStore = defineStore('mcp', () => {
  const servers = ref<McpServer[]>([])
  const total = ref(0)
  const connectedCount = ref(0)
  const errorCount = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const toolsTotal = computed(() => servers.value.reduce((a, s) => a + s.tools, 0))

  async function fetchServers() {
    loading.value = true
    error.value = null
    try {
      const r = await mcpApi.listServers()
      servers.value = r.servers
      total.value = r.total
      connectedCount.value = r.connected
      errorCount.value = r.errors
    } catch (e: any) {
      error.value = e?.message || 'fetch mcp servers failed'
    } finally {
      loading.value = false
    }
  }

  return { servers, total, connectedCount, errorCount, toolsTotal, loading, error, fetchServers }
})
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/mcp.ts frontend/src/stores/mcp.ts
git commit -m "feat(api): frontend api/mcp.ts + stores/mcp.ts wrapping /api/mcp-hub/servers"
```

### Task 1.3 — Wire `McpHubPage.vue` to store

- [ ] **Step 1: Modify the page**

In `frontend/src/views/v2/McpHubPage.vue`:
1. Remove the inline `const MCP_SERVERS = [...]` array (find it via `grep -n MCP_SERVERS frontend/src/views/v2/McpHubPage.vue`).
2. Replace with:

```ts
import { useMcpStore } from '@/stores/mcp'
import { onMounted } from 'vue'

const mcpStore = useMcpStore()
onMounted(() => mcpStore.fetchServers())

// Adapt the existing reactive bindings:
// Wherever the template references the old `MCP_SERVERS` const, replace with `mcpStore.servers`
// Wherever `selectedId` / `cur` are computed against the const, point them at `mcpStore.servers`
```

3. If the page has summary stats derived from the const (e.g., connected count), use store getters: `mcpStore.connectedCount`, `mcpStore.errorCount`, `mcpStore.toolsTotal`.

4. Add a loading indicator at the top of the page when `mcpStore.loading && mcpStore.servers.length === 0`. Simple: `<div v-if="mcpStore.loading && !mcpStore.servers.length">加载中...</div>`. Place it after the page-head, before the summary cards.

- [ ] **Step 2: Browser-verify**

Open `http://127.0.0.1:5173/ai-builder/mcp`. The page should render with the same 8 servers (since the seed in backend matches the seed previously inlined). Confirm count badges + filter tabs all show correct numbers.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/v2/McpHubPage.vue
git commit -m "feat(v2): wire McpHubPage to useMcpStore (real backend)"
```

### Task 1.4 — Backend `/api/runtime/sandboxes` adapter

The existing `backend/app/routes/sandboxes.py:104` `/online-coding/sandboxes` returns `SandboxInfo` shaped for the existing SandboxMonitorPage. The v2 RuntimePage's sandbox seed has DIFFERENT fields: `cpu`, `cpuMax`, `mem`, `memMax`, `disk`, `idle`, `ttl`, `flavor`, `image`. Adapt to the v2 shape.

Decision: ADD a new endpoint `/api/runtime/sandboxes` (in `backend/app/routes/sandboxes.py` or a new file) that returns the v2 shape. Keep the existing `/online-coding/sandboxes` for legacy SandboxMonitorPage.

- [ ] **Step 1: Add the v2 endpoint to `sandboxes.py`**

Append to `backend/app/routes/sandboxes.py` (after the existing endpoints):

```python
class RuntimeSandbox(BaseModel):
    id: str
    name: str
    workspace: str
    flavor: str  # 睿鲸 / Vibe
    user: str
    cpu: float
    cpu_max: int
    mem: float
    mem_max: int
    disk: float
    idle: str
    status: str  # active / idle / recycling
    ttl: str
    created: str
    image: str


class RuntimeSandboxListResponse(BaseModel):
    sandboxes: list[RuntimeSandbox]
    total: int
    active: int
    idle_count: int


@router.get("/v2/runtime", response_model=RuntimeSandboxListResponse)
async def list_runtime_sandboxes(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List sandboxes in v2 RuntimePage shape (flavor / cpu / mem / ttl)."""
    metas = _scan_workspaces()
    scoped = _filter_by_scope(metas, ctx)

    runtime = get_docker_runtime()
    out: list[RuntimeSandbox] = []
    for m in scoped:
        ws_id = m.get("id", "")
        title = _workspace_title(m)
        flavor = "Vibe" if m.get("kind") == "vibe" else "睿鲸"
        # Resource metrics: docker_runtime may or may not provide stats; default to 0
        cpu = float(m.get("cpu", 0.0))
        cpu_max = int(m.get("cpu_max", 4 if flavor == "Vibe" else 2))
        mem = float(m.get("mem", 0.0))
        mem_max = int(m.get("mem_max", 8 if flavor == "Vibe" else 4))
        disk = float(m.get("disk", 0.0))
        idle = m.get("idle_minutes", "0 min")
        if isinstance(idle, (int, float)):
            idle = f"{int(idle)} min"
        ttl = m.get("ttl", "—")
        created = m.get("created_at", "—")
        image = m.get("image", "node:20-alpine" if flavor == "睿鲸" else "code-server")

        # Status mapping from container_status + idle
        cs = (m.get("container_status") or "").lower()
        if cs == "running":
            status = "active"
        elif cs in ("exited", "paused"):
            status = "recycling"
        else:
            status = "idle"

        out.append(RuntimeSandbox(
            id=ws_id[:8] if ws_id else "—",
            name=title,
            workspace=ws_id,
            flavor=flavor,
            user=m.get("owner_username") or str(m.get("user_id", "")),
            cpu=cpu, cpu_max=cpu_max,
            mem=mem, mem_max=mem_max,
            disk=disk,
            idle=str(idle),
            status=status,
            ttl=str(ttl),
            created=str(created),
            image=image,
        ))
    active = sum(1 for s in out if s.status == "active")
    idle_count = sum(1 for s in out if s.status == "idle")
    return RuntimeSandboxListResponse(sandboxes=out, total=len(out), active=active, idle_count=idle_count)
```

The existing imports (`_scan_workspaces`, `_filter_by_scope`, `_workspace_title`, `get_docker_runtime`, `AuthContext`, `Annotated`, `Depends`, `AsyncSession`, `get_db`) are already in the file — no new imports needed.

- [ ] **Step 2: Smoke test**

```bash
cd backend && uvicorn app.main:app --reload --port 8001 &
sleep 3
curl -s http://localhost:8001/online-coding/sandboxes/v2/runtime -H "Cookie: <auth>" | head -30
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/sandboxes.py
git commit -m "feat(api): /online-coding/sandboxes/v2/runtime — v2 RuntimePage shape (flavor/cpu/mem/ttl)"
```

### Task 1.5 — Frontend `frontend/src/api/sandbox.ts` + store + wire

- [ ] **Step 1: Write the API module**

```ts
// frontend/src/api/sandbox.ts
import request from '@/utils/request'

export interface RuntimeSandbox {
  id: string
  name: string
  workspace: string
  flavor: '睿鲸' | 'Vibe'
  user: string
  cpu: number
  cpu_max: number
  mem: number
  mem_max: number
  disk: number
  idle: string
  status: 'active' | 'idle' | 'recycling'
  ttl: string
  created: string
  image: string
}

export interface RuntimeSandboxListResponse {
  sandboxes: RuntimeSandbox[]
  total: number
  active: number
  idle_count: number
}

export const runtimeSandboxApi = {
  list(): Promise<RuntimeSandboxListResponse> {
    return request({ url: '/online-coding/sandboxes/v2/runtime', method: 'get' }).then(r => r.data)
  },
}
```

- [ ] **Step 2: Write the store**

```ts
// frontend/src/stores/sandbox.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runtimeSandboxApi, type RuntimeSandbox } from '@/api/sandbox'

export const useRuntimeSandboxStore = defineStore('runtime-sandbox', () => {
  const sandboxes = ref<RuntimeSandbox[]>([])
  const total = ref(0)
  const activeCount = ref(0)
  const idleCount = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSandboxes() {
    loading.value = true
    error.value = null
    try {
      const r = await runtimeSandboxApi.list()
      sandboxes.value = r.sandboxes
      total.value = r.total
      activeCount.value = r.active
      idleCount.value = r.idle_count
    } catch (e: any) {
      error.value = e?.message || 'fetch sandboxes failed'
    } finally {
      loading.value = false
    }
  }

  return { sandboxes, total, activeCount, idleCount, loading, error, fetchSandboxes }
})
```

- [ ] **Step 3: Wire `RuntimePage.vue` (sandboxes tab only)**

In `frontend/src/views/v2/RuntimePage.vue`:
1. Replace the inline `const SANDBOXES = [...]` with: import store + onMounted call.
2. Update the template references: `SANDBOXES` → `sandboxStore.sandboxes`.
3. Update the stats card "运行中沙箱" to use `sandboxStore.activeCount` / `sandboxStore.total`.

Keep the inline `PIPELINES`, `ENVIRONMENTS`, `DEPLOYMENTS` seeds — those are wired in later sessions.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/sandbox.ts frontend/src/stores/sandbox.ts frontend/src/views/v2/RuntimePage.vue
git commit -m "feat(v2): wire RuntimePage sandboxes tab to useRuntimeSandboxStore (real backend)"
```

**Session 1 checkpoint:** `/mcp` page renders real backend data (8 servers same as seed). `/runtime → 沙箱` tab shows actual code-server sandboxes from the host filesystem (zero when no workspaces are running). vue-tsc clean.

---

## Session 2 — `/runtime` Environments tab + `/specs`

**Objective:** Wire the runtime environments tab to `/platform-envs` (existing endpoint), and add SPEC version-history list endpoint for the /specs page.

**Files:**

- Create: `frontend/src/api/runtimeEnv.ts` (uses existing `/platform-envs/*` endpoints — possibly merges with the existing `frontend/src/api/platformEnv.ts`)
- Create: `frontend/src/stores/runtimeEnv.ts`
- Modify: `frontend/src/views/v2/RuntimePage.vue` (envs tab)
- Create: `backend/app/routes/specs_v2.py` (NEW endpoint `/api/specs-v2` returning per-app SPEC list with versions)
- Create: `frontend/src/api/specsV2.ts`
- Create: `frontend/src/stores/specsV2.ts`
- Modify: `frontend/src/views/v2/SpecsPage.vue`
- Modify: `backend/app/main.py`

### Task 2.1 — Runtime envs frontend store

`backend/app/routes/platform_envs.py:50` already has `GET /platform-envs` returning environments. Read its response shape:

- [ ] **Step 1: Read the existing endpoint**

```bash
sed -n '50,100p' backend/app/routes/platform_envs.py
```

Identify the response Pydantic model. The shape includes `id`, `name`, `endpoint`, `tenant_id`, `tenant_name`, `is_default` and some others.

- [ ] **Step 2: Create `frontend/src/api/runtimeEnv.ts`**

Mirror the existing `frontend/src/api/platformEnv.ts` if it already exists. Check:

```bash
cat frontend/src/api/platformEnv.ts | head -30
```

If it exposes a `list()` function returning environments, REUSE that — don't duplicate. Just add to the existing store. If not, write:

```ts
// frontend/src/api/runtimeEnv.ts
import request from '@/utils/request'

export interface RuntimeEnv {
  id: string  // 'dev' / 'test' / 'prod' — matches v2 design
  name: string
  endpoint: string
  tenant: string
  tenant_name: string
  health: 'ok' | 'warn' | 'error'
  heartbeat: string
  deployed_apps: number
  default: boolean
  key_expiry: string
  key_warn?: boolean
}

export interface RuntimeEnvListResponse {
  environments: RuntimeEnv[]
  total: number
}

export const runtimeEnvApi = {
  list(): Promise<RuntimeEnvListResponse> {
    return request({ url: '/platform-envs', method: 'get' }).then(r => {
      // Adapt the existing response (read response shape from platform_envs.py to write the mapper here)
      const items = (r.data?.envs || r.data?.items || r.data || []) as any[]
      const environments: RuntimeEnv[] = items.map((e: any) => ({
        id: e.alias || e.id || '',
        name: e.name || '',
        endpoint: e.platform_url || e.endpoint || '',
        tenant: String(e.platform_tenant_id || e.tenant || ''),
        tenant_name: e.tenant_name || e.platform_tenant_name || '',
        health: e.health || 'ok',
        heartbeat: e.last_test_at || e.heartbeat || '—',
        deployed_apps: e.deployed_apps || 0,
        default: !!e.is_default,
        key_expiry: e.key_expiry || '—',
        key_warn: !!e.key_warn,
      }))
      return { environments, total: environments.length }
    })
  },
}
```

The mapper inside `.then()` is necessary because backend response shape doesn't quite match the v2 page's expected fields. If backend fields like `health` / `deployed_apps` / `key_expiry` don't exist on `PlatformEnv` today, those values default to placeholders — fix in Task 2.2.

- [ ] **Step 3: Write the store**

```ts
// frontend/src/stores/runtimeEnv.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runtimeEnvApi, type RuntimeEnv } from '@/api/runtimeEnv'

export const useRuntimeEnvStore = defineStore('runtime-env', () => {
  const environments = ref<RuntimeEnv[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchEnvironments() {
    loading.value = true
    try {
      const r = await runtimeEnvApi.list()
      environments.value = r.environments
    } catch (e: any) {
      error.value = e?.message || 'fetch env failed'
    } finally {
      loading.value = false
    }
  }

  return { environments, loading, error, fetchEnvironments }
})
```

- [ ] **Step 4: Wire `RuntimePage.vue` envs tab**

In `RuntimePage.vue`: remove inline `const ENVIRONMENTS = [...]`. Add `useRuntimeEnvStore` import + onMounted fetch. Update template references.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/runtimeEnv.ts frontend/src/stores/runtimeEnv.ts frontend/src/views/v2/RuntimePage.vue
git commit -m "feat(v2): wire RuntimePage envs tab to /platform-envs"
```

### Task 2.2 — Extend `platform_envs.py` with computed fields

The mapper in Task 2.1 substituted placeholders for `health`, `deployed_apps`, `key_expiry`, `key_warn`. Add these to the backend response.

- [ ] **Step 1: Modify `backend/app/routes/platform_envs.py:50` (list endpoint)**

Add fields to the response. Look at the existing endpoint's response Pydantic model — call it `PlatformEnvResp`. Extend it:

```python
class PlatformEnvResp(BaseModel):  # existing — find via grep
    # ... existing fields ...
    health: str = "ok"
    heartbeat: str = "—"
    deployed_apps: int = 0
    key_expiry: str = "—"
    key_warn: bool = False
```

In the list handler:
- `health`: if `env.last_test_status == 'success'`, `"ok"`; else `"warn"`.
- `heartbeat`: format `env.last_test_at` as relative time, e.g., `"1m 前"`. Use a small helper.
- `deployed_apps`: query `Application` table count where `apaas_app_id IS NOT NULL` AND `platform_env_id == env.id`.
- `key_expiry`: read `env.api_key_expires_at` (or whatever the field is) as `"YYYY-MM-DD"`.
- `key_warn`: True if `key_expiry < today + 30 days`.

If any of these fields don't exist on the `PlatformEnv` model, return safe defaults. Don't add migrations in this task — flag for a follow-up.

- [ ] **Step 2: Commit**

```bash
git add backend/app/routes/platform_envs.py
git commit -m "feat(api): extend /platform-envs with health/heartbeat/deployed_apps/key_expiry for v2 envs tab"
```

### Task 2.3 — SPEC list endpoint `/api/specs-v2`

The existing `backend/app/routes/spec.py` works on individual specs by id, but the v2 `/specs` page needs a list of specs across apps with version timelines. Add a new endpoint.

- [ ] **Step 1: Write `backend/app/routes/specs_v2.py`**

```python
# backend/app/routes/specs_v2.py
"""V2 SPEC list endpoint — returns app SPECs with version timelines."""
from __future__ import annotations
from typing import Annotated, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application
from app.models.spec import Spec, SpecVersion  # assumes these exist; if not, see below

router = APIRouter(prefix="/api/specs-v2", tags=["specs-v2"])


class SpecVersionItem(BaseModel):
    v: int
    status: str  # draft / test / prod / archived
    note: str
    author: str
    date: str


class SpecListItem(BaseModel):
    id: str
    app_id: int
    app_name: str
    latest: int
    diff_add: int
    diff_mod: int
    origin: str
    versions: list[SpecVersionItem]
    sections: list[dict]  # [{name, count}]
    excerpt: str = ""


class SpecListResponse(BaseModel):
    specs: list[SpecListItem]
    total: int


@router.get("", response_model=SpecListResponse)
async def list_specs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Pull all apps the user has access to.
    apps = (await db.execute(
        select(Application).where(Application.tenant_id == ctx.tenant_id)
    )).scalars().all()

    out: list[SpecListItem] = []
    for app in apps:
        # If spec storage exists in DB, derive versions; otherwise return one synthetic item.
        # For first pass: synthesize one version from app metadata.
        out.append(SpecListItem(
            id=f"spec-{app.id}",
            app_id=app.id,
            app_name=app.name,
            latest=1,
            diff_add=0,
            diff_mod=0,
            origin="—",
            versions=[
                SpecVersionItem(
                    v=1,
                    status="prod" if app.apaas_app_id else "draft",
                    note="—",
                    author=ctx.user.username,
                    date=app.updated_at.strftime("%Y-%m-%d") if hasattr(app, "updated_at") and app.updated_at else "—",
                )
            ],
            sections=[
                {"name": "数据模型", "count": 0},
                {"name": "表单", "count": 0},
                {"name": "流程", "count": 0},
                {"name": "角色权限", "count": 0},
                {"name": "字典", "count": 0},
            ],
            excerpt="",
        ))
    return SpecListResponse(specs=out, total=len(out))
```

If `Spec` / `SpecVersion` models don't exist in `backend/app/models/spec.py` (read it first to verify), DROP that import and synthesize as shown. The endpoint returns a SPEC stub per app; richer version data comes in a follow-up task when SPEC versions are stored persistently.

- [ ] **Step 2: Include router**

In `backend/app/main.py`:

```python
from app.routes import specs_v2
app.include_router(specs_v2.router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/specs_v2.py backend/app/main.py
git commit -m "feat(api): /api/specs-v2 — SPEC list endpoint for v2 /specs page (one synthetic version per app)"
```

### Task 2.4 — Frontend specs api + store + wire

- [ ] **Step 1: Write API + store**

```ts
// frontend/src/api/specsV2.ts
import request from '@/utils/request'

export interface SpecVersionItem { v: number; status: 'draft' | 'test' | 'prod' | 'archived'; note: string; author: string; date: string }
export interface SpecListItem {
  id: string
  app_id: number
  app_name: string
  latest: number
  diff_add: number
  diff_mod: number
  origin: string
  versions: SpecVersionItem[]
  sections: { name: string; count: number }[]
  excerpt: string
}
export interface SpecListResponse { specs: SpecListItem[]; total: number }

export const specsV2Api = {
  list(): Promise<SpecListResponse> {
    return request({ url: '/api/specs-v2', method: 'get' }).then(r => r.data)
  },
}
```

```ts
// frontend/src/stores/specsV2.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { specsV2Api, type SpecListItem } from '@/api/specsV2'

export const useSpecsV2Store = defineStore('specs-v2', () => {
  const specs = ref<SpecListItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSpecs() {
    loading.value = true
    try {
      const r = await specsV2Api.list()
      specs.value = r.specs
    } catch (e: any) {
      error.value = e?.message || 'fetch specs failed'
    } finally {
      loading.value = false
    }
  }

  return { specs, loading, error, fetchSpecs }
})
```

- [ ] **Step 2: Wire `SpecsPage.vue`**

Replace the inline `specs` seed array with `useSpecsV2Store`. Update the template's left list + right detail bindings.

Note: the page's default selected spec needs adjustment — instead of `specs.value[0]`, do `computed(() => specsStore.specs[0] ?? null)`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/specsV2.ts frontend/src/stores/specsV2.ts frontend/src/views/v2/SpecsPage.vue
git commit -m "feat(v2): wire SpecsPage to /api/specs-v2 (real apps, one synthetic version each)"
```

**Session 2 checkpoint:** /runtime envs tab shows real dev/test/prod environments configured for this tenant. /specs shows real apps' synthetic SPEC stubs. /mcp still works.

---

## Session 3 — `/agents` Agent Config Center

**Objective:** Create the `agent_configs` table + skill/MCP/knowledge bindings tables. Add `/api/agents` REST endpoint. Wire AgentsPage to it.

**Files:**

- Create: `backend/app/models/agent_config.py` (NEW model file)
- Modify: `backend/app/models/__init__.py` (export new models)
- Create: `backend/app/routes/agents_config.py` (NEW route)
- Create: `frontend/src/api/agents.ts`
- Create: `frontend/src/stores/agents.ts`
- Modify: `frontend/src/views/v2/AgentsPage.vue`
- Modify: `backend/app/main.py`
- Create: `backend/app/services/agent_seed.py` (seed default Builder/Coding/Vibe agents on tenant creation)

### Task 3.1 — Backend models

- [ ] **Step 1: Write `backend/app/models/agent_config.py`**

```python
# backend/app/models/agent_config.py
"""V2 Agent Config — Builder / Coding / Vibe agent configurations.

Each tenant has 3 default agents seeded on creation. Each agent has:
- model + system prompt + context window + max output (basic config)
- skills (many-to-many via agent_skill_bindings)
- MCP servers (many-to-many via agent_mcp_bindings)
- knowledge sources (industry packs + spec templates, via agent_knowledge_bindings)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentConfig(Base):
    """One row per (tenant_id, agent_id) — agent_id is 'builder' / 'whale' / 'vibe'."""
    __tablename__ = "agent_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_id", name="uq_tenant_agent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # 'builder' / 'whale' / 'vibe'

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    desc: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(16), default="brand")  # 'ai' / 'brand' / 'emerald'
    icon: Mapped[str] = mapped_column(String(32), default="chat")

    model: Mapped[str] = mapped_column(String(64), nullable=False)
    model_options: Mapped[list[str]] = mapped_column(JSON, default=list)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    context_window: Mapped[int] = mapped_column(Integer, default=200000)
    max_output: Mapped[int] = mapped_column(Integer, default=8192)

    # Stats (denormalized for fast read)
    active_calls: Mapped[int] = mapped_column(Integer, default=0)
    today_calls: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentSkill(Base):
    """Skills attached to an agent. Code/name/desc denormalized so we don't need a separate skill catalog table at first."""
    __tablename__ = "agent_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_config_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    desc: Mapped[str] = mapped_column(Text, default="")
    order_idx: Mapped[int] = mapped_column(Integer, default=0)


class AgentMcpBinding(Base):
    """MCP servers attached to an agent. mcp_id references mcp_servers table (or the in-memory registry today)."""
    __tablename__ = "agent_mcp_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_config_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    mcp_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_idx: Mapped[int] = mapped_column(Integer, default=0)


class AgentKnowledgeBinding(Base):
    """Knowledge sources: industry packs + spec templates."""
    __tablename__ = "agent_knowledge_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_config_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # 'industry_pack' / 'spec_template'
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_idx: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 2: Export from `__init__.py`**

In `backend/app/models/__init__.py`, add:

```python
from app.models.agent_config import (
    AgentConfig,
    AgentSkill,
    AgentMcpBinding,
    AgentKnowledgeBinding,
)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/agent_config.py backend/app/models/__init__.py
git commit -m "feat(model): agent_configs + 3 binding tables for v2 /agents page"
```

### Task 3.2 — Seeding service

- [ ] **Step 1: Write `backend/app/services/agent_seed.py`**

```python
# backend/app/services/agent_seed.py
"""Seed the 3 default agents (Builder / Coding / Vibe) for a tenant.

Called from startup hook (one-time per tenant) and on tenant creation.
"""
from __future__ import annotations
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_config import (
    AgentConfig, AgentSkill, AgentMcpBinding, AgentKnowledgeBinding,
)

logger = logging.getLogger(__name__)


# Seed data taken verbatim from frontend/src/views/v2/AgentsPage.vue inline seeds
SEED = [
    {
        "agent_id": "builder",
        "name": "睿鲸 AI Builder",
        "role": "业务搭建",
        "desc": "从对话出发，把零碎需求整理成标准 SPEC 设计文档，并驱动 aPaaS 平台生成应用。",
        "tone": "ai",
        "icon": "chat",
        "model": "Claude Haiku 4.5",
        "model_options": ["Claude Haiku 4.5", "Qwen-Max", "MiniMax abab6"],
        "system_prompt": "你是得帆云 aPaaS Builder 的业务搭建助手，目标是把用户的业务需求转化为标准设计文档（SPEC），同时驱动 aPaaS API 生成对应的模型、表单、流程、权限。",
        "context_window": 200000,
        "max_output": 8192,
        "skills": [
            ("apaas-app-builder", "应用搭建", "把 SPEC 翻译为 aPaaS YAML 配置 + 调用执行引擎"),
            ("apaas-app-updater", "应用增量更新", "对已部署应用做增量改动 + diff"),
            ("apaas-api-reference", "API 参考", "查询 aPaaS API 文档"),
            ("std-design-doc", "标准设计文档", "按章节模板生成 / 校验设计文档"),
            ("requirements-elicit", "需求挖掘", "多轮追问 + 角色 / 边界澄清"),
        ],
        "mcps": ["mcp-1", "mcp-3", "mcp-8"],
        "knowledge": [
            ("industry_pack", "pkg-mfg"),
            ("industry_pack", "pkg-crm"),
            ("spec_template", "std_design_doc"),
            ("spec_template", "mfg_design_doc"),
            ("spec_template", "crm_design_doc"),
        ],
    },
    {
        "agent_id": "whale",
        "name": "睿鲸 AI Coding",
        "role": "低代码组件生成",
        "desc": "把组件需求翻译为符合 aPaaS 规范的 Vue 组件，并发布到组件市场。",
        "tone": "brand",
        "icon": "whale",
        "model": "Claude Haiku 4.5",
        "model_options": ["Claude Haiku 4.5", "Qwen-Coder", "DeepSeek Coder"],
        "system_prompt": "你是得帆云 aPaaS 的组件生成助手，目标是生成符合平台规范的 Vue 自开发组件（表单组件 / 页面 / 列表视图 / 后端接口），并打包为 UMD。",
        "context_window": 200000,
        "max_output": 8192,
        "skills": [
            ("form-component", "表单组件生成", "按 Element UI 2.x 规范生成表单组件"),
            ("form-page", "页面生成", "生成 form-page 整页组件"),
            ("backend-api", "后端接口生成", "生成 aPaaS 后端 OpenAPI 接口"),
            ("umd-build", "UMD 打包", "编译为可挂载到平台的 UMD bundle"),
        ],
        "mcps": ["mcp-1", "mcp-2"],
        "knowledge": [],
    },
    {
        "agent_id": "vibe",
        "name": "Vibe Coding",
        "role": "全代码工作区助手",
        "desc": "code-server 内置 Chat 扩展，帮你直接编辑 / 重构本项目代码。Cursor 风格。",
        "tone": "emerald",
        "icon": "code",
        "model": "MiniMax abab6",
        "model_options": ["Claude Haiku 4.5", "Qwen-Coder", "MiniMax abab6"],
        "system_prompt": "你是嵌入 code-server 工作区里的代码助手，可以读写工程文件、执行命令、查看 git 状态。优先用项目内已有模式。",
        "context_window": 200000,
        "max_output": 8192,
        "skills": [
            ("project-search", "项目检索", "ripgrep + 语义搜索"),
            ("multi-edit", "多文件编辑", "并行修改多个文件 + diff 预览"),
            ("terminal-exec", "终端执行", "运行 npm / git / 测试命令"),
            ("git-aware", "Git 上下文", "理解 branch / commit / 未提交变更"),
        ],
        "mcps": ["mcp-2", "mcp-6"],
        "knowledge": [],
    },
]


async def seed_agents_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    """Idempotent: only inserts if no row exists for (tenant_id, agent_id)."""
    existing = (await db.execute(
        select(AgentConfig).where(AgentConfig.tenant_id == tenant_id)
    )).scalars().all()
    existing_ids = {a.agent_id for a in existing}

    for entry in SEED:
        if entry["agent_id"] in existing_ids:
            continue
        cfg = AgentConfig(
            tenant_id=tenant_id,
            agent_id=entry["agent_id"],
            name=entry["name"],
            role=entry["role"],
            desc=entry["desc"],
            tone=entry["tone"],
            icon=entry["icon"],
            model=entry["model"],
            model_options=entry["model_options"],
            system_prompt=entry["system_prompt"],
            context_window=entry["context_window"],
            max_output=entry["max_output"],
        )
        db.add(cfg)
        await db.flush()  # need cfg.id

        for i, (code, name, desc) in enumerate(entry["skills"]):
            db.add(AgentSkill(agent_config_id=cfg.id, code=code, name=name, desc=desc, order_idx=i))
        for i, mcp_id in enumerate(entry["mcps"]):
            db.add(AgentMcpBinding(agent_config_id=cfg.id, mcp_id=mcp_id, order_idx=i))
        for i, (kind, ref_id) in enumerate(entry["knowledge"]):
            db.add(AgentKnowledgeBinding(agent_config_id=cfg.id, kind=kind, ref_id=ref_id, order_idx=i))

    await db.commit()
    logger.info(f"seeded agents for tenant {tenant_id}")
```

- [ ] **Step 2: Wire seed call into startup or first-login**

In `backend/app/main.py` (or the existing startup hook), after a successful auth-context resolution where `ctx.tenant_id` is first known, call `seed_agents_for_tenant(db, ctx.tenant_id)`. Look for an existing pattern like `seed_data.py` — if a `seed_default_tenants` function exists, add the call there. Otherwise lazy-call from the GET endpoint in Task 3.3 (cheaper).

For lazy approach: in the list endpoint (Task 3.3), if `agent_configs` is empty for this tenant, call `seed_agents_for_tenant` then re-query.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/agent_seed.py
git commit -m "feat(service): agent_seed.py — seed Builder/Coding/Vibe configs per tenant"
```

### Task 3.3 — Backend `/api/agents` route

- [ ] **Step 1: Write `backend/app/routes/agents_config.py`**

```python
# backend/app/routes/agents_config.py
"""V2 Agent Config CRUD."""
from __future__ import annotations
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.agent_config import (
    AgentConfig, AgentSkill, AgentMcpBinding, AgentKnowledgeBinding,
)
from app.services.agent_seed import seed_agents_for_tenant

router = APIRouter(prefix="/api/agents", tags=["agents-v2"])


class SkillItem(BaseModel):
    code: str
    name: str
    desc: str


class KnowledgeItem(BaseModel):
    kind: str
    ref_id: str


class AgentConfigResp(BaseModel):
    id: str
    name: str
    role: str
    desc: str
    tone: str
    icon: str
    model: str
    model_options: list[str]
    system_prompt: str
    context_window: int
    max_output: int
    active_calls: int
    today_calls: int
    skills: list[SkillItem]
    mcps: list[str]
    knowledge: dict  # { industry_packs: [...], spec_templates: [...] }


class AgentListResp(BaseModel):
    agents: list[AgentConfigResp]


class AgentUpdateReq(BaseModel):
    model: Optional[str] = None
    system_prompt: Optional[str] = None


def _to_resp(cfg: AgentConfig, skills: list[AgentSkill], mcps: list[AgentMcpBinding], knowledge: list[AgentKnowledgeBinding]) -> AgentConfigResp:
    industry_packs = [k.ref_id for k in knowledge if k.kind == "industry_pack"]
    spec_templates = [k.ref_id for k in knowledge if k.kind == "spec_template"]
    return AgentConfigResp(
        id=cfg.agent_id,
        name=cfg.name, role=cfg.role, desc=cfg.desc, tone=cfg.tone, icon=cfg.icon,
        model=cfg.model, model_options=cfg.model_options or [],
        system_prompt=cfg.system_prompt,
        context_window=cfg.context_window, max_output=cfg.max_output,
        active_calls=cfg.active_calls, today_calls=cfg.today_calls,
        skills=[SkillItem(code=s.code, name=s.name, desc=s.desc) for s in sorted(skills, key=lambda x: x.order_idx)],
        mcps=[m.mcp_id for m in sorted(mcps, key=lambda x: x.order_idx)],
        knowledge={"industry_packs": industry_packs, "spec_templates": spec_templates},
    )


@router.get("", response_model=AgentListResp)
async def list_agents(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (await db.execute(
        select(AgentConfig).where(AgentConfig.tenant_id == ctx.tenant_id)
    )).scalars().all()
    if not rows:
        await seed_agents_for_tenant(db, ctx.tenant_id)
        rows = (await db.execute(
            select(AgentConfig).where(AgentConfig.tenant_id == ctx.tenant_id)
        )).scalars().all()

    out = []
    for cfg in rows:
        skills = (await db.execute(select(AgentSkill).where(AgentSkill.agent_config_id == cfg.id))).scalars().all()
        mcps = (await db.execute(select(AgentMcpBinding).where(AgentMcpBinding.agent_config_id == cfg.id))).scalars().all()
        knowledge = (await db.execute(select(AgentKnowledgeBinding).where(AgentKnowledgeBinding.agent_config_id == cfg.id))).scalars().all()
        out.append(_to_resp(cfg, skills, mcps, knowledge))
    return AgentListResp(agents=out)


@router.put("/{agent_id}", response_model=AgentConfigResp)
async def update_agent(
    agent_id: str,
    payload: AgentUpdateReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    cfg = (await db.execute(
        select(AgentConfig).where(
            AgentConfig.tenant_id == ctx.tenant_id,
            AgentConfig.agent_id == agent_id,
        )
    )).scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, f"agent {agent_id} not found for tenant {ctx.tenant_id}")
    if payload.model is not None:
        if cfg.model_options and payload.model not in cfg.model_options:
            raise HTTPException(400, f"model {payload.model} not in allowed options")
        cfg.model = payload.model
    if payload.system_prompt is not None:
        cfg.system_prompt = payload.system_prompt
    await db.commit()

    skills = (await db.execute(select(AgentSkill).where(AgentSkill.agent_config_id == cfg.id))).scalars().all()
    mcps = (await db.execute(select(AgentMcpBinding).where(AgentMcpBinding.agent_config_id == cfg.id))).scalars().all()
    knowledge = (await db.execute(select(AgentKnowledgeBinding).where(AgentKnowledgeBinding.agent_config_id == cfg.id))).scalars().all()
    return _to_resp(cfg, skills, mcps, knowledge)
```

- [ ] **Step 2: Include router**

```python
# backend/app/main.py
from app.routes import agents_config
app.include_router(agents_config.router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/agents_config.py backend/app/main.py
git commit -m "feat(api): /api/agents GET list + PUT update (model/prompt)"
```

### Task 3.4 — Frontend api + store + wire

- [ ] **Step 1: Write `frontend/src/api/agents.ts`**

```ts
import request from '@/utils/request'

export interface AgentSkillItem { code: string; name: string; desc: string }
export interface AgentConfig {
  id: string
  name: string
  role: string
  desc: string
  tone: 'ai' | 'brand' | 'emerald'
  icon: string
  model: string
  model_options: string[]
  system_prompt: string
  context_window: number
  max_output: number
  active_calls: number
  today_calls: number
  skills: AgentSkillItem[]
  mcps: string[]
  knowledge: { industry_packs: string[]; spec_templates: string[] }
}
export interface AgentListResponse { agents: AgentConfig[] }

export const agentsApi = {
  list(): Promise<AgentListResponse> {
    return request({ url: '/api/agents', method: 'get' }).then(r => r.data)
  },
  update(agentId: string, payload: { model?: string; system_prompt?: string }): Promise<AgentConfig> {
    return request({ url: `/api/agents/${agentId}`, method: 'put', data: payload }).then(r => r.data)
  },
}
```

- [ ] **Step 2: Write store**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { agentsApi, type AgentConfig } from '@/api/agents'

export const useAgentsStore = defineStore('agents', () => {
  const agents = ref<AgentConfig[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAgents() {
    loading.value = true
    try { agents.value = (await agentsApi.list()).agents }
    catch (e: any) { error.value = e?.message || 'fetch agents failed' }
    finally { loading.value = false }
  }

  async function saveAgent(agentId: string, payload: { model?: string; system_prompt?: string }) {
    const updated = await agentsApi.update(agentId, payload)
    const idx = agents.value.findIndex(a => a.id === agentId)
    if (idx >= 0) agents.value[idx] = updated
  }

  return { agents, loading, error, fetchAgents, saveAgent }
})
```

- [ ] **Step 3: Wire `AgentsPage.vue`**

Remove the inline `AGENTS = [...]` seed. Replace with:
- `import { useAgentsStore } from '@/stores/agents'`
- `const agentsStore = useAgentsStore()`
- `onMounted(() => agentsStore.fetchAgents())`
- Update `cur` computed to read from `agentsStore.agents`
- Wire `onSave()` to `agentsStore.saveAgent(cur.id, { model: curModel.value, system_prompt: curPrompt.value })`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/agents.ts frontend/src/stores/agents.ts frontend/src/views/v2/AgentsPage.vue
git commit -m "feat(v2): wire AgentsPage to /api/agents (real backend + save)"
```

**Session 3 checkpoint:** /agents loads agents from DB; first visit triggers seed for the tenant; saving model or system prompt persists.

---

## Session 4 — `/industry` Knowledge Base

**Objective:** Create `industry_packs` + ontology tables, route `/api/industry`. Seed 4 default packs (制造装备 / 客户运营 / 智慧物流 / 政企服务) plus their ontology graphs.

**Files:**

- Create: `backend/app/models/industry.py` (NEW)
- Create: `backend/app/services/industry_seed.py` (NEW)
- Create: `backend/app/routes/industry.py` (NEW)
- Create: `frontend/src/api/industry.ts`
- Create: `frontend/src/stores/industry.ts`
- Modify: `frontend/src/views/v2/IndustryPage.vue`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

### Task 4.1 — Models

- [ ] **Step 1: Write `backend/app/models/industry.py`**

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class IndustryPack(Base):
    """Industry pack metadata. Shared across all tenants (system table)."""
    __tablename__ = "industry_packs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 'pkg-mfg' etc.
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tone: Mapped[str] = mapped_column(String(16), default="brand")
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    maintainer: Mapped[str] = mapped_column(String(128), default="")
    updated: Mapped[str] = mapped_column(String(16), default="")  # "5/14" display format

    # Counters
    entities_count: Mapped[int] = mapped_column(Integer, default=0)
    relations_count: Mapped[int] = mapped_column(Integer, default=0)
    workflows_count: Mapped[int] = mapped_column(Integer, default=0)
    dicts_count: Mapped[int] = mapped_column(Integer, default=0)
    forms_count: Mapped[int] = mapped_column(Integer, default=0)
    roles_count: Mapped[int] = mapped_column(Integer, default=0)

    # Ontology JSON (entities + relations + workflows + dict-highlight)
    ontology: Mapped[dict] = mapped_column(JSON, default=dict)

    # Adopted apps (denormalized JSON list of names)
    adopted: Mapped[list[str]] = mapped_column(JSON, default=list)


class IndustryPackInstall(Base):
    """Per-tenant install state for a pack."""
    __tablename__ = "industry_pack_installs"
    __table_args__ = (UniqueConstraint("tenant_id", "pack_id", name="uq_tenant_pack"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pack_id: Mapped[str] = mapped_column(String(64), ForeignKey("industry_packs.id"), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: Export from `__init__.py`**

```python
from app.models.industry import IndustryPack, IndustryPackInstall
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/industry.py backend/app/models/__init__.py
git commit -m "feat(model): industry_packs + industry_pack_installs"
```

### Task 4.2 — Seed service

- [ ] **Step 1: Write `backend/app/services/industry_seed.py`**

The seed data is large (4 packs + full ontology for pkg-mfg). Pull from `frontend/src/views/v2/IndustryPage.vue` (currently inline `INDUSTRY_PACKS` and `INDUSTRY_ONTOLOGY`). The full seed is too long for this plan body — read the existing inline arrays and translate them into the seed dict in this file. Key points:

- 4 packs: pkg-mfg (amber, v2.1, installed, default), pkg-crm (sky, v3.0, installed), pkg-logi (emerald, v1.4), pkg-govt (rose, v0.9)
- pkg-mfg has the full ontology (9 entities + 8 relations + 5 workflows + 4 dict highlights from `data.js` lines 824-861)
- Other 3 packs have empty `ontology = {}` for now
- Seed runs once at startup if `industry_packs` table is empty
- `IndustryPackInstall` rows seeded per-tenant on first /industry visit (similar to agents seed)

The seed function shape:

```python
async def seed_industry_packs(db: AsyncSession) -> None:
    existing = (await db.execute(select(IndustryPack))).scalars().all()
    if existing:
        return  # already seeded
    # Build the 4 IndustryPack rows + commit
    # (copy data from frontend IndustryPage.vue inline seed)
```

- [ ] **Step 2: Wire to startup hook**

In `backend/app/main.py` `startup_event` or equivalent (search for `@app.on_event("startup")` or `lifespan`), call `await seed_industry_packs(db)` after the existing initialization.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/industry_seed.py backend/app/main.py
git commit -m "feat(service): seed 4 default industry packs + manufacturing ontology"
```

### Task 4.3 — Route `/api/industry`

- [ ] **Step 1: Write `backend/app/routes/industry.py`**

```python
from __future__ import annotations
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.industry import IndustryPack, IndustryPackInstall

router = APIRouter(prefix="/api/industry", tags=["industry"])


class IndustryStatsResp(BaseModel):
    entities: int; relations: int; workflows: int; dicts: int; forms: int; roles: int


class IndustryPackResp(BaseModel):
    id: str; name: str; code: str; tone: str; version: str
    installed: bool; default: bool
    summary: str
    stats: IndustryStatsResp
    adopted: list[str]
    maintainer: str; updated: str


class IndustryPackListResp(BaseModel):
    packs: list[IndustryPackResp]


class OntologyResp(BaseModel):
    pack: str
    entities: list[dict]
    relations: list[dict]
    workflows: list[dict]
    dictHighlight: list[dict]


@router.get("/packs", response_model=IndustryPackListResp)
async def list_packs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    packs = (await db.execute(select(IndustryPack))).scalars().all()
    installs = (await db.execute(
        select(IndustryPackInstall).where(IndustryPackInstall.tenant_id == ctx.tenant_id)
    )).scalars().all()
    installed_ids = {i.pack_id for i in installs}

    return IndustryPackListResp(packs=[
        IndustryPackResp(
            id=p.id, name=p.name, code=p.code, tone=p.tone, version=p.version,
            installed=p.id in installed_ids, default=p.is_default,
            summary=p.summary,
            stats=IndustryStatsResp(
                entities=p.entities_count, relations=p.relations_count,
                workflows=p.workflows_count, dicts=p.dicts_count,
                forms=p.forms_count, roles=p.roles_count,
            ),
            adopted=p.adopted or [],
            maintainer=p.maintainer, updated=p.updated,
        )
        for p in packs
    ])


@router.get("/packs/{pack_id}/ontology", response_model=OntologyResp)
async def get_ontology(
    pack_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pack = (await db.execute(select(IndustryPack).where(IndustryPack.id == pack_id))).scalar_one_or_none()
    if not pack:
        raise HTTPException(404, f"pack {pack_id} not found")
    ont = pack.ontology or {}
    return OntologyResp(
        pack=pack_id,
        entities=ont.get("entities", []),
        relations=ont.get("relations", []),
        workflows=ont.get("workflows", []),
        dictHighlight=ont.get("dictHighlight", []),
    )


@router.post("/packs/{pack_id}/install")
async def install_pack(
    pack_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pack = (await db.execute(select(IndustryPack).where(IndustryPack.id == pack_id))).scalar_one_or_none()
    if not pack:
        raise HTTPException(404, f"pack {pack_id} not found")
    # Idempotent insert
    existing = (await db.execute(
        select(IndustryPackInstall).where(
            IndustryPackInstall.tenant_id == ctx.tenant_id,
            IndustryPackInstall.pack_id == pack_id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(IndustryPackInstall(tenant_id=ctx.tenant_id, pack_id=pack_id))
        await db.commit()
    return {"ok": True, "installed": True}
```

- [ ] **Step 2: Include router**

```python
from app.routes import industry
app.include_router(industry.router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/industry.py backend/app/main.py
git commit -m "feat(api): /api/industry packs list + ontology fetch + install"
```

### Task 4.4 — Frontend wire

- [ ] **Step 1: Write `frontend/src/api/industry.ts` + store**

(Standard pattern — see Sessions 1-3 for template. Mirror prop names from the backend response.)

- [ ] **Step 2: Wire `IndustryPage.vue`**

Replace inline `INDUSTRY_PACKS` + `INDUSTRY_ONTOLOGY` with store calls. `onInstall` calls `industryApi.install(pack.id)` and flips local `installed` flag on response.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/industry.ts frontend/src/stores/industry.ts frontend/src/views/v2/IndustryPage.vue
git commit -m "feat(v2): wire IndustryPage to /api/industry (4 packs + ontology)"
```

**Session 4 checkpoint:** /industry loads packs from DB; clicking 安装到当前租户 persists; ontology renders from backend JSON; refresh shows persisted install state.

---

## Session 5 — `/runtime` Pipelines + Deployments tabs

**Objective:** Add tables for pipeline runs and deployment history; wire the two remaining tabs of /runtime.

**Files:**

- Create: `backend/app/models/runtime.py` (NEW)
- Create: `backend/app/routes/runtime.py` (NEW)
- Create: `frontend/src/api/runtimePipeline.ts`
- Create: `frontend/src/api/runtimeDeployment.ts`
- Create: `frontend/src/stores/runtimePipeline.ts`
- Create: `frontend/src/stores/runtimeDeployment.ts`
- Modify: `frontend/src/views/v2/RuntimePage.vue` (pipelines + deployments tabs)
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

### Task 5.1 — Models

- [ ] **Step 1: Write `backend/app/models/runtime.py`**

Two tables:

```python
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'run-1284'
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(256))
    source: Mapped[str] = mapped_column(String(128))
    trigger: Mapped[str] = mapped_column(String(32))  # '自动' / '手动' / 'git push'
    user: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))  # running / success / failed / pending
    branch: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    env: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # dev/test/prod
    stages: Mapped[list[dict]] = mapped_column(JSON, default=list)


class DeploymentHistory(Base):
    __tablename__ = "deployment_history"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'dep-209'
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    app: Mapped[str] = mapped_column(String(128))
    app_code: Mapped[str] = mapped_column(String(64))
    env: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(32))
    user: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16))  # success / failed
    changes: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[str] = mapped_column(String(32), default="0s")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Export + commit**

Same pattern as previous sessions.

```bash
git add backend/app/models/runtime.py backend/app/models/__init__.py
git commit -m "feat(model): pipeline_runs + deployment_history"
```

### Task 5.2 — Route `/api/runtime`

- [ ] **Step 1: Write `backend/app/routes/runtime.py`**

Endpoints:
- `GET /api/runtime/pipelines` — list recent pipeline runs (newest first), filter by tenant
- `GET /api/runtime/deployments` — list deployment history, filter by tenant

Response shapes mirror `frontend/src/views/v2/RuntimePage.vue` `PIPELINES` and `DEPLOYMENTS` arrays.

Tenant filter via `ctx.tenant_id`. Format `started_at` to display strings (`14:22`, `昨天 18:14`) using a small helper.

If a tenant has no pipelines (most common at first), the response is `{ pipelines: [], total: 0 }`. The frontend should show an empty state in that case.

Commit:
```bash
git add backend/app/routes/runtime.py backend/app/main.py
git commit -m "feat(api): /api/runtime/pipelines + /deployments"
```

### Task 5.3 — Seed sample pipeline runs and deployments

Optional but high-value: seed ~3 sample runs and ~3 sample deployments per tenant on first /runtime visit. Pattern mirrors Session 3 / 4 seed services.

If skipped, the tabs show empty state until real CI/CD or real deploys populate them — that's the eventual state anyway. Decision in this task: seed for demo, or rely on real deploys.

**Recommendation:** seed 3 of each for the default tenant only (the demo tenant `p-default`). Production tenants stay empty until real activity.

Commit:
```bash
git add backend/app/services/runtime_seed.py
git commit -m "feat(service): seed sample pipeline_runs + deployment_history for default tenant"
```

### Task 5.4 — Frontend wire

Same pattern: 2 new api modules + 2 new stores + replace the inline `PIPELINES` and `DEPLOYMENTS` in `RuntimePage.vue`.

Commit:
```bash
git add frontend/src/api/runtimePipeline.ts frontend/src/api/runtimeDeployment.ts \
        frontend/src/stores/runtimePipeline.ts frontend/src/stores/runtimeDeployment.ts \
        frontend/src/views/v2/RuntimePage.vue
git commit -m "feat(v2): wire RuntimePage pipelines+deployments tabs to /api/runtime/*"
```

**Session 5 checkpoint:** All 4 RuntimePage tabs (sandboxes + pipelines + envs + deployments) hydrated from real backend.

---

## Cross-cutting deferred items (NOT in this plan)

- True CI/CD pipeline execution backend
- Sandbox resource metric collection (cpu/mem/disk %)
- Industry pack derivation (派生新包) — backend fork + version-bump flow
- SPEC version diff computation — currently `diff_add` / `diff_mod` are zero
- Deploy modal real result feedback — replace 2.5s simulated success with real backend deploy result
- Per-environment deployment via DeployConfirmModal's confirm event (currently `runDeploy` only calls existing `startDeployFromArtifact`)

---

## Self-Review

**Spec coverage:**
- ✅ /mcp: Session 1
- ✅ /runtime sandboxes: Session 1
- ✅ /runtime envs: Session 2
- ✅ /specs: Session 2
- ✅ /agents: Session 3
- ✅ /industry: Session 4
- ✅ /runtime pipelines: Session 5
- ✅ /runtime deployments: Session 5

**Type consistency:** Backend Pydantic field naming follows snake_case throughout; frontend interfaces mirror snake_case server fields directly without converting to camelCase (matches the convention used in existing `frontend/src/api/projects.ts`).

**Placeholder scan:** No "TBD", no "fill in details" — each task has concrete code or explicit "read existing X to see Y" instructions.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-v2-backend-integration.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per session, review between sessions.
2. **Inline Execution** — Execute sessions sequentially with checkpoint reviews.

Which approach?
