"""C2 CDP 抓取引擎 — console/network ring buffer + getters (after_seq 增量)。

不启动真实 Chromium：用 FakePage 捕获 page.on(...) 注册的回调，再手动 fire
console/response/requestfailed 事件，验证 ring buffer 落库 + seq 递增 + after_seq 增量。
"""
import pytest

from app.coding.browser_service import BrowserService, BrowserSession


class FakeError:
    def __init__(self, message):
        self.message = message


class FakeRequest:
    def __init__(self, method):
        self.method = method
        self.failure = None


class FakeResponse:
    def __init__(self, url, status, method):
        self.url = url
        self.status = status
        self.request = FakeRequest(method)


class FakeFailedRequest:
    def __init__(self, url, method, failure_text):
        self.url = url
        self.method = method
        self.failure = failure_text


class FakeConsoleMessage:
    def __init__(self, type_, text, location):
        self.type = type_
        self.text = text
        self.location = location


class FakePage:
    """记录 page.on(event, cb) 注册，提供 fire() 手动触发。"""
    def __init__(self):
        self.url = "http://127.0.0.1:5174/"
        self._handlers = {}

    def on(self, event, cb):
        self._handlers[event] = cb

    def fire(self, event, payload):
        self._handlers[event](payload)


def _make_session():
    page = FakePage()
    sess = BrowserSession("cap-1", context=None, page=page)
    sess.attach_capture()
    return sess, page


def test_console_ring_buffer_records_seq_and_increment():
    sess, page = _make_session()
    page.fire("console", FakeConsoleMessage(
        "error", "boom is not a function",
        {"url": "http://127.0.0.1:5174/app.js", "lineNumber": 12, "columnNumber": 3},
    ))
    page.fire("console", FakeConsoleMessage("log", "hello", {}))

    logs = sess.read_console(0)
    assert [l["seq"] for l in logs] == [1, 2]
    assert logs[0]["level"] == "error"
    assert logs[0]["text"] == "boom is not a function"
    assert "app.js" in logs[0]["location"]
    # 增量：after_seq=1 只拿第 2 条
    assert [l["seq"] for l in sess.read_console(1)] == [2]


def test_network_only_records_errors_and_failures():
    sess, page = _make_session()
    page.fire("response", FakeResponse("http://x/ok", 200, "GET"))      # 忽略
    page.fire("response", FakeResponse("http://x/boom", 500, "POST"))   # 记录
    page.fire("requestfailed", FakeFailedRequest("http://x/dead", "GET", "net::ERR"))  # 记录

    net = sess.read_network(0)
    assert [n["seq"] for n in net] == [1, 2]
    assert net[0] == {"seq": 1, "url": "http://x/boom", "status": 500, "method": "POST", "failed": False}
    assert net[1]["failed"] is True
    assert net[1]["status"] == 0
    assert [n["seq"] for n in sess.read_network(1)] == [2]


def test_ring_buffer_caps_at_limit():
    from app.coding.browser_service import RING_LIMIT
    sess, page = _make_session()
    for i in range(RING_LIMIT + 10):
        page.fire("console", FakeConsoleMessage("log", f"m{i}", {}))
    logs = sess.read_console(0)
    assert len(logs) == RING_LIMIT
    # seq 仍单调递增，最后一条 seq == 总数
    assert logs[-1]["seq"] == RING_LIMIT + 10


def test_service_getters_delegate_to_session(monkeypatch):
    svc = BrowserService()
    sess, page = _make_session()
    svc._sessions["cap-1"] = sess
    page.fire("console", FakeConsoleMessage("warning", "w", {}))
    assert svc.get_console_logs("cap-1", 0)[0]["level"] == "warning"
    assert svc.get_console_logs("missing", 0) == []
    assert svc.get_network_requests("missing", 0) == []
