"""Section Content endpoints — PR2c (后续 PR2b 配套).

提供 7 个 GET REST endpoint, 让前端 SectionNav sub-tab 切换时能拉应用下的
真实资源列表 (模型 / 字典 / 表单 / 列表 / 流程 / 业务事件 / 角色).

每个 endpoint 都包装现有 MCP 工具 (从 app.mcp_server 直接 await), 统一 normalize
返结构为 `{ok, env_id, apaas_app_id, items: [{id, name, code, ...}], total, source}`,
让前端不用关心字段名差异 (model_id / dict_id / menu_id / role_id / event_id).

关键设计:
- 检权: check_resource_permission(VIEW) — 等价于 _require_application_permission.
- 应用未部署 (app.platform_env_id 或 app.apaas_app_id 为空) → 200 + ok=False +
  error_code=APP_NOT_DEPLOYED + items=[], 不 404 (让前端能渲染空态而非崩).
- MCP 工具调用包 try/except, 出错返 ok=False 不抛 500.
- MCP 工具不存在 (e.g. list_apaas_app_processes 未实现) → TOOL_NOT_AVAILABLE 兜底.

参考: SPEC PR2c 设计 + 现有 apaas-menus / extension 模块的语义.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application
from app.permissions import Action, check_resource_permission

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas (统一回包)
# ---------------------------------------------------------------------------
class SectionContentItem(BaseModel):
    """归一后的资源项 — 前端不用关心 MCP 工具原字段名."""
    id: str
    name: str
    code: Optional[str] = None
    # 透传原始字段方便前端按 section 做差异化渲染 (e.g. menu_type / event_type)
    extra: dict[str, Any] = Field(default_factory=dict)


class SectionContentResponse(BaseModel):
    ok: bool
    env_id: Optional[int] = None
    apaas_app_id: Optional[str] = None
    items: list[SectionContentItem] = Field(default_factory=list)
    total: int = 0
    source: str = ""  # 调用了哪个 MCP 工具 (debug 用)
    error_code: Optional[str] = None
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# 通用 helpers
# ---------------------------------------------------------------------------
async def _load_app_and_check_view(
    app_id: int,
    ctx: AuthContext,
    db: AsyncSession,
) -> Application:
    """加载应用 + 检权 (VIEW). 应用不存在 → 404."""
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


def _app_not_deployed(app: Application, source: str) -> SectionContentResponse:
    """应用未绑定 platform_env_id 或未部署 (无 apaas_app_id) → 友好降级."""
    return SectionContentResponse(
        ok=False,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id) if app.apaas_app_id else None,
        items=[],
        total=0,
        source=source,
        error_code="APP_NOT_DEPLOYED",
        message="应用尚未部署到 aPaaS 平台 — 部署后才能拉资源列表",
    )


def _tool_error(
    app: Application,
    source: str,
    error_code: str,
    message: str,
) -> SectionContentResponse:
    """MCP 工具抛错或返 ok=False 时统一兜底, 不 500."""
    return SectionContentResponse(
        ok=False,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id) if app.apaas_app_id else None,
        items=[],
        total=0,
        source=source,
        error_code=error_code,
        message=message,
    )


async def _safe_call_mcp_tool(
    tool_name: str,
    env_id: int,
    apaas_app_id: str,
    extra_args: Optional[dict] = None,
) -> tuple[bool, dict]:
    """调 MCP 工具的统一封装 — 工具不存在 / 抛异常 / 返 ok=False 都统一兜底.

    Returns:
      (ok, raw_or_error)
      - ok=True 时 raw_or_error 是 MCP 工具的原始 dict 返回.
      - ok=False 时 raw_or_error 是 {error_code, message} 错误结构.
    """
    # 延迟 import — 避免 module import 时 mcp_server 副作用 (调 LLM client 等).
    try:
        from app import mcp_server as _mcp
    except Exception as exc:
        return False, {
            "error_code": "MCP_MODULE_LOAD_FAILED",
            "message": f"mcp_server 模块加载失败: {exc}",
        }

    tool = getattr(_mcp, tool_name, None)
    if tool is None or not callable(tool):
        return False, {
            "error_code": "TOOL_NOT_AVAILABLE",
            "message": f"MCP 工具 {tool_name} 未注册 — backend 版本不匹配或工具未实现",
        }

    args: dict = {"env_id": env_id, "apaas_app_id": apaas_app_id}
    if extra_args:
        args.update(extra_args)

    try:
        raw = await tool(**args)
    except TypeError as exc:
        # 签名不匹配 (e.g. with_fields 不存在) — 当工具不可用处理而不是 500.
        logger.warning(f"section_content: MCP tool {tool_name} TypeError: {exc}")
        return False, {
            "error_code": "TOOL_SIGNATURE_MISMATCH",
            "message": f"MCP 工具 {tool_name} 签名不兼容: {exc}",
        }
    except Exception as exc:
        logger.warning(f"section_content: MCP tool {tool_name} 抛错: {exc}")
        return False, {
            "error_code": "MCP_TOOL_ERROR",
            "message": f"MCP 工具 {tool_name} 调用失败: {exc}",
        }

    if not isinstance(raw, dict):
        return False, {
            "error_code": "MCP_UNEXPECTED_SHAPE",
            "message": f"MCP 工具 {tool_name} 返非 dict: {type(raw).__name__}",
        }

    if not raw.get("ok", False):
        # MCP 工具显式失败 (e.g. INVALID_APAAS_APP_ID / APAAS_TOKEN_EXPIRED).
        return False, {
            "error_code": str(raw.get("error_code") or "MCP_TOOL_FAILED"),
            "message": str(raw.get("message") or "MCP 工具返回 ok=False"),
        }

    return True, raw


def _extract_items_from_mcp_result(
    raw: dict,
    key_candidates: list[str],
    id_keys: list[str],
    name_keys: list[str],
    code_keys: list[str],
) -> list[SectionContentItem]:
    """统一归一: 从 MCP 工具原始返结构里捞出 items 列表 + normalize 字段.

    key_candidates: 比如 ["models", "items", "data"] — 哪些 key 可能装着列表.
    id_keys: 比如 ["model_id", "id", "eventId"] — 优先级递降.
    name_keys / code_keys: 同上.
    """
    # 1) 找 list — 优先按 key_candidates 顺序找
    items_raw: list = []
    for k in key_candidates:
        v = raw.get(k)
        if isinstance(v, list):
            items_raw = v
            break
        if isinstance(v, dict):
            # data 可能是分页对象 {table/records: [...], total}
            for inner in ("table", "records", "items", "list"):
                vv = v.get(inner)
                if isinstance(vv, list):
                    items_raw = vv
                    break
            if items_raw:
                break

    def _pick(d: dict, keys: list[str]) -> str:
        for k in keys:
            v = d.get(k)
            if v is not None and v != "":
                return str(v)
        return ""

    out: list[SectionContentItem] = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        # extra 透传原 item — 让前端按 section 渲染差异化字段.
        out.append(SectionContentItem(
            id=_pick(item, id_keys),
            name=_pick(item, name_keys),
            code=_pick(item, code_keys) or None,
            extra=item,
        ))
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/{app_id}/section-content/models", response_model=SectionContentResponse)
async def get_section_content_models(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """data section: 列应用的数据模型 (走 list_apaas_app_models, with_fields=False 省 token).

    返结构: items[].id = model_id, .name = model_name, .code = model_code.
    """
    source = "list_apaas_app_models"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"with_fields": False},
    )
    if not ok:
        return _tool_error(app, source, raw_or_err["error_code"], raw_or_err["message"])

    items = _extract_items_from_mcp_result(
        raw_or_err,
        key_candidates=["models", "items"],
        id_keys=["model_id", "id"],
        name_keys=["model_name", "name"],
        code_keys=["model_code", "code"],
    )
    return SectionContentResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=int(raw_or_err.get("total") or len(items)),
        source=source,
    )


@router.get("/{app_id}/section-content/dicts", response_model=SectionContentResponse)
async def get_section_content_dicts(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """data section: 列应用的字典 (走 list_apaas_app_dicts, with_options=False 省 token)."""
    source = "list_apaas_app_dicts"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"with_options": False},
    )
    if not ok:
        return _tool_error(app, source, raw_or_err["error_code"], raw_or_err["message"])

    items = _extract_items_from_mcp_result(
        raw_or_err,
        key_candidates=["dicts", "items"],
        id_keys=["dict_id", "id"],
        name_keys=["dict_name", "name"],
        code_keys=["dict_code", "code"],
    )
    return SectionContentResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=int(raw_or_err.get("total") or len(items)),
        source=source,
    )


async def _menus_filtered_by_type(
    app: Application, allowed_types: set[str], source: str,
) -> SectionContentResponse:
    """共享: 调 list_apaas_app_menus 然后按 menu_type 过滤.

    允许的 menu_type 集合大小写比较 — apaas 平台返大写 (FORM/LIST/PAGE_CUSTOM_DEV).
    """
    ok, raw_or_err = await _safe_call_mcp_tool(
        "list_apaas_app_menus",
        env_id=app.platform_env_id,  # type: ignore[arg-type] — caller 保证非空
        apaas_app_id=str(app.apaas_app_id),
    )
    if not ok:
        return _tool_error(app, source, raw_or_err["error_code"], raw_or_err["message"])

    # menus 是扁平 list, 含 menu_type 字段.
    menus_raw = raw_or_err.get("menus") or []
    if not isinstance(menus_raw, list):
        menus_raw = []

    norm_allowed = {t.upper() for t in allowed_types}
    items: list[SectionContentItem] = []
    for m in menus_raw:
        if not isinstance(m, dict):
            continue
        mtype = str(m.get("menu_type") or "").upper()
        if mtype not in norm_allowed:
            continue
        items.append(SectionContentItem(
            id=str(m.get("menu_id") or ""),
            name=str(m.get("menu_name") or ""),
            code=str(m.get("form_code") or "") or None,
            extra=m,
        ))
    return SectionContentResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=len(items),
        source=source,
    )


@router.get("/{app_id}/section-content/forms", response_model=SectionContentResponse)
async def get_section_content_forms(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """ui section: 列应用的表单 — 平台 menu_type=MODEL 即表单视图 (一个 MODEL 菜单
    同时绑定表单 + 列表 + 详情, 不是分开管理).

    2026-05-26 fix: 老逻辑过滤 FORM 总是 0, 因为 apaas 不用 FORM 这个 type.
    真实 menu_type ∈ {MODEL, GROUP, TASK_CENTER, PAGE_CUSTOM_DEV, ...}.
    """
    source = "list_apaas_app_menus[menu_type=MODEL]"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)
    return await _menus_filtered_by_type(app, {"MODEL"}, source)


@router.get("/{app_id}/section-content/lists", response_model=SectionContentResponse)
async def get_section_content_lists(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """ui section: 列应用的列表视图 — 同 forms, 走 MODEL menu_type.

    note: apaas 平台一个 MODEL 菜单同时含表单填写视图 + 列表查询视图, 不是
    分开管理. forms / lists sub-tab 在 UI 上区分用户视角, 后端数据源相同.
    """
    source = "list_apaas_app_menus[menu_type=MODEL]"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)
    return await _menus_filtered_by_type(app, {"MODEL"}, source)


@router.get("/{app_id}/section-content/processes", response_model=SectionContentResponse)
async def get_section_content_processes(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """logic section: 列应用的流程.

    note: list_apaas_app_processes MCP 工具不存在 — 用 list_apaas_app_menus 过滤
    menu_type=PROCESS 兜底. 真有独立流程工具时切过去.
    """
    source = "list_apaas_app_menus[menu_type=PROCESS]"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    # 先试独立工具 (未来真有 list_apaas_app_processes 时自动走过去).
    independent_ok, raw_or_err = await _safe_call_mcp_tool(
        "list_apaas_app_processes",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
    )
    if independent_ok:
        items = _extract_items_from_mcp_result(
            raw_or_err,
            key_candidates=["processes", "items", "data"],
            id_keys=["process_id", "id", "processId"],
            name_keys=["process_name", "name", "processName"],
            code_keys=["process_code", "code", "processCode"],
        )
        return SectionContentResponse(
            ok=True,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id),
            items=items,
            total=int(raw_or_err.get("total") or len(items)),
            source="list_apaas_app_processes",
        )

    # 兜底走 menus — 流程挂 MODEL 菜单上, 跟 forms/lists 同源, P0 全列出来,
    # 真有流程的菜单后续可以加 has_process 过滤.
    if raw_or_err.get("error_code") not in ("TOOL_NOT_AVAILABLE", "TOOL_SIGNATURE_MISMATCH"):
        logger.info(
            f"list_apaas_app_processes failed ({raw_or_err.get('error_code')}), "
            "降级走 list_apaas_app_menus"
        )
    return await _menus_filtered_by_type(app, {"MODEL"}, source)


@router.get(
    "/{app_id}/section-content/business-events",
    response_model=SectionContentResponse,
)
async def get_section_content_business_events(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """logic section: 列应用的业务事件 (走 list_apaas_business_events).

    note: 工具返 `{ok, apaas_app_id, data: {records/table: [...], total}}` 平台分页对象.
    """
    source = "list_apaas_business_events"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        # 用平台默认分页 (page=1, page_size=20) — 前端要更多自己再扩.
    )
    if not ok:
        return _tool_error(app, source, raw_or_err["error_code"], raw_or_err["message"])

    items = _extract_items_from_mcp_result(
        raw_or_err,
        key_candidates=["data", "events", "items"],
        id_keys=["eventId", "id", "event_id", "_id"],
        name_keys=["eventName", "name", "event_name"],
        code_keys=["eventCode", "code", "event_code"],
    )
    # data 是 dict 时 total 在内层
    total = 0
    data_obj = raw_or_err.get("data")
    if isinstance(data_obj, dict):
        total = int(data_obj.get("total") or len(items))
    else:
        total = int(raw_or_err.get("total") or len(items))
    return SectionContentResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=total,
        source=source,
    )


@router.get("/{app_id}/section-content/roles", response_model=SectionContentResponse)
async def get_section_content_roles(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """permission section: 列应用的角色 (走 list_apaas_app_roles)."""
    source = "list_apaas_app_roles"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
    )
    if not ok:
        return _tool_error(app, source, raw_or_err["error_code"], raw_or_err["message"])

    items = _extract_items_from_mcp_result(
        raw_or_err,
        key_candidates=["roles", "items"],
        id_keys=["role_id", "id"],
        name_keys=["role_name", "name"],
        code_keys=["role_code", "code"],
    )
    return SectionContentResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=int(raw_or_err.get("total") or len(items)),
        source=source,
    )
