"""WebSocket bridge to Chrome extension (apaas-builder-helper).

Architecture (见 docs/rfc-2026-05-19-browser-control-poc.md Phase 2):

  Chrome extension (background.js) ─ WS ──┐
                                          │
  config-chat agent → browser_mcp_bridge ─┴→ ExtensionRouter (单例)
                                              ↓
                                            cmd 转发给 connected extension client,
                                            异步等 result.

Endpoint: WS /ws/browser-ext
Protocol (JSON over text frames):
  ext → bg : { type: "hello", version, ua }
  ext → bg : { type: "pong", t }
  ext → bg : { type: "result", id, ok, result | error }
  bg → ext : { type: "cmd", id, cmd, args }
  bg → ext : { type: "pong" }
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class ExtensionRouter:
    """单例：维护当前连接的 extension client (POC 阶段假设一个 user)。"""

    _instance: Optional["ExtensionRouter"] = None

    def __init__(self) -> None:
        self._ws: Optional[WebSocket] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._hello: dict = {}

    @classmethod
    def instance(cls) -> "ExtensionRouter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    @property
    def hello_meta(self) -> dict:
        return dict(self._hello)

    async def attach(self, ws: WebSocket) -> None:
        async with self._lock:
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    pass
            self._ws = ws
            self._hello = {}

    async def detach(self) -> None:
        async with self._lock:
            self._ws = None
            self._hello = {}
            # 把 pending 全报错
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("extension disconnected"))
            self._pending.clear()

    async def handle_inbound(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "hello":
            self._hello = {k: v for k, v in msg.items() if k != "type"}
            logger.info("browser-ext connected: %r", self._hello)
        elif t == "pong":
            pass
        elif t == "result":
            req_id = str(msg.get("id") or "")
            fut = self._pending.pop(req_id, None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def call(self, cmd: str, args: dict, timeout: float = 30.0) -> dict:
        """从 backend 主动调 extension，等 result。"""
        if not self.is_connected or self._ws is None:
            return {"ok": False, "error_code": "EXTENSION_NOT_CONNECTED",
                    "message": "Chrome extension 未连接，先安装 apaas-builder-helper extension 并打开任意 tab"}
        req_id = str(self._next_id); self._next_id += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self._ws.send_text(json.dumps({"type": "cmd", "id": req_id, "cmd": cmd, "args": args}))
        except Exception as e:
            self._pending.pop(req_id, None)
            return {"ok": False, "error_code": "EXTENSION_SEND_FAIL", "message": str(e)}
        try:
            msg = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return {"ok": False, "error_code": "EXTENSION_TIMEOUT",
                    "message": f"extension 没在 {timeout}s 内回复 cmd={cmd}"}
        # msg = {type:'result', id, ok, result|error}
        if not msg.get("ok"):
            return {"ok": False, "error_code": "EXTENSION_RUNTIME",
                    "message": (msg.get("error") or {}).get("message", "extension 内部错"),
                    "raw": msg.get("error")}
        return {"ok": True, "result": msg.get("result")}


ext_router = ExtensionRouter.instance()


@router.websocket("/ws/browser-ext")
async def browser_ext_ws(ws: WebSocket):
    """Extension 主动连过来；backend 把命令推送过去。"""
    await ws.accept()
    await ext_router.attach(ws)
    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                continue
            await ext_router.handle_inbound(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("browser-ext ws crashed")
    finally:
        await ext_router.detach()
        logger.info("browser-ext disconnected")
