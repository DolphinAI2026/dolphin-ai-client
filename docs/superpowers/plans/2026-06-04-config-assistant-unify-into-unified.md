# 配置助手统一到 AI Builder unified 引擎 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ChatPage 右栏的「配置助手」从独立的 `_config_chat_event_stream` 引擎统一到 AI Builder 的 unified `run_agent`,锁定应用上下文,一套引擎覆盖配置 + codegen + 会话 + 产出物 + trace + 自学习 skill + 自动刷预览。

**Architecture:** 给 `ai_chat_sessions` 加 `app_id` 列实现常驻锁;`run_agent` 在有 app_id 时注入应用上下文(SPEC/skill/section)+ 工具调用后端填死 app_id 护栏;工具集并成 `builder∪coding∪config`;旧 `config_chat_*` 数据 boot-time 幂等迁到 AIChat 表;前端右栏抽出 `useAiChatSession` composable,嵌 `AgentConversation`,refresh-iframe 换检测源;最后删旧 config-chat 链路。

**Tech Stack:** FastAPI + SQLAlchemy async(无 Alembic,`create_all` + `database.py` 手写 ALTER)、OpenAI 兼容 LLM 网关(omnigate gpt-5.5)、Vue 3 + TS + Element Plus、SSE。

设计文档:`docs/superpowers/specs/2026-06-04-config-assistant-unify-into-unified-design.md`

---

## 执行约定(每个任务都按这套验证)

**工程门禁现状(预存,非本次引入)**:
- 前端 `npm run build`(vue-tsc)预存坏(ChatPage 一堆历史类型错)。**只用 `npm run build:nocheck` 当编译门禁**。
- 后端全量测试有 6 个预存失败(本地 SQLite)。**只跑本任务新增/相关测试**,别拿全量绿当门禁。
- 改后端必重启 preview backend;`.venv` 是 py3.13;本地 DB 是 SQLite,prod 是 MySQL。

**后端测试基建**(recorder/run_agent/migration 这类要查 recorder 自开会话写的行的测试):用 `StaticPool` 共享内存库 + monkeypatch `app.database.AsyncSessionLocal`,否则查不到。参考现有 `backend/tests/test_*observability*.py` / recorder 测试写法。

**命令速查**:
- 后端单测:`cd backend && .venv/bin/pytest tests/<file>::<test> -v`
- 前端编译:`cd frontend && npm run build:nocheck`
- 前端 live:preview_* 工具(见仓库 preview workflow)

---

## File Structure

**后端 — 修改**:
- `backend/app/models/ai_chat.py` — `AIChatSession` 加 `app_id` 字段
- `backend/app/models/config_chat.py` — `ConfigChatSession` 加 `migrated_session_id` 字段
- `backend/app/database.py` — ALTER 列表加新列 + 新增 `_migrate_config_chat_to_ai_chat` 并在 `init_db` 调
- `backend/app/ai_chat/tools.py` — `get_all_tool_schemas` 工具 union;`execute_tool` 加 app_id 注入护栏
- `backend/app/ai_chat/agent.py` — `MAX_TURNS` 20→25;`_build_initial_messages` 加 app-context 注入;`_run_agent_inner` 给 recorder 传 app_id
- `backend/app/ai_chat/app_context.py` — **新建**,app-context prompt 组装(SPEC/skill/section 加载),从 config stream 移植
- `backend/app/routes/ai_chat.py` — `CreateSessionRequest` + `create_session` 收 app_id/section;`SendMessageRequest` 收 section;`_session_to_dict` 带 app_id;list/detail 支持 app_id 过滤

**后端 — 删除(Phase D,cutover 后)**:
- `backend/app/routes/applications/__init__.py` — `_config_chat_event_stream`、`/config-chat`、`/config-chat-stream`、`ConfigChatReq`、`_CONFIG_CHAT_*`、`_build_section_hint`

**前端 — 新建/修改**:
- `frontend/src/composables/useAiChatSession.ts` — **新建**,从 `AIChatPage.vue` 抽出的流式编排
- `frontend/src/views/AIChatPage.vue` — 改用 `useAiChatSession`
- `frontend/src/components/v2/ConfigAssistantPanel.vue` — 改造成嵌 `AgentConversation` + `useAiChatSession`(锁 app_id)
- `frontend/src/api/aiChat.ts` — `createSession` 支持传 app_id/section
- `frontend/src/views/ChatPage.vue` — 换子组件(若改 props)

**前端 — 删除(Phase D)**:
- `frontend/src/components/v2/config-assistant/`(子组件 + `useConfigChat.ts`)、`frontend/src/api/configChat.ts`

---

## Phase A — 后端地基

### Task A1: `ai_chat_sessions.app_id` 列 + 迁移标记列

**Files:**
- Modify: `backend/app/models/ai_chat.py:42`(`AIChatSession` 内)
- Modify: `backend/app/models/config_chat.py:45`(`ConfigChatSession` 内)
- Modify: `backend/app/database.py:142`(ALTER 列表末尾)
- Test: `backend/tests/test_ai_chat_app_id_column.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_ai_chat_app_id_column.py
import pytest
from sqlalchemy import inspect as sa_inspect
from app.models.ai_chat import AIChatSession
from app.models.config_chat import ConfigChatSession


def test_aichatsession_has_app_id_column():
    cols = {c.name for c in sa_inspect(AIChatSession).columns}
    assert "app_id" in cols


def test_configchatsession_has_migrated_marker():
    cols = {c.name for c in sa_inspect(ConfigChatSession).columns}
    assert "migrated_session_id" in cols
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_ai_chat_app_id_column.py -v`
Expected: FAIL（`app_id` not in cols）

