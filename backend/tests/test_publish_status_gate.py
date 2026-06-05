"""发布状态硬门测试 — 生成未完成(status=generating/in_progress)时 publish 必须被拒(409)。

根因背景: deploy 起的后台生成(模型/表单/权限)没跑完时, apaas_app_id 已写入但应用还是
半成品; 旧逻辑只查 apaas_app_id 就放行 publish → 发出缺表单的半成品版本, 且 agent 据此
误报"已上线"。这里锁死: status 还在 generating/in_progress 时发布路由抛 409。
"""
import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.tenant import Tenant, UserTenant
from app.routes.applications import publish_application


async def _seed_app(db, status: str, apaas_app_id="apaas_test_1"):
    tenant = Tenant(tenant_name="gt", tenant_code="gt")
    db.add(tenant)
    await db.flush()
    user = User(username="gate_owner", hashed_password="x")
    db.add(user)
    await db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
    project = Project(name="gp", user_id=user.id, tenant_id=tenant.id)
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    app = Application(
        user_id=user.id, tenant_id=tenant.id, created_by=user.id, project_id=project.id,
        app_name="Gate App", app_code="gate_app", status=status, apaas_app_id=apaas_app_id,
    )
    db.add(app)
    await db.commit()
    return tenant, user, app


def _ctx(user, tid):
    return AuthContext(user=user, tenant_id=tid, tenant_role="tenant_admin", org_permissions={})


@pytest.mark.asyncio
async def test_publish_blocked_while_generating(db_session):
    tenant, user, app = await _seed_app(db_session, status="generating")
    with pytest.raises(HTTPException) as ei:
        await publish_application(app.id, _ctx(user, tenant.id), db_session)
    assert ei.value.status_code == 409
    assert "生成中" in ei.value.detail


@pytest.mark.asyncio
async def test_publish_blocked_while_in_progress(db_session):
    tenant, user, app = await _seed_app(db_session, status="in_progress")
    with pytest.raises(HTTPException) as ei:
        await publish_application(app.id, _ctx(user, tenant.id), db_session)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_publish_passes_status_gate_when_completed(db_session):
    """status=completed 应越过状态门 —— 后续会因无可用平台环境报别的错, 但绝不是 409。"""
    tenant, user, app = await _seed_app(db_session, status="completed")
    with pytest.raises(HTTPException) as ei:
        await publish_application(app.id, _ctx(user, tenant.id), db_session)
    assert ei.value.status_code != 409


# ── MCP 层: publish_application 把 409 转成干净的 STILL_GENERATING; get_application 带进度 ──

@pytest.mark.asyncio
async def test_mcp_publish_returns_still_generating(monkeypatch):
    from app import mcp_server as m

    async def fake_api_call(method, path, **kw):
        if path.endswith("/publish"):
            raise RuntimeError('内部接口 POST /applications/8/publish 失败 (409): {"detail":"应用还在生成中（模型/表单…）"}')
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))

    res = await m.publish_application(app_id=8)
    assert res["ok"] is False
    assert res["error_code"] == "STILL_GENERATING"
    assert "轮询" in res["message"]


@pytest.mark.asyncio
async def test_mcp_get_application_includes_progress_while_generating(monkeypatch):
    from app import mcp_server as m

    async def fake_api_call(method, path, **kw):
        if path == "/applications/8":
            return {"id": 8, "app_name": "x", "app_code": "x", "status": "generating", "apaas_app_id": "a"}
        if path.endswith("/spec-markdown"):
            return {"markdown": "", "source": "empty", "version": None}
        if path.endswith("/steps/status"):
            return {"app_status": "generating", "steps": [
                {"key": "create_model:0", "status": "completed"},
                {"key": "create_model:1", "status": "completed"},
                {"key": "create_form:0", "status": "completed"},
                {"key": "create_form:1", "status": "pending"},
            ]}
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))
    monkeypatch.setattr(m, "_build_app_view_url", lambda a: "url")

    res = await m.get_application(app_id=8)
    gp = res["generation_progress"]
    assert gp is not None
    assert gp["models"] == "2/2"
    assert gp["forms"] == "1/2"
    assert gp["app_status"] == "generating"


@pytest.mark.asyncio
async def test_mcp_get_application_skips_progress_when_completed(monkeypatch):
    from app import mcp_server as m
    calls = []

    async def fake_api_call(method, path, **kw):
        calls.append(path)
        if path == "/applications/8":
            return {"id": 8, "app_name": "x", "app_code": "x", "status": "completed", "apaas_app_id": "a"}
        if path.endswith("/spec-markdown"):
            return {"markdown": "", "source": "empty", "version": None}
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))
    monkeypatch.setattr(m, "_build_app_view_url", lambda a: "url")

    res = await m.get_application(app_id=8)
    assert res["generation_progress"] is None
    assert not any(p.endswith("/steps/status") for p in calls)  # completed 不查进度, 省调用
