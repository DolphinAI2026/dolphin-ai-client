import importlib
import sys

from fastapi.testclient import TestClient


def test_desktop_mode_serves_spa_index(monkeypatch, tmp_path):
    """DESKTOP_MODE=1 且存在桌面 dist 时, GET / 返回前端 index.html; 未知前端路由回退 index.html。"""
    # 造一个假的桌面 dist
    fe = tmp_path / "dist-desktop"
    fe.mkdir()
    (fe / "index.html").write_text("<!doctype html><title>desktop-spa</title>", encoding="utf-8")

    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("DESKTOP_FRONTEND_DIR", str(fe))  # 测试用显式目录覆盖

    # 必须在设置 env 之后再 import, 否则 mount 逻辑读不到 DESKTOP_MODE
    import app.main as main_mod
    importlib.reload(main_mod)
    try:
        client = TestClient(main_mod.app)
        r_root = client.get("/")
        assert r_root.status_code == 200
        assert "desktop-spa" in r_root.text

        r_spa = client.get("/some/client/route")  # 前端 history 路由
        assert r_spa.status_code == 200
        assert "desktop-spa" in r_spa.text

        # API 仍优先于静态回退
        r_api = client.get("/api/health")
        assert r_api.status_code == 200
        assert r_api.json() == {"status": "ok"}
    finally:
        # 把 reload 后挂了桌面 mount 的模块逐出 sys.modules,
        # 避免泄漏给同进程后续 import app.main 的测试。
        sys.modules.pop("app.main", None)
