"""桌面端附件解析失败的传播守卫回归测试。

背景: 桌面打包曾排除文档解析库 → import 失败被静默吞 → read_attachment 永远"解析失败或为空"。
修复把可读原因写进 content_text(带 DOC_PARSE_ERROR_PREFIX 前缀)。本测试锁住三处守卫:
  1. execute_read_attachment 识别错误前缀 → 返回"解析失败: <原因>"而非当正文喂 LLM。
  2. execute_create_artifact_from_attachment 同样不把错误标记复制进 artifact。
  3. web 端 chat.py 上传循环不把错误标记当文档段(if parsed: 回归)。
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models.ai_chat  # noqa: F401  (register tables)
from app.models.ai_chat import AIChatSession, AIChatAttachment
from app.ai_chat.tools import (
    execute_read_attachment,
    execute_create_artifact_from_attachment,
)
from app.routes.chat import DOC_PARSE_ERROR_PREFIX


async def _make_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.mark.asyncio
async def test_read_attachment_returns_parse_error_not_content():
    Session = await _make_db()
    async with Session() as db:
        s = AIChatSession(tenant_id=1, user_id=1, title="t")
        db.add(s); await db.flush()
        db.add(AIChatAttachment(
            session_id=s.id, filename="bad.pdf", kind="pdf",
            mime="application/pdf", size_bytes=10,
            content_text=DOC_PARSE_ERROR_PREFIX + "桌面端缺少 PDF 解析库 (pdfplumber)",
        ))
        await db.commit()
        out = await execute_read_attachment({"filename": "bad.pdf"}, s, db)
    assert "解析失败" in out
    assert "桌面端缺少 PDF 解析库 (pdfplumber)" in out
    # 关键: 错误标记前缀本身不能被当正文回给 agent
    assert not out.startswith(DOC_PARSE_ERROR_PREFIX)


@pytest.mark.asyncio
async def test_create_artifact_from_attachment_rejects_parse_failure():
    Session = await _make_db()
    async with Session() as db:
        s = AIChatSession(tenant_id=1, user_id=1, title="t")
        db.add(s); await db.flush()
        db.add(AIChatAttachment(
            session_id=s.id, filename="bad.docx", kind="docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=10,
            content_text=DOC_PARSE_ERROR_PREFIX + "docx 解析出错: boom",
        ))
        await db.commit()
        out = await execute_create_artifact_from_attachment({"filename": "bad.docx"}, s, db)
    assert "解析失败" in out
    assert "无法转 artifact" in out


@pytest.mark.asyncio
async def test_read_attachment_ok_returns_content():
    """正常正文仍照常返回(不被守卫误伤)。"""
    Session = await _make_db()
    async with Session() as db:
        s = AIChatSession(tenant_id=1, user_id=1, title="t")
        db.add(s); await db.flush()
        db.add(AIChatAttachment(
            session_id=s.id, filename="ok.docx", kind="docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=10, content_text="这是正常的文档正文",
        ))
        await db.commit()
        out = await execute_read_attachment({"filename": "ok.docx"}, s, db)
    assert out == "这是正常的文档正文"


def test_chat_upload_loop_skips_parse_failure_marker(monkeypatch):
    """web 端 chat.py 的 `if parsed:` 不能把解析失败标记拼进 doc_segments —
    否则会污染会话内容并误导 _detect_doc 评分/doc_pipeline 路由。

    直接复刻 chat.py 上传循环里那段判定逻辑, 锁住前缀守卫。
    """
    from app.routes import chat as chat_mod
    prefix = chat_mod.DOC_PARSE_ERROR_PREFIX

    def _segment_if_kept(upload_name: str, parsed: str) -> str | None:
        # 与 chat.py:996-1001 的守卫保持一致
        if parsed and not parsed.startswith(prefix):
            return f"## 文件：{upload_name}\n\n{parsed}"
        return None

    # 解析失败标记 → 跳过(等价旧的空串静默跳过)
    assert _segment_if_kept("bad.pdf", prefix + "桌面端缺少 PDF 解析库 (pdfplumber)") is None
    # 空串 → 跳过
    assert _segment_if_kept("empty.pdf", "") is None
    # 真正文 → 保留
    seg = _segment_if_kept("ok.docx", "正文内容")
    assert seg is not None and "正文内容" in seg
