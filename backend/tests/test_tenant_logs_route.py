from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routes import tenant_logs


@pytest.mark.asyncio
async def test_get_tenant_lowcode_logs_uses_current_tenant_env(monkeypatch):
    env = SimpleNamespace(id=88)

    async def fake_resolve_tenant_id(db, ctx):
        assert ctx.tenant_id == 7
        return 7

    async def fake_resolve_env(db, tenant_id):
        assert tenant_id == 7
        return env

    captured = {}

    async def fake_call_apaas_with_relogin(env_id, db, fn):
        captured["env_id"] = env_id

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
                            "operationTime": "2026-06-14 21:58:42",
                            "functionMenu": "高级设置",
                            "operationObject": "智能体WMS系统.自开发配置",
                            "operationDescription": "启用了【自开发配置】",
                            "operationType": "编辑",
                            "operationUserName": "管理",
                        }
                    ],
                }

        return await fn(FakeClient())

    monkeypatch.setattr(tenant_logs, "resolve_effective_tenant_id", fake_resolve_tenant_id)
    monkeypatch.setattr(tenant_logs, "_resolve_platform_env_for_tenant", fake_resolve_env)
    monkeypatch.setattr(tenant_logs, "call_apaas_with_relogin", fake_call_apaas_with_relogin)

    resp = await tenant_logs.get_tenant_lowcode_logs(
        SimpleNamespace(tenant_id=7),
        object(),
        page=1,
        page_size=20,
        operation_type="EDIT",
        function_menu="SELF_DEVELOPMENT_MANAGEMENT",
        keyword="自开发配置",
    )

    assert captured["env_id"] == 88
    assert captured["filters"] == {
        "operationType": "EDIT",
        "functionMenu": "SELF_DEVELOPMENT_MANAGEMENT",
        "operationObject": "自开发配置",
    }
    assert resp["ok"] is True
    assert resp["items"][0]["summary"] == "高级设置 · 智能体WMS系统.自开发配置 · 启用了【自开发配置】"
    assert resp["analysis"]["risk_total"] == 1
