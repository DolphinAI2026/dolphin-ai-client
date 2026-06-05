# 延迟工具 + ToolSearch 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `run_agent` 的 ~85 工具从「每轮全量内联完整 schema」改成「核心集恒在 + 长尾只列清单 + `search_tools` 按需激活」,大幅降每轮 `tools` token。

**Architecture:** 工具宇宙三分(CORE_LOCAL + CORE_HOT 恒在 / DEFERRED 只在 system prompt 列一行清单);新 base 工具 `search_tools` 命中后把工具激活进会话 active 集;`_run_agent_inner` 每轮用 `core + active 延迟工具` 重建 `tools`;active 集从历史(过去 search_tools 调用结果)推导,重启不丢、不加表。

**Tech Stack:** Python / FastAPI / OpenAI 兼容网关(gpt-5.5,无 Anthropic tool_reference)。

spec:`docs/superpowers/specs/2026-06-05-deferred-tools-toolsearch-design.md`

---

## 执行约定
- 后端 `reload=False` → **改后端必重启** preview backend(`preview_stop`+`preview_start`)才生效;`openapi.json` grep 字段名可验证。
- 全量测试 6 个预存失败,**只跑本任务新增测试**。DB-touching 测试用 `StaticPool` 共享内存库 + monkeypatch `AsyncSessionLocal`(同 recorder/migration 测试)。
- `.venv` py3.13;命令 `cd backend && .venv/bin/pytest tests/<f>::<t> -v`。

## File Structure
- `backend/app/ai_chat/tools.py` — 加 `CORE_TOOL_NAMES`、`split_core_deferred()`、`build_deferred_manifest()`、`search_deferred_tools()`、`search_tools` 的 schema(进 `TOOL_SCHEMAS`)+ handler(进 `TOOL_HANDLERS`)。
- `backend/app/tool_registry.py` — 加 `search_hint_for(name)` / `search_hints()`(读 yaml 的可选 `search_hint`)。
- `backend/tool_registry.yaml` — 给若干工具加可选 `search_hint`。
- `backend/app/ai_chat/agent.py` — `_run_agent_inner`:开场 split + seed active(从历史)+ 每轮重建 tools + search_tools 后扩 active;`_build_initial_messages` 注入清单。加 `_reconstruct_active_tools()` + `_parse_activated()` 辅助。
- 测试:`backend/tests/test_deferred_tools.py`(纯函数)、`backend/tests/test_active_tools_history.py`(DB)。

---

## Task 1: CORE_TOOL_NAMES + split_core_deferred(纯函数)

**Files:** Modify `backend/app/ai_chat/tools.py`;Test `backend/tests/test_deferred_tools.py`

- [ ] **Step 1: 先确定 CORE_HOT(数据驱动)**
查真实高频 apaas 读工具:
```bash
cd backend && .venv/bin/python -c "
import asyncio, sqlite3
# 若 agent_step 有数据：取 step_type='tool' 的 tool_name top 频次
# 本地 SQLite：直接连 DB 文件查；查不到就用下面默认
print('查 agent_step.tool_name 频次；若空用默认')
"
```
若 `agent_step` 数据稀疏(observability 是近期上的),用默认 CORE_HOT:`list_apaas_app_models`、`list_apaas_app_menus`、`get_apaas_app_overview`、`list_apaas_app_dicts`、`list_apaas_app_roles`、`get_apaas_model_fields`(存在则取,名字以 `tool_registry.yaml` 实际为准——用 `rg "^  (list_apaas|get_apaas)" tool_registry.yaml` 核对真实名)。

- [ ] **Step 2: 写失败测试**
```python
# backend/tests/test_deferred_tools.py
from app.ai_chat.tools import CORE_TOOL_NAMES, split_core_deferred

def _fake_schemas(names):
    return [{"type":"function","function":{"name":n,"description":n+" desc","parameters":{"type":"object","properties":{}}}} for n in names]

def test_core_names_include_base_and_search():
    assert "search_tools" in CORE_TOOL_NAMES
    assert "read_attachment" in CORE_TOOL_NAMES   # base 本地工具
    assert "write_artifact" in CORE_TOOL_NAMES

def test_split_core_deferred():
    schemas = _fake_schemas(["read_attachment","search_tools","list_apaas_app_models","update_apaas_model_field","obscure_tool_x"])
    core, deferred = split_core_deferred(schemas)
    core_names = {s["function"]["name"] for s in core}
    assert "read_attachment" in core_names and "search_tools" in core_names
    assert "update_apaas_model_field" in deferred and "obscure_tool_x" in deferred  # 长尾
    assert "update_apaas_model_field" not in core_names
```

