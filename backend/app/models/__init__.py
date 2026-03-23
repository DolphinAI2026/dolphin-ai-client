from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

# Import tenant models
from app.models.tenant import Tenant, UserTenant, Role, Team, TeamMember


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    apaas_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    apaas_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    apaas_base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    apaas_tenant_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class DocumentVersion(Base):
    """文档版本 — 跟踪上传的设计文档"""
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    structure_index: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 章节索引
    parsed_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 解析配置
    parent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 基于哪个版本修改的（版本链）
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ChangePlan(Base):
    """变更计划 — 文档版本间的增量变更"""
    __tablename__ = "change_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False)  # JSON {added, modified, removed}
    actions: Mapped[str] = mapped_column(Text, nullable=False)  # JSON patch actions 数组
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending/confirmed/completed/cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)  # builder/assistant/developer
    workspace_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # coding工作区ID
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active/completed/failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user/assistant/system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Project(Base):
    """项目 — 每个项目拥有独立的平台环境配置"""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    # Platform environment config (per-project)
    platform_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    platform_tenant_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    platform_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    platform_password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # base64 encoded
    platform_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform_app_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    platform_app_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ProjectMember(Base):
    """项目成员 — 团队协作"""
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # "owner", "admin", "member"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketplaceComponent(Base):
    """组件市场 — 用户发布的可复用组件"""
    __tablename__ = "marketplace_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="form-component")
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array of tags
    readme: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zip_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_workspace_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    apaas_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    app_name: Mapped[str] = mapped_column(String(100), nullable=False)
    app_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirement_doc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    config_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    generation_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON - copilot 中间状态
    current_doc_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 当前文档版本号
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft/generating/completed/failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
