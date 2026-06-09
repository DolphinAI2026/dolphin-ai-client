"""work-state BFF 端点测试 — 函数级直调 handler"""
import uuid

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.preference import UserPreference
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.routes.work_state import _effective_mode, get_work_state


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


async def _seed_app(db_session, *, with_canonical: bool = True):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, f"ws_owner_{uuid.uuid4().hex[:6]}")
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))

    application = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        project_id=project.id, app_name="WS App", app_code="ws_app",
    )
    db_session.add(application)
    await db_session.flush()

    canonical_spec = None
    if with_canonical:
        canonical_spec = SpecORM(
            id=uuid.uuid4().hex,
            application_id=application.id,
            version=1,
            kind="canonical",
            commit_sha="deadbeef",
            payload={},
            phase="refining",
            created_by=owner.id,
            tenant_id=tenant.id,
        )
        db_session.add(canonical_spec)
        await db_session.flush()
        application.canonical_spec_id = canonical_spec.id

    await db_session.commit()
    await db_session.refresh(application)

    return {
        "tenant": tenant, "owner": owner, "project": project,
        "application": application, "canonical": canonical_spec,
    }


@pytest.mark.asyncio
async def test_work_state_returns_aggregated_payload(db_session):
    """canonical + draft + git → 字段齐全"""
    s = await _seed_app(db_session, with_canonical=True)
    owner = s["owner"]
    app = s["application"]

    # draft for owner
    draft = SpecORM(
        id=uuid.uuid4().hex,
        application_id=app.id, version=2, kind="draft",
        payload={}, phase="gathering",
        completeness_confirmed=3, completeness_total=10,
        created_by=owner.id, tenant_id=s["tenant"].id,
    )
    db_session.add(draft)
    await db_session.flush()

    # set git on app
    app.git_repo_url = "https://gitlab.example.com/proj.git"
    app.git_provider = "gitlab"
    app.git_default_branch = "main"
    await db_session.commit()

    ctx = _ctx_for(owner, s["tenant"].id)
    result = await get_work_state(app.id, ctx, db_session)

    assert result["application"]["id"] == app.id
    assert result["application"]["app_code"] == "ws_app"
    assert result["application"]["default_mode"] is None

    assert result["canonical"]["id"] == s["canonical"].id
    assert result["canonical"]["kind"] == "canonical"

    assert result["current_draft"]["id"] == draft.id
    assert result["current_draft"]["completeness_confirmed"] == 3
    assert result["current_draft"]["completeness_total"] == 10

    assert result["git"]["repo_url"].endswith(".git")
    assert result["git"]["provider"] == "gitlab"
    assert result["git"]["connected"] is False  # 没建 GitConnection

    member_usernames = {m["username"] for m in result["members"]}
    assert owner.username in member_usernames

    # owner = maintainer+; pref 默认 simple → effective='simple'（app_default None）
    assert result["user_role_on_app"] == "owner"
    assert result["user_pref_mode"] == "simple"
    assert result["effective_mode"] == "simple"


@pytest.mark.asyncio
async def test_work_state_no_canonical_returns_null(db_session):
    """全新应用无 canonical → canonical=None"""
    s = await _seed_app(db_session, with_canonical=False)
    ctx = _ctx_for(s["owner"], s["tenant"].id)
    result = await get_work_state(s["application"].id, ctx, db_session)

    assert result["canonical"] is None
    assert result["current_draft"] is None
    assert result["git"] is None


@pytest.mark.asyncio
async def test_work_state_effective_mode_for_contributor_is_simple(db_session):
    """contributor 角色 → effective_mode='simple' 即使 user pref='pro'"""
    s = await _seed_app(db_session, with_canonical=False)
    contributor = await _make_user(db_session, "ws_contrib")
    db_session.add(UserTenant(user_id=contributor.id, tenant_id=s["tenant"].id, status=1))
    db_session.add(ProjectMember(
        project_id=s["project"].id, user_id=contributor.id, role="contributor",
    ))
    # contributor 自己设置 user pref='pro'
    db_session.add(UserPreference(user_id=contributor.id, default_mode="pro"))
    # 应用 default_mode 也设成 pro
    s["application"].default_mode = "pro"
    await db_session.commit()

    ctx = _ctx_for(contributor, s["tenant"].id)
    result = await get_work_state(s["application"].id, ctx, db_session)

    assert result["user_role_on_app"] == "contributor"
    assert result["user_pref_mode"] == "pro"
    assert result["application"]["default_mode"] == "pro"
    assert result["effective_mode"] == "simple"  # contributor 强制 simple


@pytest.mark.asyncio
async def test_work_state_no_access_returns_403(db_session):
    """非成员访问 → 403"""
    s = await _seed_app(db_session, with_canonical=False)
    outsider = await _make_user(db_session, "ws_outsider")
    db_session.add(UserTenant(user_id=outsider.id, tenant_id=s["tenant"].id, status=1))
    await db_session.commit()

    ctx = _ctx_for(outsider, s["tenant"].id)
    with pytest.raises(HTTPException) as exc:
        await get_work_state(s["application"].id, ctx, db_session)
    assert exc.value.status_code == 403


def test_effective_mode_helper_units():
    """_effective_mode 单元 — 4 类身份 + None/simple/pro"""
    # contributor 强制 simple
    assert _effective_mode("pro", "pro", "contributor") == "simple"
    assert _effective_mode("pro", None, "viewer") == "simple"
    # maintainer+ 优先 app_default
    assert _effective_mode("simple", "pro", "maintainer") == "pro"
    assert _effective_mode("pro", "simple", "owner") == "simple"
    # app_default None → 退到 user_pref
    assert _effective_mode("pro", None, "owner") == "pro"
    assert _effective_mode("simple", None, "maintainer") == "simple"