- [ ] **Step 3: 跑确认失败** — `cd backend && .venv/bin/pytest tests/test_deferred_tools.py -v` → FAIL (无 CORE_TOOL_NAMES)

- [ ] **Step 4: 实现** —— 在 `tools.py`(`TOOL_SCHEMAS` 定义之后、`get_all_tool_schemas` 附近)加:
```python
# 核心集:恒在 tools 数组、不延迟。= 8 个 base 本地工具 + search_tools + 数据驱动的高频 apaas 读。
_BASE_LOCAL_NAMES = {s["function"]["name"] for s in TOOL_SCHEMAS}  # read_attachment / run_python / write/read/edit_artifact / create_artifact_from_attachment / ask_clarifying_question / export_apaas_app_design_doc
_CORE_HOT_READS = {
    "list_apaas_app_models", "list_apaas_app_menus", "get_apaas_app_overview",
    "list_apaas_app_dicts", "list_apaas_app_roles", "get_apaas_model_fields",
}  # ← Step 1 数据/默认确定；名字以 tool_registry.yaml 实际为准
CORE_TOOL_NAMES: set[str] = _BASE_LOCAL_NAMES | {"search_tools"} | _CORE_HOT_READS

def split_core_deferred(all_schemas: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """把全集拆成 (core_schemas 列表, deferred_by_name 字典)。"""
    core, deferred = [], {}
    for s in all_schemas:
        name = s.get("function", {}).get("name", "")
        if name in CORE_TOOL_NAMES:
            core.append(s)
        else:
            deferred[name] = s
    return core, deferred
```
(注:`search_tools` 的 schema 在 Task 4 加进 `TOOL_SCHEMAS`,届时自动进 `_BASE_LOCAL_NAMES`/core。)

- [ ] **Step 5: 跑确认通过** → 2 passed

- [ ] **Step 6: Commit** — `git add backend/app/ai_chat/tools.py backend/tests/test_deferred_tools.py && git commit -m "feat(ai_chat): CORE_TOOL_NAMES + split_core_deferred for deferred tools"`

---

## Task 2: search_hint 注册表读取 + search_deferred_tools 打分搜索

**Files:** Modify `backend/app/tool_registry.py`、`backend/tool_registry.yaml`、`backend/app/ai_chat/tools.py`;Test `backend/tests/test_deferred_tools.py`

- [ ] **Step 1: 写失败测试**(加到 test_deferred_tools.py)
```python
from app.ai_chat.tools import search_deferred_tools

def test_search_select_exact():
    deferred = {"update_apaas_model_field":{"function":{"name":"update_apaas_model_field","description":"改模型字段"}},
                "add_apaas_dict_option":{"function":{"name":"add_apaas_dict_option","description":"加字典选项"}}}
    assert search_deferred_tools("select:update_apaas_model_field", deferred) == ["update_apaas_model_field"]

def test_search_keyword_tokenizes_name():
    deferred = {"update_apaas_model_field":{"function":{"name":"update_apaas_model_field","description":"修改模型字段属性"}}}
    hits = search_deferred_tools("模型 字段", deferred)
    assert "update_apaas_model_field" in hits

def test_search_uses_hint(monkeypatch):
    import app.ai_chat.tools as t
    monkeypatch.setattr(t, "_search_hint_for", lambda n: "发布 上线 go-live" if n=="republish_apaas_app" else "")
    deferred = {"republish_apaas_app":{"function":{"name":"republish_apaas_app","description":"重新发布版本"}}}
    assert "republish_apaas_app" in search_deferred_tools("上线", deferred)
```

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 实现 registry search_hint** —— `backend/app/tool_registry.py` 加:
```python
def search_hints() -> dict[str, str]:
    """name -> search_hint(yaml 可选字段);缺省空串。"""
    reg = _load_registry()  # 复用现有 yaml 载入
    return {name: (meta.get("search_hint") or "") for name, meta in reg.get("tools", {}).items()}
```
(用现有的 yaml 载入函数;若没有公开载入函数,复用 `tools_for_agent` 同款 `_load`。)

