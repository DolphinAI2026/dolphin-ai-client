"""SPEC 版本管理 endpoint — Y 阶段 SPEC 版本快照 + markdown 缓存系统.

URL prefix:
    GET  /applications/{app_id}/spec/versions
    GET  /applications/{app_id}/spec/versions/{version_id}
    GET  /applications/{app_id}/spec/markdown
    GET  /applications/{app_id}/spec/export.md

定位:
    SPEC 设计 tab 现是混合模式 — 显示层每次实时拉 apaas (慢 + 无快照), 草稿层
    spec_sections 有 base/draft version 计数. 本模块给系统加正经版本管理:

    GET versions          — 列已 apply 版本 (历史 N 条)
    GET versions/{id}     — 读某版本完整 snapshot
    GET markdown          — 当前 SPEC.md 缓存 (cache miss 时实时生成 + 落库)
    GET export.md         — 当前 SPEC.md attachment 下载 (跟 GET markdown 同源, 包装成 text/markdown)

跟 spec_apply 关系:
    apply_spec 成功跑完 → 在 spec_apply.py 内部建一行 SpecAppliedVersion
    + 顺便 invalidate SpecDocument cache. 本模块只 read.

缓存策略 (GET markdown):
    1. SELECT FROM spec_documents WHERE app_id=X
    2. 调 generate_spec_markdown 拿当前 (markdown, hash)
    3. 没行 / hash 不匹配 → UPSERT
    4. 匹配 → 直接返 cached row (跳生成, 但 hash 一致性已由步骤2 算出确认)

    注: 当前 hash 每次都算 (调用一次 generate_spec_markdown), 没短路.
    P5 优化: 加 light-weight hash 函数只拉 menu/role count 不渲染 markdown.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application
from app.models.spec_applied_version import SpecAppliedVersion
from app.models.spec_document import SpecDocument
from app.permissions import Action, check_resource_permission
from app.services.spec_markdown_generator import generate_spec_markdown

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
async def _load_app_for_view(
    app_id: int,
    ctx: AuthContext,
    db: AsyncSession,
) -> Application:
    """加载应用 + VIEW 检权. 不存在 → 404."""
    r = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)
    return app


# ---------------------------------------------------------------------------
# Endpoint 1 — GET /spec/versions  (list 已 apply 版本)
# ---------------------------------------------------------------------------
@router.get("/{app_id}/spec/versions")
async def list_spec_versions(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """列已 apply 版本历史 (按 applied_at desc).

    Returns:
      {
        ok: true,
        app_id: 13,
        versions: [
          {
            id, version_label, applied_at, applied_by_user_id,
            applied_steps, failed_steps, total_steps, is_active,
          }
        ]
      }
    """
    app = await _load_app_for_view(app_id, ctx, db)

    q = await db.execute(
        select(SpecAppliedVersion)
        .where(SpecAppliedVersion.application_id == app.id)
        .order_by(SpecAppliedVersion.applied_at.desc())
    )
    rows = list(q.scalars().all())

    return {
        "ok": True,
        "app_id": app.id,
        "versions": [
            {
                "id": r.id,
                "version_label": r.version_label,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "applied_by_user_id": r.applied_by_user_id,
                "total_steps": r.total_steps,
                "applied_steps": r.applied_steps,
                "failed_steps": r.failed_steps,
                "is_active": bool(r.is_active),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# Endpoint 2 — GET /spec/versions/{version_id}  (读完整 snapshot)
# ---------------------------------------------------------------------------
@router.get("/{app_id}/spec/versions/{version_id}")
async def get_spec_version(
    app_id: int,
    version_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """读某版本完整 snapshot (sections_snapshot + markdown_snapshot).

    Returns:
      {
        ok, version: {...meta..., sections_snapshot, markdown_snapshot, apply_results}
      }
    """
    app = await _load_app_for_view(app_id, ctx, db)

    q = await db.execute(
        select(SpecAppliedVersion).where(
            SpecAppliedVersion.id == version_id,
            SpecAppliedVersion.application_id == app.id,
        )
    )
    row = q.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="SPEC 版本不存在")

    return {
        "ok": True,
        "version": {
            "id": row.id,
            "application_id": row.application_id,
            "version_label": row.version_label,
            "applied_at": row.applied_at.isoformat() if row.applied_at else None,
            "applied_by_user_id": row.applied_by_user_id,
            "total_steps": row.total_steps,
            "applied_steps": row.applied_steps,
            "failed_steps": row.failed_steps,
            "is_active": bool(row.is_active),
            "sections_snapshot": row.sections_snapshot or {},
            "markdown_snapshot": row.markdown_snapshot or "",
            "apply_results": row.apply_results or [],
        },
    }


# ---------------------------------------------------------------------------
# Endpoint 3 — GET /spec/markdown  (当前 SPEC.md, cache + 自动生成)
# ---------------------------------------------------------------------------
@router.get("/{app_id}/spec/markdown")
async def get_spec_markdown(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """读应用当前 SPEC.md.

    缓存逻辑:
      1. 调 generate_spec_markdown 拿 (markdown, current_hash)
      2. SELECT FROM spec_documents
      3. 不匹配 → UPSERT
      4. 匹配 → 复用 cached row 的 markdown / last_generated_at

    Returns:
      {
        ok: true,
        app_id, app_name, app_code,
        markdown: "...",
        sections_hash: "...",
        last_generated_at: ISO,
        cache_hit: bool,
      }
    """
    app = await _load_app_for_view(app_id, ctx, db)

    # 1. 实时拉 + 算 hash
    try:
        markdown, current_hash = await generate_spec_markdown(db, app.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_spec_markdown crashed app_id=%s", app.id)
        raise HTTPException(
            status_code=500, detail=f"生成 SPEC markdown 失败: {exc}",
        ) from exc

    # 2. 查 cache
    q = await db.execute(
        select(SpecDocument).where(SpecDocument.application_id == app.id)
    )
    cached = q.scalar_one_or_none()

    from datetime import datetime as _dt

    cache_hit = False
    if cached and cached.sections_hash == current_hash:
        cache_hit = True
        # markdown 可能跟存的微差 (timestamp 头变), 用 cached.markdown_content 保稳定
        served_markdown = cached.markdown_content
        last_generated_at = cached.last_generated_at
    else:
        # UPSERT
        if cached:
            cached.markdown_content = markdown
            cached.sections_hash = current_hash
            cached.last_generated_at = _dt.utcnow()
            last_generated_at = cached.last_generated_at
        else:
            new_row = SpecDocument(
                application_id=app.id,
                markdown_content=markdown,
                sections_hash=current_hash,
                last_generated_at=_dt.utcnow(),
            )
            db.add(new_row)
            last_generated_at = new_row.last_generated_at
        await db.commit()
        served_markdown = markdown

    return {
        "ok": True,
        "app_id": app.id,
        "app_name": app.app_name or "",
        "app_code": app.app_code or "",
        "markdown": served_markdown,
        "sections_hash": current_hash,
        "last_generated_at": last_generated_at.isoformat() if last_generated_at else None,
        "cache_hit": cache_hit,
    }


# ---------------------------------------------------------------------------
# Endpoint 4 — GET /spec/export.md  (attachment 下载)
# ---------------------------------------------------------------------------
@router.get("/{app_id}/spec/export.md")
async def export_spec_md(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """导出 SPEC.md attachment (text/markdown).

    复用 get_spec_markdown 拿 markdown, 包装成 text/markdown + Content-Disposition.
    """
    app = await _load_app_for_view(app_id, ctx, db)

    try:
        markdown, current_hash = await generate_spec_markdown(db, app.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("export_spec_md: generate failed app_id=%s", app.id)
        raise HTTPException(
            status_code=500, detail=f"生成 SPEC markdown 失败: {exc}",
        ) from exc

    # 也 UPSERT 一下 cache (跟 get_spec_markdown 同步)
    q = await db.execute(
        select(SpecDocument).where(SpecDocument.application_id == app.id)
    )
    cached = q.scalar_one_or_none()
    from datetime import datetime as _dt
    if cached and cached.sections_hash != current_hash:
        cached.markdown_content = markdown
        cached.sections_hash = current_hash
        cached.last_generated_at = _dt.utcnow()
        await db.commit()
    elif not cached:
        new_row = SpecDocument(
            application_id=app.id,
            markdown_content=markdown,
            sections_hash=current_hash,
            last_generated_at=_dt.utcnow(),
        )
        db.add(new_row)
        await db.commit()

    # 文件名: app_code.spec.md (没 app_code 用 app-{id})
    safe_code = (app.app_code or f"app-{app.id}").replace("/", "_")
    filename = f"{safe_code}.spec.md"

    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Sections-Hash": current_hash,
        },
    )
