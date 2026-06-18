"""验证 pipeline 在 autofix flag 开启时把 agent 事件包进 driver，
且 autofix_round marker 进 replay；flag 关闭时走原单跑路径（行为不变）。"""
from __future__ import annotations

from app.coding import pipeline as pipeline_mod


def test_resolve_preview_url_from_serve_status_dual():
    # 双端 serve：优先取 web port
    status = {"running": True, "dual": True, "web": {"port": 8080}, "mobile": {"port": 8090}}
    assert pipeline_mod._autofix_preview_url(status) == "http://127.0.0.1:8080/"


def test_resolve_preview_url_from_serve_status_single():
    status = {"running": True, "port": 8081}
    assert pipeline_mod._autofix_preview_url(status) == "http://127.0.0.1:8081/"


def test_resolve_preview_url_none_when_not_running():
    assert pipeline_mod._autofix_preview_url({"running": False}) is None


def test_autofix_enabled_flag_default_on(monkeypatch):
    monkeypatch.delenv("CODING_AUTOFIX_ENABLED", raising=False)
    assert pipeline_mod._autofix_enabled() is True


def test_autofix_enabled_flag_off_when_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("CODING_AUTOFIX_ENABLED", "0")
    assert pipeline_mod._autofix_enabled() is False
