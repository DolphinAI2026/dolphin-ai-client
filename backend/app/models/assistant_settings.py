"""Tenant-scoped assistant integration settings."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AssistantSetting(Base):
    """External assistant integration config, currently Dolphin issue assistant."""

    __tablename__ = "assistant_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", name="uq_assistant_settings_tenant_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="dolphin")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    server_url: Mapped[str] = mapped_column(String(500), nullable=False, default="https://dolphin-trial.definesys.cn")
    agent_code: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    apaas_tenant_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    button_text: Mapped[str] = mapped_column(String(80), nullable=False, default="得小帆")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
