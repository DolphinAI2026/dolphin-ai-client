"""平台知识库(规范库)文档 — wiki 式 markdown,渐进披露给 agent。

平台级单库:tenant_id 恒为 NULL(=全局),列预留供后续租户覆盖(C 方案),本期不写非 NULL。
只 status='published' 进 agent。
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

BigText = Text().with_variant(LONGTEXT, "mysql")


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="平台规范", index=True)
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body_md: Mapped[str] = mapped_column(BigText, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    # NULL=平台全局(本期恒 NULL);列预留,避免后续 MySQL ALTER(项目用 create_all 不改既有表)。
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
