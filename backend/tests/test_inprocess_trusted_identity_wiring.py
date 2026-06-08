"""锁住「进程内工具入口把 JWT 身份标记为可信」的接线。

两个进程内可信入口必须在调工具前用 trusted_identity() 包住，让工具内部的
_resolve_identity 采信传入的租户、不被进程内 current_app slot 覆盖：
  - mcp_bridge._call_inprocess_tool —— unified ai-chat / 配置助手走这条
  - mcp_inprocess.call_inprocess_tool —— 平台管理 MCP 测试台走这条

外部 /api/mcp/mcp HTTP 路径不经过这两个函数，故不受影响（保持 slot 反查）。
"""
from __future__ import annotations

import pytest

from app import mcp_server
from app.ai_chat.mcp_bridge import _call_inprocess_tool
from app.mcp_inprocess import call_inprocess_tool
from app.routes.current_app import set_current_app, clear_current_app

DRAGONBOAT_TID = 42
WRONG_TID = 99   # slot 残留的错误租户
UID = 7
PROBE = "__probe_identity__"


class _ProbeTool:
    """假工具：工具体里像真工具一样调 _resolve_identity，记录解析出的身份。"""

    def __init__(self):
        self.seen: tuple[int, int] | None = None

    async def run(self, args, convert_result=True):
        tid, uid = mcp_server._resolve_identity(args.get("tenant_id"), args.get("user_id"))
        self.seen = (tid, uid)
        return {"tid": tid, "uid": uid}


def _install_probe(monkeypatch) -> _ProbeTool:
    probe = _ProbeTool()
    tools = mcp_server.mcp._tool_manager._tools
    monkeypatch.setitem(tools, PROBE, probe)
    return probe


async def test_bridge_inprocess_marks_identity_trusted(monkeypatch):
    """unified/config 入口：即使 slot 残留别的租户，工具也应采信传入的 dragonboat 租户。"""
    clear_current_app(UID)
    set_current_app(UID, WRONG_TID, 0, "")
    probe = _install_probe(monkeypatch)
    try:
        await _call_inprocess_tool(PROBE, {"tenant_id": DRAGONBOAT_TID, "user_id": UID})
        assert probe.seen == (DRAGONBOAT_TID, UID)
    finally:
        clear_current_app(UID)


async def test_admin_inprocess_marks_identity_trusted(monkeypatch):
    """admin 测试台入口：同样采信平台管理员 JWT 的租户、不被 slot 覆盖。"""
    clear_current_app(UID)
    set_current_app(UID, WRONG_TID, 0, "")
    probe = _install_probe(monkeypatch)
    try:
        await call_inprocess_tool(PROBE, {"tenant_id": DRAGONBOAT_TID, "user_id": UID})
        assert probe.seen == (DRAGONBOAT_TID, UID)
    finally:
        clear_current_app(UID)
