import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.deps import AuthContext
from app.models import Application, User
from app.models.ai_chat import AIChatArtifact, AIChatSession
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.routes.applications.lifecycle import (
    DeployFromArtifactReq,
    deploy_from_artifact,
    deploy_status,
)


async def _user(db, tenant_id: int, username: str) -> User:
    user = User(username=username, hashed_password="x")
    db.add(user)
    await db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant_id, status=1))
    return user


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="member",
        org_permissions={},
    )


async def _seed(db):
    tenant = Tenant(tenant_name="Deploy permissions", tenant_code="deploy-permissions")
    db.add(tenant)
    await db.flush()

    owner = await _user(db, tenant.id, "deploy-owner")
    collaborator = await _user(db, tenant.id, "deploy-collaborator")
    admin = await _user(db, tenant.id, "deploy-admin")
    outsider = await _user(db, tenant.id, "deploy-outsider")

    session = AIChatSession(
        tenant_id=tenant.id,
        user_id=owner.id,
        title="Deploy source",
    )
    db.add(session)
    await db.flush()
    artifact = AIChatArtifact(
        session_id=session.id,
        filename="updated-design.md",
        format="md",
        content="# Updated design",
    )
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="Original",
        app_code="shared-code",
        requirement_doc="original-doc",
        config_preview='{"type":"preview","data":{"appCode":"shared-code","models":[]}}',
        status="completed",
        ai_chat_session_id=None,
    )
    db.add_all([artifact, app])
    await db.flush()
    db.add_all(
        [
            ApplicationMember(
                application_id=app.id,
                user_id=collaborator.id,
                role="collaborator",
                invited_by=owner.id,
            ),
            ApplicationMember(
                application_id=app.id,
                user_id=admin.id,
                role="admin",
                invited_by=owner.id,
            ),
        ]
    )
    await db.commit()
    return {
        "tenant": tenant,
        "owner": owner,
        "collaborator": collaborator,
        "admin": admin,
        "outsider": outsider,
        "artifact": artifact,
        "app": app,
    }


def _patch_design_parser(monkeypatch):
    monkeypatch.setattr(
        "app.doc_parser.parse_design_doc",
        lambda _: {
            "type": "preview",
            "data": {
                "appName": "Updated Name",
                "appCode": "shared-code",
                "models": [],
            },
        },
    )


async def _artifact_for_user(db, seed, user: User) -> AIChatArtifact:
    if user.id == seed["owner"].id:
        return seed["artifact"]
    session = AIChatSession(
        tenant_id=seed["tenant"].id,
        user_id=user.id,
        title=f"Deploy source for {user.username}",
    )
    db.add(session)
    await db.flush()
    artifact = AIChatArtifact(
        session_id=session.id,
        filename="updated-design.md",
        format="md",
        content="# Updated design",
    )
    db.add(artifact)
    await db.commit()
    return artifact


@pytest.mark.asyncio
async def test_deploy_reuse_denies_outsider_before_mutating_existing_application(
    db_session, monkeypatch
):
    seed = await _seed(db_session)
    _patch_design_parser(monkeypatch)
    artifact = await _artifact_for_user(db_session, seed, seed["outsider"])
    app = seed["app"]
    original = {
        "app_name": app.app_name,
        "requirement_doc": app.requirement_doc,
        "config_preview": app.config_preview,
        "platform_env_id": app.platform_env_id,
        "status": app.status,
        "ai_chat_session_id": app.ai_chat_session_id,
    }

    with pytest.raises(HTTPException) as denied:
        await deploy_from_artifact(
            DeployFromArtifactReq(
                artifact_id=artifact.id,
                app_code="shared-code",
            ),
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
        )

    assert denied.value.status_code == 403
    await db_session.refresh(app)
    assert {
        "app_name": app.app_name,
        "requirement_doc": app.requirement_doc,
        "config_preview": app.config_preview,
        "platform_env_id": app.platform_env_id,
        "status": app.status,
        "ai_chat_session_id": app.ai_chat_session_id,
    } == original
    app_count = await db_session.scalar(select(func.count(Application.id)))
    assert app_count == 1


@pytest.mark.asyncio
async def test_deploy_denies_outsider_from_creating_application_from_foreign_artifact(
    db_session, monkeypatch
):
    seed = await _seed(db_session)
    _patch_design_parser(monkeypatch)
    original_count = await db_session.scalar(select(func.count(Application.id)))

    with pytest.raises(HTTPException) as denied:
        await deploy_from_artifact(
            DeployFromArtifactReq(
                artifact_id=seed["artifact"].id,
                app_code="stolen-new-code",
            ),
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
        )

    assert denied.value.status_code in {403, 404}
    assert await db_session.scalar(select(func.count(Application.id))) == original_count
    stolen = await db_session.scalar(
        select(Application).where(Application.app_code == "stolen-new-code")
    )
    assert stolen is None


@pytest.mark.asyncio
@pytest.mark.parametrize("user_key", ["owner", "collaborator", "admin"])
async def test_deploy_reuse_allows_users_with_edit_permission(
    db_session, monkeypatch, user_key
):
    seed = await _seed(db_session)
    _patch_design_parser(monkeypatch)
    artifact = await _artifact_for_user(db_session, seed, seed[user_key])

    result = await deploy_from_artifact(
        DeployFromArtifactReq(
            artifact_id=artifact.id,
            app_code="shared-code",
        ),
        _ctx(seed[user_key], seed["tenant"].id),
        db_session,
    )

    assert result.app_id == seed["app"].id
    assert seed["app"].app_name == "Updated Name"
    assert seed["app"].status == "generating"


@pytest.mark.asyncio
async def test_deploy_status_denies_outsider_for_existing_application(db_session):
    seed = await _seed(db_session)

    with pytest.raises(HTTPException) as denied:
        await deploy_status(
            f'deploy-art-{seed["app"].id}-123',
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
        )

    assert denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("user_key", ["collaborator", "admin"])
async def test_deploy_status_allows_users_with_view_permission(db_session, user_key):
    seed = await _seed(db_session)

    result = await deploy_status(
        f'deploy-art-{seed["app"].id}-123',
        _ctx(seed[user_key], seed["tenant"].id),
        db_session,
    )

    assert result.app_id == seed["app"].id
    assert result.phase == "completed"
    assert result.done is True
