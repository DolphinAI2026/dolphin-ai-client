"""孤儿 workspace 迁移（幂等）。

背景：Conversation(agent_type='coding') 是 AI Coding 唯一主单位，1:1 拥有
workspace。历史上存在磁盘有目录、但 Conversation 表里没有任何行的
workspace_id 指向它的情况（"孤儿 workspace"）。

本模块在 main.py lifespan startup 时运行一次，把所有孤儿挂上一个 owner 会话：
- 有 user_id + tenant_id → 补建 Conversation(agent_type='coding', workspace_id=<id>)
- 缺 user_id 或 tenant_id → 打 archived=true 标记到 .workspace.json，不删目录
- 已有会话指向的 → 跳过（幂等）

幂等保证：检查"此 workspace_id 已有 Conversation 行"后才建；多次调用结果相同。
绝不删除任何 workspace 目录。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coding.workspace import WORKSPACE_SEARCH_ROOTS
from app.models import Conversation

logger = logging.getLogger(__name__)


def _iter_workspace_dirs(roots: Sequence[Path]):
    """扫所有 workspace 根目录，yield 有 .workspace.json 的子目录（去重）。"""
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.iterdir():
            if not candidate.is_dir():
                continue
            if candidate.name.startswith("."):
                continue
            if not (candidate / ".workspace.json").exists():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield candidate


def _read_meta(ws_path: Path) -> dict:
    try:
        return json.loads((ws_path / ".workspace.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(ws_path: Path, meta: dict) -> None:
    (ws_path / ".workspace.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def migrate_orphan_workspaces(
    db: AsyncSession,
    *,
    roots: Sequence[Path] | None = None,
) -> dict:
    """扫描所有 workspace，把孤儿补建 Conversation 或打 archived 标记。

    返回 {"migrated": int, "skipped": int, "archived": int}。
    幂等：已有会话指向的直接 skipped；相同调用结果不变。
    """
    if roots is None:
        roots = WORKSPACE_SEARCH_ROOTS

    # 一次性加载所有 coding 会话的 workspace_id，避免 N+1
    rows = (await db.execute(
        select(Conversation.workspace_id).where(
            Conversation.agent_type == "coding",
            Conversation.workspace_id.isnot(None),
        )
    )).scalars().all()
    owned_ws_ids: set[str] = {str(ws_id) for ws_id in rows if ws_id}

    migrated = 0
    skipped = 0
    archived = 0

    for ws_path in _iter_workspace_dirs(roots):
        meta = _read_meta(ws_path)
        ws_id = str(meta.get("id") or "").strip()
        if not ws_id:
            # 没有 id 字段，无法关联，归档
            if not meta.get("archived"):
                meta["archived"] = True
                _write_meta(ws_path, meta)
                logger.warning(
                    "migrate_orphan_workspaces: archived (no id) %s", ws_path
                )
            archived += 1
            continue

        if ws_id in owned_ws_ids:
            skipped += 1
            logger.debug(
                "migrate_orphan_workspaces: skip (owned) ws_id=%s path=%s",
                ws_id, ws_path,
            )
            continue

        # 孤儿：先做二次确认（防并发重跑时 owned_ws_ids 过时）
        existing = (await db.execute(
            select(Conversation).where(
                Conversation.agent_type == "coding",
                Conversation.workspace_id == ws_id,
            )
        )).scalar_one_or_none()
        if existing is not None:
            # 幂等：另一次调用已经补建了，更新 in-memory set 防重复计数
            owned_ws_ids.add(ws_id)
            skipped += 1
            continue

        # 检查能否定位 owner
        user_id = meta.get("user_id")
        tenant_id = meta.get("tenant_id")

        if not user_id or not tenant_id:
            # 无法定位 owner → 归档（打标记，不删目录）
            if not meta.get("archived"):
                meta["archived"] = True
                _write_meta(ws_path, meta)
                logger.warning(
                    "migrate_orphan_workspaces: archived (no owner) ws_id=%s path=%s",
                    ws_id, ws_path,
                )
            archived += 1
            continue

        # 补建 owner 会话
        display_name = (
            meta.get("display_name")
            or meta.get("project_name")
            or ws_id
        )
        title = f"[迁移] {display_name}"
        project_id = meta.get("project_id")  # optional

        new_conv = Conversation(
            user_id=int(user_id),
            tenant_id=int(tenant_id),
            title=title[:200],  # 字段 String(200)
            agent_type="coding",
            workspace_id=ws_id,
            project_id=project_id,
        )
        db.add(new_conv)
        await db.commit()
        await db.refresh(new_conv)

        owned_ws_ids.add(ws_id)
        migrated += 1
        logger.info(
            "migrate_orphan_workspaces: migrated ws_id=%s → conv_id=%s "
            "user_id=%s tenant_id=%s",
            ws_id, new_conv.id, user_id, tenant_id,
        )

    logger.info(
        "migrate_orphan_workspaces done: migrated=%d skipped=%d archived=%d",
        migrated, skipped, archived,
    )
    return {"migrated": migrated, "skipped": skipped, "archived": archived}