- [ ] **Step 3: 加 model 字段**

`backend/app/models/ai_chat.py` 在 `AIChatSession` 的 `selected_llm_config_id` 之后加:
```python
    # 应用上下文常驻锁：非空 = 锁定该内部 applications.id（app 配置/二次开发态）；
    # 空 = 自由态（/ai-chat 0-1 创建/通用）。不加 FK，沿用 ai_chat 解耦风格。
    app_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
```

`backend/app/models/config_chat.py` 在 `ConfigChatSession` 的 `updated_at` 之后加:
```python
    # 一次性迁到 ai_chat_sessions 后回写新 session id（幂等标记；非空=已迁）
    migrated_session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: 加 boot-time ALTER（兼容已存在的库）**

`backend/app/database.py` 在 ALTER 列表（`:142` 那批 `app_type`/`source_workspace_id` 之后）追加:
```python
            # 配置助手统一到 unified：会话级应用上下文常驻锁
            "ALTER TABLE ai_chat_sessions ADD COLUMN app_id INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_app_id ON ai_chat_sessions(app_id)",
            # config_chat → ai_chat 一次性迁移幂等标记
            "ALTER TABLE config_chat_sessions ADD COLUMN migrated_session_id INTEGER",
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_ai_chat_app_id_column.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/ai_chat.py backend/app/models/config_chat.py backend/app/database.py backend/tests/test_ai_chat_app_id_column.py
git commit -m "feat(ai_chat): add session.app_id lock column + config_chat migration marker"
```

---

### Task A2: 工具集并成 builder∪coding∪config + MAX_TURNS 25

**Files:**
- Modify: `backend/app/ai_chat/tools.py:1404`
- Modify: `backend/app/ai_chat/agent.py:582`
- Test: `backend/tests/test_tool_union_config.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_tool_union_config.py
from app.tool_registry import tools_for_agent


def test_config_only_tools_in_union():
    # save_config_skill 是 config 专属（不在 builder/coding），union 后必须在
    builder = set(tools_for_agent("builder"))
    coding = set(tools_for_agent("coding"))
    config = set(tools_for_agent("config"))
    union = builder | coding | config
    assert "save_config_skill" in config
    assert "save_config_skill" in union
    # 至少有一个 config 专属工具不在 builder∪coding（证明 union 确实扩了集合）
    assert config - (builder | coding), "config 应有专属工具，否则 union 无意义"
```

- [ ] **Step 2: 跑测试确认通过/失败**

Run: `cd backend && .venv/bin/pytest tests/test_tool_union_config.py -v`
Expected: PASS（这测的是 registry 既有事实，确认 config 有专属工具）。若 FAIL 说明 registry 里 config 工具被 builder/coding 全覆盖,需回看 spec §2 假设。

- [ ] **Step 3: 改 union（一行）**

`backend/app/ai_chat/tools.py:1404`:
```python
        allow = (
            set(tools_for_agent("builder"))
            | set(tools_for_agent("coding"))
            | set(tools_for_agent("config"))
        )
```
同时更新该函数 docstring 里「builder ∪ coding (~71)」→「builder ∪ coding ∪ config (~85)」。

- [ ] **Step 4: MAX_TURNS 20→25**

`backend/app/ai_chat/agent.py:582`:
```python
MAX_TURNS = 25  # 工具循环最大轮数（统一 config 的 25：app 配置/codegen 多步任务需要）
```

- [ ] **Step 5: 写并跑 union 生效测试**

加到同文件:
```python
import pytest

@pytest.mark.asyncio
async def test_get_all_tool_schemas_includes_config(monkeypatch):
    from app.ai_chat import tools as t
    # 桩掉 MCP bridge，让它返回 registry 里所有 config 工具的假 schema
    config_tools = list(set(t.__import__("app.tool_registry", fromlist=["tools_for_agent"]).tools_for_agent("config")))
    fake = [{"type": "function", "function": {"name": n, "parameters": {}}} for n in config_tools]
    async def _fake_schemas():
        return fake
    monkeypatch.setattr("app.ai_chat.mcp_bridge.get_tool_schemas_openai", _fake_schemas)
    schemas = await t.get_all_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "save_config_skill" in names
