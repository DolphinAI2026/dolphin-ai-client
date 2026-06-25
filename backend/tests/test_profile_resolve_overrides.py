"""SP2a T2: 行为由会话 mode 推导。

- narrow_tools_for_locked_ws:把 coding.py 里 _cutover_tool_names 的「ws_id 存在则
  砍枚举/新建 + app/env 级 apaas 工具」逻辑抽进 profile.py(去重,两边复用)。
- resolve_overrides_for_session:按 session.mode 返回 (system_prompt, tool_names_set,
  locked_ws_id)。mode='code' → dev-apaas 提示词 + 按 ws 收窄工具 + workspace_id;
  其它/未知 → (None, None, None)。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.agents.profile import (
    narrow_tools_for_locked_ws,
    resolve_overrides_for_session,
    resolve_profile,
)
from app.harness.profiles.coding import CodingProfile


_SAMPLE_TOOLS = (
    "list_dev_workspaces", "create_dev_workspace",      # 枚举/新建,会被砍
    "get_apaas_app_overview", "list_apaas_app_models",  # app/env 级,会被砍
    "read_workspace_file", "write_workspace_files",     # 工作区工具,保留
    "search_tools", "ask_clarifying_question",          # base 本地,保留
)


# ── narrow_tools_for_locked_ws ──────────────────────────────────────────

def test_narrow_with_ws_drops_enum_and_app_tools():
    out = narrow_tools_for_locked_ws(_SAMPLE_TOOLS, "ws-1")
    assert "list_dev_workspaces" not in out
    assert "create_dev_workspace" not in out
    assert "get_apaas_app_overview" not in out
    assert "list_apaas_app_models" not in out
    assert "read_workspace_file" in out
    assert "search_tools" in out


def test_narrow_without_ws_keeps_all():
    out = narrow_tools_for_locked_ws(_SAMPLE_TOOLS, "")
    assert set(out) == set(_SAMPLE_TOOLS)


def test_narrow_returns_tuple():
    assert isinstance(narrow_tools_for_locked_ws(_SAMPLE_TOOLS, "ws-1"), tuple)


# ── 等价性:抽取后与原 _cutover_tool_names 对同输入输出一致(防退化) ──

def test_equivalence_with_original_cutover_with_ws():
    """关键守门:抽出来的 narrow_tools_for_locked_ws 与原 classmethod 同输入同输出。"""
    original = CodingProfile._cutover_tool_names(_SAMPLE_TOOLS, "ws-1")
    extracted = narrow_tools_for_locked_ws(_SAMPLE_TOOLS, "ws-1")
    assert set(extracted) == set(original)


def test_equivalence_with_original_cutover_no_ws():
    original = CodingProfile._cutover_tool_names(_SAMPLE_TOOLS, "")
    extracted = narrow_tools_for_locked_ws(_SAMPLE_TOOLS, "")
    assert set(extracted) == set(original)


def test_equivalence_on_real_dev_apaas_tool_set():
    """用真实 dev-apaas 全量工具集做等价性(覆盖所有 drop 项)。"""
    profile = resolve_profile("dev-apaas")
    for ws in ("ws-real", ""):
        original = CodingProfile._cutover_tool_names(profile.tool_names, ws)
        extracted = narrow_tools_for_locked_ws(profile.tool_names, ws)
        assert set(extracted) == set(original), f"ws={ws!r} 不一致"


# ── resolve_overrides_for_session ────────────────────────────────────────

def test_resolve_code_session_returns_dev_apaas_triple():
    session = SimpleNamespace(mode="code", workspace_id="ws-42")
    sp, tn, ws = resolve_overrides_for_session(session)
    profile = resolve_profile("dev-apaas")
    assert sp == profile.system_prompt
    assert sp is not None and "确认即开干" in sp
    assert ws == "ws-42"
    # 工具集已按 ws 收窄
    assert tn is not None
    assert "list_dev_workspaces" not in tn
    assert "get_apaas_app_overview" not in tn
    assert set(tn) == set(narrow_tools_for_locked_ws(profile.tool_names, "ws-42"))


def test_resolve_code_session_without_ws_not_narrowed():
    session = SimpleNamespace(mode="code", workspace_id=None)
    sp, tn, ws = resolve_overrides_for_session(session)
    profile = resolve_profile("dev-apaas")
    assert sp == profile.system_prompt
    assert ws is None
    # 无 ws → 不收窄,等于全集
    assert set(tn) == set(profile.tool_names)


def test_resolve_chat_session_returns_none_triple():
    session = SimpleNamespace(mode="chat", workspace_id=None)
    assert resolve_overrides_for_session(session) == (None, None, None)


def test_resolve_cowork_session_returns_none_triple():
    session = SimpleNamespace(mode="cowork", workspace_id=None)
    assert resolve_overrides_for_session(session) == (None, None, None)


def test_resolve_unknown_mode_returns_none_triple():
    session = SimpleNamespace(mode="something-else", workspace_id="ws-x")
    assert resolve_overrides_for_session(session) == (None, None, None)
