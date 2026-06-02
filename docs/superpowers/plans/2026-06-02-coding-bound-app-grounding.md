# AI Coding bound 会话「先读应用上下文再写 SPEC」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans / subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** bound(在应用上定制)会话首轮,agent 先调读工具了解所选应用的模型/菜单,再基于「应用信息 + 用户需求」写 SPEC 和代码。

**Architecture:** 3b 局部 tool-loop。app_id 一路透传(CodingPipelineRequest → metadata → harness/profiles/coding.py → PipelineParams);首轮 brainstorm 分支判 `app_id` 是否解析到平台应用,解析到就走 `_grounded_brainstorm`(复用 `read_query.py` 的 LLM tool-loop + `_call_apaas_platform_tool` token 自愈),`apaas_app_id` 后端锁定;解析不到优雅回退现有 `_generate_brainstorm_proposal`。

**Tech Stack:** FastAPI + SQLAlchemy async + httpx;pytest(`backend/tests/`,`asyncio_mode=auto`)。

**Spec:** `docs/superpowers/specs/2026-06-02-coding-bound-app-grounding-design.md`

---

## Task 1: 透传 app_id(3 层)

**Files:**
- Modify: `backend/app/routes/harness.py`(`CodingPipelineRequest`/`IDECodingPipelineRequest` 加字段;`coding_pipeline` metadata 加 `app_id`)
- Modify: `backend/app/harness/profiles/coding.py:78`(`PipelineParams(... app_id=meta.get("app_id"))`)
- Modify: `backend/app/coding/pipeline.py:56`(`PipelineParams` 加 `app_id` 字段 + 赋值)
- Test: `backend/tests/test_coding_bound_app_grounding.py`

- [ ] **Step 1: 写失败测试 — PipelineParams 接受 app_id + harness 请求模型带 app_id**
```python
# backend/tests/test_coding_bound_app_grounding.py
import json
from unittest.mock import AsyncMock, MagicMock
import pytest

def test_pipeline_params_carries_app_id():
    from app.coding.pipeline import PipelineParams
    p = PipelineParams(message="x", user_id=1, tenant_id=1, app_id="84799")
    assert p.app_id == "84799"

def test_coding_pipeline_request_has_app_id():
    from app.routes.harness import CodingPipelineRequest
    req = CodingPipelineRequest(message="x", app_id="84799")
    assert req.app_id == "84799"
```

- [ ] **Step 2: 跑测试确认失败**
Run: `cd backend && .venv/bin/python -m pytest tests/test_coding_bound_app_grounding.py -v`
Expected: FAIL（`PipelineParams` 无 `app_id` kwarg / `CodingPipelineRequest` 无 `app_id`）

- [ ] **Step 3: 实现**
`pipeline.py` `PipelineParams.__init__`:在 `project_id: Optional[int] = None,` 后加 `app_id: Optional[str] = None,`;body 里 `self.project_id = project_id` 后加 `self.app_id = app_id`。
`harness.py`:`CodingPipelineRequest` 与 `IDECodingPipelineRequest` 各加 `app_id: str | None = None`;`coding_pipeline` 的 `metadata` dict 加 `"app_id": req.app_id,`。
`harness/profiles/coding.py:78` `PipelineParams(...)` 加一行 `app_id=meta.get("app_id"),`(与 `project_id=meta.get("project_id"),` 并列)。

- [ ] **Step 4: 跑测试确认通过**
Run: `cd backend && .venv/bin/python -m pytest tests/test_coding_bound_app_grounding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add backend/app/routes/harness.py backend/app/harness/profiles/coding.py backend/app/coding/pipeline.py backend/tests/test_coding_bound_app_grounding.py
git commit -m "feat(coding): app_id 一路透传到 PipelineParams(分场景 bound 绑定)"
```

---

## Task 2: `_resolve_bound_app`(本地 app_id → apaas_app_id + env + 名称)

**Files:**
- Modify: `backend/app/coding/pipeline.py`(新 helper)
- Test: `backend/tests/test_coding_bound_app_grounding.py`(追加)

