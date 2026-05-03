"""Vibe Coding 沙箱管理 — 列举 / 停止 / 删除运行中的 sandbox 容器。

权限分层（基于 ctx.tenant_role + user.is_platform_admin）：
- platform_admin：看所有 tenant 所有 sandbox
- tenant_admin：看本 tenant 所有用户的 sandbox
- 普通用户（developer/viewer/member）：只看自己 own 的 sandbox

数据来源：
- workspace meta（host 文件 .online-coding.json）有 user_id + tenant_id，按它过滤
- docker_runtime 给每个 workspace 查 container 状态 + 端口映射
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import User
from app.routes.online_coding import (
    ONLINE_CODING_ROOT,
    _find_workspace_dir,
    _iter_workspace_meta_dirs,
    _meta_path,
)
from app.vibe_coding.docker_runtime import get_runtime as get_docker_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/online-coding/sandboxes", tags=["vibe-coding-sandboxes"])


class SandboxInfo(BaseModel):
    workspace_id: str
    title: str  # workspace.task 或 repo 名
    user_id: int
    tenant_id: int
    owner_username: Optional[str] = None
    container_status: Optional[str] = None  # running / exited / created / paused / null（未起容器）
    ports: dict[int, int] = {}  # {container_port: host_port}
    listening_ports: list[int] = []  # 容器内真正在监听的端口
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SandboxListResponse(BaseModel):
    sandboxes: list[SandboxInfo]
    scope: str  # "user" / "tenant" / "platform" 表示当前请求权限
    total: int


def _scan_workspaces() -> list[dict]:
    """扫所有 workspace meta（不过滤），递归含 tenant 子目录。"""
    if not ONLINE_CODING_ROOT.exists():
        return []
    items: list[dict] = []
    for ws_dir in _iter_workspace_meta_dirs():
        try:
            meta = json.loads(_meta_path(ws_dir).read_text(encoding="utf-8"))
            items.append(meta)
        except Exception:
            continue
    return items


def _resolve_scope(ctx: AuthContext) -> str:
    if ctx.tenant_role == "platform_admin" or ctx.user.is_platform_admin:
        return "platform"
    if ctx.tenant_role == "tenant_admin":
        return "tenant"
    return "user"


def _filter_by_scope(metas: list[dict], ctx: AuthContext) -> list[dict]:
    scope = _resolve_scope(ctx)
    if scope == "platform":
        return metas
    if scope == "tenant":
        return [m for m in metas if m.get("tenant_id") == ctx.tenant_id]
    return [m for m in metas if m.get("user_id") == ctx.user.id]


def _workspace_title(meta: dict) -> str:
    repo_url = (meta.get("repo_url") or "").strip().replace("/", " ").rstrip(" ")
    if repo_url:
        last = (meta.get("repo_url") or "").rstrip("/").split("/")[-1]
        if last.endswith(".git"):
            last = last[:-4]
        if last:
            return last
    task = (meta.get("task") or "").strip()
    if task:
        return task[:60]
    return meta.get("id", "(无标题)")


@router.get("", response_model=SandboxListResponse)
async def list_sandboxes(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前用户视野内的 sandbox。"""
    metas = _scan_workspaces()
    scope = _resolve_scope(ctx)
    metas = _filter_by_scope(metas, ctx)

    # 拉一次所有 owner username（避免 N+1）
    user_ids = list({m.get("user_id") for m in metas if m.get("user_id")})
    name_map: dict[int, str] = {}
    if user_ids:
        res = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        name_map = dict(res.all())

    rt = get_docker_runtime()
    docker_avail = await rt.is_available()

    sandboxes: list[SandboxInfo] = []
    for meta in metas:
        ws_id = meta.get("id")
        if not ws_id:
            continue
        info = SandboxInfo(
            workspace_id=ws_id,
            title=_workspace_title(meta),
            user_id=meta.get("user_id") or 0,
            tenant_id=meta.get("tenant_id") or 0,
            owner_username=name_map.get(meta.get("user_id")),
            created_at=meta.get("created_at"),
            updated_at=meta.get("updated_at"),
        )
        if docker_avail:
            try:
                status = await rt.container_status(ws_id)
                info.container_status = status
                if status == "running":
                    mapped = await rt.all_host_ports(ws_id)
                    listening = await rt.listening_ports(ws_id)
                    info.ports = {cp: hp for cp, hp in mapped.items() if cp in listening}
                    info.listening_ports = sorted(listening)
            except Exception as e:
                logger.warning("查 sandbox %s 状态失败: %s", ws_id, e)
        sandboxes.append(info)

    # 排序：running 在前 + 最近更新优先
    sandboxes.sort(
        key=lambda s: (
            0 if s.container_status == "running" else 1,
            -(int((s.updated_at or "").replace("-", "").replace(":", "").replace("T", "").replace("Z", "")[:14] or "0")),
        )
    )

    return SandboxListResponse(sandboxes=sandboxes, scope=scope, total=len(sandboxes))


