"""ConfigChat 模块的数据模型 — `/chat?app_id=X` 右侧 ConfigAssistantPanel 用的会话持久化。

2026-05-24 在 ConfigAssistantPanel 重构 (commit 8df3c83) 之后补的，目的是让用户对同一应用
反复调整的对话不再是 in-memory（刷新页面就丢）。学 super-agents-dev 的 ChatSession +
ChatSessionContent 双表模式：

- config_chat_sessions    会话主体（按 app_id 隔离）
- config_chat_messages    消息（role user/assistant + 富 metadata：tool_trace / change_plan / actions_summary）

设计沿用现有 ai_chat.py 的风格（BigText / cascade delete / index 命名等），独立于 ai_chat
和老 conversations / messages 表，避免污染其他链路。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# 跟 ai_chat.py 一致：MySQL 走 LONGTEXT (4GB)，其他 dialect (SQLite dev) 走 TEXT
BigText = Text().with_variant(LONGTEXT, "mysql")


class ConfigChatSession(Base):
    """ConfigChat 会话 — 对应 ConfigAssistantPanel 右侧的"一次对话"。

    按 (tenant_id, user_id, app_id) 隔离。同一用户在同一应用下可以有多个 session
    （不同主题或不同时段），通过左侧 SessionDrawer 切换。
    """

    __tablename__ = "config_chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    # 一次性迁到 ai_chat_sessions 后回写新 session id（幂等标记；非空=已迁）
    migrated_session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ConfigChatMessage(Base):
    """ConfigChat 消息 — 一条用户问 / 一条 AI 回。

    AI 那条会带 tool_trace_json / change_plan_json / actions_summary_json 三个富字段，
    让用户重新打开历史会话时能看到当时调用的工具痕迹 + 草拟的 ChangePlan + 变更摘要。
    """

    __tablename__ = "config_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("config_chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(BigText, nullable=False, default="")
    # AI 这条专属 — 工具调用痕迹（list of {tool_name, args, ok, summary, image_data_url?}）
    tool_trace_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # AI 这条专属 — 草拟的 ChangePlan JSON（None 表示本轮没产生 plan）
    change_plan_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # AI 这条专属 — 人话变更摘要列表（["人员档案: 电话 改为必填", ...]）
    actions_summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