- [ ] **Step 1: 确认 Application 字段**
Run: `cd backend && grep -nE "platform_env_id|platform_app_id|class Application" app/models/__init__.py | head`
Expected: 看到 `platform_app_id`、`platform_env_id`(若 env 字段名不同，按实际改下方代码)。

- [ ] **Step 2: 写失败测试**
```python
@pytest.mark.asyncio
async def test_resolve_bound_app_returns_handle(monkeypatch):
    from app.coding import pipeline as pl
    app = MagicMock(platform_app_id="84799", platform_env_id=3, name="通用B2B CRM", tenant_id=1)
    db = MagicMock()
    res = MagicMock(); res.scalar_one_or_none.return_value = app
    db.execute = AsyncMock(return_value=res)
    out = await pl._resolve_bound_app(tenant_id=1, app_id="10", db=db)
    assert out == ("84799", 3, "通用B2B CRM")

@pytest.mark.asyncio
async def test_resolve_bound_app_none_when_missing_platform_fields(monkeypatch):
    from app.coding import pipeline as pl
    app = MagicMock(platform_app_id=None, platform_env_id=None, name="x", tenant_id=1)
    db = MagicMock()
    res = MagicMock(); res.scalar_one_or_none.return_value = app
    db.execute = AsyncMock(return_value=res)
    assert await pl._resolve_bound_app(tenant_id=1, app_id="10", db=db) is None
```

- [ ] **Step 3: 跑测试确认失败** — `AttributeError: _resolve_bound_app`

- [ ] **Step 4: 实现**
```python
# pipeline.py
async def _resolve_bound_app(tenant_id, app_id, db):
    """本地 Application.id → (apaas_app_id, platform_env_id, app_name)。缺平台字段→None。"""
    if not app_id:
        return None
    try:
        from app.models import Application
        from sqlalchemy import select
        res = await db.execute(
            select(Application).where(
                Application.id == int(app_id),
                Application.tenant_id == tenant_id,
            )
        )
        app = res.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[grounding] 解析 bound app 失败: %s", exc)
        return None
    if not app or not getattr(app, "platform_app_id", None) or not getattr(app, "platform_env_id", None):
        return None
    return (str(app.platform_app_id), int(app.platform_env_id), app.name or "应用")
```

- [ ] **Step 5: 跑测试确认通过** + **Commit**
```bash
git add backend/app/coding/pipeline.py backend/tests/test_coding_bound_app_grounding.py
git commit -m "feat(coding): _resolve_bound_app 解析本地 app_id→apaas_app_id+env"
```

---

## Task 3: `_grounded_brainstorm`(tool-loop:先读应用再写 SPEC)

**Files:**
- Modify: `backend/app/coding/pipeline.py`(新 async generator + 常量)
- Test: `backend/tests/test_coding_bound_app_grounding.py`(追加)

