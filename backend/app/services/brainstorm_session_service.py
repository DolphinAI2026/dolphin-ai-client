"""BrainstormSession 持久化 + suspend/resume 服务。

职责：
- 创建 / 更新 brainstorm_sessions 表记录
- suspend：把 agent snapshot 写 DB，状态改 suspended
- resume：从 DB 读 snapshot 并重建 BrainstormAgent 实例
- 超时识别：last_activity_at 距今 > 30 min 的 active 会话标为 suspended

表结构见 backend/app/models/agent_models.py 的 BrainstormSession 类。
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.brainstorm import BrainstormAgent
from app.agents.brainstorm.config import ABORT_AFTER_SUSPENDED_DAYS, SUSPEND_AFTER_IDLE_MINUTES
from app.agents.types import AgentContext
from app.models import agent_models

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 状态常量
# ══════════════════════════════════════════════════════════════

class BsStatus:
    ACTIVE = "active"
    PAUSED = "paused"         # ask_user 等用户答（内存内暂停）
    SUSPENDED = "suspended"   # HTTP 断开后落盘
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class BsTrigger:
    INITIAL = "initial"
    ITERATE_MINOR = "iterate_minor"
    ITERATE_MAJOR = "iterate_major"


def new_session_id() -> str:
    """生成 brainstorm_session id"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"bs_{ts}_{secrets.token_hex(3)}"


# ══════════════════════════════════════════════════════════════
# CRUD
# ══════════════════════════════════════════════════════════════

