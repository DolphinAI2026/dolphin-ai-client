"""Phase D Task 7 — OAuth start / callback endpoint 测试。

覆盖：
- /git-oauth/start：env var 缺失时 500；存在时返回 authorize_url（含 client_id + state）
- /git-oauth/callback：mock httpx，code -> access_token -> upsert GitConnection
- callback：state 校验 + token 加密落库
- callback：env var 缺失时 500
- callback：upstream 未返 access_token 时 502
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Project, ProjectMember, User
from app.models.collaboration import GitConnection
from app.models.tenant import Tenant, UserTenant
from app.git.connection import decrypt_token
from app.routes.git_connection import (
    OAuthCallbackRequest,
    git_oauth_start,
    git_oauth_callback,
)


async def _seed(db_session):
    tenant = Tenant(tenant_name="t-oauth", tenant_code="t-oauth")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="oauth_owner", hashed_password="x")
    db_session.add(owner)
    await db_session.flush()

    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = Project(name="p-oauth", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()

    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    await db_session.commit()

    return {"tenant": tenant, "owner": owner, "project": project}


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_oauth_start_github_returns_authorize_url(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.setenv("GITHUB_CLIENT_ID", "Iv1.fakeclientid")
    monkeypatch.setenv("BUILDER_PUBLIC_URL", "https://builder.example.com")

    res = await git_oauth_start(
        project_id=s["project"].id, provider="github", ctx=ctx, db=db_session,
    )
    url = res["authorize_url"]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=Iv1.fakeclientid" in url
    assert f"state={s['project'].id}" in url
    assert "redirect_uri=https%3A%2F%2Fbuilder.example.com%2Fgit%2Fcallback%2Fgithub" in url


@pytest.mark.asyncio
async def test_oauth_start_github_missing_env_returns_500(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)

    with pytest.raises(HTTPException) as ei:
        await git_oauth_start(
            project_id=s["project"].id, provider="github", ctx=ctx, db=db_session,
        )
    assert ei.value.status_code == 500
    assert "GITHUB_CLIENT_ID" in ei.value.detail


@pytest.mark.asyncio
async def test_oauth_start_gitlab_with_custom_host(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.setenv("GITLAB_CLIENT_ID", "gitlab-fake-id")

    res = await git_oauth_start(
        project_id=s["project"].id, provider="gitlab", ctx=ctx, db=db_session,
        host="https://gitlab.mycompany.com",
    )
    url = res["authorize_url"]
    assert url.startswith("https://gitlab.mycompany.com/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=gitlab-fake-id" in url


@pytest.mark.asyncio
async def test_oauth_callback_state_mismatch_400(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "y")

    req = OAuthCallbackRequest(
        provider="github",
        code="abc",
        state="999",  # 不匹配 project_id
        group_id_or_org="myorg",
    )
    with pytest.raises(HTTPException) as ei:
        await git_oauth_callback(s["project"].id, req, ctx, db_session)
    assert ei.value.status_code == 400
    assert "state" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_oauth_callback_exchanges_code_and_persists(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.setenv("GITHUB_CLIENT_ID", "fake-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "fake-secret")

    captured = {}

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "ghp_oauth_returned_token", "token_type": "bearer"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, headers=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            return _FakeResponse()

    import app.routes.git_connection as mod
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)

    req = OAuthCallbackRequest(
        provider="github",
        code="oauth_code_xyz",
        state=str(s["project"].id),
        group_id_or_org="my-github-org",
    )
    result = await git_oauth_callback(s["project"].id, req, ctx, db_session)

    # 校验：token 换取请求带正确字段
    assert captured["url"] == "https://github.com/login/oauth/access_token"
    assert captured["data"]["client_id"] == "fake-id"
    assert captured["data"]["client_secret"] == "fake-secret"
    assert captured["data"]["code"] == "oauth_code_xyz"

    # 校验：返回的 connection
    assert result["provider"] == "github"
    assert result["group_id_or_org"] == "my-github-org"
    assert result["status"] == "connected"

    # 校验：数据库里 token 已加密 + 可解密回原值
    conn = (await db_session.execute(
        select(GitConnection).where(GitConnection.project_id == s["project"].id)
    )).scalar_one()
    assert conn.access_token_enc != "ghp_oauth_returned_token"
    assert decrypt_token(conn.access_token_enc) == "ghp_oauth_returned_token"


@pytest.mark.asyncio
async def test_oauth_callback_no_access_token_502(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.setenv("GITHUB_CLIENT_ID", "fake-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "fake-secret")

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"error": "bad_verification_code", "error_description": "code 已失效"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, headers=None):
            return _FakeResponse()

    import app.routes.git_connection as mod
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)

    req = OAuthCallbackRequest(
        provider="github",
        code="bad_code",
        state=str(s["project"].id),
        group_id_or_org="my-org",
    )
    with pytest.raises(HTTPException) as ei:
        await git_oauth_callback(s["project"].id, req, ctx, db_session)
    assert ei.value.status_code == 502
    assert "access_token" in ei.value.detail


@pytest.mark.asyncio
async def test_oauth_callback_missing_secret_500(db_session, monkeypatch):
    s = await _seed(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    monkeypatch.setenv("GITHUB_CLIENT_ID", "fake-id")
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)

    req = OAuthCallbackRequest(
        provider="github",
        code="abc",
        state=str(s["project"].id),
        group_id_or_org="my-org",
    )
    with pytest.raises(HTTPException) as ei:
        await git_oauth_callback(s["project"].id, req, ctx, db_session)
    assert ei.value.status_code == 500
    assert "CLIENT_SECRET" in ei.value.detail
