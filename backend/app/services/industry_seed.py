"""Seed the 4 default industry packs and the manufacturing ontology.

Idempotent: re-running on a populated `industry_packs` table is a no-op. Lazy-seeded
from `routes/industry.py:list_packs` on first call rather than at startup, so this
doesn't get tangled in the FastAPI lifespan hook (no `main.py` coupling).

Data is verbatim from the previous inline `INDUSTRY_PACKS` + `INDUSTRY_ONTOLOGY`
consts in `frontend/src/views/v2/IndustryPage.vue` (commit history pre-Session-4)
which itself was lifted from the design handoff data.js.

Only pkg-mfg gets the full ontology (9 entities + 8 relations + 5 workflows +
4 dictHighlight). pkg-crm / pkg-logi / pkg-govt ship with empty `ontology = {}`
for now — Session 5+ can populate them when their detail views come online.

No per-tenant `IndustryPackInstall` rows are seeded here. Pre-existing inline UI
marked pkg-mfg + pkg-crm as already installed, but that was display-only state;
real installs now happen exclusively via POST /industry/packs/{id}/install.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.industry import IndustryPack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Manufacturing ontology — pkg-mfg only
# ---------------------------------------------------------------------------

_MFG_ONTOLOGY: dict[str, Any] = {
    "entities": [
        {"code": "work_order", "name": "生产工单", "fields": 18, "x": 50, "y": 50, "hot": True, "tone": "brand"},
        {"code": "bom", "name": "BOM 物料清单", "fields": 12, "x": 50, "y": 220, "tone": "brand"},
        {"code": "process", "name": "工序", "fields": 8, "x": 260, "y": 50, "tone": "brand"},
        {"code": "workshop", "name": "车间", "fields": 6, "x": 260, "y": 220, "tone": "sky"},
        {"code": "machine", "name": "设备", "fields": 14, "x": 260, "y": 380, "tone": "sky"},
        {"code": "operator", "name": "操作工", "fields": 10, "x": 470, "y": 220, "tone": "amber"},
        {"code": "qc_record", "name": "质检记录", "fields": 11, "x": 470, "y": 50, "tone": "rose"},
        {"code": "material", "name": "原材料", "fields": 9, "x": 50, "y": 380, "tone": "brand"},
        {"code": "fg_inv", "name": "成品库存", "fields": 8, "x": 470, "y": 380, "tone": "emerald"},
    ],
    "relations": [
        {"from": "work_order", "to": "bom", "label": "consumes"},
        {"from": "work_order", "to": "process", "label": "has steps"},
        {"from": "process", "to": "workshop", "label": "runs in"},
        {"from": "process", "to": "machine", "label": "uses"},
        {"from": "machine", "to": "operator", "label": "operated by"},
        {"from": "work_order", "to": "qc_record", "label": "inspected by"},
        {"from": "bom", "to": "material", "label": "composed of"},
        {"from": "work_order", "to": "fg_inv", "label": "produces"},
    ],
    "workflows": [
        {"name": "工单发起 → 计划排程", "nodes": 4, "sla": "24h"},
        {"name": "车间派工 → 工序确认", "nodes": 5, "sla": "4h"},
        {"name": "在制品转序 → 质检", "nodes": 6, "sla": "2h"},
        {"name": "成品入库 → 工单关闭", "nodes": 4, "sla": "24h"},
        {"name": "异常停机 → 修复 → 复工", "nodes": 7, "sla": "60min"},
    ],
    "dictHighlight": [
        {"code": "wo_status", "name": "工单状态", "items": 8},
        {"code": "qc_result", "name": "质检结果", "items": 5},
        {"code": "machine_state", "name": "设备状态", "items": 6},
        {"code": "priority", "name": "优先级", "items": 4},
    ],
}


# ---------------------------------------------------------------------------
# 4 default packs
# ---------------------------------------------------------------------------

_DEFAULT_PACKS: list[dict[str, Any]] = [
    {
        "id": "pkg-mfg",
        "name": "制造装备",
        "code": "manufacturing",
        "tone": "amber",
        "version": "v2.1",
        "summary": "面向离散制造与连续生产，覆盖订单 → 计划 → 派工 → 质检 → 入库全链路。",
        "is_default": True,
        "maintainer": "得帆云 · 行业卓越中心",
        "updated": "5/14",
        "entities_count": 12,
        "relations_count": 30,
        "workflows_count": 8,
        "dicts_count": 24,
        "forms_count": 18,
        "roles_count": 6,
        "ontology": _MFG_ONTOLOGY,
        "adopted": ["生产工单调度", "资产管理系统", "某汽车制造客户"],
    },
    {
        "id": "pkg-crm",
        "name": "客户运营",
        "code": "crm-ops",
        "tone": "sky",
        "version": "v3.0",
        "summary": "客户 360 + 商机 + 工单 + SLA + 回访的完整对象图谱。",
        "is_default": False,
        "maintainer": "得帆云 · 客户成功部",
        "updated": "5/12",
        "entities_count": 9,
        "relations_count": 22,
        "workflows_count": 6,
        "dicts_count": 18,
        "forms_count": 14,
        "roles_count": 5,
        "ontology": {},
        "adopted": ["客户工单中心", "某连锁零售客户"],
    },
    {
        "id": "pkg-logi",
        "name": "智慧物流",
        "code": "logistics",
        "tone": "emerald",
        "version": "v1.4",
        "summary": "运单 / 仓配 / 路由 / 异常处理，含 GIS 字段类型与司机签收节点。",
        "is_default": False,
        "maintainer": "物流行业小组",
        "updated": "5/03",
        "entities_count": 11,
        "relations_count": 26,
        "workflows_count": 7,
        "dicts_count": 21,
        "forms_count": 15,
        "roles_count": 5,
        "ontology": {},
        "adopted": ["某物流客户（试用）"],
    },
    {
        "id": "pkg-govt",
        "name": "政企服务",
        "code": "govt-svc",
        "tone": "rose",
        "version": "v0.9",
        "summary": "事项审批、办件流转、政务字典（行政区划 / 事项分类标准编码）。",
        "is_default": False,
        "maintainer": "政企行业小组（Beta）",
        "updated": "4/28",
        "entities_count": 8,
        "relations_count": 16,
        "workflows_count": 5,
        "dicts_count": 36,
        "forms_count": 12,
        "roles_count": 6,
        "ontology": {},
        "adopted": [],
    },
]


async def seed_industry_packs(db: AsyncSession) -> bool:
    """Seed the 4 default packs if the table is empty. Returns True if seeded."""
    existing = (await db.execute(select(IndustryPack.id))).scalars().first()
    if existing:
        return False  # already seeded — caller can skip

    for spec in _DEFAULT_PACKS:
        db.add(IndustryPack(**spec))
    await db.commit()
    logger.info("industry_seed: inserted %d default packs", len(_DEFAULT_PACKS))
    return True
