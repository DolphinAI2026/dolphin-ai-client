import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base


@pytest.mark.asyncio
async def test_persist_doc_upload_returns_spec_id_and_keeps_requirements_mode(monkeypatch):
    from app import database
    from app.models import Conversation
    from app.models.spec import Spec as SpecORM
    from app.routes.applications.docs import _persist_doc_upload

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)

    parsed_config = {
        "appName": "配额管理",
        "appCode": "PEGL",
        "roles": [{"code": "quota_admin", "name": "配额管理员", "scope": "ALL"}],
        "dicts": [
            {
                "code": "approval_type",
                "name": "批准书类型",
                "options": [{"code": "delegate", "name": "委托派遣"}],
            }
        ],
        "models": [
            {
                "code": "industry",
                "name": "行业表单",
                "fields": [
                    {"code": "approval_type", "name": "批准书类型", "type": "下拉单选", "dict": "approval_type"},
                    {"code": "company_type", "name": "行业", "type": "单行输入"},
                ],
            }
        ],
        "forms": [],
        "permissions": [
            {
                "form": "industry",
                "rules": [{"role": "quota_admin", "op": "all", "data": "ALL"}],
            }
        ],
    }

    result = await _persist_doc_upload(
        data=parsed_config,
        fname="配额申请_配置文档.md",
        text="# 配额管理",
        parse_meta={"mode": "test"},
        existing_conversation_id=None,
        user_id=1,
        tenant_id=1,
        v1_parsed_config=None,
        is_incremental=False,
    )

    assert result["spec_id"]
    async with Session() as session:
        conversation = await session.get(Conversation, result["conversation_id"])
        spec_row = await session.get(SpecORM, result["spec_id"])

    assert conversation is not None
    assert conversation.agent_type == "requirements"
    assert conversation.spec_id == result["spec_id"]
    assert spec_row is not None
    assert spec_row.payload["goal"]["title"] == "配额管理"

    await engine.dispose()
