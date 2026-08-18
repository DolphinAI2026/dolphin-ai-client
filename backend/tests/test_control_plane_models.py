import pytest

from app.code_runtime import control_plane_models


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses, requests):
        self.responses = responses
        self.requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, *, headers):
        self.requests.append((url, headers))
        return self.responses[url]


@pytest.mark.asyncio
async def test_control_plane_options_only_expose_litellm_models(monkeypatch):
    base_url = "https://control.example"
    requests = []
    responses = {
        f"{base_url}/api/code/model-gateway/v1/models": _Response(200, {
            "data": [
                {"id": "gpt-live", "owned_by": "litellm"},
                {"id": "qwen-live", "owned_by": "litellm"},
            ]
        }),
        f"{base_url}/api/code/desktop-runtime-model-catalog": _Response(200, {
            "defaultModel": "qwen-live"
        }),
    }
    monkeypatch.setattr(control_plane_models, "control_plane_base_url", lambda: base_url)
    monkeypatch.setattr(control_plane_models, "_control_plane_headers", lambda *_args, **_kwargs: {"Authorization": "Bearer token"})
    monkeypatch.setattr(
        control_plane_models.httpx,
        "AsyncClient",
        lambda **_kwargs: _Client(responses, requests),
    )

    options = await control_plane_models.list_control_plane_model_options(
        purpose="coding",
        authorization_header="Bearer token",
        delegated_context=object(),
    )

    assert [option["model"] for option in options] == ["gpt-live", "qwen-live"]
    assert [option["is_default"] for option in options] == [False, True]
    assert all("platform-catalog" not in url for url, _headers in requests)
