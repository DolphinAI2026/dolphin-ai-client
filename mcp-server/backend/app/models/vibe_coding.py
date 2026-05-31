"""Vibe Coding（全代码）模块的数据模型。

跟睿鲸 AI Coding（routes/coding.py + coding/vibe_agent.py）完全分开——
睿鲸是 aPaaS 自开发场景，Vibe Coding 是通用全代码 IDE + 对话开发。

4 张表：
- vibe_coding_threads             会话（1 workspace = 1 thread，多人共享）
- vibe_coding_messages            消息（user / assistant / system）
- vibe_coding_tool_calls          工具调用记录
- vibe_coding_workspace_members   workspace 多人协作成员

注意 workspace_id 是字符串（来自 online_coding 的 `oc_xxxx`），
不是外键 — OnlineCoding workspace 当前是文件系统态（_workspace_dir/.meta.json），
不在数据库里。后续如果迁库可以加 FK。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    DateTime,
    Integer,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


BigText = Text().with_variant(LONGTEXT, "mysql")


class VibeCodingThread(Base):
    """Vibe Coding 会话 — 1 workspace = 1 thread。"""

    __tablename__ = "vibe_coding_threads"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_vc_thread_workspace"),
        Index("idx_vc_thread_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(60), nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # 用户在 chat 顶部切换的模型；为 None 时走租户默认 (purpose='all')
    selected_llm_config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 当前 todo list（agent 用 todo_write 维护），存 JSON：[{id, content, status}]
    todos: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class VibeCodingMessage(Base):
    """会话消息。

    role:
      - user      : 用户消息（user_id 标识发送者，支持多人协作）
      - assistant : LLM 回复（extra_meta.tool_calls 存当轮发起的 tool_call 列表，跨轮重建用）
      - system    : 系统提示
    role:tool 不存 message 表，存到 vibe_coding_tool_calls.result_text，重建时合成。
    """

    __tablename__ = "vibe_coding_messages"
    __table_args__ = (Index("idx_vc_msg_thread_created", "thread_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vibe_coding_threads.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(BigText, nullable=False, default="")
    # 仅 role=user 时填写，记录是哪个 member 发的（多人协作场景）
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # JSON: assistant 时存 tool_calls 列表 [{id, name, arguments}]；其他场景存 thinking 等
    extra_meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class VibeCodingToolCall(Base):
    """工具调用记录 — 一条 assistant message 可能触发多次 tool_call（并行）。"""

    __tablename__ = "vibe_coding_tool_calls"
    __table_args__ = (
        Index("idx_vc_tc_thread", "thread_id"),
        Index("idx_vc_tc_provider_call", "provider_call_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vibe_coding_threads.id", ondelete="CASCADE"), nullable=False
    )
    # 关联到触发它的 assistant message
    message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vibe_coding_messages.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # OpenAI/Anthropic 返回的原始 tool_call id（"call_xyz"），跨轮对齐 tool_calls ↔ tool result
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    args_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_text: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    # pending / running / success / error / aborted
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class VibeCodingWorkspaceMember(Base):
    """Workspace 多人协作成员（workspace_id 引自 online_coding 的字符串 id）。"""

    __tablename__ = "vibe_coding_workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_vc_ws_member"),
        Index("idx_vc_ws_member_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(60), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # owner / contributor
    role: Mapped[str] = mapped_column(String(20), default="contributor", nullable=False)
    invited_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
