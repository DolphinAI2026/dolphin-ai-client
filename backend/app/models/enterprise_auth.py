from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EnterpriseAuthAccount(Base):
    __tablename__ = "enterprise_auth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "base_url",
            "tenant_ref",
            "account",
            name="uq_enterprise_auth_account_identity",
        ),
        CheckConstraint(
            "provider IN ('apaas', 'control_plane')",
            name="ck_enterprise_auth_account_provider",
        ),
        CheckConstraint(
            "status IN ('unverified', 'connected', 'error', 'disabled')",
            name="ck_enterprise_auth_account_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    account: Mapped[str] = mapped_column(String(128), nullable=False)
    password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    access_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="unverified",
        server_default="unverified",
        nullable=False,
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class EnterpriseAuthBinding(Base):
    __tablename__ = "enterprise_auth_bindings"
    __table_args__ = (
        UniqueConstraint(
            "left_account_id",
            "right_account_id",
            name="uq_enterprise_auth_binding_pair",
        ),
        CheckConstraint(
            "left_account_id < right_account_id",
            name="ck_enterprise_auth_binding_canonical_order",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    left_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("enterprise_auth_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    right_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("enterprise_auth_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100", nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
