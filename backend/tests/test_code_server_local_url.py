from starlette.requests import Request

from app.routes.coding import (
    _align_local_code_server_base_url,
    _build_ide_proxy_api_base,
    _infer_code_server_base_url,
)


def _request(origin: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/coding/workspace/ws_1/ide-url",
        "headers": [
            (b"host", b"localhost:8000"),
            (b"origin", origin.encode("utf-8")),
        ],
        "scheme": "http",
        "server": ("localhost", 8000),
        "client": ("127.0.0.1", 12345),
    })


def _proxied_request(*, host: str, prefix: str = "/ai-builder", referer: str = "") -> Request:
    headers = [
        (b"host", host.encode("utf-8")),
        (b"x-forwarded-proto", b"https"),
        (b"x-forwarded-host", host.encode("utf-8")),
    ]
    if prefix:
        headers.append((b"x-forwarded-prefix", prefix.encode("utf-8")))
    if referer:
        headers.append((b"referer", referer.encode("utf-8")))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/coding/workspace/ws_1/ide-url",
        "headers": headers,
        "scheme": "http",
        "server": ("127.0.0.1", 8003),
        "client": ("127.0.0.1", 12345),
    })


def test_local_code_server_url_follows_browser_origin_host():
    req = _request("http://127.0.0.1:5173")

    assert _align_local_code_server_base_url(req, "http://localhost:8080") == "http://127.0.0.1:8080"


def test_local_ide_proxy_api_base_uses_aligned_code_server_host(monkeypatch):
    req = _request("http://127.0.0.1:5173")
    monkeypatch.setattr("app.routes.coding.settings.code_server_base_url", "http://localhost:8080")

    assert (
        _build_ide_proxy_api_base(req, "ws_1")
        == "http://127.0.0.1:8080/proxy/8000/api/coding/workspace/ws_1/ide"
    )


def test_public_code_server_url_is_not_rewritten():
    req = _request("https://builder.example.com")

    assert (
        _align_local_code_server_base_url(req, "https://ide.example.com/ide")
        == "https://ide.example.com/ide"
    )


def test_code_server_url_defaults_to_current_domain_and_forwarded_prefix(monkeypatch):
    monkeypatch.setattr("app.routes.coding.settings.code_server_base_url", "")
    req = _proxied_request(host="builder.example.com", prefix="/ai-builder")

    assert _infer_code_server_base_url(req) == "https://builder.example.com/ai-builder/ide"


def test_code_server_url_defaults_to_current_domain_and_referer_prefix(monkeypatch):
    monkeypatch.setattr("app.routes.coding.settings.code_server_base_url", "")
    req = _proxied_request(
        host="builder.example.com",
        prefix="",
        referer="https://builder.example.com/ai-builder/coding",
    )

    assert _infer_code_server_base_url(req) == "https://builder.example.com/ai-builder/ide"
