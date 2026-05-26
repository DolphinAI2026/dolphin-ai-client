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

import json
import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application
from app.models.process_definition import ProcessDefinition
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
    with_fields: bool = Query(False, description="True 时拉完整字段 (FormBuilder 用), 默认 False 省 token"),
) -> SectionContentResponse:
    """data section: 列应用的数据模型 (走 list_apaas_app_models).

    默认 with_fields=False 省 token (用于左侧 list 渲染); FormBuilder 可传 with_fields=true
    让 extra 含 fields[] 数组, 直接喂前端 widget 渲染.

    返结构: items[].id = model_id, .name = model_name, .code = model_code, .extra = 整 model dict.
    """
    source = "list_apaas_app_models"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"with_fields": with_fields},
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


@router.get("/{app_id}/forms/{form_id}/components", response_model=SectionContentResponse)
async def get_form_components(
    app_id: int,
    form_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """design-v4 Phase A: 拿表单的字段组件 (FormBuilder 用 form_id 直查, 替代 model 反查).

    走 list_apaas_form_components MCP, 返字段 components list. 跟得帆云
    `/data-model-fn-config?formId=...` 真路径对齐 — 表单字段是 form 维度,
    不是 model 维度 (一个 form 绑一个 model, 字段配置在 form layout 上).

    items[].id = uuid, .name = label, .code = bo_code, .extra = 整 component dict
    含 component_type / required / choose_options / dictionary_choose_options.
    """
    source = "list_apaas_form_components"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)
    form_id = (form_id or "").strip()
    if not form_id:
        return _tool_error(app, source, "INVALID_FORM_ID", "form_id 不能为空")

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"form_id": form_id},
    )
    if not ok:
        return _tool_error(app, source, raw_or_err["error_code"], raw_or_err["message"])

    items = _extract_items_from_mcp_result(
        raw_or_err,
        key_candidates=["components", "items"],
        id_keys=["uuid", "id"],
        name_keys=["label", "name"],
        code_keys=["bo_code", "code"],
    )
    return SectionContentResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=int(raw_or_err.get("total") or len(items)),
        source=source,
    )


@router.get("/{app_id}/forms/{form_id}/detail")
async def get_form_detail(
    app_id: int,
    form_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """design-v4 Phase A+: 拿表单完整配置 (跟低代码原生 data-model-fn-config 100% 对齐).

    走 get_apaas_form_detail MCP, 返:
      - models: form 关联的所有 model (主表 + 子表 + 关联表), 每个含完整字段定义
      - components: form 已用组件 list
      - main_model_code: 主 model code (用于 sidebar 数据模型 tab 默认选中)

    替代之前 list_apaas_app_models 路径 — 那个会漏 borrow_apply 等 form-scoped model.
    """
    source = "get_apaas_form_detail"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return {
            "ok": False,
            "error_code": "APP_NOT_DEPLOYED",
            "message": "应用尚未部署到 aPaaS 平台",
            "source": source,
        }
    form_id = (form_id or "").strip()
    if not form_id:
        return {"ok": False, "error_code": "INVALID_FORM_ID", "message": "form_id 不能为空", "source": source}

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"form_id": form_id},
    )
    if not ok:
        return {
            "ok": False,
            "error_code": raw_or_err["error_code"],
            "message": raw_or_err["message"],
            "source": source,
        }
    return {
        "ok": True,
        "env_id": app.platform_env_id,
        "apaas_app_id": str(app.apaas_app_id),
        "form_id": form_id,
        "form_name": raw_or_err.get("form_name", ""),
        "main_model_code": raw_or_err.get("main_model_code", ""),
        "models": raw_or_err.get("models", []),
        "components": raw_or_err.get("components", []),
        "model_count": raw_or_err.get("model_count", 0),
        "component_count": raw_or_err.get("component_count", 0),
        "all_model_codes": raw_or_err.get("all_model_codes", []),
        "source": source,
    }


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


@router.get("/{app_id}/section-content/field-permissions", response_model=SectionContentResponse)
async def get_section_content_field_permissions(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """permission section / 字段权限 sub-tab: 列应用所有表单 (按表单管理字段权限).

    note: apaas 平台字段权限是按 form 配的 (`list_apaas_form_permissions(form_id)`).
    没有 app 维度 list. 这里列出所有 MODEL 菜单, 用户点击后再切到该表单的字段权限页.
    """
    source = "list_apaas_app_menus[for_field_permissions]"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)
    # 复用 MODEL 菜单列表 — 用户点哪个表单就跳到该表单字段权限编辑页
    return await _menus_filtered_by_type(app, {"MODEL"}, source)


