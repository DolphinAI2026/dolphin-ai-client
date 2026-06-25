"""SP2a T1: AIChatSession.workspace_id 列 + cutover 建会话写入。

地基:Code 会话把绑定的 ws_id 落到 session.workspace_id,供 run_agent 引擎
推导 ws-lock(SP2a T3)。SP1 的两处 guard 不动,本步纯增量。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.ai_chat import AIChatSession


def test_model_accepts_workspace_id():
    """模型层:AIChatSession(workspace_id=...) 透传。"""
    s = AIChatSession(tenant_id=1, user_id=1, title="t", mode="code", workspace_id="ws-x")
    assert s.workspace_id == "ws-x"


def test_model_workspace_id_defaults_none():
    s = AIChatSession(tenant_id=1, user_id=1, title="t", mode="chat")
    assert s.workspace_id is None


@pytest.mark.asyncio
async def test_get_or_create_writes_workspace_id(db_session):
    """cutover 建会话(_get_or_create_ai_session)时 ws_id 落到 workspace_id 列。"""
    from app.harness.profiles.coding import CodingProfile

    params = SimpleNamespace(
        conversation_id=None,
        tenant_id=7,
        user_id=11,
        app_id=None,
        message="改一下登录页",
        workspace_id="ws-abc123",
    )
    thread_ctx = SimpleNamespace(metadata={})

    profile = CodingProfile.__new__(CodingProfile)  # 不跑 __init__,只测该方法
    session = await profile._get_or_create_ai_session(
        db_session, params, thread_ctx, "ws-abc123"
    )
    assert session.mode == "code"
    assert session.workspace_id == "ws-abc123"

    # 落库验证
    fetched = await db_session.get(AIChatSession, session.id)
    assert fetched.workspace_id == "ws-abc123"


@pytest.mark.asyncio
async def test_get_or_create_no_ws_writes_none(db_session):
    """没绑 ws_id → workspace_id 为 None(空串归一为 None)。"""
    from app.harness.profiles.coding import CodingProfile

    params = SimpleNamespace(
        conversation_id=None,
        tenant_id=7,
        user_id=11,
        app_id=None,
        message="代码会话",
        workspace_id="",
    )
    thread_ctx = SimpleNamespace(metadata={})

    profile = CodingProfile.__new__(CodingProfile)
    session = await profile._get_or_create_ai_session(db_session, params, thread_ctx, "")
    assert session.workspace_id is None
