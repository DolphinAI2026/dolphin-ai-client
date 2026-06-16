from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_resolve_effective_coding_model_resolves_llm_config_without_route_private_import(monkeypatch):
    from app.coding import pipeline

    async def fake_resolve_llm_config(db, tenant_id, *, purpose, selected_config_id=None):
        assert purpose == "coding"
        assert tenant_id == 64
        assert selected_config_id == 7
        return SimpleNamespace(model="gpt-test", config_id=7)

    monkeypatch.setattr("app.harness.llm_resolver.resolve_llm_config", fake_resolve_llm_config)

    model, config_id = await pipeline.resolve_effective_coding_model(
        MagicMock(),
        64,
        requested_model="llmcfg:7",
    )

    assert model == "gpt-test"
    assert config_id == 7
