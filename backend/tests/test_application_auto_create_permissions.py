import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.deps import AuthContext
from app.models import Application, Conversation, DocumentVersion, PlatformEnv, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import Tenant, UserTenant
from app.routes.applications.crud import AutoCreateRequest, auto_create_application


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
    tenant = Tenant(tenant_name="Auto create permissions", tenant_code="auto-create-permissions")
    db.add(tenant)
    await db.flush()

    owner = await _user(db, tenant.id, "auto-create-owner")
    collaborator = await _user(db, tenant.id, "auto-create-collaborator")
    admin = await _user(db, tenant.id, "auto-create-admin")
    outsider = await _user(db, tenant.id, "auto-create-outsider")
    old_env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="Old environment",
        base_url="https://old.example.test",
        platform_tenant_id="old-tenant",
        status="connected",
    )
    new_env = PlatformEnv(
        tenant_id=tenant.id,
        env_name="New environment",
        base_url="https://new.example.test",
        platform_tenant_id="new-tenant",
        status="connected",
    )
    db.add_all([old_env, new_env])
    await db.flush()

    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="Original",
        app_code="shared-code",
        config_preview=(
            '{"type":"preview","data":{"appCode":"shared-code",'
            '"models":[{"code":"original-model"}]}}'
        ),
        platform_env_id=old_env.id,
        status="completed",
    )
    db.add(app)
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
        "old_env": old_env,
        "new_env": new_env,
        "app": app,
    }


async def _add_conversation_state(db, seed, conversation_user: User):
    conversation = Conversation(
        user_id=conversation_user.id,
        tenant_id=seed["tenant"].id,
        title="Shared conversation",
        agent_type="builder",
    )
    db.add(conversation)
    await db.flush()
    seed["app"].conversation_id = conversation.id
    seed["app"].current_doc_version = 1
    current = DocumentVersion(
        application_id=seed["app"].id,
        conversation_id=conversation.id,
        version=1,
        filename="original-v1.md",
        content_hash="original-v1-hash",
        raw_content="original-v1-content",
        parsed_config='{"appCode":"shared-code","models":[]}',
    )
    pending = DocumentVersion(
        application_id=None,
        conversation_id=conversation.id,
        version=2,
        filename="pending-v2.md",
        content_hash="pending-v2-hash",
        raw_content="pending-v2-content",
        parsed_config='{"appCode":"shared-code","models":[]}',
    )
    db.add_all([current, pending])
    await db.commit()
    return conversation, current, pending


def _request(seed, create_mode=None, conversation_id=None) -> AutoCreateRequest:
    return AutoCreateRequest(
        app_name="Updated Name",
        config_preview={
            "type": "preview",
            "data": {
                "appCode": "shared-code",
                "models": [{"code": "new-model"}],
            },
        },
        conversation_id=conversation_id,
        platform_env_id=seed["new_env"].id,
        create_mode=create_mode,
    )


