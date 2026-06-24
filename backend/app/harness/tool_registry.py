"""Harness Core — Tool Registry

对 coding/tools.py 的薄包装,让 Agent 通过 registry 访问本地执行工具,
而不是直接 import 全局列表。
"""
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.coding.tools import TOOL_DEFINITIONS, execute_tool


class ToolRegistry:
    """本地执行工具注册表(read_file/write_file/edit_file/run_command/…)。"""

    def __init__(self, profile: str = "coding"):
        self._profile = profile
        self._definitions = list(TOOL_DEFINITIONS)

    @property
    def definitions(self) -> list[dict]:
        """返回给 LLM 的 tool schema(OpenAI function-calling 格式)。"""
        return self._definitions

    @property
    def tool_names(self) -> list[str]:
        return [d.get("function", {}).get("name", "") for d in self._definitions]

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        workspace_path: Path,
        progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
    ) -> str:
        """执行工具调用,委托给 coding/tools.py。"""
        return await execute_tool(tool_name, arguments, workspace_path, progress_callback)
