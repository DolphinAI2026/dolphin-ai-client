from __future__ import annotations
from typing import List, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime


# Auth schemas
class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    tenant_role: Optional[str] = None
    org_permissions: Optional[dict] = None


class TenantOption(BaseModel):
    """租户选项（多租户登录时返回）"""
    tenant_id: int
    tenant_name: str
    tenant_code: str


class LoginResponse(BaseModel):
    """登录响应（支持多租户）"""
    access_token: Optional[str] = None
    token_type: str = "bearer"
    requires_tenant_selection: bool = False
    selection_token: Optional[str] = None
    tenants: Optional[list[TenantOption]] = None


class TenantSelectRequest(BaseModel):
    """租户选择请求"""
    selection_token: str
    tenant_id: int


# Conversation schemas
class ConversationCreate(BaseModel):
    agent_type: str = Field(..., pattern="^(builder|assistant|developer|requirements|coding)$")
    selected_llm_config_id: Optional[int] = None
    initial_message: Optional[str] = None
    spec_id: Optional[str] = None


class ConversationResponse(BaseModel):
    id: int
    title: str
    agent_type: str
    status: str
    selected_llm_config_id: Optional[int] = None
    spec_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# Message schemas


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


# Application schemas
class ApplicationCreate(BaseModel):
    conversation_id: Optional[int] = None
    project_id: Optional[int] = None
    app_name: str
    app_code: str
    description: Optional[str] = None
    config_preview: Optional[dict] = None
    canonical_spec_id: Optional[str] = None
    platform_env_id: Optional[int] = None
    # 平台环境配置（可选）
    platform_url: Optional[str] = None
    platform_tenant_id: Optional[str] = None


class ApplicationResponse(BaseModel):
    id: int
    app_name: str
    app_code: str
    icon_svg: Optional[str] = None
    description: Optional[str]
    status: str
    conversation_id: Optional[int] = None
    platform_env_id: Optional[int] = None
    canonical_spec_id: Optional[str] = None
    apaas_app_id: Optional[str] = None
    apaas_url: Optional[str] = None
    config_preview: Optional[dict] = None
    models: int = 0
    forms: int = 0
    roles: int = 0
    dicts: int = 0
    # Phase C：project & git
    project_id: Optional[int] = None
    git_repo_url: Optional[str] = None
    git_provider: Optional[str] = None
    git_default_branch: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    permissions: Optional[dict] = None  # {edit: bool, delete: bool, clone: bool}


class MergedAppResponse(BaseModel):
    """合并后的应用响应（本地 + 得帆云平台）"""
    id: str                                # 本地 id 或 "remote_{apaas_id}"
    app_name: str
    app_code: Optional[str] = None
    icon_svg: Optional[str] = None
    description: Optional[str] = None
    source: str                            # "local" | "remote" | "linked"
    status: str                            # 统一展示状态
    local_status: Optional[str] = None
    remote_status: Optional[str] = None
    apaas_app_id: Optional[str] = None
    apaas_url: Optional[str] = None        # 平台直达链接
    conversation_id: Optional[int] = None  # 关联的对话ID，用于"继续完善"
    canonical_spec_id: Optional[str] = None
    models: int = 0
    forms: int = 0
    roles: int = 0
    dicts: int = 0
    config_preview: Optional[dict] = None
    permissions: Optional[dict] = None
    env_name: Optional[str] = None          # 关联平台环境名称
    env_status: Optional[str] = None        # 关联平台环境连接状态
    # Phase C：project & git
    project_id: Optional[int] = None
    git_repo_url: Optional[str] = None
    git_provider: Optional[str] = None
    git_default_branch: Optional[str] = None
    # 应用类型: low-code (ai-builder/SPEC) | ai-code (vibe-coding)
    app_type: str = "low-code"
    source_workspace_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApplicationListCounts(BaseModel):
    all: int = 0
    active: int = 0
    deployed: int = 0
    draft: int = 0


class ApplicationPageResponse(BaseModel):
    items: List[MergedAppResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    counts: ApplicationListCounts


# Chat schemas
class ChatRequest(BaseModel):
    conversation_id: int
    message: str
    current_config: Optional[dict] = None
    # Phase B: ChatPage 显式传 application_id 时，触发首次编辑前的 fork canonical → personal draft
    application_id: Optional[int] = None
    # 从已落库但未收到助手回复的最后一条用户消息恢复，不重复保存用户消息
    resume_from_message_id: Optional[int] = None


# Generation Step schemas (Copilot 模式)
class StepExecuteRequest(BaseModel):
    step: str  # e.g. "create_app", "create_model:0"


class StepResetRequest(BaseModel):
    step: Optional[str] = None  # None = reset all


class StepStatus(BaseModel):
    model_config = {"protected_namespaces": ()}

    key: str
    label: str
    status: str  # pending | completed | error
    deps_met: bool
    model_index: Optional[int] = None
    error: Optional[str] = None
    result: Optional[dict] = None


class GenerationStatusResponse(BaseModel):
    apaas_app_id: Optional[str] = None
    app_status: Optional[str] = None
    error_message: Optional[str] = None
    steps: List[StepStatus]


class ConflictInfo(BaseModel):
    """编码冲突详情"""
    conflict_type: str  # code_duplicate
    model_name: str  # 冲突的模型/字典/角色名称
    current_code: str  # 当前冲突的编码
    message: str  # 提示信息


class StepExecuteResponse(BaseModel):
    step: str
    status: str  # completed | error | conflict
    result: Optional[dict] = None
    error: Optional[str] = None
    conflict: Optional[ConflictInfo] = None


class ResolveConflictRequest(BaseModel):
    """编码冲突修复请求"""
    step: str  # e.g. "create_model:0"
    model_name: str  # 模型/字典/角色名称
    old_code: str  # 原编码
    new_code: str  # 新编码
