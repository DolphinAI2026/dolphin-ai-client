"""Agent 架构相关数据模型。

仅剩 1 张活跃表（2026-06-14: 删 brainstorm_sessions/specs/coding_sessions/
agent_traces/agent_error_events 五张死表 —— 随 v2 orchestrator 死栈退役、全仓零
读写、FK 链已无活跃引用）：
- conversation_events  SSE 事件缓存（支持断线重连，活跃，db_publisher 写入）

id 字段使用 String(64)，存 ULID/UUID hex。JSON 字段同时兼容 SQLite 和 MySQL。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ══════════════════════════════════════════════════════════════
# conversation_events — SSE 事件缓存
# ══════════════════════════════════════════════════════════════

class ConversationEvent(Base):
    """发送给前端的 SSE 事件缓存，支持断线重连补发。

    保留 7 天（超过删除）。
    """
    __tablename__ = "conversation_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True,
    )

    seq: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="conversation 内单调递增，用于断线重连的 last_seen_seq",
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_conv_events_conv_seq", "conversation_id", "seq"),
    )
