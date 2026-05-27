"""SpecSection — 应用的草稿规格（per (app, section_type, section_key) 一行）

O1 阶段（spec-driven 应用编辑流的"草稿层"基础设施）：

    对话 → AI 改 SPEC（草稿）→ 预览 → 用户 OK → AI 调 MCP 真存 apaas

4 个 designer panel（FormDesigner / DataSchemaEditor / ProcessDesigner /
RoleManagePanel）当前直接操作 apaas，没草稿层。SpecSection 给整个流程提供
"先改本地草稿、确认后再 push apaas" 的中间状态。

section_type / section_key 取值（O1 阶段 6 类）：

    form        ←→ form_id      （来自 apaas detailPageConfigById）
    list        ←→ menu_id      （列表页配置）
    process     ←→ process_id   （流程定义）
    page        ←→ menu_id      （页面 / 自定义页面）
    permission  ←→ role_id      （权限矩阵）
    data_model  ←→ model_code   （数据模型字段）

spec_json：O1 阶段保留为自由 JSON 字符串，O3 阶段引入 strict schema 校验。
base_version：从 apaas 拉取并初始化时记录的快照版本，diff 用。
draft_version：每次 update_spec_section 累加 1。
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


VALID_SECTION_TYPES = (
    "form",
    "list",
    "process",
    "page",
    "permission",
    "data_model",
)


class SpecSection(Base):
    """应用某 section 的草稿规格。"""

    __tablename__ = "spec_sections"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "section_type",
            "section_key",
            name="uq_spec_section",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    section_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    section_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
