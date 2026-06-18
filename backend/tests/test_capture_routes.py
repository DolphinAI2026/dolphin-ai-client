"""C2 /capture/* 路由 — start/console/network/devtools/stop。

不启动真实 Chromium：monkeypatch BrowserService.get_instance() 为 FakeService。
token 用 _verify_token 期望的 ide_access JWT 现铸。
"""
import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app
from app.config import settings
from app.routes import browser as browser_routes


def _token(ws_id: str) -> str:
    return jwt.encode(
        {"type": "ide_access", "ws": ws_id, "sub": "1", "tid": "1"},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )


class FakeService:
    def __init__(self):
        self.launched = []
        self.devtools_calls = []
        self.closed = []

    async def launch_capture(self, url, headless=True):
        self.launched.append((url, headless))
        return "cap-deadbeef0001"

    def get_console_logs(self, session_id, after_seq):
        return [{"seq": 1, "level": "error", "text": "boom", "location": "app.js:1:1"}]

    def get_network_requests(self, session_id, after_seq):
        return [{"seq": 1, "url": "http://x/boom", "status": 500, "method": "POST", "failed": False}]

    async def open_devtools(self, session_id):
        self.devtools_calls.append(session_id)

    async def close_capture(self, session_id):
        self.closed.append(session_id)


@pytest.fixture
def fake_service(monkeypatch):
    svc = FakeService()
    monkeypatch.setattr(browser_routes.BrowserService, "get_instance", classmethod(lambda cls: svc))
    return svc


@pytest.fixture
def client():
    return TestClient(app)


def test_capture_start_returns_session_id(client, fake_service):
    ws = "ws1"
    r = client.post(
        f"/api/coding/workspace/{ws}/browser/capture/start",
        params={"token": _token(ws)},
        json={"url": "http://127.0.0.1:5174/"},
    )
    assert r.status_code == 200
    assert r.json() == {"session_id": "cap-deadbeef0001"}
    assert fake_service.launched == [("http://127.0.0.1:5174/", True)]


def test_capture_console_and_network(client, fake_service):
    ws = "ws1"
    rc = client.get(
        f"/api/coding/workspace/{ws}/browser/capture/console",
        params={"token": _token(ws), "after_seq": 0, "session_id": "cap-x"},
    )
    assert rc.status_code == 200
    assert rc.json()["logs"][0]["level"] == "error"

    rn = client.get(
        f"/api/coding/workspace/{ws}/browser/capture/network",
        params={"token": _token(ws), "after_seq": 0, "session_id": "cap-x"},
    )
    assert rn.status_code == 200
    assert rn.json()["requests"][0]["status"] == 500


def test_capture_devtools_and_stop(client, fake_service):
    ws = "ws1"
    rd = client.post(
        f"/api/coding/workspace/{ws}/browser/capture/devtools",
        params={"token": _token(ws)},
        json={"session_id": "cap-x"},
    )
    assert rd.status_code == 200 and rd.json()["status"] == "ok"
    assert fake_service.devtools_calls == ["cap-x"]

    rs = client.post(
        f"/api/coding/workspace/{ws}/browser/capture/stop",
        params={"token": _token(ws)},
        json={"session_id": "cap-x"},
    )
    assert rs.status_code == 200 and rs.json()["status"] == "closed"
    assert fake_service.closed == ["cap-x"]


def test_capture_start_rejects_bad_token(client, fake_service):
    r = client.post(
        "/api/coding/workspace/ws1/browser/capture/start",
        params={"token": _token("OTHER_WS")},
        json={"url": "http://127.0.0.1:5174/"},
    )
    assert r.status_code == 403
