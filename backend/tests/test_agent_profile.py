"""AgentProfile 地基测试 — 统一智能体引擎 Phase 0。

见 docs/superpowers/specs/2026-06-24-unified-agent-engine-design.md
"""
from __future__ import annotations

import dataclasses

import pytest

from app.agents.profile import AgentProfile, BASE_LOCAL_TOOLS, resolve_profile


# ── Task 1: AgentProfile 数据结构 ──────────────────────────────────


def test_agent_profile_is_frozen_and_holds_scenario_config():
    p = AgentProfile(
        name="demo",
        system_prompt="你是助手",
        tool_names=("write_file", "read_file"),
        skill_pack=("apaas-conventions",),
        use_mcp=True,
        max_turns=20,
    )
    assert p.name == "demo"
    assert p.tool_names == ("write_file", "read_file")
    assert p.skill_pack == ("apaas-conventions",)
    assert p.use_mcp is True
    assert p.max_turns == 20
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.name = "x"  # type: ignore[misc]


# ── Task 2: 工具白名单解析 + 命名 profile ──────────────────────────


def test_base_local_tools_cover_the_seven_exec_tools():
    for name in ("read_file", "write_file", "edit_file", "run_command",
                 "glob_files", "grep_search", "start_serve"):
        assert name in BASE_LOCAL_TOOLS


def test_dev_apaas_profile_unions_mcp_and_local_tools_minus_paused():
    p = resolve_profile("dev-apaas")
    # 本地执行工具在内(让 agent 能直接写文件)
    assert "write_file" in p.tool_names
    # MCP workspace 工具也在内(run_agent 现有好行为:读/写/跑 workspace)
    assert "write_workspace_files" in p.tool_names
    assert "read_workspace_file" in p.tool_names
    # business_event 暂停工具被排除
    from app.tool_registry import load as _load
    paused = {n for n, m in _load()["tools"].items() if m.get("category") == "business_event"}
    assert paused.isdisjoint(set(p.tool_names))
    # 无重复
    assert len(p.tool_names) == len(set(p.tool_names))


def test_resolve_unknown_profile_raises():
    with pytest.raises(KeyError):
        resolve_profile("nope")
