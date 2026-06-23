"""agent 驱动的预览(_run_workspace_preview)应给已绑定应用注入真数据 env。

之前 bug：agent 在对话里跑预览时 start_serve 不传 apaas_api_base/proxy_target，
导致永远是 mock，用户「让 AI 接真实 API」必然失败。修复后两条路(HTTP manage_serve
与 agent 工具)走同一个 resolver，绑定到已部署应用即接真数据。
"""
from __future__ import annotations

import types

import pytest

import app.agents.coding.tools as tools_mod
import app.coding.preview_data as preview_data


class _FakeWsMgr:
    def __init__(self):
        self.start_serve_kwargs = None
        self._serve_processes = {}

    async def start_serve(self, ws_id, kind="web", *, apaas_api_base=None, proxy_target=None):
        self.start_serve_kwargs = {
            "ws_id": ws_id, "kind": kind,
            "apaas_api_base": apaas_api_base, "proxy_target": proxy_target,
        }
        return {"status": "ok", "port": 8085}


def _ctx():
    # db 给个哨兵(非 None)，让 _with_db 直接用它、不去开真实 AsyncSessionLocal；
    # resolver 已被 monkeypatch，不会真的碰这个 db。
    return types.SimpleNamespace(workspace_id="ws-1", tenant_id=7, db=object())


def _patch_common(monkeypatch, ws_mgr):
    monkeypatch.setattr(tools_mod, "_get_workspace_manager", lambda: ws_mgr)

    # 浏览器抓取不可用（模拟桌面包内 playwright 被排除）→ 走降级分支，不依赖 CDP
    def _no_browser():
        raise RuntimeError("playwright excluded")
    monkeypatch.setattr(tools_mod, "_get_browser_service_for_preview", _no_browser)


@pytest.mark.asyncio
async def test_bound_app_preview_injects_real_data_env(monkeypatch):
    ws_mgr = _FakeWsMgr()
    _patch_common(monkeypatch, ws_mgr)

    async def _fake_resolve(ws_id, tenant_id, db, *, apaas_user=None):
        assert ws_id == "ws-1" and tenant_id == 7
        return "/apaas/backend/tenantX/appY"
    monkeypatch.setattr(preview_data, "resolve_preview_api_base", _fake_resolve)
    monkeypatch.setattr(preview_data, "self_proxy_target", lambda: "http://127.0.0.1:8000")

    res = await tools_mod._run_workspace_preview({"kind": "web"}, _ctx())

    assert res.success
    assert ws_mgr.start_serve_kwargs["apaas_api_base"] == "/apaas/backend/tenantX/appY"
    assert ws_mgr.start_serve_kwargs["proxy_target"] == "http://127.0.0.1:8000"


@pytest.mark.asyncio
async def test_unbound_app_preview_falls_back_to_mock(monkeypatch):
    """未绑定/未部署 → resolver 返 None → start_serve 不带真数据 env（保持 mock 行为）。"""
    ws_mgr = _FakeWsMgr()
    _patch_common(monkeypatch, ws_mgr)

    async def _fake_resolve(ws_id, tenant_id, db, *, apaas_user=None):
        return None
    monkeypatch.setattr(preview_data, "resolve_preview_api_base", _fake_resolve)

    res = await tools_mod._run_workspace_preview({"kind": "web"}, _ctx())

    assert res.success
    assert ws_mgr.start_serve_kwargs["apaas_api_base"] is None
    assert ws_mgr.start_serve_kwargs["proxy_target"] is None


@pytest.mark.asyncio
async def test_resolve_failure_does_not_break_preview(monkeypatch):
    """真数据解析抛错(平台不可达等)不能让预览整个失败 —— 降级 mock 继续起 serve。"""
    ws_mgr = _FakeWsMgr()
    _patch_common(monkeypatch, ws_mgr)

    async def _boom(ws_id, tenant_id, db, *, apaas_user=None):
        raise RuntimeError("apaas unreachable")
    monkeypatch.setattr(preview_data, "resolve_preview_api_base", _boom)

    res = await tools_mod._run_workspace_preview({"kind": "web"}, _ctx())

    assert res.success
    assert ws_mgr.start_serve_kwargs["apaas_api_base"] is None
