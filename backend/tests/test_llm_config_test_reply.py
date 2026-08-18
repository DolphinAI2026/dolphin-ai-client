import httpx

from app.routes.llm_configs import _chat_model_test_body, _model_test_http_error, _test_reply_from_response


def test_chat_model_test_request_uses_only_openai_minimum_fields():
    # A few OpenAI-compatible gateways route correctly only when optional
    # generation controls are omitted. Keep this aligned with a basic curl.
    assert _chat_model_test_body("custom", "GLM-5.1") == {
        "model": "GLM-5.1",
        "messages": [{"role": "user", "content": "回复OK"}],
    }


def test_chat_test_reply_reports_null_choice_as_a_model_response_error():
    try:
        _test_reply_from_response({"choices": [None]}, is_codex=False, is_anthropic_compat=False)
    except ValueError as exc:
        assert "choices[0]" in str(exc)
    else:
        raise AssertionError("expected malformed response to be rejected")


def test_chat_test_reply_accepts_a_normal_openai_compatible_response():
    assert _test_reply_from_response(
        {"choices": [{"message": {"content": "OK"}}]},
        is_codex=False,
        is_anthropic_compat=False,
    ) == "OK"


def test_model_test_surfaces_jd_gateway_missing_instance_error():
    response = httpx.Response(
        404,
        json={"error": {"message": "Not found instance", "type": "invalid_instance_error"}},
    )

    assert _model_test_http_error(response) == (
        "模型服务找不到对应实例（HTTP 404: Not found instance）。"
        "当前 API 地址缺少该账号的实例/推理端点，请向服务提供方确认完整 Base URL。"
    )
