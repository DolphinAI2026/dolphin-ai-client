"""Spec → CodingAgent 桥接测试。

覆盖：
- build_coding_input_from_spec：字段映射 + 场景 → project_type 映射
- render_spec_brief：三种场景（component/page/backend）的 markdown 渲染
- build_user_prompt：spec_brief 注入路径 + 保持旧 snapshot 兼容（不传 spec_brief 时字节级一致）
- CodingAgent.build_initial_user_message：Spec 驱动路径
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.coding import CodingAgent  # noqa: E402
from app.agents.coding.prompts import build_user_prompt  # noqa: E402
from app.agents.coding.spec_bridge import (  # noqa: E402
    build_coding_input_from_spec,
    render_spec_brief,
    scene_to_project_type,
)
from app.agents.publisher import InMemoryEventPublisher  # noqa: E402
from app.agents.trace_writer import InMemoryTraceWriter  # noqa: E402
from app.agents.types import AgentContext  # noqa: E402

_SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "prompt_snapshots"


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

def _component_envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_component_dual",
        "spec_id": "spec_x",
        "provenance": {
            "version": 1,
            "confidence": 0.9,
            "open_questions": [{"question": "主色?", "assumed_answer": "#409EFF"}],
            "created_by": "agent",
        },
        "identity": {
            "code_name": "rating-star",
            "display_name": "评分",
            "description_cn": "星级评分",
            "widget_code": "FORM_CUSTOM_RATING_STAR",
        },
        "intent": {
            "original_requirement": "做个评分",
            "core_purpose": "1-5 星打分",
            "acceptance_criteria": ["用户可点击 1~5 星", "主色可配置"],
        },
        "spec": {
            "data": {
                "bof_type": "BOF_NUMBER",
                "component_model_field": ["NUM"],
                "form_value_shape": "scalar",
                "default_value": 0,
                "storage_note": "1-5 整数",
            },
            "config_properties": [
                {
                    "key": "primaryColor", "type": "string", "label": "主色",
                    "default": "#409EFF", "required": False,
                    "ui_editor": "form-custom-color-editor", "is_custom_editor": False,
                },
            ],
            "scenes_required": ["edit", "read"],
            "scenes_optional": [],
            "constraints_hard": ["禁止 innerHTML"],
            "constraints_soft": ["主色用 CSS variable"],
            "third_party_deps": ["lodash"],
        },
    }


def _page_envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "web_page",
        "spec_id": "spec_p",
        "provenance": {"version": 1, "confidence": 0.8, "open_questions": [], "created_by": "agent"},
        "identity": {"code_name": "order-list", "display_name": "订单列表", "description_cn": "订单管理页面"},
        "intent": {
            "original_requirement": "做个订单列表",
            "core_purpose": "展示订单并支持查询",
            "acceptance_criteria": ["支持关键字搜索", "分页展示"],
        },
        "spec": {
            "route": {"router_name": "apaas-custom-order-list", "menu_title": "订单"},
            "layout": "standard",
            "data_sources": [
                {"name": "orders", "type": "api", "endpoint": "/api/orders", "method": "GET"},
            ],
            "ui_sections": [
                {"name": "search", "type": "search_form", "is_custom_type": False,
                 "config": {"fields": ["keyword"]}},
                {"name": "main", "type": "table", "is_custom_type": False,
                 "config": {"columns": ["id", "amount"]}},
            ],
        },
    }


def _backend_envelope() -> dict:
    return {
        "schema_version": "1.0",
        "scene_type": "backend_api",
        "spec_id": "spec_b",
        "provenance": {"version": 1, "confidence": 0.85, "open_questions": [], "created_by": "agent"},
        "identity": {"code_name": "order-api", "display_name": "订单接口", "description_cn": "订单 CRUD"},
        "intent": {
            "original_requirement": "给订单加接口",
            "core_purpose": "创建 + 查询订单",
            "acceptance_criteria": ["创建返回订单 ID"],
        },
        "spec": {
            "package_name": "com.xdap.custom.order",
            "endpoints": [
                {"path": "/custom/order/create", "method": "POST", "description": "创建订单",
                 "request": {"amount": {"type": "number", "required": True}}},
                {"path": "/custom/order/get", "method": "GET", "description": "查订单"},
            ],
            "mpaas_tables": [{"name": "t_order", "access": "readwrite"}],
            "permissions": ["order.create", "order.read"],
        },
    }


def _ctx(input_data: dict = None) -> AgentContext:
    return AgentContext(
        session_id="c_s1", conversation_id=1, user_id=1, tenant_id=1, model="m",
        input=input_data or {"requirement": "t"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
    )


# ══════════════════════════════════════════════════════════════
# scene_to_project_type
# ══════════════════════════════════════════════════════════════

def test_scene_to_project_type_map():
    assert scene_to_project_type("web_component_dual") == "form-component-dual"
    assert scene_to_project_type("web_page") == "form-page"
    assert scene_to_project_type("mobile_page") == "mobile-page"
    assert scene_to_project_type("backend_api") == "backend-api"
    assert scene_to_project_type("backend_feign") == "backend-api"
    assert scene_to_project_type("backend_scheduled") == "backend-api"
    assert scene_to_project_type("unknown") == "form-component-dual"


# ══════════════════════════════════════════════════════════════
# build_coding_input_from_spec
# ══════════════════════════════════════════════════════════════

def test_build_input_component_basic():
    env = _component_envelope()
    inp = build_coding_input_from_spec(env)
    assert inp["requirement"] == "1-5 星打分"  # = core_purpose
    assert inp["scene_type"] == "web_component_dual"
    assert inp["project_type"] == "form-component-dual"
    assert inp["spec_envelope"] is env
    assert "rating-star" in inp["spec_brief"]
    assert inp["max_turns"] == 30
    assert inp["conversation_summary"] == ""


def test_build_input_falls_back_to_original_requirement_when_no_core_purpose():
    env = _component_envelope()
    env["intent"]["core_purpose"] = ""
    inp = build_coding_input_from_spec(env)
    assert inp["requirement"] == "做个评分"  # = original_requirement


def test_build_input_missing_intent_uses_placeholder():
    env = _component_envelope()
    env["intent"] = {}
    inp = build_coding_input_from_spec(env)
    assert inp["requirement"] == "(missing requirement)"


def test_build_input_accepts_extra():
    env = _component_envelope()
    inp = build_coding_input_from_spec(env, conversation_summary="之前的对话", max_turns=50, extra={"system_prompt": "sys"})
    assert inp["conversation_summary"] == "之前的对话"
    assert inp["max_turns"] == 50
    assert inp["system_prompt"] == "sys"


def test_build_input_extra_does_not_override_core_fields():
    env = _component_envelope()
    inp = build_coding_input_from_spec(env, extra={"requirement": "hijacked"})
    assert inp["requirement"] != "hijacked"  # 核心字段保护


def test_build_input_rejects_non_dict_envelope():
    try:
        build_coding_input_from_spec("not a dict")  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("expected TypeError")


# ══════════════════════════════════════════════════════════════
# render_spec_brief
# ══════════════════════════════════════════════════════════════

def test_render_brief_component_contains_key_sections():
    env = _component_envelope()
    out = render_spec_brief(env)
    assert "# 结构化需求" in out
    assert "## 标识" in out
    assert "rating-star" in out
    assert "FORM_CUSTOM_RATING_STAR" in out
    assert "## 意图" in out
    assert "1-5 星打分" in out
    assert "## 验收点" in out
    assert "用户可点击 1~5 星" in out
    assert "## 组件规格" in out
    assert "BOF_NUMBER" in out
    assert "primaryColor" in out
    assert "form-custom-color-editor" in out
    assert "## 约束" in out
    assert "禁止 innerHTML" in out
    assert "## 默认假设" in out
    assert "主色?" in out


def test_render_brief_page_contains_routing_and_sections():
    env = _page_envelope()
    out = render_spec_brief(env)
    assert "web_page" in out
    assert "## 页面规格" in out
    assert "apaas-custom-order-list" in out
    assert "search_form" in out
    assert "table" in out


def test_render_brief_backend_contains_endpoints():
    env = _backend_envelope()
    out = render_spec_brief(env)
    assert "## 后端规格" in out
    assert "com.xdap.custom.order" in out
    assert "POST /custom/order/create" in out
    assert "GET /custom/order/get" in out
    assert "t_order" in out
    assert "readwrite" in out


def test_render_brief_skips_missing_optional_sections():
    env = _component_envelope()
    env["spec"]["constraints_hard"] = []
    env["spec"]["constraints_soft"] = []
    env["provenance"]["open_questions"] = []
    env["spec"]["third_party_deps"] = []
    out = render_spec_brief(env)
    assert "## 约束" not in out
    assert "## 默认假设" not in out
    assert "### 三方依赖" not in out


# ══════════════════════════════════════════════════════════════
# build_user_prompt：spec_brief 注入 + 旧路径兼容
# ══════════════════════════════════════════════════════════════

def test_build_user_prompt_without_spec_brief_matches_old_snapshot():
    """不传 spec_brief 时 —— 字节级与现有 snapshot 完全一致（P1 兼容承诺）"""
    fake_info = {
        "project_name": "test-comp",
        "project_type": "form-component-dual",
        "files": [".cursor/rules/widget-config.mdc"],
    }
    out = build_user_prompt(
        requirement="做个测试",
        conversation_summary="",
        workspace_info=fake_info,
        workspace_path=Path("/tmp/ws"),
        # 不传 spec_brief
    )
    expected = (_SNAPSHOT_DIR / "form_component_dual.txt").read_text()
    assert out == expected, f"snapshot 漂移，len new={len(out)} expected={len(expected)}"


def test_build_user_prompt_with_spec_brief_inserts_structured_section():
    fake_info = {
        "project_name": "x", "project_type": "form-component-dual",
        "files": [".cursor/rules/widget-config.mdc"],
    }
    spec_brief = "# 结构化需求\n## 标识\n- code_name: `x`"
    out = build_user_prompt(
        requirement="原话",
        conversation_summary="",
        workspace_info=fake_info,
        workspace_path=Path("/tmp/ws"),
        spec_brief=spec_brief,
    )
    # 结构：Task → Structured Spec → Workspace Info → Workspace Rules → Summary → Workflow
    assert "## Task\n原话" in out
    assert "## Structured Spec (from BrainstormAgent)" in out
    assert "code_name: `x`" in out
    # 顺序检查：Structured Spec 应在 Workspace Info 之前
    idx_spec = out.find("## Structured Spec")
    idx_ws = out.find("## Workspace Info")
    assert idx_spec != -1 and idx_spec < idx_ws


def test_build_user_prompt_empty_spec_brief_is_ignored():
    fake_info = {"project_name": "x", "project_type": "form-component-dual", "files": []}
    out = build_user_prompt(
        requirement="r",
        conversation_summary="",
        workspace_info=fake_info,
        workspace_path=Path("/tmp/ws"),
        spec_brief="",   # empty str 视同 None
    )
    assert "## Structured Spec" not in out


# ══════════════════════════════════════════════════════════════
# CodingAgent.build_initial_user_message: Spec 驱动路径
# ══════════════════════════════════════════════════════════════

def test_agent_build_message_spec_driven_injects_structured_section():
    env = _component_envelope()
    inp = build_coding_input_from_spec(env)
    ctx = _ctx(input_data=inp)
    msg = CodingAgent(ctx).build_initial_user_message()
    # Task 段应是 core_purpose
    assert "## Task\n1-5 星打分" in msg
    # Structured Spec 段应存在
    assert "## Structured Spec (from BrainstormAgent)" in msg
    # Spec 里的关键字段都出现
    assert "FORM_CUSTOM_RATING_STAR" in msg
    assert "primaryColor" in msg
    assert "form-custom-color-editor" in msg
    # project_type 注入 → workflow 模板选对（form-component-dual）
    assert "web/src" in msg  # dual 路径独有


def test_agent_build_message_without_spec_envelope_keeps_old_path():
    """ctx.input 只有 requirement 时，走老路径（无 Structured Spec 段）"""
    ctx = _ctx(input_data={"requirement": "做个评分", "conversation_summary": ""})
    msg = CodingAgent(ctx).build_initial_user_message()
    assert "## Structured Spec" not in msg
    assert "## Task\n做个评分" in msg


def test_agent_build_message_spec_driven_backend_selects_backend_workflow():
    env = _backend_envelope()
    inp = build_coding_input_from_spec(env)
    ctx = _ctx(input_data=inp)
    msg = CodingAgent(ctx).build_initial_user_message()
    assert "## Structured Spec" in msg
    # backend_api scene → project_type=backend-api → 走 backend workflow
    # （验收：backend workflow 的特征词；至少不应该包含 form-component 的 scaffold 路径）
    assert "com.xdap" in msg or "backend" in msg.lower()


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
