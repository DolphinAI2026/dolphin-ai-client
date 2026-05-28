import pytest
from sqlalchemy import select
from app.models.app_prototype import AppPrototype


# ---------------------------------------------------------------------------
# Task 3 — _generate_event_stream: persists to DB + emits prototype_ready
# ---------------------------------------------------------------------------


def _async_return(v):
    """Return a coroutine that resolves to v (helper for monkeypatching async fns)."""
    async def _f(*a, **k):
        return v
    return _f()


@pytest.mark.asyncio
async def test_generate_prototype_persists_and_emits_ready(db_session, monkeypatch):
    from app.routes.applications import prototype as proto_mod

    # Patch build_prototype_prompt to be a simple async function returning a constant
    async def fake_build_prompt(db, app_id):
        return "PROMPT"

    monkeypatch.setattr(proto_mod, "build_prototype_prompt", fake_build_prompt)

    # Patch _llm_html_stream to be a simple async generator yielding HTML chunks
    async def fake_stream(prompt, db, tenant_id, app_id):
        for chunk in ["<!DOCTYPE html><body>", "<div data-block='卡片'>x</div>", "</body>"]:
            yield chunk

    monkeypatch.setattr(proto_mod, "_llm_html_stream", fake_stream)

    events = []
    async for ev in proto_mod._generate_event_stream(db_session, app_id=1, tenant_id=1, user_id=1):
        events.append(ev)

    # Must emit a prototype_ready event
    assert any(e.get("event") == "prototype_ready" for e in events), (
        f"Expected 'prototype_ready' event, got: {[e.get('event') for e in events]}"
    )

    # Must persist exactly one row for app_id=1
    rows = (await db_session.execute(
        select(AppPrototype).where(AppPrototype.app_id == 1)
    )).scalars().all()
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"

    # Persisted HTML must contain the data-block marker
    assert "data-block" in rows[0].html_content, "HTML content missing data-block attribute"


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