@router.get("/{app_id}/section-content/menu-visibility", response_model=SectionContentResponse)
async def get_section_content_menu_visibility(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SectionContentResponse:
    """permission section / 菜单可见性 sub-tab: 列应用所有菜单 (按菜单管理可见角色).

    note: apaas 菜单可见性是 menu × role 矩阵, 没有 app 维度独立 list. 列所有菜单
    (含 GROUP / TASK_CENTER / MODEL 等), 用户点击后配 visibility.
    """
    source = "list_apaas_app_menus[for_menu_visibility]"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)
    # 列出所有 menu_type (不过滤) — 菜单可见性 cover 全部菜单
    return await _menus_filtered_by_type(
        app, {"MODEL", "GROUP", "TASK_CENTER", "PAGE_CUSTOM_DEV", "QUOTE"}, source,
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


# ---------------------------------------------------------------------------
# Phase D: 权限矩阵 — RoleManagePanel 矩阵 view 数据源.
# ---------------------------------------------------------------------------
class RoleResourceMatrixResource(BaseModel):
    id: str
    code: Optional[str] = None
    name: str


class RoleResourceMatrixRole(BaseModel):
    role_id: str
    role_code: str
    role_name: str
    member_count: int = 0


class RoleResourceMatrixResources(BaseModel):
    page: list[RoleResourceMatrixResource] = Field(default_factory=list)
    data: list[RoleResourceMatrixResource] = Field(default_factory=list)
    process: list[RoleResourceMatrixResource] = Field(default_factory=list)
    app_setting: list[RoleResourceMatrixResource] = Field(default_factory=list)


class RoleResourceMatrixResponse(BaseModel):
    ok: bool
    env_id: Optional[int] = None
    apaas_app_id: Optional[str] = None
    roles: list[RoleResourceMatrixRole] = Field(default_factory=list)
    resources: RoleResourceMatrixResources = Field(default_factory=RoleResourceMatrixResources)
    # matrix: role_id -> resource_id -> perm ('all'/'rw'/'r'/'none')
    matrix: dict[str, dict[str, str]] = Field(default_factory=dict)
    is_mock: bool = True
    note: Optional[str] = None
    source: str = ""
    error_code: Optional[str] = None
    message: Optional[str] = None


@router.get(
    "/{app_id}/role-resource-matrix",
    response_model=RoleResourceMatrixResponse,
)
async def get_role_resource_matrix_endpoint(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResourceMatrixResponse:
    """聚合应用所有角色 × 资源 (页面/数据/流程/应用设置) 的权限矩阵.

    给 design-v4 RoleManagePanel 矩阵 view 用 — 一次拉全, 前端不用串 4 个 list endpoint.
    数据源走 get_role_resource_matrix MCP 工具 (内部聚合 roles + menus + models).
    matrix 字段当前 mock — P2 真接 apaas list_apaas_form_permissions 取代.
    """
    source = "get_role_resource_matrix"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return RoleResourceMatrixResponse(
            ok=False,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id) if app.apaas_app_id else None,
            source=source,
            error_code="APP_NOT_DEPLOYED",
            message="应用尚未部署到 aPaaS 平台 — 部署后才能拉权限矩阵",
        )

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
    )
    if not ok:
        return RoleResourceMatrixResponse(
            ok=False,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id),
            source=source,
            error_code=raw_or_err.get("error_code") or "MCP_TOOL_FAILED",
            message=raw_or_err.get("message") or "矩阵聚合工具调用失败",
        )

    # raw_or_err 是 get_role_resource_matrix MCP 工具返的完整 dict — 字段已 normalize.
    roles_data = raw_or_err.get("roles") or []
    resources_data = raw_or_err.get("resources") or {}
    matrix_data = raw_or_err.get("matrix") or {}

    def _coerce_resource_list(raw_list: Any) -> list[RoleResourceMatrixResource]:
        if not isinstance(raw_list, list):
            return []
        out: list[RoleResourceMatrixResource] = []
        for it in raw_list:
            if not isinstance(it, dict):
                continue
            out.append(RoleResourceMatrixResource(
                id=str(it.get("id") or ""),
                code=str(it.get("code") or "") or None,
                name=str(it.get("name") or ""),
            ))
        return [r for r in out if r.id]

    resources = RoleResourceMatrixResources(
        page=_coerce_resource_list(resources_data.get("page")),
        data=_coerce_resource_list(resources_data.get("data")),
        process=_coerce_resource_list(resources_data.get("process")),
        app_setting=_coerce_resource_list(resources_data.get("app_setting")),
    )

    roles_norm: list[RoleResourceMatrixRole] = []
    for r in roles_data:
        if not isinstance(r, dict):
            continue
        roles_norm.append(RoleResourceMatrixRole(
            role_id=str(r.get("role_id") or ""),
            role_code=str(r.get("role_code") or ""),
            role_name=str(r.get("role_name") or ""),
            member_count=int(r.get("member_count") or 0),
        ))
    roles_norm = [r for r in roles_norm if r.role_id]

    # matrix 字段保留原 shape — role_id → resource_id → perm.
    matrix_norm: dict[str, dict[str, str]] = {}
    if isinstance(matrix_data, dict):
        for role_id, row in matrix_data.items():
            if not isinstance(row, dict):
                continue
            inner: dict[str, str] = {}
            for resource_id, perm in row.items():
                inner[str(resource_id)] = str(perm or "none")
            matrix_norm[str(role_id)] = inner

    return RoleResourceMatrixResponse(
        ok=True,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        roles=roles_norm,
        resources=resources,
        matrix=matrix_norm,
        is_mock=bool(raw_or_err.get("is_mock", True)),
        note=str(raw_or_err.get("note") or "") or None,
        source=source,
    )


