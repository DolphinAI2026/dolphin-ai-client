"""Seed lightweight demo components for the /marketplace page.

Idempotent: if `marketplace_components` already has any row for the target
tenant, this is a no-op. Skips silently if the default tenant or an admin
author user doesn't exist yet (seed_initial_data is expected to have run
first; otherwise demo data simply isn't created — no error).

Five demo components ship so a fresh tenant browsing /marketplace sees
plausible content instead of an empty grid:
- talent-dashboard       TalentDashboard.vue   (HR 看板)
- asset-timeline         AssetTimeline.vue     (资产维保时间线)
- kpi-chart              KPIChart.vue          (通用 KPI 图表)
- crm-funnel             CRMFunnel.vue         (销售漏斗)
- approval-stepper       ApprovalStepper.vue   (审批流可视化)

`zip_path` 设为 None — 这些是占位元数据，下载会 404，但是列表/详情 OK。
真发布走 POST /marketplace/publish 写真实 zip，跟 seed 共存不冲突。
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketplaceComponent, User
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


_DEFAULT_COMPONENTS: list[dict] = [
    {
        "name": "TalentDashboard",
        "code": "talent-dashboard",
        "description": "员工档案、入职动态、考勤统计三合一看板组件。",
        "category": "page-template",
        "version": "v1.0.0",
        "tags": ["HR", "看板", "dashboard"],
        "readme": "# TalentDashboard\n\n人事场景标杆组件。包含员工档案搜索、入职动态时间线、月度考勤统计三栏布局。",
    },
    {
        "name": "AssetTimeline",
        "code": "asset-timeline",
        "description": "资产维保历史时间线可视化，支持点位标注 + 状态切换。",
        "category": "form-component-dual",
        "version": "v1.0.0",
        "tags": ["资产", "timeline", "维保"],
        "readme": "# AssetTimeline\n\n横向时间线组件。每个节点=一次维保记录，悬停展开详情。",
    },
    {
        "name": "KPIChart",
        "code": "kpi-chart",
        "description": "通用 KPI 卡片 + 趋势小图组合，支持环比/同比标注。",
        "category": "chart",
        "version": "v1.2.0",
        "tags": ["KPI", "chart", "通用"],
        "readme": "# KPIChart\n\n一行 N 张 KPI 卡，每卡含主数 + sparkline + 环比箭头。",
    },
    {
        "name": "CRMFunnel",
        "code": "crm-funnel",
        "description": "销售漏斗组件，线索/商机/合同/回款四阶段转化率可视化。",
        "category": "chart",
        "version": "v1.0.0",
        "tags": ["CRM", "funnel", "销售"],
        "readme": "# CRMFunnel\n\n四阶段倒锥形漏斗。点击每段下钻到明细列表。",
    },
    {
        "name": "ApprovalStepper",
        "code": "approval-stepper",
        "description": "审批流可视化组件，节点 + 审批人 + 时间 + 意见四列展示。",
        "category": "form-component-dual",
        "version": "v1.1.0",
        "tags": ["审批", "stepper", "流程"],
        "readme": "# ApprovalStepper\n\n竖向 stepper。每节点彩色徽章 + 审批人头像 + 意见折叠。",
    },
]


async def seed_marketplace_components(db: AsyncSession) -> bool:
    """Insert 5 demo components for the default tenant if none exist.

    No-op if:
    - default tenant not found
    - no users exist (no plausible author_id)
    - any marketplace_components row already exists for that tenant

    Returns True if inserted, False if skipped.
    """
    # 找 default tenant
    default_tenant = (
        await db.execute(select(Tenant).where(Tenant.tenant_code == "default"))
    ).scalar_one_or_none()
    if not default_tenant:
        logger.info("marketplace_seed: default tenant 不存在，跳过 seed")
        return False

    # idempotent — 该 tenant 已有任何组件则跳过
    existing = (
        await db.execute(
            select(MarketplaceComponent.id).where(
                MarketplaceComponent.tenant_id == default_tenant.id
            )
        )
    ).scalars().first()
    if existing:
        return False

    # 选一个 author — 优先 platform_admin，否则第一个 user
    author = (
        await db.execute(
            select(User).where(User.is_platform_admin == True).order_by(User.id).limit(1)  # noqa: E712
        )
    ).scalar_one_or_none()
    if not author:
        author = (
            await db.execute(select(User).order_by(User.id).limit(1))
        ).scalar_one_or_none()
    if not author:
        logger.info("marketplace_seed: 没有可用 author user，跳过 seed")
        return False

    for spec in _DEFAULT_COMPONENTS:
        comp = MarketplaceComponent(
            name=spec["name"],
            code=spec["code"],
            description=spec["description"],
            category=spec["category"],
            version=spec["version"],
            author_id=author.id,
            tenant_id=default_tenant.id,
            tags=json.dumps(spec["tags"], ensure_ascii=False) if spec.get("tags") else None,
            readme=spec.get("readme"),
            zip_path=None,  # 占位 demo，不带真 zip
            source_workspace_id=None,
        )
        db.add(comp)
    await db.commit()
    logger.info(
        "marketplace_seed: inserted %d demo components for tenant=%d author=%d",
        len(_DEFAULT_COMPONENTS),
        default_tenant.id,
        author.id,
    )
    return True
