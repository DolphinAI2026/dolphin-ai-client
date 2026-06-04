"""ai-builder 精确编辑产出物工具 edit_artifact / read_artifact。

动机：以前改设计文档只能 write_artifact 整篇重写(25K 字、200s)。加 edit_artifact
做 old_string→new_string 精确替换(走 write_artifact 复用 version++/校验)，小改不再整篇重写。
"""
from __future__ import annotations

import pytest
from sqlalchemy import desc, select

from app.ai_chat import tools
from app.models import AIChatSession, AIChatArtifact


async def _seed(db, content: str = "# 设计\n\n模型编码 test委托 检测委托\n字段 apply_no\n") -> AIChatSession:
    s = AIChatSession(tenant_id=1, user_id=1, title="t", status="active")
    db.add(s)
    await db.flush()
    db.add(AIChatArtifact(session_id=s.id, filename="design.md", format="md", content=content, version=1))
    await db.commit()
    await db.refresh(s)
    return s


async def _latest(db, sid):
    return (await db.execute(
        select(AIChatArtifact).where(AIChatArtifact.session_id == sid, AIChatArtifact.filename == "design.md")
        .order_by(desc(AIChatArtifact.version)).limit(1)
    )).scalar_one()


@pytest.mark.asyncio
async def test_edit_artifact_replaces_and_bumps_version(db_session):
    s = await _seed(db_session)
    res = await tools.execute_edit_artifact(
        {"filename": "design.md", "old_string": "test委托", "new_string": "test_entrust"},
        s, db_session,
    )
    assert "错误" not in res
    latest = await _latest(db_session, s.id)
    assert latest.version == 2
    assert "test_entrust" in latest.content
    assert "test委托" not in latest.content
    # 其余内容原样保留 —— 不是整篇重写
    assert "字段 apply_no" in latest.content


@pytest.mark.asyncio
async def test_edit_artifact_old_string_not_found_no_new_version(db_session):
    s = await _seed(db_session)
    res = await tools.execute_edit_artifact(
        {"filename": "design.md", "old_string": "压根不存在的串", "new_string": "x"},
        s, db_session,
    )
    assert "错误" in res and "未找到" in res
    rows = (await db_session.execute(
        select(AIChatArtifact).where(AIChatArtifact.session_id == s.id)
    )).scalars().all()
    assert len(rows) == 1  # 没有新版本被写出


@pytest.mark.asyncio
async def test_edit_artifact_multiple_matches_rejected(db_session):
    s = await _seed(db_session, content="dup line\nmiddle\ndup line\n")
    res = await tools.execute_edit_artifact(
        {"filename": "design.md", "old_string": "dup line", "new_string": "x"},
        s, db_session,
    )
    assert "错误" in res and ("2" in res or "多" in res)
    rows = (await db_session.execute(
        select(AIChatArtifact).where(AIChatArtifact.session_id == s.id)
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_edit_artifact_missing_file(db_session):
    s = await _seed(db_session)
    res = await tools.execute_edit_artifact(
        {"filename": "nope.md", "old_string": "a", "new_string": "b"}, s, db_session,
    )
    assert "错误" in res and "不存在" in res


@pytest.mark.asyncio
async def test_read_artifact_returns_current_content(db_session):
    s = await _seed(db_session)
    res = await tools.execute_read_artifact({"filename": "design.md"}, s, db_session)
    assert "test委托" in res
    assert "apply_no" in res


@pytest.mark.asyncio
async def test_read_artifact_missing_file(db_session):
    s = await _seed(db_session)
    res = await tools.execute_read_artifact({"filename": "nope.md"}, s, db_session)
    assert "错误" in res and "不存在" in res


def test_edit_and_read_artifact_registered():
    assert "edit_artifact" in tools.TOOL_HANDLERS
    assert "read_artifact" in tools.TOOL_HANDLERS
    names = [s["function"]["name"] for s in tools.TOOL_SCHEMAS]
    assert "edit_artifact" in names
    assert "read_artifact" in names
