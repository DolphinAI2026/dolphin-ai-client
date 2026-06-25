"""SP2a T3: run_agent 在调用方未传 override 时按 session.mode 推导行为。

地基(休眠):调用方显式传 override 的 harness 老路一字不改;只在两个 override 都为
None 时,从 session 推导 dev-apaas 提示词 + 收窄工具 + 设 _locked_ws_id。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.profile import resolve_profile, narrow_tools_for_locked_ws
from app.ai_chat.agent import _apply_session_overrides, run_agent
from app.models.ai_chat import AIChatSession


def _code_session(ws_id):
    return SimpleNamespace(mode="code", workspace_id=ws_id)


# ── 1. code 会话 + 不传 override → 推导 dev-apaas + 收窄 + 设 lock ──

def test_code_session_no_override_derives_dev_apaas():
    session = _code_session("ws-77")
    sp, tn = _apply_session_overrides(session, None, None)
    profile = resolve_profile("dev-apaas")
    assert sp == profile.system_prompt
    assert "确认即开干" in sp  # dev-apaas 特征串
    assert tn is not None
    assert set(tn) == set(narrow_tools_for_locked_ws(profile.tool_names, "ws-77"))
    # 工具被收窄
    assert "list_dev_workspaces" not in tn
    # 单工作区锁被设
    assert getattr(session, "_locked_ws_id", None) == "ws-77"


def test_code_session_no_ws_no_lock():
    """code 会话但 workspace_id 为空 → 仍给 dev-apaas 提示词,但不设 lock。"""
    session = _code_session(None)
    sp, tn = _apply_session_overrides(session, None, None)
    assert sp == resolve_profile("dev-apaas").system_prompt
    assert getattr(session, "_locked_ws_id", None) is None


# ── 2. chat 会话 + 不传 override → 行为同今天(回归保护) ──

def test_chat_session_no_override_unchanged():
    session = SimpleNamespace(mode="chat", workspace_id=None)
    sp, tn = _apply_session_overrides(session, None, None)
    assert sp is None
    assert tn is None
    assert getattr(session, "_locked_ws_id", None) is None


def test_cowork_session_no_override_unchanged():
    session = SimpleNamespace(mode="cowork", workspace_id=None)
    sp, tn = _apply_session_overrides(session, None, None)
    assert sp is None and tn is None
    assert getattr(session, "_locked_ws_id", None) is None


# ── 3. 显式传 override → 推导被跳过(override 优先,防 harness 老路被改) ──

def test_explicit_override_skips_derivation():
    session = _code_session("ws-99")
    explicit_sp = "调用方自己的提示词"
    explicit_tn = {"read_workspace_file"}
    sp, tn = _apply_session_overrides(session, explicit_sp, explicit_tn)
    assert sp == explicit_sp
    assert tn == explicit_tn
    # 显式传 override 的老路:_apply_session_overrides 不碰 _locked_ws_id
    # (harness 自己在 coding.py 里设)。
    assert not hasattr(session, "_locked_ws_id")


def test_explicit_partial_override_still_skips():
    """只传了 system_prompt(tool_names=None)也算调用方显式 → 不推导。"""
    session = _code_session("ws-99")
    sp, tn = _apply_session_overrides(session, "x", None)
    assert sp == "x"
    assert tn is None
    assert not hasattr(session, "_locked_ws_id")


# ── 4. 浅集成:run_agent 真的把 code 会话推导接进去并设 lock ──

@pytest.mark.asyncio
async def test_run_agent_code_session_sets_lock_no_network(db_session):
    """code 会话经 run_agent 且不传 override → _locked_ws_id 被设。

    _apply_session_overrides 在 _resolve_llm_config 之前跑,本测试不配 LLM(让它
    早退 error/done),不打网络,只验证推导接线 + lock 副作用确实发生。
    """
    session = AIChatSession(
        tenant_id=12345, user_id=678, title="t", mode="code", workspace_id="ws-int1"
    )
    db_session.add(session)
    await db_session.flush()

    events = []
    async for ev in run_agent(
        db_session, session, "改登录页", asyncio.Event()
    ):
        events.append(ev.get("event"))
        if ev.get("event") == "done":
            break

    # 没配模型 → 早退,但推导已先发生:lock 被设上
    assert getattr(session, "_locked_ws_id", None) == "ws-int1"
    assert "done" in events


@pytest.mark.asyncio
async def test_run_agent_chat_session_no_lock_no_network(db_session):
    """回归:chat 会话经 run_agent 不传 override → 不设 lock(行为同今天)。"""
    session = AIChatSession(
        tenant_id=12345, user_id=678, title="t", mode="chat", workspace_id=None
    )
    db_session.add(session)
    await db_session.flush()

    async for ev in run_agent(db_session, session, "你好", asyncio.Event()):
        if ev.get("event") == "done":
            break

    assert getattr(session, "_locked_ws_id", None) is None
