"""锁住：save_process_config 在 apaas 返非 2xx 时，必须把平台的错误响应体暴露出来。

背景 bug：set_apaas_app_process 调 /xdap-app/process/save/processConfig 拿到 500，
但 save_process_config 用 response.raise_for_status() 在读响应体之前就抛 —— apaas
真正的错因（哪个字段 null / NPE 详情）被丢掉，调用方只看到通用 "Server error 500"，
无法定位。本测试要求异常消息里带上 apaas 的响应体。
"""
from __future__ import annotations

import httpx
import pytest

from app.apaas_client import APaaSClient


@pytest.mark.asyncio
async def test_save_process_config_surfaces_apaas_error_body(monkeypatch):
    client = APaaSClient(base_url="http://apaas.test/backend", tenant_id="t1", token="tok")

    apaas_detail = '{"code":"error","message":"newData is null: NodeApproveConfig deserialize 失败"}'

    async def fake_post(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(500, request=httpx.Request("POST", url), text=apaas_detail)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(Exception) as ei:
        await client.save_process_config("app1", {"nodes": [], "edges": []})

    msg = str(ei.value)
    assert "500" in msg, f"应包含 HTTP 状态码，得到：{msg}"
    # 关键：apaas 的真实错误详情必须出现在异常里（否则没法定位 500 根因）
    assert "newData is null" in msg, f"未暴露 apaas 错误响应体，得到：{msg}"


@pytest.mark.asyncio
async def test_save_process_config_saves_once_after_create(monkeypatch):
    client = APaaSClient(base_url="http://apaas.test/backend", tenant_id="t1", token="tok")
    calls = []

    async def fake_post(self, url, **kwargs):  # noqa: ANN001
        calls.append(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "code": "ok",
                "message": "保存成功",
                "data": {
                    "id": "proc-1",
                    "processName": "审批流",
                    "appId": "app1",
                    "lastUpdateDate": "2026-06-27 18:38:58",
                },
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    create_payload = {
        "processName": "审批流",
        "nodes": [
            {
                "id": "cell-2",
                "width": 112,
                "height": 48,
                "data": {
                    "type": "APPROVE",
                    "icon": "approve-icon",
                    "nodeTriggerRemindStatus": False,
                },
            }
        ],
    }

    result = await client.save_process_config("app1", create_payload)

    assert len(calls) == 1
    assert calls[0] == create_payload
    assert result["data"]["lastUpdateDate"] == "2026-06-27 18:38:58"


@pytest.mark.asyncio
async def test_save_process_config_does_not_double_save_updates(monkeypatch):
    client = APaaSClient(base_url="http://apaas.test/backend", tenant_id="t1", token="tok")
    calls = []

    async def fake_post(self, url, **kwargs):  # noqa: ANN001
        calls.append(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "code": "ok",
                "message": "保存成功",
                "data": {
                    "id": "proc-1",
                    "processName": "审批流",
                },
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await client.save_process_config("app1", {"id": "proc-1", "processName": "审批流"})

    assert calls == [{"id": "proc-1", "processName": "审批流"}]
