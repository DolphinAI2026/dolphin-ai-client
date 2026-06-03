"""把 app 上下文喂进 codegen agent(2026-06,方案 B)— 行为测试

需求(handoff-2026-06-03 待办③,大明哥定 B 方案):codegen agent 已注册 aPaaS 读工具
(list_apaas_app_models / list_apaas_app_menus),但 agent 不知道在哪个应用上干活、
apaas_app_id 也没锁定。B 方案 = 把 bound app 的 apaas_app_id/env 锁进 codegen 工具
+ 在 prompt 告诉 agent 先读真实模型/菜单。

覆盖:
- _apply_bound_app_scope:bound 且工具吃 apaas_app_id → 强制成绑定应用(防跨应用读/传错);
  工具不吃 apaas_app_id / 非 bound → 原样不动。
- build_user_prompt:传 app_context → 渲染「关联应用上下文」段(含应用名 + 读工具名);不传 → 无该段。
- 端到端 wiring:bound ctx 下,平台 executor 真的把 LLM 传的 apaas_app_id 覆盖成锁定值、用 bound env。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents.types import AgentContext
from app.agents.coding.tools import _apply_bound_app_scope, build_coding_tools
from app.agents.coding.prompts import build_user_prompt


def _ctx(extra=None, input=None):
    return AgentContext(
        session_id="s", conversation_id=1, user_id=1, tenant_id=57,
        model="gpt-5.5", workspace_id="ws-x",
        input=input or {}, extra=extra or {},
    )


# ---------- 单元:apaas_app_id 锁定 helper ----------

def test_apply_bound_app_scope_overrides_when_bound_and_accepts():
    """bound + 工具吃 apaas_app_id → 强制成绑定应用,其他入参保留。"""
    ctx = _ctx(extra={"bound_apaas_app_id": "APP_REAL"})
    out = _apply_bound_app_scope({"apaas_app_id": "ATTACKER", "with_fields": True}, ctx, accepts_app_id=True)
    assert out["apaas_app_id"] == "APP_REAL"   # 覆盖 LLM 传的值
    assert out["with_fields"] is True           # 其他入参不动


def test_apply_bound_app_scope_noop_when_tool_has_no_app_id():
    """工具 schema 不吃 apaas_app_id → 不注入(避免给不接收的工具塞多余参数)。"""
    ctx = _ctx(extra={"bound_apaas_app_id": "APP_REAL"})
    out = _apply_bound_app_scope({"foo": 1}, ctx, accepts_app_id=False)
    assert "apaas_app_id" not in out


def test_apply_bound_app_scope_noop_when_not_bound():
    """非 bound(没在应用上定制)→ 原样,不锁。"""
    ctx = _ctx(extra={})
    out = _apply_bound_app_scope({"apaas_app_id": "X"}, ctx, accepts_app_id=True)
    assert out["apaas_app_id"] == "X"


# ---------- 单元:prompt 关联应用上下文段 ----------

def test_build_user_prompt_renders_app_context():
    p = build_user_prompt(
        requirement="给商机做个看板", conversation_summary="",
        workspace_info={"project_type": "form-component-dual"}, workspace_path=Path("/tmp/ws"),
        app_context={"app_name": "通用B2B CRM", "apaas_app_id": "849609751397400576"},
    )
    assert "通用B2B CRM" in p
    assert "list_apaas_app_models" in p
    assert "list_apaas_app_menus" in p


def test_build_user_prompt_no_app_context_section_when_absent():
    p = build_user_prompt(
        requirement="做个组件", conversation_summary="",
        workspace_info={"project_type": "form-component-dual"}, workspace_path=Path("/tmp/ws"),
    )
    assert "关联应用上下文" not in p


# ---------- 端到端:平台 executor 锁定 apaas_app_id + 用 bound env ----------

@pytest.mark.asyncio
async def test_platform_tool_locks_apaas_app_id_to_bound_app():
    """bound ctx 下,agent 调 list_apaas_app_models 即使传了别的 apaas_app_id,
    实际执行也被强制成绑定应用,且用 ctx.extra 的 bound env。"""
    recorded: dict = {}

    async def _fake_models(args, env_id, db):
        recorded["args"] = args
        recorded["env_id"] = env_id
        return json.dumps({"models": []}, ensure_ascii=False)

    @asynccontextmanager
    async def _fake_session():
        yield MagicMock()

    with (
        patch.dict("app.coding.apaas_tools.APAAS_TOOL_EXECUTORS_PLATFORM",
                   {"list_apaas_app_models": _fake_models}, clear=False),
        patch("app.database.AsyncSessionLocal", _fake_session),
    ):
        tools = build_coding_tools()
        tool = next(t for t in tools if t.name == "list_apaas_app_models")
        ctx = _ctx(extra={"bound_apaas_app_id": "APP_REAL", "platform_env_id": 7})
        res = await tool.execute({"apaas_app_id": "ATTACKER", "with_fields": True}, ctx)

    assert res.success, res.content
    assert recorded["args"]["apaas_app_id"] == "APP_REAL"  # 锁定生效,跨应用读被挡
    assert recorded["env_id"] == 7                          # 用 bound env,不走租户默认兜底


# ---------- 单元:pipeline → codegen ctx 注入 glue ----------

def test_codegen_overlays_bound_injects_app_id_env_and_context():
    from app.coding.pipeline import _codegen_app_context_overlays
    _input, _extra = _codegen_app_context_overlays(("APP_REAL", 7, "通用B2B CRM"), "SYS")
    assert _input["system_prompt"] == "SYS"
    assert _input["app_context"] == {"app_name": "通用B2B CRM", "apaas_app_id": "APP_REAL"}
    assert _extra["bound_apaas_app_id"] == "APP_REAL"
    assert _extra["platform_env_id"] == 7


def test_codegen_overlays_non_bound_is_noop():
    from app.coding.pipeline import _codegen_app_context_overlays
    _input, _extra = _codegen_app_context_overlays(None, "SYS")
    assert _input == {"system_prompt": "SYS"}   # 无 app_context
    assert _extra == {}                          # 无锁定 → codegen 行为不变


# ---------- agent 层:ctx.input["app_context"] → build_initial_user_message ----------

def test_agent_build_initial_user_message_includes_app_context():
    """CodingAgent 把 ctx.input["app_context"] 透传进 build_user_prompt(agent.py wiring)。"""
    from app.agents.coding.agent import CodingAgent
    ctx = _ctx(
        input={
            "system_prompt": "SYS",
            "requirement": "给商机做个看板",
            "app_context": {"app_name": "通用B2B CRM", "apaas_app_id": "849609751397400576"},
        },
        extra={"bound_apaas_app_id": "849609751397400576", "platform_env_id": 7},
    )
    agent = CodingAgent(ctx)
    prompt = agent.build_initial_user_message()
    assert "通用B2B CRM" in prompt
    assert "list_apaas_app_models" in prompt