- [ ] **Step 4: 实现搜索**(`tools.py`)
```python
import re
def _search_hint_for(name: str) -> str:
    try:
        from app.tool_registry import search_hints
        return search_hints().get(name, "")
    except Exception:
        return ""

def _tokenize(name: str) -> list[str]:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name)           # CamelCase → _
    return [p for p in re.split(r"[_\W]+", s.lower()) if p]

def search_deferred_tools(query: str, deferred_by_name: dict[str, dict], limit: int = 8) -> list[str]:
    q = (query or "").strip()
    if q.lower().startswith("select:"):
        want = [x.strip() for x in q[len("select:"):].split(",") if x.strip()]
        return [n for n in want if n in deferred_by_name]
    terms = [w for w in re.split(r"[\s,]+", q.lower()) if w]
    scored = []
    for name, schema in deferred_by_name.items():
        desc = (schema.get("function", {}).get("description") or "")
        hint = _search_hint_for(name)
        hay_name = set(_tokenize(name))
        hay_text = (desc + " " + hint).lower()
        score = 0
        for term in terms:
            if term in hay_name: score += 3
            elif term in hay_text: score += 1
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _, n in scored[:limit]]
```

- [ ] **Step 5: 跑确认通过** → all pass

- [ ] **Step 6: 给几个工具加 search_hint** —— `tool_registry.yaml` 挑 5-8 个名字不直白的工具加 `search_hint`(如 `republish_apaas_app: search_hint: "发布 上线 release"`、`upload_external_zip_to_apaas: search_hint: "自开发包 zip 上传"`)。

- [ ] **Step 7: Commit** — `git add backend/app/tool_registry.py backend/tool_registry.yaml backend/app/ai_chat/tools.py backend/tests/test_deferred_tools.py && git commit -m "feat(ai_chat): search_deferred_tools (keyword/select scoring) + registry search_hint"`

---

## Task 3: build_deferred_manifest(纯函数)

**Files:** Modify `tools.py`;Test `test_deferred_tools.py`

- [ ] **Step 1: 写失败测试**
```python
from app.ai_chat.tools import build_deferred_manifest
def test_manifest_lists_each_deferred_with_desc():
    deferred = {"update_apaas_model_field":{"function":{"name":"update_apaas_model_field","description":"改模型字段必填/类型"}}}
    m = build_deferred_manifest(deferred)
    assert "update_apaas_model_field" in m and "改模型字段" in m
    assert "search_tools" in m  # 引导句提到先 search
```
- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现**
```python
def build_deferred_manifest(deferred_by_name: dict[str, dict]) -> str:
    if not deferred_by_name:
        return ""
    lines = ["\n\n## 可按需加载的工具(先 search_tools 再用)",
             "下面这些工具**不在当前 tools 列表里**;要用,先调 `search_tools`(关键词或 `select:工具名`)把它们加载进来,下一轮即可调用:"]
    for name in sorted(deferred_by_name):
        desc = (deferred_by_name[name].get("function", {}).get("description") or "").strip().replace("\n", " ")
        hint = _search_hint_for(name)
        line = f"- {name}: {desc[:80]}"
        if hint:
            line += f"(关键词: {hint})"
        lines.append(line)
    return "\n".join(lines)
```
- [ ] **Step 4: 跑确认通过**
- [ ] **Step 5: Commit** — `git commit -am "feat(ai_chat): build_deferred_manifest"`(只 add 相关文件)

---

## Task 4: search_tools 工具(schema + handler)

**Files:** Modify `tools.py`(`TOOL_SCHEMAS` + `TOOL_HANDLERS`);Test `test_deferred_tools.py`

