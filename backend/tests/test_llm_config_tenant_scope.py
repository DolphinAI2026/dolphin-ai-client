"""平台共享 LLM 配置解析函数 —— 单测。

2026-06-07 后 LLM 配置改为平台级共享；这些函数保留 tenant_id 参数只是为了兼容
旧调用签名，不参与过滤。
"""
import pytest

from app.crypto import encrypt_password
from app.models import LLMConfig
from app.models.tenant import Tenant
from app.routes.llm_configs import (
    get_llm_config_for_purpose,
    list_llm_configs_for_purpose,
    get_active_llm_config_by_id,
    get_active_llm_config_by_id_for_purpose,
    _clear_defaults,
)


def _cfg(tenant_id, base, *, purpose="all", is_default=True):
    return LLMConfig(
        tenant_id=tenant_id, config_name="m", provider="dolphin",
        base_url=base, api_key_enc=encrypt_password("k"), model="gpt-5.5",
        purpose=purpose, is_default=is_default, status="active",
    )


async def _two_tenants_one_config(db):
    """租户 A 无配置;租户 B 有一条 default。返回 (a_id, b_id, b_config)。"""
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    db.add_all([t_a, t_b])
    await db.flush()
    b_cfg = _cfg(t_b.id, "https://tenant-b/v1")
    db.add(b_cfg)
    await db.flush()
    return t_a.id, t_b.id, b_cfg


@pytest.mark.asyncio
async def test_get_for_purpose_does_not_leak(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    assert (await get_llm_config_for_purpose(db_session, a_id, "builder")).id == b_cfg.id
    got = await get_llm_config_for_purpose(db_session, b_id, "builder")
    assert got is not None and got.id == b_cfg.id


@pytest.mark.asyncio
async def test_list_for_purpose_does_not_leak(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    rows_a = await list_llm_configs_for_purpose(db_session, a_id, "builder")
    assert [r.id for r in rows_a] == [b_cfg.id]
    rows = await list_llm_configs_for_purpose(db_session, b_id, "builder")
    assert [r.id for r in rows] == [b_cfg.id]


@pytest.mark.asyncio
async def test_get_by_id_does_not_leak(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    assert (await get_active_llm_config_by_id(db_session, a_id, b_cfg.id)).id == b_cfg.id
    assert (await get_active_llm_config_by_id_for_purpose(db_session, a_id, b_cfg.id, "all")).id == b_cfg.id
    assert (await get_active_llm_config_by_id(db_session, b_id, b_cfg.id)).id == b_cfg.id


@pytest.mark.asyncio
async def test_clear_defaults_only_touches_own_tenant(db_session):
    a_id, b_id, b_cfg = await _two_tenants_one_config(db_session)
    a_cfg = _cfg(a_id, "https://tenant-a/v1")
    db_session.add(a_cfg)
    await db_session.flush()
    await _clear_defaults(db_session, "all")
    await db_session.refresh(a_cfg)
    await db_session.refresh(b_cfg)
    assert a_cfg.is_default is False
    assert b_cfg.is_default is False, "平台默认清理应作用于全部共享模型配置"
