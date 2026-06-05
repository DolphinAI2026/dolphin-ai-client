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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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


# ---------------------------------------------------------------------------
# Section content TTL 缓存 — apaas 每个 MCP 工具调用 1-3s, panel reload 一开就打 8-10
# 个工具, 用户切应用 / 切 chapter / spec_change 刷新都重打全套 → 极慢.
#
# 2026-05-27: 加 process-level TTL 缓存 (180s = 3 min), apply 后失效全部.
# 缓存只命中成功 (ok=True) 的工具结果; 失败结果不缓存 (下次再试).
#
# Force 模式: endpoint 加 ?force=true 跳过缓存 (前端"重试"按钮 / 调试用).
# ---------------------------------------------------------------------------
import time as _time

_SECTION_CACHE_TTL_SECONDS = 180.0
_section_cache: dict[tuple, tuple[float, dict]] = {}


def _cache_key(
    tool_name: str,
    env_id: int,
    apaas_app_id: str,
    extra_args: Optional[dict],
) -> tuple:
    """缓存 key — 工具名 + env + app + extra args (sorted tuple, hashable)."""
    extra_key: tuple = ()
    if extra_args:
        extra_key = tuple(sorted((k, str(v)) for k, v in extra_args.items()))
    return (tool_name, int(env_id), str(apaas_app_id), extra_key)


def invalidate_section_cache_for_app(apaas_app_id: str) -> int:
    """spec_apply 成功后清这个 app 的全部 section 缓存 — 让下次 reload 拿新数据.

    Returns: 清了多少条目 (便于 log).
    """
    key_str = str(apaas_app_id)
    keys_to_drop = [k for k in _section_cache if k[2] == key_str]
    for k in keys_to_drop:
        _section_cache.pop(k, None)
    return len(keys_to_drop)


def _cache_get(key: tuple) -> Optional[dict]:
    """命中 + 未过期 → 返 cached raw dict; 否则 None."""
    entry = _section_cache.get(key)
    if not entry:
        return None
    expires_at, raw = entry
    if _time.time() > expires_at:
        # 过期 — 清掉
        _section_cache.pop(key, None)
        return None
    return raw


def _cache_set(key: tuple, raw: dict) -> None:
    """写缓存, TTL 跟 _SECTION_CACHE_TTL_SECONDS."""
    _section_cache[key] = (_time.time() + _SECTION_CACHE_TTL_SECONDS, raw)


async def _safe_call_mcp_tool(
    tool_name: str,
    env_id: int,
    apaas_app_id: str,
    extra_args: Optional[dict] = None,
    *,
    use_cache: bool = True,
) -> tuple[bool, dict]:
    """调 MCP 工具的统一封装 — 工具不存在 / 抛异常 / 返 ok=False 都统一兜底.

    Returns:
      (ok, raw_or_error)
      - ok=True 时 raw_or_error 是 MCP 工具的原始 dict 返回.
      - ok=False 时 raw_or_error 是 {error_code, message} 错误结构.

    Cache:
      use_cache=True (默) → 命中 TTL cache (180s) 直接返, 不打 apaas.
      use_cache=False → 强制重打 (endpoint ?force=true 模式).
      只缓存成功结果, 失败下次再试.
    """
    # ── 缓存命中 fast path ────────────────────────────────────────────
    cache_key = _cache_key(tool_name, env_id, apaas_app_id, extra_args)
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return True, cached

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

    from app.error_messages import is_apaas_token_error

    async def _invoke() -> tuple[bool, dict, bool]:
        """跑一次工具。返回 (ok, payload, is_token_err)。payload 成功=raw, 失败=错误 dict。"""
        try:
            raw_ = await tool(**args)
        except TypeError as exc:
            # 签名不匹配 (e.g. with_fields 不存在) — 当工具不可用处理而不是 500.
            logger.warning(f"section_content: MCP tool {tool_name} TypeError: {exc}")
            return False, {
                "error_code": "TOOL_SIGNATURE_MISMATCH",
                "message": f"MCP 工具 {tool_name} 签名不兼容: {exc}",
            }, False
        except Exception as exc:
            logger.warning(f"section_content: MCP tool {tool_name} 抛错: {exc}")
            return False, {
                "error_code": "MCP_TOOL_ERROR",
                "message": f"MCP 工具 {tool_name} 调用失败: {exc}",
            }, is_apaas_token_error(str(exc))
        if not isinstance(raw_, dict):
            return False, {
                "error_code": "MCP_UNEXPECTED_SHAPE",
                "message": f"MCP 工具 {tool_name} 返非 dict: {type(raw_).__name__}",
            }, False
        if not raw_.get("ok", False):
            # MCP 工具显式失败 (e.g. INVALID_APAAS_APP_ID / APAAS_TOKEN_EXPIRED).
            err_code = str(raw_.get("error_code") or "MCP_TOOL_FAILED")
            err_msg = str(raw_.get("message") or "MCP 工具返回 ok=False")
            is_tok = is_apaas_token_error(err_msg) or is_apaas_token_error(err_code)
            return False, {"error_code": err_code, "message": err_msg}, is_tok
        return True, raw_, False

    ok, payload, is_tok = await _invoke()

    # 2026-05-29: aPaaS token 过期撞 401 → 用 env 账号密码自动重登 + 重试一次, 用户无感。
    if not ok and is_tok:
        try:
            from app.database import AsyncSessionLocal
            from app.coding.apaas_tools import _relogin_apaas_env
            async with AsyncSessionLocal() as _s:
                relogged = await _relogin_apaas_env(env_id, _s)
            if relogged:
                logger.info("section_content: %s 撞 token 失效, 已重登, 重试一次", tool_name)
                ok, payload, is_tok = await _invoke()
        except Exception as exc:  # noqa: BLE001
            logger.warning("section_content: %s 重登重试失败: %s", tool_name, exc)

    if not ok:
        # 失败结果不缓存 — 下次再试.
        return False, payload

    # 成功 → 写 TTL 缓存 (即便 use_cache=False 路径也写, 让后续 reload 命中).
    _cache_set(cache_key, payload)
    return True, payload


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


class FormPermRole(BaseModel):
    role_id: str
    role_name: str
    is_all_user: bool = False


class FormPermissionsResponse(BaseModel):
    ok: bool
    env_id: Optional[int] = None
    apaas_app_id: Optional[str] = None
    form_id: Optional[str] = None
    roles: list[FormPermRole] = Field(default_factory=list)
    # matrix: subject_key(role_id 或 "__ALL_USER__") -> {view,edit,delete,add,import: bool, range: str|None}
    matrix: dict[str, dict[str, Any]] = Field(default_factory=dict)
    source: str = ""
    error_code: Optional[str] = None
    message: Optional[str] = None


