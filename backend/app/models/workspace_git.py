from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkspaceGitRemote(Base):
    """代码会话工作区 ↔ git 远程仓绑定(模型 B,工作区级)。凭证引用 GitConnection。"""

    __tablename__ = "workspace_git_remote"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    ws_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # github / gitlab
    remote_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )
    git_connection_id: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # → git_connections.id(复用加密 PAT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
