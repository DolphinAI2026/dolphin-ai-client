"""harness ToolRegistry 简化后契约 — 统一智能体引擎 Phase 0 Task 3。

死 filter/_allowed_tools 无外部调用,已删。
"""
from __future__ import annotations

from app.harness.tool_registry import ToolRegistry


def test_registry_exposes_full_coding_definitions():
    reg = ToolRegistry(profile="coding")
    names = reg.tool_names
    for n in ("read_file", "write_file", "edit_file", "run_command"):
        assert n in names


def test_registry_has_no_dead_filter_api():
    reg = ToolRegistry(profile="coding")
    assert not hasattr(reg, "filter")
    assert not hasattr(reg, "_allowed_tools")