@router.get("/{app_id}/forms/{form_id}/permissions", response_model=FormPermissionsResponse)
async def get_form_permissions(
    app_id: int,
    form_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FormPermissionsResponse:
    """表单级权限矩阵 (角色 × 查看/编辑/删除/新增/导入 + 数据范围).

    读 list_apaas_form_permissions (真 apaas, 非 mock) + list_apaas_app_roles 拼角色名 →
    归一成 {roles, matrix}. 给设计器「权限」子 tab 用. 只读; 写走 POST 同路径 (Phase B).
    ALL_USER 主体 → 合成 "__ALL_USER__" 行排最前; USER/DEPT 主体 v1 不进矩阵 (留 P2).
    """
    source = "list_apaas_form_permissions"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return FormPermissionsResponse(
            ok=False,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id) if app.apaas_app_id else None,
            form_id=form_id,
            source=source,
            error_code="APP_NOT_DEPLOYED",
            message="应用尚未部署到 aPaaS 平台 — 部署后才能配表单权限",
        )
    form_id = (form_id or "").strip()
    if not form_id:
        return FormPermissionsResponse(
            ok=False,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id),
            form_id=form_id,
            source=source,
            error_code="INVALID_FORM_ID",
            message="form_id 不能为空",
        )

    env_id = app.platform_env_id
    apaas_app_id = str(app.apaas_app_id)

    # 1) 角色列表 (拼 role_name) — 失败不致命, 矩阵仍可显 ALL_USER / 已知 role_id.
    roles_norm: list[FormPermRole] = []
    ok_r, raw_r = await _safe_call_mcp_tool(
        "list_apaas_app_roles", env_id=env_id, apaas_app_id=apaas_app_id,
    )
    if ok_r:
        for r in _extract_items_from_mcp_result(
            raw_r,
            key_candidates=["roles", "items"],
            id_keys=["role_id", "id"],
            name_keys=["role_name", "name"],
            code_keys=["role_code", "code"],
        ):
            rid = str(r.id or "")
            if not rid:
                continue
            roles_norm.append(FormPermRole(role_id=rid, role_name=str(r.name or rid)))

    # 2) 表单权限 (真 apaas)
    ok_p, raw_p = await _safe_call_mcp_tool(
        source, env_id=env_id, apaas_app_id=apaas_app_id, extra_args={"form_id": form_id},
    )
    if not ok_p:
        return FormPermissionsResponse(
            ok=False,
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            roles=roles_norm,
            source=source,
            error_code=raw_p.get("error_code") or "MCP_TOOL_FAILED",
            message=raw_p.get("message") or "读表单权限失败",
        )

    matrix: dict[str, dict[str, Any]] = {}

    def _cell(subj: dict) -> Optional[dict[str, Any]]:
        stype = subj.get("subject_type")
        if stype == "ROLE":
            key = str(subj.get("subject_value") or "")
        elif stype == "ALL_USER":
            key = "__ALL_USER__"
        else:
            return None  # USER / DEPT 主体 v1 不进矩阵
        if not key:
            return None
        return matrix.setdefault(
            key,
            {"view": False, "edit": False, "delete": False, "add": False, "import": False, "range": None},
        )

    has_all_user = False
    for g in (raw_p.get("data_permissions") or []):
        subj = g.get("subject") or {}
        c = _cell(subj)
        if c is None:
            continue
        if subj.get("subject_type") == "ALL_USER":
            has_all_user = True
        c["view"] = c["view"] or bool(g.get("can_view"))
        c["edit"] = c["edit"] or bool(g.get("can_edit"))
        c["delete"] = c["delete"] or bool(g.get("can_delete"))
        if subj.get("range_type"):
            c["range"] = subj.get("range_type")
    for g in (raw_p.get("operation_permissions") or []):
        subj = g.get("subject") or {}
        c = _cell(subj)
        if c is None:
            continue
        if subj.get("subject_type") == "ALL_USER":
            has_all_user = True
        c["add"] = c["add"] or bool(g.get("can_add"))
        c["import"] = c["import"] or bool(g.get("can_import"))

    if has_all_user:
        roles_norm.insert(0, FormPermRole(role_id="__ALL_USER__", role_name="所有人(默认)", is_all_user=True))

    return FormPermissionsResponse(
        ok=True,
        env_id=env_id,
        apaas_app_id=apaas_app_id,
        form_id=form_id,
        roles=roles_norm,
        matrix=matrix,
        source=source,
    )


class FormPermSaveRequest(BaseModel):
    # matrix: subject_key(role_id 或 "__ALL_USER__") -> {view,edit,delete,add,import: bool, range: str|None}
    matrix: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.post("/{app_id}/forms/{form_id}/permissions", response_model=FormPermissionsResponse)
