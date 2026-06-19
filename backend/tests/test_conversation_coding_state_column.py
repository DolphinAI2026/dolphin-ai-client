from app.models import Conversation


def test_conversation_has_coding_agent_state_column():
    assert "coding_agent_state" in Conversation.__table__.columns
    col = Conversation.__table__.columns["coding_agent_state"]
    assert col.nullable is True


def test_migration_alter_present():
    import inspect as _inspect
    import app.database as db
    src = _inspect.getsource(db.init_db)
    assert "ALTER TABLE conversations ADD COLUMN coding_agent_state" in src
