"""Shared workspace access checks and binding resolution for coding routes and agent tools.

本模块是 workspace 绑定服务的正式归属地:
- 访问控制: _ensure_workspace_access / _decorate_workspace_access / _workspace_permissions
- 绑定解析: resolve_conversation_app_id — 从 Conversation 对象安全读取 coding_app_id

【各调用场景保留原地的原因(附注于此,供下次维护者参考)】

Point A (tools.py _resolve_local_app_id):
  多源优先级链 args→ctx.extra→ctx.input→Conversation.coding_app_id→apaas反查。
  语义是「装回应用」目标 app;含 DB 查询;优先级链太长且与其他点不等价,保留原地。

Point B (read_query.py _load_bound_application):
  候选链 args→params→Conversation.coding_app_id→workspace.project_id,
  语义是读应用上下文时确定哪个 Application;返回 Application 对象+证据字典;保留原地。

Point C (pipeline.py 绑定持久化状态机):
  写入 + 回读;带 DB commit;不是纯解析;保留原地。

Point D (pipeline.py _create_workspace_now):
  `project_id or _param_app_id_int or conv.coding_app_id`
  workspace 创建时的 project_id;强耦合局部变量;保留原地。

Point E (routes/coding.py 批量自愈回填):
  批量 DB 查 Conversation.coding_app_id 补 workspace.project_id;批量操作语义;保留原地。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coding.workspace import WorkspaceManager
from app.deps import AuthContext
from app.models import Application
from app.project_access import require_project_access


workspace_mgr = WorkspaceManager()


def resolve_conversation_app_id(conv: Any) -> int | None:
    """从 Conversation-like 对象安全读取 coding_app_id。

    这是绑定解析的最小共享原语:统一处理各调用点中散落的
    `_coerce_int(getattr(conv, "coding_app_id", None))` / `_safe_int(...)` 变体。

    规则(与被收口的旧 `_coerce_int`/`_safe_int(getattr(...))` 严格等价):
    - conv=None 或没有 coding_app_id 属性 → None
    - coding_app_id=None 或 "" → None
    - 可转 int → int(原样,含 0/负数)
    - 其他无法转 int → None

    注意:本函数是纯函数(无 I/O、无副作用),调用方负责 DB 查询。
    TODO(单独任务): coding_app_id=0 逻辑上等同未绑定(Application.id 从 1 起),
    可考虑统一降级为 None;但那是行为变化,不在本次纯 refactor 范围,故此处保持
    与旧实现逐字等价(返回 0)。
    """
    if conv is None:
        return None
    value = getattr(conv, "coding_app_id", None)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _workspace_permissions(access_role: str) -> dict[str, bool]:
    return {
        "edit": True,
        "delete": True,
        "publish": True,
        "upload_to_platform": True,
    }


def _decorate_workspace_access(meta: dict[str, Any], access_role: str) -> dict[str, Any]:
    return {
        **meta,
        "access_role": access_role,
        "permissions": _workspace_permissions(access_role),
    }


async def _ensure_workspace_access(
    ws_id: str,
    ctx: AuthContext,
    db: AsyncSession,
    *,
    minimum_project_role: str = "member",
) -> dict[str, Any]:
    try:
        meta = workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")

    project_id = meta.get("project_id")
    if project_id:
        # project_id 字段被复用为「所属应用」(Application.id)。应用绑定不是协作项目,
        # 不能拿它查 Project 表(会 404 把工作区打不开)。归属=应用属本租户:
        # 创建者按 owner, 同租户其他成员按 member(admin 级操作仍只限创建者)。
        app_row = await db.execute(
            select(Application.id).where(
                Application.id == int(project_id),
                Application.tenant_id == ctx.tenant_id,
            )
        )
        if app_row.scalar_one_or_none() is not None:
            return _decorate_workspace_access(meta, "tenant")
        access = await require_project_access(
            db,
            project_id=int(project_id),
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role=minimum_project_role,
        )
        return _decorate_workspace_access(meta, access.role)

    meta_tenant_id = meta.get("tenant_id")
    if meta_tenant_id is not None and int(meta_tenant_id) != int(ctx.tenant_id):
        raise HTTPException(status_code=404, detail="工作区不存在")
    if meta_tenant_id is None and meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=404, detail="工作区不存在")

    return _decorate_workspace_access(meta, "tenant")
