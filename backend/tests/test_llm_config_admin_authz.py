"""admin LLM 配置端点:租户作用域 + 归属授权。

直接调用路由函数(Depends 只是普通参数),手构 AuthContext。

⚠️ 整文件 skip(2026-06-12): 本文件测的是「LLM 配置按租户严格隔离」模型
(2026-06-06 c5c7184e 落地), 但 2026-06-07 8068d895 把端点改回了
「平台级共享」(list 仅平台管理员、options 忽略租户、create 无 tenant_id),
两个方向冲突, 7 个用例永远红。待产品方向拍板:
- 维持平台共享 → 删本文件
- 恢复租户隔离 → 还原 8068d895 中 llm_configs.py 的改动并解除 skip
"""
import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.skip(
    reason="LLM 配置租户隔离(c5c7184e) 与平台共享(8068d895) 方向冲突, 待拍板 — 见文件头注释"
)

from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import LLMConfig, User
from app.models.tenant import Tenant
from app.routes.llm_configs import (
    LLMConfigCreate,
    list_llm_configs,
    create_llm_config,
    update_llm_config,
    LLMConfigUpdate,
)


def _cfg(tenant_id, base):
    return LLMConfig(
        tenant_id=tenant_id, config_name="m", provider="dolphin",
        base_url=base, api_key_enc=encrypt_password("k"), model="gpt-5.5",
        purpose="all", is_default=True, status="active",
    )


async def _setup(db):
    t_a = Tenant(tenant_name="A", tenant_code="ta")
    t_b = Tenant(tenant_name="B", tenant_code="tb")
    db.add_all([t_a, t_b])
    await db.flush()
    a_cfg, b_cfg = _cfg(t_a.id, "https://a/v1"), _cfg(t_b.id, "https://b/v1")
    db.add_all([a_cfg, b_cfg])
    await db.flush()
    return t_a, t_b, a_cfg, b_cfg


def _ctx(db, tenant_id, *, platform=False):
    user = User(username=f"u{tenant_id}{platform}", hashed_password="x", is_platform_admin=platform)
    db.add(user)
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="platform_admin" if platform else "tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_tenant_admin_list_sees_only_own(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id)
    rows = await list_llm_configs(ctx, db_session, tenant_id=t_b.id)
    assert [r.id for r in rows] == [a_cfg.id]


@pytest.mark.asyncio
async def test_platform_admin_list_with_tenant_id(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id, platform=True)
    rows = await list_llm_configs(ctx, db_session, tenant_id=t_b.id)
    assert [r.id for r in rows] == [b_cfg.id]


@pytest.mark.asyncio
async def test_tenant_admin_cannot_edit_other_tenant(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id)
    with pytest.raises(HTTPException) as exc:
        await update_llm_config(b_cfg.id, LLMConfigUpdate(model="x"), ctx, db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_platform_admin_create_lands_on_target_tenant(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id, platform=True)
    req = LLMConfigCreate(
        config_name="new", provider="dolphin", base_url="https://new/v1",
        api_key="k", model="gpt-5.5", purpose="all", tenant_id=t_b.id,
    )
    created = await create_llm_config(req, ctx, db_session)
    row = (await db_session.get(LLMConfig, created.id))
    assert row.tenant_id == t_b.id


@pytest.mark.asyncio
async def test_tenant_admin_create_ignores_body_tenant_id(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id)
    req = LLMConfigCreate(
        config_name="new", provider="dolphin", base_url="https://new/v1",
        api_key="k", model="gpt-5.5", purpose="all", tenant_id=t_b.id,
    )
    created = await create_llm_config(req, ctx, db_session)
    row = (await db_session.get(LLMConfig, created.id))
    assert row.tenant_id == t_a.id, "租户管理员创建必须落到自己租户"


@pytest.mark.asyncio
async def test_platform_admin_create_rejects_unknown_tenant(db_session):
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    ctx = _ctx(db_session, t_a.id, platform=True)
    req = LLMConfigCreate(
        config_name="new", provider="dolphin", base_url="https://new/v1",
        api_key="k", model="gpt-5.5", purpose="all", tenant_id=999999,
    )
    with pytest.raises(HTTPException) as exc:
        await create_llm_config(req, ctx, db_session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_platform_admin_create_rejects_disabled_tenant(db_session):
    from app.models.tenant import Tenant
    t_a, t_b, a_cfg, b_cfg = await _setup(db_session)
    t_disabled = Tenant(tenant_name="D", tenant_code="td", status=0)
    db_session.add(t_disabled)
    await db_session.flush()
    ctx = _ctx(db_session, t_a.id, platform=True)
    req = LLMConfigCreate(
        config_name="new", provider="dolphin", base_url="https://new/v1",
        api_key="k", model="gpt-5.5", purpose="all", tenant_id=t_disabled.id,
    )
    with pytest.raises(HTTPException) as exc:
        await create_llm_config(req, ctx, db_session)
    assert exc.value.status_code == 400
