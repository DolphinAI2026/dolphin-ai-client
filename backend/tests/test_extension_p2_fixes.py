"""PR6 reviewer P2 修复测试 — notify EDIT auth / republish 幂等.

覆盖:
- notify_extension_update 对非 owner / 无 EDIT 权限的成员返 403
- notify_extension_update 对 app 创建者 (owner) 成功广播 (返 ok + delivered)
- _should_dedup_republish 在 5s 窗口内同 app_id 第二次返 deduped=True
- _should_dedup_republish 不同 app_id 互不干扰
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, Tenant, User
from app.models.tenant import UserTenant
from app.permissions import Action


# ─────────── seed helpers ───────────


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _seed_app_with_owner_and_viewer(db_session):
    """Seed: tenant + owner (creator) + viewer (tenant member, 无 EDIT 权限) + 1 app."""
    tenant = Tenant(tenant_name="t-ext", tenant_code="t-ext")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "ext-owner")
    viewer = await _make_user(db_session, "ext-viewer")

    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=viewer.id, tenant_id=tenant.id, status=1),
    ])

    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="扩展测试应用",
        app_code="ext-test-app",
        status="completed",
        platform_env_id=None,  # 不部署也行 — 我们只测权限层
        apaas_app_id=None,
    )
    db_session.add(app)
    await db_session.commit()
    await db_session.refresh(app)
    return {"tenant": tenant, "owner": owner, "viewer": viewer, "app": app}


def _ctx_admin(user: User, tenant_id: int) -> AuthContext:
    """tenant_admin — 绕过所有检查 (Layer 1+2 都 bypass)."""
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={"*": True},
    )


def _ctx_viewer(user: User, tenant_id: int) -> AuthContext:
    """tenant member 但 org_permissions 空 → Layer 1 应用:edit 必失败."""
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="member",
        org_permissions={},  # 空 → has_org_permission 直接 False
    )


# ─────────── Task 1: notify_extension_update EDIT auth ───────────


@pytest.mark.asyncio
async def test_notify_extension_update_rejects_viewer_without_edit(db_session):
    """PR6 P2 #1: viewer (没 EDIT 权限) 调 notify endpoint → 403.

    回归点: 此前 notify 只走 _load_app_and_env 默认 VIEW 检查, viewer 能调
    → 能向同 app_id 所有订阅者广播任意事件 (例如 fake dev_kit_published 触发
    误以为有更新). 修后 viewer 直接 403.
    """
    from app.routes.applications.extension import notify_extension_update, NotifyExtensionUpdateRequest

    seed = await _seed_app_with_owner_and_viewer(db_session)
    ctx = _ctx_viewer(seed["viewer"], seed["tenant"].id)
    body = NotifyExtensionUpdateRequest(event_type="dev_kit_published", payload={"x": 1})

    with pytest.raises(HTTPException) as exc:
        await notify_extension_update(
            app_id=seed["app"].id, body=body, ctx=ctx, db=db_session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_notify_extension_update_allows_tenant_admin(db_session):
    """PR6 P2 #1 对照: tenant_admin 调 notify → ok=True."""
    from app.routes.applications import extension as ext_mod

    seed = await _seed_app_with_owner_and_viewer(db_session)
    ctx = _ctx_admin(seed["owner"], seed["tenant"].id)
    body = ext_mod.NotifyExtensionUpdateRequest(
        event_type="dev_kit_published", payload={"kit_id": "k1"},
    )

    # 没真订阅者, delivered 应该是 0; 重点是不抛 403.
    result = await ext_mod.notify_extension_update(
        app_id=seed["app"].id, body=body, ctx=ctx, db=db_session,
    )
    assert result.ok is True
    assert isinstance(result.delivered, int)


# ─────────── Task 2: republish 幂等去重 ───────────


@pytest.mark.asyncio
async def test_republish_dedup_second_call_in_window_returns_true():
    """PR6 P2 #2: 同 app_id 5s 窗口内第二次 _should_dedup_republish → (True, >0)."""
    from app.routes.applications import extension as ext_mod

    # 隔离全局 state — patch module-level dict.
    test_dict: dict[int, float] = {}
    with patch.object(ext_mod, "_republish_last_ts", test_dict):
        deduped1, since1 = await ext_mod._should_dedup_republish(12345)
        assert deduped1 is False
        assert since1 == 0.0

        # 立即第二次 — 应 dedup.
        deduped2, since2 = await ext_mod._should_dedup_republish(12345)
        assert deduped2 is True
        assert since2 >= 0  # 距上次秒数, 可能 0.001 也行
        assert since2 < ext_mod._REPUBLISH_DEDUP_WINDOW_S


@pytest.mark.asyncio
async def test_republish_dedup_different_app_ids_independent():
    """PR6 P2 #2: 不同 app_id 各自一窗 — A dedup 不影响 B."""
    from app.routes.applications import extension as ext_mod

    test_dict: dict[int, float] = {}
    with patch.object(ext_mod, "_republish_last_ts", test_dict):
        # app 100 第一次进窗
        d100_1, _ = await ext_mod._should_dedup_republish(100)
        assert d100_1 is False
        # app 200 第一次也应该通过 — 跟 100 互不干扰
        d200_1, _ = await ext_mod._should_dedup_republish(200)
        assert d200_1 is False
        # 但 app 100 第二次 dedup
        d100_2, _ = await ext_mod._should_dedup_republish(100)
        assert d100_2 is True


@pytest.mark.asyncio
async def test_republish_dedup_window_expires_allows_second_call():
    """PR6 P2 #2: 窗口过期后同 app_id 第二次又能通过.

    监控 time.monotonic 走过 _REPUBLISH_DEDUP_WINDOW_S + 0.1s 后, dedup 释放.
    用 patch monotonic 模拟时间跳变, 避免真 sleep 5s 拖慢测试.
    """
    from app.routes.applications import extension as ext_mod

    test_dict: dict[int, float] = {}
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    with patch.object(ext_mod, "_republish_last_ts", test_dict), \
         patch.object(ext_mod.time, "monotonic", side_effect=fake_monotonic):
        # t=1000.0 第一次进
        deduped1, _ = await ext_mod._should_dedup_republish(999)
        assert deduped1 is False
        # t=1003.0 (3s 内) — 还在窗口
        fake_now[0] = 1003.0
        deduped2, _ = await ext_mod._should_dedup_republish(999)
        assert deduped2 is True
        # t=1006.0 (6s 后) — 窗口已过, 重新放行
        fake_now[0] = 1006.0
        deduped3, _ = await ext_mod._should_dedup_republish(999)
        assert deduped3 is False