```

Run: `cd backend && .venv/bin/pytest tests/test_tool_union_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai_chat/tools.py backend/app/ai_chat/agent.py backend/tests/test_tool_union_config.py
git commit -m "feat(ai_chat): union config tools into agent toolset + MAX_TURNS 25"
```

---

### Task A3: `create_session` / send 收 app_id + section,序列化带 app_id

**Files:**
- Modify: `backend/app/routes/ai_chat.py`（`CreateSessionRequest`、`SendMessageRequest`、`create_session`、`_session_to_dict`、`list_sessions`）
- Test: `backend/tests/test_session_app_lock.py`

- [ ] **Step 1: 先读取请求模型与序列化定义**

读 `backend/app/routes/ai_chat.py` 里 `CreateSessionRequest` / `SendMessageRequest` / `_session_to_dict` 的现状（位置约在文件上半部与 `_*_to_dict` 区），确认字段名后再改。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_session_app_lock.py
import pytest
from app.routes.ai_chat import CreateSessionRequest, _session_to_dict
from app.models.ai_chat import AIChatSession


def test_create_session_request_accepts_app_id_and_section():
    req = CreateSessionRequest(app_id=42, section="data")
    assert req.app_id == 42
    assert req.section == "data"


def test_session_to_dict_exposes_app_id():
    s = AIChatSession(id=1, tenant_id=1, user_id=1, title="t", app_id=42)
    d = _session_to_dict(s)
    assert d["app_id"] == 42
```

- [ ] **Step 3: 跑确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_session_app_lock.py -v`
Expected: FAIL（`CreateSessionRequest` 无 app_id / dict 无 app_id）

- [ ] **Step 4: 实现**

- `CreateSessionRequest` 加 `app_id: Optional[int] = None` 与 `section: Optional[str] = None`。
- `SendMessageRequest` 加 `section: Optional[str] = None`（每条消息可带当前 section 软提示）。
- `create_session` 在构造 `AIChatSession(...)` 时加 `app_id=body.app_id`。
- `_session_to_dict` 返回里加 `"app_id": getattr(s, "app_id", None)`。
- `list_sessions` 加可选 query `app_id: Optional[int] = None`,非空时 `.where(AIChatSession.app_id == app_id)`(右栏 session 抽屉按 app 过滤;为空时保持现有「全部」行为给 /ai-chat 全局侧栏)。

- [ ] **Step 5: 跑确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_session_app_lock.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/ai_chat.py backend/tests/test_session_app_lock.py
git commit -m "feat(ai_chat): create_session locks app_id + section, list filterable by app_id"
```

---

### Task A4: 工具调用 app_id 注入护栏

**Files:**
- Modify: `backend/app/ai_chat/tools.py:1479`（`execute_tool` 内,`_mcp_call` 之前）
- Test: `backend/tests/test_app_id_injection.py`

- [ ] **Step 1: 先确认 apaas 工具的 app-id 参数语义**

读本机 MCP server 工具定义(`backend/app/mcp_server.py` + 相关 tool 模块),挑 2–3 个 apaas 配置工具(如 `list_apaas_app_models` / `update_apaas_model_field` / `add_dict_option`)确认:①参数名是 `app_id` 还是 `appId`/`application_id`;②期望的是**内部 `applications.id`** 还是 apaas 平台 id。记下结论(注入要填对值)。`session.app_id` 是内部 id;若工具要平台 id,需在注入前用 application 记录解析。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_app_id_injection.py
import pytest
from app.ai_chat import tools as t
from app.models.ai_chat import AIChatSession


@pytest.mark.asyncio
async def test_locked_app_id_overrides_llm_value(monkeypatch):
    captured = {}
    async def _fake_mcp_call(name, args, tenant_id=0, user_id=0):
        captured["args"] = args
        return "ok"
    monkeypatch.setattr("app.ai_chat.mcp_bridge.call_tool", _fake_mcp_call)
    monkeypatch.setattr("app.ai_chat.mcp_bridge.list_mcp_tool_names_cached", lambda: ["list_apaas_app_models"])
    # 该工具声明了 app_id 参数（schema-gated 注入用）
    monkeypatch.setattr(t, "_tool_declares_param", lambda name, p: p == "app_id")

    s = AIChatSession(id=1, tenant_id=7, user_id=3, app_id=99)
    # LLM 故意给了别的 app_id，必须被锁定值覆盖
    await t.execute_tool("list_apaas_app_models", {"app_id": 12345}, s, db=None)
    assert captured["args"]["app_id"] == 99


@pytest.mark.asyncio
async def test_free_session_no_injection(monkeypatch):
    captured = {}
    async def _fake_mcp_call(name, args, tenant_id=0, user_id=0):
        captured["args"] = dict(args)
        return "ok"
    monkeypatch.setattr("app.ai_chat.mcp_bridge.call_tool", _fake_mcp_call)
    monkeypatch.setattr("app.ai_chat.mcp_bridge.list_mcp_tool_names_cached", lambda: ["list_apaas_app_models"])
    monkeypatch.setattr(t, "_tool_declares_param", lambda name, p: p == "app_id")
    s = AIChatSession(id=1, tenant_id=7, user_id=3, app_id=None)  # 自由态
    await t.execute_tool("list_apaas_app_models", {"app_id": 12345}, s, db=None)
    assert captured["args"]["app_id"] == 12345  # 不锁，不动
```

- [ ] **Step 3: 跑确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_app_id_injection.py -v`
Expected: FAIL（`_tool_declares_param` 不存在 / 没注入逻辑）

- [ ] **Step 4: 实现 schema-gated 注入**

