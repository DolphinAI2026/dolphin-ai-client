from types import SimpleNamespace

import pytest

from app.code_runtime import control_plane_models
from app.routes.llm_configs import list_llm_config_options


@pytest.mark.asyncio
async def test_control_plane_code_model_options_do_not_require_local_tenant(
    db_session,
    monkeypatch,
):
    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "code": "OK",
                "data": {
                    "table": [
                        {
                            "modelId": 1782119249072,
                            "modelCode": "gpt-5.5",
                            "modelDisplayName": "GPT-5.5",
                            "modelKind": "chat",
                            "enabled": True,
                            "defaultModel": True,
                            "provider": {
                                "providerCode": "OpenAI-geekery",
                                "providerName": "OpenAI-geekery",
                                "enabled": True,
                            },
                        }
                    ]
                },
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv(
        "DOLPHIN_CODE_CONTROL_PLANE_URL",
        "https://code.example.com/control-plane",
    )
    monkeypatch.setattr(control_plane_models.httpx, "AsyncClient", FakeClient)
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            id=17,
            account_source="control_plane",
            coding_access_token="control-plane-token",
            coding_refresh_token=None,
        ),
        tenant_id=0,
        tenant_access_scope="control_plane_code",
        control_plane_tenant_id="2077284540335579137",
    )

    result = await list_llm_config_options(ctx, db_session, purpose="coding")

    assert [item.model_dump() for item in result] == [
        {
            "id": 1782119249072,
            "config_name": "GPT-5.5",
            "provider": "OpenAI-geekery",
            "model": "gpt-5.5",
            "purpose": "coding",
            "is_default": True,
        }
    ]
    assert calls == [
        {
            "url": "https://code.example.com/control-plane/api/ai-models",
            "headers": {
                "Authorization": "Bearer control-plane-token",
                "X-Tenant-Id": "2077284540335579137",
            },
            "params": {
                "enabled": "true",
                "modelType": "chat",
                "page": 1,
                "pageSize": 100,
            },
        }
    ]
