import pytest
from app.models.app_prototype import AppPrototype


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
