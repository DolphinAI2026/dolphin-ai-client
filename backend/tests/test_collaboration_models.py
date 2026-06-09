"""协作 ORM models 的 smoke 测试

跑在 in-memory sqlite 上，使用 conftest 的 db_session fixture（每个测试一份新 schema）。
不依赖 dev DB 数据 —— 测试内自己 seed 必要的 User/Application/Project/Spec 行。
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models import User, Application, Project, Tenant
from app.models.spec import Spec as SpecORM
from app.models.collaboration import (
    ApplicationMember, GitConnection, PlatformDriftLog,
)


async def _seed_basics(db_session):
    """Seed 一份最小 fixture: tenant + user + project + application + spec."""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    user = User(username="u1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    project = Project(name="p1", user_id=user.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    app = Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="app1",
        app_code="APP1",
    )
    db_session.add(app)
    await db_session.flush()

    spec = SpecORM(
        id="spec_seed_1",
        application_id=app.id,
        version=1,
        payload={},
        phase="gathering",
        created_by=user.id,
        tenant_id=tenant.id,
    )
    db_session.add(spec)
    await db_session.flush()

    return {"tenant": tenant, "user": user, "project": project, "app": app, "spec": spec}


@pytest.mark.asyncio
async def test_collaboration_tables_registered(db_session):
    """协作表都应被 Base.metadata.create_all 创建出来"""
    def _table_names(sync_session):
        return inspect(sync_session.connection()).get_table_names()
    names = await db_session.run_sync(_table_names)
    for t in ("application_members", "git_connections", "platform_drift_logs"):
        assert t in names


@pytest.mark.asyncio
async def test_application_member_crud(db_session):
    seed = await _seed_basics(db_session)

    member = ApplicationMember(
        application_id=seed["app"].id,
        user_id=seed["user"].id,
        role="contributor",
        invited_by=seed["user"].id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)

    assert member.id is not None
    assert member.role == "contributor"
    assert member.created_at is not None


@pytest.mark.asyncio
async def test_git_connection_unique_per_project(db_session):
    seed = await _seed_basics(db_session)

    conn1 = GitConnection(
        project_id=seed["project"].id,
        provider="gitlab",
        host="https://gitlab.com",
        access_token_enc="enc1",
        status="connected",
    )
    db_session.add(conn1)
    await db_session.commit()

    conn2 = GitConnection(
        project_id=seed["project"].id,
        provider="github",
        host="https://github.com",
        access_token_enc="enc2",
        status="connected",
    )
    db_session.add(conn2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_platform_drift_log_create(db_session):
    seed = await _seed_basics(db_session)

    log = PlatformDriftLog(
        application_id=seed["app"].id,
        kind="drift_detected",
        git_sha="abc123",
        builder_canonical_sha="def456",
    )
    db_session.add(log)
    await db_session.commit()
    await db_session.refresh(log)

    assert log.id is not None
    assert log.detected_at is not None
    assert log.kind == "drift_detected"
