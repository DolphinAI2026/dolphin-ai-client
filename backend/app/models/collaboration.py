"""协作 Phase A — 5 张新表的 ORM models"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey, JSON, DateTime, Text, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApplicationMember(Base):
    """应用级外部协作者（在 Project member 之外的额外邀请）"""
    __tablename__ = "application_members"
    __table_args__ = (
        UniqueConstraint("application_id", "user_id", name="uq_app_member"),
        Index("idx_app_member_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="contributor", nullable=False)
    invited_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChangeProposal(Base):
    """变更提案（Phase B 起会写入数据，本 Phase 只建表）"""
    __tablename__ = "change_proposals"
    __table_args__ = (
        Index("idx_proposal_app_status", "application_id", "status"),
        Index("idx_proposal_draft", "draft_spec_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft_spec_id: Mapped[str] = mapped_column(String(40), ForeignKey("builder_specs.id"), nullable=False)
    base_canonical_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("builder_specs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    validation_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    apply_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    apply_log: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    git_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    git_pr_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ProposalReview(Base):
    """提案的多人评审记录"""
    __tablename__ = "proposal_reviews"
    __table_args__ = (Index("idx_review_proposal", "proposal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(40), ForeignKey("change_proposals.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GitConnection(Base):
    """项目级 git 平台凭证"""
    __tablename__ = "git_connections"
    __table_args__ = (UniqueConstraint("project_id", name="uq_git_conn_project"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_secret_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    group_id_or_org: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformDriftLog(Base):
    """漂移检测日志"""
    __tablename__ = "platform_drift_logs"
    __table_args__ = (Index("idx_drift_app", "application_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    git_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    builder_canonical_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_direction: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