async def set_form_permissions(
    app_id: int,
    form_id: str,
    body: FormPermSaveRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FormPermissionsResponse:
    """覆盖式写表单级权限 (RMW: 读现状→保留 USER/DEPT 主体→并入提交矩阵→整表覆盖).

    ⚠️ 真写 apaas (set_apaas_form_permissions 覆盖式). 提交的 matrix 是 角色+ALL_USER 的
    完整期望态(前端载入现状→改→提交全量); USER/DEPT 主体不在矩阵里, 从现状读出保留,
    避免被覆盖式 API 清掉。自己按 _simplify_perm_object 真 key 转换(不用 mcp_server
    的 _form_perms_to_rules — 它读 subj.get('type') 与现状的 'subject_type' 不匹配, 有 bug)。
    """
    source = "set_apaas_form_permissions"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return FormPermissionsResponse(
            ok=False,
            env_id=app.platform_env_id,
            apaas_app_id=str(app.apaas_app_id) if app.apaas_app_id else None,
            form_id=form_id, source=source,
            error_code="APP_NOT_DEPLOYED", message="应用尚未部署 — 无法写权限",
        )
    form_id = (form_id or "").strip()
    if not form_id:
        return FormPermissionsResponse(
            ok=False, env_id=app.platform_env_id, apaas_app_id=str(app.apaas_app_id),
            form_id=form_id, source=source,
            error_code="INVALID_FORM_ID", message="form_id 不能为空",
        )

    env_id = app.platform_env_id
    apaas_app_id = str(app.apaas_app_id)

    # 1) form_code 反查 (set 需要) — ⚠️ 菜单的 form_code 实测为 null (set_role_resource_permission
    #    走菜单拿 form_code 对这类菜单也会失败). 用 get_apaas_form_detail 的 main_model_code:
    #    apaas 表单 code = 主模型 code (如 "idm_erp_payable", 设计器 header 显的就是它).
    ok_d, raw_d = await _safe_call_mcp_tool(
        "get_apaas_form_detail", env_id=env_id, apaas_app_id=apaas_app_id, extra_args={"form_id": form_id},
    )
    form_code = str((raw_d or {}).get("main_model_code") or "") if ok_d else ""
    if not form_code:
        return FormPermissionsResponse(
            ok=False, env_id=env_id, apaas_app_id=apaas_app_id, form_id=form_id, source=source,
            error_code="FORM_CODE_NOT_FOUND",
            message=((raw_d.get("message") if (not ok_d and isinstance(raw_d, dict)) else None)
                     or f"form_id={form_id} 未取到 form_code(main_model_code)"),
        )

    # 2) 读现状 (保留 USER/DEPT 主体, 避免覆盖式 set 清掉) — 不走缓存拿最新.
    ok_c, cur = await _safe_call_mcp_tool(
        "list_apaas_form_permissions", env_id=env_id, apaas_app_id=apaas_app_id,
        extra_args={"form_id": form_id}, use_cache=False,
    )
    if not ok_c:
        return FormPermissionsResponse(
            ok=False, env_id=env_id, apaas_app_id=apaas_app_id, form_id=form_id, source=source,
            error_code=cur.get("error_code") or "READ_BEFORE_WRITE_FAILED",
            message=cur.get("message") or "写前读现状失败",
        )

    preserved: dict[str, dict] = {}

    def _preserve(group: dict, act_keys: list) -> None:
        subj = group.get("subject") or {}
        st = str(subj.get("subject_type") or "").upper()
        if st not in ("USER", "DEPT"):
            return  # 角色 / ALL_USER 由提交矩阵覆盖, 不在这里保留
        sv = str(subj.get("subject_value") or "")
        rule = preserved.setdefault(f"{st}:{sv}", {
            "subject_type": st, "subject_value": sv,
            "subject_name": str(subj.get("subject_name") or sv),
            "actions": [], "range_type": str(subj.get("range_type") or "ALL").upper(),
        })
        for act, gk in act_keys:
            if group.get(gk) and act not in rule["actions"]:
                rule["actions"].append(act)

    for g in (cur.get("data_permissions") or []):
        if isinstance(g, dict):
            _preserve(g, [("view", "can_view"), ("edit", "can_edit"), ("delete", "can_delete")])
    for g in (cur.get("operation_permissions") or []):
        if isinstance(g, dict):
            _preserve(g, [("add", "can_add"), ("import", "can_import"), ("draft", "can_draft")])

    # 3) 角色名 (subject_name 显示用)
    role_names: dict[str, str] = {}
    ok_r, raw_r = await _safe_call_mcp_tool("list_apaas_app_roles", env_id=env_id, apaas_app_id=apaas_app_id)
    if ok_r:
        for r in _extract_items_from_mcp_result(
            raw_r, key_candidates=["roles", "items"],
            id_keys=["role_id", "id"], name_keys=["role_name", "name"], code_keys=["role_code", "code"],
        ):
            if r.id:
                role_names[str(r.id)] = str(r.name or r.id)

    # 4) 提交矩阵 → rules (只建有权限的主体; 全 false = 无权限 = 不建 rule)
    my_rules: list[dict] = []
    ACTS = ["view", "edit", "delete", "add", "import"]
    for key, cell in (body.matrix or {}).items():
        if not isinstance(cell, dict):
            continue
        actions = [a for a in ACTS if cell.get(a)]
        if not actions:
            continue
        rng = str(cell.get("range") or "ALL").upper()
        if key == "__ALL_USER__":
            my_rules.append({"subject_type": "ALL_USER", "subject_value": "",
                             "subject_name": "全部人员", "actions": actions, "range_type": rng})
        else:
            my_rules.append({"subject_type": "ROLE_USER", "subject_value": key,
                             "subject_name": role_names.get(key, key), "actions": actions, "range_type": rng})

    new_rules = list(preserved.values()) + my_rules
    if not new_rules:
        return FormPermissionsResponse(
            ok=False, env_id=env_id, apaas_app_id=apaas_app_id, form_id=form_id, source=source,
            error_code="EMPTY_MATRIX",
            message="矩阵全空 — 至少给一个角色/全员一项权限再保存(避免锁死表单访问)",
        )

    # 5) 覆盖写回真 apaas
    ok_w, raw_w = await _safe_call_mcp_tool(
        source, env_id=env_id, apaas_app_id=apaas_app_id,
        extra_args={"form_id": form_id, "form_code": form_code, "rules": new_rules}, use_cache=False,
    )
    if not ok_w:
        return FormPermissionsResponse(
            ok=False, env_id=env_id, apaas_app_id=apaas_app_id, form_id=form_id, source=source,
            error_code=raw_w.get("error_code") or "WRITE_FAILED",
            message=raw_w.get("message") or "写表单权限失败",
        )

    invalidate_section_cache_for_app(apaas_app_id)  # 失效缓存, 前端 reload GET 拿最新
    return FormPermissionsResponse(
        ok=True, env_id=env_id, apaas_app_id=apaas_app_id, form_id=form_id, source=source,
        message="表单权限已覆盖写入(apaas 运行时立即生效)",
    )


@router.get("/{app_id}/apaas-access-url")
async def get_apaas_access_url(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """拿应用在 apaas 的**真实运行态访问 URL** (跟最终用户访问应用一致).

    2026-05-28 实证: apaas 应用详情 (query_app_detail) 含:
      - accessUrl:       {host}/app/{tenantCode}/{appCode}/   ← PC 运行态
      - accessMobileUrl: {host}/m/{tenantCode}/{appCode}/     ← 移动端
    跟编辑器 URL (/platform/{tid}/admin/...) 完全不同前缀.
    之前 CUSTOM 自开发页 preview 猜的 /platform/{tid}/{app_code}/page/{menu_id}
    是错的 (apaas SPA 无此路由 → 白屏), 真路由走 accessUrl.

    返: {ok, access_url, access_mobile_url, app_code, tenant_code}
    """
    from app.coding.apaas_tools import call_apaas_with_relogin

    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED",
                "message": "应用尚未部署到 aPaaS 平台"}
    try:
        # 2026-06-01: 租户来源统一为「当前登录用户」—— 有 apaas_token 时直接用 ctx.user 三件套
        # (base_url + tenant + token, 对齐 __init__.py 既有正确模式), 避免用 app 绑定环境里
        # 残留的别家租户去查 → 拉不到 / 错租户。无当前用户 token 才退回 env 自愈路径 (保旧行为)。
        if ctx.user.apaas_token:
            from app.apaas_client import APaaSClient
            user_client = APaaSClient(
                base_url=ctx.user.apaas_base_url,
                tenant_id=ctx.user.apaas_tenant_id,
                token=ctx.user.apaas_token,
            )
            detail = await user_client.query_app_detail(str(app.apaas_app_id))
        else:
            detail = await call_apaas_with_relogin(
                app.platform_env_id, db,
                lambda c: c.query_app_detail(str(app.apaas_app_id)),
            )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error_code": "APAAS_CLIENT_ERROR", "message": f"拉应用详情失败: {exc}"}
    if not detail:
        return {"ok": False, "error_code": "APP_NOT_FOUND",
                "message": f"apaas 没找到应用 {app.apaas_app_id}"}
    access_url = str(detail.get("accessUrl") or "")
    if not access_url:
        return {"ok": False, "error_code": "NO_ACCESS_URL",
                "message": "应用详情没有 accessUrl — 可能尚未部署/发布"}
    return {
        "ok": True,
        "access_url": access_url,
        "access_mobile_url": str(detail.get("accessMobileUrl") or ""),
        "app_code": str(detail.get("appCode") or ""),
        "tenant_code": str(detail.get("tenantCode") or ""),
    }


@router.get("/{app_id}/editor-url")
async def get_editor_url(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    menu_type: str = "",
    menu_id: str = "",
    form_id: str = "",
) -> dict:
    """返回 host-absolute 的 aPaaS 原生编辑器深链（前端 window.open 新标签页用）。

    host = 应用绑定环境 PlatformEnv.base_url（去 /backend）；tid = platform_tenant_id。
    路径由 app.apaas_editor_url.build_editor_path 构建。
    """
    from app.apaas_editor_url import build_editor_path
    from app.models import PlatformEnv

    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return {"ok": False, "error_code": "APP_NOT_DEPLOYED", "message": "应用尚未部署到 aPaaS 平台"}
    env = (
        await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.id == app.platform_env_id,
                PlatformEnv.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not env or not env.base_url or not env.platform_tenant_id:
        return {"ok": False, "error_code": "ENV_NOT_BOUND", "message": "应用未绑定有效平台环境"}
    host = env.base_url.rstrip("/").replace("/backend", "")
    path = build_editor_path(
        menu_type, apaas_app_id=str(app.apaas_app_id),
        menu_id=menu_id, form_id=form_id, tid=str(env.platform_tenant_id),
    )
    return {"ok": True, "url": f"{host}{path}"}


def _custom_host_error_html(msg: str) -> str:
    safe = (msg or "").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
        "font-family:-apple-system,sans-serif;background:#f8f8fc;color:#666}"
        ".b{max-width:420px;text-align:center;padding:32px}h3{color:#333;margin:0 0 8px;font-size:15px}"
        "p{font-size:13px;margin:0;line-height:1.6}</style></head>"
        f"<body><div class='b'><h3>自开发组件预览暂不可用</h3><p>{safe}</p></div></body></html>"
    )


def _build_custom_page_host_html(
    app_base: str, bundle_dir: str, component_tag: str,
    api_base: str, apaas_app_id: str, tenant_id: str,
) -> str:
    """构建自开发整页组件的独立运行 host HTML.

    思路: 不加载 apaas 完整运行态 SPA (有端用户登录闸 + 整套框架), 只把自开发组件的
    UMD bundle 拉过来, 在我们自己提供的 Vue2 + ElementUI 宿主里 install + mount.
    无登录闸 → 直接渲染页面骨架. 数据调用 (this.$request / window.df) 走同源 /apaas
    代理 (后端注入平台 token); 取不到数据时组件仍渲染 UI — 对"预览长什么样"已足够.

    bundle 是 Vue2 plugin: install(Vue){ Vue.component(component_tag, ...) }, UMD 全局名
    = bundle_dir. 依赖实测: Vue2 + ElementUI (el-table/card/button/icon/tag/progress/empty),
    无 echarts / 无 apaas base 组件.
    """
    import json as _json
    cfg = _json.dumps({
        "appBase": app_base, "bundleDir": bundle_dir, "componentTag": component_tag,
        "apiBase": api_base, "apaasAppId": apaas_app_id, "tenantId": tenant_id,
    })
    # Vue2 + ElementUI 走 CDN (jsdelivr). 注: 这是预览宿主, 生产可换内网 CDN / vendored.
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>自开发页面预览</title>"
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/element-ui@2.15.14/lib/theme-chalk/index.css'>"
        f"<link rel='stylesheet' href='{app_base}{bundle_dir}/{bundle_dir}.css'>"
        "<style>"
        "html,body{margin:0;height:100%;background:#f5f6fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
        "#app{min-height:100vh}"
        "#host-loading{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;"
        "justify-content:center;gap:12px;color:#888;font-size:13px;background:#f5f6fa;z-index:9999}"
        ".host-spin{width:32px;height:32px;border:3px solid #e4e7ed;border-top-color:#5B5BD6;border-radius:50%;"
        "animation:hs .7s linear infinite}@keyframes hs{to{transform:rotate(360deg)}}"
        "#host-status{font-size:12px;max-width:80%;text-align:center}#host-status.err{color:#dc2626}"
        "</style>"
        "<script src='https://cdn.jsdelivr.net/npm/vue@2.7.16/dist/vue.min.js'></script>"
        "<script src='https://cdn.jsdelivr.net/npm/element-ui@2.15.14/lib/index.js'></script>"
        "</head><body>"
        "<div id='host-loading'><div class='host-spin'></div><div id='host-status'>正在加载自开发组件…</div></div>"
        "<div id='app'></div>"
        "<script>\n"
        f"var HOST_CFG = {cfg};\n"
        "(function(){\n"
        "  var C = HOST_CFG;\n"
        "  function setStatus(m, err){ var e=document.getElementById('host-status'); if(e){ e.textContent=m; e.className=err?'err':''; } }\n"
        "  function hideLoading(){ var e=document.getElementById('host-loading'); if(e) e.style.display='none'; }\n"
        "  window.GLOBAL_ENV = window.GLOBAL_ENV || {};\n"
        "  window.GLOBAL_ENV.VUE_APP_APP_ID = C.apaasAppId;\n"
        "  window.GLOBAL_ENV.VUE_APP_TENANT_ID = C.tenantId;\n"
        "  window.GLOBAL_ENV.VUE_APP_BASE_DOMAIN = C.apiBase;\n"
        "  // $request shim — 同源 /apaas 代理 (后端注入 token). 得帆云 $request body 用 params.\n"
        "  function apaasRequest(cfg){\n"
        "    if (typeof cfg === 'string') cfg = { url: cfg };\n"
        "    cfg = cfg || {}; var url = cfg.url || '';\n"
        "    if (url.indexOf('http') !== 0) {\n"
        "      if (url.charAt(0) !== '/') url = C.apiBase + '/' + url;\n"
        "      else if (url.indexOf('/apaas') !== 0) url = C.apiBase + url;\n"
        "    }\n"
        "    var method = (cfg.method || 'get').toUpperCase();\n"
        "    var params = cfg.params || cfg.data;\n"
        "    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };\n"
        "    if (params && method === 'GET') {\n"
        "      var qs = Object.keys(params).map(function(k){ return encodeURIComponent(k)+'='+encodeURIComponent(params[k]); }).join('&');\n"
        "      if (qs) url += (url.indexOf('?')<0?'?':'&') + qs;\n"
        "    } else if (params) { opts.body = typeof params==='string'?params:JSON.stringify(params); }\n"
        "    return fetch(url, opts).then(function(r){ return r.json().catch(function(){ return null; }); })\n"
        "      .then(function(j){ return (j && typeof j==='object' && 'data' in j) ? j : { data: j, success: true }; })\n"
        "      .catch(function(e){ console.warn('[host] $request fail', url, e); return { data: null, success: false }; });\n"
        "  }\n"
        "  // window.df shim — 已知方法 + chainable no-op 兜底 (取不到的方法返 resolved Promise 防崩)\n"
        "  var dfBase = {\n"
        "    request: apaasRequest, http: apaasRequest,\n"
        "    get: function(u,p){ return apaasRequest({url:u,method:'get',params:p}); },\n"
        "    post: function(u,p){ return apaasRequest({url:u,method:'post',params:p}); },\n"
        "    getToken: function(){ return ''; }, t: function(k){ return k; }, i18n: { t: function(k){ return k; } },\n"
        "    user: {}, store: {}, env: window.GLOBAL_ENV,\n"
        "  };\n"
        "  window.df = new Proxy(dfBase, { get: function(t,k){ if (k in t) return t[k]; return function(){ return Promise.resolve(null); }; } });\n"
        "  function boot(){\n"
        "    var Vue = window.Vue;\n"
        "    Vue.config.productionTip = false;\n"
        "    Vue.config.errorHandler = function(err, vm, info){ console.error('[host] vue error', info, err); };\n"
        "    Vue.prototype.$request = apaasRequest; Vue.prototype.$df = window.df;\n"
        "    if (window.ELEMENT && window.ELEMENT.Message) { Vue.prototype.$message = window.ELEMENT.Message; }\n"
        "    var s = document.createElement('script');\n"
        "    s.src = C.appBase + C.bundleDir + '/' + C.bundleDir + '.umd.js';\n"
        "    s.onload = function(){\n"
        "      var raw = window[C.bundleDir];\n"
        "      if (!raw) { setStatus('组件包已加载但找不到导出: ' + C.bundleDir, true); return; }\n"
        "      // UMD 用 esModuleInterop 导出 { default: plugin, _Ctor } — 真插件在 .default\n"
        "      var plugin = (raw && raw.default) ? raw.default : raw;\n"
        "      try {\n"
        "        if (plugin && typeof plugin.install === 'function') Vue.use(plugin);\n"
        "        else if (plugin) Vue.component(C.componentTag, plugin);\n"
        "      } catch(e){ console.error('[host] register fail', e); }\n"
        "      if (!Vue.options.components[C.componentTag]) {\n"
        "        setStatus('组件未注册成功: ' + C.componentTag, true); return;\n"
        "      }\n"
        "      try {\n"
        "        new Vue({ render: function(h){ return h(C.componentTag); } }).$mount('#app');\n"
        "        hideLoading();\n"
        "      } catch(e){ setStatus('挂载组件失败: ' + (e&&e.message||e), true); console.error(e); }\n"
        "    };\n"
        "    s.onerror = function(){ setStatus('组件包加载失败 (404?): ' + s.src, true); };\n"
        "    document.body.appendChild(s);\n"
        "  }\n"
        "  var tries = 0;\n"
        "  (function wait(){\n"
        "    if (window.Vue && window.ELEMENT) { boot(); return; }\n"
        "    if (tries++ > 120) { setStatus('依赖加载超时 — Vue / ElementUI CDN 不可达', true); return; }\n"
        "    setTimeout(wait, 100);\n"
        "  })();\n"
        "})();\n"
        "</script></body></html>"
    )


