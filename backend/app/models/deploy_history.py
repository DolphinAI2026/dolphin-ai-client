"""部署历史 & 回滚

参考 super-agents-dev 的 DeployRecord 模式（Java→Python 重写）：
- 每次 deploy_application / publish_application 落一行 DeployRecord
- 包含 snapshot_artifact_id 引用 ConfigSnapshot 用于回滚
- 状态：in_progress / success / failed / rolled_back
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DeployRecord(Base):
    """部署记录 — 每次 deploy/publish/rollback 都落一行，支持历史查看 + 一键回滚"""
    __tablename__ = "deploy_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 谁触发的

    # 版本标签：'v1.0.0' 或时间戳
    version_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 'in_progress' | 'success' | 'failed' | 'rolled_back'
    status: Mapped[str] = mapped_column(String(20), default="in_progress", nullable=False, index=True)

    # 'deploy' | 'publish' | 'rollback'
    deploy_type: Mapped[str] = mapped_column(String(20), default="deploy", nullable=False)

    # SPEC 快照引用 —— 复用 config_snapshots 表（其他人也复用这同一张表）
    # 如果是 ai_chat_artifacts（task 文档假设的表），这里就改成 FK ai_chat_artifacts.id
    snapshot_artifact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("config_snapshots.id"), nullable=True, index=True
    )

    # 部署前 / 部署后的 apaas_app_id（一般不变，但 rollback 时可能用得上）
    apaas_app_id_before: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    apaas_app_id_after: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 失败原因（任何 stage 出错都 dump 到这里）
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # SSE 事件日志快照（JSON array）—— 用于事后看 deploy 详细 timeline
    event_log_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
