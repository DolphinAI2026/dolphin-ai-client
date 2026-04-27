"""Orchestrator —— 用户消息路由 + Phase 转移 + Agent 生命周期。

职责（架构文档 § 2.3）：
1. 接收用户消息 → 根据 conversation.coding_phase 决定交给哪个 agent
2. 维护 phase 转移 + 持久化到 conversations.coding_phase
3. 创建 / 挂载 / suspend brainstorm 和 coding session
4. 把 agent 事件转发给 EventPublisher（前端 SSE）

本文件只提供协调逻辑；真实驱动（流式迭代 agent）放在调用方（routes/coding.py 或
tests）。这样 orchestrator 仍可单元测试，无需起 LLM。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.types import AgentContext
from app.models import Conversation, agent_models
from app.orchestrator.phases import (
    Phase,
    PhaseTransitionError,
    assert_transition,
    can_transition,
    parse_phase,
)
from app.services import brainstorm_session_service as bs_svc

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Phase 转移
# ══════════════════════════════════════════════════════════════

async def get_phase(db: AsyncSession, conversation_id: int) -> Phase:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError(f"conversation {conversation_id} not found")
    return parse_phase(conv.coding_phase)


async def transition_phase(
    db: AsyncSession,
    *,
    conversation_id: int,
    to: Phase,
    strict: bool = True,
) -> Phase:
    """把 conversation 的 phase 推进到 `to`。

    strict=True：违反状态机时 raise PhaseTransitionError
    strict=False：仅记 warning（供异常恢复场景用）
    """
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError(f"conversation {conversation_id} not found")
    current = parse_phase(conv.coding_phase)
    if current == to:
        return current  # 同 phase 自循环，无需记录
    if not can_transition(current, to):
        if strict:
            assert_transition(current, to)
        else:
            logger.warning(
                "非法 phase 转移（strict=False，仍执行）：%s → %s (conversation=%s)",
                current.value, to.value, conversation_id,
            )
    conv.coding_phase = to.value
    await db.flush()
    logger.info("phase transition: %s → %s (conv=%s)", current.value, to.value, conversation_id)
    return to


async def reset_phase(db: AsyncSession, conversation_id: int) -> None:
    """把 phase 清回 IDLE（谨慎使用，主要给测试 / 强制重启场景）"""
    stmt = (
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(coding_phase=Phase.IDLE.value)
    )
    await db.execute(stmt)


# ══════════════════════════════════════════════════════════════
# Brainstorm session 关联
# ══════════════════════════════════════════════════════════════

async def _load_conv(db: AsyncSession, conversation_id: int) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError(f"conversation {conversation_id} not found")
    return conv


async def attach_brainstorm_session(
    db: AsyncSession,
    *,
    conversation_id: int,
    brainstorm_session_id: str,
) -> None:
    """把 brainstorm_session_id 挂到 conversation 上（便于 resume 时查找）"""
    conv = await _load_conv(db, conversation_id)
    conv.coding_active_brainstorm_session_id = brainstorm_session_id
    await db.flush()


async def detach_brainstorm_session(
    db: AsyncSession,
    *,
    conversation_id: int,
) -> None:
    conv = await _load_conv(db, conversation_id)
    conv.coding_active_brainstorm_session_id = None
    await db.flush()


async def attach_coding_session(
    db: AsyncSession,
    *,
    conversation_id: int,
    coding_session_id: str,
) -> None:
    conv = await _load_conv(db, conversation_id)
    conv.coding_active_coding_session_id = coding_session_id
    await db.flush()


async def detach_coding_session(db: AsyncSession, *, conversation_id: int) -> None:
    conv = await _load_conv(db, conversation_id)
    conv.coding_active_coding_session_id = None
    await db.flush()


# ══════════════════════════════════════════════════════════════
# 入口：路由一次用户消息
# ══════════════════════════════════════════════════════════════

class RouteDecision:
    """根据当前 phase 和消息决定下一步动作"""

    __slots__ = ("action", "phase", "session_id", "reason", "extra")

    def __init__(
        self,
        action: str,
        phase: Phase,
        *,
        session_id: Optional[str] = None,
        reason: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        self.action = action    # start_brainstorm / resume_brainstorm / confirm_spec /
                                # start_coding / iterate / reject_message / resume_coding
        self.phase = phase
        self.session_id = session_id
        self.reason = reason
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "phase": self.phase.value,
            "session_id": self.session_id,
            "reason": self.reason,
            "extra": self.extra,
        }


async def route_user_message(
    db: AsyncSession,
    *,
    conversation_id: int,
) -> RouteDecision:
    """读当前 phase 决定用户新消息应该触发什么动作。

    不实际启动 agent（调用方负责），只返回决策 + phase。
    """
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError(f"conversation {conversation_id} not found")
    phase = parse_phase(conv.coding_phase)

    # —— IDLE：首轮 —— #
    if phase == Phase.IDLE:
        return RouteDecision(
            action="start_brainstorm",
            phase=phase,
            reason="首轮对话，启动 BrainstormAgent 反问 + 产出 Spec",
        )

    # —— UNDERSTAND：复用现有 brainstorm session —— #
    if phase == Phase.UNDERSTAND:
        bs = await bs_svc.get_active_session_for_conversation(db, conversation_id)
        if bs is None:
            return RouteDecision(
                action="start_brainstorm",
                phase=phase,
                reason="UNDERSTAND phase 但无活跃 brainstorm，启动新 session",
            )
        action = "resume_brainstorm" if bs.status == bs_svc.BsStatus.SUSPENDED else "continue_brainstorm"
        return RouteDecision(
            action=action,
            phase=phase,
            session_id=bs.id,
            reason=f"UNDERSTAND phase，{action} session={bs.id}",
        )

    # —— CONFIRM：等用户确认 —— #
    if phase == Phase.CONFIRM:
        # 用户发消息而非按确认按钮 → 视为反问追问，回到 UNDERSTAND
        bs = await bs_svc.get_active_session_for_conversation(db, conversation_id)
        return RouteDecision(
            action="refine_brainstorm",
            phase=phase,
            session_id=bs.id if bs else None,
            reason="CONFIRM phase 收到文本消息，视为不满意反馈，回到 UNDERSTAND 再反问",
        )

    # —— GENERATE / SCAFFOLD / VERIFY：agent 运行中 —— #
    if phase in (Phase.SCAFFOLD, Phase.GENERATE, Phase.VERIFY):
        return RouteDecision(
            action="reject_message",
            phase=phase,
            reason=f"{phase.value} 运行中，用户消息暂时不接收（可选：记录待命令）",
        )

    # —— DONE：迭代 —— #
    if phase == Phase.DONE:
        return RouteDecision(
            action="iterate",
            phase=phase,
            reason="DONE 状态收到新消息，进入 ITERATE 分级判定（trivial/minor/major）",
        )

    # —— FAILED / ABORTED —— #
    if phase in (Phase.FAILED, Phase.ABORTED):
        return RouteDecision(
            action="restart",
            phase=phase,
            reason=f"{phase.value} 状态收到消息，需要用户明确重启",
        )

    # 未知 phase 兜底
    return RouteDecision(
        action="reject_message",
        phase=phase,
        reason=f"未知 phase={phase.value}",
    )


# ══════════════════════════════════════════════════════════════
# 高级编排 — 结合 DB + service 的一体化动作
# ══════════════════════════════════════════════════════════════

async def start_brainstorm(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    model: str,
    trigger_type: str = bs_svc.BsTrigger.INITIAL,
    parent_spec_id: Optional[str] = None,
) -> agent_models.BrainstormSession:
    """创建 brainstorm session + 转 phase=UNDERSTAND + 绑到 conversation。

    返回 brainstorm_sessions 行；调用方负责构造 BrainstormAgent 并驱动。
    """
    bs_row = await bs_svc.create_session(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_used=model,
        trigger_type=trigger_type,
        parent_spec_id=parent_spec_id,
    )
    await attach_brainstorm_session(db, conversation_id=conversation_id, brainstorm_session_id=bs_row.id)
    await transition_phase(db, conversation_id=conversation_id, to=Phase.UNDERSTAND)
    return bs_row


async def on_brainstorm_emit(
    db: AsyncSession,
    *,
    conversation_id: int,
    brainstorm_session_id: str,
    spec_id: str,
) -> None:
    """BrainstormAgent 成功 emit Spec → phase UNDERSTAND → CONFIRM。

    final_spec_id 暂不写（等用户 /confirm API 才确认）；这里只是把 phase 切过去，
    同时把 brainstorm session 保持 active（用户可能 refine）。
    """
    await transition_phase(db, conversation_id=conversation_id, to=Phase.CONFIRM)


async def on_spec_confirmed(
    db: AsyncSession,
    *,
    conversation_id: int,
    spec_id: str,
    need_scaffold: bool,
) -> None:
    """用户确认 Spec 后（/api/spec/{id}/confirm 调用此函数）。

    need_scaffold=True（首轮 / 无 workspace）→ phase = SCAFFOLD
    need_scaffold=False（迭代）→ phase = GENERATE
    """
    target = Phase.SCAFFOLD if need_scaffold else Phase.GENERATE
    await transition_phase(db, conversation_id=conversation_id, to=target)


async def on_scaffold_done(db: AsyncSession, *, conversation_id: int) -> None:
    """工作区创建完成 → phase SCAFFOLD → GENERATE"""
    await transition_phase(db, conversation_id=conversation_id, to=Phase.GENERATE)


async def on_coding_complete_start_verify(db: AsyncSession, *, conversation_id: int) -> None:
    """coding 完成，进入 AC 验收（autofix 闭环） GENERATE → VERIFY"""
    await transition_phase(db, conversation_id=conversation_id, to=Phase.VERIFY)


async def on_verify_retry(db: AsyncSession, *, conversation_id: int) -> None:
    """AC 验收失败，重跑 coding（autofix 闭环重试） VERIFY → GENERATE"""
    await transition_phase(db, conversation_id=conversation_id, to=Phase.GENERATE)


async def on_coding_done(db: AsyncSession, *, conversation_id: int) -> None:
    """CodingAgent 正常结束 → phase = DONE（MVP 跳过 VERIFY）"""
    current = await get_phase(db, conversation_id)
    if current == Phase.GENERATE:
        await transition_phase(db, conversation_id=conversation_id, to=Phase.DONE)
    elif current == Phase.VERIFY:
        await transition_phase(db, conversation_id=conversation_id, to=Phase.DONE)
    else:
        logger.warning(
            "on_coding_done 时 phase 非预期：%s (conv=%s)", current.value, conversation_id
        )


async def on_agent_failed(
    db: AsyncSession,
    *,
    conversation_id: int,
    error_message: str,
) -> None:
    """任一 agent 明确失败 → phase = FAILED"""
    await transition_phase(
        db, conversation_id=conversation_id, to=Phase.FAILED, strict=False
    )


async def on_user_cancel(db: AsyncSession, *, conversation_id: int) -> None:
    """用户主动取消（/api/conversation/{id}/cancel）"""
    await transition_phase(
        db, conversation_id=conversation_id, to=Phase.ABORTED, strict=False
    )
