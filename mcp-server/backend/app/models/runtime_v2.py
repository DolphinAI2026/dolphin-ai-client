# backend/app/models/runtime_v2.py
"""V2 Runtime — pipeline runs + deployment history tables.

Backs the `/runtime` page's pipelines tab and deployment history tab. Both
tables are tenant-scoped and seeded lazily on first read via
`app.services.runtime_seed.seed_runtime_for_tenant`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PipelineRun(Base):
    """A single CI/CD run shown on the /runtime · 流水线 tab."""

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'run-1284'
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(128), default="")
    trigger: Mapped[str] = mapped_column(String(32), default="手动")  # '自动' / '手动' / 'git push'
    user: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # running/success/failed/pending
    branch: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    env: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    stages: Mapped[list[dict]] = mapped_column(JSON, default=list)


class DeploymentHistory(Base):
    """A single deployment record shown on the /runtime · 部署历史 tab."""

    __tablename__ = "deployment_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'dep-209'
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    app: Mapped[str] = mapped_column(String(128), nullable=False)
    app_code: Mapped[str] = mapped_column(String(64), default="")
    env: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="")
    user: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success")  # success/failed
    changes: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[str] = mapped_column(String(32), default="0s")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
