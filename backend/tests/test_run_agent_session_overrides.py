"""SP2a T3 + 修复: run_agent 在调用方未传 override 时按 session.mode 推导行为。

地基(休眠):调用方显式传 override 的 harness 老路一字不改;只在两个 override 都为
None 时,从 session 推导 dev-apaas 提示词 + 收窄工具 + 设 _locked_ws_id +
**ws 绑定 view_context(告诉 agent 当前 ws_id)**。

⚠️ 2026-06-25 修复: 原 _apply_session_overrides 只推导 (prompt, tools),没推导
view_context → code 会话经 /ai-chat 发送时 agent 不知道 ws_id,反问用户「请把 ws_id
发我」。现返回 3 元组,第 3 个是 ws 绑定上下文。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import zlib

import pytest
from sqlalchemy import select

from app.agents.profile import resolve_profile, narrow_tools_for_locked_ws
from app.ai_chat import agent as agent_mod
from app.ai_chat.agent import _apply_session_overrides, run_agent
from app.models.ai_chat import AIChatMessage, AIChatSession


def _code_session(ws_id):
    return SimpleNamespace(mode="code", workspace_id=ws_id)


# ── 1. code 会话 + 不传 override → 推导 dev-apaas + 收窄 + 设 lock + ws view_context ──

def test_code_session_no_override_derives_dev_apaas():
    session = _code_session("ws-77")
    sp, tn, vc = _apply_session_overrides(session, None, None)
    profile = resolve_profile("dev-apaas")
    assert sp == profile.system_prompt
    assert "确认即开干" in sp  # dev-apaas 特征串
    assert tn is not None
    assert set(tn) == set(narrow_tools_for_locked_ws(profile.tool_names, "ws-77"))
    # 工具被收窄
    assert "list_dev_workspaces" not in tn
    # 单工作区锁被设
    assert getattr(session, "_locked_ws_id", None) == "ws-77"
    # ★ 修复核心: 推导出 ws 绑定 view_context,含 ws_id → agent 不再反问
    assert vc is not None
    assert "ws-77" in vc


def test_code_session_no_ws_no_lock_no_vc():
    """code 会话但 workspace_id 为空 → 仍给 dev-apaas 提示词,但不设 lock、无 ws view_context。"""
    session = _code_session(None)
    sp, tn, vc = _apply_session_overrides(session, None, None)
    assert sp == resolve_profile("dev-apaas").system_prompt
    assert getattr(session, "_locked_ws_id", None) is None
    assert vc is None


# ── 2. chat 会话 + 不传 override → 行为同今天(回归保护) ──

def test_chat_session_no_override_unchanged():
    session = SimpleNamespace(mode="chat", workspace_id=None)
    sp, tn, vc = _apply_session_overrides(session, None, None)
    assert sp is None
    assert tn is None
    assert vc is None
    assert getattr(session, "_locked_ws_id", None) is None


def test_cowork_session_no_override_unchanged():
    session = SimpleNamespace(mode="cowork", workspace_id=None)
    sp, tn, vc = _apply_session_overrides(session, None, None)
    assert sp is None and tn is None and vc is None
    assert getattr(session, "_locked_ws_id", None) is None


# ── 3. 显式传 override → 推导被跳过(override 优先,防 harness 老路被改) ──

def test_explicit_override_skips_derivation():
    session = _code_session("ws-99")
    explicit_sp = "调用方自己的提示词"
    explicit_tn = {"read_workspace_file"}
    sp, tn, vc = _apply_session_overrides(session, explicit_sp, explicit_tn)
    assert sp == explicit_sp
    assert tn == explicit_tn
    # 显式传 override 的老路: 不推导 view_context(harness 自己传 view_context)
    assert vc is None
    # 也不碰 _locked_ws_id(harness 自己在 coding.py 里设)。
    assert not hasattr(session, "_locked_ws_id")


def test_explicit_partial_override_still_skips():
    """只传了 system_prompt(tool_names=None)也算调用方显式 → 不推导。"""
    session = _code_session("ws-99")
    sp, tn, vc = _apply_session_overrides(session, "x", None)
    assert sp == "x"
    assert tn is None
    assert vc is None
    assert not hasattr(session, "_locked_ws_id")


# ── 4. 浅集成:run_agent 真的把 code 会话推导接进去并设 lock ──

@pytest.mark.asyncio
async def test_run_agent_code_session_sets_lock_no_network(db_session):
    """code 会话经 run_agent 且不传 override → _locked_ws_id 被设。"""
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


@pytest.mark.asyncio
async def test_run_agent_persists_unexpected_frozen_runtime_failure(db_session, monkeypatch):
    """A lazy PyInstaller import failure must be visible after the UI reloads history."""
    session = AIChatSession(
        tenant_id=12345,
        user_id=678,
        title="系统助手",
        mode="code",
        assistant_profile="system_assistant",
    )
    db_session.add(session)
    await db_session.flush()

    async def fail_before_agent_loop(*_args, **_kwargs):
        raise zlib.error("incorrect header check")
        yield  # pragma: no cover - keeps this an async generator

    monkeypatch.setattr(agent_mod, "_run_agent_inner", fail_before_agent_loop)

    events = [
        event
        async for event in run_agent(db_session, session, "列出种子工程", asyncio.Event())
    ]

    assistant_event = next(event for event in events if event["event"] == "assistant_message")
    error_event = next(event for event in events if event["event"] == "error")
    assert "本地系统助手运行组件加载失败" in json.loads(assistant_event["data"])["content"]
    assert json.loads(error_event["data"])["code"] == "SYSTEM_ASSISTANT_RUNTIME_LOAD_FAILED"

    persisted = (await db_session.execute(
        select(AIChatMessage).where(AIChatMessage.session_id == session.id)
    )).scalars().all()
    assert any(
        message.extra_meta.get("notice_type") == "SYSTEM_ASSISTANT_RUNTIME_LOAD_FAILED"
        for message in persisted
    )