- [ ] **Step 1: 写失败测试(mock LLM httpx + mock 平台工具)**
```python
@pytest.mark.asyncio
async def test_grounded_brainstorm_reads_app_then_emits_spec(monkeypatch):
    from app.coding import pipeline as pl

    # mock LLM 配置
    monkeypatch.setattr(pl, "load_coding_llm_config",
                        AsyncMock(return_value=("http://llm", "k", "m")), raising=False)

    # LLM 两次响应：①要调 list_apaas_app_models ②无工具→输出 SPEC
    calls = {"n": 0}
    def _post(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            msg = {"tool_calls": [{"id": "c1", "function": {"name": "list_apaas_app_models", "arguments": "{}"}}], "content": ""}
        else:
            msg = {"tool_calls": None, "content": "## 开发 SPEC 确认\n页面名称：商机看板"}
        r = MagicMock(); r.raise_for_status = MagicMock()
        r.json.return_value = {"choices": [{"message": msg}]}
        return r
    client = MagicMock(); client.post = AsyncMock(side_effect=_post)
    client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(pl.httpx, "AsyncClient", MagicMock(return_value=client))

    # mock 平台工具执行(断言 apaas_app_id 被锁定)
    seen = {}
    async def _fake_tool(name, args, env_id):
        seen["name"] = name; seen["apaas_app_id"] = args.get("apaas_app_id"); seen["env_id"] = env_id
        return {"ok": True, "models": [{"name": "商机"}]}
    monkeypatch.setattr(pl, "_call_apaas_platform_tool", _fake_tool, raising=False)

    params = MagicMock(tenant_id=1, selected_model="m", message="给商机做个看板")
    events = []
    spec = None
    async for ev in pl._grounded_brainstorm(params, "web_page", "84799", 3, "通用B2B CRM", db=MagicMock()):
        if ev.get("__spec__"):
            spec = ev["__spec__"]
        else:
            events.append(ev)

    assert "商机看板" in (spec or "")
    assert seen["apaas_app_id"] == "84799"     # 后端锁定，agent 不能改
    assert seen["env_id"] == 3
    assert any(e.get("step") == "read_app_context" for e in events)
```
（约定:`_grounded_brainstorm` 是 async generator,yield 普通 step 事件;最后用 `{"__spec__": <markdown>}` 把 SPEC 交回调用方。）

- [ ] **Step 2: 跑测试确认失败** — `AttributeError: _grounded_brainstorm`

- [ ] **Step 3: 实现**
```python
# pipeline.py — 顶部已 import httpx? 若无则加 `import httpx`
_GROUNDING_MAX_TURNS = 4
_GROUNDING_TOOL_NAMES = {"list_apaas_app_models", "list_apaas_app_menus"}

def _grounding_tool_defs():
    from app.coding.apaas_tools import APAAS_TOOL_DEFINITIONS
    out = []
    for t in APAAS_TOOL_DEFINITIONS:
        fn = t.get("function", {})
        if fn.get("name") in _GROUNDING_TOOL_NAMES:
            # 移除 apaas_app_id 入参(后端锁定),agent 只决定调哪个工具
            t2 = json.loads(json.dumps(t))
            props = t2["function"].get("parameters", {}).get("properties", {})
            props.pop("apaas_app_id", None)
            req = t2["function"].get("parameters", {}).get("required", [])
            t2["function"]["parameters"]["required"] = [r for r in req if r != "apaas_app_id"]
            out.append(t2)
    return out

async def _grounded_brainstorm(params, scene_type, apaas_app_id, platform_env_id, app_name, db):
    """bound 首轮:先调读工具了解应用,再输出开发 SPEC。失败时 yield {"__spec__": None} 让调用方回退。"""
    from app.agents.coding.llm_config import load_coding_llm_config
    try:
        base_url, api_key, llm_model = await load_coding_llm_config(params.tenant_id, params.selected_model or "")
    except Exception as exc:
        logger.warning("[grounding] LLM 配置失败,回退: %s", exc)
        yield {"__spec__": None}; return

    system = (
        f"你在为已有应用「{app_name}」做自开发扩展。**先调用读工具**了解该应用的数据模型、菜单"
        f"(必要时多查几次),理解清楚后**只输出一份结构化「开发 SPEC 确认」markdown**"
        f"(含:页面/组件名称、自开发类型、实现范围、功能概述、需求拆解与边界、页面结构)。"
        f"SPEC 要引用该应用的真实模型/字段/菜单,不要脑补。不要输出 SPEC 以外的话。"
    )
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": params.message[:1000]}]
    tool_defs = _grounding_tool_defs()

    for _turn in range(_GROUNDING_MAX_TURNS):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": llm_model, "messages": messages, "tools": tool_defs,
                          "tool_choice": "auto", "temperature": 0.3, "max_tokens": 1500},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("[grounding] LLM 调用失败 turn=%d,回退: %s", _turn, exc)
            yield {"__spec__": None}; return

        msg = data.get("choices", [{}])[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        content = (msg.get("content") or "").strip()
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls or None})

        if not tool_calls:
            yield {"__spec__": content or None}; return

        for tc in tool_calls:
            fn = tc.get("function", {}).get("name", "")
            tc_id = tc.get("id") or fn
            if fn not in _GROUNDING_TOOL_NAMES:
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"Error: {fn} 不可用"})
                continue
            try:
                args = json.loads(tc.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            args["apaas_app_id"] = apaas_app_id  # 后端锁定,严防跨应用
            label = "读取应用模型" if fn == "list_apaas_app_models" else "读取应用菜单"
            yield {"type": "step", "step": "read_app_context", "status": "running",
                   "data": {"label": f"📖 {label}…", "app": app_name}}
            try:
                result = await _call_apaas_platform_tool(fn, args, platform_env_id)
                result_str = json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                result_str = f"Error: {exc}"
            yield {"type": "step", "step": "read_app_context", "status": "done",
                   "data": {"label": f"📖 {label}", "app": app_name}}
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_str[:6000]})

    yield {"__spec__": None}  # 轮次耗尽没出 SPEC → 回退
```

