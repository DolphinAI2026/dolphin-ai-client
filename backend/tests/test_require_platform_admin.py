import pytest
from types import SimpleNamespace
from fastapi import HTTPException


def _ctx(role, is_pa):
    return SimpleNamespace(tenant_role=role, user=SimpleNamespace(is_platform_admin=is_pa))


@pytest.mark.asyncio
async def test_allows_platform_admin():
    from app.deps import require_platform_admin
    ctx = _ctx("platform_admin", False)
    assert await require_platform_admin(ctx) is ctx


@pytest.mark.asyncio
async def test_allows_user_flag():
    from app.deps import require_platform_admin
    ctx = _ctx("member", True)
    assert await require_platform_admin(ctx) is ctx


@pytest.mark.asyncio
async def test_rejects_tenant_admin():
    from app.deps import require_platform_admin
    with pytest.raises(HTTPException) as ei:
        await require_platform_admin(_ctx("tenant_admin", False))
    assert ei.value.status_code == 403
