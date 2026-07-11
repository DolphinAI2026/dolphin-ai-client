from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, Index, JSON, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

# 存大 JSON / markdown 的列用 LONGTEXT（MySQL 4GB），SQLite 下等价于 TEXT。
# 直接 Text 在 MySQL 下是 TEXT（上限 64KB），大文档解析的 config/raw_content 会
# 溢出报 "Data too long for column" 500。本地 SQLite 不会暴露这个 bug。
BigText = Text().with_variant(LONGTEXT, "mysql")

# Import tenant models
from app.models.tenant import Tenant, UserTenant, Role, Team, TeamMember
from app.models.spec import Spec  # noqa: F401  — register ORM mapping
from app.models.preference import UserPreference  # noqa: F401  — register ORM mapping
from app.models.system_setting import SystemSetting  # noqa: F401  — register ORM mapping
from app.models.collaboration import (  # noqa: F401  — register ORM mapping
    ApplicationMember,
    ChangeProposal,
    ProposalReview,
    GitConnection,
    PlatformDriftLog,
)
# Import deploy history (DeployRecord) — 2026-05-24
from app.models.deploy_history import DeployRecord  # noqa: F401
# Import process definition (design-v4 H2) — 流程图 JSON 本地存档
from app.models.process_definition import ProcessDefinition  # noqa: F401
# Import spec applied version + spec document (Y SPEC 版本快照 + markdown 缓存)
from app.models.spec_applied_version import SpecAppliedVersion  # noqa: F401
from app.models.spec_document import SpecDocument  # noqa: F401
from app.models.spec_section import SpecSection  # noqa: F401  — design-v4 草稿层 SpecSection
from app.models.agent_observability import AgentRun, AgentStep  # noqa: F401  — Agent 可观测底座
from app.models.enterprise_auth import (  # noqa: F401
    EnterpriseAuthAccount,
    EnterpriseAuthBinding,
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", "account_source", name="uq_user_username_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    apaas_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    apaas_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    apaas_base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    apaas_tenant_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    coding_user_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    coding_base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    coding_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    coding_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 账号来源: 'apaas'(aPaaS 同步/默认) | 'desktop'(桌面产品账号) | 'coding'(Dolphin Code)。
    # 用于把桌面登录与 aPaaS 登录链路隔离, 避免 username 撞名被 aPaaS 抢先认证。
    account_source: Mapped[str] = mapped_column(String(20), default="apaas", nullable=False, server_default="apaas")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class APaaSPlatformCredential(Base):
    """aPaaS 平台级凭据，用于平台管理员长任务续 token。"""
    __tablename__ = "apaas_platform_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "base_url", "account", name="uq_apaas_platform_credential"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    account: Mapped[str] = mapped_column(String(100), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class APaaSUserCredential(Base):
    """aPaaS 租户用户凭据，按 user + tenant 保存，供长任务续 token。"""
    __tablename__ = "apaas_user_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "local_tenant_id", name="uq_apaas_user_credential"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    local_tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    apaas_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    apaas_tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    account: Mapped[str] = mapped_column(String(100), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    raw_content: Mapped[str] = mapped_column(BigText, nullable=False)
    structure_index: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)  # JSON 章节索引
    parsed_config: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)  # JSON 解析配置
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
    diff_summary: Mapped[str] = mapped_column(BigText, nullable=False)  # JSON {added, modified, removed}
    actions: Mapped[str] = mapped_column(BigText, nullable=False)  # JSON patch actions 数组
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
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)  # coding工作区ID
    selected_llm_config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active/completed/failed
    doc_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 需求分析生成的设计文档 JSON
    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 对话摘要（上下文压缩用）
    phase: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # gathering | refining（智能搭建用）
    current_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 服务端权威 config 状态
    # 智能开发 V2 架构 - agent 流水线状态（不复用 phase 字段避免与智能搭建冲突）
    coding_phase: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="understand / confirm / scaffold / generate / verify / done / iterate",
    )
    coding_active_brainstorm_session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    coding_active_coding_session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # AI Coding「在应用上定制」绑定的本地 Application.id —— 持久化绑定,刷新/侧栏点开后仍记得是哪个应用,
    # grounding/codegen 据此复用该应用的模型/菜单(不再因前端 ref 丢失而退回通用 SPEC)。
    coding_app_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 滑动窗口压缩态(messages+summary 的 JSON), coding agent 跨轮 from_snapshot 恢复用。
    coding_agent_state: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("builder_specs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user/assistant/system
    content: Mapped[str] = mapped_column(BigText, nullable=False)
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


class ProjectArtifactDependency(Base):
    """跨产物声明式依赖 — 一个产物暴露、另一个消费(workspace↔workspace, v1)"""
    __tablename__ = "project_artifact_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    from_ref: Mapped[str] = mapped_column(String(80), nullable=False)   # workspace:<id>
    to_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    expose_label: Mapped[str] = mapped_column(String(120), default="")
    consume_label: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketplaceComponent(Base):
    """组件市场 — 用户发布的可复用组件"""
    __tablename__ = "marketplace_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="form-component-dual")
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
    config_json: Mapped[str] = mapped_column(BigText, nullable=False)  # JSON: 完整 config_preview 内容
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # "chat" | "document" | "sync" | "rollback" | "generation"
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 变更摘要
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformEnv(Base):
    """平台环境配置"""
    __tablename__ = "platform_envs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    env_name: Mapped[str] = mapped_column(String(100), nullable=False)
    alias: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)
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
    # 应用对话调整迁到 ai_chat 引擎后绑定的 session id；由 chat-session/ensure 接口创建
    ai_chat_session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
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
    icon_svg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirement_doc: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)  # JSON
    config_preview: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)  # JSON
    generation_state: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)  # JSON - copilot 中间状态
    current_doc_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 当前文档版本号
    canonical_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("builder_specs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft/generating/updating/completed/failed
    default_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'simple' | 'pro' | None
    # Phase C 协作：git 镜像元数据
    git_repo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    git_provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'gitlab' | 'github'
    git_default_branch: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 应用类型: low-code (ai-builder/SPEC 生成) | ai-code (vibe-coding 全代码生成)
    # server_default 让加列时现有行自动填 low-code
    app_type: Mapped[str] = mapped_column(String(20), default="low-code", server_default="low-code", nullable=False)
    # ai-code 应用关联的 vibe coding workspace id（low-code 应用为空）
    source_workspace_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
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


class MCPCallLog(Base):
    """MCP 网关调用日志，用于平台管理页排查工具调用。"""
    __tablename__ = "mcp_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    service: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rpc_method: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tool: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    request_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    request_arguments: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    request_headers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_source: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    apaas_tenant_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    apaas_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    local_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    local_tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# AIChat 模块 — 注册 ORM mapping
from app.models.ai_chat import (  # noqa: E402, F401
    AIChatSession,
    AIChatMessage,
    AIChatToolCall,
    AIChatAttachment,
    AIChatArtifact,
    CodeRuntimeBinding,
    CodeRuntimeAgentSession,
)


from app.models.agent_prompt import AgentPrompt  # noqa: E402, F401  — agent prompt templates per-tenant per-phase
from app.models.config_assistant_skill import ConfigAssistantSkill  # noqa: E402, F401  — 配置助手自学习 skills
from app.models.knowledge_doc import KnowledgeDoc  # noqa: E402, F401  — 平台知识库(规范库)


class DbConnection(Base):
    """数据库连接 — platform_envs 的兄弟模型，托管租户外部 DB 凭据 (fernet 加密 password)。"""
    __tablename__ = "db_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # MYSQL / PostgreSQL / SQLServer / ORACLE / DAMENG / KingBase（与 quick_db 对齐）
    db_type: Mapped[str] = mapped_column(String(20), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    # `database` 是 SQL 保留字，列名加 _name 后缀；API 层 alias 回 `database`。
    database_name: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # fernet 加密
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # active / disconnected
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    table_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_db_conn_tenant_name"),
    )
from app.models.conversation_replay import ConversationReplay  # noqa: F401  — 会话富回放落库


class AppHealthSnapshot(Base):
    """应用体检快照 — 确定性体检引擎每次结果落库，支撑趋势/横比/diff。"""

    __tablename__ = "app_health_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id"), index=True, nullable=False)
    apaas_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    has_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    data_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)


class RegisteredWorkspace(Base):
    """桌面「打开本地文件夹」external 工作区注册表 (指针进 DB, 不写用户文件夹)。"""
    __tablename__ = "registered_workspaces"
    # abs_path VARCHAR(1000) utf8mb4 = 4000 字节,直接进唯一约束超 MySQL 索引上限 3072 字节
    # (本地 SQLite 无此限制,故只在 MySQL 上线时暴露)。改用带 mysql_length 前缀的唯一索引:
    # MySQL 只索引 abs_path 前 255 字符(255*4=1020<3072),SQLite 忽略 mysql_length 走全列。
    __table_args__ = (
        Index("uq_regws_tenant_path", "tenant_id", "abs_path", unique=True, mysql_length={"abs_path": 255}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ws_id: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    abs_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    workspace_type: Mapped[str] = mapped_column(String(40), nullable=False, default="external")
    apaas_app_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