- [ ] **Step 4: 跑测试确认通过** + **Commit**
```bash
git add backend/app/coding/pipeline.py backend/tests/test_coding_bound_app_grounding.py
git commit -m "feat(coding): _grounded_brainstorm 先读应用上下文再出 SPEC(tool-loop)"
```

---

## Task 4: 接入 run_coding_pipeline 首轮分支 + 注入 codegen

**Files:**
- Modify: `backend/app/coding/pipeline.py`(首轮 brainstorm 分支,约 line 1658)
- Test: `backend/tests/test_coding_bound_app_grounding.py`(追加分支选择测试)

- [ ] **Step 1: 写失败测试 — 解析不到 app → 不进 grounding**
```python
@pytest.mark.asyncio
async def test_unbound_skips_grounding(monkeypatch):
    from app.coding import pipeline as pl
    monkeypatch.setattr(pl, "_resolve_bound_app", AsyncMock(return_value=None))
    called = {"grounded": False}
    async def _g(*a, **k):
        called["grounded"] = True
        yield {"__spec__": "x"}
    monkeypatch.setattr(pl, "_grounded_brainstorm", _g)
    # 直接测分支 helper（见 Step 3 抽出的 _first_turn_brainstorm）
    gen = pl._first_turn_brainstorm(MagicMock(app_id=None, tenant_id=1, message="做个页面", selected_model="m"),
                                    "web_page", db=MagicMock(), effective_model="m")
    spec = None
    async for ev in gen:
        if ev.get("__spec__") is not None: spec = ev["__spec__"]
    assert called["grounded"] is False
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 — 抽 `_first_turn_brainstorm` 统一首轮逻辑,bound 走 grounded**
在 pipeline.py 加:
```python
async def _first_turn_brainstorm(params, scene_type, db, effective_model):
    """首轮 brainstorm:bound(app 解析到)走 grounded tool-loop,否则走旧 _generate_brainstorm_proposal。
    yield step 事件;最后 yield {"__spec__": <markdown or None>}。"""
    handle = await _resolve_bound_app(params.tenant_id, getattr(params, "app_id", None), db)
    if handle:
        apaas_app_id, env_id, app_name = handle
        got_spec = None
        async for ev in _grounded_brainstorm(params, scene_type, apaas_app_id, env_id, app_name, db):
            if "__spec__" in ev:
                got_spec = ev["__spec__"]
            else:
                yield ev
        if got_spec:
            yield {"__spec__": got_spec}; return
        # grounded 回退 → 落到旧逻辑
    proposal = await _generate_brainstorm_proposal(
        params.tenant_id, effective_model, scene_type, requirement=params.message)
    yield {"__spec__": proposal or None}
