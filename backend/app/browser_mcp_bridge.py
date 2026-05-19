"""桥到 chrome-devtools-mcp (stdio MCP server) — 给 config-chat agent 接入浏览器控制。

架构 (见 docs/rfc-2026-05-19-browser-control-poc.md):

  config-chat agent → browser_mcp_bridge.call_tool("take_snapshot", {...})
       ↓
  asyncio subprocess: chrome-devtools-mcp (npx chrome-devtools-mcp@latest
                                            --browserUrl http://127.0.0.1:9222)
       ↓ jsonrpc stdio
  Chrome (--remote-debugging-port=9222) ← 用户的浏览器

启动方式：FastAPI lifespan startup 时 `await BrowserMcpBridge.ensure_started()`
shutdown 时 `await BrowserMcpBridge.shutdown()`。

依赖：
  - node + npm 在 PATH (npx chrome-devtools-mcp@latest)
  - 用户 Chrome 必须先开 remote debug:
      mac: open -a "Google Chrome" --args --remote-debugging-port=9222
      win: chrome.exe --remote-debugging-port=9222
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BROWSER_URL = os.getenv("CHROME_DEVTOOLS_BROWSER_URL", "http://127.0.0.1:9222")
_CDM_CMD = ["npx", "-y", "chrome-devtools-mcp@latest", "--browserUrl", _BROWSER_URL]


class BrowserMcpBridge:
    """单例 — 进程内只跑一个 chrome-devtools-mcp child process。

    多用户隔离暂不在 POC 范围（Phase 2 会按用户启不同 user-data-dir）。
    """

    _instance: Optional["BrowserMcpBridge"] = None

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id: int = 1
        self._lock = asyncio.Lock()
        self._initialized = False
        self._tools_cache: Optional[list[dict]] = None

    @classmethod
    def instance(cls) -> "BrowserMcpBridge":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ─────────────────────────── 生命周期 ───────────────────────────

    async def ensure_started(self) -> bool:
        """启动 chrome-devtools-mcp child process。失败返 False。"""
        async with self._lock:
            if self._proc and self._proc.returncode is None:
                return True
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *_CDM_CMD,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._reader_task = asyncio.create_task(self._read_loop())
                # MCP initialize handshake
                await self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-builder", "version": "0.1"},
                })
                await self._send_notification("notifications/initialized", {})
                self._initialized = True
                logger.info(
                    "BrowserMcpBridge started (pid=%s, browserUrl=%s)",
                    self._proc.pid, _BROWSER_URL,
                )
                return True
            except FileNotFoundError as exc:
                logger.warning("chrome-devtools-mcp 启动失败（npx 不在 PATH 或 node 未装）: %s", exc)
                return False
            except Exception as exc:
                logger.exception("BrowserMcpBridge 启动失败: %s", exc)
                self._proc = None
                return False

    async def shutdown(self) -> None:
        async with self._lock:
            if self._reader_task:
                self._reader_task.cancel()
                self._reader_task = None
            if self._proc:
                try:
                    self._proc.terminate()
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None
            self._initialized = False

    @property
    def is_alive(self) -> bool:
        return bool(self._proc and self._proc.returncode is None and self._initialized)

    # ─────────────────────────── jsonrpc stdio ───────────────────────────

    async def _read_loop(self) -> None:
        """从 child process stdout 读 jsonrpc messages，dispatch 给 pending futures。

        chrome-devtools-mcp 用 LSP-style framing: 每个 message 前面有
        `Content-Length: N\r\n\r\n` header。但 mcp-sdk 也支持 newline-delimited
        json (一行一 message) — 我们先按 newline-delimited 处理，撞 framing 错再补。
        """
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    logger.warning("BrowserMcpBridge: stdout 非 JSON 行: %r", line[:200])
                    continue
                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if "error" in msg:
                        fut.set_exception(RuntimeError(str(msg["error"])))
                    else:
                        fut.set_result(msg.get("result"))
                # 其他 (notification) 暂时忽略
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("BrowserMcpBridge _read_loop crashed: %s", exc)

    async def _send_request(self, method: str, params: dict, timeout: float = 30.0) -> Any:
        assert self._proc and self._proc.stdin
        msg_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
        body = (json.dumps(payload) + "\n").encode("utf-8")
        self._proc.stdin.write(body)
        await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise

    async def _send_notification(self, method: str, params: dict) -> None:
        assert self._proc and self._proc.stdin
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        body = (json.dumps(payload) + "\n").encode("utf-8")
        self._proc.stdin.write(body)
        await self._proc.stdin.drain()

    # ─────────────────────────── 公开 API ───────────────────────────

    async def list_tools(self, force: bool = False) -> list[dict]:
        """拉 chrome-devtools-mcp 工具列表 (cache)。"""
        if self._tools_cache is not None and not force:
            return self._tools_cache
        if not self.is_alive:
            if not await self.ensure_started():
                return []
        try:
            result = await self._send_request("tools/list", {})
            tools = result.get("tools", []) if isinstance(result, dict) else []
            self._tools_cache = tools
            return tools
        except Exception as exc:
            logger.warning("BrowserMcpBridge.list_tools failed: %s", exc)
            return []

    async def call_tool(self, name: str, args: dict) -> str:
        """调用 chrome-devtools-mcp 工具，返 result.content[0].text (string)。

        失败返 JSON 字符串 {ok: false, error_code, message}，跟 ai_chat.mcp_bridge 对齐。
        """
        if not self.is_alive:
            if not await self.ensure_started():
                return json.dumps({
                    "ok": False, "error_code": "BRIDGE_NOT_STARTED",
                    "message": "chrome-devtools-mcp 未启动或 node 不可用",
                }, ensure_ascii=False)
        try:
            result = await self._send_request("tools/call", {"name": name, "arguments": args}, timeout=90.0)
            if not isinstance(result, dict):
                return json.dumps({"ok": False, "error_code": "BAD_RESULT", "raw": str(result)})
            if result.get("isError"):
                return json.dumps({"ok": False, "error_code": "TOOL_RUNTIME_ERROR", "raw": result}, ensure_ascii=False)
            content = result.get("content") or []
            if not content:
                return json.dumps({"ok": True, "empty": True}, ensure_ascii=False)
            block = content[0]
            text = block.get("text") if isinstance(block, dict) else None
            if text is None:
                return json.dumps({"ok": True, "raw": result}, ensure_ascii=False)
            return text
        except Exception as exc:
            logger.exception("BrowserMcpBridge.call_tool(%s) failed", name)
            return json.dumps({
                "ok": False, "error_code": "BRIDGE_EXCEPTION", "message": str(exc),
            }, ensure_ascii=False)


# 模块级单例，给外部用
browser_bridge = BrowserMcpBridge.instance()
