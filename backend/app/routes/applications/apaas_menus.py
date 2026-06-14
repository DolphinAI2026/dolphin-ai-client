from __future__ import annotations
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Application
from app.deps import get_auth_context, AuthContext
from app.permissions import Action
from app.apaas_client import APaaSClient

from .crud import (
    _require_application_permission,
    _resolve_apaas_call_context,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# ────────────────────── ChatPage 原生 AppMenuSidebar 用 ──────────────────────
# 2026-05-25: 不再走 ConfigChat agent (MCP loop), 直接给前端 sidebar 拉真实菜单.
# 走 platform list_apaas_app_menus, 返结构含 menu_id / menu_name / menu_type /
# form_id / icon / 父子嵌套 (isGroup + children).
# 前端 AppMenuSidebar.vue 渲染后点菜单 → 切 platform-proxy entry iframe 的 src
# 带上 menu_id/form_id/menu_type → 后端 _build_menu_redirect_path 算出对应表单
# 编辑器 URL.

@router.get("/{app_id}/apaas-menus")
async def get_application_apaas_menus(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """拉应用在 aPaaS 平台上的真实菜单列表 — ChatPage 原生 sidebar 用.

    返回:
      {
        ok: true,
        env_id: 11,
        apaas_app_id: "846351551214649344",
        menus: [{
          menu_id, menu_name, menu_type, form_id, form_code, icon, depth,
          is_group, parent_menu_id, children?: [...]  # 嵌套
        }, ...]
      }
    """
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.VIEW)

    if not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用尚未部署到平台"}

    # 2026-05-25: 直接调 client.query_menus (manageAppMenu) 拿管理视图 — 含 GROUP
    # 跟 process workflow menus. mcp 的 list_apaas_app_menus 走 allAppMenu (runtime
    # 视图, 过滤了 GROUP) 不适合 sidebar 用.
    # 线上环境绑定来自 backend.env / Secret，不再依赖 applications.platform_env_id
    # 反查 platform_envs。旧 app 里残留的 platform_env_id 只作为诊断信息返回。
    try:
        base_url, tenant_id, token, credential_source = await _resolve_apaas_call_context(db, ctx)
        if not base_url or not tenant_id:
            return {
                "ok": False,
                "error_code": "APAAS_CONTEXT_MISSING",
                "message": "未获取到当前环境地址或当前租户绑定的 aPaaS 租户，无法拉取菜单",
                "env_id": app.platform_env_id,
                "tenant_id": ctx.tenant_id,
                "apaas_app_id": app.apaas_app_id,
            }
        if not token:
            return {
                "ok": False,
                "error_code": "CONFIG_ENV_TOKEN_MISSING",
                "message": "当前登录用户没有可用的 aPaaS token，请重新登录",
                "env_id": app.platform_env_id,
                "apaas_app_id": app.apaas_app_id,
            }
        logger.info(
            "应用 %s 按当前租户拉菜单 base_url=%s tenant_id=%s credential_source=%s stale_platform_env_id=%s",
            app.id, base_url, tenant_id, credential_source, app.platform_env_id,
        )
        client = APaaSClient(base_url=base_url, tenant_id=tenant_id, token=token)
        raw_menus_nested = await client.query_menus(app.apaas_app_id)
        if not raw_menus_nested:
            logger.info(
                "应用 %s manageAppMenu 返回空，fallback allAppMenu app_id=%s",
                app.id, app.apaas_app_id,
            )
            fallback = await client.query_all_app_menus(app.apaas_app_id)
            if isinstance(fallback, dict):
                raw_menus_nested = fallback.get("menus") or fallback.get("data") or fallback.get("items") or []
            elif isinstance(fallback, list):
                raw_menus_nested = fallback
        if not raw_menus_nested:
            logger.info(
                "应用 %s allAppMenu 仍为空，fallback queryAllFormMenu app_id=%s",
                app.id, app.apaas_app_id,
            )
            raw_menus_nested = await client.list_form_menus_for_event(app.apaas_app_id)
    except Exception as exc:
        return {
            "ok": False, "error_code": "APAAS_FETCH_FAILED",
            "message": f"拉取菜单失败: {exc}",
            "env_id": app.platform_env_id,
            "tenant_id": ctx.tenant_id,
            "apaas_tenant_id": tenant_id,
            "apaas_app_id": app.apaas_app_id,
        }

    # 平台返嵌套 (submenus 字段), 打平后给后续 normalize + tree-build 复用.
    def _flat_with_parent(nodes: list, parent_id: str = ""):
        out: list = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            # 注 platform 嵌套返结构里 submenus 已经是 dict 数组
            n_with_parent = {**n, "parentId": parent_id or n.get("parentId")}
            out.append(n_with_parent)
            kids = n.get("submenus") or n.get("children") or []
            cur_id = str(n.get("id") or n.get("menuId") or "")
            if kids and cur_id:
                out.extend(_flat_with_parent(kids, cur_id))
        return out

    menus_raw = _flat_with_parent(raw_menus_nested or [])

    # 兜底: 若空, 把 raw 当作单 list (老 API 返 array 不带 submenus 的情况)
    if not menus_raw and isinstance(raw_menus_nested, dict):
        menus_raw = raw_menus_nested.get("menus") or raw_menus_nested.get("data") or []

    def _normalize_menu(m: dict) -> dict:
        # 平台字段名可能是 camelCase / snake_case 混合, 都接住
        mtype = m.get("menu_type") or m.get("menuType") or ""
        return {
            "menu_id": str(m.get("menu_id") or m.get("menuId") or m.get("id") or ""),
            "menu_name": m.get("menu_name") or m.get("menuName") or m.get("name") or "",
            "menu_type": mtype,
            "menu_display": m.get("menu_display") or m.get("menuDisplay") or "",
            "form_id": str(m.get("form_id") or m.get("formId") or "") or None,
            "form_code": m.get("form_code") or m.get("formCode") or None,
            "icon": m.get("icon") or m.get("menu_icon") or m.get("menuIcon") or "",
            "depth": m.get("depth") or m.get("level") or 0,
            "path": m.get("path") or "",
            "parent_menu_id": str(m.get("parent_menu_id") or m.get("parentMenuId") or m.get("parentId") or m.get("pid") or "") or None,
            # menuType=GROUP 自动判为 group; 也兼容 is_group / isGroup 显式标记
            "is_group": bool(m.get("is_group") or m.get("isGroup")
                              or str(mtype).upper() == "GROUP"),
            "dashboard_id": str(m.get("dashboard_id") or m.get("dashboardId") or "") or None,
            "link_url": m.get("link_url") or m.get("linkUrl") or None,
            "sort_order": m.get("sort_order") or m.get("sortOrder")
                          or m.get("menuOrder") or 0,
        }

    # 2026-05-25: 过滤掉平台自动注入的系统菜单 (流程待办 / 我发起的 / 流程授权 etc)
    # 这些是 runtime 用户看的, 不是 AI Builder 配置目标. 用户/AI 不需要在 sidebar 看到.
    # 2026-06-05: 加 TASK_CENTER（异步任务管理）—— 平台自动注入的系统菜单, 不是配置目标。
    _SYSTEM_AUTO_MENU_TYPES = {
        "TODO", "TO_CHECK", "MY_SUBMIT", "MY_PARTICIPATE",
        "TODO_MANAGE", "PROC_AUTH", "PROC_FORWARD", "TASK_CENTER",
    }
    flat_all = [_normalize_menu(m) for m in menus_raw if isinstance(m, dict)]
    # 哪些分组在原始数据里本来有子菜单 —— 用于下面只剔「被系统过滤掏空」的分组,
    # 不误伤用户刚建、本来就空的分组。
    _parents_with_children = {m["parent_menu_id"] for m in flat_all if m.get("parent_menu_id")}
    flat = [m for m in flat_all if m["menu_type"].upper() not in _SYSTEM_AUTO_MENU_TYPES]

    # 嵌套 — 按 parent_menu_id 构 tree (无 parent 的放根)
    by_id: dict[str, dict] = {m["menu_id"]: {**m, "children": []} for m in flat if m["menu_id"]}
    roots: list[dict] = []
    for m in by_id.values():
        pid = m.get("parent_menu_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(m)
        else:
            roots.append(m)
    # 同层按 sort_order 排
    def _sort(items: list[dict]) -> None:
        items.sort(key=lambda x: (int(x.get("sort_order") or 0), x.get("menu_name") or ""))
        for it in items:
            if it.get("children"):
                _sort(it["children"])
    _sort(roots)

    # 剔掉「被系统菜单过滤掏空」的分组(如只装了 异步任务管理 的「系统管理」组)。
    # 只剔本来有子菜单、过滤后变空的分组; 用户新建的本来就空的分组保留(不在 _parents_with_children)。
    def _prune_emptied_groups(items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for it in items:
            it["children"] = _prune_emptied_groups(it.get("children") or [])
            if it.get("is_group") and not it["children"] and it["menu_id"] in _parents_with_children:
                continue
            out.append(it)
        return out
    roots = _prune_emptied_groups(roots)

    return {
        "ok": True,
        "env_id": app.platform_env_id,
        "tenant_id": ctx.tenant_id,
        "apaas_tenant_id": tenant_id,
        "apaas_app_id": app.apaas_app_id,
        "menus": roots,
        "flat_count": len(flat),
    }


# 2026-05-25 续: ChatPage AppMenuSidebar 用户主动操作 menus 的 endpoint.
# Pinia store 调 backend, backend 复用 mcp_server 的 _call_apaas_platform_tool 走平台.

class _CreateMenuGroupReq(BaseModel):
    group_name: str
    menu_order: int = 0
    parent_id: str = ""


@router.post("/{app_id}/apaas-menu-group")
async def create_apaas_menu_group(
    app_id: int,
    payload: _CreateMenuGroupReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """sidebar 新建菜单分组 — 创建 menuType=GROUP 的菜单."""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.EDIT)

    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未部署到平台"}

    name = payload.group_name.strip()
    if not name:
        return {"ok": False, "error_code": "INVALID_NAME", "message": "分组名必填"}

    # WRITE 类工具不在 _call_apaas_platform_tool 的 executor 字典里, 直接调 mcp tool fn
    from app.mcp_server import create_apaas_menu_group as _mcp_create_group  # type: ignore
    return await _mcp_create_group(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        group_name=name,
        menu_order=payload.menu_order,
        parent_id=payload.parent_id,
    )


class _SetMenuParentReq(BaseModel):
    menu_id: str
    parent_id: str = ""  # "" = 移到根
    menu_order: int = 0


@router.post("/{app_id}/apaas-menu-set-parent")
async def set_apaas_menu_parent(
    app_id: int,
    payload: _SetMenuParentReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """sidebar 把菜单挂到分组下 / 移出回根级."""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.EDIT)

    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未部署到平台"}
    if not payload.menu_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "menu_id 必填"}

    from app.mcp_server import set_apaas_menu_parent as _mcp_set_parent  # type: ignore
    return await _mcp_set_parent(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        menu_id=payload.menu_id.strip(),
        parent_id=payload.parent_id,
        menu_order=payload.menu_order,
    )


class _DeleteMenuReq(BaseModel):
    menu_id: str
    menu_name: str = ""


@router.post("/{app_id}/apaas-menu-delete")
async def delete_apaas_menu(
    app_id: int,
    payload: _DeleteMenuReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """sidebar 删除菜单 — 普通菜单 / 表单菜单 / GROUP 分组 都用这个.

    平台 /xdap-app/menu/delete/menu 通用. 删表单菜单会联动删表单本身.
    删 GROUP 时前端应保证里面没子菜单 (否则平台行为是 cascade 还是 reject 没探过,
    前端 UI 拦一道安全).
    """
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.EDIT)

    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用未部署到平台"}
    if not payload.menu_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "menu_id 必填"}

    from app.mcp_server import delete_apaas_app_menu as _mcp_delete_menu  # type: ignore
    return await _mcp_delete_menu(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        menu_id=payload.menu_id.strip(),
        menu_name=payload.menu_name,
    )


# ───── 应用基本信息编辑（PR3, SPEC v2 §2 顶部 CTA）─────


class _UpdateApaasAppInfoReq(BaseModel):
    # 2026-05-26 (PR3 reviewer P1 #3): pydantic max_length 统一前后端校验.
    # app_name 上限跟前端 el-input maxlength=64 + saveAppInfo guard 对齐.
    # description 200 跟前端 textarea maxlength=200 对齐.
    # icon_svg 50KB 防超大 SVG 撑爆 payload (实际 svg 通常 <5KB).
    app_name: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=200)
    icon_svg: str = Field(default="", max_length=50_000)


