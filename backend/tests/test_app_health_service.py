import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services.app_health import service
from app.services.app_health.types import AppSnapshotInput

AS_OF = datetime(2026, 6, 16, 12, 0, 0)


def _fixed_input(app_id=1):
    return AppSnapshotInput(
        app_id=app_id,
        apaas_app_id="AID",
        as_of=AS_OF,
        menus=[{"menuName": "m", "menuType": "TODO", "submenus": [], "isEffective": True}],
        models=[{"modelName": "ok", "fields": [{"fieldCode": "a"}], "status": "ENABLE"}],
        dicts=[{"dictionaryName": "d", "dictionaryStatus": "ENABLE"}],
        roles=[{"roleName": "r", "userCount": 2, "status": "ENABLE"}],
        processes=[{"processName": "断流", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [], "status": "ENABLE", "_detail_ok": True}],
        events=[],
        app_entry={"statusName": "已上线", "status": "RUNNING", "currentVersion": "1.0", "lastUpdateDate": "2026-06-15 00:00:00"},
        coverage={"menus": True, "models": True, "dicts": True, "roles": True, "processes": True, "events": True, "app_entry": True},
    )


def test_run_app_health_no_persist_shape(monkeypatch):
    async def fake_collect(app, env_id, db, as_of):
        return _fixed_input()

    monkeypatch.setattr(service, "collect_app_snapshot", fake_collect)
    app = SimpleNamespace(id=1, tenant_id=57, apaas_app_id="AID", platform_env_id=9)
    out = asyncio.run(service.run_app_health(app, 9, db=None, as_of=AS_OF, persist=False))
    assert out["total_score"] is not None
    assert out["grade"] in {"健康", "良好", "中等", "风险", "严重"}
    assert out["has_critical"] is True  # 断流流程
    assert out["as_of"] == AS_OF.isoformat()
    assert any(d["dimension"] == "processes" for d in out["dimensions"])


def test_run_app_health_persists_snapshot(monkeypatch):
    async def fake_collect(app, env_id, db, as_of):
        return _fixed_input()

    monkeypatch.setattr(service, "collect_app_snapshot", fake_collect)

    async def scenario():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            app = SimpleNamespace(id=1, tenant_id=57, apaas_app_id="AID", platform_env_id=9)
            await service.run_app_health(app, 9, db=db, as_of=AS_OF, persist=True)
            from sqlalchemy import select

            from app.models import AppHealthSnapshot

            rows = (await db.execute(select(AppHealthSnapshot))).scalars().all()
            return rows

    rows = asyncio.run(scenario())
    assert len(rows) == 1
    assert rows[0].tenant_id == 57
    assert rows[0].has_critical is True
    assert rows[0].engine_version == "1.0"


def test_application_router_registers_health_route():
    from app.routes.applications import router

    paths = {r.path for r in router.routes}
    assert "/applications/{app_id}/health" in paths
