# AI Code 需求基线（③）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 vibe 单 agent 加 `requirement_write` 工具，AI 边聊边把需求结构化成「需求基线」（6 项），实时显示在只读的「需求」tab。

**Architecture:** 完全照搬现成的 `todos` 机制（thread JSON 列 + 工具覆盖式写 + agent loop SSE 推送 + getThread 序列化 + 前端 tab 渲染）。新增一条平行链路 `requirement_baseline` / `requirement_write` / `requirement_updated`。

**Tech Stack:** FastAPI + SQLAlchemy(JSON 列) + 现有 vibe_coding agent loop + Vue 3 `<script setup>`。

**验证方式:** 后端有 pytest（`tests/`，`asyncio_mode=auto`）—— 工具 handler 写单测。模型/迁移/SSE/序列化/prompt 靠后端启动 + getThread 验证。前端无测试框架 —— 「需求」tab 靠 dev server + 浏览器验证。**前提：后端在 :8000 跑着**（`{"status":"ok"}`），前端 dev server 5173。

**铁律:** 只动 `vibe_coding/*` + ai-coding 前端。不碰 apaas/低代码。

---

## 文件结构

| 文件 | 改动 |
|---|---|
| `backend/app/models/vibe_coding.py:59` | 模型加 `requirement_baseline` JSON 列 |
| `backend/app/database.py:122` | 启动迁移加一条 ALTER（幂等） |
| `backend/app/vibe_coding/tools.py` | TOOL_SCHEMAS 加 schema(:114 列表) + `execute_requirement_write` handler(仿 :714) + TOOL_HANDLERS 加 dispatch(:843) |
| `backend/app/vibe_coding/agent.py:476` | todos_updated 后加 requirement_updated SSE |
| `backend/app/routes/vibe_coding_chat.py:93` | `_thread_to_dict` 加 requirement_baseline |
| `backend/app/vibe_coding/prompts.py:23` | 第 2 步加 requirement_write 指令 |
| `backend/tests/test_requirement_write.py` | 新建 handler 单测 |
| `frontend/src/api/vibeCodingChat.ts:15` | VibeChatThread 加 requirement_baseline 类型 |
| `frontend/src/components/ai-coding/RequirementTab.vue` | 新建只读渲染组件 |
| `frontend/src/components/ai-coding/WorkspaceTabs.vue` | requirement 分支接 RequirementTab |

---

## 已确认锚点（照抄，勿猜）

- `todo_write` schema: `tools.py:241-273`（`TOOL_SCHEMAS: list[dict]` 始于 `:114`）
- `execute_todo_write` handler: `tools.py:714-737`（覆盖式写 `thread.todos` + `await db.commit()` + 返回 summary）
- `TOOL_HANDLERS` dispatch: `tools.py:843-853`
- agent SSE: `agent.py:474-476`（`if tool_name == "todo_write" and tc_db.status == "success": yield _sse("todos_updated", {...})`）
- 模型: `vibe_coding.py:59`（`todos: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)`）
- 迁移: `database.py:64-123`（ALTER 列表，每条 try/except 幂等；app_type 在 :120-122）
- 序列化: `vibe_coding_chat.py:84-96`（`_thread_to_dict`，`"todos": t.todos or []` 在 :93）
- prompt: `prompts.py:23-26`（### 第 2 步：拆 TODO + 开干）
- 前端类型: `vibeCodingChat.ts:7-18`（VibeChatThread，`todos` 在 :15）

---

### Task 1: 后端数据层 — 模型字段 + 迁移列

**Files:**
- Modify: `backend/app/models/vibe_coding.py:59`
- Modify: `backend/app/database.py:122`

- [ ] **Step 1: 模型加字段** —— 在 `vibe_coding.py` 的 `todos` 行（:59）下面加：

```python
    # 当前 todo list（agent 用 todo_write 维护），存 JSON：[{id, content, status}]
    todos: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 需求基线（agent 用 requirement_write 维护）：{roles,features,flows,external,ai_points,acceptance} 各 string[]
    requirement_baseline: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 2: 迁移加列** —— 在 `database.py` 的 `source_workspace_id` 那条（:122）后面加：

```python
            "ALTER TABLE applications ADD COLUMN source_workspace_id VARCHAR(60)",
            # ③需求基线: vibe agent 用 requirement_write 维护的结构化需求
            "ALTER TABLE vibe_coding_threads ADD COLUMN requirement_baseline JSON",
