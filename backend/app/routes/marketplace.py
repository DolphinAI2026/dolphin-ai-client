"""
Marketplace API 路由 - 组件市场
"""

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, or_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, MarketplaceComponent
from app.deps import get_auth_context, AuthContext
from app.coding.workspace import WORKSPACE_ROOT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketplace", tags=["marketplace"])

# 市场组件 zip 存储根目录
MARKETPLACE_STORE = Path(__file__).parent.parent.parent.parent / "marketplace_store"
MARKETPLACE_STORE.mkdir(parents=True, exist_ok=True)


# ============================================================
# 请求/响应模型
# ============================================================

class PublishRequest(BaseModel):
    """发布组件到市场"""
    workspace_id: str
    name: str
    code: str
    description: Optional[str] = None
    category: str = "form-component"
    version: str = "1.0.0"
    tags: Optional[list[str]] = None
    readme: Optional[str] = None


class ComponentResponse(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str]
    category: str
    version: str
    author_id: int
    author_name: Optional[str] = None
    tenant_id: int
    download_count: int
    tags: Optional[list[str]] = None
    readme: Optional[str] = None
    source_workspace_id: Optional[str] = None
    published_at: str
    updated_at: str

    class Config:
        from_attributes = True


def _component_to_response(comp: MarketplaceComponent, author_name: str = None) -> dict:
    """Convert model to response dict."""
    tags = None
    if comp.tags:
        try:
            tags = json.loads(comp.tags)
        except (json.JSONDecodeError, TypeError):
            tags = None
    return {
        "id": comp.id,
        "name": comp.name,
        "code": comp.code,
        "description": comp.description,
        "category": comp.category,
        "version": comp.version,
        "author_id": comp.author_id,
        "author_name": author_name,
        "tenant_id": comp.tenant_id,
        "download_count": comp.download_count,
        "tags": tags,
        "readme": comp.readme,
        "source_workspace_id": comp.source_workspace_id,
        "published_at": comp.published_at.isoformat() if comp.published_at else "",
        "updated_at": comp.updated_at.isoformat() if comp.updated_at else "",
    }


# ============================================================
# 路由
# ============================================================

@router.get("")
async def list_components(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    category: Optional[str] = Query(None, description="分类筛选"),
    sort: Optional[str] = Query("latest", description="排序: latest / popular"),
):
    """列出/搜索市场组件"""
    query = select(MarketplaceComponent)

    # 关键词搜索
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            or_(
                MarketplaceComponent.name.ilike(pattern),
                MarketplaceComponent.description.ilike(pattern),
                MarketplaceComponent.tags.ilike(pattern),
            )
        )

    # 分类筛选
    if category:
        query = query.where(MarketplaceComponent.category == category)

    # 排序
    if sort == "popular":
        query = query.order_by(desc(MarketplaceComponent.download_count))
    else:
        query = query.order_by(desc(MarketplaceComponent.published_at))

    result = await db.execute(query)
    components = result.scalars().all()

    # 批量获取作者名
    author_ids = list({c.author_id for c in components})
    author_map = {}
    if author_ids:
        author_result = await db.execute(select(User).where(User.id.in_(author_ids)))
        for u in author_result.scalars().all():
            author_map[u.id] = u.username

    return [_component_to_response(c, author_map.get(c.author_id)) for c in components]


@router.get("/my")
async def list_my_components(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前用户发布的组件"""
    result = await db.execute(
        select(MarketplaceComponent)
        .where(MarketplaceComponent.author_id == ctx.user.id)
        .order_by(desc(MarketplaceComponent.published_at))
    )
    components = result.scalars().all()
    return [_component_to_response(c, ctx.user.username) for c in components]


@router.get("/{component_id}")
async def get_component(
    component_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取组件详情"""
    result = await db.execute(
        select(MarketplaceComponent).where(MarketplaceComponent.id == component_id)
    )
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(status_code=404, detail="组件不存在")

    # 获取作者名
    author_result = await db.execute(select(User).where(User.id == comp.author_id))
    author = author_result.scalar_one_or_none()
    author_name = author.username if author else None

    return _component_to_response(comp, author_name)


@router.post("/publish")
async def publish_component(
    req: PublishRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从工作区发布组件到市场"""
    ws_path = WORKSPACE_ROOT / req.workspace_id
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")

    # 检查 code 唯一性
    existing = await db.execute(
        select(MarketplaceComponent).where(MarketplaceComponent.code == req.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"组件代码 '{req.code}' 已被使用")

    # 打包工作区 src 目录为 zip
    src_dir = ws_path / "src"
    if not src_dir.exists():
        src_dir = ws_path  # fallback to entire workspace

    zip_filename = f"{req.code}-{req.version}.zip"
    zip_dest = MARKETPLACE_STORE / zip_filename

    # 创建 zip 包
    with tempfile.TemporaryDirectory() as tmp:
        archive_base = Path(tmp) / req.code
        shutil.copytree(src_dir, archive_base, dirs_exist_ok=True)
        # 同时复制 package.json 如果存在
        pkg_json = ws_path / "package.json"
        if pkg_json.exists():
            shutil.copy2(pkg_json, archive_base / "package.json")
        shutil.make_archive(str(zip_dest.with_suffix("")), "zip", tmp, req.code)

    # 创建数据库记录
    comp = MarketplaceComponent(
        name=req.name,
        code=req.code,
        description=req.description,
        category=req.category,
        version=req.version,
        author_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        tags=json.dumps(req.tags) if req.tags else None,
        readme=req.readme,
        zip_path=str(zip_dest),
        source_workspace_id=req.workspace_id,
    )
    db.add(comp)
    await db.commit()
    await db.refresh(comp)

    logger.info(f"Component published: {req.code} v{req.version} by user {ctx.user.id}")
    return _component_to_response(comp, ctx.user.username)


@router.get("/{component_id}/download")
async def download_component(
    component_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """下载组件 zip 包"""
    result = await db.execute(
        select(MarketplaceComponent).where(MarketplaceComponent.id == component_id)
    )
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(status_code=404, detail="组件不存在")

    if not comp.zip_path or not Path(comp.zip_path).exists():
        raise HTTPException(status_code=404, detail="组件包文件不存在")

    # 增加下载计数
    comp.download_count = (comp.download_count or 0) + 1
    await db.commit()

    return FileResponse(
        path=comp.zip_path,
        media_type="application/zip",
        filename=f"{comp.code}-{comp.version}.zip",
    )


@router.delete("/{component_id}")
async def unpublish_component(
    component_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """下架组件（仅作者可操作）"""
    result = await db.execute(
        select(MarketplaceComponent).where(MarketplaceComponent.id == component_id)
    )
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(status_code=404, detail="组件不存在")

    if comp.author_id != ctx.user.id:
        raise HTTPException(status_code=403, detail="只有作者可以下架组件")

    # 删除 zip 文件
    if comp.zip_path and Path(comp.zip_path).exists():
        try:
            Path(comp.zip_path).unlink()
        except OSError:
            logger.warning(f"Failed to delete zip: {comp.zip_path}")

    await db.delete(comp)
    await db.commit()

    return {"status": "ok", "message": "组件已下架"}
