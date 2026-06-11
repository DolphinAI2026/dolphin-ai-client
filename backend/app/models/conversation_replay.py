"""会话富回放落库 — 替代 .vscode/chat-replay.json 的"一工作区一文件"存储。

文件方案按 conversation_id 独占：同工作区第二个会话跑一轮, 第一个会话的富回放
就被覆盖(实测踩过)。这里按会话各存一行；文件仅保留给 IDE 扩展读。
stream_messages 直接存前端可渲染的回放消息数组(JSON 文本), 读写都过
routes/coding.py 的类型白名单规范化。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

BigText = Text().with_variant(LONGTEXT, "mysql")


class ConversationReplay(Base):
    """一个会话的富回放流(逻辑外键 conversation_id, 旁路表不加硬 FK)。"""

    __tablename__ = "conversation_replays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    stream_messages: Mapped[str] = mapped_column(BigText, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
