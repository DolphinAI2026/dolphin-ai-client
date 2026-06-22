"""本地 HMR 预览接真数据:harness $request 走 /apaas 同源代理(后端注 token)拿真平台数据,
未绑定/未部署时回退 mock 只渲染结构。serve 启动时按绑定应用注入 base + 代理目标到子进程 env。

根因(2026-06-22): 白屏修复后本地预览能渲染,但 $request 仍走 mock(空数据)。部署版整页
预览(_build_custom_page_host_html)早已用 /apaas/backend/{tenant}/{app} 同源代理拿真数据,
本块把同一套真请求搬进 vue-cli HMR 预览。
"""
from __future__ import annotations

from app.coding.workspace import ProjectType, WorkspaceManager


def _scaffold(tmp_path, ptype=ProjectType.FORM_PAGE, name="rating-star"):
    ws = tmp_path / "ws"
    WorkspaceManager()._scaffold_via_cli_template(ws, name, ptype)
    return ws


def test_preview_request_supports_real_data_and_chain_contract(tmp_path):
    ws = _scaffold(tmp_path)
    req = (ws / "preview" / "apaas-request.js").read_text("utf-8")
    # 真数据:走 VUE_APP_APAAS_API_BASE 注入的 /apaas 同源代理
    assert "VUE_APP_APAAS_API_BASE" in req
    assert "fetch(" in req
    # 平台链式契约(.asyncThen().asyncErrorCatch())+ thenable 都要支持
    assert "asyncThen" in req and "asyncErrorCatch" in req
    # main.js 安装它(替代旧 mock-only)
    main = (ws / "preview" / "main.js").read_text("utf-8")
    assert "installRequest" in main


def test_preview_vue_config_proxies_apaas_when_target_set(tmp_path):
    ws = _scaffold(tmp_path)
    vcfg = (ws / "vue.config.js").read_text("utf-8")
    # devServer 把 /apaas 代理到后端 runtime_proxy(仅当 env 注入目标时挂)
    assert "APAAS_PREVIEW_PROXY_TARGET" in vcfg
    assert "'/apaas'" in vcfg


def test_preview_data_env_set_when_provided():
    env = WorkspaceManager()._preview_data_env("/apaas/backend/t1/a1", "http://127.0.0.1:8799")
    assert env["VUE_APP_APAAS_API_BASE"] == "/apaas/backend/t1/a1"
    assert env["APAAS_PREVIEW_PROXY_TARGET"] == "http://127.0.0.1:8799"


def test_preview_data_env_empty_when_unbound():
    # 未绑定/未部署 → 不注入 → 预览回退 mock
    assert WorkspaceManager()._preview_data_env(None, None) == {}
    assert WorkspaceManager()._preview_data_env("", "") == {}


def test_preview_api_base_path_format():
    from app.coding.workspace import _preview_api_base_path
    assert _preview_api_base_path("mars", "crm") == "/apaas/backend/mars/crm"


def test_preview_api_base_path_none_when_missing():
    from app.coding.workspace import _preview_api_base_path
    assert _preview_api_base_path("", "crm") is None
    assert _preview_api_base_path("mars", "") is None
    assert _preview_api_base_path(None, None) is None