def _check_sandbox_access(ws_id: str, ctx: AuthContext) -> dict:
    """权限检查 — 返回 meta 或抛 403/404。"""
    _, meta = _find_workspace_dir(ws_id)  # 不存在自带 raise 404
    scope = _resolve_scope(ctx)
    if scope == "platform":
        return meta
    if scope == "tenant" and meta.get("tenant_id") == ctx.tenant_id:
        return meta
    if meta.get("user_id") == ctx.user.id:
        return meta
    raise HTTPException(status_code=403, detail="无权操作该 sandbox")


@router.post("/{workspace_id}/start")
async def start_sandbox(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """启动 sandbox 容器（不存在则新建，exited 则 start 复用）。

    增强：启动后自动恢复上次记录的 background dev 命令（来自 meta.bg_commands），
    让"停了又启"无需用户手动让 agent 再跑一次 npm run dev。
    """
    _check_sandbox_access(workspace_id, ctx)
    rt = get_docker_runtime()
    if not await rt.is_available():
        raise HTTPException(status_code=503, detail="docker runtime 不可用")
    ws_dir, meta = _find_workspace_dir(workspace_id)
    repo_dir = ws_dir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    try:
        await rt.ensure_container(workspace_id, repo_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"启动失败: {exc}")

    # 自动恢复上次的 background 命令（dev server 等）
    restored: list[str] = []
    bg_commands = meta.get("bg_commands") or []
    for entry in bg_commands:
        cmd = entry.get("command")
        if not cmd:
            continue
        # 用新的 log 路径避免覆盖历史
        import time as _t
        log_rel = f".vibe-logs/dev-{int(_t.time())}.log"
        try:
            await rt.exec_background(workspace_id, cmd, log_path=log_rel)
            restored.append(cmd)
        except Exception as e:
            logger.warning("恢复 bg 命令失败 (ws=%s, cmd=%s): %s", workspace_id, cmd, e)
    return {
        "ok": True,
        "workspace_id": workspace_id,
        "status": "running",
        "restored_commands": restored,
    }


@router.post("/{workspace_id}/stop")
async def stop_sandbox(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """停止 sandbox 容器（保留容器壳，下次启动复用 node_modules）。"""
    _check_sandbox_access(workspace_id, ctx)
    rt = get_docker_runtime()
    if not await rt.is_available():
        raise HTTPException(status_code=503, detail="docker runtime 不可用")
    ok = await rt.stop(workspace_id)
    if not ok:
        raise HTTPException(status_code=500, detail="停止失败，请查看后端日志")
    return {"ok": True, "workspace_id": workspace_id, "status": "stopped"}


@router.delete("/{workspace_id}")
async def remove_sandbox(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """彻底删除 sandbox 容器（force=True；清理 node_modules 等容器层数据）。
    注意：workspace 文件本身（用户代码）不删，只删容器；下次再起会重建容器但 npm 重装。
    """
    _check_sandbox_access(workspace_id, ctx)
    rt = get_docker_runtime()
    if not await rt.is_available():
        raise HTTPException(status_code=503, detail="docker runtime 不可用")
    ok = await rt.remove(workspace_id, force=True)
    if not ok:
        raise HTTPException(status_code=500, detail="删除失败，请查看后端日志")
    return {"ok": True, "workspace_id": workspace_id, "status": "removed"}
