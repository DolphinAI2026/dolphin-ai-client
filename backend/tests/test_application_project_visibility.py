import pytest

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.routes.applications import (
    _get_application_permissions,
    list_applications_page,
    match_applications_by_name,
)


async def _match_visibility_seed(db_session):
    tenant = Tenant(tenant_name="match tenant", tenant_code="match-tenant")
    other_tenant = Tenant(
        tenant_name="match other tenant",
        tenant_code="match-other-tenant",
    )
    owner = User(username="match-owner", hashed_password="x")
    member = User(username="match-member", hashed_password="x")
    db_session.add_all([tenant, other_tenant, owner, member])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=member.id, tenant_id=tenant.id, status=1),
    ])

    visible_project = Project(
        name="match-visible-project",
        user_id=owner.id,
        tenant_id=tenant.id,
    )
    other_project = Project(
        name="match-other-project",
        user_id=owner.id,
        tenant_id=other_tenant.id,
    )
    db_session.add_all([visible_project, other_project])
    await db_session.flush()
    db_session.add_all([
        ProjectMember(
            project_id=visible_project.id,
            user_id=member.id,
            role="contributor",
        ),
        ProjectMember(
            project_id=other_project.id,
            user_id=member.id,
            role="owner",
        ),
    ])

    direct = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="Direct Match",
        app_code="match-direct",
        status="draft",
    )
    inherited = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=visible_project.id,
        app_name="Inherited Match",
        app_code="match-inherited",
        status="draft",
    )
    hidden = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="Hidden Match",
        app_code="match-hidden",
        status="draft",
    )
    cross_tenant = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=other_project.id,
        app_name="Cross Tenant Match",
        app_code="match-cross-tenant",
        status="draft",
    )
    db_session.add_all([direct, inherited, hidden, cross_tenant])
    await db_session.flush()
    db_session.add(ApplicationMember(
        application_id=direct.id,
        user_id=member.id,
        role="collaborator",
        invited_by=owner.id,
    ))
    await db_session.commit()
    return tenant, member


async def _match_codes(db_session, tenant, member, app_code: str) -> list[str]:
    matches = await match_applications_by_name(
        AuthContext(
            user=member,
            tenant_id=tenant.id,
            tenant_role="member",
            org_permissions={},
        ),
        db_session,
        app_name_like="",
        app_code_like=app_code,
        limit=5,
    )
    return [match.app_code for match in matches]


@pytest.mark.asyncio
async def test_match_by_name_hides_application_without_user_access(db_session):
    tenant, member = await _match_visibility_seed(db_session)

    assert await _match_codes(db_session, tenant, member, "match-hidden") == []


@pytest.mark.asyncio
async def test_match_by_name_includes_direct_application_member(db_session):
    tenant, member = await _match_visibility_seed(db_session)

    assert await _match_codes(db_session, tenant, member, "match-direct") == [
        "match-direct"
    ]


@pytest.mark.asyncio
async def test_match_by_name_includes_same_tenant_project_member(db_session):
    tenant, member = await _match_visibility_seed(db_session)

    assert await _match_codes(db_session, tenant, member, "match-inherited") == [
        "match-inherited"
    ]


@pytest.mark.asyncio
async def test_match_by_name_rejects_cross_tenant_project_membership(db_session):
    tenant, member = await _match_visibility_seed(db_session)

    assert await _match_codes(db_session, tenant, member, "match-cross-tenant") == []


