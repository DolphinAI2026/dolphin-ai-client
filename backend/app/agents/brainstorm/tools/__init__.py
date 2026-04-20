"""BrainstormAgent 工具集合。

5 个 tool（架构文档 § 2.1）：
- detect_scene — 场景识别 + P1 清单展开
- ask_user — 反问（emit 事件 + should_pause）
- query_marketplace — 检索相似 Spec（MVP 返回 []，P2.3 接 DB）
- read_workspace_context — 读迭代场景的当前 workspace
- emit_spec — 产出最终 Spec（校验 + 终止）
"""
from __future__ import annotations

from app.agents.brainstorm.state import BrainstormState
from app.agents.brainstorm.tools.ask_user import build_ask_user_tool
from app.agents.brainstorm.tools.detect_scene import build_detect_scene_tool
from app.agents.brainstorm.tools.emit_spec import build_emit_spec_tool
from app.agents.brainstorm.tools.query_marketplace import build_query_marketplace_tool
from app.agents.brainstorm.tools.read_workspace_context import build_read_workspace_context_tool
from app.agents.types import Tool


def build_brainstorm_tools(state: BrainstormState) -> list[Tool]:
    """构造 5 个绑定到同一 state 的 tool 实例"""
    return [
        build_detect_scene_tool(state),
        build_ask_user_tool(state),
        build_query_marketplace_tool(state),
        build_read_workspace_context_tool(state),
        build_emit_spec_tool(state),
    ]


__all__ = [
    "build_brainstorm_tools",
    "build_detect_scene_tool",
    "build_ask_user_tool",
    "build_query_marketplace_tool",
    "build_read_workspace_context_tool",
    "build_emit_spec_tool",
]