```
然后把 pipeline.py:1658 那个 `elif not is_iteration and scene_type in BRAINSTORM_SCENES:` 块里
原本的 `proposal = await _generate_brainstorm_proposal(...)` 调用替换为消费 `_first_turn_brainstorm`:
```python
        elif not is_iteration and scene_type in BRAINSTORM_SCENES:
            _inline_brainstorm_proposal: str = ""
            yield _record_event({"type": "step", "step": "brainstorm", "status": "running"})
            proposal = None
            async for ev in _first_turn_brainstorm(params, scene_type, db, effective_model):
                if "__spec__" in ev:
                    proposal = ev["__spec__"]
                else:
                    yield _record_event(ev)   # read_app_context running/done
            if proposal:
                _inline_brainstorm_proposal = proposal
                await save_coding_message(db, conversation_id, "assistant",
                                          BRAINSTORM_PROPOSAL_MARKER + proposal)
                yield _record_event({"type": "step", "step": "brainstorm", "status": "done"})
                yield _record_event({"type": "content", "content": proposal})
                effective_requirement = (
                    f"{params.message}\n\n[开发 SPEC 已生成，请严格按以下 SPEC 生成代码]\n{proposal}"
                )
            else:
                yield _record_event({"type": "step", "step": "brainstorm", "status": "done"})
                logger.warning("Brainstorm proposal generation failed, falling back to direct codegen")
```
(其余行为 — 工作区命名/创建/codegen — 完全不变。)

- [ ] **Step 4: 跑测试确认通过** + 全量回归
Run: `cd backend && .venv/bin/python -m pytest tests/test_coding_bound_app_grounding.py tests/test_coding_intent_router.py -v`
Expected: PASS;无新回归。

- [ ] **Step 5: Commit**
```bash
git add backend/app/coding/pipeline.py backend/tests/test_coding_bound_app_grounding.py
git commit -m "feat(coding): 首轮 brainstorm 接入 grounded 分支(bound 先读应用再 SPEC)"
```

---

## Task 5: 前端 `read_app_context` 步骤可见

**Files:**
- Modify: `frontend/src/views/coding/useCodingPipeline.ts`(`STEP_HANDLERS` 加项)

- [ ] **Step 1: 加 step handler**(对照同文件 detect_scene/create_workspace 写法)
```ts
read_app_context: {
  running: '正在读取应用上下文…',
  done: '已读取应用上下文',
  onDone: (data) => {
    const app = data?.app ? `「${data.app}」` : ''
    completeStepMsg('read_app_context', `已读取应用${app}上下文`)
  },
},
```
(放进 `STEP_HANDLERS` 对象,detect_scene 之后。)

- [ ] **Step 2: 验证编译**
Run: `cd frontend && npx vite build 2>&1 | tail -3`
Expected: `✓ built`

- [ ] **Step 3: Commit**
```bash
git add frontend/src/views/coding/useCodingPipeline.ts
git commit -m "feat(coding): 前端显示 read_app_context 读取应用上下文步骤"
```

---

## Task 6: 真实 trial 端到端验证
- [ ] 新会话 →「在应用上定制」选「通用B2B CRM」→「给他设计一个首页」→ 观察:先出「📖 读取应用上下文」步骤(调 list_app_models/menus),SPEC 引用该应用真实模型/菜单(不再是脑补的通用「工作台首页」)。
- [ ] 回归:lib 模式 / read 问答 / 改稿轮 / 解析不到 app 的旧 build 流程 无伤。
- [ ] `cd backend && .venv/bin/python -m pytest tests/test_coding_bound_app_grounding.py -v` 全绿。

## 备注 / 风险
- `_call_apaas_platform_tool` 已封 token 自愈(空 token 登录 + 401 重试),grounding 直接复用。
- `apaas_app_id` 每次工具调用都被后端覆盖为锁定值 → agent 改不了。
- LLM 不支持 tools / 配置失败 / 轮次耗尽 → `_grounded_brainstorm` yield `{"__spec__": None}`,`_first_turn_brainstorm` 回退旧 `_generate_brainstorm_proposal`,绝不阻断。
- 改动严格局部在首轮 brainstorm,detect_scene / 工作区 / codegen 主体不动。
- mcp-server twin 的 pipeline 是否同源 → 本计划只动主后端,twin 单独评估。