@pytest.mark.asyncio
async def test_application_page_uses_same_member_visibility_for_counts_and_items(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    owner = User(username="page-owner", hashed_password="x")
    member = User(username="page-member", hashed_password="x")
    db_session.add_all([tenant, owner, member])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=member.id, tenant_id=tenant.id, status=1),
    ])

    for index in range(2):
        db_session.add(Application(
            user_id=member.id,
            tenant_id=tenant.id,
            created_by=member.id,
            app_name=f"Owned {index}",
            app_code=f"owned-{index}",
            status="draft",
        ))
    direct_app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="Direct",
        app_code="direct-visible",
        status="completed",
    )
    hidden_app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="Hidden",
        app_code="hidden",
        status="draft",
    )
    db_session.add_all([direct_app, hidden_app])
    await db_session.flush()
    db_session.add(ApplicationMember(
        application_id=direct_app.id,
        user_id=member.id,
        role="collaborator",
        invited_by=owner.id,
    ))
    await db_session.commit()

    ctx = AuthContext(
        user=member,
        tenant_id=tenant.id,
        tenant_role="member",
        org_permissions={},
    )
    first = await list_applications_page(ctx, db_session, page=1, page_size=2)
    second = await list_applications_page(ctx, db_session, page=2, page_size=2)

    assert first["total"] == 3
    assert first["total_pages"] == 2
    assert first["counts"] == {"all": 3, "active": 0, "deployed": 1, "draft": 2}
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert {item.app_code for item in first["items"] + second["items"]} == {
        "owned-0", "owned-1", "direct-visible",
    }


@pytest.mark.asyncio
async def test_application_page_includes_project_member_in_counts_and_items(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    owner = User(username="project-owner", hashed_password="x")
    member = User(username="project-page-member", hashed_password="x")
    db_session.add_all([tenant, owner, member])
    await db_session.flush()
    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=member.id, tenant_id=tenant.id, status=1),
    ])

    visible_project = Project(name="visible-project", user_id=owner.id, tenant_id=tenant.id)
    hidden_project = Project(name="hidden-project", user_id=owner.id, tenant_id=tenant.id)
    db_session.add_all([visible_project, hidden_project])
    await db_session.flush()
    db_session.add(ProjectMember(
        project_id=visible_project.id,
        user_id=member.id,
        role="contributor",
    ))
    db_session.add_all([
        Application(
            user_id=owner.id,
            tenant_id=tenant.id,
            created_by=owner.id,
            project_id=visible_project.id,
            app_name="Inherited Visible",
            app_code="inherited-visible",
            status="draft",
        ),
        Application(
            user_id=owner.id,
            tenant_id=tenant.id,
            created_by=owner.id,
            project_id=hidden_project.id,
            app_name="Project Hidden",
            app_code="project-hidden",
            status="completed",
        ),
    ])
    await db_session.commit()

    result = await list_applications_page(
        AuthContext(
            user=member,
            tenant_id=tenant.id,
            tenant_role="member",
            org_permissions={},
        ),
        db_session,
        page=1,
        page_size=20,
    )

    assert result["total"] == 1
    assert result["counts"] == {"all": 1, "active": 0, "deployed": 0, "draft": 1}
    assert [item.app_code for item in result["items"]] == ["inherited-visible"]
    assert result["items"][0].permissions["access_role"] == "collaborator"


@pytest.mark.asyncio
async def test_cross_tenant_project_membership_does_not_grant_application_access(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    other_tenant = Tenant(tenant_name="other", tenant_code="other")
    owner = User(username="cross-tenant-owner", hashed_password="x")
    member = User(username="cross-tenant-member", hashed_password="x")
    db_session.add_all([tenant, other_tenant, owner, member])
    await db_session.flush()
    db_session.add(UserTenant(user_id=member.id, tenant_id=tenant.id, status=1))

    other_project = Project(
        name="other-project",
        user_id=owner.id,
        tenant_id=other_tenant.id,
    )
    db_session.add(other_project)
    await db_session.flush()
    db_session.add(ProjectMember(
        project_id=other_project.id,
        user_id=member.id,
        role="owner",
    ))
    application = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=other_project.id,
        app_name="Cross Tenant Link",
        app_code="cross-tenant-link",
        status="draft",
    )
    db_session.add(application)
    await db_session.commit()
    ctx = AuthContext(
        user=member,
        tenant_id=tenant.id,
        tenant_role="member",
        org_permissions={},
    )

    page = await list_applications_page(ctx, db_session, page=1, page_size=20)
    permissions = await _get_application_permissions(ctx, db_session, application)

    assert page["total"] == 0
    assert page["items"] == []
    assert permissions is None
