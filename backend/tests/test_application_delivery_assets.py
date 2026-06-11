import json

import pytest

from app.deps import AuthContext
from app.models import Application, Conversation, DocumentVersion, Message, User
from app.models.ai_chat import AIChatArtifact, AIChatAttachment, AIChatMessage, AIChatSession
from app.models.tenant import Tenant, UserTenant
from app.routes.applications.docs import list_delivery_assets


async def _seed_app_with_assets(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    owner = User(username="asset_owner", hashed_password="x")
    db_session.add_all([tenant, owner])
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    conversation = Conversation(
        user_id=owner.id,
        tenant_id=tenant.id,
        title="创建巡检管理系统",
        agent_type="builder",
        status="active",
    )
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(Message(
        conversation_id=conversation.id,
        role="user",
        content="需要一个巡检管理系统，包含计划、执行、整改和验收。",
    ))

    chat_session = AIChatSession(
        tenant_id=tenant.id,
        user_id=owner.id,
        title="巡检管理系统调整",
        app_id=None,
    )
    db_session.add(chat_session)
    await db_session.flush()
    db_session.add_all([
        AIChatMessage(
            session_id=chat_session.id,
            role="user",
            content="补充移动端巡检拍照上传能力。",
        ),
        AIChatAttachment(
            session_id=chat_session.id,
            filename="巡检需求.xlsx",
            kind="xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=128,
            content_text="巡检计划、巡检点位、整改闭环",
        ),
        AIChatArtifact(
            session_id=chat_session.id,
            filename="巡检管理系统设计文档.md",
            format="md",
            content="# 巡检管理系统设计文档\n\n包含配置设计和自开发设计。",
            version=2,
        ),
        AIChatArtifact(
            session_id=chat_session.id,
            filename="巡检管理系统UI设计.html",
            format="html",
            content="<html><body>巡检移动端原型</body></html>",
            version=1,
        ),
    ])

    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        conversation_id=conversation.id,
        ai_chat_session_id=chat_session.id,
        app_name="巡检管理系统",
        app_code="inspection-app",
        status="completed",
        apaas_app_id="apaas-1",
        current_doc_version=1,
        config_preview=json.dumps({
            "models": [{"code": "inspection_plan"}, {"code": "inspection_record"}],
            "forms": [{"code": "inspection_plan_form"}],
            "roles": [{"code": "inspector"}],
            "dicts": [{"code": "inspection_status"}],
            "workflows": [{"code": "inspection_flow"}],
        }, ensure_ascii=False),
    )
    db_session.add(app)
    await db_session.flush()
    db_session.add(DocumentVersion(
        application_id=app.id,
        conversation_id=conversation.id,
        version=1,
        filename="巡检管理系统-V1.md",
        content_hash="abc123",
        raw_content="# 巡检管理系统\n\n标准设计文档",
        summary="标准设计文档",
    ))
    await db_session.commit()
    return tenant, owner, app


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


@pytest.mark.asyncio
async def test_delivery_assets_aggregates_application_artifacts(db_session):
    tenant, owner, app = await _seed_app_with_assets(db_session)

    result = await list_delivery_assets(app.id, _ctx(owner, tenant.id), db_session)

    sections = {section["key"]: section for section in result["sections"]}
    assert result["app"]["id"] == app.id
    assert sections["requirements"]["count"] >= 4
    assert sections["design_docs"]["count"] >= 2
    assert sections["ui_designs"]["count"] == 1
    assert sections["build_inventory"]["items"][0]["meta"]["models"] == 2
    assert sections["build_inventory"]["items"][0]["meta"]["forms"] == 2
    assert sections["acceptance_cases"]["items"][0]["kind"] == "generated_cases"
    assert len(sections["acceptance_cases"]["items"][0]["meta"]["cases"]) >= 4


@pytest.mark.asyncio
async def test_delivery_assets_returns_empty_sections_for_plain_app(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    owner = User(username="plain_owner", hashed_password="x")
    db_session.add_all([tenant, owner])
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="空应用",
        app_code="plain-app",
        status="draft",
    )
    db_session.add(app)
    await db_session.commit()

    result = await list_delivery_assets(app.id, _ctx(owner, tenant.id), db_session)

    assert result["summary"] == {
        "requirements": 0,
        "design_docs": 0,
        "ui_designs": 0,
        "build_inventory": 0,
        "acceptance_cases": 0,
    }
