import dataclasses
from datetime import datetime

from app.services.app_health.engine import run_health_engine
from app.services.app_health.types import AppSnapshotInput

AS_OF = datetime(2026, 6, 16, 12, 0, 0)


def _full_healthy():
    return AppSnapshotInput(
        app_id=1,
        apaas_app_id="x",
        as_of=AS_OF,
        menus=[{"menuName": "m", "menuType": "TODO", "submenus": [], "isEffective": True}],
        models=[{"modelName": "ok", "fields": [{"fieldCode": "a"}], "status": "ENABLE"}],
        dicts=[{"dictionaryName": "d", "dictionaryStatus": "ENABLE"}],
        roles=[{"roleName": "r", "userCount": 3, "status": "ENABLE"}],
        processes=[{"processName": "p", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [{"id": "e1"}], "status": "ENABLE", "_detail_ok": True}],
        events=[],
        app_entry={"statusName": "已上线", "status": "RUNNING", "currentVersion": "1.0", "lastUpdateDate": "2026-06-15 00:00:00"},
        coverage={"menus": True, "models": True, "dicts": True, "roles": True, "processes": True, "events": True, "app_entry": True},
    )


def test_healthy_app_high_score_no_critical():
    r = run_health_engine(_full_healthy())
    assert r.total_score >= 85 and r.grade == "健康" and r.has_critical is False


def test_broken_process_gates_and_flags_critical():
    inp = _full_healthy()
    inp.processes = [{"processName": "断流", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [], "status": "ENABLE", "_detail_ok": True}]
    r = run_health_engine(inp)
    pdim = next(d for d in r.dimensions if d.dimension == "processes")
    assert pdim.score <= 50 and r.has_critical is True
    # 有高危 → 总分封顶、等级不得为健康/良好
    assert r.total_score <= 69 and r.grade not in ("健康", "良好")


def test_na_dimension_excluded_and_renormalized():
    inp = _full_healthy()
    inp.events = []  # events -> na
    r = run_health_engine(inp)
    edim = next(d for d in r.dimensions if d.dimension == "events")
    assert edim.na is True and edim.weight_used == 0.0
    assert abs(sum(d.weight_used for d in r.dimensions) - 1.0) < 1e-6


def test_determinism_byte_identical():
    a = run_health_engine(_full_healthy())
    b = run_health_engine(_full_healthy())
    assert dataclasses.asdict(a) == dataclasses.asdict(b)
