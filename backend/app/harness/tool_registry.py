"""Harness Core — Tool Registry

对 coding/tools.py 的薄包装，让 Agent 通过 registry 访问工具，
而不是直接 import 全局列表。未来可按 profile 过滤工具集。
"""
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.coding.tools import TOOL_DEFINITIONS, execute_tool


class ToolRegistry:
    """工具注册表。包装现有 tools.py，提供 profile 级别的过滤能力。"""

    def __init__(self, profile: str = "coding"):
        self._profile = profile
        self._definitions = list(TOOL_DEFINITIONS)
        # 未来可按 profile 过滤，当前 coding 用全量
        self._allowed_tools: set[str] | None = None

    @property
    def definitions(self) -> list[dict]:
        """返回给 LLM 的 tool schema（OpenAI function-calling 格式）。"""
        if self._allowed_tools is None:
            return self._definitions
        return [d for d in self._definitions if d.get("function", {}).get("name") in self._allowed_tools]

    @property
    def tool_names(self) -> list[str]:
        return [d.get("function", {}).get("name", "") for d in self.definitions]

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        workspace_path: Path,
        progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
    ) -> str:
        """执行工具调用，委托给 coding/tools.py。"""
        if self._allowed_tools and tool_name not in self._allowed_tools:
            return f"Error: tool '{tool_name}' is not allowed for profile '{self._profile}'"
        return await execute_tool(tool_name, arguments, workspace_path, progress_callback)

    def filter(self, allowed: set[str]) -> "ToolRegistry":
        """返回一个只包含指定工具的新 registry。"""
        filtered = ToolRegistry(self._profile)
        filtered._definitions = self._definitions
        filtered._allowed_tools = allowed
        return filtered
