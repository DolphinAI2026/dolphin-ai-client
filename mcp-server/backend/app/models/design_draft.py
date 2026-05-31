"""DesignDraft 模型 — 应用设计草稿持久化层。

设计原则：
- 单表存所有信息（md_content + spec_json + 应用绑定 + patch 链）
- patch 不可变：每次 patch 生成新 draft 行，parent_draft_id 串成版本链
- promote/apply 之后写回 app_id/apaas_app_id，方便从 draft 反查应用
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Index
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

BigText = Text().with_variant(LONGTEXT, "mysql")


class DesignDraft(Base):
    __tablename__ = "design_drafts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "d_xxxxxx" 格式
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # ─── 内容 ────────────────────────────────────────────────────
    md_content: Mapped[str] = mapped_column(BigText, nullable=False)        # 完整 markdown
    spec_json: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)  # 解析后 JSON
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 一行摘要

    # ─── 校验状态 ────────────────────────────────────────────────
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    # standard / partial / freeform
    warnings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    errors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ─── 版本链（patch 不可变） ───────────────────────────────────
    parent_draft_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    patch_action_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 从 parent 到自己的 patch
    summary_of_change: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ─── 应用绑定（promote/apply 之后回填） ────────────────────────
    app_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    apaas_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    env: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    admin_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    web_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ─── 状态 ────────────────────────────────────────────────────
    # active     刚建/最新版，未上线
    # promoted   已通过 promote 创建成新应用
    # applied    已通过 apply 同步到既有应用
    # superseded 被新版 patch 取代
    # failed     promote/apply 失败
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ─── 审计 ────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_draft_tenant_user", "tenant_id", "user_id"),
        Index("idx_draft_app", "app_id"),
    )