```

- [ ] **Step 3: 验证后端启动 + 列存在**

Run: 后端重启（用户终端 `cd backend && ./venv/bin/python run.py`，或已在跑则重启）
Expected: 启动无异常；`curl -s localhost:8000/api/health` → `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/vibe_coding.py backend/app/database.py
git commit -m "feat(ai-coding): vibe thread 加 requirement_baseline 列 + 迁移"
```

---

### Task 2: 后端工具 `requirement_write`（TDD）

**Files:**
- Create: `backend/tests/test_requirement_write.py`
- Modify: `backend/app/vibe_coding/tools.py`（schema :273 后 + handler :737 后 + dispatch :850）

- [ ] **Step 1: 写失败测试** —— 新建 `backend/tests/test_requirement_write.py`：

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.vibe_coding.tools import execute_requirement_write


async def test_requirement_write_sets_baseline():
    thread = SimpleNamespace(requirement_baseline=None)
    db = AsyncMock()
    out = await execute_requirement_write(
        {
            "roles": ["管理员 — 管理用户", "员工 — 提交报销"],
            "features": ["报销提交", "审批"],
            "flows": ["提交→审批→打款"],
            "acceptance": ["提交后主管能看到待审"],
        },
        thread,
        db,
    )
    assert thread.requirement_baseline["roles"] == ["管理员 — 管理用户", "员工 — 提交报销"]
    assert thread.requirement_baseline["features"] == ["报销提交", "审批"]
    # 缺省字段补空数组
    assert thread.requirement_baseline["external"] == []
    assert thread.requirement_baseline["ai_points"] == []
    db.commit.assert_awaited_once()
    assert "需求基线" in out


async def test_requirement_write_rejects_non_list():
    thread = SimpleNamespace(requirement_baseline=None)
    db = AsyncMock()
    out = await execute_requirement_write({"roles": "管理员"}, thread, db)
    assert "数组" in out  # _err 返回
    db.commit.assert_not_awaited()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_requirement_write.py -v`
Expected: FAIL（`ImportError: cannot import name 'execute_requirement_write'`）

- [ ] **Step 3: 写 handler** —— 在 `tools.py` 的 `execute_todo_write` 之后（:737 后）加：

```python
_REQ_FIELDS = ["roles", "features", "flows", "external", "ai_points", "acceptance"]


async def execute_requirement_write(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    cleaned: dict[str, list[str]] = {}
    for key in _REQ_FIELDS:
        val = args.get(key)
        if val is None:
            cleaned[key] = []
            continue
        if not isinstance(val, list):
            return _err(f"{key} 必须是字符串数组")
        cleaned[key] = [str(x).strip() for x in val if str(x).strip()]
    thread.requirement_baseline = cleaned
    await db.commit()
    counts = ", ".join(f"{k}:{len(cleaned[k])}" for k in _REQ_FIELDS if cleaned[k])
    return f"需求基线已更新（{counts or '空'}）"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_requirement_write.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 注册 schema** —— 在 `tools.py` 的 `TOOL_SCHEMAS` 列表里、`todo_write` schema（:273 那个 `},` 结束的 dict）之后加：

```python
    {
        "type": "function",
        "function": {
            "name": "requirement_write",
            "description": (
                "维护当前应用的「需求基线」——把用户需求结构化记录，实时显示在用户的「需求」tab。"
                "每次调用都会**完整覆盖**当前基线（不是增量）。"
                "澄清完关键点后调用一次；之后需求有变（用户改、范围调整）就再调更新。"
                "所有字段都是字符串数组，可空；简单应用 external/ai_points 可留空。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "roles":      {"type": "array", "items": {"type": "string"}, "description": "使用角色，如 '管理员 — 管理用户与权限'"},
                    "features":   {"type": "array", "items": {"type": "string"}, "description": "功能点列表"},
                    "flows":      {"type": "array", "items": {"type": "string"}, "description": "关键业务流程，如 '员工提交 → 主管审批 → 财务打款'"},
                    "external":   {"type": "array", "items": {"type": "string"}, "description": "外部交互/集成（第三方 API 等），无则空"},
                    "ai_points":  {"type": "array", "items": {"type": "string"}, "description": "需要 AI 能力的决策点，无则空"},
                    "acceptance": {"type": "array", "items": {"type": "string"}, "description": "验收标准"},
                },
                "required": ["roles", "features", "flows", "acceptance"],
            },
        },
    },