# ---------------------------------------------------------------------------
# ProcessDefinition — design-v4 H2 简化 BPMN 序列化的本地 save/get
# ---------------------------------------------------------------------------
class ProcessDefinitionNodePos(BaseModel):
    x: float = 0
    y: float = 0


class ProcessDefinitionNode(BaseModel):
    id: str
    type: str
    label: Optional[str] = None
    position: ProcessDefinitionNodePos = Field(default_factory=ProcessDefinitionNodePos)
    props: dict[str, Any] = Field(default_factory=dict)


class ProcessDefinitionEdge(BaseModel):
    id: str
    source: str
    target: str
    label: Optional[str] = None
    condition: Optional[str] = None


class ProcessDefinitionBody(BaseModel):
    process_name: Optional[str] = None
    nodes: list[ProcessDefinitionNode] = Field(default_factory=list)
    edges: list[ProcessDefinitionEdge] = Field(default_factory=list)


class ProcessDefinitionResponse(BaseModel):
    ok: bool
    process_id: str
    process_name: Optional[str] = None
    version: int = 1
    updated_at: Optional[str] = None
    nodes: list[ProcessDefinitionNode] = Field(default_factory=list)
    edges: list[ProcessDefinitionEdge] = Field(default_factory=list)
    source: str = "process_definitions"


