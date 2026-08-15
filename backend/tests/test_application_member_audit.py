import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import audit_log as audit_log_module
from app.database import Base
from app.deps import AuthContext
from app.models import Application, AuditLog, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.routes.application_members import (
    InviteAppMemberRequest,
    UpdateAppMemberRoleRequest,
    invite_application_member,
    remove_application_member,
    update_application_member_role,
)


async def _seed(db):
    tenant = Tenant(tenant_name="t", tenant_code="t")
    db.add(tenant)
    await db.flush()
    users = {}
    for name in ("owner", "admin", "collaborator", "target"):
        user = User(username=name, hashed_password="x")
        db.add(user)
        await db.flush()
        db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
        users[name] = user
    app = Application(user_id=users["owner"].id, created_by=users["owner"].id,
                      tenant_id=tenant.id, app_name="App", app_code="app")
    db.add(app)
    await db.flush()
    db.add_all([
        ApplicationMember(application_id=app.id, user_id=users["admin"].id,
                          role="admin", invited_by=users["owner"].id),
        ApplicationMember(application_id=app.id, user_id=users["collaborator"].id,
                          role="collaborator", invited_by=users["owner"].id),
    ])
    await db.commit()
    return tenant, users, app


def _ctx(user, tenant_id, role="member"):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role=role, org_permissions={})


@pytest.mark.asyncio
async def test_member_add_role_change_and_remove_write_audit_events(db_session):
    tenant, users, app = await _seed(db_session)
    owner_ctx = _ctx(users["owner"], tenant.id)
    await invite_application_member(app.id, InviteAppMemberRequest(user_id=users["target"].id, role="collaborator"), owner_ctx, db_session)
    await update_application_member_role(app.id, users["target"].id, UpdateAppMemberRoleRequest(role="admin"), owner_ctx, db_session)
    await remove_application_member(app.id, users["target"].id, owner_ctx, db_session)

    events = list((await db_session.scalars(select(AuditLog).order_by(AuditLog.id))).all())
    assert [event.event_type for event in events] == [
        "application_member.direct_add",
        "application_member.role_changed",
        "application_member.removed",
    ]
    assert events[0].after_value == {"user_id": users["target"].id, "role": "collaborator"}
    assert events[1].before_value["role"] == "collaborator"
    assert events[1].after_value["role"] == "admin"
    assert events[2].before_value["role"] == "admin"


@pytest.mark.asyncio
async def test_audit_insert_failure_rolls_back_member_add(db_session):
    tenant, users, app = await _seed(db_session)
    app_id = app.id
    target_id = users["target"].id

    def reject_audit(_mapper, _connection, _target):
        raise RuntimeError("audit unavailable")

    event.listen(AuditLog, "before_insert", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await invite_application_member(
                app_id,
                InviteAppMemberRequest(user_id=target_id, role="collaborator"),
                _ctx(users["owner"], tenant.id),
                db_session,
            )
    finally:
        event.remove(AuditLog, "before_insert", reject_audit)
        await db_session.rollback()

    member = await db_session.scalar(select(ApplicationMember).where(
        ApplicationMember.application_id == app_id,
        ApplicationMember.user_id == target_id,
    ))
    assert member is None


@pytest.mark.asyncio
async def test_collaborator_cannot_change_members_but_admin_can(db_session):
    tenant, users, app = await _seed(db_session)
    tenant_id = tenant.id
    app_id = app.id
    target_id = users["target"].id
    collaborator_id = users["collaborator"].id
    admin_id = users["admin"].id
    with pytest.raises(HTTPException) as denied:
        await invite_application_member(
            app_id,
            InviteAppMemberRequest(user_id=target_id, role="collaborator"),
            _ctx(users["collaborator"], tenant_id),
            db_session,
        )
    assert denied.value.status_code == 403

    admin = await db_session.get(User, admin_id)
    result = await invite_application_member(
        app_id,
        InviteAppMemberRequest(user_id=target_id, role="collaborator"),
        _ctx(admin, tenant_id),
        db_session,
    )
    assert result["role"] == "collaborator"


def test_member_request_rejects_legacy_roles():
    with pytest.raises(ValueError):
        InviteAppMemberRequest(user_id=1, role="maintainer")


@pytest.mark.asyncio
async def test_denied_member_change_is_recorded_without_changing_http_error(
    monkeypatch,
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit-denied.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr(audit_log_module, "AsyncSessionLocal", session_factory)

    async with session_factory() as db:
        tenant, users, app = await _seed(db)
        tenant_id = tenant.id
        app_id = app.id
        target_id = users["target"].id
        collaborator = users["collaborator"]

    async with session_factory() as db:
        with pytest.raises(HTTPException) as denied:
            await invite_application_member(
                app_id,
                InviteAppMemberRequest(user_id=target_id, role="collaborator"),
                _ctx(collaborator, tenant_id),
                db,
            )
    assert denied.value.status_code == 403
    assert denied.value.detail == "需要应用所有者或管理员权限"

    async with session_factory() as db:
        event_row = await db.scalar(select(AuditLog))
        assert event_row is not None
        assert event_row.event_type == "application_member.direct_add"
        assert event_row.result == "denied"
        assert event_row.target_id == str(target_id)
        assert event_row.failure_reason == "需要应用所有者或管理员权限"
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_member_change_is_recorded_after_main_transaction_rolls_back(
    monkeypatch,
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit-failure.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr(audit_log_module, "AsyncSessionLocal", session_factory)

    async with session_factory() as db:
        tenant, users, app = await _seed(db)
        tenant_id = tenant.id
        app_id = app.id
        missing_user_id = users["target"].id + 1000
        owner = users["owner"]

    async with session_factory() as db:
        with pytest.raises(HTTPException) as failed:
            await update_application_member_role(
                app_id,
                missing_user_id,
                UpdateAppMemberRoleRequest(role="admin"),
                _ctx(owner, tenant_id),
                db,
            )
    assert failed.value.status_code == 404
    assert failed.value.detail == "应用直接成员不存在（如是 inherited 请到 Project 修改）"

    async with session_factory() as db:
        event_row = await db.scalar(select(AuditLog))
        assert event_row is not None
        assert event_row.event_type == "application_member.role_changed"
        assert event_row.result == "failure"
        assert event_row.target_id == str(missing_user_id)
        assert event_row.failure_reason == failed.value.detail
    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_tenant_denial_does_not_bind_foreign_application(
    monkeypatch,
    tmp_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit-cross-tenant.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(audit_log_module, "AsyncSessionLocal", session_factory)

    async with session_factory() as db:
        tenant, users, _ = await _seed(db)
        other_tenant = Tenant(tenant_name="other", tenant_code="other")
        db.add(other_tenant)
        await db.flush()
        foreign_app = Application(
            user_id=users["owner"].id,
            created_by=users["owner"].id,
            tenant_id=other_tenant.id,
            app_name="Foreign",
            app_code="foreign",
        )
        db.add(foreign_app)
        await db.commit()
        foreign_app_id = foreign_app.id
        target_id = users["target"].id
        actor = users["owner"]
        tenant_id = tenant.id

    async with session_factory() as db:
        with pytest.raises(HTTPException) as denied:
            await invite_application_member(
                foreign_app_id,
                InviteAppMemberRequest(user_id=target_id, role="collaborator"),
                _ctx(actor, tenant_id, "tenant_admin"),
                db,
            )
    assert denied.value.status_code == 404

    async with session_factory() as db:
        audit = await db.scalar(select(AuditLog))
        assert audit is not None
        assert audit.tenant_id == tenant_id
        assert audit.application_id is None
    await engine.dispose()