```

- [ ] **Step 6: 注册 dispatch** —— 在 `tools.py` 的 `TOOL_HANDLERS`（:850 `"todo_write"` 那条后）加：

```python
    "todo_write": execute_todo_write,
    "requirement_write": execute_requirement_write,
```

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_requirement_write.py backend/app/vibe_coding/tools.py
git commit -m "feat(ai-coding): requirement_write 工具 — 结构化需求基线 (覆盖式) + 单测"
```

---

### Task 3: 后端接线 — SSE 事件 + 序列化 + prompt

**Files:**
- Modify: `backend/app/vibe_coding/agent.py:476`
- Modify: `backend/app/routes/vibe_coding_chat.py:93`
- Modify: `backend/app/vibe_coding/prompts.py:23-24`

- [ ] **Step 1: agent loop 推 SSE** —— 在 `agent.py` 的 `todos_updated`（:475-476）之后加：

```python
            # todo_write 成功 → 推送最新 todos 给前端渲染
            if tool_name == "todo_write" and tc_db.status == "success":
                yield _sse("todos_updated", {"todos": thread.todos or []})

            # requirement_write 成功 → 推送最新需求基线给「需求」tab
            if tool_name == "requirement_write" and tc_db.status == "success":
                yield _sse("requirement_updated", {"requirement": thread.requirement_baseline or {}})
```

- [ ] **Step 2: getThread 序列化带上基线** —— 在 `vibe_coding_chat.py` 的 `_thread_to_dict`（:93 `"todos"` 行后）加：

```python
        "todos": t.todos or [],
        "requirement_baseline": t.requirement_baseline or {
            "roles": [], "features": [], "flows": [],
            "external": [], "ai_points": [], "acceptance": [],
        },
```

- [ ] **Step 3: prompt 加指令** —— 把 `prompts.py` 的 `### 第 2 步：拆 TODO + 开干`（:23）那段改成：

```
### 第 2 步：记录需求基线 + 拆 TODO
- **先调 `requirement_write`** 把需求结构化记录：角色 / 功能 / 流程 / 外部交互 / AI决策点 / 验收标准（都是字符串数组，简单应用 external/ai_points 可空）。这会实时显示在用户「需求」tab 作为共识基线；之后需求有变（用户改、范围调整）就立刻再调 requirement_write 更新（完整覆盖）。
- 用 todo_write 把任务拆成 3-8 条，**复杂任务必须拆**——脚手架、装依赖、写每个核心模块、跑 dev server、http_check 各 1 条
```

- [ ] **Step 4: 验证** —— 后端重启无异常；`curl -s localhost:8000/api/health` → ok。（端到端 SSE/基线产生在 Task 5 浏览器验。）

- [ ] **Step 5: Commit**

```bash
git add backend/app/vibe_coding/agent.py backend/app/routes/vibe_coding_chat.py backend/app/vibe_coding/prompts.py
git commit -m "feat(ai-coding): requirement_updated SSE + getThread 序列化 + prompt 指令"
```

---

### Task 4: 前端「需求」tab

**Files:**
- Modify: `frontend/src/api/vibeCodingChat.ts:15`
- Create: `frontend/src/components/ai-coding/RequirementTab.vue`
- Modify: `frontend/src/components/ai-coding/WorkspaceTabs.vue`

- [ ] **Step 1: 类型** —— 在 `vibeCodingChat.ts` 的 `VibeChatThread` 里 `todos` 行（:15）后加：

```ts
  todos: Array<{ id: string; content: string; status: 'pending' | 'in_progress' | 'completed' }>
  requirement_baseline?: {
    roles: string[]; features: string[]; flows: string[]
    external: string[]; ai_points: string[]; acceptance: string[]
  }
```

- [ ] **Step 2: 新建 `RequirementTab.vue`**

