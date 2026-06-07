from app.routes.applications.generate import _generation_event_error_message


def test_generation_event_error_message_falls_back_to_step():
    event = {
        "stage": 3,
        "status": "error",
        "step": "表单创建失败: cannot access local variable 'components'",
    }

    assert _generation_event_error_message(event) == event["step"]


def test_generation_event_error_message_prefers_explicit_error():
    event = {
        "stage": 3,
        "status": "error",
        "error": "平台接口失败",
        "message": "生成失败",
        "step": "表单创建失败",
    }

    assert _generation_event_error_message(event) == "平台接口失败"
