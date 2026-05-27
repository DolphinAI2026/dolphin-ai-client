"""业务事件 endpoint — 包 list_apaas_business_events MCP 工具.

URL: GET /applications/{app_id}/business-events

跟现有 section_content endpoint `/section-content/business-events` 区别:
    section_content                       本模块 business_events
    ────────────────────                  ─────────────────────────
    SectionNav sub-tab 用                 SPEC 设计 tab 章九用
    返 SectionContentResponse 归一        返简化 dict (eventId/eventName/eventType/...)
    {ok, env_id, apaas_app_id, items}    {ok, items, total, ...}

两个 endpoint 并存因为前端章九展示字段不同 (含 trigger / target / 触发时机),
不强求合并. 后端调同一个 MCP 工具.

Returns:
  {
    ok: true,
    app_id, env_id, apaas_app_id,
    items: [
      {event_id, event_name, event_code, event_type, status,
       trigger: {form_id?, boc_code?}, last_update?},
      ...
    ],
    total: N,
    source: "list_apaas_business_events"
  }
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
# Pydantic
# ---------------------------------------------------------------------------
class BusinessEventTrigger(BaseModel):
    """事件触发源 — 一般是 form_id + boc_code, 不同 event_type schema 略差."""
    form_id: Optional[str] = None
    boc_code: Optional[str] = None
    field_code: Optional[str] = None  # EVENT_VALUE_CHANGE 字段名


class BusinessEventItem(BaseModel):
    event_id: str
    event_name: str
    event_code: Optional[str] = None
    event_type: str = ""  # EVENT_OPERATION / EVENT_BUTTON / EVENT_VALUE_CHANGE / ...
    status: str = ""  # ENABLE / DISABLE
    trigger: Optional[BusinessEventTrigger] = None
    target: Optional[str] = None  # 目标动作描述 (从 endNode 提)
    last_update: Optional[str] = None
    # 透传原始 raw — 前端要详细字段可看
    extra: dict[str, Any] = Field(default_factory=dict)


class BusinessEventsResponse(BaseModel):
    ok: bool
    app_id: int
    env_id: Optional[int] = None
    apaas_app_id: Optional[str] = None
    items: list[BusinessEventItem] = Field(default_factory=list)
    total: int = 0
    source: str = ""
    error_code: Optional[str] = None
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
async def _load_app(
    app_id: int,
    ctx: AuthContext,
    db: AsyncSession,
) -> Application:
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


async def _call_mcp(
    tool_name: str,
    env_id: int,
    apaas_app_id: str,
    extra: Optional[dict] = None,
) -> tuple[bool, dict[str, Any]]:
    """跟 section_content._safe_call_mcp_tool 同 pattern, 但本模块自带, 避免循环 import."""
    try:
        from app import mcp_server as _mcp
    except Exception as exc:  # noqa: BLE001
        return False, {
            "error_code": "MCP_MODULE_LOAD_FAILED",
            "message": f"mcp_server 模块加载失败: {exc}",
        }

    tool = getattr(_mcp, tool_name, None)
    if tool is None or not callable(tool):
        return False, {
            "error_code": "TOOL_NOT_AVAILABLE",
            "message": f"MCP 工具 {tool_name} 未注册 — backend 版本不匹配",
        }

    args: dict[str, Any] = {"env_id": env_id, "apaas_app_id": apaas_app_id}
    if extra:
        args.update(extra)

    try:
        raw = await tool(**args)
    except TypeError as exc:
        return False, {
            "error_code": "TOOL_SIGNATURE_MISMATCH",
            "message": f"MCP 工具 {tool_name} 签名不兼容: {exc}",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"business_events: MCP tool {tool_name} 抛错: {exc}")
        return False, {
            "error_code": "MCP_TOOL_ERROR",
            "message": f"MCP 工具 {tool_name} 调用失败: {exc}",
        }

    if not isinstance(raw, dict):
        return False, {
            "error_code": "MCP_UNEXPECTED_SHAPE",
            "message": f"MCP 工具返非 dict: {type(raw).__name__}",
        }
    if not raw.get("ok", False):
        return False, {
            "error_code": str(raw.get("error_code") or "MCP_TOOL_FAILED"),
            "message": str(raw.get("message") or "MCP 工具返回 ok=False"),
        }
    return True, raw


def _extract_trigger(raw_event: dict[str, Any]) -> Optional[BusinessEventTrigger]:
    """从 raw event 抽 triggerNodeNd (老平台叫 trigger / triggerForm)."""
    trigger = None
    trigger_node = raw_event.get("triggerNodeNd") or raw_event.get("triggerNode")
    if isinstance(trigger_node, dict):
        trigger = BusinessEventTrigger(
            form_id=str(
                trigger_node.get("triggerFormId") or trigger_node.get("formId") or ""
            ) or None,
            boc_code=str(
                trigger_node.get("triggerBocCode") or trigger_node.get("bocCode") or ""
            ) or None,
            field_code=str(
                trigger_node.get("triggerFieldCode") or trigger_node.get("fieldCode") or ""
            ) or None,
        )
    return trigger


def _extract_target_summary(raw_event: dict[str, Any]) -> Optional[str]:
    """从 eventNodeNdList 或 endNode 提一个简短摘要给前端显."""
    nodes = raw_event.get("eventNodeNdList") or []
    if isinstance(nodes, list) and nodes:
        types = [str(n.get("nodeType") or "") for n in nodes if isinstance(n, dict)]
        if types:
            return " → ".join(types[:3])
    end_node = raw_event.get("endNode")
    if isinstance(end_node, dict):
        return str(end_node.get("nodeName") or end_node.get("name") or "") or None
    return None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.get("/{app_id}/business-events", response_model=BusinessEventsResponse)
async def list_business_events(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    keyword: str = Query("", description="按 event_name 模糊匹配"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> BusinessEventsResponse:
    """拉应用业务事件 (调 list_apaas_business_events MCP).

    SPEC 设计 tab 章九用. 应用未部署 → ok=False + APP_NOT_DEPLOYED + items=[].
    """
    source = "list_apaas_business_events"
    app = await _load_app(app_id, ctx, db)

    if not app.platform_env_id or not app.apaas_app_id:
        return BusinessEventsResponse(
            ok=False,
            app_id=app.id,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id) if app.apaas_app_id else None,
            items=[],
            total=0,
            source=source,
            error_code="APP_NOT_DEPLOYED",
            message="应用尚未部署到 aPaaS 平台 — 部署后才能拉业务事件",
        )

    ok, raw = await _call_mcp(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra={"keyword": keyword, "page": page, "page_size": page_size},
    )
    if not ok:
        return BusinessEventsResponse(
            ok=False,
            app_id=app.id,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id),
            items=[],
            total=0,
            source=source,
            error_code=raw.get("error_code") or "MCP_TOOL_FAILED",
            message=raw.get("message") or "拉业务事件失败",
        )

    # MCP 返结构: {ok: true, apaas_app_id, data: {table/records: [...], total: N}}
    data = raw.get("data")
    events_raw: list[Any] = []
    total = 0
    if isinstance(data, dict):
        events_raw = (
            data.get("table") or data.get("records")
            or data.get("items") or data.get("list") or []
        )
        total = int(data.get("total") or 0)
    elif isinstance(data, list):
        events_raw = data
        total = len(data)
    if not isinstance(events_raw, list):
        events_raw = []
    if total == 0:
        total = len(events_raw)

    items: list[BusinessEventItem] = []
    for ev in events_raw:
        if not isinstance(ev, dict):
            continue
        items.append(
            BusinessEventItem(
                event_id=str(ev.get("eventId") or ev.get("id") or ev.get("_id") or ""),
                event_name=str(ev.get("eventName") or ev.get("name") or ""),
                event_code=str(ev.get("eventCode") or ev.get("code") or "") or None,
                event_type=str(ev.get("eventType") or ev.get("type") or ""),
                status=str(ev.get("status") or ""),
                trigger=_extract_trigger(ev),
                target=_extract_target_summary(ev),
                last_update=str(
                    ev.get("lastUpdateDate") or ev.get("updatedAt") or ev.get("update_time") or ""
                ) or None,
                extra=ev,
            )
        )

    return BusinessEventsResponse(
        ok=True,
        app_id=app.id,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        items=items,
        total=total,
        source=source,
    )
