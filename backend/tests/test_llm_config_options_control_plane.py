from types import SimpleNamespace

import pytest

import app.routes.llm_configs as llm_config_routes


@pytest.mark.asyncio
async def test_control_plane_code_model_options_use_remote_catalog_without_local_tenant(
    db_session, monkeypatch,
):
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            id=17,
            is_platform_admin=False,
            account_source="control_plane",
        ),
        tenant_id=0,
        tenant_role="member",
        tenant_access_scope="control_plane_code",
        control_plane_tenant_id="2077284540335579137",
    )

    async def fake_auth(*_args, **_kwargs):
        return "Bearer remote-token", "control_plane"

    async def fake_catalog(**kwargs):
        assert kwargs["purpose"] == "coding"
        assert kwargs["authorization_header"] == "Bearer remote-token"
        assert kwargs["delegated_context"] is ctx
        return [{
            "id": -17,
            "config_name": "企业 Coding 模型",
            "provider": "openai",
            "model": "gpt-5.5",
            "purpose": "coding",
            "is_default": True,
        }]

    import app.routes.code_runtime as code_runtime_routes

    monkeypatch.setattr(code_runtime_routes, "_control_plane_request_auth", fake_auth)
    monkeypatch.setattr(llm_config_routes, "list_control_plane_model_options", fake_catalog)

    result = await llm_config_routes.list_llm_config_options(
        ctx,
        db_session,
        purpose="coding",
    )

    assert [item.model for item in result] == ["gpt-5.5"]


@pytest.mark.asyncio
async def test_control_plane_model_catalog_accepts_code_generation_capability(monkeypatch):
    from app.code_runtime import control_plane_models

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return [{
                "modelCode": "gpt-code",
                "displayName": "GPT Code",
                "capabilities": ["code_generation"],
                "status": "enabled",
            }]

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(control_plane_models.httpx, "AsyncClient", Client)
    monkeypatch.setattr(control_plane_models, "control_plane_base_url", lambda: "https://cp.example")

    result = await control_plane_models.list_control_plane_model_options(
        purpose="coding",
        authorization_header="Bearer token",
        delegated_context=SimpleNamespace(control_plane_tenant_id="tenant-1"),
    )

    assert [item["model"] for item in result] == ["gpt-code"]
