"""bound 会话「先读应用上下文再写 SPEC」(3b 局部 tool-loop) 测试。

覆盖:
  Task1 app_id 透传(PipelineParams / CodingPipelineRequest)
  Task2 _resolve_bound_app(本地 app_id → apaas_app_id+env+name)
  Task3 _grounded_brainstorm(tool-loop: 先读应用再出 SPEC + apaas_app_id 锁定 + 回退)
  Task4 _first_turn_brainstorm 分支(解析不到 app → 不进 grounding)
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Task 1: app_id 透传 ──────────────────────────────────────────

def test_pipeline_params_carries_app_id():
    from app.coding.pipeline import PipelineParams
    p = PipelineParams(message="x", user_id=1, tenant_id=1, app_id="84799")
    assert p.app_id == "84799"


def test_coding_pipeline_request_has_app_id():
    from app.routes.harness import CodingPipelineRequest
    req = CodingPipelineRequest(message="x", app_id="84799")
    assert req.app_id == "84799"


# ── Task 2: _resolve_bound_app ──────────────────────────────────

async def test_resolve_bound_app_returns_handle():
    from app.coding import pipeline as pl
    app = MagicMock(apaas_app_id="84799", platform_env_id=3, app_name="通用B2B CRM", tenant_id=1)
    db = MagicMock()
    res = MagicMock(); res.scalar_one_or_none.return_value = app
    db.execute = AsyncMock(return_value=res)
    out = await pl._resolve_bound_app(tenant_id=1, app_id="10", db=db)
    assert out == ("84799", 3, "通用B2B CRM")


async def test_resolve_bound_app_none_when_missing_platform_fields():
    from app.coding import pipeline as pl
    app = MagicMock(apaas_app_id=None, platform_env_id=None, app_name="x", tenant_id=1)
    db = MagicMock()
    res = MagicMock(); res.scalar_one_or_none.return_value = app
    db.execute = AsyncMock(return_value=res)
    assert await pl._resolve_bound_app(tenant_id=1, app_id="10", db=db) is None


async def test_resolve_bound_app_none_when_no_app_id():
    from app.coding import pipeline as pl
    assert await pl._resolve_bound_app(tenant_id=1, app_id=None, db=MagicMock()) is None


# ── Task 3: _grounded_brainstorm(tool-loop:先读应用再出 SPEC) ────

async def test_grounded_brainstorm_reads_app_then_emits_spec(monkeypatch):
    from app.coding import pipeline as pl

    monkeypatch.setattr("app.agents.coding.llm_config.load_coding_llm_config",
                        AsyncMock(return_value=("http://llm", "k", "m")))

    # LLM 两次响应:① 要调 list_apaas_app_models  ② 无工具→输出 SPEC
    calls = {"n": 0}
    def _post(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            msg = {"tool_calls": [{"id": "c1", "function": {"name": "list_apaas_app_models", "arguments": "{}"}}], "content": ""}
        else:
            msg = {"tool_calls": None, "content": "## 开发 SPEC 确认\n页面名称:商机看板"}
        r = MagicMock(); r.raise_for_status = MagicMock()
        r.json = MagicMock(return_value={"choices": [{"message": msg}]})
        return r
    client = MagicMock()
    client.post = AsyncMock(side_effect=_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(pl.httpx, "AsyncClient", MagicMock(return_value=client))

    # mock 工具执行(断言 apaas_app_id 被后端锁定)
    seen = {}
    async def _fake_tool(name, args, env_id):
        seen["name"] = name; seen["apaas_app_id"] = args.get("apaas_app_id"); seen["env_id"] = env_id
        return {"ok": True, "models": [{"name": "商机"}]}
    monkeypatch.setattr(pl, "_call_grounding_tool", _fake_tool)

    params = MagicMock(tenant_id=1, selected_model="m", message="给商机做个看板")
    events = []; spec = None
    async for ev in pl._grounded_brainstorm(params, "web_page", "84799", 3, "通用B2B CRM", db=MagicMock()):
        if "__spec__" in ev:
            spec = ev["__spec__"]
        else:
            events.append(ev)

    assert "商机看板" in (spec or "")
    assert seen["apaas_app_id"] == "84799"      # 后端锁定,agent 改不了
    assert seen["env_id"] == 3
    assert any(e.get("step") == "read_app_context" for e in events)


async def test_grounded_brainstorm_fallbacks_on_llm_error(monkeypatch):
    from app.coding import pipeline as pl
    monkeypatch.setattr("app.agents.coding.llm_config.load_coding_llm_config",
                        AsyncMock(side_effect=RuntimeError("no llm")))
    params = MagicMock(tenant_id=1, selected_model="m", message="x")
    out = [ev async for ev in pl._grounded_brainstorm(params, "web_page", "84799", 3, "X", db=MagicMock())]
    assert out == [{"__spec__": None}]   # LLM 配置失败 → 回退信号


# ── Task 4: _first_turn_brainstorm 分支选择 ─────────────────────

async def test_unbound_skips_grounding(monkeypatch):
    from app.coding import pipeline as pl
    monkeypatch.setattr(pl, "_resolve_bound_app", AsyncMock(return_value=None))
    called = {"grounded": False}
    async def _g(*a, **k):
        called["grounded"] = True
        yield {"__spec__": "x"}
    monkeypatch.setattr(pl, "_grounded_brainstorm", _g)
    monkeypatch.setattr(pl, "_generate_brainstorm_proposal", AsyncMock(return_value="OLD SPEC"))
    params = MagicMock(app_id=None, tenant_id=1, message="做个页面", selected_model="m")
    spec = None
    async for ev in pl._first_turn_brainstorm(params, "web_page", db=MagicMock(), effective_model="m"):
        if "__spec__" in ev:
            spec = ev["__spec__"]
    assert called["grounded"] is False
    assert spec == "OLD SPEC"


async def test_bound_uses_grounding(monkeypatch):
    from app.coding import pipeline as pl
    monkeypatch.setattr(pl, "_resolve_bound_app", AsyncMock(return_value=("84799", 3, "通用B2B CRM")))
    async def _g(params, scene_type, apaas_app_id, env_id, app_name, db):
        yield {"type": "step", "step": "read_app_context", "status": "done", "data": {}}
        yield {"__spec__": "GROUNDED SPEC 引用商机模型"}
    monkeypatch.setattr(pl, "_grounded_brainstorm", _g)
    monkeypatch.setattr(pl, "_generate_brainstorm_proposal", AsyncMock(return_value="OLD SPEC"))
    params = MagicMock(app_id="10", tenant_id=1, message="给商机做看板", selected_model="m")
    spec = None; steps = []
    async for ev in pl._first_turn_brainstorm(params, "web_page", db=MagicMock(), effective_model="m"):
        if "__spec__" in ev:
            spec = ev["__spec__"]
        else:
            steps.append(ev)
    assert spec == "GROUNDED SPEC 引用商机模型"
    assert any(s.get("step") == "read_app_context" for s in steps)


async def test_bound_grounding_none_falls_back_to_old(monkeypatch):
    from app.coding import pipeline as pl
    monkeypatch.setattr(pl, "_resolve_bound_app", AsyncMock(return_value=("84799", 3, "X")))
    async def _g(*a, **k):
        yield {"__spec__": None}
    monkeypatch.setattr(pl, "_grounded_brainstorm", _g)
    monkeypatch.setattr(pl, "_generate_brainstorm_proposal", AsyncMock(return_value="OLD SPEC"))
    params = MagicMock(app_id="10", tenant_id=1, message="x", selected_model="m")
    spec = None
    async for ev in pl._first_turn_brainstorm(params, "web_page", db=MagicMock(), effective_model="m"):
        if "__spec__" in ev:
            spec = ev["__spec__"]
    assert spec == "OLD SPEC"
