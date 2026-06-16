from datetime import datetime

from app.services.app_health import checks
from app.services.app_health.types import AppSnapshotInput

AS_OF = datetime(2026, 6, 16, 12, 0, 0)


def _inp(**kw):
    return AppSnapshotInput(app_id=1, apaas_app_id="x", as_of=AS_OF, **kw)


def test_process_no_edges_is_high_fail():
    # 有详情(_detail_ok) 且 nodes>1 但无 edges → 真断流
    inp = _inp(processes=[{"processName": "入库审批流", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [], "status": "ENABLE", "_detail_ok": True}])
    res = {c.id: c for c in checks.check_processes(inp)}
    assert res["process.no_edges"].status == "fail"
    assert res["process.no_edges"].severity == "high"


def test_process_connected_passes():
    inp = _inp(processes=[{"processName": "p", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [{"id": "e1"}, {"id": "e2"}], "status": "ENABLE", "_detail_ok": True}])
    res = {c.id: c for c in checks.check_processes(inp)}
    assert res["process.no_edges"].status == "pass"


def test_process_no_detail_is_na_not_false_positive():
    # 列表数据没补到详情（无 _detail_ok）→ 断流检查转 N/A，绝不误报
    inp = _inp(processes=[{"processName": "p", "nodes": [{"id": "A"}, {"id": "B"}], "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_processes(inp)}
    assert res["process.no_edges"].status == "na"


def test_models_disabled():
    inp = _inp(models=[{"modelName": "停用模型", "status": "DISABLE"}, {"modelName": "好", "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_models(inp)}
    assert res["model.disabled"].metric == 1
    assert "model.no_fields" not in res  # 字段级检查 v1 不做


def test_roles_no_users():
    inp = _inp(roles=[{"roleName": "孤儿角色", "userCount": 0, "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_roles(inp)}
    assert res["role.no_users"].metric == 1


def test_events_na_when_none():
    inp = _inp(events=[])
    res = checks.check_events(inp)
    assert all(c.status == "na" for c in res)


def test_deploy_unpublished():
    inp = _inp(app_entry={"statusName": "未发布", "status": "DRAFT", "currentVersion": ""})
    res = {c.id: c for c in checks.check_deploy(inp)}
    assert res["deploy.unpublished"].status == "fail"
    assert res["deploy.no_version"].status == "fail"


def test_deploy_published_ok():
    inp = _inp(app_entry={"statusName": "已上线", "status": "RUNNING", "currentVersion": "0.0.4"})
    res = {c.id: c for c in checks.check_deploy(inp)}
    assert res["deploy.unpublished"].status == "pass"


def test_activity_stale():
    inp = _inp(app_entry={"lastUpdateDate": "2026-01-01 00:00:00"})
    res = {c.id: c for c in checks.check_activity(inp)}
    assert res["activity.stale"].status == "fail"


def test_activity_fresh():
    inp = _inp(app_entry={"lastUpdateDate": "2026-06-10 00:00:00"})
    res = {c.id: c for c in checks.check_activity(inp)}
    assert res["activity.stale"].status == "pass"
