# backend/app/services/runtime_seed.py
"""Lazy seed for the v2 /runtime page pipelines + deployments tabs.

The values here are lifted verbatim from the inline seed that previously
lived in `frontend/src/views/v2/RuntimePage.vue` (`PIPELINES` /
`DEPLOYMENTS`). Each tenant gets the same demo dataset on first read so a
fresh login still shows something meaningful — replace with real data once
CI/CD + deployment events start flowing through ai-builder.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runtime_v2 import DeploymentHistory, PipelineRun


def _pipelines(tenant_id: int, now: datetime, yesterday: datetime) -> list[PipelineRun]:
    # Source of truth: `const PIPELINES` in frontend/src/views/v2/RuntimePage.vue.
    return [
        PipelineRun(
            id="run-1284", tenant_id=tenant_id,
            name="差旅报销表单", source="睿鲸 · ws-1",
            trigger="自动", user="AI",
            started_at=now, duration_s=0, status="running",
            branch="apaas-form-component",
            stages=[
                {"name": "Lint", "status": "done", "duration_s": 4},
                {"name": "Build UMD", "status": "done", "duration_s": 23},
                {"name": "Unit Test", "status": "running", "duration_s": 12},
                {"name": "E2E", "status": "pending", "duration_s": 0},
                {"name": "发布到组件市场", "status": "pending", "duration_s": 0},
            ],
        ),
        PipelineRun(
            id="run-1283", tenant_id=tenant_id,
            name="资产管理系统 · 增量部署", source="智能搭建 · 资产管理系统",
            trigger="手动", user="marshub",
            started_at=now - timedelta(minutes=24), duration_s=142, status="success", env="test",
            stages=[
                {"name": "解析 diff", "status": "done", "duration_s": 8},
                {"name": "校验配置", "status": "done", "duration_s": 14},
                {"name": "调用 aPaaS API", "status": "done", "duration_s": 96},
                {"name": "回归校验", "status": "done", "duration_s": 24},
            ],
        ),
        PipelineRun(
            id="run-1282", tenant_id=tenant_id,
            name="apaas-builder-ai · frontend", source="Vibe · sbx-2b1c · main",
            trigger="git push", user="marshub",
            started_at=now - timedelta(minutes=50), duration_s=86, status="success",
            branch="main", commit="a3f9b21",
            stages=[
                {"name": "Lint", "status": "done", "duration_s": 6},
                {"name": "Build (vite)", "status": "done", "duration_s": 42},
                {"name": "Unit Test", "status": "done", "duration_s": 18},
                {"name": "部署到 staging", "status": "done", "duration_s": 20},
            ],
        ),
        PipelineRun(
            id="run-1281", tenant_id=tenant_id,
            name="客户工单看板", source="睿鲸 · ws-2",
            trigger="自动", user="AI",
            started_at=now - timedelta(hours=3, minutes=34), duration_s=67, status="failed",
            branch="apaas-form-page",
            stages=[
                {"name": "Lint", "status": "done", "duration_s": 5},
                {"name": "Build UMD", "status": "failed", "duration_s": 62,
                 "error": 'SyntaxError: Unexpected token (form-list/index.vue:48)'},
                {"name": "Unit Test", "status": "skip", "duration_s": 0},
                {"name": "发布到组件市场", "status": "skip", "duration_s": 0},
            ],
        ),
        PipelineRun(
            id="run-1280", tenant_id=tenant_id,
            name="生产工单调度 · 全量部署", source="智能搭建",
            trigger="手动", user="marshub",
            started_at=yesterday.replace(hour=18, minute=14, second=0, microsecond=0),
            duration_s=312, status="success", env="prod",
            stages=[
                {"name": "解析配置", "status": "done", "duration_s": 12},
                {"name": "校验", "status": "done", "duration_s": 8},
                {"name": "调用 aPaaS API", "status": "done", "duration_s": 268},
                {"name": "回归校验", "status": "done", "duration_s": 24},
            ],
        ),
        PipelineRun(
            id="run-1279", tenant_id=tenant_id,
            name="人员选择组件 v3.2.1", source="睿鲸 · 王琪",
            trigger="手动", user="王琪",
            started_at=yesterday.replace(hour=16, minute=2, second=0, microsecond=0),
            duration_s=88, status="success",
            branch="apaas-form-component",
            stages=[
                {"name": "Lint", "status": "done", "duration_s": 4},
                {"name": "Build UMD", "status": "done", "duration_s": 28},
                {"name": "Unit Test", "status": "done", "duration_s": 32},
                {"name": "E2E", "status": "done", "duration_s": 14},
                {"name": "发布到组件市场", "status": "done", "duration_s": 10},
            ],
        ),
    ]


def _deployments(tenant_id: int, now: datetime, yesterday: datetime) -> list[DeploymentHistory]:
    # Source of truth: `const DEPLOYMENTS` in frontend/src/views/v2/RuntimePage.vue.
    return [
        DeploymentHistory(
            id="dep-209", tenant_id=tenant_id,
            app="资产管理系统", app_code="asset_mgr", env="test", version="v1.4.3",
            user="marshub", started_at=now,
            status="success", changes="增量：+ 报废审批节点 · 字段 +2", duration="2m 22s",
        ),
        DeploymentHistory(
            id="dep-208", tenant_id=tenant_id,
            app="差旅报销表单", app_code="asset_mgr", env="prod", version="v0.9.4",
            user="AI", started_at=now - timedelta(minutes=52),
            status="success", changes="组件发布：v0.9.4", duration="1m 46s",
        ),
        DeploymentHistory(
            id="dep-207", tenant_id=tenant_id,
            app="客户工单中心", app_code="cs_ticket", env="test", version="v2.1.0",
            user="marshub", started_at=now - timedelta(hours=5, minutes=16),
            status="success", changes="调整 SLA 字段", duration="1m 12s",
        ),
        DeploymentHistory(
            id="dep-206", tenant_id=tenant_id,
            app="生产工单调度", app_code="mfg_work", env="prod", version="v1.0.0",
            user="marshub", started_at=yesterday.replace(hour=18, minute=0, second=0, microsecond=0),
            status="success", changes="首次全量部署", duration="5m 12s",
        ),
        DeploymentHistory(
            id="dep-205", tenant_id=tenant_id,
            app="客户工单看板", app_code="ws-2", env="test", version="v0.0.1",
            user="AI", started_at=yesterday.replace(hour=10, minute=48, second=0, microsecond=0),
            status="failed", changes="组件构建失败", duration="1m 07s", error="SyntaxError",
        ),
        DeploymentHistory(
            id="dep-204", tenant_id=tenant_id,
            app="资产管理系统", app_code="asset_mgr", env="prod", version="v1.4.2",
            user="marshub", started_at=now - timedelta(days=2),
            status="success", changes="增量：+ 盘点结果字典", duration="2m 08s",
        ),
        DeploymentHistory(
            id="dep-203", tenant_id=tenant_id,
            app="合同审批", app_code="contract_v3", env="dev", version="v0.1.0",
            user="marshub", started_at=now - timedelta(days=3),
            status="success", changes="草稿试部署", duration="0m 58s",
        ),
    ]


async def seed_runtime_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    """DISABLED 2026-05-19 — user requested clean slate.

    To re-enable, remove the early return below. Sample pipeline_runs +
    deployment_history data is preserved as constants in this file.
    """
    return  # no-op; lazy seed disabled
    existing_pipe = (  # type: ignore[unreachable]
        await db.execute(
            select(PipelineRun).where(PipelineRun.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    existing_dep = (
        await db.execute(
            select(DeploymentHistory).where(DeploymentHistory.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if existing_pipe and existing_dep:
        return

    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)

    if not existing_pipe:
        for p in _pipelines(tenant_id, now, yesterday):
            db.add(p)

    if not existing_dep:
        for d in _deployments(tenant_id, now, yesterday):
            db.add(d)

    await db.commit()
