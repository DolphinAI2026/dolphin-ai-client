import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatSession, AIChatArtifact
from app.ai_chat.tools import execute_tool


async def _mk(tmp_path):
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
async def test_register_file_artifact(tmp_path):
    db, s, ws = await _mk(tmp_path)
    (ws / "out.pptx").write_bytes(b"PK\x03\x04demo")
    res = await execute_tool("save_binary_artifact", {"source_path": "out.pptx"}, s, db)
    assert "out.pptx" in res
    row = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.session_id == s.id))).scalar_one()
    assert row.storage == "file"
    assert row.format == "pptx"
    assert row.size_bytes == 8


@pytest.mark.asyncio
async def test_reject_outside_workspace(tmp_path):
    db, s, ws = await _mk(tmp_path)
    res = await execute_tool("save_binary_artifact", {"source_path": "../escape.pptx"}, s, db)
    assert "错误" in res


@pytest.mark.asyncio
async def test_reject_missing_file(tmp_path):
    db, s, ws = await _mk(tmp_path)
    res = await execute_tool("save_binary_artifact", {"source_path": "ghost.pptx"}, s, db)
    assert "错误" in res