在 `tools.py` 加 helper（schema 来自 `get_all_tool_schemas` 的缓存;若无缓存则保守地按参数名直接判断）:
```python
# 锁定 app 时，强制把 session.app_id 填进声明了 app-id 参数的工具，覆盖 LLM 给的值。
# 护栏：0-1/跨应用工具即使在工具集里，也跨不出锁定应用。
_APP_ID_PARAM_ALIASES = ("app_id", "appId", "application_id")

def _tool_declares_param(tool_name: str, param: str) -> bool:
    """该工具的 schema 是否声明了 param（用已加载的 schema 缓存判断）。"""
    for s in (globals().get("_LAST_TOOL_SCHEMAS") or []):
        fn = s.get("function", {})
        if fn.get("name") == tool_name:
            props = (fn.get("parameters") or {}).get("properties") or {}
            return param in props
    return False

def _inject_locked_app_id(tool_name: str, args: dict, session) -> dict:
    app_id = getattr(session, "app_id", None)
    if not app_id:
        return args
    for alias in _APP_ID_PARAM_ALIASES:
        if _tool_declares_param(tool_name, alias):
            return {**args, alias: app_id}
    return args
```
在 `get_all_tool_schemas` 返回前把结果缓存到 `globals()["_LAST_TOOL_SCHEMAS"]`（供 `_tool_declares_param` 用）。
在 `execute_tool` 的 MCP 分支、artifact_id 自愈之后、`_mcp_call` 之前插入:
```python
        args = _inject_locked_app_id(tool_name, args, session)
```
**注意**:若 Step 1 结论是「工具要 apaas 平台 id」,把 `app_id` 替换为「用 `db` + `session.app_id` 解析出的平台 id」。

- [ ] **Step 5: 跑确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_app_id_injection.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai_chat/tools.py backend/tests/test_app_id_injection.py
git commit -m "feat(ai_chat): inject locked app_id into apaas tools (cross-app guardrail)"
```

---

### Task A5: app-context prompt 注入（SPEC + skill + section）

**Files:**
- Create: `backend/app/ai_chat/app_context.py`
- Modify: `backend/app/ai_chat/agent.py:500`（`_build_initial_messages` system prompt 之后）
- Test: `backend/tests/test_app_context_prompt.py`

- [ ] **Step 1: 先移植源参照**

读 config stream 的三段可移植逻辑作为蓝本(别照抄路由耦合,抽成纯函数):
- SPEC 加载:`backend/app/routes/applications/__init__.py:2951`(`canonical_spec → config_preview → requirement_doc`,各 ≤12000 字)
- skill 加载:`:3025`–`3048` + 注入 `:3177`(tenant+app skills)
- section hint:`_CONFIG_CHAT_SECTION_HINTS`(`:2477`)+ `_build_section_hint`(`:2512`)

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_app_context_prompt.py
import pytest
from app.ai_chat.app_context import build_app_context_block


@pytest.mark.asyncio
async def test_no_app_id_returns_empty(monkeypatch):
    block = await build_app_context_block(db=None, app_id=None, section=None)
    assert block == ""


@pytest.mark.asyncio
async def test_app_context_includes_app_and_section(monkeypatch):
    # 桩掉内部加载器，只验证组装
    import app.ai_chat.app_context as ac
    async def _fake_app(db, app_id):
        return {"id": app_id, "name": "图书借阅", "platform_env_id": 5}
    async def _fake_spec(db, app_id):
        return "SPEC 摘要内容"
    async def _fake_skills(db, app):
        return ["技能: 改字段必填"]
    monkeypatch.setattr(ac, "_load_application", _fake_app)
    monkeypatch.setattr(ac, "_load_spec_text", _fake_spec)
    monkeypatch.setattr(ac, "_load_skills", _fake_skills)
    block = await build_app_context_block(db=None, app_id=42, section="data")
    assert "图书借阅" in block
    assert "SPEC 摘要内容" in block
    assert "技能: 改字段必填" in block
    assert "data" in block or "数据" in block  # section 软提示
    assert "AI Coding 模块" not in block  # 过时引导不得出现
```

- [ ] **Step 3: 跑确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_app_context_prompt.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 `app_context.py`**

```python
# backend/app/ai_chat/app_context.py
"""应用上下文 prompt 组装 — session 锁定 app_id 时给 run_agent 注入。

从 config stream（applications/__init__.py）移植 SPEC / skill / section 三段加载，
抽成不依赖路由的纯函数。无 app_id 时返回空串（自由态零影响）。
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

_SECTION_HINTS = {
    "data": "用户当前在「数据建模」设计器，优先用 list/update 模型字段、字典相关工具。",
    "ui": "用户当前在「页面/表单」设计器，优先用菜单/表单/列表相关工具。",
    "logic": "用户当前在「流程/逻辑」设计器，优先用流程/业务事件相关工具。",
    "permission": "用户当前在「权限」设计器，优先用角色/访问控制相关工具。",
    "extension": "用户当前在「扩展/二次开发」区，可用自开发包上传/关联 + codegen 工具。",
}

async def _load_application(db: AsyncSession, app_id: int) -> Optional[dict]:
    from app.models.application import Application  # 按实际模型路径调整
    app = await db.get(Application, app_id)
    if not app:
        return None
    return {"id": app.id, "name": getattr(app, "name", ""),
            "platform_env_id": getattr(app, "platform_env_id", None)}

async def _load_spec_text(db: AsyncSession, app_id: int) -> str:
    # 移植 applications/__init__.py:2951 的 canonical_spec → config_preview → requirement_doc
    # 各 ≤12000 字。找不到返回 ""。
    ...

async def _load_skills(db: AsyncSession, app: dict) -> list[str]:
    # 移植 applications/__init__.py:3025 的 tenant+app skill 加载（config_assistant_skills）
    ...

async def build_app_context_block(
    db: AsyncSession, app_id: Optional[int], section: Optional[str]
) -> str:
    if not app_id or db is None:
        return ""
    app = await _load_application(db, app_id)
    if not app:
        return ""
    parts = [
        "\n\n## 当前应用上下文（已锁定）",
        f"- 应用：{app['name']}（内部 id={app['id']}，env={app.get('platform_env_id')}）",
        "- 你正在这个应用内工作。配置改动立即生效；二次开发/codegen 你现在就能干（工具已具备）。",
        "- 不要新建其它应用、不要跨应用操作；工具调用的 app id 由后端锁定。",
    ]
    if section and section in _SECTION_HINTS:
        parts.append(f"- {_SECTION_HINTS[section]}")
    spec = await _load_spec_text(db, app_id)
    if spec:
        parts.append(f"\n### 应用 SPEC 摘要\n{spec}")
    skills = await _load_skills(db, app)
    if skills:
        parts.append("\n### 本应用已学习的操作技能（可复用）\n" + "\n".join(f"- {s}" for s in skills))
    return "\n".join(parts)
```
（`_load_spec_text` / `_load_skills` 的 `...` 处按 Step 1 移植的真实加载逻辑填实;import 路径按实际模型核对。）

