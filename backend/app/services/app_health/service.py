from __future__ import annotations

import dataclasses
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .collector import collect_app_snapshot
from .engine import run_health_engine
from .types import HealthReport


def report_to_dict(r: HealthReport) -> dict:
    d = dataclasses.asdict(r)
    d["as_of"] = r.as_of.isoformat()
    return d


async def run_app_health(app, env_id: int, db: AsyncSession, *, as_of: datetime, persist: bool) -> dict:
    inp = await collect_app_snapshot(app, env_id, db, as_of)
    report = run_health_engine(inp)
    if persist:
        from app.models import AppHealthSnapshot

        db.add(
            AppHealthSnapshot(
                tenant_id=app.tenant_id,
                app_id=app.id,
                apaas_app_id=report.apaas_app_id,
                as_of=report.as_of,
                total_score=report.total_score,
                grade=report.grade,
                has_critical=report.has_critical,
                dimensions=[
                    {
                        "dimension": d.dimension,
                        "score": d.score,
                        "na": d.na,
                        "weight_base": d.weight_base,
                        "weight_used": d.weight_used,
                    }
                    for d in report.dimensions
                ],
                findings=[dataclasses.asdict(f) for f in report.findings],
                data_coverage=report.data_coverage,
                engine_version=report.engine_version,
            )
        )
        await db.commit()
    return report_to_dict(report)
