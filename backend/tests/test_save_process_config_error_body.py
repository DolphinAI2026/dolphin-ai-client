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
