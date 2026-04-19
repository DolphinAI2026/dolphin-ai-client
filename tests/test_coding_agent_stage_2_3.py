"""CodingAgent Stage 2.3 单测：Prompt 构造（build_user_prompt）。

核心验证：CodingAgent.build_initial_user_message() 与 VibeCodingAgent._build_prompt()
在所有 project_type 下**字节级完全一致**（纯搬迁，不改行为）。
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.coding import CodingAgent
from app.agents.coding.prompts import build_user_prompt, render_form_component_sections
from app.agents.publisher import InMemoryEventPublisher
from app.agents.trace_writer import InMemoryTraceWriter
from app.agents.types import AgentContext
from app.coding.vibe_agent import VibeCodingAgent


# ══════════════════════════════════════════════════════════════
# build_user_prompt 与 VibeCodingAgent._build_prompt 一致性
# ══════════════════════════════════════════════════════════════

def _compare_prompts(project_type: str, conversation_summary: str = "", requirement: str = "做个测试") -> None:
    """对比新旧两套 prompt 构造输出是否完全一致。"""
    fake_info = {
        "project_name": "test-comp",
        "project_type": project_type,
        "files": [".cursor/rules/widget-config.mdc"] if "component" in project_type else [],
    }
    ws_path = Path("/tmp/ws")

    # 新：build_user_prompt
    new_prompt = build_user_prompt(
        requirement=requirement,
        conversation_summary=conversation_summary,
        workspace_info=fake_info,
        workspace_path=ws_path,
    )

    # 旧：VibeCodingAgent._build_prompt
    class FakeWsMgr:
        def get_workspace_info(self, ws_id):
            return fake_info

    agent = VibeCodingAgent.__new__(VibeCodingAgent)
    agent.ws_id = "x"
    agent.ws_mgr = FakeWsMgr()
    agent.ws_path = ws_path
    agent._system_prompt = "s"
    agent.tenant_id = 1
    old_prompt = agent._build_prompt(requirement=requirement, conversation_summary=conversation_summary)

    assert new_prompt == old_prompt, (
        f"{project_type}: prompt 不一致 new={len(new_prompt)} old={len(old_prompt)}"
    )


def test_prompt_identical_form_component():
    _compare_prompts("form-component")


def test_prompt_identical_form_component_dual():
    _compare_prompts("form-component-dual")


def test_prompt_identical_menu_page():
    _compare_prompts("menu-page")


def test_prompt_identical_form_page():
    _compare_prompts("form-page")


def test_prompt_identical_mobile_page():
    _compare_prompts("mobile-page")


def test_prompt_identical_layout():
    _compare_prompts("layout")


def test_prompt_identical_form_list():
    _compare_prompts("form-list")


def test_prompt_identical_plugin():
    _compare_prompts("plugin")


def test_prompt_identical_backend_api():
    _compare_prompts("backend-api")


def test_prompt_identical_with_conversation_summary():
    _compare_prompts("form-component-dual", conversation_summary="之前讨论了主色可配，默认 5 星")


def test_prompt_identical_with_rule_files():
    """多个 .cursor/rules/*.mdc 文件都应列在 Workspace Rules 段"""
    fake_info = {
        "project_name": "t",
        "project_type": "form-component-dual",
        "files": [
            ".cursor/rules/apaas-form-component-dual-dev.mdc",
            ".cursor/rules/widget-config.mdc",
            ".cursor/rules/setting-vue.mdc",
            ".cursor/rules/editor-config.mdc",
            "src/index.js",  # 非 mdc 规则文件，不应被列入
        ],
    }
    new = build_user_prompt(
        requirement="r",
        conversation_summary="",
        workspace_info=fake_info,
        workspace_path=Path("/tmp/ws"),
    )
    # 4 个 .mdc 规则都应出现
    assert "apaas-form-component-dual-dev.mdc" in new
    assert "widget-config.mdc" in new
    assert "setting-vue.mdc" in new
    assert "editor-config.mdc" in new
    # index.js 不应作为 rule 被列入
    assert "- Read and follow `src/index.js`" not in new


# ══════════════════════════════════════════════════════════════
# render_form_component_sections 路径替换
# ══════════════════════════════════════════════════════════════

def test_render_form_component_sections_single_end_base_path():
    """单端 base_path=src 时，__BASE_PATH__ 应全部替换为 src"""
    text = render_form_component_sections("src")
    assert "__BASE_PATH__" not in text
    assert "src/form-component-config/form-widget" in text
    assert "src/form-component/form-editor" in text


def test_render_form_component_sections_dual_end_base_path():
    """双端 base_path=web/src"""
    text = render_form_component_sections("web/src")
    assert "__BASE_PATH__" not in text
    assert "web/src/form-component-config/form-widget" in text
    assert "web/src/form-component/form-editor" in text


# ══════════════════════════════════════════════════════════════
# CodingAgent.build_initial_user_message 集成
# ══════════════════════════════════════════════════════════════

def _make_ctx(workspace_id=None, input_data=None):
    return AgentContext(
        session_id="test_s",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="test-model",
        workspace_id=workspace_id,
        input=input_data or {"requirement": "t"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
    )


def test_agent_system_prompt_default():
    """默认 system prompt 走 AGENT_SYSTEM_PROMPT（不再是占位）"""
    from app.coding.prompts import AGENT_SYSTEM_PROMPT
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    assert agent.get_system_prompt() == AGENT_SYSTEM_PROMPT
    assert "aPaaS" in agent.get_system_prompt()


def test_agent_system_prompt_override():
    """ctx.input.system_prompt 可覆盖"""
    ctx = _make_ctx(input_data={"requirement": "t", "system_prompt": "Custom sys"})
    agent = CodingAgent(ctx)
    assert agent.get_system_prompt() == "Custom sys"


def test_agent_build_initial_message_without_workspace():
    """没有 workspace_id 时退化为 project_type 空的默认 workflow（form-component 单端）"""
    ctx = _make_ctx(workspace_id=None, input_data={
        "requirement": "需求文本",
        "conversation_summary": "summary 内容",
    })
    msg = CodingAgent(ctx).build_initial_user_message()

    # Task 段
    assert "## Task\n需求文本" in msg
    # Summary 段
    assert "summary 内容" in msg
    # workflow 进入默认分支（form-component）
    assert "## Workflow" in msg


def test_agent_build_initial_message_with_workspace_info(monkeypatch=None):
    """有 workspace_id 时注入 project_name / project_type / files 到 prompt — 用 mock WorkspaceManager（避免依赖 APAAS_WORKSPACE_ROOT 环境）"""
    from app.coding import workspace as ws_module

    class FakeWsMgr:
        def get_workspace_info(self, ws_id):
            return {
                "id": ws_id,
                "project_name": "rating-star",
                "project_type": "form-component-dual",
                "files": [".cursor/rules/widget-config.mdc"],
            }

        def get_workspace_path(self, ws_id):
            return Path("/tmp/fake_ws")

    original_cls = ws_module.WorkspaceManager
    ws_module.WorkspaceManager = FakeWsMgr   # type: ignore[assignment]
    try:
        ctx = _make_ctx(
            workspace_id="test_ws_fake",
            input_data={"requirement": "做评分组件", "conversation_summary": ""},
        )
        msg = CodingAgent(ctx).build_initial_user_message()
    finally:
        ws_module.WorkspaceManager = original_cls  # type: ignore[assignment]

    # Workspace info 正确注入
    assert "rating-star" in msg
    assert "form-component-dual" in msg
    # Rule 文件列出
    assert "widget-config.mdc" in msg
    # 走 dual 工作流（包含 SHARED web/src 路径）
    assert "web/src" in msg


if __name__ == "__main__":
    import inspect, traceback as _tb
    current = sys.modules[__name__]
    tests = [
        (n, f) for n, f in inspect.getmembers(current, inspect.isfunction)
        if n.startswith("test_")
    ]
    passed = failed = 0
    for name, func in tests:
        try:
            func()
            print(f"✓ {name}")
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}")
            _tb.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
