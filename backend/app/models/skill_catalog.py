"""V2 Agent skill catalog — master list of callable skills agents can bind to."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AgentSkillCatalog(Base):
    """One row per real skill function in app/skills/.

    Lazy-discovered: scans the package on first /api/skills/catalog hit and
    inserts new rows. Existing rows aren't overwritten — admins can edit
    name/desc/category via UI later without losing customizations.
    """
    __tablename__ = "agent_skill_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    desc: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="general")  # platform / component / orchestrator / general
    callable_path: Mapped[str] = mapped_column(String(256), nullable=False)  # e.g. 'app.skills.platform:create_app'
    params_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # inferred from signature
    is_async: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
