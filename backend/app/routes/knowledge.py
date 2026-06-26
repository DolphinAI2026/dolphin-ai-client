# backend/app/routes/knowledge.py
"""平台知识库(规范库)管理 — /knowledge CRUD。仅平台管理员可读写;
agent 不经此路由,直接查 DB(app.knowledge_base)。"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.deps import AuthContext, require_platform_admin
from app.models.knowledge_doc import KnowledgeDoc

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class DocIn(BaseModel):
    slug: str
    title: str
    summary: str = ""
    category: str = "平台规范"
    tags: Optional[str] = None
    body_md: str
    status: str = "draft"


class DocOut(BaseModel):
    id: int
    slug: str
    title: str
    summary: str
    category: str
    tags: Optional[str]
    body_md: str
    status: str
    updated_at: datetime

    @classmethod
    def of(cls, d: KnowledgeDoc) -> "DocOut":
        return cls(id=d.id, slug=d.slug, title=d.title, summary=d.summary,
                   category=d.category, tags=d.tags, body_md=d.body_md,
                   status=d.status, updated_at=d.updated_at)


@router.get("/docs")
async def list_docs(
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = None,
    status: Optional[str] = None,
):
    stmt = select(KnowledgeDoc).where(KnowledgeDoc.tenant_id.is_(None))
    if category:
        stmt = stmt.where(KnowledgeDoc.category == category)
    if status:
        stmt = stmt.where(KnowledgeDoc.status == status)
    res = await db.execute(stmt.order_by(KnowledgeDoc.category, KnowledgeDoc.title))
    return {"docs": [DocOut.of(d).model_dump() for d in res.scalars().all()]}


@router.get("/docs/{slug}")
async def get_doc(
    slug: str,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    res = await db.execute(select(KnowledgeDoc).where(
        KnowledgeDoc.slug == slug, KnowledgeDoc.tenant_id.is_(None)))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "文档不存在")
    return DocOut.of(d).model_dump()


@router.post("/docs")
async def create_doc(
    body: DocIn,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if (await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == body.slug))).scalar_one_or_none():
        raise HTTPException(409, f"slug 已存在: {body.slug}")
    d = KnowledgeDoc(slug=body.slug, title=body.title, summary=body.summary,
                     category=body.category, tags=body.tags, body_md=body.body_md,
                     status=body.status, tenant_id=None, updated_by=ctx.user.id)
    db.add(d)
    await db.commit()           # get_db 不 autocommit,必须显式 commit
    await db.refresh(d)
    return DocOut.of(d).model_dump()


@router.put("/docs/{slug}")
async def update_doc(
    slug: str,
    body: DocIn,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    res = await db.execute(select(KnowledgeDoc).where(
        KnowledgeDoc.slug == slug, KnowledgeDoc.tenant_id.is_(None)))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "文档不存在")
    d.title, d.summary, d.category = body.title, body.summary, body.category
    d.tags, d.body_md, d.status = body.tags, body.body_md, body.status
    d.updated_by = ctx.user.id
    await db.commit()
    await db.refresh(d)
    return DocOut.of(d).model_dump()


@router.delete("/docs/{slug}")
async def delete_doc(
    slug: str,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    res = await db.execute(select(KnowledgeDoc).where(
        KnowledgeDoc.slug == slug, KnowledgeDoc.tenant_id.is_(None)))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "文档不存在")
    await db.delete(d)
    await db.commit()
    return {"ok": True}