- [ ] **Step 5: 接入 `_build_initial_messages`**

`backend/app/ai_chat/agent.py` 在 `_build_initial_messages` 的 `system_prompt = _select_system_prompt(...)` 之后:
```python
    from app.ai_chat.app_context import build_app_context_block
    app_id = getattr(session, "app_id", None)
    section = getattr(session, "_pending_section", None)  # send 时挂到 session 的临时属性，见下
    if app_id:
        system_prompt = system_prompt + await build_app_context_block(db, app_id, section)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
```
（section 传递:`routes/ai_chat.py` 的 send 处理把 `body.section` 临时挂到 `session._pending_section` 再调 `run_agent`;或把 section 作为 `run_agent`/`_build_initial_messages` 显式参数透传 —— 执行时择一,推荐显式参数,更干净。）

- [ ] **Step 6: 跑确认通过 + 编译**

Run: `cd backend && .venv/bin/pytest tests/test_app_context_prompt.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai_chat/app_context.py backend/app/ai_chat/agent.py backend/tests/test_app_context_prompt.py
git commit -m "feat(ai_chat): inject app-context (SPEC/skill/section) prompt when session locks app_id"
```

---

### Task A6: recorder 填 app_id（观测红利）

**Files:**
- Modify: `backend/app/ai_chat/agent.py`（`_run_agent_inner` 里 `recorder.start_run(...)` 调用处，约 `:638`）
- Test: 并入 A5/现有 observability 测试，或加一条断言

- [ ] **Step 1: 改 start_run 传 app_id**

找到 `_run_agent_inner` 里 `recorder.start_run(agent_type="ai_builder", ...)`,加 `app_id=getattr(session, "app_id", None)`。`agent_run` 表已有 `app_id` 列（spec headroom）,此前一直空。

- [ ] **Step 2: 验证**

跑现有 observability 测试确认不回归:
Run: `cd backend && .venv/bin/pytest tests/ -k observability -v`
Expected: 与改前一致（无新失败）

- [ ] **Step 3: Commit**

```bash
git add backend/app/ai_chat/agent.py
git commit -m "feat(observability): fill agent_run.app_id from locked session"
```

---

## Phase B — 数据迁移（依赖 A1）

### Task B1: config_chat → ai_chat boot-time 幂等迁移

**Files:**
- Modify: `backend/app/database.py`（新增 `_migrate_config_chat_to_ai_chat`,在 `init_db` 调）
- Test: `backend/tests/test_migrate_config_chat.py`

- [ ] **Step 1: 写失败测试（StaticPool 共享内存库）**

```python
# backend/tests/test_migrate_config_chat.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base, _migrate_config_chat_to_ai_chat
import app.models.ai_chat  # noqa
import app.models.config_chat  # noqa


@pytest.mark.asyncio
async def test_migration_copies_and_is_idempotent():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 种一条旧 config 会话 + 2 条消息（assistant 带 tool_trace）
        await conn.execute(text(
            "INSERT INTO config_chat_sessions(id,app_id,tenant_id,user_id,title,created_at,updated_at) "
            "VALUES (1,42,7,3,'调字段','2026-06-01','2026-06-01')"))
        await conn.execute(text(
            "INSERT INTO config_chat_messages(id,session_id,role,content,created_at) "
            "VALUES (1,1,'user','把电话改必填','2026-06-01')"))
        await conn.execute(text(
            "INSERT INTO config_chat_messages(id,session_id,role,content,tool_trace_json,created_at) "
            "VALUES (2,1,'assistant','已改',"
            "'[{\"tool_name\":\"update_apaas_model_field\",\"args\":{\"app_id\":42},\"ok\":true,\"summary\":\"ok\",\"duration_ms\":120}]',"
            "'2026-06-01')"))
        # 第一次迁移
        await _migrate_config_chat_to_ai_chat(conn)
        n1 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_sessions"))).scalar()
        m1 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_messages"))).scalar()
        t1 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_tool_calls"))).scalar()
        marker = (await conn.execute(text("SELECT migrated_session_id FROM config_chat_sessions WHERE id=1"))).scalar()
        # 第二次迁移（幂等：不应重复）
        await _migrate_config_chat_to_ai_chat(conn)
        n2 = (await conn.execute(text("SELECT COUNT(*) FROM ai_chat_sessions"))).scalar()

    assert n1 == 1 and m1 == 2 and t1 == 1
    assert marker is not None
    new_app_id = (await _one(engine, "SELECT app_id FROM ai_chat_sessions LIMIT 1"))
    assert new_app_id == 42
    assert n2 == 1  # 幂等，没翻倍


async def _one(engine, sql):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql))).scalar()
```

