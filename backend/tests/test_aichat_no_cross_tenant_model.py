"""AI Builder 使用平台共享模型配置 —— 回归测试。

LLM 配置已改为平台级共享，Builder 允许任一租户会话解析平台默认模型。
"""
import pytest

from app.ai_chat import agent as agent_module
from app.ai_chat.agent import _resolve_llm_config, _responses_input, _responses_message, _responses_tools
from app.crypto import encrypt_password
from app.models import LLMConfig, User
from app.models.tenant import Tenant
from app.models.ai_chat import AIChatSession


def _cfg(tenant_id, base):
    return LLMConfig(
        tenant_id=tenant_id, config_name="m", provider="dolphin",
        base_url=base, api_key_enc=encrypt_password("k"), model="gpt-5.5",
        purpose="all", is_default=True, status="active",
    )


@pytest.mark.asyncio
async def test_builder_uses_platform_shared_model(db_session):
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    db_session.add_all([t_a, t_b])
    await db_session.flush()

    # 只有租户 B 配了模型;租户 A 一个都没有
    db_session.add(_cfg(t_b.id, "https://tenant-b/v1"))
    await db_session.flush()

    sess_a = AIChatSession(tenant_id=t_a.id, user_id=1, title="x", selected_llm_config_id=None)
    db_session.add(sess_a)
    await db_session.flush()

    # LLM 配置是平台共享，租户 A 可以使用平台默认模型。
    snap = await _resolve_llm_config(db_session, sess_a)
    assert "tenant-b" in snap.base_url

    # 后创建的默认配置会成为新的平台默认。
    db_session.add(_cfg(t_a.id, "https://tenant-a/v1"))
    await db_session.flush()
    snap = await _resolve_llm_config(db_session, sess_a)
    assert "tenant-a" in snap.base_url, f"应解析最新平台默认模型,得到 {snap.base_url}"


@pytest.mark.asyncio
async def test_builder_reports_friendly_error_when_model_key_cannot_decrypt(db_session):
    tenant = Tenant(tenant_name="A", tenant_code="ta-invalid-key")
    db_session.add(tenant)
    await db_session.flush()

    db_session.add(
        LLMConfig(
            tenant_id=tenant.id,
            config_name="dolphin.ai",
            provider="dolphin",
            base_url="https://dolphin.example/v1",
            api_key_enc="invalid-fernet-token",
            model="gpt-5.5",
            purpose="all",
            is_default=True,
            status="active",
        )
    )
    await db_session.flush()

    session = AIChatSession(tenant_id=tenant.id, user_id=1, title="x")
    db_session.add(session)
    await db_session.flush()

    with pytest.raises(RuntimeError, match="模型配置.*API Key.*重新保存"):
        await _resolve_llm_config(db_session, session)


@pytest.mark.asyncio
async def test_system_assistant_resolves_coding_model(db_session):
    tenant = Tenant(tenant_name="SA", tenant_code="sa-coding-model")
    db_session.add(tenant)
    await db_session.flush()
    db_session.add_all([
        LLMConfig(
            tenant_id=tenant.id,
            config_name="Builder",
            provider="dolphin",
            base_url="https://builder.example/v1",
            api_key_enc=encrypt_password("builder-key"),
            model="builder-model",
            purpose="builder",
            is_default=True,
            status="active",
        ),
        LLMConfig(
            tenant_id=tenant.id,
            config_name="Coding",
            provider="dolphin",
            base_url="https://coding.example/v1",
            api_key_enc=encrypt_password("coding-key"),
            model="coding-model",
            purpose="coding",
            is_default=True,
            status="active",
        ),
    ])
    await db_session.flush()
    session = AIChatSession(
        tenant_id=tenant.id,
        user_id=1,
        title="系统助手",
        assistant_profile="system_assistant",
    )
    db_session.add(session)
    await db_session.flush()

    snapshot = await _resolve_llm_config(db_session, session)

    assert snapshot.model == "coding-model"
    assert snapshot.base_url == "https://coding.example/v1"


@pytest.mark.asyncio
async def test_desktop_builder_defaults_to_control_plane_model_not_empty_local_tenant(
    db_session,
    monkeypatch,
):
    user = User(
        username="desktop-control-plane-user",
        display_name="Desktop user",
        hashed_password="not-used",
        account_source="control_plane",
        coding_tenant_id="cp-tenant-42",
    )
    db_session.add(user)
    await db_session.flush()
    session = AIChatSession(
        tenant_id=999,
        user_id=user.id,
        title="Builder",
        control_plane_tenant_id="cp-tenant-42",
    )
    db_session.add(session)
    await db_session.flush()

    async def fake_catalog(**_kwargs):
        return [
            {"id": -101, "model": "online-default", "is_default": True},
            {"id": -102, "model": "online-other", "is_default": False},
        ]

    monkeypatch.setattr(agent_module.runtime, "is_desktop", lambda: True)
    monkeypatch.setattr(agent_module, "control_plane_access_token", lambda _user: "cp-token")
    monkeypatch.setattr(agent_module, "control_plane_base_url", lambda: "https://control.example")
    monkeypatch.setattr(agent_module, "list_control_plane_model_options", fake_catalog)

    snapshot = await _resolve_llm_config(db_session, session)

    assert snapshot.model == "online-default"
    assert snapshot.base_url == "https://control.example/api/code/model-gateway/v1"
    assert snapshot.api_format == "responses"
    assert snapshot.extra_headers["Authorization"] == "Bearer cp-token"
    assert snapshot.extra_headers["X-Tenant-Id"] == "cp-tenant-42"


def test_control_plane_responses_adapter_preserves_tool_turns():
    input_items = _responses_input([
        {"role": "system", "content": "You are helpful."},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call-1",
            "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
        }]},
        {"role": "tool", "tool_call_id": "call-1", "content": "file contents"},
    ])

    assert input_items[0]["role"] == "developer"
    assert input_items[1]["type"] == "function_call"
    assert input_items[2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "file contents",
    }
    assert _responses_tools([{
        "type": "function",
        "function": {"name": "read_file", "parameters": {"type": "object"}},
    }]) == [{
        "type": "function",
        "name": "read_file",
        "description": "",
        "parameters": {"type": "object"},
    }]
    assert _responses_message({"output": [
        {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
        {"type": "function_call", "call_id": "call-2", "name": "save", "arguments": "{}"},
    ]}) == {
        "content": "done",
        "tool_calls": [{
            "id": "call-2",
            "type": "function",
            "function": {"name": "save", "arguments": "{}"},
        }],
    }


@pytest.mark.asyncio
async def test_desktop_builder_reports_control_plane_catalog_failure(db_session, monkeypatch):
    user = User(
        username="desktop_catalog_failure_user",
        hashed_password="not-used",
        account_source="control_plane",
        coding_tenant_id="cp-tenant-failure",
    )
    db_session.add(user)
    await db_session.flush()
    session = AIChatSession(tenant_id=998, user_id=user.id, title="Builder")
    db_session.add(session)
    await db_session.flush()

    async def unavailable_catalog(**_kwargs):
        raise RuntimeError("503 Service Temporarily Unavailable")

    monkeypatch.setattr(agent_module.runtime, "is_desktop", lambda: True)
    monkeypatch.setattr(agent_module, "control_plane_access_token", lambda _user: "cp-token")
    monkeypatch.setattr(agent_module, "list_control_plane_model_options", unavailable_catalog)

    with pytest.raises(RuntimeError, match="线上模型目录加载失败.*503"):
        await _resolve_llm_config(db_session, session)
