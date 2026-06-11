# backend/tests/test_app_context_prompt.py
import pytest
from app.ai_chat.app_context import build_app_context_block


@pytest.mark.asyncio
async def test_no_app_id_returns_empty():
    assert await build_app_context_block(db=None, app_id=None) == ""


@pytest.mark.asyncio
async def test_app_context_assembles(monkeypatch):
    import app.ai_chat.app_context as ac
    async def _fake_app(db, app_id):
        return {"id": app_id, "name": "图书借阅", "platform_env_id": 5, "apaas_app_id": "APP9"}
    async def _fake_spec(db, app_id):
        return "SPEC摘要XYZ"
    async def _fake_skills(db, app_id, tenant_id):
        return ["【skill_id=1】「改字段必填」"]
    monkeypatch.setattr(ac, "_load_application", _fake_app)
    monkeypatch.setattr(ac, "_load_spec_text", _fake_spec)
    monkeypatch.setattr(ac, "_load_skills", _fake_skills)
    block = await build_app_context_block(db=object(), app_id=42, section="data", tenant_id=7)
    assert "图书借阅" in block
    assert "SPEC摘要XYZ" in block
    assert "改字段必填" in block
    assert "AI Coding 模块" not in block  # 过时引导不得出现
    assert "数据" in block  # section 软提示


@pytest.mark.asyncio
async def test_app_context_lists_existing_self_dev_workspaces(monkeypatch):
    import app.ai_chat.app_context as ac

    async def _fake_app(db, app_id):
        return {"id": app_id, "name": "企业级研发项目管理PMS", "platform_env_id": 63, "apaas_app_id": "APP9"}

    async def _fake_spec(db, app_id):
        return ""

    async def _fake_skills(db, app_id, tenant_id):
        return []

    async def _fake_workspaces(db, app_id, tenant_id, user_id):
        return [
            {
                "id": "1_existing",
                "project_type": "form-page",
                "project_name": "form-page-project-dashboard",
                "display_name": "项目驾驶舱",
                "status": "ready",
                "project_id": app_id,
            }
        ]

    monkeypatch.setattr(ac, "_load_application", _fake_app)
    monkeypatch.setattr(ac, "_load_spec_text", _fake_spec)
    monkeypatch.setattr(ac, "_load_skills", _fake_skills)
    monkeypatch.setattr(ac, "_load_app_workspaces", _fake_workspaces, raising=False)

    block = await build_app_context_block(db=object(), app_id=5, tenant_id=7, user_id=3)

    assert "已有自开发 workspace" in block
    assert "1_existing" in block
    assert "form-page-project-dashboard" in block
    assert "修改已有自开发代码" in block
    assert "create_dev_workspace" in block
