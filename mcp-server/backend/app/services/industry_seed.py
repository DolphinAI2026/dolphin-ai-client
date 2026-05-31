"""Seed lightweight demo industry packs for the /industry knowledge-base page.

Idempotent: if `industry_packs` already has any row, this is a no-op so existing
deployments (or repeat startup) don't get duplicated rows.

Three demo packs ship out-of-the-box so a fresh tenant can browse a non-empty
catalog immediately:
- pkg-hr   人力资源 (talent + onboarding flow)
- pkg-crm  客户运营 (lead → opportunity → contract)
- pkg-asset 资产管理 (asset → maintenance → disposal)

Each pack carries 1-3 entities + 1-2 relations + 1 workflow + 1 dict highlight —
just enough for the ontology canvas to render something meaningful, not the
full production catalog. Replace with real customer data via admin tooling
once that pipeline exists.

Re-enable history: this file was previously disabled (early-return) per user
request 2026-05-19; restored 2026-05-19 PM with lighter-weight demo content.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.industry import IndustryPack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HR ontology — 人力资源
# ---------------------------------------------------------------------------

_HR_ONTOLOGY: dict[str, Any] = {
    "entities": [
        {"code": "employee", "name": "员工档案", "fields": 24, "x": 60, "y": 80, "hot": True, "tone": "brand"},
        {"code": "onboarding", "name": "入职流程", "fields": 12, "x": 320, "y": 80, "tone": "sky"},
        {"code": "leave_record", "name": "请假记录", "fields": 8, "x": 320, "y": 240, "tone": "amber"},
    ],
    "relations": [
        {"from": "employee", "to": "onboarding", "label": "goes through"},
        {"from": "employee", "to": "leave_record", "label": "files"},
    ],
    "workflows": [
        {"name": "员工入职 → 三方协议 → 试用考核", "nodes": 6, "sla": "30d"},
    ],
    "dictHighlight": [
        {"code": "employee_status", "name": "员工状态", "items": 5},
    ],
}


# ---------------------------------------------------------------------------
# CRM ontology — 客户运营
# ---------------------------------------------------------------------------

_CRM_ONTOLOGY: dict[str, Any] = {
    "entities": [
        {"code": "lead", "name": "销售线索", "fields": 14, "x": 60, "y": 80, "hot": True, "tone": "sky"},
        {"code": "opportunity", "name": "商机", "fields": 18, "x": 320, "y": 80, "tone": "brand"},
        {"code": "contract", "name": "合同", "fields": 22, "x": 580, "y": 80, "tone": "emerald"},
    ],
    "relations": [
        {"from": "lead", "to": "opportunity", "label": "converts to"},
        {"from": "opportunity", "to": "contract", "label": "closes as"},
    ],
    "workflows": [
        {"name": "线索分配 → 跟进 → 商机转化", "nodes": 5, "sla": "14d"},
    ],
    "dictHighlight": [
        {"code": "lead_source", "name": "线索来源", "items": 8},
    ],
}


# ---------------------------------------------------------------------------
# Asset ontology — 资产管理
# ---------------------------------------------------------------------------

_ASSET_ONTOLOGY: dict[str, Any] = {
    "entities": [
        {"code": "asset", "name": "资产档案", "fields": 16, "x": 60, "y": 80, "hot": True, "tone": "amber"},
        {"code": "maintenance", "name": "维保记录", "fields": 10, "x": 320, "y": 80, "tone": "sky"},
    ],
    "relations": [
        {"from": "asset", "to": "maintenance", "label": "has"},
    ],
    "workflows": [
        {"name": "资产登记 → 领用 → 维保 → 报废", "nodes": 4, "sla": "—"},
    ],
    "dictHighlight": [
        {"code": "asset_category", "name": "资产分类", "items": 12},
    ],
}


# ---------------------------------------------------------------------------
# Demo packs (3) — lightweight HR / CRM / Asset Mgmt
# ---------------------------------------------------------------------------

_DEFAULT_PACKS: list[dict[str, Any]] = [
    {
        "id": "pkg-hr",
        "name": "人力资源",
        "code": "hr",
        "tone": "brand",
        "version": "v1.0",
        "summary": "员工档案、入职流程、请假考勤的基础人事场景。",
        "is_default": True,
        "maintainer": "得帆云 · 人事行业小组",
        "updated": "5/19",
        "entities_count": 3,
        "relations_count": 2,
        "workflows_count": 1,
        "dicts_count": 1,
        "forms_count": 4,
        "roles_count": 3,
        "ontology": _HR_ONTOLOGY,
        "adopted": ["示例 · 员工入职"],
    },
    {
        "id": "pkg-crm",
        "name": "客户运营",
        "code": "crm",
        "tone": "sky",
        "version": "v1.0",
        "summary": "线索 → 商机 → 合同的客户关系最小闭环。",
        "is_default": False,
        "maintainer": "得帆云 · 客户成功部",
        "updated": "5/19",
        "entities_count": 3,
        "relations_count": 2,
        "workflows_count": 1,
        "dicts_count": 1,
        "forms_count": 4,
        "roles_count": 3,
        "ontology": _CRM_ONTOLOGY,
        "adopted": ["示例 · 销售线索池"],
    },
    {
        "id": "pkg-asset",
        "name": "资产管理",
        "code": "asset",
        "tone": "amber",
        "version": "v1.0",
        "summary": "资产档案与维保记录的轻量资产追踪场景。",
        "is_default": False,
        "maintainer": "得帆云 · 资产行业小组",
        "updated": "5/19",
        "entities_count": 2,
        "relations_count": 1,
        "workflows_count": 1,
        "dicts_count": 1,
        "forms_count": 3,
        "roles_count": 2,
        "ontology": _ASSET_ONTOLOGY,
        "adopted": [],
    },
]


async def seed_industry_packs(db: AsyncSession) -> bool:
    """Insert the 3 demo packs if the table is empty. No-op otherwise.

    Returns True if inserted, False if skipped.
    """
    existing = (await db.execute(select(IndustryPack.id))).scalars().first()
    if existing:
        return False  # already seeded — caller can skip

    for spec in _DEFAULT_PACKS:
        db.add(IndustryPack(**spec))
    await db.commit()
    logger.info("industry_seed: inserted %d demo packs", len(_DEFAULT_PACKS))
    return True
