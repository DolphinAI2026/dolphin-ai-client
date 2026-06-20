"""deploy 上传 token 失效自愈 — _upload_resp_is_token_error 检测 + _upload_one_kit 重登重试。

背景: 上传是 deploy 第一个平台调用, 用 _ensure_env_token 返回的 env.token(token 非空不验证过期),
且裸 httpx POST 漏了 call_apaas_with_relogin 自愈 → 旧 token 直接撞 Unauthorized。本组守住上传自愈。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.coding import deploy_service
from app.coding.deploy_service import _upload_resp_is_token_error, _upload_one_kit


# ── 纯函数: token 失效检测 ────────────────────────────────────────────

def test_detect_http_401():
    assert _upload_resp_is_token_error(httpx.Response(401, json={"code": "x"})) is True


def test_detect_body_unauthorized():
    # HTTP 200 但 body code != ok 且 message 含 "Unauthorized"(APAAS_TOKEN_MARKERS)
    r = httpx.Response(200, json={"code": "error", "message": "Unauthorized"})
    assert _upload_resp_is_token_error(r) is True


def test_detect_ok_is_not_token_error():
    assert _upload_resp_is_token_error(httpx.Response(200, json={"code": "ok"})) is False


def test_detect_non_token_business_error():
    r = httpx.Response(200, json={"code": "error", "message": "上传失败"})
    assert _upload_resp_is_token_error(r) is False


def test_detect_non_json_not_token_error():
    assert _upload_resp_is_token_error(httpx.Response(200, text="<html>oops</html>")) is False


# ── 集成: _upload_one_kit 重登重试 ───────────────────────────────────

def _patch_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig(transport=transport, **kw))


async def test_upload_relogins_and_retries_on_401(tmp_path, monkeypatch):
    fp = tmp_path / "kit.zip"
    fp.write_bytes(b"zipdata")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={"code": "error", "message": "Unauthorized"})
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)

    relogin = {"n": 0}
    async def _fake_relogin(env_id, db):
        relogin["n"] += 1
        return True
    monkeypatch.setattr(deploy_service, "_relogin_apaas_env", _fake_relogin)

    env = SimpleNamespace(platform_tenant_id="t", token="stale", id=7)
    rj = await _upload_one_kit("http://gw/upload", env, fp, "application/zip", {"f": "1"}, MagicMock())

    assert rj == {"code": "ok"}
    assert calls["n"] == 2      # 第一次 401 → 重登 → 重试第二次成功
    assert relogin["n"] == 1


async def test_upload_no_retry_when_relogin_fails(tmp_path, monkeypatch):
    fp = tmp_path / "kit.zip"
    fp.write_bytes(b"x")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"code": "error", "message": "Unauthorized"})

    _patch_transport(monkeypatch, handler)

    async def _fake_relogin(env_id, db):
        return False  # 重登失败(无凭据等)
    monkeypatch.setattr(deploy_service, "_relogin_apaas_env", _fake_relogin)

    env = SimpleNamespace(platform_tenant_id="t", token="stale", id=7)
    with pytest.raises(HTTPException):  # 重登失败 → 不重试 → 原失败抛
        await _upload_one_kit("http://gw/upload", env, fp, "application/zip", {}, MagicMock())
    assert calls["n"] == 1  # 没重试


async def test_upload_success_no_relogin(tmp_path, monkeypatch):
    fp = tmp_path / "kit.zip"
    fp.write_bytes(b"x")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"code": "ok"})

    _patch_transport(monkeypatch, handler)

    relogin = {"n": 0}
    async def _fake_relogin(env_id, db):
        relogin["n"] += 1
        return True
    monkeypatch.setattr(deploy_service, "_relogin_apaas_env", _fake_relogin)

    env = SimpleNamespace(platform_tenant_id="t", token="good", id=7)
    rj = await _upload_one_kit("http://gw/upload", env, fp, "application/zip", {}, MagicMock())

    assert rj == {"code": "ok"}
    assert calls["n"] == 1
    assert relogin["n"] == 0  # 没撞 token 错, 不重登