@router.get("/{app_id}/custom-page-host")
async def get_custom_page_host(
    app_id: int,
    menu_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _auth: str = "",
):
    """自开发整页 (CUSTOM 菜单) 的**独立运行 host** — 直接跑自开发组件 bundle.

    2026-05-28: 之前 preview 是 iframe 整个 apaas 运行态 SPA, 但部署应用按租户做
    端用户登录 → iframe 卡在 /account/login. 用户决策: 我们已经能拿到自开发组件的
    UMD bundle, 直接在自己的 Vue2+ElementUI 宿主里 mount 它, 跳过 apaas 登录闸.

    返 text/html 的 host 页 (iframe src 指这里). host 内: CDN Vue2+ElementUI +
    window.df/$request shim + 拉 bundle umd + install + mount component_tag.

    认证: iframe src GET 带不了 Authorization header → 走 ?_auth=<token> query param
    (跟 platform-proxy/entry 一致), fallback header.
    """
    from fastapi.responses import HTMLResponse
    from app.coding.apaas_tools import call_apaas_with_relogin
    from app.deps import get_auth_context_from_token

    token = _auth or ""
    if not token:
        ah = request.headers.get("authorization", "")
        if ah.startswith("Bearer "):
            token = ah[7:]
    try:
        ctx = await get_auth_context_from_token(token)
    except Exception:  # noqa: BLE001
        return HTMLResponse(_custom_host_error_html("未认证 — 请重新登录后重试"))

    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return HTMLResponse(_custom_host_error_html("应用尚未部署到 aPaaS 平台"))
    try:
        detail = await call_apaas_with_relogin(
            app.platform_env_id, db,
            lambda c: c.query_app_detail(str(app.apaas_app_id)),
        )
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(_custom_host_error_html(f"拉应用详情失败: {exc}"))
    detail = detail or {}
    tenant_code = str(detail.get("tenantCode") or "")
    app_code = str(detail.get("appCode") or "")
    if not tenant_code or not app_code:
        return HTMLResponse(_custom_host_error_html("应用详情缺 tenantCode / appCode — 可能尚未发布"))

    # 运行态状态门：自开发整页 bundle 挂在 apaas **运行态** /app/{tenant}/{app}/ 下,
    # 应用「已下线」(status=SHUTDOWN) 时整个运行态路径被 apaas 404 → bundle 拉不到 →
    # 之前只弹「组件包加载失败 (404?)」这种天书。这里提前判 status, 给一句人话。
    # (RUNNING=已上线 才真在跑; 其余 SHUTDOWN/启动中 等都没法预览。)
    app_status = str(detail.get("status") or "").upper()
    if app_status and app_status != "RUNNING":
        status_name = str(detail.get("statusName") or "未运行")
        app_label = str(detail.get("appName") or app_code)
        return HTMLResponse(_custom_host_error_html(
            f"应用「{app_label}」在 aPaaS 当前为「{status_name}」,未处于运行态 — "
            f"自开发页面要应用上线运行后才能预览。请先到 aPaaS 启动/上线该应用,再回来刷新预览。"
        ))

    # 解析 menu_id → link_url (= 注册的组件 tag, 如 apaas-custom-library-home-dashboard).
    # 用 client.query_menus (manageAppMenu 管理视图, 含 linkUrl) — MCP list_apaas_app_menus
    # 走 runtime allAppMenu 视图不带 linkUrl, 不能用.
    try:
        raw_menus_nested = await call_apaas_with_relogin(
            app.platform_env_id, db,
            lambda c: c.query_menus(str(app.apaas_app_id)),
        )
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(_custom_host_error_html(f"拉菜单失败: {exc}"))

    def _find_link_url(nodes: Any, target: str) -> str:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id") or n.get("menuId") or n.get("menu_id") or "")
            if nid == str(target):
                return str(n.get("linkUrl") or n.get("link_url") or "")
            found = _find_link_url(n.get("submenus") or n.get("children") or [], target)
            if found:
                return found
        return ""

    link_url = _find_link_url(raw_menus_nested or [], str(menu_id))
    if not link_url:
        return HTMLResponse(_custom_host_error_html("没找到该菜单的自开发组件 (link_url 为空)"))

    component_tag = link_url
    # bundle 目录命名: apaas-custom-{X} 组件 → form-page-{X} bundle (实证).
    if link_url.startswith("apaas-custom-"):
        bundle_dir = "form-page-" + link_url[len("apaas-custom-"):]
    else:
        bundle_dir = link_url

    app_base = f"/app/{tenant_code}/{app_code}/"
    api_base = f"/apaas/backend/{tenant_code}/{app_code}"
    html = _build_custom_page_host_html(
        app_base, bundle_dir, component_tag, api_base,
        str(app.apaas_app_id), str(detail.get("tenantId") or ""),
    )
    return HTMLResponse(html)