- [ ] **Step 2: 跑确认失败**

Run: `cd backend && .venv/bin/pytest tests/test_migrate_config_chat.py -v`
Expected: FAIL（`_migrate_config_chat_to_ai_chat` 不存在）

- [ ] **Step 3: 实现迁移函数**

`backend/app/database.py` 新增（用低层 SQL 走传入的 conn,避免 ORM session 复杂度）:
```python
async def _migrate_config_chat_to_ai_chat(conn) -> None:
    """一次性幂等：config_chat_* → ai_chat_*。

    - 选未迁（migrated_session_id IS NULL）的 config 会话，逐条复制到 ai_chat_*
    - tool_trace_json 尽量还原成 ai_chat_tool_calls 行（provider_call_id 留空）
    - 回写 migrated_session_id（幂等标记），旧表保留作 archive
    - 并发护栏：MySQL GET_LOCK 抢到才跑；SQLite 无此函数 → try/except 直接跑
    """
    import json, logging
    log = logging.getLogger(__name__)
    # 并发锁（多 pod）：失败/不支持都直接放行（SQLite dev）
    try:
        got = (await conn.execute(text("SELECT GET_LOCK('migrate_config_chat', 0)"))).scalar()
        if got == 0:
            return  # 别的 pod 在迁
    except Exception:
        pass  # SQLite 无 GET_LOCK
    try:
        rows = (await conn.execute(text(
            "SELECT id, app_id, tenant_id, user_id, title, created_at, updated_at "
            "FROM config_chat_sessions WHERE migrated_session_id IS NULL"
        ))).fetchall()
        for r in rows:
            old_sid, app_id, tenant_id, user_id, title, created_at, updated_at = r
            res = await conn.execute(text(
                "INSERT INTO ai_chat_sessions(tenant_id,user_id,title,status,mode,app_id,created_at,updated_at) "
                "VALUES (:t,:u,:title,'active','chat',:app,:c,:up)"
            ), {"t": tenant_id, "u": user_id, "title": title or "新会话",
                "app": app_id, "c": created_at, "up": updated_at})
            new_sid = res.lastrowid
            msgs = (await conn.execute(text(
                "SELECT id, role, content, tool_trace_json, change_plan_json, actions_summary_json, created_at "
                "FROM config_chat_messages WHERE session_id=:s ORDER BY id ASC"
            ), {"s": old_sid})).fetchall()
            for mid, role, content, trace, plan, summary, mcreated in msgs:
                extra = {}
                if plan: extra["change_plan"] = _maybe_json(plan)
                if summary: extra["actions_summary"] = _maybe_json(summary)
                mres = await conn.execute(text(
                    "INSERT INTO ai_chat_messages(session_id,role,content,extra_meta,created_at) "
                    "VALUES (:s,:r,:c,:e,:ts)"
                ), {"s": new_sid, "r": role, "c": content or "",
                    "e": json.dumps(extra, ensure_ascii=False) if extra else None, "ts": mcreated})
                new_mid = mres.lastrowid
                for tc in (_maybe_json(trace) or []):
                    await conn.execute(text(
                        "INSERT INTO ai_chat_tool_calls(session_id,message_id,tool_name,args_json,result_text,status,duration_ms,created_at) "
                        "VALUES (:s,:m,:name,:args,:res,:st,:dur,:ts)"
                    ), {"s": new_sid, "m": new_mid, "name": tc.get("tool_name", "unknown"),
                        "args": json.dumps(tc.get("args"), ensure_ascii=False) if tc.get("args") is not None else None,
                        "res": tc.get("summary") or "", "st": "success" if tc.get("ok") else "error",
                        "dur": tc.get("duration_ms"), "ts": mcreated})
            await conn.execute(text(
                "UPDATE config_chat_sessions SET migrated_session_id=:n WHERE id=:o"
            ), {"n": new_sid, "o": old_sid})
        if rows:
            log.info("[migrate] config_chat → ai_chat 迁移 %d 会话", len(rows))
    finally:
        try:
            await conn.execute(text("SELECT RELEASE_LOCK('migrate_config_chat')"))
        except Exception:
            pass


def _maybe_json(v):
    import json
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return None
```
说明:JSON 列在 MySQL 返回 dict/list、在 SQLite 返回 str,故用 `_maybe_json` 兼容。`lastrowid` 在 SQLite/MySQL 的 async driver 上可用;若某 driver 不返回,改用 `SELECT last_insert_rowid()`/`LAST_INSERT_ID()`。

- [ ] **Step 4: 在 init_db 调用**

