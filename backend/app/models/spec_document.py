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

    GET /spec/parsed  (2026-05-28 新)
      同 markdown 缓存机制, 但返结构化 JSON 而非 markdown — 给前端 panel 反序列化
      渲染. 跟 markdown 共享同一行 + 同一 hash, 二者同时生成 + 同时失效.

2026-05-28 加 parsed_sections_json:
    之前只缓存 markdown 输出 — panel 渲染时仍要 8 个 fetchSection 并发打 apaas.
    现把 generator 一次拉出来的全 11 章 raw data 也存进 DB, 让 panel reload 1
    个 endpoint /spec/parsed 拿全数据, backend 重启不丢, 命中即秒开.
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

    # 2026-05-28: 结构化 11 章 raw data (JSON dict keyed by chapter name).
    # 跟 markdown_content 同源 (一次 generator run 同时产出两份), 同 hash 失效.
    # 形态:
    #   {
    #     "app_info":       {...本地 Application 元数据...},
    #     "roles":          [{code, name, member_count}, ...],
    #     "models":         [...with_fields=true 完整字段...],
    #     "dicts":          [...with_options=true 完整选项...],
    #     "menus":          [...完整菜单树 flatten...],
    #     "forms":          [...MODEL 类菜单子集...],
    #     "lists":          [...同 forms (一菜单含表单+列表两视图)...],
    #     "processes":      [...list_apaas_app_processes 抽摘要...],
    #     "business_events":[...list_apaas_business_events...],
    #     "integration":    [...PAGE_CUSTOM_DEV 菜单...],
    #     "datasources":    [...distinct datasource_id 聚合...]
    #   }
    # 给 GET /spec/parsed 直接返; 前端 reload 用这个替代 8 个 fetchSection 并发.
    parsed_sections_json: Mapped[str] = mapped_column(
        _BigText, nullable=False, default="{}"
    )
