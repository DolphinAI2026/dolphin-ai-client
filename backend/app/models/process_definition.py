"""ProcessDefinition ORM — design-v4 H2 简化 BPMN 序列化的本地存储.

存的是前端 ProcessDesignerPanel x6 graph 序列化出来的应用层 JSON
(不是平台真 BPMN). 用户点"保存"先落到 backend SQLite, 真同步到 aPaaS
平台留 P5 deploy 流程.

数据结构 (definition_json):
  {
    "process_name": "审批流程",
    "nodes": [
      { "id": "...", "type": "assignee_approval", "label": "...",
        "position": { "x": 100, "y": 200 }, "props": {...} }
    ],
    "edges": [
      { "id": "...", "source": "node_id_1", "target": "node_id_2",
        "label": "...", "condition": "true_branch" }
    ]
  }
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProcessDefinition(Base):
    """流程定义 — 应用层 ProcessDefinition JSON (P4 阶段不真同步 apaas).

    process_id 是 apaas 流程的 platform-side id (32hex UUID), 不是自增主键 —
    一个 process_id 对一行 (UPSERT 语义).
    """
    __tablename__ = "process_definitions"
    __table_args__ = (
        UniqueConstraint("application_id", "process_id", name="uq_process_definition_app_process"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    process_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    process_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
