"""平台知识库(规范库)核心 — 查询 + 渐进披露清单渲染。

纯逻辑,被 agent 工具(ai_chat/tools.py)与 manifest 注入(agent.py)复用。
检索用可移植 ilike LIKE 子串匹配(SQLite/MySQL 一致),不走向量/FULLTEXT。
"""
from __future__ import annotations
import re
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.knowledge_doc import KnowledgeDoc


async def list_published_docs(db: AsyncSession) -> list[KnowledgeDoc]:
    res = await db.execute(
        select(KnowledgeDoc)
        .where(KnowledgeDoc.status == "published", KnowledgeDoc.tenant_id.is_(None))
        .order_by(KnowledgeDoc.category, KnowledgeDoc.title)
    )
    return list(res.scalars().all())


async def get_published_doc(db: AsyncSession, slug: str) -> KnowledgeDoc | None:
    res = await db.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.slug == slug,
            KnowledgeDoc.status == "published",
            KnowledgeDoc.tenant_id.is_(None),
        )
    )
    return res.scalar_one_or_none()


def _tokenize(query: str) -> list[str]:
    parts = re.split(r"[\s,，、;；:：。.!！?？/\\()()\[\]]+", (query or "").strip())
    return [p for p in parts if p]


def _score(d: KnowledgeDoc, tokens: list[str]) -> int:
    s = 0
    title, summary, body = (d.title or "").lower(), (d.summary or "").lower(), (d.body_md or "").lower()
    for t in tokens:
        tl = t.lower()
        if tl in title: s += 5
        if tl in summary: s += 3
        if tl in body: s += 1
    return s


async def search_published_docs(db: AsyncSession, query: str, limit: int = 8) -> list[KnowledgeDoc]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    conds = [
        or_(KnowledgeDoc.title.ilike(f"%{t}%"),
            KnowledgeDoc.summary.ilike(f"%{t}%"),
            KnowledgeDoc.body_md.ilike(f"%{t}%"))
        for t in tokens
    ]
    res = await db.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.status == "published",
            KnowledgeDoc.tenant_id.is_(None),
            or_(*conds),  # 命中任一 token 即入选,Python 端按命中加权排序
        )
    )
    docs = list(res.scalars().all())
    docs.sort(key=lambda d: _score(d, tokens), reverse=True)
    return docs[:limit]


def build_knowledge_manifest(docs: list[KnowledgeDoc]) -> str:
    if not docs:
        return ""
    by_cat: dict[str, list[KnowledgeDoc]] = {}
    for d in docs:
        by_cat.setdefault(d.category or "其他", []).append(d)
    lines = [
        "\n\n## 平台知识库(规范)",
        "需要某条规范时,先 `read_knowledge(slug)` 读全文,或 `search_knowledge(query)` 检索:",
    ]
    for cat in sorted(by_cat):
        lines.append(f"[{cat}]")
        for d in by_cat[cat]:
            lines.append(f"- {d.slug}: {d.title} — {d.summary}")
    return "\n".join(lines)
