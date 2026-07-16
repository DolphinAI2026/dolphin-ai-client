"""AIChat 模块的数据模型 — 独立于现有 conversations / messages，避免污染老链路。

5 张表：
- ai_chat_sessions    会话
- ai_chat_messages    消息（user / assistant / system）
- ai_chat_tool_calls  工具调用记录（read_attachment / run_python / write_artifact / ask_user）
- ai_chat_attachments 用户上传的附件（含解析后的文本）
- ai_chat_artifacts   AI 产出物（md / json 等）
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, JSON, BigInteger, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# 支持 dev SQLite + prod MySQL：MySQL 用 LONGTEXT (4GB)，其他用 Text
BigText = Text().with_variant(LONGTEXT, "mysql")


class AIChatSession(Base):
    """AIChat 会话"""

    __tablename__ = "ai_chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话", nullable=False)
    # active / running / paused / completed / archived
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # 工作模式：'chat'（从零理需求）/ 'cowork'（批量材料整合）
    # 影响 agent.py 选用哪套 SYSTEM_PROMPT
    mode: Mapped[str] = mapped_column(String(20), default="chat", nullable=False)
    # 用户选择的 LLM 配置（拉自 llm_configs.options，purpose='all'）
    selected_llm_config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 应用上下文常驻锁：非空 = 锁定该内部 applications.id（app 配置/二次开发态）；
    # 空 = 自由态（/ai-chat 0-1 创建/通用）。不加 FK，沿用 ai_chat 解耦风格。
    app_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # Code 模式外部应用来源：d-ai-code Control Plane 的 applicationId。
    # 纯代码应用不在本项目 applications 表落本地项目，列表和 workspace/open 都以该 ID 对接。
    external_application_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    external_app_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    external_app_code: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # workspace 目录路径（per-session tmp 目录，用于 run_python 的 cwd + 附件存储）
    workspace_dir: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # 绑定工作区 ws_id（非路径，是 WorkspaceManager 的 ws_id）；Code 会话据此让引擎推导
    # ws-lock（SP2a：run_agent 无 override 时按 session.mode 推导 dev-apaas + 单工作区锁）。
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class CodeRuntimeBinding(Base):
    """Dolphin Code 会话到 d-ai-code runtime 的映射。"""

    __tablename__ = "code_runtime_bindings"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_code_runtime_bindings_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_application_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    runtime_base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    builder_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    sandbox_instance_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    runtime_session_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class CodeRuntimeAgentSession(Base):
    """External runtime session ownership for the outer Code rail.

    Local debug runtimes may reuse one runtime_base_url for multiple Code apps.
    This table lets the aPaaS shell remember which runtime sessions were created
    or activated from each app shell, so the outer rail does not mix histories.
    """

    __tablename__ = "code_runtime_agent_sessions"
    __table_args__ = (
        UniqueConstraint("session_id", "runtime_session_id", name="uq_code_runtime_agent_sessions_shell_runtime"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    app_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_application_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    sandbox_instance_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    runtime_session_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class AIChatMessage(Base):
    """会话消息"""

    __tablename__ = "ai_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # user / assistant / system
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(BigText, nullable=False, default="")
    # JSON: 关联的 attachment_ids / 当时的 thinking 等元信息
    extra_meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AIChatToolCall(Base):
    """工具调用记录 — 一条 assistant message 可能触发多次 tool_call"""

    __tablename__ = "ai_chat_tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_chat_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # LLM 返回的原始 tool_call id（OpenAI/Anthropic 的 "call_xyz"），跨轮重建
    # messages 时用来对齐 assistant.tool_calls 和 role:tool 的 tool_call_id
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    args_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_text: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    # pending / running / success / error / aborted
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AIChatAttachment(Base):
    """用户上传的附件 + 解析后的文本"""

    __tablename__ = "ai_chat_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # image / docx / pdf / xlsx / pptx / md / txt / other
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    mime: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # 文件存盘路径（在 session.workspace_dir 下）
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # 解析后的纯文本（图片为空，docx/pdf/xlsx/pptx 才有）
    content_text: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    # 仅图片：base64 data URL（让 vision LLM 直接看）
    image_data_url: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AIChatArtifact(Base):
    """AI 产出物（write_artifact 工具的产出，比如 md 设计文档）"""

    __tablename__ = "ai_chat_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # md / json / txt / html / py / 其他
    format: Mapped[str] = mapped_column(String(40), default="md", nullable=False)
    content: Mapped[str] = mapped_column(BigText, nullable=False, default="")
    # 当 AI 多次写同名 artifact 时，version+1，前端 UI 可以选择看历史
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 产物存储方式：text=用 content（默认，老产物不变）；file=二进制落盘
    storage: Mapped[str] = mapped_column(String(10), default="text", nullable=False)
    # storage=file 时指向 session.workspace_dir 下的文件
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
