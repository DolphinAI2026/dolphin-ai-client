"""租户资源使用统计测试 — 资源数量不再做上限拦截。"""
import pytest
from fastapi import HTTPException

from app.auth import get_password_hash
from app.models import Application, MarketplaceComponent, User
from app.models.tenant import Tenant
from app.tenant_quota import (
    assert_tenant_quota,
    get_tenant_or_404,
    get_tenant_usage,
)


async def _seed_tenant(db_session, *, max_apps=2, max_ws=2, max_comps=2):
    t = Tenant(
        tenant_name="QuotaTest",
        tenant_code=f"qt_{id(db_session)}",
        max_applications=max_apps,
        max_workspaces=max_ws,
        max_components=max_comps,
        status=1,
    )
    db_session.add(t)
    user = User(username=f"qt_{id(db_session)}", hashed_password=get_password_hash("x"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    return t, user


@pytest.mark.asyncio
async def test_get_tenant_or_404_raises_for_unknown(db_session):
    with pytest.raises(HTTPException) as exc:
        await get_tenant_or_404(db_session, 999_999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assert_quota_passes_under_limit(db_session):
    t, _ = await _seed_tenant(db_session, max_apps=3)
    # 0 < 3，应通过
    await assert_tenant_quota(db_session, t.id, "applications")


@pytest.mark.asyncio
async def test_assert_quota_does_not_block_at_limit_for_applications(db_session):
    t, user = await _seed_tenant(db_session, max_apps=2)
    # seed 2 个 application，历史上这里会触发数量限制；现在应允许继续创建。
    for i in range(2):
        db_session.add(
            Application(
                user_id=user.id,
                tenant_id=t.id,
                created_by=user.id,
                app_name=f"a{i}",
                app_code=f"a{i}",
                status="draft",
            )
        )
    await db_session.flush()

    await assert_tenant_quota(db_session, t.id, "applications")


@pytest.mark.asyncio
async def test_assert_quota_does_not_block_at_limit_for_components(db_session):
    t, user = await _seed_tenant(db_session, max_comps=1)
    db_session.add(
        MarketplaceComponent(
            name="c1",
            code="c1",
            description="",
            category="cat",
            version="0.1",
            author_id=user.id,
            tenant_id=t.id,
            zip_path="",
        )
    )
    await db_session.flush()

    await assert_tenant_quota(db_session, t.id, "components")


@pytest.mark.asyncio
async def test_assert_quota_blocks_disabled_tenant(db_session):
    t, _ = await _seed_tenant(db_session)
    t.status = 0
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await assert_tenant_quota(db_session, t.id, "applications")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_tenant_usage_shape(db_session):
    t, user = await _seed_tenant(db_session, max_apps=5, max_ws=5, max_comps=5)
    db_session.add(
        Application(
            user_id=user.id, tenant_id=t.id, created_by=user.id,
            app_name="a", app_code="a", status="draft",
        )
    )
    await db_session.flush()

    usage = await get_tenant_usage(db_session, t.id)
    assert usage["applications"]["used"] == 1
    assert usage["applications"]["max"] == 5
    assert usage["workspaces"]["max"] == 5
    assert usage["components"]["max"] == 5
    assert "members" in usage