```vue
<template>
  <div class="rq">
    <div v-if="isEmpty" class="rq-empty">AI 还没产出需求基线 —— 去左边描述你想做的应用</div>
    <template v-else>
      <section v-for="s in sections" :key="s.key" v-show="(baseline[s.key] || []).length" class="rq-sec">
        <div class="rq-label">{{ s.label }}</div>
        <ul class="rq-list">
          <li v-for="(item, i) in baseline[s.key]" :key="i">{{ item }}</li>
        </ul>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { vibeCodingChatApi } from '@/api/vibeCodingChat'

const props = defineProps<{ workspaceId: string }>()
const EMPTY: Record<string, string[]> = { roles: [], features: [], flows: [], external: [], ai_points: [], acceptance: [] }
const baseline = ref<Record<string, string[]>>({ ...EMPTY })
const sections = [
  { key: 'roles', label: '角色' },
  { key: 'features', label: '功能' },
  { key: 'flows', label: '流程' },
  { key: 'external', label: '外部交互' },
  { key: 'ai_points', label: 'AI 决策点' },
  { key: 'acceptance', label: '验收标准' },
]
const isEmpty = computed(() => sections.every(s => !(baseline.value[s.key] || []).length))
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  if (!props.workspaceId) return
  try {
    const d = await vibeCodingChatApi.getThread(props.workspaceId)
    baseline.value = { ...EMPTY, ...((d.thread?.requirement_baseline as any) || {}) }
  } catch (_) { /* 静默：还没线程 */ }
}
onMounted(() => { refresh(); timer = setInterval(refresh, 3000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.rq { padding: 16px; display: flex; flex-direction: column; gap: 18px; }
.rq-empty { padding: 48px; text-align: center; color: var(--text-4); }
.rq-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-4); margin-bottom: 8px; }
.rq-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 5px; }
.rq-list li { font-size: 13px; color: var(--text-2); line-height: 1.5; }
</style>
```

- [ ] **Step 3: 接进 WorkspaceTabs** —— `WorkspaceTabs.vue` 顶部 `import RequirementTab from './RequirementTab.vue'`，把 `.wt-body` 里 requirement 的占位换成：

```html
    <div class="wt-body">
      <RequirementTab v-if="active === 'requirement'" :workspace-id="workspaceId" />
      <ProgressTab v-else-if="active === 'progress'" :workspace-id="workspaceId" />
      <RuntimePreviewTab v-else-if="active === 'preview'" :workspace-id="workspaceId" />
      <OutputTab v-else-if="active === 'output'" :workspace-id="workspaceId" />
      <div v-else class="wt-placeholder">「{{ activeLabel }}」建设中（后续切片接入）</div>
    </div>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/vibeCodingChat.ts frontend/src/components/ai-coding/RequirementTab.vue frontend/src/components/ai-coding/WorkspaceTabs.vue
git commit -m "feat(ai-coding): 需求 tab — 只读渲染 requirement_baseline 6 分区"
```

---

### Task 5: 端到端浏览器验证

- [ ] **Step 1: 验证**（后端 :8000 + 前端 5173 都在）
  1. `preview_start` frontend，导航到一个 ai-code 工作区（如新建一个，或 `/ai-coding/oc_xxx`）
  2. 左边对话发"做一个报销系统：员工提交、主管审批、财务打款，带统计看板"
  3. AI 澄清后调 `requirement_write` → 切「需求」tab → 应出现 **角色/功能/流程/验收** 的结构化条目（真数据）
  4. 对话里说"再加一个管理员角色" → 「需求」tab 几秒内多出该角色
  5. `preview_console_logs` 无我方报错；`preview_screenshot` 留证

- [ ] **Step 2: Commit（如有微调）**

```bash
git add -A && git commit -m "chore(ai-coding): 需求基线端到端验证通过"
```

---

## 自查（Self-Review）

**Spec 覆盖：**
- 活文档 / 非阻塞 → requirement_write 不打断 agent 流程 ✓
- 新增 agent 工具(照搬 todo_write) → Task 2 ✓
- 6 字段 string[] → schema + handler + 类型一致 ✓
- 只读 tab + 对话改 → RequirementTab 只读；改走对话触发 requirement_write ✓（Task 4 + prompt Task 3）
- 存 thread + SSE 实时渲染 → 模型(T1) + SSE(T3) + 序列化(T3) + 轮询(T4) ✓
- 铁律不碰低代码 → 全在 vibe_coding/* + ai-coding/* ✓

**类型一致：** `requirement_baseline` 的 6 个 key（roles/features/flows/external/ai_points/acceptance）在 handler `_REQ_FIELDS`、schema properties、序列化默认值、前端类型、RequirementTab sections **五处完全一致**。

**无占位：** 每步有完整代码 + 确切命令。CSS 变量用已确认的 --text-2/--text-4。

**偏离/风险：** RequirementTab 用 3s 轮询（同 ProgressTab 思路，简化版，未接 busy 判断）；后续可改监听 SSE requirement_updated。
