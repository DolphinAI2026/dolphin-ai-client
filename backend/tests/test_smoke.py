import pytest


def test_pytest_works():
    assert 1 + 1 == 2


@pytest.mark.asyncio
async def test_db_session_yields(db_session):
    assert db_session is not None
    result = await db_session.execute(__import__("sqlalchemy").text("SELECT 1"))
    assert result.scalar() == 1
