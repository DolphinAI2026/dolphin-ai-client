"""Industry knowledge-base models — packs (system-wide) + per-tenant installs.

`IndustryPack` is system-wide (one row per shipped pack, e.g. 制造装备 / 客户运营).
`IndustryPackInstall` tracks per-tenant install state — flipping `installed=true` in
the /industry list response is a join against this table.

Seed data (4 default packs + manufacturing ontology) lives in
`app.services.industry_seed`; lazy-seeded on first /industry/packs call.
"""
from __future__ import annotations

from datetime import datetime

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


class IndustryPack(Base):
    """Industry pack metadata. Shared across all tenants (system table)."""

    __tablename__ = "industry_packs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 'pkg-mfg' etc.
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tone: Mapped[str] = mapped_column(String(16), default="brand", nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    maintainer: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    updated: Mapped[str] = mapped_column(String(16), default="", nullable=False)  # "5/14" display

    # Counters
    entities_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relations_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    workflows_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dicts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    forms_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    roles_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Ontology JSON (entities + relations + workflows + dictHighlight)
    ontology: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # Adopted apps (denormalized JSON list of names)
    adopted: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class IndustryPackInstall(Base):
    """Per-tenant install state for a pack."""

    __tablename__ = "industry_pack_installs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "pack_id", name="uq_tenant_pack"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pack_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("industry_packs.id"), nullable=False
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
