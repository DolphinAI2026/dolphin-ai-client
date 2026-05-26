"""PR3 (SPEC v2 §2): `update_apaas_app_info` MCP tool + REST endpoint 测试.

覆盖:
- INVALID_APAAS_APP_ID: apaas_app_id 空串
- INVALID_PARAMS: 3 字段全空
- NOT_IMPLEMENTED 优雅降级: apaas_client.update_app 抛 NOT_IMPLEMENTED 文本时
  顶层包装成 error_code=NOT_IMPLEMENTED
- 成功路径: 平台 client 返成功 dict → tool 返 ok + updated_fields
- REST endpoint: APP_NOT_DEPLOYED 守卫
- REST endpoint: 改名后同步 app.name 到 DB
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import Application, Tenant, User


async def _seed_basics(db_session, *, deployed: bool = True):
    tenant = Tenant(tenant_name="t-update-info", tenant_code="t-update-info")
    db_session.add(tenant)
    await db_session.flush()

    user = User(username="u-update-info", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    from app.models.tenant import UserTenant
    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))

    app = Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="原应用名",
        app_code="orig-name",
        status="completed" if deployed else "draft",
        platform_env_id=1 if deployed else None,
        apaas_app_id="846123456789012345" if deployed else None,
    )
    db_session.add(app)
    await db_session.commit()
    await db_session.refresh(app)

    return {"tenant": tenant, "user": user, "app": app}


# ─────────── MCP tool 层测试 ───────────


@pytest.mark.asyncio
async def test_update_apaas_app_info_rejects_empty_apaas_app_id():
    from app.mcp_server import update_apaas_app_info

    result = await update_apaas_app_info(env_id=1, apaas_app_id="")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_APAAS_APP_ID"


@pytest.mark.asyncio
async def test_update_apaas_app_info_rejects_all_empty_fields():
    from app.mcp_server import update_apaas_app_info

    result = await update_apaas_app_info(
        env_id=1, apaas_app_id="846123", app_name="", description="", icon_svg="",
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_PARAMS"
    assert "至少传一个非空字段" in result["message"]


@pytest.mark.asyncio
async def test_update_apaas_app_info_success_path():
    """平台 client 返成功 → tool 返 ok=True + updated_fields."""
    from app import mcp_server

    fake_client_call = AsyncMock(return_value={"id": "846123", "appName": "新名"})

    async def fake_with_client(env_id, op, fn):
        # 模拟 _with_client 拿到 client 调 fn 成功
        class _FakeClient:
            async def update_app(self, *args, **kwargs):
                return await fake_client_call(*args, **kwargs)
        return True, await fn(_FakeClient())

    with patch.object(mcp_server, "_with_client", side_effect=fake_with_client):
        result = await mcp_server.update_apaas_app_info(
            env_id=1,
            apaas_app_id="846123",
            app_name="新名",
            description="新描述",
        )

    assert result["ok"] is True
    assert set(result["updated_fields"]) == {"app_name", "description"}
    assert result["app_name"] == "新名"
    assert "应用已更新" in result["message"]
    fake_client_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_apaas_app_info_not_implemented_fallback():
    """apaas_client 抛 NOT_IMPLEMENTED → tool 包装成 error_code=NOT_IMPLEMENTED."""
    from app import mcp_server

    async def fake_with_client(env_id, op, fn):
        # 模拟 client.update_app 抛 NOT_IMPLEMENTED → _with_client 返 (False, error_dict)
        return False, {
            "ok": False, "error_code": "APAAS_CALL_FAILED",
            "message": "改应用信息失败：NOT_IMPLEMENTED: 平台没有 /xdap-app/apaasApplications/update 端点 (HTTP 404)",
            "env_id": 1,
        }

    with patch.object(mcp_server, "_with_client", side_effect=fake_with_client):
        result = await mcp_server.update_apaas_app_info(
            env_id=1, apaas_app_id="846123", app_name="新名",
        )

    assert result["ok"] is False
    assert result["error_code"] == "NOT_IMPLEMENTED"
    assert "平台无对应更新接口" in result["message"]
    assert result["attempted_fields"] == ["app_name"]


@pytest.mark.asyncio
async def test_update_apaas_app_info_only_icon():
    """只传 icon_svg 也算有效."""
    from app import mcp_server

    async def fake_with_client(env_id, op, fn):
        class _FakeClient:
            async def update_app(self, *args, **kwargs):
                return {"id": "846123"}
        return True, await fn(_FakeClient())

    with patch.object(mcp_server, "_with_client", side_effect=fake_with_client):
        result = await mcp_server.update_apaas_app_info(
            env_id=1, apaas_app_id="846123", icon_svg="<svg>...</svg>",
        )

    assert result["ok"] is True
    assert result["updated_fields"] == ["icon_svg"]


# ─────────── apaas_client.update_app 真接口层测试 ───────────


@pytest.mark.asyncio
async def test_apaas_client_update_app_payload_skips_empty_fields():
    """空串字段不进 payload, apaas_app_id 永远进 id."""
    from app.apaas_client import APaaSClient

    client = APaaSClient("https://fake.local", "fake-tenant", "fake-token")
    captured: dict = {}

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"code": "ok", "data": {"id": "846"}}
        def raise_for_status(self):
            return None

    class _FakeHttp:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return None
        async def post(self_, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    with patch("app.apaas_client.httpx.AsyncClient", lambda *a, **k: _FakeHttp()):
        result = await client.update_app(
            "846", app_name="新名", description="", icon_svg="",
        )

    assert result == {"id": "846"}
    assert captured["url"].endswith("/xdap-app/apaasApplications/update")
    # 关键: 空字段不能进 payload
    assert captured["json"] == {"id": "846", "appName": "新名"}


@pytest.mark.asyncio
async def test_apaas_client_update_app_404_raises_not_implemented():
    """平台返 404 / 405 时 raise NOT_IMPLEMENTED 文本."""
    from app.apaas_client import APaaSClient

    client = APaaSClient("https://fake.local", "fake-tenant", "fake-token")

    class _FakeResp:
        status_code = 404
        def json(self):
            return {"code": "error"}
        def raise_for_status(self):
            return None

    class _FakeHttp:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return None
        async def post(self_, *a, **kw):
            return _FakeResp()

    with patch("app.apaas_client.httpx.AsyncClient", lambda *a, **k: _FakeHttp()):
        with pytest.raises(Exception) as excinfo:
            await client.update_app("846", app_name="x")

    assert "NOT_IMPLEMENTED" in str(excinfo.value)


# ─────────── REST endpoint 测试 ───────────


@pytest.mark.asyncio
async def test_rest_endpoint_rejects_undeployed_app(db_session):
    """app 没 platform_env_id / apaas_app_id 时返 APP_NOT_DEPLOYED."""
    from app.deps import AuthContext
    from app.routes.applications import update_apaas_app_info_route, _UpdateApaasAppInfoReq

    seed = await _seed_basics(db_session, deployed=False)
    ctx = AuthContext(
        user=seed["user"], tenant_id=seed["tenant"].id,
        tenant_role="tenant_admin", org_permissions={},
    )

    payload = _UpdateApaasAppInfoReq(app_name="新名", description="", icon_svg="")
    result = await update_apaas_app_info_route(
        app_id=seed["app"].id, payload=payload, ctx=ctx, db=db_session,
    )

    assert result["ok"] is False
    assert result["error_code"] == "APP_NOT_DEPLOYED"


@pytest.mark.asyncio
async def test_rest_endpoint_rejects_empty_payload(db_session):
    from app.deps import AuthContext
    from app.routes.applications import update_apaas_app_info_route, _UpdateApaasAppInfoReq

    seed = await _seed_basics(db_session, deployed=True)
    ctx = AuthContext(
        user=seed["user"], tenant_id=seed["tenant"].id,
        tenant_role="tenant_admin", org_permissions={},
    )

    payload = _UpdateApaasAppInfoReq(app_name="", description="", icon_svg="")
    result = await update_apaas_app_info_route(
        app_id=seed["app"].id, payload=payload, ctx=ctx, db=db_session,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_rest_endpoint_syncs_app_name_to_db_on_success(db_session):
    """改名成功后 Application.name 字段同步更新, UI 刷新立刻看到新名."""
    from app.deps import AuthContext
    from app import mcp_server
    from app.routes.applications import update_apaas_app_info_route, _UpdateApaasAppInfoReq

    seed = await _seed_basics(db_session, deployed=True)
    ctx = AuthContext(
        user=seed["user"], tenant_id=seed["tenant"].id,
        tenant_role="tenant_admin", org_permissions={},
    )

    # mock mcp_server._with_client 模拟平台 client 返成功
    async def fake_with_client(env_id, op, fn):
        class _FakeClient:
            async def update_app(self, *a, **k):
                return {"id": k.get("apaas_app_id") or "846"}
        return True, await fn(_FakeClient())

    payload = _UpdateApaasAppInfoReq(app_name="改后的名", description="", icon_svg="")
    with patch.object(mcp_server, "_with_client", side_effect=fake_with_client):
        result = await update_apaas_app_info_route(
            app_id=seed["app"].id, payload=payload, ctx=ctx, db=db_session,
        )

    assert result["ok"] is True
    assert result.get("synced_local_name") == "改后的名"
    # 真从 db 重新拉一次确认
    from sqlalchemy import select
    refreshed = (await db_session.execute(
        select(Application).where(Application.id == seed["app"].id)
    )).scalar_one()
    assert refreshed.app_name == "改后的名"
