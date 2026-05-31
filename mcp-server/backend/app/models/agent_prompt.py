"""V2 Agent prompt storage — per-agent multi-phase prompt templates.

Allows the runtime agents (SpecAgent / vibe_agent.py) to read their system
prompts from DB instead of hardcoded Python constants, so admins can edit
agent behavior via /agents UI.

Each row is one prompt template for an (agent_id, phase) tuple. Phase enables
multi-stage prompts (e.g., Builder has gathering/drafting/refining phases each
with their own system prompt). For single-stage agents (Coding, Vibe), use
phase='default'.

Template variables (e.g., {spec_summary}) are filled at runtime via str.format
or jinja2 (jinja2 if any template uses {{ }} or {%; otherwise str.format).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

BigText = Text().with_variant(LONGTEXT, "mysql")


class AgentPrompt(Base):
    __tablename__ = "agent_prompts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "phase", name="uq_tenant_agent_phase"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # 'builder' / 'whale' / 'vibe'
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="default")  # 'gathering' / 'drafting' / 'refining' / 'default'
    template: Mapped[str] = mapped_column(BigText, nullable=False)  # Raw prompt body (may contain {var} placeholders)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Admin notes (why this prompt, when to use)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
