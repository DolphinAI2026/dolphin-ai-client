"""unified 系统提示「改提示词不发版」回归测试。

覆盖三件事：
  1. DB 里有 (tenant, agent_id='unified', phase='system') 行 → 用 DB 模板（覆盖生效）。
  2. DB 里没行 → lazy seed 后仍回退到代码常量 SYSTEM_PROMPT_UNIFIED。
  3. DB 查询抛异常 → 不挂主链路，回退代码常量。

_resolve_unified_system_prompt 只管**静态模板**；app 上下文等运行时拼接不在此处，
所以这里只断言静态模板本身的选择逻辑。
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.ai_chat.agent import (
    SYSTEM_PROMPT_UNIFIED,
    UNIFIED_AGENT_ID,
    UNIFIED_PHASE,
    _resolve_unified_system_prompt,
)
from app.models.agent_prompt import AgentPrompt


@pytest.mark.asyncio
async def test_db_row_overrides_constant(db_session):
    """DB 有 unified/system 行时，解析结果用 DB 模板而非代码常量。"""
    db_session.add(
        AgentPrompt(
            tenant_id=42,
            agent_id=UNIFIED_AGENT_ID,
            phase=UNIFIED_PHASE,
            template="自定义提示词：admin 在管理页改过的内容。",
        )
    )
    await db_session.commit()

    prompt = await _resolve_unified_system_prompt(db_session, tenant_id=42)

    assert prompt == "自定义提示词：admin 在管理页改过的内容。"
    assert prompt != SYSTEM_PROMPT_UNIFIED


@pytest.mark.asyncio
async def test_missing_row_falls_back_to_constant(db_session):
    """DB 无行（lazy seed 后）→ 回退/落库为代码常量。"""
    prompt = await _resolve_unified_system_prompt(db_session, tenant_id=99)

    assert prompt == SYSTEM_PROMPT_UNIFIED
    # 工具速查不再写死数字
    assert "55 个" not in prompt

    # lazy seed 应把 unified/system 行落进库（管理页首次加载即可见）
    from sqlalchemy import select

    row = (
        await db_session.execute(
            select(AgentPrompt).where(
                AgentPrompt.tenant_id == 99,
                AgentPrompt.agent_id == UNIFIED_AGENT_ID,
                AgentPrompt.phase == UNIFIED_PHASE,
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.template == SYSTEM_PROMPT_UNIFIED


@pytest.mark.asyncio
async def test_no_tenant_returns_constant():
    """tenant_id 缺失 → 直接回退代码常量，不碰 DB。"""
    db = MagicMock()  # 不应被使用
    prompt = await _resolve_unified_system_prompt(db, tenant_id=None)
    assert prompt == SYSTEM_PROMPT_UNIFIED


@pytest.mark.asyncio
async def test_db_error_falls_back_to_constant():
    """DB 查询抛异常 → 兜底回退代码常量，不让 prompt 解析挂掉主链路。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    prompt = await _resolve_unified_system_prompt(db, tenant_id=7)
    assert prompt == SYSTEM_PROMPT_UNIFIED