@router.get("/{app_id}/forms/{form_id}/detail")
async def get_form_detail(
    app_id: int,
    form_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    force: bool = Query(False, description="True 时跳过 180s 缓存强制重拉 — 写后刷新用 (apaas 改完读模型才追上, 缓存命中会返 stale)"),
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
        use_cache=not force,
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
        # 2026-05-27 T: 列表页真实配置 (apaas 列表设计 tab 的 queryConditions + queryList)
        # ListDesignerPanel 用这个判 "用户在 apaas 上是否真配过列表" — 没配显空态而不是
        # 自己猜全部字段当列.
        "list_page_view": raw_or_err.get("list_page_view", {"query_conditions": [], "query_list": []}),
        "source": source,
    }


class CustomWidgetChatBody(BaseModel):
    """OPENAPI_SSE_CHAT 自开发组件 — 预览交互 chat 请求体."""
    bo_code: str = Field(..., description="组件 bo_code (定位是哪个自开发组件)")
    input: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(None, description="覆盖 config 里的 sessionId; 空用 config 的")


@router.post("/{app_id}/forms/{form_id}/custom-widget/chat")
async def custom_widget_chat_proxy(
    app_id: int,
    form_id: str,
    body: CustomWidgetChatBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """P2: 自开发组件 OPENAPI_SSE_CHAT 真交互 — backend SSE 代理.

    为什么走 backend 代理 (不前端直连):
      - authorization bearer token 不下发前端 (前端拿到的 config 已脱敏成 ***)
      - 规避 dolphin-trial CORS (前端 origin 不在白名单)
      - 统一鉴权 (本 endpoint 走 ai-builder 自己的 ctx 权限校验)

    流程:
      1. 校 VIEW 权限 + 拉 RAW form detail (未脱敏, 含真 token)
      2. 按 bo_code 定位自开发组件 + 取 customComponentConfig
      3. 转发 POST apiUrl (body {input, sessionId, stream:true}), 透传 SSE
      4. 逐 chunk re-emit {event:token, data:{text}} 给前端

    2026-05-28 实证 dolphin agentChat OpenAPI 协议:
      POST {apiUrl}  headers: Authorization + X-Tenant-Id + Content-Type
      body: {"input": "<msg>", "sessionId": "<sid>", "stream": true}
      SSE:  data: {"type":"TEXT","id":"...","text":"<token>"}
    """
    import httpx
    from sse_starlette.sse import EventSourceResponse
    from app.coding.apaas_tools import call_apaas_with_relogin

    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用未部署到 aPaaS 平台")
    fid = (form_id or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="form_id 不能为空")

    # ── 拉 RAW form detail (未脱敏) — 直调 apaas_client, 不走脱敏的 MCP 工具 ──
    try:
        raw = await call_apaas_with_relogin(
            app.platform_env_id, db,
            lambda c: c.query_detail_page_config(str(app.apaas_app_id), fid),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"拉 apaas 表单配置失败: {exc}")

    detail_page = raw.get("detailPage") or {}
    comps = detail_page.get("formComponents") or raw.get("formComponents") or []
    target = None
    for c in comps:
        if not isinstance(c, dict):
            continue
        ct = str(c.get("componentType") or "")
        if ct.startswith("FORM_CUSTOM_COMPONENT_") and str(c.get("boCode") or "") == body.bo_code:
            target = c
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"未找到自开发组件 bo_code={body.bo_code}")

    ct = str(target.get("componentType") or "")
    if ct != "FORM_CUSTOM_COMPONENT_OPENAPI_SSE_CHAT":
        raise HTTPException(
            status_code=400,
            detail=f"组件类型 {ct} 暂不支持预览交互 (目前仅 OPENAPI_SSE_CHAT)",
        )

    cfg = target.get("customComponentConfig") or {}
    api_url = str(cfg.get("apiUrl") or "")
    authorization = str(cfg.get("authorization") or "")
    tenant_id = str(cfg.get("tenantId") or "default")
    session_id = body.session_id or str(cfg.get("sessionId") or "")
    if not api_url or not authorization:
        raise HTTPException(status_code=400, detail="自开发组件 config 缺 apiUrl / authorization")

    fwd_headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "X-Tenant-Id": tenant_id,
    }
    fwd_body = {"input": body.input, "sessionId": session_id, "stream": True}

    async def event_stream():
        try:
            async with httpx.AsyncClient(verify=False, timeout=120.0) as h:
                async with h.stream("POST", api_url, headers=fwd_headers, json=fwd_body) as resp:
                    if resp.status_code != 200:
                        err_txt = (await resp.aread()).decode("utf-8", "ignore")[:300]
                        yield {"event": "error", "data": json.dumps(
                            {"message": f"上游 HTTP {resp.status_code}: {err_txt}"},
                            ensure_ascii=False,
                        )}
                        return
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            obj = json.loads(payload)
                        except (ValueError, TypeError):
                            continue
                        text = obj.get("text")
                        if text:
                            yield {"event": "token", "data": json.dumps({"text": text}, ensure_ascii=False)}
        except Exception as exc:  # noqa: BLE001
            yield {"event": "error", "data": json.dumps({"message": f"代理转发失败: {exc}"}, ensure_ascii=False)}
        finally:
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


