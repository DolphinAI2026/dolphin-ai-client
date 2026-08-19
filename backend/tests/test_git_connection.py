"""GitConnection PAT 直连 endpoint + connection helpers 测试。

覆盖：
- encrypt/decrypt round trip
- make_provider 根据 GitConnection.provider 路由到 GitLab / GitHub provider
- POST /api/projects/{id}/git-connection 落库且 access_token 加密
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext, require_tenant_admin
from app.models import Project, ProjectMember, User
from app.models.collaboration import GitConnection, TenantGitConnection
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token, decrypt_token, make_provider
from app.git.provider.gitlab import GitLabProvider
from app.git.provider.github import GitHubProvider
from app.routes.git_connection import (
    ConnectGitPATRequest,
    connect_git_pat,
    delete_git_connection,
    get_git_connection,
    delete_tenant_git_connection,
    get_tenant_git_connection,
    upsert_tenant_git_connection,
)


def test_encrypt_decrypt_round_trip():
    plain = "ghp_supersecrettoken12345"
    enc = encrypt_token(plain)
    assert enc != plain  # 已加密
    assert decrypt_token(enc) == plain


def test_make_provider_gitlab_returns_gitlab():
    enc = encrypt_token("glpat-xxx")
    conn = GitConnection(
        project_id=1,
        provider="gitlab",
        host="https://gitlab.com",
        access_token_enc=enc,
        group_id_or_org="myorg",
    )
    provider = make_provider(conn)
    assert isinstance(provider, GitLabProvider)
    assert provider.token == "glpat-xxx"
    assert provider.host == "https://gitlab.com"


def test_make_provider_github_returns_github():
    enc = encrypt_token("ghp_yyy")
    conn = GitConnection(
        project_id=1,
        provider="github",
        host="https://github.com",
        access_token_enc=enc,
        group_id_or_org="myorg",
    )
    provider = make_provider(conn)
    assert isinstance(provider, GitHubProvider)
    assert provider.token == "ghp_yyy"


def test_make_provider_unknown_raises():
    enc = encrypt_token("x")
    conn = GitConnection(
        project_id=1,
        provider="bitbucket",
        host="https://bitbucket.org",
        access_token_enc=enc,
        group_id_or_org="myorg",
    )
    with pytest.raises(ValueError, match="unknown git provider"):
        make_provider(conn)


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _seed(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "owner_u")
    contributor = await _make_user(db_session, "contrib_u")

    db_session.add_all([
        UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1),
        UserTenant(user_id=contributor.id, tenant_id=tenant.id, status=1),
    ])

    project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    db_session.add(ProjectMember(project_id=project.id, user_id=contributor.id, role="contributor"))
    await db_session.commit()

    return {"tenant": tenant, "owner": owner, "contributor": contributor, "project": project}


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_connect_pat_persists_encrypted_token(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    req = ConnectGitPATRequest(
        provider="github",
        host="https://github.com",
        access_token="ghp_realtoken_abc",
        group_id_or_org="myorg",
    )
    result = await connect_git_pat(s["project"].id, req, ctx, db_session)

    assert result["provider"] == "github"
    assert result["host"] == "https://github.com"
    assert result["group_id_or_org"] == "myorg"
    assert result["status"] == "connected"
    assert "access_token_enc" not in result  # 不返回密文

    # 验证落库后 token 已加密 + 可解密回原值
    from sqlalchemy import select
    conn = (await db_session.execute(
        select(GitConnection).where(GitConnection.project_id == s["project"].id)
    )).scalar_one()
    assert conn.access_token_enc != "ghp_realtoken_abc"
    assert decrypt_token(conn.access_token_enc) == "ghp_realtoken_abc"


@pytest.mark.asyncio
async def test_connect_pat_overwrites_existing(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    await connect_git_pat(
        s["project"].id,
        ConnectGitPATRequest(provider="gitlab", host="https://gitlab.com", access_token="t1", group_id_or_org="g1"),
        ctx, db_session,
    )
    await connect_git_pat(
        s["project"].id,
        ConnectGitPATRequest(provider="github", host="https://github.com", access_token="t2", group_id_or_org="g2"),
        ctx, db_session,
    )

    from sqlalchemy import select
    rows = (await db_session.execute(
        select(GitConnection).where(GitConnection.project_id == s["project"].id)
    )).scalars().all()
    assert len(rows) == 1  # 唯一约束 + 覆盖
    assert rows[0].provider == "github"
    assert decrypt_token(rows[0].access_token_enc) == "t2"


@pytest.mark.asyncio
async def test_connect_pat_rejects_invalid_provider(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    with pytest.raises(HTTPException) as ei:
        await connect_git_pat(
            s["project"].id,
            ConnectGitPATRequest(provider="bitbucket", host="x", access_token="y", group_id_or_org="z"),
            ctx, db_session,
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_get_git_connection_returns_none_when_absent(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)
    result = await get_git_connection(s["project"].id, ctx, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_delete_requires_owner(db_session):
    s = await _seed(db_session)
    owner_ctx = _ctx_for(s["owner"], s["tenant"].id)
    contrib_ctx = _ctx_for(s["contributor"], s["tenant"].id)

    await connect_git_pat(
        s["project"].id,
        ConnectGitPATRequest(provider="github", host="https://github.com", access_token="t", group_id_or_org="g"),
        owner_ctx, db_session,
    )

    # contributor 不能 delete
    with pytest.raises(HTTPException) as ei:
        await delete_git_connection(s["project"].id, contrib_ctx, db_session)
    assert ei.value.status_code == 403

    # owner 可以
    result = await delete_git_connection(s["project"].id, owner_ctx, db_session)
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_tenant_connection_persists_encrypted_token_and_never_returns_it(db_session):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    result = await upsert_tenant_git_connection(
        ConnectGitPATRequest(
            provider="gitlab", host="https://git.example.com",
            access_token="glpat-global-secret", group_id_or_org="platform/capabilities",
        ), ctx, db_session,
    )

    assert result["scope"] == "tenant"
    assert result["group_id_or_org"] == "platform/capabilities"
    assert "access_token" not in result
    stored = (await db_session.execute(
        select(TenantGitConnection).where(TenantGitConnection.tenant_id == s["tenant"].id)
    )).scalar_one()
    assert stored.access_token_enc != "glpat-global-secret"
    assert decrypt_token(stored.access_token_enc) == "glpat-global-secret"

    fetched = await get_tenant_git_connection(ctx, db_session)
    assert fetched["id"] == result["id"]
    assert "access_token_enc" not in fetched

    deleted = await delete_tenant_git_connection(ctx, db_session)
    assert deleted == {"status": "ok"}


@pytest.mark.asyncio
async def test_tenant_connection_requires_tenant_admin(db_session):
    s = await _seed(db_session)
    member_ctx = AuthContext(
        user=s["contributor"], tenant_id=s["tenant"].id,
        tenant_role="member", org_permissions={},
    )
    with pytest.raises(HTTPException) as exc:
        await require_tenant_admin(member_ctx)
    assert exc.value.status_code == 403