- [ ] **Step 1: 写失败测试**
```python
import json, pytest
@pytest.mark.asyncio
async def test_search_tools_handler_returns_activated(monkeypatch):
    import app.ai_chat.tools as t
    # 让 handler 能拿到 deferred 全集:它从 _LAST_TOOL_SCHEMAS split
    t._LAST_TOOL_SCHEMAS = [{"type":"function","function":{"name":"update_apaas_model_field","description":"改模型字段","parameters":{}}}]
    res = await t._handle_search_tools({"query":"select:update_apaas_model_field"}, session=None, db=None)
    data = json.loads(res)
    assert data["ok"] is True and "update_apaas_model_field" in data["activated"]
```
- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现** —— `TOOL_SCHEMAS` 末尾加 search_tools 条目:
```python
    {"type":"function","function":{
        "name":"search_tools",
        "description":"按需加载延迟工具:当你要用的工具不在当前 tools 列表(但在「可按需加载的工具」清单里)时,先调这个把它加载进来,下一轮就能直接调用。query 用关键词,或 'select:工具名1,工具名2' 精确选。",
        "parameters":{"type":"object","properties":{"query":{"type":"string","description":"关键词,或 select:名字 精确选"}},"required":["query"]}}},
```
handler + 注册:
```python
async def _handle_search_tools(args: dict, session, db) -> str:
    import json
    _core, deferred = split_core_deferred(_LAST_TOOL_SCHEMAS or [])
    names = search_deferred_tools(args.get("query",""), deferred)
    if not names:
        return json.dumps({"ok":True,"activated":[],"message":"无匹配工具;换个关键词或用 select:工具名"}, ensure_ascii=False)
    return json.dumps({"ok":True,"activated":names,"message":f"已加载 {len(names)} 个工具,下一轮可直接调用: {', '.join(names)}"}, ensure_ascii=False)
```
在 `TOOL_HANDLERS = {...}`(`:1368`)里加 `"search_tools": _handle_search_tools,`。
- [ ] **Step 4: 跑确认通过**
- [ ] **Step 5: 导入检查** — `cd backend && .venv/bin/python -c "import app.ai_chat.tools"`
- [ ] **Step 6: Commit** — `git commit` 相关文件,msg `feat(ai_chat): search_tools tool (schema + handler)`

---

## Task 5: active 集从历史推导

**Files:** Modify `backend/app/ai_chat/agent.py`(加 `_parse_activated` + `_reconstruct_active_tools`);Test `backend/tests/test_active_tools_history.py`

- [ ] **Step 1: 写失败测试**(StaticPool 共享内存库,种一条 search_tools tool_call)
```python
import json, pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models.ai_chat  # noqa
from app.models.ai_chat import AIChatSession, AIChatToolCall
from app.ai_chat.agent import _reconstruct_active_tools, _parse_activated

def test_parse_activated():
    assert set(_parse_activated(json.dumps({"activated":["a","b"]}))) == {"a","b"}
    assert _parse_activated("not json") == []

@pytest.mark.asyncio
async def test_reconstruct_active_from_history():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as db:
        s = AIChatSession(tenant_id=1, user_id=1, title="t"); db.add(s); await db.flush()
        db.add(AIChatToolCall(session_id=s.id, tool_name="search_tools", status="success",
                              result_text=json.dumps({"activated":["update_apaas_model_field"]})))
        db.add(AIChatToolCall(session_id=s.id, tool_name="list_apaas_app_models", status="success", result_text="..."))
        await db.commit()
        active = await _reconstruct_active_tools(db, s)
    assert "update_apaas_model_field" in active
```
- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现**(`agent.py`,顶部加)
```python
def _parse_activated(result_text: str) -> list[str]:
    try:
        import json
        d = json.loads(result_text or "")
        return list(d.get("activated") or []) if isinstance(d, dict) else []
    except Exception:
        return []

async def _reconstruct_active_tools(db, session) -> set[str]:
    """从历史推导本会话已激活的延迟工具:过去 search_tools 调用的 activated + 已成功调用过的工具名。"""
    from sqlalchemy import select as _sel
    from app.models.ai_chat import AIChatToolCall
    active: set[str] = set()
    try:
        rows = (await db.execute(_sel(AIChatToolCall).where(AIChatToolCall.session_id == session.id))).scalars().all()
        for tc in rows:
            if tc.tool_name == "search_tools":
                active.update(_parse_activated(tc.result_text or ""))
            else:
                active.add(tc.tool_name)  # 兜底:用过的就保持可用
    except Exception:
        pass
    return active
```
- [ ] **Step 4: 跑确认通过** → 2 passed
- [ ] **Step 5: Commit** — `feat(ai_chat): reconstruct active deferred tools from session history`

---

## Task 6: 接进 _run_agent_inner(每轮重建 tools + 注入清单)

**Files:** Modify `backend/app/ai_chat/agent.py`

