"""GET /projects/:id/dependencies 读接口测试

直接 import route handler 函数级调用，绕过 HTTP 层（仍走真实 ORM + DB）。
"""
import pytest
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Project, ProjectMember, User, ProjectArtifactDependency
from app.models.tenant import Tenant, UserTenant
from app.routes.projects import list_dependencies


async def _setup(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="o", hashed_password="x")
    db_session.add(owner)
    await db_session.flush()

    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = Project(name="p", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    await db_session.commit()

    ctx = AuthContext(user=owner, tenant_id=tenant.id, tenant_role="tenant_admin", org_permissions={})
    return ctx, project.id


@pytest.mark.asyncio
async def test_lists_dependencies(db_session):
    ctx, pid = await _setup(db_session)
    db_session.add(ProjectArtifactDependency(
        project_id=pid, from_ref="workspace:a", to_ref="workspace:b",
        expose_label="暴露X", consume_label="consumeX", note="n"))
    await db_session.commit()
    rows = await list_dependencies(pid, ctx, db_session)
    assert len(rows) == 1 and rows[0]["from_ref"] == "workspace:a"
    assert rows[0]["expose_label"] == "暴露X"


@pytest.mark.asyncio
async def test_empty_when_none(db_session):
    ctx, pid = await _setup(db_session)
    rows = await list_dependencies(pid, ctx, db_session)
    assert rows == []
