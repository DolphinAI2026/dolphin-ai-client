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
