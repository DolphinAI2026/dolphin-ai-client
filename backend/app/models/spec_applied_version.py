"""SpecAppliedVersion — 应用 SPEC 版本快照（每次"确认并生成"产出一行）

正经版本管理 (不是 demo). 当用户在 SPEC 设计 tab 点 "确认并生成" + apply_spec
跑完后, 落一行 SpecAppliedVersion 锁住当时的 SPEC 全量状态:

    sections_snapshot   — 所有 spec_sections 行的 JSON 全量快照 (含 base_version
                          bump 后的 spec_json)
    markdown_snapshot   — 调 generate_spec_markdown 生成的完整 SPEC.md
    apply_results       — 那次 MCP 调用的真实结果 (用 spec_apply 的 results 字段),
                          含每步成功 / 失败 + error_code (debug audit)

is_active 模型:
    只允许最多 1 行 is_active=True (per application).
    回滚 = 新建一行 SpecAppliedVersion + 老的 is_active=False (不删, 保历史).
    P6 真接通回滚时, 新行的 sections_snapshot 从历史行复制.

version_label 命名:
    spec_apply 端点产生时按 minor-bump 规则 (v1.0 → v1.1 → v1.2);
    回滚产生时按 patch-bump (v1.2 + revert to v1.0 → 写一行 v1.0.1).
    具体逻辑在 spec_apply.py:apply_spec.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# markdown 快照可能上百 KB (11 章 + 字段表), MySQL TEXT(64KB) 会溢; LONGTEXT(4GB) 兜底.
_BigText = Text().with_variant(LONGTEXT, "mysql")


class SpecAppliedVersion(Base):
    """应用 SPEC 已 apply 的版本快照 — 每次"确认并生成"成功后落一行."""

    __tablename__ = "spec_applied_versions"
    __table_args__ = (
        Index("ix_spec_app_ver", "application_id", "applied_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    applied_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # 全量快照 — 所有 spec_sections 行的 JSON, shape:
    #   {
    #     "sections": [
    #       {"id": 12, "section_type": "data_model", "section_key": "main",
    #        "spec_json": {...}, "base_version": 3, "draft_version": 3},
    #       ...
    #     ],
    #     "apaas_snapshot": {
    #        "roles": [...], "models": [...], "menus": [...], "dicts": [...],
    #        "processes": [...], "business_events": [...],
    #     },  # optional — 调 generate_spec_markdown 时顺便收集
    #     "captured_at": ISO timestamp
    #   }
    sections_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # apply 时刻生成的完整 SPEC.md — 跟 spec_documents 同 schema 但 frozen 一份
    markdown_snapshot: Mapped[Optional[str]] = mapped_column(_BigText, nullable=True)

    # MCP 真实执行结果 — debug audit
    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # apply_spec.py 返的 results list (含每步 {ok, mcp_tool, desc, error_code?, ...}).
    apply_results: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    # is_active: 只最新 1 行=current production. 老的标 False (不删, 保历史).
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
