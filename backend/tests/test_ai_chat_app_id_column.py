import pytest
from sqlalchemy import inspect as sa_inspect
from app.models.ai_chat import AIChatSession
from app.models.config_chat import ConfigChatSession


def test_aichatsession_has_app_id_column():
    cols = {c.name for c in sa_inspect(AIChatSession).columns}
    assert "app_id" in cols


def test_configchatsession_has_migrated_marker():
    cols = {c.name for c in sa_inspect(ConfigChatSession).columns}
    assert "migrated_session_id" in cols