@pytest.mark.asyncio
async def test_auto_create_reuse_denies_outsider_before_mutating_existing_application(
    db_session,
):
    seed = await _seed(db_session)
    app = seed["app"]
    original = {
        "config_preview": app.config_preview,
        "app_name": app.app_name,
        "platform_env_id": app.platform_env_id,
        "status": app.status,
    }

    with pytest.raises(HTTPException) as denied:
        await auto_create_application(
            _request(seed),
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
        )

    assert denied.value.status_code == 403
    await db_session.refresh(app)
    assert {
        "config_preview": app.config_preview,
        "app_name": app.app_name,
        "platform_env_id": app.platform_env_id,
        "status": app.status,
    } == original
    assert await db_session.scalar(select(func.count(Application.id))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("user_key", ["owner", "collaborator", "admin"])
async def test_auto_create_reuse_allows_users_with_edit_permission(db_session, user_key):
    seed = await _seed(db_session)

    result = await auto_create_application(
        _request(seed),
        _ctx(seed[user_key], seed["tenant"].id),
        db_session,
    )

    assert result.app_id == seed["app"].id
    assert result.is_new is False
    assert seed["app"].app_name == "Updated Name"
    assert seed["app"].platform_env_id == seed["new_env"].id
    assert seed["app"].status == "draft"
    assert "original-model" in seed["app"].config_preview
    assert "new-model" in seed["app"].config_preview


@pytest.mark.asyncio
async def test_auto_create_force_new_creates_suffixed_application_without_reusing_existing(
    db_session,
):
    seed = await _seed(db_session)
    original_config = seed["app"].config_preview

    result = await auto_create_application(
        _request(seed, create_mode="new"),
        _ctx(seed["outsider"], seed["tenant"].id),
        db_session,
    )

    assert result.is_new is True
    assert result.app_id != seed["app"].id
    created = await db_session.get(Application, result.app_id)
    assert created.app_code == "shared-code-2"
    await db_session.refresh(seed["app"])
    assert seed["app"].config_preview == original_config
    assert seed["app"].app_name == "Original"
    assert seed["app"].status == "completed"
    assert await db_session.scalar(select(func.count(Application.id))) == 2


@pytest.mark.asyncio
async def test_auto_create_conversation_reuse_denies_outsider_before_any_mutation(
    db_session,
):
    seed = await _seed(db_session)
    conversation, current, pending = await _add_conversation_state(
        db_session, seed, seed["outsider"]
    )
    app = seed["app"]
    original_app = {
        "app_code": app.app_code,
        "config_preview": app.config_preview,
        "app_name": app.app_name,
        "platform_env_id": app.platform_env_id,
        "current_doc_version": app.current_doc_version,
    }
    original_current = {
        "application_id": current.application_id,
        "version": current.version,
        "content_hash": current.content_hash,
        "raw_content": current.raw_content,
        "parsed_config": current.parsed_config,
    }
    original_pending = {
        "application_id": pending.application_id,
        "version": pending.version,
        "content_hash": pending.content_hash,
        "raw_content": pending.raw_content,
        "parsed_config": pending.parsed_config,
    }

    with pytest.raises(HTTPException) as denied:
        await auto_create_application(
            _request(seed, conversation_id=conversation.id),
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
        )

    assert denied.value.status_code == 403
    await db_session.refresh(app)
    await db_session.refresh(current)
    await db_session.refresh(pending)
    assert {
        "app_code": app.app_code,
        "config_preview": app.config_preview,
        "app_name": app.app_name,
        "platform_env_id": app.platform_env_id,
        "current_doc_version": app.current_doc_version,
    } == original_app
    assert {
        "application_id": current.application_id,
        "version": current.version,
        "content_hash": current.content_hash,
        "raw_content": current.raw_content,
        "parsed_config": current.parsed_config,
    } == original_current
    assert {
        "application_id": pending.application_id,
        "version": pending.version,
        "content_hash": pending.content_hash,
        "raw_content": pending.raw_content,
        "parsed_config": pending.parsed_config,
    } == original_pending


@pytest.mark.asyncio
async def test_auto_create_denies_foreign_conversation_before_creating_or_binding(
    db_session,
):
    seed = await _seed(db_session)
    conversation = Conversation(
        user_id=seed["owner"].id,
        tenant_id=seed["tenant"].id,
        title="Owner-only conversation",
        agent_type="builder",
    )
    db_session.add(conversation)
    await db_session.flush()
    pending = DocumentVersion(
        application_id=None,
        conversation_id=conversation.id,
        version=1,
        filename="owner-pending.md",
        content_hash="owner-pending-hash",
        raw_content="owner-pending-content",
        parsed_config='{"appCode":"foreign-conversation-code","models":[]}',
    )
    db_session.add(pending)
    await db_session.commit()
    original_count = await db_session.scalar(select(func.count(Application.id)))
    original_pending = {
        "application_id": pending.application_id,
        "version": pending.version,
        "content_hash": pending.content_hash,
        "raw_content": pending.raw_content,
        "parsed_config": pending.parsed_config,
    }

    with pytest.raises(HTTPException) as denied:
        await auto_create_application(
            AutoCreateRequest(
                app_name="Foreign Conversation App",
                config_preview={
                    "type": "preview",
                    "data": {
                        "appCode": "foreign-conversation-code",
                        "models": [],
                    },
                },
                conversation_id=conversation.id,
                platform_env_id=seed["new_env"].id,
            ),
            _ctx(seed["outsider"], seed["tenant"].id),
            db_session,
        )

    assert denied.value.status_code == 404
    assert await db_session.scalar(select(func.count(Application.id))) == original_count
    created = await db_session.scalar(
        select(Application).where(Application.app_code == "foreign-conversation-code")
    )
    assert created is None
    await db_session.refresh(pending)
    assert {
        "application_id": pending.application_id,
        "version": pending.version,
        "content_hash": pending.content_hash,
        "raw_content": pending.raw_content,
        "parsed_config": pending.parsed_config,
    } == original_pending


@pytest.mark.asyncio
@pytest.mark.parametrize("user_key", ["owner", "collaborator", "admin"])
async def test_auto_create_conversation_reuse_allows_editors_and_binds_pending_version(
    db_session, user_key
):
    seed = await _seed(db_session)
    conversation, _current, pending = await _add_conversation_state(
        db_session, seed, seed[user_key]
    )

    result = await auto_create_application(
        _request(seed, conversation_id=conversation.id),
        _ctx(seed[user_key], seed["tenant"].id),
        db_session,
    )

    assert result.app_id == seed["app"].id
    assert result.is_new is False
    assert seed["app"].app_name == "Updated Name"
    assert seed["app"].platform_env_id == seed["new_env"].id
    assert seed["app"].current_doc_version == 2
    assert "new-model" in seed["app"].config_preview
    await db_session.refresh(pending)
    assert pending.application_id == seed["app"].id
    assert pending.version == 2
    assert "new-model" in pending.parsed_config
