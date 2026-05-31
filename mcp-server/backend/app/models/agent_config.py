# backend/app/models/agent_config.py
"""V2 Agent Config — Builder / Coding / Vibe agent configurations.

Each tenant has 3 default agents seeded on first read. Each agent has:
- model + system prompt + context window + max output (basic config)
- skills (many-to-many via agent_skill_bindings)
- MCP servers (many-to-many via agent_mcp_bindings)
- knowledge sources (industry packs + spec templates, via agent_knowledge_bindings)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentConfig(Base):
    """One row per (tenant_id, agent_id) — agent_id is 'builder' / 'whale' / 'vibe'."""
    __tablename__ = "agent_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_id", name="uq_tenant_agent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # 'builder' / 'whale' / 'vibe'

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    desc: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(16), default="brand")  # 'ai' / 'brand' / 'emerald'
    icon: Mapped[str] = mapped_column(String(32), default="chat")

    model: Mapped[str] = mapped_column(String(64), nullable=False)
    model_options: Mapped[list[str]] = mapped_column(JSON, default=list)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    context_window: Mapped[int] = mapped_column(Integer, default=200000)
    max_output: Mapped[int] = mapped_column(Integer, default=8192)

    # Stats (denormalized for fast read)
    active_calls: Mapped[int] = mapped_column(Integer, default=0)
    today_calls: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentSkill(Base):
    """Skills attached to an agent. Code/name/desc denormalized so we don't need a separate skill catalog table at first."""
    __tablename__ = "agent_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_config_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    desc: Mapped[str] = mapped_column(Text, default="")
    order_idx: Mapped[int] = mapped_column(Integer, default=0)


class AgentMcpBinding(Base):
    """MCP servers attached to an agent. mcp_id references mcp_servers table (or the in-memory registry today)."""
    __tablename__ = "agent_mcp_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_config_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    mcp_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_idx: Mapped[int] = mapped_column(Integer, default=0)


class AgentKnowledgeBinding(Base):
    """Knowledge sources: industry packs + spec templates."""
    __tablename__ = "agent_knowledge_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_config_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # 'industry_pack' / 'spec_template'
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_idx: Mapped[int] = mapped_column(Integer, default=0)