@router.get("/{app_id}/forms/{form_id}/business-data")
async def get_form_business_data(
    app_id: int,
    form_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1, description="页码 (1-based)"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数, 上限 200"),
    tab_id: str = Query("", description="表单视图 id (空时自动取默认 tab)"),
) -> dict:
    """design-v4 O2-List: 拉表单的运行时业务数据 (用户提交的数据行).

    走 query_apaas_business_data MCP, 跟得帆云原生表单"列表页"背后真接口一致.

    返:
      - items: 数据行数组 (每行 dict, key 是字段 uuid)
      - total: 总行数
      - tab_id: 实际用的视图 id
      - page / page_size: 当前页

    P0 简化: 不支持 server-side filter/sort, 客户端拿到后 in-memory 处理.
    """
    source = "query_apaas_business_data"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return {
            "ok": False,
            "error_code": "APP_NOT_DEPLOYED",
            "message": "应用尚未部署到 aPaaS 平台",
            "source": source,
            "items": [],
            "total": 0,
        }
    form_id = (form_id or "").strip()
    if not form_id:
        return {
            "ok": False,
            "error_code": "INVALID_FORM_ID",
            "message": "form_id 不能为空",
            "source": source,
            "items": [],
            "total": 0,
        }

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={
            "form_id": form_id,
            "tab_id": tab_id or "",
            "page": page,
            "page_size": page_size,
        },
    )
    if not ok:
        return {
            "ok": False,
            "error_code": raw_or_err["error_code"],
            "message": raw_or_err["message"],
            "source": source,
            "items": [],
            "total": 0,
        }
    return {
        "ok": True,
        "env_id": app.platform_env_id,
        "apaas_app_id": str(app.apaas_app_id),
        "form_id": form_id,
        "tab_id": raw_or_err.get("tab_id", ""),
        "page": raw_or_err.get("page", page),
        "page_size": raw_or_err.get("page_size", page_size),
        "total": int(raw_or_err.get("total") or 0),
        "items_count": raw_or_err.get("items_count", 0),
        "items": raw_or_err.get("items", []),
        "source": source,
    }


@router.get("/{app_id}/section-content/dicts", response_model=SectionContentResponse)
async def get_section_content_dicts(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    with_options: bool = Query(False, description="是否回填字典 options[] (省 token 默认 False)"),
) -> SectionContentResponse:
    """data section: 列应用的字典.

    走 list_apaas_app_dicts. with_options=True 时 MCP 会真拉每个 dict 的 options 数组
    (跟 query_dict_options 同源), 适合 SPEC 设计 tab 一次展示全字典内容.
    """
    source = "list_apaas_app_dicts"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed(app, source)

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"with_options": bool(with_options)},
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

    # 兜底走 menus 过滤 menu_type=PROCESS — MODEL 是数据表单, 不是流程, 不能混.
    # 没真定义 BPMN 流程的应用 (例如 app_id=13 图书借阅管理系统) items 自然为空,
    # 前端走友好空态.
    if raw_or_err.get("error_code") not in ("TOOL_NOT_AVAILABLE", "TOOL_SIGNATURE_MISMATCH"):
        logger.info(
            f"list_apaas_app_processes failed ({raw_or_err.get('error_code')}), "
            "降级走 list_apaas_app_menus[menu_type=PROCESS]"
        )
    return await _menus_filtered_by_type(app, {"PROCESS"}, source)


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
# design-v4 K3: 应用发布状态 — 3 态判断 (draft / published / draft_on_published)
# ---------------------------------------------------------------------------
class PublishStatusResponse(BaseModel):
    ok: bool
    status: str  # 'draft' | 'published' | 'draft_on_published' | 'failed' | 'generating'
    latest_deploy: Optional[dict[str, Any]] = None
    pending_changes_count: int = 0
    last_modified_at: Optional[str] = None
    message: Optional[str] = None
    # 2026-05-29: 从未成功发布的应用, 暴露真实 app.status 而非一律 'draft'。
    partial: bool = False  # status='failed' 且 apaas 已建了一部分 → 部分失败
    app_status: Optional[str] = None  # 原始 application.status (调试/tooltip)


