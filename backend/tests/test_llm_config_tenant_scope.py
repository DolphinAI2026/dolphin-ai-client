"""LLM 配置解析函数 —— 单测(按租户优先 + 回落共享兜底)。

2026-06-16 语义:每个租户可配自己的 LLM 模型,读取时**当前租户优先**;本租户没配
则**回落到全平台现有共享配置**(兜底)——桌面新号开箱即用、在线版零影响不报错。
list_llm_configs_for_purpose 只列本租户(管理页面"本租户有哪些"),不兜底。
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


async def _three_tenants(db):
    """A/B 各有自己的 default;C 无配置。返回 (a_id, b_id, c_id, a_cfg, b_cfg)。"""
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    t_c = Tenant(tenant_name="C", tenant_code="tc")
    db.add_all([t_a, t_b, t_c])
    await db.flush()
    a_cfg = _cfg(t_a.id, "https://tenant-a/v1")
    b_cfg = _cfg(t_b.id, "https://tenant-b/v1")
    db.add_all([a_cfg, b_cfg])
    await db.flush()
    return t_a.id, t_b.id, t_c.id, a_cfg, b_cfg


@pytest.mark.asyncio
async def test_tenant_with_own_config_uses_own(db_session):
    """A 查到 A 的、B 查到 B 的,不串。"""
    a_id, b_id, c_id, a_cfg, b_cfg = await _three_tenants(db_session)
    got_a = await get_llm_config_for_purpose(db_session, a_id, "builder")
    got_b = await get_llm_config_for_purpose(db_session, b_id, "builder")
    assert got_a is not None and got_a.id == a_cfg.id
    assert got_b is not None and got_b.id == b_cfg.id


@pytest.mark.asyncio
async def test_tenant_without_config_falls_back_shared(db_session):
    """C 没配,但全平台有 config → C 回落兜底拿到那条(不返回 None)。"""
    a_id, b_id, c_id, a_cfg, b_cfg = await _three_tenants(db_session)
    got_c = await get_llm_config_for_purpose(db_session, c_id, "builder")
    assert got_c is not None, "本租户没配不应返回 None,必须回落全平台共享兜底"
    assert got_c.id in {a_cfg.id, b_cfg.id}


@pytest.mark.asyncio
async def test_get_by_id_tenant_first_then_fallback(db_session):
    """先校验 id 属本租户;本租户没该 id 则回落按 id 全平台查。"""
    a_id, b_id, c_id, a_cfg, b_cfg = await _three_tenants(db_session)
    # A 自己的 id → 命中本租户
    assert (await get_active_llm_config_by_id(db_session, a_id, a_cfg.id)).id == a_cfg.id
    assert (
        await get_active_llm_config_by_id_for_purpose(db_session, a_id, a_cfg.id, "all")
    ).id == a_cfg.id
    # C 没有任何配置,传 B 的 id → 回落全平台按 id 查到 B 的(兜底)
    got = await get_active_llm_config_by_id(db_session, c_id, b_cfg.id)
    assert got is not None and got.id == b_cfg.id
    got2 = await get_active_llm_config_by_id_for_purpose(db_session, c_id, b_cfg.id, "all")
    assert got2 is not None and got2.id == b_cfg.id


@pytest.mark.asyncio
async def test_list_for_purpose_only_own_tenant_no_fallback(db_session):
    """list 只列本租户(管理页面),不兜底回落。"""
    a_id, b_id, c_id, a_cfg, b_cfg = await _three_tenants(db_session)
    rows_a = await list_llm_configs_for_purpose(db_session, a_id, "builder")
    assert [r.id for r in rows_a] == [a_cfg.id]
    rows_c = await list_llm_configs_for_purpose(db_session, c_id, "builder")
    assert rows_c == [], "list 是本租户视角,C 没配就空,不回落"


@pytest.mark.asyncio
async def test_clear_defaults_only_touches_own_tenant(db_session):
    """每租户唯一默认:清默认只清本租户,不动别租户。"""
    a_id, b_id, c_id, a_cfg, b_cfg = await _three_tenants(db_session)
    await _clear_defaults(db_session, a_id, "all")
    await db_session.refresh(a_cfg)
    await db_session.refresh(b_cfg)
    assert a_cfg.is_default is False, "本租户默认应被清"
    assert b_cfg.is_default is True, "别租户默认不应被波及"
