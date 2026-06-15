from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routes.applications import lowcode_logs


@pytest.mark.asyncio
async def test_get_application_lowcode_logs_uses_bound_platform_env(monkeypatch):
    app = SimpleNamespace(
        id=10,
        tenant_id=7,
        platform_env_id=55,
        app_name="智能体WMS系统",
        app_code="wms_app",
        apaas_app_id="10010",
    )

    async def fake_verify_app_access(app_id, ctx, db):
        assert app_id == 10
        return app

    captured = {}

    async def fake_call_apaas_with_relogin(env_id, db, fn):
        captured["env_id"] = env_id
        captured["db"] = db

        class FakeClient:
            async def query_operate_logs(self, *, page, page_size, filters):
                captured["page"] = page
                captured["page_size"] = page_size
                captured["filters"] = filters
                return {
                    "code": "ok",
                    "total": 1,
                    "table": [
                        {
                            "id": "log-1",
                            "operationTime": "2026-06-14 21:59:46",
                            "functionMenu": "应用信息",
                            "operationObject": "智能体WMS系统.智能体WMS系统",
                            "operationDescription": "发布了应用【智能体WMS系统】",
                            "operationType": "发布",
                            "operationUserName": "管理",
                        }
                    ],
                }

        return await fn(FakeClient())

    monkeypatch.setattr(lowcode_logs, "_verify_app_access", fake_verify_app_access)
    monkeypatch.setattr(lowcode_logs, "call_apaas_with_relogin", fake_call_apaas_with_relogin)

    resp = await lowcode_logs.get_application_lowcode_logs(
        10,
        SimpleNamespace(tenant_id=7),
        object(),
        page=2,
        page_size=20,
        operation_type="发布",
        function_menu="应用信息",
    )

    assert captured["env_id"] == 55
    assert captured["page"] == 2
    assert captured["page_size"] == 20
    assert captured["filters"] == {"operationType": "发布", "functionMenu": "应用信息"}
    assert resp["ok"] is True
    assert resp["items"][0]["status"] == "risk_medium"
    assert resp["analysis"]["risk_total"] == 1

