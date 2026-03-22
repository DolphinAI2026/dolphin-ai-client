from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey
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
    platform_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform_app_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


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
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft/generating/completed/failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