@router.get("/{app_id}/publish-status", response_model=PublishStatusResponse)
async def get_publish_status(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishStatusResponse:
    """计算应用真发布状态 (K3).

    逻辑:
    - 查 deploy_records 最新 1 行 (status='success')
    - 没有 → 'draft' (从未部署)
    - 有 + application.updated_at > deploy_record.completed_at → 'draft_on_published'
    - 有 + 一致 → 'published'
    """
    from app.models.deploy_history import DeployRecord
    app = await _load_app_and_check_view(app_id, ctx, db)

    # 查最新成功部署
    q = await db.execute(
        select(DeployRecord)
        .where(DeployRecord.app_id == app_id, DeployRecord.status == "success")
        .order_by(DeployRecord.completed_at.desc())
        .limit(1)
    )
    latest = q.scalar_one_or_none()

    last_modified = getattr(app, "updated_at", None) or getattr(app, "created_at", None)

    if not latest:
        # 从未成功发布 → 别一律显示"草稿"。看 application.status 暴露真实态:
        #   failed → 生成失败 (apaas 已建了一部分则部分失败); generating/updating → 生成中。
        app_status = (app.status or "").lower()
        if app_status == "failed":
            ui_status = "failed"
        elif app_status in ("generating", "updating"):
            ui_status = "generating"
        else:
            ui_status = "draft"
        return PublishStatusResponse(
            ok=True,
            status=ui_status,
            latest_deploy=None,
            pending_changes_count=1 if last_modified else 0,
            last_modified_at=last_modified.isoformat() if last_modified else None,
            partial=(ui_status == "failed" and bool(app.apaas_app_id)),
            app_status=app.status,
        )

    deploy_dict = {
        "deploy_id": latest.id,
        "version": latest.version_label or f"v{latest.id}",
        "completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
        "user_id": latest.user_id,
        "deploy_type": latest.deploy_type,
    }

    has_pending = (
        last_modified
        and latest.completed_at
        and last_modified > latest.completed_at
    )
    return PublishStatusResponse(
        ok=True,
        status="draft_on_published" if has_pending else "published",
        latest_deploy=deploy_dict,
        pending_changes_count=1 if has_pending else 0,
        last_modified_at=last_modified.isoformat() if last_modified else None,
    )


# ---------------------------------------------------------------------------
# design-v4 J1: 拉 apaas 平台真有的流程详情 — fallback 路径 (本地 definition 不在时)
# ---------------------------------------------------------------------------
@router.get(
    "/{app_id}/processes/{process_id}/apaas-detail",
    response_model=ProcessDefinitionResponse,
)
async def get_process_apaas_detail(
    app_id: int,
    process_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProcessDefinitionResponse:
    """拉 apaas 平台已有流程详情 (用 get_apaas_process_detail MCP).

    跟 H2 local definition GET 路径互补:
      - frontend 优先调 .../definition (本地 ProcessDefinition 表)
      - 404 时调 .../apaas-detail 拉 apaas 平台真定义
      - 都没就空 canvas + 编辑提示

    返跟 ProcessDefinitionResponse 一样的结构, source='apaas_process_detail'.
    """
    source = "get_apaas_process_detail"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用未部署到 apaas")

    ok, raw_or_err = await _safe_call_mcp_tool(
        source,
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        extra_args={"process_id": process_id},
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"{raw_or_err.get('error_code')}: {raw_or_err.get('message')}",
        )

    nodes: list[ProcessDefinitionNode] = []
    for n in raw_or_err.get("nodes") or []:
        try:
            nodes.append(ProcessDefinitionNode(**n))
        except Exception:
            logger.warning(f"skip malformed apaas node: {n!r}")
    edges: list[ProcessDefinitionEdge] = []
    for e in raw_or_err.get("edges") or []:
        try:
            edges.append(ProcessDefinitionEdge(**e))
        except Exception:
            logger.warning(f"skip malformed apaas edge: {e!r}")

    return ProcessDefinitionResponse(
        ok=True,
        process_id=process_id,
        process_name=str(raw_or_err.get("process_name") or ""),
        version=0,
        updated_at=None,
        nodes=nodes,
        edges=edges,
        source="apaas_process_detail",
    )


# ---------------------------------------------------------------------------
# design-v4 I4: 部署 ProcessDefinition 到 apaas 平台 (真同步, 不只是本地 save)
# ---------------------------------------------------------------------------
class ProcessDeployResponse(BaseModel):
    ok: bool
    process_id: str
    deployed_version: Optional[int] = None
    deployed_at: Optional[str] = None
    apaas_app_id: Optional[str] = None
    menu_id: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0
    unsupported_nodes: list[dict[str, str]] = Field(default_factory=list)
    apaas_response_code: Optional[str] = None
    message: Optional[str] = None
    error_code: Optional[str] = None


@router.post(
    "/{app_id}/processes/{process_id}/deploy",
    response_model=ProcessDeployResponse,
)
async def deploy_process_endpoint(
    app_id: int,
    process_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProcessDeployResponse:
    """把本地 ProcessDefinition 真同步到 apaas 平台 (design-v4 I4).

    工作流:
      1) 验 app 存在 + 检 EDIT 权限 + 应用已部署 (apaas_app_id 非空)
      2) 调 MCP deploy_process_to_apaas (内含 24→17 翻译 + save_process_config)
      3) 返同步结果 + unsupported_nodes (P6 todo 节点)

    入参:
      - app_id (path)
      - process_id (path) — 一般是 apaas menu_id

    不同于 POST .../save-definition (只本地存):
      本接口走 apaas 真存, 流程在 apaas 平台立即生效.
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
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if not process_id or not process_id.strip():
        raise HTTPException(status_code=400, detail="process_id 不能为空")

    if not app.platform_env_id or not app.apaas_app_id:
        return ProcessDeployResponse(
            ok=False,
            process_id=process_id,
            error_code="APP_NOT_DEPLOYED",
            message="应用尚未部署到 aPaaS 平台 — 先 deploy_application 把应用部署后才能部署流程",
        )

    # 调 MCP 工具
    try:
        from app import mcp_server as _mcp
    except Exception as exc:
        return ProcessDeployResponse(
            ok=False,
            process_id=process_id,
            error_code="MCP_MODULE_LOAD_FAILED",
            message=f"mcp_server 模块加载失败: {exc}",
        )

    tool = getattr(_mcp, "deploy_process_to_apaas", None)
    if tool is None or not callable(tool):
        return ProcessDeployResponse(
            ok=False,
            process_id=process_id,
            error_code="TOOL_NOT_AVAILABLE",
            message="MCP 工具 deploy_process_to_apaas 未注册",
        )

    try:
        result = await tool(
            app_id=app_id,
            process_id=process_id.strip(),
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
    except Exception as exc:
        logger.exception("deploy_process_to_apaas threw: app_id=%s process_id=%s", app_id, process_id)
        return ProcessDeployResponse(
            ok=False,
            process_id=process_id,
            error_code="MCP_TOOL_ERROR",
            message=f"MCP 调用失败: {exc}",
        )

    if not isinstance(result, dict):
        return ProcessDeployResponse(
            ok=False,
            process_id=process_id,
            error_code="MCP_UNEXPECTED_SHAPE",
            message=f"MCP 工具返非 dict: {type(result).__name__}",
        )

    if not result.get("ok"):
        return ProcessDeployResponse(
            ok=False,
            process_id=process_id,
            error_code=str(result.get("error_code") or "DEPLOY_FAILED"),
            message=str(result.get("message") or "部署失败"),
            unsupported_nodes=result.get("unsupported_nodes") or [],
        )

    return ProcessDeployResponse(
        ok=True,
        process_id=process_id,
        deployed_version=result.get("deployed_version"),
        deployed_at=result.get("deployed_at"),
        apaas_app_id=str(result.get("apaas_app_id") or ""),
        menu_id=str(result.get("menu_id") or ""),
        node_count=int(result.get("node_count") or 0),
        edge_count=int(result.get("edge_count") or 0),
        unsupported_nodes=result.get("unsupported_nodes") or [],
        apaas_response_code=str(result.get("apaas_response_code") or "") or None,
        message=str(result.get("message") or "已部署"),
    )



# ---------------------------------------------------------------------------
# Q2 (2026-05-27): 应用数据源 endpoint — design-v4 4 tab 第二个 tab "数据源".
#
# 设计思路:
#   apaas 平台没暴露 "list datasources for app" 公共 API, 但每个 model / menu
#   都带 datasourceId 字段. 所以这个 endpoint 走聚合: 拉应用 models + menus,
#   distinct datasource_id, 再按 datasource_id group count.
#
#   datasource 详情字段 (name/type/host/port/is_online) — 没有公开工具能拿,
#   先返空 (fallback "未知" + datasource_id 当 name). P5 真接通 platform-admin
#   /datasource/list API 再 join 填回.
#
# 实测真实样本: apaas 返 model dict 含 "datasourceId": "833831227906588672".
# ---------------------------------------------------------------------------
class AppDatasourceItem(BaseModel):
    datasource_id: str
    name: str  # 暂用 datasource_id 当 name (P5 接平台 API 填真名)
    type: str  # MySQL/PostgreSQL/...
    host: Optional[str] = None
    port: Optional[int] = None
    model_count: int  # 多少 model 用这个 datasource
    is_online: Optional[bool] = None


class AppDatasourcesResponse(BaseModel):
    ok: bool
    items: list[AppDatasourceItem] = Field(default_factory=list)
    total: int = 0
    source: str = ""  # 调了哪些 MCP 工具 (debug 用, 逗号分隔)
    error_code: Optional[str] = None
    message: Optional[str] = None


def _aggregate_datasources_from_items(
    items: list[dict],
    id_keys: tuple[str, ...] = ("datasourceId", "datasource_id"),
) -> dict[str, dict]:
    """从 raw list (model 或 menu) 聚合 distinct datasource_id + count.

    Returns: {datasource_id: {"count": int, "raw_first": dict}}
    """
    agg: dict[str, dict] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        ds_id = ""
        for k in id_keys:
            v = it.get(k)
            if v:
                ds_id = str(v).strip()
                if ds_id:
                    break
        if not ds_id:
            continue
        slot = agg.setdefault(ds_id, {"count": 0, "raw_first": it})
        slot["count"] += 1
    return agg


async def _try_enrich_datasource_detail(
    env_id: int,
    apaas_app_id: str,
    datasource_id: str,
) -> Optional[dict]:
    """试着拿 datasource 详情 (name/type/host/port). 工具不存在返 None.

    试 2 个可能存在的 MCP 工具名:
      - get_apaas_datasource_detail
      - list_apaas_datasources (return list + filter by id)
    都没有就放弃, 返 None.
    """
    # 1) 先试 detail 工具
    ok, raw = await _safe_call_mcp_tool(
        "get_apaas_datasource_detail",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
        extra_args={"datasource_id": datasource_id},
    )
    if ok and isinstance(raw, dict):
        return raw

    # 2) 试 list 工具 — 一次拉所有再 filter (P5 接入时按需缓存)
    ok2, raw2 = await _safe_call_mcp_tool(
        "list_apaas_datasources",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
    )
    if ok2 and isinstance(raw2, dict):
        items_raw = raw2.get("items") or raw2.get("datasources") or raw2.get("list") or []
        if isinstance(items_raw, list):
            for it in items_raw:
                if not isinstance(it, dict):
                    continue
                this_id = str(
                    it.get("datasource_id") or it.get("datasourceId") or it.get("id") or ""
                ).strip()
                if this_id == datasource_id:
                    return it
    return None


@router.get("/{app_id}/datasources", response_model=AppDatasourcesResponse)
async def get_app_datasources(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AppDatasourcesResponse:
    """design-v4 Q2: 列应用关联的数据源 (DB 连接维度).

    实现:
      1. 调 list_apaas_app_models (with_fields=False) 拿 models — 每个 model
         raw dict 应含 datasourceId.
      2. 调 list_apaas_app_menus 拿 menus — 每菜单也带 datasource_id.
      3. distinct + count = 总用量, model_count = 多少 model 用这数据源.
      4. 每个 datasource_id 试 _try_enrich_datasource_detail 拿 name/type/host/port.
         工具不存在 → 字段空, 前端显 "未知".
    """
    source = "list_apaas_app_models+menus"
    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return AppDatasourcesResponse(
            ok=False,
            items=[],
            total=0,
            source=source,
            error_code="APP_NOT_DEPLOYED",
            message="应用尚未部署到 aPaaS 平台 — 部署后才能拉数据源",
        )

    env_id = app.platform_env_id
    apaas_app_id = str(app.apaas_app_id)

    # ── 1) 拉 models — 提 datasource_id ────────────────────────────────────
    # 注: _list_apaas_app_models normalize 后丢了 raw model 的 datasourceId 字段,
    # 但 list_apaas_app_menus 返的 menus 保留了 datasource_id (已 flatten).
    # 所以这里走 menus 主路径; models 当 secondary signal 兜底.
    menu_agg: dict[str, dict] = {}
    model_agg: dict[str, dict] = {}

    ok_menus, menus_raw = await _safe_call_mcp_tool(
        "list_apaas_app_menus",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
    )
    if ok_menus and isinstance(menus_raw, dict):
        menus_list = menus_raw.get("menus") or menus_raw.get("items") or []
        if isinstance(menus_list, list):
            menu_agg = _aggregate_datasources_from_items(
                menus_list,
                id_keys=("datasource_id", "datasourceId"),
            )

    # models 兜底 — _list_apaas_app_models normalize 不带 datasourceId,
    # 但试着读 (未来扩展时 / 别处定制时可能加上).
    ok_models, models_raw = await _safe_call_mcp_tool(
        "list_apaas_app_models",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
        extra_args={"with_fields": False},
    )
    if ok_models and isinstance(models_raw, dict):
        models_list = models_raw.get("models") or models_raw.get("items") or []
        if isinstance(models_list, list):
            model_agg = _aggregate_datasources_from_items(
                models_list,
                id_keys=("datasourceId", "datasource_id"),
            )

    # ── 2) merge: union of datasource_ids, model_count 优先 model_agg.count ─
    all_ds_ids: set[str] = set(menu_agg.keys()) | set(model_agg.keys())
    if not all_ds_ids:
        # 没拉到 menus 也没拉到 models — 区分 "真没数据源" vs "MCP 工具失败"
        if not ok_menus and not ok_models:
            # 两边都失败 → 上报错误
            err_msg = ""
            err_code = ""
            if isinstance(menus_raw, dict) and menus_raw.get("error_code"):
                err_code = str(menus_raw["error_code"])
                err_msg = str(menus_raw.get("message") or "")
            elif isinstance(models_raw, dict) and models_raw.get("error_code"):
                err_code = str(models_raw["error_code"])
                err_msg = str(models_raw.get("message") or "")
            return AppDatasourcesResponse(
                ok=False,
                items=[],
                total=0,
                source=source,
                error_code=err_code or "MCP_TOOL_ERROR",
                message=err_msg or "拉数据源列表失败",
            )
        # 否则真就是没数据源 (新建应用没 model 没 menu) — ok=True 空列表
        return AppDatasourcesResponse(
            ok=True,
            items=[],
            total=0,
            source=source,
        )

    # ── 3) 富化 detail (name/type/host/port/is_online) — 尽力而为 ─────────
    items_out: list[AppDatasourceItem] = []
    for ds_id in sorted(all_ds_ids):
        model_count = model_agg.get(ds_id, {}).get("count", 0)
        # 没 model 信息时, 拿 menu count 当 fallback (虽然语义略差).
        if model_count == 0:
            model_count = menu_agg.get(ds_id, {}).get("count", 0)

        # 默认字段 — 工具不可用时显
        name = ds_id  # P5 接平台 datasource API 后填真名
        ds_type = ""
        host: Optional[str] = None
        port: Optional[int] = None
        is_online: Optional[bool] = None

        # 试着读 raw_first 里的内联字段 (有些场景 menu/model 自带 datasourceName)
        for agg in (model_agg.get(ds_id), menu_agg.get(ds_id)):
            if not agg:
                continue
            raw_first = agg.get("raw_first") or {}
            if not isinstance(raw_first, dict):
                continue
            inline_name = str(
                raw_first.get("datasourceName")
                or raw_first.get("datasource_name")
                or raw_first.get("datasourceCode")
                or ""
            ).strip()
            if inline_name and name == ds_id:
                name = inline_name
            inline_type = str(
                raw_first.get("datasourceType")
                or raw_first.get("dbType")
                or ""
            ).strip()
            if inline_type and not ds_type:
                ds_type = inline_type

        # 再调 enrich 工具 (失败/不存在返 None)
        try:
            detail = await _try_enrich_datasource_detail(env_id, apaas_app_id, ds_id)
        except Exception as exc:
            logger.warning(f"get_app_datasources: enrich {ds_id} 失败: {exc}")
            detail = None
        if isinstance(detail, dict):
            d_name = str(
                detail.get("name")
                or detail.get("datasourceName")
                or detail.get("datasource_name")
                or ""
            ).strip()
            if d_name:
                name = d_name
            d_type = str(
                detail.get("type")
                or detail.get("datasourceType")
                or detail.get("dbType")
                or ""
            ).strip()
            if d_type:
                ds_type = d_type
            d_host = str(
                detail.get("host")
                or detail.get("datasourceAddress")
                or ""
            ).strip()
            if d_host:
                host = d_host
            d_port = detail.get("port") or detail.get("datasourcePort")
            try:
                if d_port is not None and d_port != "":
                    port = int(d_port)
            except (TypeError, ValueError):
                pass
            d_online = detail.get("is_online")
            if d_online is None:
                d_online = detail.get("isOnline")
            if isinstance(d_online, bool):
                is_online = d_online

        items_out.append(AppDatasourceItem(
            datasource_id=ds_id,
            name=name,
            type=ds_type,
            host=host,
            port=port,
            model_count=int(model_count or 0),
            is_online=is_online,
        ))

    return AppDatasourcesResponse(
        ok=True,
        items=items_out,
        total=len(items_out),
        source=source,
    )
