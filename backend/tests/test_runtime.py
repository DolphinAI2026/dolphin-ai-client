"""Tests for app.runtime — 统一桌面/web 运行时门面。

pin 住从 skills.py / tools.py / main.py / desktop_auth.py 收口进来的现有行为,
尤其 is_frozen() 与 is_desktop() 的语义不对称(不可互换)。
"""
import sys
from pathlib import Path

from app import runtime


# ── is_frozen ──
def test_is_frozen_true_when_sys_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runtime.is_frozen() is True


def test_is_frozen_false_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert runtime.is_frozen() is False


# ── is_desktop ──
def test_is_desktop_true_when_desktop_mode(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("DESKTOP_MODE", "1")
    assert runtime.is_desktop() is True


def test_is_desktop_true_when_frozen_even_without_env(monkeypatch):
    """frozen 必然是桌面, 不依赖 DESKTOP_MODE env(信任边界/前端托管语义)。"""
    monkeypatch.delenv("DESKTOP_MODE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runtime.is_desktop() is True


def test_is_desktop_false_when_neither(monkeypatch):
    monkeypatch.delenv("DESKTOP_MODE", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert runtime.is_desktop() is False


# ── desktop_data_dir(五级反推的桌面部分) ──
def test_desktop_data_dir_prefers_sidecar_data_dir(monkeypatch):
    monkeypatch.setenv("SIDECAR_DATA_DIR", "/data/ruijing")
    monkeypatch.setenv("APAAS_WORKSPACE_ROOT", "/other/workspaces")
    assert runtime.desktop_data_dir() == Path("/data/ruijing")


def test_desktop_data_dir_derives_from_workspace_root(monkeypatch):
    monkeypatch.delenv("SIDECAR_DATA_DIR", raising=False)
    monkeypatch.setenv("APAAS_WORKSPACE_ROOT", "/data/ruijing/workspaces")
    assert runtime.desktop_data_dir() == Path("/data/ruijing")


def test_desktop_data_dir_fallback_home(monkeypatch):
    monkeypatch.delenv("SIDECAR_DATA_DIR", raising=False)
    monkeypatch.delenv("APAAS_WORKSPACE_ROOT", raising=False)
    assert runtime.desktop_data_dir() == Path.home() / ".ruijing-builder"


# ── server_data_dir(web 数据根) ──
def test_server_data_dir_from_env(monkeypatch):
    monkeypatch.setenv("RUIJING_SERVER_DATA_DIR", "/srv/data")
    assert runtime.server_data_dir() == Path("/srv/data")


def test_server_data_dir_none_when_unset(monkeypatch):
    monkeypatch.delenv("RUIJING_SERVER_DATA_DIR", raising=False)
    assert runtime.server_data_dir() is None


# ── desktop_frontend_dir(main.py 收口) ──
def test_desktop_frontend_dir_explicit_env(monkeypatch):
    monkeypatch.setenv("DESKTOP_FRONTEND_DIR", "/custom/fe")
    assert runtime.desktop_frontend_dir() == Path("/custom/fe")


def test_desktop_frontend_dir_meipass(monkeypatch):
    monkeypatch.delenv("DESKTOP_FRONTEND_DIR", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/frozen/bundle", raising=False)
    assert runtime.desktop_frontend_dir() == Path("/frozen/bundle") / "frontend_dist"


def test_desktop_frontend_dir_dev_fallback(monkeypatch):
    monkeypatch.delenv("DESKTOP_FRONTEND_DIR", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    result = runtime.desktop_frontend_dir()
    assert result.name == "dist-desktop"
    assert result.parent.name == "frontend"


# ── is_federation(desktop_auth 收口) ──
def test_is_federation_true_when_base_url_set(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "public_account_base_url", "https://acct")
    assert runtime.is_federation() is True


def test_is_federation_false_when_empty(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "public_account_base_url", "")
    assert runtime.is_federation() is False