@router.post(
    "/{app_id}/processes/{process_id}/save-definition",
    response_model=ProcessDefinitionResponse,
)
async def save_process_definition(
    app_id: int,
    process_id: str,
    body: ProcessDefinitionBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProcessDefinitionResponse:
    """保存 ProcessDefinition JSON 到本地 (design-v4 H2 简化版).

    暂存到 backend `process_definitions` 表, 不转 BPMN/apaas 平台格式 (P5).
    用户后续点"部署"才会触发 apaas 真同步.
    """
    # 加载应用 + 检 EDIT 权限
    r = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if not process_id:
        raise HTTPException(status_code=400, detail="process_id 不能为空")

    # 序列化 body 到 JSON 文本
    definition_payload = {
        "process_name": body.process_name,
        "nodes": [n.model_dump() for n in body.nodes],
        "edges": [e.model_dump() for e in body.edges],
    }
    definition_json = json.dumps(definition_payload, ensure_ascii=False)

    # upsert — 先查再决定 INSERT/UPDATE (跨 dialect 通用)
    existing_q = await db.execute(
        select(ProcessDefinition).where(
            ProcessDefinition.application_id == app_id,
            ProcessDefinition.process_id == process_id,
        )
    )
    existing = existing_q.scalar_one_or_none()
    now = datetime.utcnow()
    if existing:
        existing.process_name = body.process_name
        existing.definition_json = definition_json
        existing.version = (existing.version or 1) + 1
        existing.updated_at = now
        await db.flush()
        row = existing
    else:
        row = ProcessDefinition(
            application_id=app_id,
            process_id=process_id,
            process_name=body.process_name,
            definition_json=definition_json,
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
    await db.commit()

    return ProcessDefinitionResponse(
        ok=True,
        process_id=process_id,
        process_name=row.process_name,
        version=row.version,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        nodes=body.nodes,
        edges=body.edges,
        source="process_definitions",
    )


@router.get(
    "/{app_id}/processes/{process_id}/definition",
    response_model=ProcessDefinitionResponse,
)
async def get_process_definition(
    app_id: int,
    process_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProcessDefinitionResponse:
    """读应用流程的本地 ProcessDefinition (没有 → 404).

    前端 reload 流程时优先调本接口; 404 才走 apaas 平台 list 兜底.
    """
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

    def_q = await db.execute(
        select(ProcessDefinition).where(
            ProcessDefinition.application_id == app_id,
            ProcessDefinition.process_id == process_id,
        )
    )
    row = def_q.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="本地暂无该流程定义")

    try:
        payload = json.loads(row.definition_json or "{}")
    except (ValueError, TypeError):
        payload = {}
    raw_nodes = payload.get("nodes") if isinstance(payload, dict) else None
    raw_edges = payload.get("edges") if isinstance(payload, dict) else None

    nodes: list[ProcessDefinitionNode] = []
    if isinstance(raw_nodes, list):
        for it in raw_nodes:
            if not isinstance(it, dict):
                continue
            try:
                nodes.append(ProcessDefinitionNode(**it))
            except Exception:  # noqa: BLE001 — 容忍坏 row, 不挡 reload
                logger.warning(f"skip malformed node in process {process_id}: {it!r}")

    edges: list[ProcessDefinitionEdge] = []
    if isinstance(raw_edges, list):
        for it in raw_edges:
            if not isinstance(it, dict):
                continue
            try:
                edges.append(ProcessDefinitionEdge(**it))
            except Exception:  # noqa: BLE001
                logger.warning(f"skip malformed edge in process {process_id}: {it!r}")

    return ProcessDefinitionResponse(
        ok=True,
        process_id=row.process_id,
        process_name=row.process_name,
        version=row.version,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        nodes=nodes,
        edges=edges,
        source="process_definitions",
    )


# ---------------------------------------------------------------------------
# Phase H1: 矩阵 cell 真存 — 单 cell 改动 dispatch 到对应 apaas 权限 API.
# ---------------------------------------------------------------------------
class RoleResourceCellRequest(BaseModel):
    """单 cell 权限改动入参."""
    role_id: str
    resource_type: str  # 'form' / 'model' / 'process' / 'app_setting'
    resource_id: str
    permission: str  # 'all' / 'rw' / 'r' / 'none'


class RoleResourceCellResponse(BaseModel):
    ok: bool
    source: str = ""
    resource_type: Optional[str] = None
    form_id: Optional[str] = None
    form_code: Optional[str] = None
    role_id: Optional[str] = None
    permission: Optional[str] = None
    message: Optional[str] = None
    error_code: Optional[str] = None


@router.post(
    "/{app_id}/role-resource-matrix/cell",
    response_model=RoleResourceCellResponse,
)
async def set_role_resource_cell_endpoint(
    app_id: int,
    body: RoleResourceCellRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResourceCellResponse:
    """改单个矩阵 cell 权限, 走 set_role_resource_permission MCP 工具.

    按 resource_type 分发: form 真存到 apaas 平台 (走 list+set form permissions),
    其他类型 P5 接入返 NOT_IMPLEMENTED.

    入参: {role_id, resource_type, resource_id, permission}
    返: {ok, source, message, ...} — ok=True 时 message="已保存".
    """
    source = "set_role_resource_permission"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return RoleResourceCellResponse(
            ok=False,
            source=source,
            error_code="APP_NOT_DEPLOYED",
            message="应用尚未部署到 aPaaS 平台 — 部署后才能写权限",
        )

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={
            "role_id": body.role_id.strip(),
            "resource_type": body.resource_type.strip().lower(),
            "resource_id": body.resource_id.strip(),
            "permission": body.permission.strip().lower(),
        },
    )
    if not ok:
        return RoleResourceCellResponse(
            ok=False,
            source=source,
            error_code=raw_or_err.get("error_code") or "MCP_TOOL_FAILED",
            message=raw_or_err.get("message") or "权限写入失败",
        )

    return RoleResourceCellResponse(
        ok=True,
        source=source,
        resource_type=str(raw_or_err.get("resource_type") or body.resource_type),
        form_id=str(raw_or_err.get("form_id") or "") or None,
        form_code=str(raw_or_err.get("form_code") or "") or None,
        role_id=str(raw_or_err.get("role_id") or body.role_id),
        permission=str(raw_or_err.get("permission") or body.permission),
        message=str(raw_or_err.get("message") or "已保存"),
    )