`backend/app/database.py` 的 `init_db`,在所有 ALTER/索引补丁之后(约 `:186` 之后)加:
```python
        # 配置助手统一：一次性把旧 config_chat 会话迁到 ai_chat（幂等，可回滚——旧表保留）
        try:
            await _migrate_config_chat_to_ai_chat(conn)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("config_chat 迁移跳过（非致命）：%s", e)
```

- [ ] **Step 5: 跑确认通过**

Run: `cd backend && .venv/bin/pytest tests/test_migrate_config_chat.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/database.py backend/tests/test_migrate_config_chat.py
git commit -m "feat(db): one-time idempotent config_chat -> ai_chat migration (boot-time, GET_LOCK guarded)"
```

---

## Phase C — 前端右栏改造

### Task C1: 抽 `useAiChatSession` composable

**Files:**
- Create: `frontend/src/composables/useAiChatSession.ts`
- Modify: `frontend/src/views/AIChatPage.vue`（改用 composable）
- Modify: `frontend/src/api/aiChat.ts`（`createSession` 透传 app_id/section）

- [ ] **Step 1: 读现状,定 composable 接口**

读 `AIChatPage.vue` 里发消息/消费 SSE 的逻辑(`aiChatApi` 用法、reactive messages/typing/queue/abort 状态)。圈定要抽出的:`messages`、`typing`、`typingSeconds`、`sending`、`queue`、`send()`、`stop()`、`loadSession()`、`createSession()`。composable 接受 `{ appId?: Ref<number|null>, section?: Ref<string|null> }`,内部建会话时把 app_id/section 传给 `aiChatApi.createSession`。

- [ ] **Step 2: 实现 `useAiChatSession.ts`**

把 Step 1 圈定的逻辑搬进 composable,导出上述 state + 方法。transport 仍调 `aiChatApi`。新增:建会话时透传 `appId?.value` / `section?.value`。

- [ ] **Step 3: `api/aiChat.ts` createSession 透传**

`aiChatApi.createSession` 的入参加可选 `app_id` / `section`,POST body 带上。

- [ ] **Step 4: AIChatPage 改用 composable**

`AIChatPage.vue` 删掉内联的那段流式逻辑,改 `const { messages, typing, send, stop, ... } = useAiChatSession({})`(自由态,不传 appId)。保持模板绑定不变。

- [ ] **Step 5: 编译 + live 回归 /ai-chat**

Run: `cd frontend && npm run build:nocheck`
Expected: 通过(无新错)
然后 preview:开 /ai-chat 发一条消息,确认流式/工具卡/停止/排队都和改前一致(纯重构,行为不变)。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/composables/useAiChatSession.ts frontend/src/views/AIChatPage.vue frontend/src/api/aiChat.ts
git commit -m "refactor(ai-chat): extract useAiChatSession composable from AIChatPage"
```

---

### Task C2: 右栏面板嵌 AgentConversation（锁 app_id）

**Files:**
- Modify: `frontend/src/components/v2/ConfigAssistantPanel.vue`（改造成 unified 面板）
- Modify: `frontend/src/views/ChatPage.vue`（如 props 变化）

- [ ] **Step 1: 读 ChatPage 怎么用 ConfigAssistantPanel**

读 `ChatPage.vue` 对 `ConfigAssistantPanel` 的使用(`:app-id`、`:current-section`、`@refresh-iframe` 等 props/events,约 `:387`)。确认 app_id/section 来源。

- [ ] **Step 2: 改造面板**

`ConfigAssistantPanel.vue` 内部:
- 保留 `usePanelResize`,把 maxWidth 880 → 1200。
- 用 `useAiChatSession({ appId: toRef(props,'appId'), section: toRef(props,'currentSection') })`。
- 模板主体换成 `<AgentConversation :messages="messages" :typing="typing" :typing-seconds="typingSeconds" tool-grouping @open-trace="..." @open-artifact="..." @answer-ask="..." />`。
- 复用 unified 输入器 + 模型选择;session 抽屉调 `aiChatApi.listSessions({ app_id: props.appId })` 列本 app 会话;接 trace 抽屉(两入口)。
- 保留对外 `(e:'refresh-iframe')` emit(C3 用)。

- [ ] **Step 3: ChatPage 接线**

若 props/events 名变了,同步 `ChatPage.vue` 调用处;`@refresh-iframe="refreshPlatformAndSidebar"` 保持。

- [ ] **Step 4: 编译 + live**

Run: `cd frontend && npm run build:nocheck`
Expected: 通过
preview:开 `/chat?app_id=<真实app>`,右栏发一条配置消息,确认走 unified(有 trace 入口、工具卡是 AgentConversation 样式)、会话能存能切、拖宽到 ~1200。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/v2/ConfigAssistantPanel.vue frontend/src/views/ChatPage.vue
git commit -m "feat(chat): right panel hosts unified AgentConversation locked to app_id"
```

---

### Task C3: refresh-iframe 换检测源

**Files:**
- Modify: `frontend/src/components/v2/ConfigAssistantPanel.vue`（或其消息子层）

- [ ] **Step 1: 实现 modify 检测 → emit**

