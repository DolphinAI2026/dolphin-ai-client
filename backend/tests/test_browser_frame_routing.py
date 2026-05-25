"""配置助手 iframe 精确操作 — P0 协议覆盖测试 (2026-05-25).

覆盖范围:
- browser_snapshot 聚合 frames[]; role 兜底分类; 新/老 extension 协议向后兼容
- browser_click / browser_type 把 frame_id 透传给 extension
- browser_wait_for_text + browser_press_key 基本逻辑 + ext 未连兜底
- _CONFIG_CHAT_TOOL_WHITELIST 含新增两工具

不跑真 WebSocket — 直接 monkeypatch _browser_tool_via_ext_or_cdm 模拟 extension 回执。
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from app import mcp_server
from app.routes.applications import _CONFIG_CHAT_TOOL_WHITELIST


# ─────────────────────────── classify_frame_url ───────────────────────────

def test_classify_frame_url_platform_match():
    f = mcp_server._classify_frame_url
    assert f("http://localhost:5173/platform/abc/admin", True) == "platform"
    assert f("http://localhost:5173/platform/abc/admin", False) == "platform"
    assert f("http://localhost:5173/api/platform-proxy/entry?app_id=1", False) == "platform"
    # 即使在 top frame, URL 含 /platform/ 也判 platform (proxy 直开场景)
    assert f("http://x/platform/y", True) == "platform"


def test_classify_frame_url_host_vs_other():
    f = mcp_server._classify_frame_url
    assert f("http://localhost:5173/ai-builder/chat?app_id=13", True) == "host"
    assert f("http://localhost:5173/ai-builder/chat?app_id=13", False) == "other"
    assert f("https://third-party.example.com/widget", False) == "other"
    assert f("", True) == "host"
    assert f("", False) == "other"


# ─────────────────────────── browser_snapshot ───────────────────────────

@pytest.mark.asyncio
async def test_browser_snapshot_aggregates_frames_new_protocol():
    """新版 extension (>=0.2.0) 返 frames[], backend 透传 + role 兜底."""
    fake_ext = {
        "ok": True,
        "result": {
            "tab_id": 7,
            "tab_url": "http://localhost:5173/ai-builder/chat?app_id=13",
            "tab_title": "应用调整",
            "frame_count": 2,
            "frames": [
                {
                    "frame_id": 0,
                    "parent_frame_id": -1,
                    "url": "http://localhost:5173/ai-builder/chat?app_id=13",
                    "title": "ChatPage",
                    "role": "host",
                    "tree": {"uid": "u1", "tag": "DIV"},
                },
                {
                    "frame_id": 99,
                    "parent_frame_id": 0,
                    "url": "http://localhost:5173/platform/abc/admin/app-store/edit-app?appId=123",
                    "title": "平台",
                    "role": "platform",
                    "tree": {"uid": "u2", "tag": "MAIN", "text": "应用编辑"},
                },
            ],
        },
    }
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm",
                      new=AsyncMock(return_value=fake_ext)):
        out = await mcp_server.browser_snapshot()
    assert out["ok"] is True
    assert out["source"] == "extension"
    assert out["frame_count"] == 2
    assert out["tab_id"] == 7
    assert out["tab_url"].startswith("http://localhost:5173/ai-builder/chat")
    plat = [f for f in out["frames"] if f["role"] == "platform"]
    assert len(plat) == 1
    assert plat[0]["frame_id"] == 99
    assert plat[0]["tree"]["text"] == "应用编辑"


@pytest.mark.asyncio
async def test_browser_snapshot_role_fallback_on_missing():
    """ext 没填 role 时 backend 按 URL 兜底."""
    fake_ext = {
        "ok": True,
        "result": {
            "frames": [
                {"frame_id": 0, "url": "http://localhost:5173/ai-builder/chat"},
                {"frame_id": 5, "url": "http://localhost:5173/platform/abc/admin"},
                {"frame_id": 7, "url": "http://localhost:5173/api/platform-proxy/entry?app_id=1"},
                {"frame_id": 9, "url": "https://some-third-party.com/iframe"},
            ],
        },
    }
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm",
                      new=AsyncMock(return_value=fake_ext)):
        out = await mcp_server.browser_snapshot()
    roles = {f["frame_id"]: f["role"] for f in out["frames"]}
    assert roles[0] == "host"
    assert roles[5] == "platform"
    assert roles[7] == "platform"
    assert roles[9] == "other"


@pytest.mark.asyncio
async def test_browser_snapshot_legacy_extension_wraps():
    """老版 extension (0.1.0) 返单 {url,title,root} — backend 包成单元素 frames[]."""
    legacy = {
        "ok": True,
        "result": {
            "url": "http://localhost:5173/platform/abc/admin",
            "title": "P",
            "root": {"uid": "r", "tag": "BODY"},
        },
    }
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm",
                      new=AsyncMock(return_value=legacy)):
        out = await mcp_server.browser_snapshot()
    assert out["ok"] is True
    assert out["frame_count"] == 1
    assert out["legacy_extension"] is True
    f = out["frames"][0]
    assert f["frame_id"] == 0
    # URL 含 /platform/ → 即使是 top frame 也判 platform
    assert f["role"] == "platform"
    assert f["tree"] == {"uid": "r", "tag": "BODY"}


@pytest.mark.asyncio
async def test_browser_snapshot_ext_disconnected_falls_back_to_cdm():
    """ext 没连 (_browser_tool_via_ext_or_cdm 返 None) 走 chrome-devtools-mcp fallback."""
    async def fake_ext_disc(cmd, args):
        return None

    async def fake_cdm_call(name, args):
        import json
        return json.dumps({
            "url": "http://localhost:5173/ai-builder/chat",
            "title": "x",
            "root": {"uid": "r"},
        })

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext_disc), \
         patch("app.browser_mcp_bridge.browser_bridge.call_tool", new=fake_cdm_call):
        out = await mcp_server.browser_snapshot()
    assert out["source"] == "cdm"
    assert out["frame_count"] == 1
    assert out["frames"][0]["frame_id"] == 0
    assert out["frames"][0]["role"] == "host"


@pytest.mark.asyncio
async def test_browser_snapshot_ext_returns_error():
    """ext 报错 → 直接返错给上层."""
    err = {"ok": False, "error_code": "EXTENSION_TIMEOUT", "message": "30s 没响应"}
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm",
                      new=AsyncMock(return_value=err)):
        out = await mcp_server.browser_snapshot()
    assert out["ok"] is False
    assert out["error_code"] == "EXTENSION_TIMEOUT"


# ─────────────────────────── browser_click / browser_type ───────────────────────────

@pytest.mark.asyncio
async def test_browser_click_passes_frame_id_through():
    captured = {}

    async def fake_ext(cmd, args):
        captured["cmd"] = cmd
        captured["args"] = args
        return {
            "ok": True,
            "result": {
                "ok": True,
                "clicked": {"tag": "BUTTON", "text": "保存"},
                "frame_url": "http://localhost:5173/platform/x",
                "frame_id_used": 99,
            },
        }

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext):
        out = await mcp_server.browser_click(uid="u123", frame_id=99)
    assert captured["cmd"] == "click"
    assert captured["args"]["uid"] == "u123"
    assert captured["args"]["frame_id"] == 99
    assert "frame_role" not in captured["args"]
    assert out["ok"] is True
    assert out["source"] == "extension"
    assert out["frame_id"] == 99
    assert out["frame_url"].startswith("http://localhost:5173/platform/")


@pytest.mark.asyncio
async def test_browser_click_with_frame_role():
    """传 frame_role 时透传给 extension, 让 extension 现场解析."""
    captured = {}

    async def fake_ext(cmd, args):
        captured["args"] = args
        return {
            "ok": True,
            "result": {
                "ok": True,
                "clicked": {"tag": "DIV", "text": "应用信息"},
                "frame_url": "http://localhost:5173/platform/y",
                "frame_id_used": 250,
            },
        }

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext):
        out = await mcp_server.browser_click(uid="utab", frame_role="platform")
    assert captured["args"]["frame_role"] == "platform"
    assert out["frame_id"] == 250  # extension 现场解析的真实落点


@pytest.mark.asyncio
async def test_browser_click_self_heal_reported():
    """老 frame_id 失效, extension 自愈拿到新 frame_id, response 透传 self_healed."""
    async def fake_ext(cmd, args):
        return {
            "ok": True,
            "result": {
                "ok": True,
                "clicked": {"tag": "BUTTON"},
                "frame_url": "http://localhost:5173/platform/x",
                "frame_id_used": 887,
                "frame_id_was_stale": 124,
                "self_healed": True,
            },
        }

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext):
        out = await mcp_server.browser_click(uid="u1", frame_id=124, frame_role="platform")
    assert out["ok"] is True
    assert out["frame_id"] == 887
    assert out["frame_id_was_stale"] == 124
    assert out["self_healed"] is True


@pytest.mark.asyncio
async def test_browser_click_elem_not_found_propagates():
    err_inside = {
        "ok": True,
        "result": {
            "ok": False,
            "error_code": "ELEM_NOT_FOUND",
            "args": {"uid": "missing", "frame_id": 99},
            "frame_url": "http://x",
        },
    }
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm",
                      new=AsyncMock(return_value=err_inside)):
        out = await mcp_server.browser_click(uid="missing", frame_id=99)
    assert out["ok"] is False
    assert out["error_code"] == "ELEM_NOT_FOUND"
    assert out["frame_id"] == 99


@pytest.mark.asyncio
async def test_browser_click_rejects_empty_uid():
    out = await mcp_server.browser_click(uid="   ", frame_id=0)
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_UID"


@pytest.mark.asyncio
async def test_browser_type_passes_frame_id():
    captured = {}

    async def fake_ext(cmd, args):
        captured["args"] = args
        return {
            "ok": True,
            "result": {"ok": True, "typed": "abc", "target": {"tag": "INPUT"}, "frame_url": "x"},
        }

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext):
        out = await mcp_server.browser_type(uid="u9", text="abc", frame_id=99)
    assert captured["args"] == {"uid": "u9", "text": "abc", "frame_id": 99}
    assert out["frame_id"] == 99
    assert out["typed"] == "abc"


# ─────────────────────────── browser_wait_for_text ───────────────────────────

@pytest.mark.asyncio
async def test_browser_wait_for_text_passes_args_and_timeout():
    captured = {}

    async def fake_ext(cmd, args, timeout):
        captured["cmd"] = cmd
        captured["args"] = args
        captured["timeout"] = timeout
        return {
            "ok": True,
            "result": {"ok": True, "text": "应用编辑", "elapsed_ms": 1200, "frame_url": "x"},
        }

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm_with_timeout", new=fake_ext):
        out = await mcp_server.browser_wait_for_text(text="应用编辑", frame_id=99, timeout_ms=3000)
    assert captured["cmd"] == "wait_for_text"
    assert captured["args"] == {"text": "应用编辑", "timeout_ms": 3000, "frame_id": 99}
    # RPC timeout = timeout_ms/1000 + 2s buffer
    assert captured["timeout"] == 5.0
    assert out["ok"] is True
    assert out["frame_id"] == 99
    assert out["elapsed_ms"] == 1200


@pytest.mark.asyncio
async def test_browser_wait_for_text_timeout_propagates():
    err = {
        "ok": True,
        "result": {
            "ok": False,
            "error_code": "WAIT_TIMEOUT",
            "elapsed_ms": 5000,
            "message": "等 5000ms 没出现文本「应用编辑」",
            "frame_url": "x",
        },
    }
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm_with_timeout",
                      new=AsyncMock(return_value=err)):
        out = await mcp_server.browser_wait_for_text(text="应用编辑", frame_id=99, timeout_ms=5000)
    assert out["ok"] is False
    assert out["error_code"] == "WAIT_TIMEOUT"
    assert out["elapsed_ms"] == 5000


@pytest.mark.asyncio
async def test_browser_wait_for_text_ext_disconnected():
    async def fake_ext_disc(cmd, args, timeout):
        return None
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm_with_timeout", new=fake_ext_disc):
        out = await mcp_server.browser_wait_for_text(text="x", frame_id=0, timeout_ms=1000)
    assert out["ok"] is False
    assert out["error_code"] == "EXTENSION_NOT_CONNECTED"


@pytest.mark.asyncio
async def test_browser_wait_for_text_rejects_empty_text():
    out = await mcp_server.browser_wait_for_text(text="", frame_id=0)
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_TEXT"


@pytest.mark.asyncio
async def test_browser_wait_for_text_clamps_timeout():
    """timeout_ms 超出 [100, 30000] 范围 backend 自动 clamp."""
    captured = {}

    async def fake_ext(cmd, args, timeout):
        captured["args"] = args
        return {"ok": True, "result": {"ok": True, "text": "x", "elapsed_ms": 1, "frame_url": "u"}}

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm_with_timeout", new=fake_ext):
        await mcp_server.browser_wait_for_text(text="x", frame_id=0, timeout_ms=999_999)
    assert captured["args"]["timeout_ms"] == 30000

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm_with_timeout", new=fake_ext):
        await mcp_server.browser_wait_for_text(text="x", frame_id=0, timeout_ms=10)
    assert captured["args"]["timeout_ms"] == 100


# ─────────────────────────── browser_press_key ───────────────────────────

@pytest.mark.asyncio
async def test_browser_press_key_passes_args():
    captured = {}

    async def fake_ext(cmd, args):
        captured["cmd"] = cmd
        captured["args"] = args
        return {
            "ok": True,
            "result": {"ok": True, "key": "Enter", "target_tag": "INPUT", "frame_url": "x"},
        }

    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext):
        out = await mcp_server.browser_press_key(key="Enter", frame_id=99, uid="u3")
    assert captured["cmd"] == "press_key"
    assert captured["args"] == {"key": "Enter", "frame_id": 99, "uid": "u3"}
    assert out["ok"] is True
    assert out["frame_id"] == 99


@pytest.mark.asyncio
async def test_browser_press_key_ext_disconnected():
    async def fake_ext_disc(cmd, args):
        return None
    with patch.object(mcp_server, "_browser_tool_via_ext_or_cdm", new=fake_ext_disc):
        out = await mcp_server.browser_press_key(key="Enter", frame_id=0)
    assert out["ok"] is False
    assert out["error_code"] == "EXTENSION_NOT_CONNECTED"


@pytest.mark.asyncio
async def test_browser_press_key_rejects_empty():
    out = await mcp_server.browser_press_key(key="  ", frame_id=0)
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_KEY"


# ─────────────────────────── whitelist ───────────────────────────

def test_config_chat_whitelist_includes_new_tools():
    """配置助手白名单必须含新两工具, 否则 agent 调了被拒."""
    assert "browser_wait_for_text" in _CONFIG_CHAT_TOOL_WHITELIST
    assert "browser_press_key" in _CONFIG_CHAT_TOOL_WHITELIST
    # 保留原有 browser_* 工具
    assert "browser_snapshot" in _CONFIG_CHAT_TOOL_WHITELIST
    assert "browser_click" in _CONFIG_CHAT_TOOL_WHITELIST
    assert "browser_type" in _CONFIG_CHAT_TOOL_WHITELIST
    assert "browser_screenshot" in _CONFIG_CHAT_TOOL_WHITELIST


def test_config_chat_whitelist_includes_menu_perm_dict_disable():
    """2026-05-25: 菜单 / 表单权限 / 字典禁用 6 个高频工具必须在白名单内.

    填补 P0 能力缺口: 用户说'加菜单 / 加自开发页面 / 删菜单 / 改字段权限 / 禁用字典'
    时不应该让 agent 退回去走 browser_* 模拟点击.
    """
    must = [
        "create_apaas_form_menu",
        "create_apaas_self_dev_menu",
        "delete_apaas_app_menu",
        "set_apaas_form_permissions",
        "disable_apaas_app_dict",
        "disable_apaas_dict_option",
    ]
    missing = [t for t in must if t not in _CONFIG_CHAT_TOOL_WHITELIST]
    assert not missing, f"白名单漏了 {missing}"
