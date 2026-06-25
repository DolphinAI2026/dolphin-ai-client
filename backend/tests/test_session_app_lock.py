import pytest
from app.routes.ai_chat import CreateSessionRequest, _session_to_dict
from app.models.ai_chat import AIChatSession


def test_create_session_request_accepts_app_id():
    req = CreateSessionRequest(app_id=42)
    assert req.app_id == 42


def test_session_to_dict_exposes_app_id():
    s = AIChatSession(id=1, tenant_id=1, user_id=1, title="t", app_id=42)
    d = _session_to_dict(s)
    assert d["app_id"] == 42


def test_session_to_dict_exposes_workspace_id():
    s = AIChatSession(id=1, tenant_id=1, user_id=1, title="t", workspace_id="ws-x")
    d = _session_to_dict(s)
    assert d["workspace_id"] == "ws-x"


def test_create_session_request_accepts_code_mode_and_workspace_id():
    req = CreateSessionRequest(mode="code", workspace_id="ws-42")
    assert req.mode == "code"
    assert req.workspace_id == "ws-42"


def _coerce_mode(mode):
    # 镜像 create_session 里的 mode 归一逻辑（SP2b T9）
    return "code" if mode == "code" else ("cowork" if mode == "cowork" else "chat")


def test_create_session_mode_coercion_keeps_code():
    assert _coerce_mode("code") == "code"
    assert _coerce_mode("cowork") == "cowork"
    assert _coerce_mode("chat") == "chat"
    assert _coerce_mode(None) == "chat"
    assert _coerce_mode("bogus") == "chat"
