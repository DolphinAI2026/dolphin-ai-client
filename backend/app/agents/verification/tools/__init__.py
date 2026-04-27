"""VerificationAgent 工具集合（4 个）。"""
from __future__ import annotations

from pathlib import Path

from app.agents.types import Tool
from app.agents.verification.state import VerificationState
from app.agents.verification.tools.check_ac import build_check_ac_tool
from app.agents.verification.tools.emit_report import build_emit_report_tool
from app.agents.verification.tools.grep_code import build_grep_code_tool
from app.agents.verification.tools.read_file import build_read_file_tool


def build_verification_tools(state: VerificationState, workspace_root: Path) -> list[Tool]:
    return [
        build_grep_code_tool(state, workspace_root),
        build_read_file_tool(state, workspace_root),
        build_check_ac_tool(state),
        build_emit_report_tool(state),
    ]


__all__ = [
    "build_verification_tools",
    "build_grep_code_tool",
    "build_read_file_tool",
    "build_check_ac_tool",
    "build_emit_report_tool",
]