在面板里 watch `useAiChatSession` 的 `messages`(AgentConversation 形状,工具调用在消息的 tool_calls 数组),复刻现有规则:assistant 消息 + 非流式 + 含成功的 modify 工具(正则 `^(update_|create_|add_|delete_|disable_|set_)` + 成功状态)+ 未刷过(`Set<id>` 去重)→ `setTimeout(()=>emit('refresh-iframe'),200)`。参照 `ConfigAssistantMessages.vue:33-47` 的原逻辑,只换数据形状。

- [ ] **Step 2: 编译 + live 验证自动刷**

Run: `cd frontend && npm run build:nocheck`
Expected: 通过
preview:右栏让 agent 改一个字段(必填)→ 成功后 200ms 内预览/设计器面板自动 remount(`designerRefreshKey++` 生效)。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/v2/ConfigAssistantPanel.vue
git commit -m "feat(chat): wire refresh-iframe off AgentConversation tool calls"
```

---

## Phase C+ — Live 端到端验证(删码前的硬门)

### Task CHECK: 真 gpt-5.5 端到端

- [ ] 用产品租户(57,有模型 + 通用 B2B CRM)登录,开 `/chat?app_id=<真实app>`。
- [ ] 右栏发「把某模型的电话字段改成必填」→ 观察:工具调用走 unified、app_id 被锁(LLM 即使给别的 id 也落到锁定 app)、改完预览自动刷。
- [ ] 会话脚注「查看本次 trace」可点开,`agent_run` 有记录、`app_id` 填上了、token 采到。
- [ ] 让 agent 存一个 skill(`save_config_skill`),新开会话能复用。
- [ ] 二次开发:让 agent `write_artifact` 写点代码,确认 codegen 工具在锁定 app 下可用。
- [ ] 旧会话:迁移后在右栏 session 抽屉能看到历史 config 会话,能打开看(续聊上下文可能略糙,符合预期)。
- [ ] 全过且无回归 → 进 Phase D。**任一不过先修,别删旧码。**

---

## Phase D — Cutover 删旧链路（CHECK 通过后才做）

### Task D1: 删后端 config-chat 链路

**Files:**
- Modify: `backend/app/routes/applications/__init__.py`

- [ ] 删 `_config_chat_event_stream`、`POST /applications/{app_id}/config-chat`(`:2574`)、`/config-chat-stream`(`:3432`)、`ConfigChatReq`(`:2525`)、`_CONFIG_CHAT_SECTION_HINTS`(`:2477`)、`_build_section_hint`(`:2512`)、`_CONFIG_CHAT_TOOL_WHITELIST`(`:2571`)及其私有 helper。
- [ ] grep 确认无残留引用:`rg -n "config-chat|_config_chat_event_stream|ConfigChatReq|_CONFIG_CHAT" backend/`。
- [ ] 后端起得来:`cd backend && .venv/bin/python -c "import app.main"`(import OK)。
- [ ] Commit: `chore(cleanup): remove legacy config-chat backend stream + routes`

### Task D2: 删前端 config-assistant 旧件

**Files:**
- Delete: `frontend/src/components/v2/config-assistant/`(子组件 + `useConfigChat.ts`)、`frontend/src/api/configChat.ts`

- [ ] 确认 `ConfigAssistantPanel.vue` 已不再 import 这些(C2 已换);删目录 + `configChat.ts`。
- [ ] grep:`rg -n "configChat|useConfigChat|ConfigAssistantMessages|ConfigAssistantInput" frontend/src`(应只剩可能的历史注释)。
- [ ] 编译:`cd frontend && npm run build:nocheck`(通过)。
- [ ] Commit: `chore(cleanup): remove legacy config-assistant frontend engine`

---

## Self-Review

**Spec 覆盖核对**:
- ① 应用上下文常驻锁 → A1(列)+ A3(设置)+ A5(注入)+ A4(工具锁)✅
- ② 工具集 union ~85 → A2 ✅
- ③ 前端右栏拖宽不跳转 → C2(maxWidth 1200 + 嵌 AgentConversation)✅
- ④ 数据一次性迁移 → B1 ✅
- ⑤ refresh-iframe 接入 → C3 ✅
- ⑥ 自学习 skill 保留 → A2(白名单)+ A5(加载注入)✅
- 过时 AI Coding 引导删除 → A5(新 prompt 不含)+ D1(旧 prompt 整删)✅
- cutover 删码 → D1/D2 ✅
- 测试策略(后端幂等/还原/护栏/组装 + 前端 + live)→ 各任务 TDD + CHECK ✅

**依赖顺序(多 agent 切分)**:A1 先;A2 可与 A1 并行(不碰同文件冲突点);A3/A4/A5/A6 依赖 A1;B1 依赖 A1;C1 可早起(只依赖前端);C2 依赖 C1 + A3;C3 依赖 C2;CHECK 依赖 A*/B1/C*;D 依赖 CHECK。

**Placeholder 扫描**:A4 Step1 / A5 Step1 的「读源确认」是有意的前置 read(非占位),A5 `app_context.py` 里 `...` 处明确指向移植源行号。其余步骤均有可执行代码/命令。

**类型一致**:`build_app_context_block(db, app_id, section)`、`_inject_locked_app_id(tool_name, args, session)`、`_tool_declares_param(tool_name, param)`、`_migrate_config_chat_to_ai_chat(conn)`、`useAiChatSession({appId, section})` 在引用处签名一致。
