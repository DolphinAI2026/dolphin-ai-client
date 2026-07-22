import pytest
from sqlalchemy import select

from app import seed_data
from app.crypto import encrypt_password
from app.models import LLMConfig
from app.models.tenant import Tenant


@pytest.mark.asyncio
async def test_sync_builtin_llm_configs_keeps_specs_aligned_when_duplicate_skipped(
    db_session,
    monkeypatch,
):
    specs = [
        {
            "config_name": "内置通用模型 (gpt-5.5)",
            "provider": "dolphin",
            "base_url": "https://dolphin.example/v1",
            "api_key": "dolphin-key",
            "model": "gpt-5.5",
            "purpose": "all",
            "is_default": True,
            "max_tokens": 8192,
            "temperature": 0.3,
        },
        {
            "config_name": "内置通用模型 (Qwen 3.6 Plus)",
            "provider": "qwen",
            "base_url": "https://qwen.example/v1",
            "api_key": "qwen-key",
            "model": "qwen3.6-plus",
            "purpose": "all",
            "is_default": False,
            "max_tokens": 8192,
            "temperature": 0.3,
        },
    ]
    monkeypatch.setattr(seed_data, "_builtin_llm_specs", lambda: specs)

    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    db_session.add(
        LLMConfig(
            tenant_id=tenant.id,
            config_name="用户已有 Dolphin",
            provider="dolphin",
            base_url="https://custom.example/v1",
            api_key_enc=encrypt_password("custom-key"),
            model="gpt-5.5",
            purpose="all",
            is_default=False,
            max_tokens=4096,
            temperature=0.2,
            status="active",
        )
    )
    db_session.add(
        LLMConfig(
            tenant_id=tenant.id,
            config_name="内置 Coding GPT (gpt-5.4)",
            provider="dolphin",
            base_url="https://wrong-gpt54.example/v1",
            api_key_enc=encrypt_password("wrong-key"),
            model="gpt-5.4",
            purpose="coding",
            is_default=True,
            max_tokens=8192,
            temperature=0.3,
            status="active",
        )
    )
    await db_session.flush()

    await seed_data.sync_builtin_llm_configs(
        db_session,
        tenant_ids=[tenant.id],
        commit=False,
    )

    rows = (
        await db_session.execute(
            select(LLMConfig).where(LLMConfig.tenant_id == tenant.id)
        )
    ).scalars().all()
    by_name = {row.config_name: row for row in rows}

    assert "内置通用模型 (gpt-5.5)" not in by_name
    assert "内置 Coding GPT (gpt-5.4)" not in by_name
    assert by_name["用户已有 Dolphin"].is_default is True
    assert by_name["内置通用模型 (Qwen 3.6 Plus)"].purpose == "all"
    assert by_name["内置通用模型 (Qwen 3.6 Plus)"].is_default is False


def test_builtin_llm_specs_do_not_seed_gpt54(monkeypatch):
    monkeypatch.setattr(seed_data.settings, "dolphin_base_url", "https://dolphin.example")
    monkeypatch.setattr(seed_data.settings, "dolphin_api_key", "dolphin-key")
    monkeypatch.setattr(seed_data.settings, "dolphin_model", "gpt-5.5")
    monkeypatch.setattr(seed_data.settings, "coding_model_gpt54_base_url", "https://wrong-gpt54.example")
    monkeypatch.setattr(seed_data.settings, "coding_model_gpt54_api_key", "wrong-key")
    monkeypatch.setattr(seed_data.settings, "coding_model_gpt54_model", "gpt-5.4")
    monkeypatch.setattr(seed_data.settings, "coding_model_qwen_base_url", "https://qwen.example")
    monkeypatch.setattr(seed_data.settings, "coding_model_qwen_api_key", "qwen-key")

    specs = seed_data._builtin_llm_specs()

    assert {spec["model"] for spec in specs} == {"gpt-5.5", "qwen3.6-plus"}
    assert all(spec["config_name"] != "内置 Coding GPT (gpt-5.4)" for spec in specs)


@pytest.mark.asyncio
async def test_desktop_seed_skips_apaas_and_llm_initialization(db_session, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    calls: list[str] = []

    async def track_platform_env(*_args, **_kwargs):
        calls.append("apaas")

    async def track_llm(*_args, **_kwargs):
        calls.append("llm")

    monkeypatch.setattr(seed_data, "bind_default_tenant_platform_env", track_platform_env)
    monkeypatch.setattr(seed_data, "sync_builtin_llm_configs", track_llm)

    await seed_data.seed_initial_data(db_session)

    assert calls == []