- [ ] **Step 1: 读现状** —— 看 `_run_agent_inner`:`_build_initial_messages` 调用(~663)、`tool_schemas = await get_all_tool_schemas()` + browser 排除(~674)、`_call_llm_stream(cfg, messages, tool_schemas, abort_event)`(:713)、`result_text = await execute_tool(...)`(:927)。

- [ ] **Step 2: 开场 split + seed active + 注入清单**
把现有「`tool_schemas = await get_all_tool_schemas()` + browser 排除」那段(~674)改成:
```python
    all_schemas = await get_all_tool_schemas()
    if getattr(session, "app_id", None):
        all_schemas = [t for t in all_schemas if not str(t.get("function",{}).get("name","")).startswith("browser_")]
    from app.ai_chat.tools import split_core_deferred, build_deferred_manifest
    core_schemas, deferred_by_name = split_core_deferred(all_schemas)
    deferred_manifest = build_deferred_manifest(deferred_by_name)
    active_tool_names: set[str] = await _reconstruct_active_tools(db, session)
```
并把 `_build_initial_messages` 调用(~663)改为传入清单:`messages = await _build_initial_messages(db, session, current_user_message, section, view_context, deferred_manifest)` —— 但 `_build_initial_messages` 在 split 之前(663<674),**reorder**:把上面这段 split/manifest 移到 `_build_initial_messages` 调用**之前**。`_build_initial_messages` 加参 `deferred_manifest: str = ""`,在拼 system_prompt 时 `system_prompt += deferred_manifest`(放 app_context 之后)。

- [ ] **Step 3: 每轮重建 tools**
在 turn loop 内、`_call_llm_stream` 调用(:713)之前加:
```python
        tool_schemas = core_schemas + [deferred_by_name[n] for n in active_tool_names if n in deferred_by_name]
```
(删掉 loop 外那个固定 `tool_schemas`;现在每轮算。)

- [ ] **Step 4: search_tools 后扩 active**
在执行工具处(`result_text = await execute_tool(tool_name, args, session, db)`,:927)之后加:
```python
                if tool_name == "search_tools":
                    active_tool_names.update(_parse_activated(result_text))
```

- [ ] **Step 5: 验证编译 + 导入 + 不回归**
```bash
cd backend && .venv/bin/python -c "import app.ai_chat.agent" && .venv/bin/pytest tests/test_deferred_tools.py tests/test_active_tools_history.py tests/test_app_context_prompt.py tests/test_app_id_injection.py -v
```
Expected: 全过(app_context/app_id 护栏不回归)。

- [ ] **Step 6: 重启后端 + live 端到端**
`preview_stop`+`preview_start` backend。preview:产品租户某 app 右栏发「把某字段改必填」→ 看:① system prompt 有延迟清单(后端日志/或行为);② 模型调 `search_tools` → 下一轮调到 `update_apaas_model_field`;③ 改成功;④ 每轮 tools 不再是 ~85(可在 `_call_llm_stream` 临时 log `len(tools)` 验证,验完删)。

- [ ] **Step 7: Commit** — `feat(ai_chat): wire deferred tools into run_agent (per-turn tools rebuild + manifest + active set)`

---

## Self-Review

**Spec 覆盖**:三分(T1)✅ / manifest(T3)✅ / search_tools(T4)✅ / 每轮重建(T6 S3)✅ / active 从历史(T5)✅ / search_hint(T2)✅ / 数据驱动 CORE_HOT(T1 S1)✅ / 测试(各任务 + T6 live)✅。
**依赖顺序**:T1→T2→T3→T4(纯函数/工具,可顺序)→ T5(独立)→ T6(依赖 T1-T5,集成)。多 agent:T1-T5 可较独立并行(都在 tools.py/agent.py 加新符号,注意 tools.py 并发编辑冲突——建议 T1-T4 串行同文件,T5 并行),T6 最后。
**Placeholder**:T1 S1 的 agent_step 查询是真命令 + 默认兜底(非占位)。其余均有完整代码。
**类型一致**:`split_core_deferred(all)->(list,dict)`、`search_deferred_tools(query,deferred,limit)->list`、`build_deferred_manifest(deferred)->str`、`_reconstruct_active_tools(db,session)->set`、`_parse_activated(str)->list`、`_handle_search_tools(args,session,db)->str`、`CORE_TOOL_NAMES:set` 各处签名一致。
