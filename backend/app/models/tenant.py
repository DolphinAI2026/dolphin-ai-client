"""Tenant, Role, and Team models for multi-tenancy support."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Tenant(Base):
    """租户表 — 顶层隔离单位"""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(32), default="free", nullable=False)  # free/pro/enterprise
    max_applications: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_workspaces: Mapped[int] = mapped_column(Integer, default=20, nullable=False)  # vibe-coding 工作区配额
    max_components: Mapped[int] = mapped_column(Integer, default=50, nullable=False)  # 自开发组件配额
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=active, 0=disabled
    contact_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # ai-builder 租户级身份对齐：一个本地租户可绑定唯一 aPaaS 平台环境。
    apaas_env_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("platform_envs.id", ondelete="SET NULL"), nullable=True,
        comment="ai-builder 租户唯一绑定的 apaas 平台环境 (PlatformEnv.id)",
    )
    apaas_tenant_id_str: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True, unique=True,
        comment="aPaaS 平台租户 ID；NULL=不强绑单一 apaas tenant",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UserTenant(Base):
    """用户-租户关系表 — N:M，支持多租户成员"""
    __tablename__ = "user_tenants"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=active, 0=disabled
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Role(Base):
    """角色表 — 租户隔离，定义组织级权限"""
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role_code", name="uq_tenant_role_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 系统角色不可删除
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Team(Base):
    """团队表 — 租户内的二级协作单位"""
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("tenant_id", "team_name", name="uq_team_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=active, 0=disabled
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TeamMember(Base):
    """团队成员表 — 三种角色：admin/member/viewer"""
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    team_role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)  # admin / member / viewer
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

