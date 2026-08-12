import base64
import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, AuditLog, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.audit_log import (
    AuditLogQuery,
    list_audit_logs,
    record_audit_log_best_effort,
    redact_audit_value,
)


async def _seed(db):
    tenant = Tenant(tenant_name="audit", tenant_code="audit")
    other_tenant = Tenant(tenant_name="other", tenant_code="other")
    db.add_all([tenant, other_tenant])
    await db.flush()
    users = {}
    for name in ("tenant_admin", "owner", "admin", "collaborator", "outsider"):
        user = User(username=name, hashed_password="x")
        db.add(user)
        await db.flush()
        users[name] = user
        db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
    app = Application(user_id=users["owner"].id, created_by=users["owner"].id,
                      tenant_id=tenant.id, app_name="A", app_code="a")
    other_app = Application(user_id=users["owner"].id, created_by=users["owner"].id,
                            tenant_id=tenant.id, app_name="B", app_code="b")
    db.add_all([app, other_app])
    await db.flush()
    db.add_all([
        ApplicationMember(application_id=app.id, user_id=users["admin"].id,
                          role="admin", invited_by=users["owner"].id),
        ApplicationMember(application_id=app.id, user_id=users["collaborator"].id,
                          role="collaborator", invited_by=users["owner"].id),
    ])
    stamp = datetime(2026, 8, 12, 10, 0, 0)
    db.add_all([
        AuditLog(occurred_at=stamp, tenant_id=tenant.id, application_id=app.id,
                 actor_id=users["owner"].id, actor_name="owner", event_type="one",
                 target_type="application_member", target_id="1", result="success"),
        AuditLog(occurred_at=stamp, tenant_id=tenant.id, application_id=app.id,
                 actor_id=users["owner"].id, actor_name="owner", event_type="two",
                 target_type="application_member", target_id="2", result="success"),
        AuditLog(occurred_at=stamp, tenant_id=tenant.id, application_id=other_app.id,
                 actor_id=users["owner"].id, actor_name="owner", event_type="other",
                 target_type="application_member", target_id="3", result="success"),
    ])
    await db.commit()
    return tenant, users, app, other_app


def _ctx(user, tenant_id, tenant_role="member"):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role=tenant_role, org_permissions={})


@pytest.mark.asyncio
async def test_four_identities_enforce_tenant_and_application_scope(db_session):
    tenant, users, app, other_app = await _seed(db_session)
    tenant_page = await list_audit_logs(db_session, _ctx(users["tenant_admin"], tenant.id, "tenant_admin"), AuditLogQuery())
    assert [item.event_type for item in tenant_page.items] == ["other", "two", "one"]
    for role in ("owner", "admin"):
        page = await list_audit_logs(db_session, _ctx(users[role], tenant.id), AuditLogQuery(application_id=app.id))
        assert [item.event_type for item in page.items] == ["two", "one"]
    with pytest.raises(HTTPException) as denied:
        await list_audit_logs(db_session, _ctx(users["collaborator"], tenant.id), AuditLogQuery(application_id=app.id))
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as outsider:
        await list_audit_logs(db_session, _ctx(users["outsider"], tenant.id), AuditLogQuery(application_id=app.id))
    assert outsider.value.status_code == 403


@pytest.mark.asyncio
async def test_inherited_project_roles_enforce_application_audit_scope(db_session):
    tenant, users, app, _ = await _seed(db_session)
    maintainer = User(username="project-maintainer", hashed_password="x")
    contributor = User(username="project-contributor", hashed_password="x")
    db_session.add_all([maintainer, contributor])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=maintainer.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=contributor.id, tenant_id=tenant.id, status=1),
    ])
    project = Project(name="audit-project", user_id=users["owner"].id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()
    app.project_id = project.id
    db_session.add_all([
        ProjectMember(project_id=project.id, user_id=maintainer.id, role="maintainer"),
        ProjectMember(project_id=project.id, user_id=contributor.id, role="contributor"),
    ])
    await db_session.commit()

    page = await list_audit_logs(
        db_session,
        _ctx(maintainer, tenant.id),
        AuditLogQuery(application_id=app.id),
    )
    assert [item.event_type for item in page.items] == ["two", "one"]
    with pytest.raises(HTTPException) as denied:
        await list_audit_logs(
            db_session,
            _ctx(contributor, tenant.id),
            AuditLogQuery(application_id=app.id),
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_application_query_cannot_expand_application_admin_scope(db_session):
    tenant, users, app, other_app = await _seed(db_session)
    with pytest.raises(HTTPException) as denied:
        await list_audit_logs(db_session, _ctx(users["admin"], tenant.id), AuditLogQuery(application_id=other_app.id))
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_same_timestamp_cursor_is_stable(db_session):
    tenant, users, app, _ = await _seed(db_session)
    first = await list_audit_logs(db_session, _ctx(users["owner"], tenant.id), AuditLogQuery(application_id=app.id, limit=1))
    second = await list_audit_logs(db_session, _ctx(users["owner"], tenant.id), AuditLogQuery(application_id=app.id, limit=1, cursor=first.next_cursor))
    assert [first.items[0].event_type, second.items[0].event_type] == ["two", "one"]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_non_utf8_cursor_returns_400(db_session):
    tenant, users, app, _ = await _seed(db_session)
    cursor = base64.urlsafe_b64encode(b"\xff").decode().rstrip("=")
    with pytest.raises(HTTPException) as invalid:
        await list_audit_logs(
            db_session,
            _ctx(users["owner"], tenant.id),
            AuditLogQuery(application_id=app.id, cursor=cursor),
        )
    assert invalid.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cursor",
    [
        "%%%",
        base64.urlsafe_b64encode(b"not-json").decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps([]).encode()).decode().rstrip("="),
        base64.urlsafe_b64encode(
            json.dumps({"occurred_at": [], "id": 1}).encode()
        ).decode().rstrip("="),
        base64.urlsafe_b64encode(
            json.dumps({"occurred_at": "2026-08-12T10:00:00", "id": True}).encode()
        ).decode().rstrip("="),
    ],
)
async def test_malformed_cursor_shapes_return_400(db_session, cursor):
    tenant, users, app, _ = await _seed(db_session)

    with pytest.raises(HTTPException) as invalid:
        await list_audit_logs(
            db_session,
            _ctx(users["owner"], tenant.id),
            AuditLogQuery(application_id=app.id, cursor=cursor),
        )

    assert invalid.value.status_code == 400


def test_redaction_removes_sensitive_keys_and_values_before_persistence():
    secret = "sk-live-secret-value"
    redacted = redact_audit_value({"password": secret, "nested": {"token": secret}, "note": f"use {secret}"}, sensitive_values=[secret])
    rendered = str(redacted)
    assert secret not in rendered
    assert redacted == {"password": "[REDACTED]", "nested": {"token": "[REDACTED]"}, "note": "use [REDACTED]"}


@pytest.mark.asyncio
async def test_best_effort_writer_swallows_its_own_storage_failure():
    class BrokenSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise RuntimeError("audit storage unavailable")

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    user = User(id=9, username="operator", hashed_password="x")
    ctx = _ctx(user, 7, "tenant_admin")

    await record_audit_log_best_effort(
        ctx=ctx,
        application_id=11,
        event_type="application_member.removed",
        target_type="application_member",
        target_id=22,
        result="failure",
        failure_reason="original business error",
        session_factory=BrokenSessionFactory(),
    )
