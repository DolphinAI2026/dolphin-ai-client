"""Config Assistant 自学习 skill — 用户教 AI 干一类事，AI 把流程总结成
markdown 步骤存进来，下次同类指令自动 follow。

设计：
- app_id NULL = 全局 skill（适用所有应用）
- app_id 整数 = 仅当前应用 scope
- intent_keywords 用逗号分隔，AI 拼 system_prompt 时按关键词匹配相关 skills
- steps_md 是 AI 总结的具体步骤（markdown），同时也是它下次"读"的指南
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

BigText = Text().with_variant(LONGTEXT, "mysql")


class ConfigAssistantSkill(Base):
    __tablename__ = "config_assistant_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)  # NULL = 全局
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    intent_keywords: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    steps_md: Mapped[str] = mapped_column(BigText, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
