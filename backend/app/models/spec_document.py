"""SpecDocument — 应用当前 SPEC.md 缓存 (1 行 per app, upsert).

跟 SpecAppliedVersion 区分:

    SpecDocument          (本模块)        SpecAppliedVersion
    ─────────────────────                 ─────────────────────────
    1 行 per app, upsert                 N 行 per app, append-only
    当前 SPEC.md 缓存                    历次 apply 的 frozen 快照
    sections_hash 失效就重建             永不变 (只标 is_active)
    给 GET /spec/markdown 用             给版本历史 / 回滚用

工作流:
    GET /spec/markdown
      1. SELECT FROM spec_documents WHERE app_id=X
      2. 算当前 (spec_sections + apaas 状态) hash
      3. cache miss (无行 / hash 不匹配) → 调 generate_spec_markdown + UPSERT row
      4. cache hit → 直接返 markdown_content

不存 raw apaas 数据 (那个走 SpecAppliedVersion.sections_snapshot 历史快照),
本表只缓存 markdown 输出 + hash 标记.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


_BigText = Text().with_variant(LONGTEXT, "mysql")


class SpecDocument(Base):
    """应用当前 SPEC.md 缓存 — 1 行 per app."""

    __tablename__ = "spec_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("applications.id"),
        unique=True,
        nullable=False,
    )

    # 完整 SPEC.md (跟前端 SpecDesignPanel 11 章渲染对齐).
    markdown_content: Mapped[str] = mapped_column(_BigText, nullable=False, default="")

    # 上次生成时间 — 用于 GET /spec/markdown 返 last_generated_at.
    last_generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # sha256(sorted JSON of all section data) — cache 失效判断.
    # 当前 hash 跟存的 hash 不一致 → 重新生成 + UPDATE row.
    sections_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
