from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Spec(Base):
    """Persisted SPEC document. Pydantic Spec object is serialized into `payload`."""
    __tablename__ = "specs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("applications.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("specs.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    phase: Mapped[str] = mapped_column(String(20), default="gathering")
    completeness_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    completeness_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