@router.post("/{app_id}/update-apaas-info")
async def update_apaas_app_info_route(
    app_id: int,
    payload: _UpdateApaasAppInfoReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改应用基本信息 (名称 / 描述 / 图标), 内部包装 `update_apaas_app_info` MCP 工具.

    ChatPage 顶部 breadcrumb 点应用名 → 弹小窗 → 保存调本接口. 跟 apaas-menu-delete
    一样的模式: 鉴权 + 应用存在性检查 + 透传到 mcp_server tool.

    保存成功后前端会刷新 builderAppDisplayName.
    """
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await _require_application_permission(ctx, db, app, Action.EDIT)

    if not app.platform_env_id or not app.apaas_app_id:
        return {
            "ok": False, "error_code": "APP_NOT_DEPLOYED",
            "message": "应用未部署到平台，请先部署后再编辑应用信息",
        }

    has_any = any(v.strip() for v in (payload.app_name, payload.description, payload.icon_svg))
    if not has_any:
        return {
            "ok": False, "error_code": "INVALID_PARAMS",
            "message": "app_name / description / icon_svg 至少传一个非空字段",
        }

    from app.mcp_server import update_apaas_app_info as _mcp_update_app_info  # type: ignore
    mcp_result = await _mcp_update_app_info(
        env_id=app.platform_env_id,
        apaas_app_id=app.apaas_app_id,
        app_name=payload.app_name,
        description=payload.description,
        icon_svg=payload.icon_svg,
    )

    # 平台改名成功 → 同步回 backend Application.app_name + description (UI 即时刷新源头)
    # 2026-05-26 (PR3 reviewer P1 #2): commit 失败时不再 raise 500 — 平台已改好但本地
    # DB 没改, 应该告知客户端 partial_success 让 UI 提示\"已存到平台, 本地缓存稍后同步\"
    # 而不是误以为整体失败.
    if mcp_result.get("ok"):
        touched = False
        if payload.app_name.strip():
            app.app_name = payload.app_name.strip()
            touched = True
        if payload.description.strip():
            app.description = payload.description.strip()
            touched = True
        if payload.icon_svg.strip():
            app.icon_svg = payload.icon_svg.strip()
            touched = True
        if touched:
            try:
                await db.commit()
                await db.refresh(app)
                mcp_result["app_id"] = app.id
                mcp_result["synced_local_name"] = app.app_name
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "update_apaas_app_info_route DB commit 失败 (平台已改) app_id=%s: %r",
                    app_id, exc,
                )
                try:
                    await db.rollback()
                except Exception:
                    pass
                # 平台已改, 本地未同步 — UI 应显示"平台已更新, 下次刷新页面看到"提示
                mcp_result["partial_success"] = True
                mcp_result["db_sync_failed"] = True
                mcp_result["db_sync_error"] = str(exc)[:200]

    return mcp_result