async def create_session(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    model_used: Optional[str] = None,
    trigger_type: str = BsTrigger.INITIAL,
    parent_spec_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> agent_models.BrainstormSession:
    """创建一个新的 brainstorm_sessions 记录（status=active）"""
    row = agent_models.BrainstormSession(
        id=session_id or new_session_id(),
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        status=BsStatus.ACTIVE,
        trigger_type=trigger_type,
        parent_spec_id=parent_spec_id,
        model_used=model_used,
        agent_snapshot=None,
    )
    db.add(row)
    await db.flush()
    return row


async def get_session(
    db: AsyncSession, session_id: str
) -> Optional[agent_models.BrainstormSession]:
    return (
        await db.execute(
            select(agent_models.BrainstormSession).where(
                agent_models.BrainstormSession.id == session_id
            )
        )
    ).scalar_one_or_none()


async def get_active_session_for_conversation(
    db: AsyncSession, conversation_id: int
) -> Optional[agent_models.BrainstormSession]:
    """找某 conversation 下最新的未终结 session（active / paused / suspended）"""
    stmt = (
        select(agent_models.BrainstormSession)
        .where(
            agent_models.BrainstormSession.conversation_id == conversation_id,
            agent_models.BrainstormSession.status.in_(
                [BsStatus.ACTIVE, BsStatus.PAUSED, BsStatus.SUSPENDED]
            ),
        )
        .order_by(agent_models.BrainstormSession.last_activity_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ══════════════════════════════════════════════════════════════
# Snapshot / Suspend / Resume
# ══════════════════════════════════════════════════════════════

async def suspend_session(
    db: AsyncSession,
    *,
    session_id: str,
    agent: BrainstormAgent,
    reason: str = "http_disconnect",
) -> agent_models.BrainstormSession:
    """把 agent 当前状态序列化并落 DB，状态改 suspended"""
    snapshot = agent.to_snapshot()
    row = await get_session(db, session_id)
    if not row:
        raise ValueError(f"brainstorm_session {session_id} not found")

    row.agent_snapshot = snapshot
    row.status = BsStatus.SUSPENDED
    row.last_activity_at = datetime.utcnow()
    if row.scene_type is None and snapshot.get("custom", {}).get("brainstorm_state", {}).get("scene_type"):
        row.scene_type = snapshot["custom"]["brainstorm_state"]["scene_type"]

    await db.flush()
    logger.info("brainstorm session %s suspended (reason=%s)", session_id, reason)
    return row


async def resume_session(
    db: AsyncSession,
    *,
    session_id: str,
    ctx: AgentContext,
    user_answer: Optional[str] = None,
) -> tuple[agent_models.BrainstormSession, BrainstormAgent]:
    """从 DB 读 snapshot 恢复一个 BrainstormAgent 实例。

    Args:
        user_answer: 若非空，把它作为"上一轮 ask_user 工具的 tool_result"注入到
                     agent._messages 里，让 LLM 看到用户的回答（见架构文档 § 5.5 第 5 步）。
                     调用 agent.run() 时它会从这个历史上下文继续推理，不会重头跑。

    调用方需要保证 ctx 字段与原 session 匹配（session_id / conversation_id / user_id / tenant_id）。
    """
    row = await get_session(db, session_id)
    if not row:
        raise ValueError(f"brainstorm_session {session_id} not found")
    if row.status in (BsStatus.COMPLETED, BsStatus.ABORTED, BsStatus.FAILED):
        raise ValueError(f"session {session_id} already terminal ({row.status})")

    snap = row.agent_snapshot or {}
    # 构造 agent（from_snapshot 会调 _deserialize_custom_state 恢复业务态）
    agent = BrainstormAgent.from_snapshot(ctx, snap)

    # 注入用户答案为 tool_result
    if user_answer:
        _inject_user_answer_as_tool_result(agent, user_answer)

    row.status = BsStatus.ACTIVE
    row.last_activity_at = datetime.utcnow()
    await db.flush()
    return row, agent


def _inject_user_answer_as_tool_result(agent: BrainstormAgent, user_answer: str) -> None:
    """把用户答案追加为 ask_user 的 tool_result 到 agent._messages 里。

    查找规则：从 _messages 末尾向前找最后一条 role=assistant 且带 tool_calls 的消息，
    取它最后一个 tool_call（通常是 ask_user）的 id，append 对应 role=tool 的消息。

    同时：若该 ask_user 调用的 arguments 里带了 p1_key，把它同步回写到
    agent.state（state.mark_p1_answered），让 p1_coverage / confidence 能推进。
    这是真实 pause/resume 路径下 P1 答案落地的唯一入口——ask_user tool 本身
    在 should_pause=True 分支不会执行到 mark_p1_answered（它在同步注入分支里）。

    若找不到匹配（例如 snapshot 结构异常），则以 role=user 的文本消息形式追加兜底，
    避免让 LLM 看到孤悬的 assistant.tool_calls 而报错。
    """
    import json

    messages = agent._messages  # type: ignore[attr-defined]
    target_tool_call_id: Optional[str] = None
    target_tool_name: Optional[str] = None
    target_p1_key: Optional[str] = None
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            continue
        last_tc = tool_calls[-1]
        target_tool_call_id = last_tc.get("id")
        fn = last_tc.get("function") or {}
        target_tool_name = fn.get("name")
        raw_args = fn.get("arguments")
        parsed_args: dict[str, Any] = {}
        if isinstance(raw_args, dict):
            parsed_args = raw_args
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed_args = json.loads(raw_args)
            except Exception:
                parsed_args = {}
        p1_raw = parsed_args.get("p1_key") if isinstance(parsed_args, dict) else None
        if isinstance(p1_raw, str) and p1_raw.strip():
            target_p1_key = p1_raw.strip()
        break

    if target_tool_call_id:
        # 用 OpenAI function-calling 的 tool 消息格式追加
        content = f"[USER ANSWER] {user_answer}"
        if target_tool_name and target_tool_name != "ask_user":
            # 不是预期的 ask_user，仍注入但标注（防止误判）
            content = f"[USER ANSWER for {target_tool_name}] {user_answer}"
        messages.append({
            "role": "tool",
            "tool_call_id": target_tool_call_id,
            "content": content,
        })
        if target_tool_name == "ask_user" and target_p1_key:
            hit = agent.state.mark_p1_answered(target_p1_key, user_answer)
            if hit:
                logger.info(
                    "resume_session: marked P1 '%s' answered (p1_coverage=%.2f)",
                    target_p1_key,
                    agent.state.p1_coverage(),
                )
            else:
                logger.warning(
                    "resume_session: p1_key '%s' not found in state.p1_questions",
                    target_p1_key,
                )
        logger.info(
            "resume_session: injected user answer as tool_result for tool_call_id=%s",
            target_tool_call_id,
        )
    else:
        # 兜底：作为额外 user message 追加（不常见场景）
        messages.append({
            "role": "user",
            "content": f"[补充] {user_answer}",
        })
        logger.warning(
            "resume_session: no pending tool_call found, appended as user message fallback",
        )


async def mark_session_completed(
    db: AsyncSession,
    *,
    session_id: str,
    final_spec_id: Optional[str] = None,
) -> agent_models.BrainstormSession:
    row = await get_session(db, session_id)
    if not row:
        raise ValueError(f"brainstorm_session {session_id} not found")
    row.status = BsStatus.COMPLETED
    row.final_spec_id = final_spec_id
    row.ended_at = datetime.utcnow()
    row.last_activity_at = row.ended_at
    await db.flush()
    return row


async def mark_session_failed(
    db: AsyncSession,
    *,
    session_id: str,
    error_message: str,
) -> agent_models.BrainstormSession:
    row = await get_session(db, session_id)
    if not row:
        raise ValueError(f"brainstorm_session {session_id} not found")
    row.status = BsStatus.FAILED
    row.error_message = error_message
    row.ended_at = datetime.utcnow()
    row.last_activity_at = row.ended_at
    await db.flush()
    return row


# ══════════════════════════════════════════════════════════════
# Timeout 扫描（架构文档 § 6.7）
# ══════════════════════════════════════════════════════════════

async def suspend_idle_sessions(
    db: AsyncSession,
    *,
    idle_minutes: int = SUSPEND_AFTER_IDLE_MINUTES,
) -> int:
    """扫描 active 状态下闲置超过阈值的 session，自动改 suspended。

    注意：本函数仅改数据库状态，不持久化 agent snapshot
    （因为此时 agent 对象已不在内存 — 通常是 HTTP 连接已断）。
    返回被处理的行数。
    """
    cutoff = datetime.utcnow() - timedelta(minutes=idle_minutes)
    stmt = (
        update(agent_models.BrainstormSession)
        .where(
            agent_models.BrainstormSession.status == BsStatus.ACTIVE,
            agent_models.BrainstormSession.last_activity_at < cutoff,
        )
        .values(status=BsStatus.SUSPENDED)
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


async def abort_stale_sessions(
    db: AsyncSession,
    *,
    stale_days: int = ABORT_AFTER_SUSPENDED_DAYS,
) -> int:
    """扫描 suspended 状态下超过阈值的 session，标为 aborted。"""
    cutoff = datetime.utcnow() - timedelta(days=stale_days)
    stmt = (
        update(agent_models.BrainstormSession)
        .where(
            agent_models.BrainstormSession.status == BsStatus.SUSPENDED,
            agent_models.BrainstormSession.last_activity_at < cutoff,
        )
        .values(
            status=BsStatus.ABORTED,
            ended_at=datetime.utcnow(),
            error_message="session auto-aborted after long suspension",
        )
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


# ══════════════════════════════════════════════════════════════
# 状态辅助
# ══════════════════════════════════════════════════════════════

async def touch_activity(db: AsyncSession, session_id: str) -> None:
    """更新 last_activity_at。轻量级，每次用户交互调一次即可。"""
    stmt = (
        update(agent_models.BrainstormSession)
        .where(agent_models.BrainstormSession.id == session_id)
        .values(last_activity_at=datetime.utcnow())
    )
    await db.execute(stmt)
