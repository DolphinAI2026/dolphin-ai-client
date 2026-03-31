from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, JSON, func
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
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)  # builder/assistant/developer/requirements
    workspace_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # coding工作区ID
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active/completed/failed
    doc_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 需求分析生成的设计文档 JSON
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


class ConfigSnapshot(Base):
    """配置快照 — 每次 config_preview 变更时保存，用于版本回滚"""
    __tablename__ = "config_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON: 完整 config_preview 内容
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # "chat" | "document" | "sync" | "rollback" | "generation"
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 变更摘要
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformEnv(Base):
    """平台环境配置"""
    __tablename__ = "platform_envs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    env_name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_tenant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="disconnected", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)  # 过渡字段，兼容旧 Project
    platform_env_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("platform_envs.id"), nullable=True, index=True)

    # 平台环境配置（从 Project 合并过来）
    platform_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    platform_tenant_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    platform_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    platform_password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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


class LLMConfig(Base):
    """LLM 模型配置 — 管理员通过前台配置接入的大模型"""
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    config_name: Mapped[str] = mapped_column(String(100), nullable=False)  # "通义千问", "DeepSeek" 等
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # qwen, deepseek, minimax, openai, anthropic
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet 加密
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), default="all", nullable=False)  # builder, coding, all
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=8192, nullable=False)
    temperature: Mapped[float] = mapped_column(default=0.3, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ApiCallLog(Base):
    """平台 API 调用日志"""
    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    step_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # create_app, create_role:0, etc
    method: Mapped[str] = mapped_column(String(10), nullable=False)  # GET/POST
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    request_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON (truncated)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
