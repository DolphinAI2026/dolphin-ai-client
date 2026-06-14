from types import SimpleNamespace

import pytest
import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import sys
import app.routes.auth  # 确保包（含子模块）已加载
auth_routes = sys.modules["app.routes.auth.login"]  # login 子模块，monkeypatch 在此生效
from app.deps import get_auth_context
from app.routes.auth import get_me, login
from app.schemas import UserLogin


@pytest.mark.asyncio
async def test_login_converts_apaas_sync_integrity_error_to_conflict(db_session, monkeypatch):
    async def fail_sync(_user_data, _db):
        raise IntegrityError("insert users", {}, Exception("duplicate key"))

    monkeypatch.setattr(auth_routes, "_try_apaas_login_flow", fail_sync)

    with pytest.raises(HTTPException) as exc:
        await login(UserLogin(username="admin", password="secret"), db_session)

    assert exc.value.status_code == 409
    assert "同步本地账号/租户数据" in exc.value.detail


@pytest.mark.asyncio
async def test_login_converts_apaas_network_error_to_service_unavailable(db_session, monkeypatch):
    monkeypatch.setattr(auth_routes, "_is_placeholder_apaas_base_url", lambda: False)

    async def fail_network(_user_data, _db):
        raise httpx.ConnectError("connect failed")

    monkeypatch.setattr(auth_routes, "_try_apaas_login_flow", fail_network)

    with pytest.raises(HTTPException) as exc:
        await login(UserLogin(username="admin", password="secret"), db_session)

    assert exc.value.status_code == 503
    assert "aPaaS 登录链路暂不可用" in exc.value.detail


@pytest.mark.asyncio
async def test_login_converts_unexpected_apaas_error_to_bad_gateway(db_session, monkeypatch):
    async def fail_unexpected(_user_data, _db):
        raise ValueError("bad payload")

    monkeypatch.setattr(auth_routes, "_try_apaas_login_flow", fail_unexpected)

    with pytest.raises(HTTPException) as exc:
        await login(UserLogin(username="admin", password="secret"), db_session)

    assert exc.value.status_code == 502
    assert "aPaaS 登录链路返回异常数据或同步失败" in exc.value.detail


@pytest.mark.asyncio
async def test_apaas_login_success_token_can_load_me(db_session, monkeypatch):
    monkeypatch.setattr(auth_routes.settings, "apaas_base_url", "https://apaas-trial.definesys.cn/backend")

    async def fake_platform_login(_username, _password):
        return None, {"code": "error", "message": "not platform admin"}

    async def fake_backend_login(_username, _password, _tenant_id=""):
        return "backend.token.sig", {
            "data": {
                "token": "backend.token.sig",
                "defaultTenantId": "tenant-1",
                "user": {"id": "apaas-user-1", "username": "admin", "name": "Admin"},
                "tenantInfos": [
                    {"tenantId": "tenant-1", "tenantName": "默认租户", "tenantCode": "default"}
                ],
            }
        }

    async def fake_switchable_tenants(_backend_token, _default_tenant_id):
        return []

    monkeypatch.setattr(auth_routes, "_apaas_platform_login", fake_platform_login)
    monkeypatch.setattr(auth_routes, "_apaas_backend_login", fake_backend_login)
    monkeypatch.setattr(auth_routes, "_apaas_switchable_tenants", fake_switchable_tenants)

    response = await login(UserLogin(username="admin", password="secret"), db_session)

    assert response.access_token
    assert response.requires_tenant_selection is False
    assert response.has_tenant_context is True
    assert response.tenants and response.tenants[0].tenant_name == "默认租户"

    ctx = await get_auth_context(SimpleNamespace(credentials=response.access_token), db_session)
    me = await get_me(ctx, db_session)

    assert me.username == "admin"
    assert me.tenant_name == "默认租户"
