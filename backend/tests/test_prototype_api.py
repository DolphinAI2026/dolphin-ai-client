import pytest
from app.models.app_prototype import AppPrototype


@pytest.mark.asyncio
async def test_build_prototype_prompt_includes_models(db_session, monkeypatch):
    from app.routes.applications import prototype

    async def fake_read(db, app_id, section_type, section_key):
        # Real convention (spec_chat.py _section_key_for):
        #   data_model chapter → section_type="data_model", section_key="main"
        if section_type == "data_model" and section_key == "main":
            return {"ok": True, "exists": True,
                    "section": {"spec_json": {"models": [{"name": "供应商", "fields": [{"name": "风险等级"}]}]}}}
        return {"ok": True, "exists": False}

    monkeypatch.setattr(prototype, "read_spec_section", fake_read)
    prompt = await prototype.build_prototype_prompt(db_session, app_id=1)

    assert "供应商" in prompt
    assert "风险等级" in prompt
    assert "data-block" in prompt  # prompt 必须要求给可点选区块加 data-block
    assert "iframe" in prompt.lower()  # 必须要求可独立预览


@pytest.mark.asyncio
async def test_app_prototype_insert_and_query(db_session):
    proto = AppPrototype(
        app_id=1,
        tenant_id=1,
        version=1,
        html_content="<html><body>hi</body></html>",
        source_spec_version=3,
        created_by=1,
    )
    db_session.add(proto)
    await db_session.commit()
    await db_session.refresh(proto)

    assert proto.id is not None
    assert proto.app_id == 1
    assert proto.version == 1
    assert "<body>" in proto.html_content
