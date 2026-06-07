from types import SimpleNamespace

from app.routes.ai_chat import (
    _deploy_error_from_record,
    _extract_generated_app_from_tool,
    _generation_status_label,
)
from app.routes.generation_steps import _first_meaningful_generation_error


def test_generation_steps_recovers_error_from_state_before_unknown_record():
    state = {
        "step_errors": {
            "stage:3": "表单创建失败: cannot access local variable 'components'",
        }
    }

    assert _first_meaningful_generation_error(state=state, event_log=[]) == state["step_errors"]["stage:3"]


def test_generation_steps_recovers_error_from_event_log_step():
    event_log = [
        {"stage": 3, "status": "running", "step": "创建表单..."},
        {"stage": 3, "status": "error", "step": "表单未完整创建，缺少 1 个"},
    ]

    assert _first_meaningful_generation_error(state={}, event_log=event_log) == "表单未完整创建，缺少 1 个"


def test_ai_chat_extracts_generated_app_from_tool_result():
    tool = SimpleNamespace(
        result_text='{"ok": true, "app_id": 11, "app_name": "客户拜访管理", "status": "draft"}',
    )

    assert _extract_generated_app_from_tool(tool) == {
        "app_id": 11,
        "app_name": "客户拜访管理",
        "app_code": None,
        "is_new": None,
        "tool_status": "draft",
    }


def test_ai_chat_deploy_error_falls_back_to_event_step_when_record_is_unknown():
    record = SimpleNamespace(
        error_message="未知错误",
        event_log_json=[
            {"stage": 3, "status": "error", "step": "表单创建失败: x"},
        ],
    )

    assert _deploy_error_from_record(record) == "表单创建失败: x"


def test_ai_chat_generation_status_label():
    assert _generation_status_label("success") == "生成成功"
    assert _generation_status_label("failed") == "生成失败"
    assert _generation_status_label("draft") == "草稿"
