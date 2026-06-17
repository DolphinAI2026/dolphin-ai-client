import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatSession
from app.ai_chat.tools import execute_tool


async def _mk(tmp_path, monkeypatch):
    root = tmp_path / "skills" / "user" / "pptx-brand"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: pptx-brand\ndescription: 出PPT\n---\n第一步: 跑 helper.py\n", encoding="utf-8")
    (root / "helper.py").write_text("print('gen')", encoding="utf-8")
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db = Session()
    ws = tmp_path / "ws"; ws.mkdir()
    s = AIChatSession(tenant_id=1, user_id=1, workspace_dir=str(ws))
    db.add(s); await db.commit(); await db.refresh(s)
    return db, s, ws


@pytest.mark.asyncio
async def test_use_skill_expands_and_copies_files(tmp_path, monkeypatch):
    db, s, ws = await _mk(tmp_path, monkeypatch)
    res = await execute_tool("use_skill", {"name": "pptx-brand"}, s, db)
    assert "第一步" in res          # SKILL.md 正文返回
    assert "helper.py" in res       # 文件清单
    # 文件已拷进 workspace（隔离子目录）
    assert (ws / "skill_pptx-brand" / "helper.py").is_file()


@pytest.mark.asyncio
async def test_use_skill_unknown_name(tmp_path, monkeypatch):
    db, s, ws = await _mk(tmp_path, monkeypatch)
    res = await execute_tool("use_skill", {"name": "nope"}, s, db)
    assert "错误" in res and "pptx-brand" in res  # 列出可用 skill
