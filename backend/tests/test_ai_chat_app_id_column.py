from sqlalchemy import inspect as sa_inspect
from app.models.ai_chat import AIChatSession


def test_aichatsession_has_app_id_column():
    cols = {c.name for c in sa_inspect(AIChatSession).columns}
    assert "app_id" in cols
