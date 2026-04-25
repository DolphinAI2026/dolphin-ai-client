from sqlalchemy import text


def test_pytest_works():
    assert 1 + 1 == 2


async def test_db_session_yields(db_session):
    assert db_session is not None
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1
