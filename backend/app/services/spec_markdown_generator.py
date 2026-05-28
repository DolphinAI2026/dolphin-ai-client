"""SPEC markdown generator — 实时拉 apaas 渲染 11 章 SPEC.md.

设计跟 SpecDesignPanel CHAPTERS 严格对齐 (frontend `frontend/src/components/v3/
SpecDesignPanel.vue:713`):

    一、应用信息   — Application metadata
    二、角色与权限  — list_apaas_app_roles
    三、数据模型   — list_apaas_app_models(with_fields=True)
    四、数据字典   — list_apaas_app_dicts(with_options=True)
    五、菜单结构   — list_apaas_app_menus
    六、表单设计   — menus 过 menu_type=MODEL
    七、列表设计   — 同 6 (一个 menu 含表单+列表视图)
    八、业务流程   — list_apaas_app_processes (兜底 menus 过 PROCESS)
    九、业务事件   — list_apaas_business_events (Y 新接通)
    十、集成 & 自开发 — menus 过 PAGE_CUSTOM_DEV
    十一、数据源    — distinct datasourceId 聚合 (复用 section_content 逻辑)

每章产物:
    ## N、章节标题
    (空时返 "_暂无数据_" 占位)
    (有数据时返 markdown 表格)

Returns:
    (markdown_str, sections_hash)

    sections_hash = sha256(sorted JSON of raw section data) — 用于 SpecDocument
    缓存失效判断. 任一章的 raw data 变化 hash 就变.

错误兜底:
    单章 MCP 工具失败 → 该章渲染 "_拉取失败: <error_code>_", 不抛 — 整文档仍可用.
    应用未部署 (apaas_app_id 空) → 各章渲染 "_应用未部署到 apaas, 无法拉数据_".

注: 当前 streaming markdown 用字符串 concat (够用 < 200 KB 范围). 真量大切 jinja2.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight MCP tool dispatch helper (本地复刻 section_content 的 _safe_call_mcp_tool)
# ---------------------------------------------------------------------------
async def _call_tool(
    tool_name: str,
    *,
    env_id: int,
    apaas_app_id: str,
    extra: Optional[dict[str, Any]] = None,
) -> tuple[bool, dict[str, Any]]:
    """调 MCP 工具的统一封装 — 工具不存在 / 抛异常 / 返 ok=False 都统一兜底."""
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
            "message": f"MCP 工具 {tool_name} 未注册",
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
        return False, {
            "error_code": str(raw.get("error_code") or "MCP_TOOL_FAILED"),
            "message": str(raw.get("message") or "MCP 工具返回 ok=False"),
        }
    return True, raw


# ---------------------------------------------------------------------------
# 章节渲染 — 每个函数返 (markdown_section_str, raw_data_for_hash).
# ---------------------------------------------------------------------------
def _render_app_info(
    app: Application,
) -> tuple[str, dict[str, Any]]:
    """一、应用信息 — 本地 Application 元数据 (不走 MCP)."""
    raw = {
        "app_id": app.id,
        "app_name": app.app_name or "",
        "app_code": app.app_code or "",
        "apaas_app_id": str(app.apaas_app_id) if app.apaas_app_id else "",
        "description": app.description or "",
        "status": app.status or "",
        "created_at": app.created_at.isoformat() if app.created_at else "",
    }
    md = ["## 一、应用信息", ""]
    md.append(f"- **应用名称**: {raw['app_name']}")
    md.append(f"- **应用编码**: `{raw['app_code']}`")
    if raw["apaas_app_id"]:
        md.append(f"- **apaas 应用 ID**: `{raw['apaas_app_id']}`")
    if raw["description"]:
        md.append(f"- **描述**: {raw['description']}")
    md.append(f"- **状态**: {raw['status']}")
    if raw["created_at"]:
        md.append(f"- **创建时间**: {raw['created_at']}")
    md.append("")
    return "\n".join(md), raw


async def _render_roles(
    env_id: int, apaas_app_id: str
) -> tuple[str, list[dict[str, Any]]]:
    """二、角色与权限 — list_apaas_app_roles."""
    md = ["## 二、角色与权限", ""]
    ok, raw = await _call_tool("list_apaas_app_roles", env_id=env_id, apaas_app_id=apaas_app_id)
    if not ok:
        md.append(f"_拉取失败: {raw.get('error_code')} — {raw.get('message')}_")
        md.append("")
        return "\n".join(md), []
    roles = raw.get("roles") or raw.get("items") or []
    if not isinstance(roles, list) or not roles:
        md.append("_暂无角色_")
        md.append("")
        return "\n".join(md), []
    md.append("| 角色编码 | 角色名称 | 成员数 |")
    md.append("|---------|---------|--------|")
    safe_roles: list[dict[str, Any]] = []
    for r in roles:
        if not isinstance(r, dict):
            continue
        code = str(r.get("role_code") or r.get("code") or "")
        name = str(r.get("role_name") or r.get("name") or "")
        member_count = int(r.get("member_count") or r.get("memberCount") or 0)
        md.append(f"| `{code}` | {name} | {member_count} |")
        safe_roles.append({"code": code, "name": name, "member_count": member_count})
    md.append("")
    return "\n".join(md), safe_roles


async def _render_data_models(
    env_id: int, apaas_app_id: str
) -> tuple[str, list[dict[str, Any]]]:
    """三、数据模型 — list_apaas_app_models(with_fields=True)."""
    md = ["## 三、数据模型", ""]
    ok, raw = await _call_tool(
        "list_apaas_app_models",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
        extra={"with_fields": True},
    )
    if not ok:
        md.append(f"_拉取失败: {raw.get('error_code')} — {raw.get('message')}_")
        md.append("")
        return "\n".join(md), []
    models = raw.get("models") or raw.get("items") or []
    if not isinstance(models, list) or not models:
        md.append("_暂无数据模型_")
        md.append("")
        return "\n".join(md), []
    safe_models: list[dict[str, Any]] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("model_name") or m.get("name") or "")
        m_code = str(m.get("model_code") or m.get("code") or "")
        fields = m.get("fields") or []
        md.append(f"### 3.{len(safe_models) + 1} {m_name} (`{m_code}`)")
        md.append("")
        if isinstance(fields, list) and fields:
            md.append("| 字段名 | 字段编码 | 类型 | 必填 | 说明 |")
            md.append("|--------|---------|------|------|------|")
            safe_fields: list[dict[str, Any]] = []
            for f in fields:
                if not isinstance(f, dict):
                    continue
                f_name = str(f.get("field_name") or f.get("name") or f.get("label") or "")
                f_code = str(f.get("field_code") or f.get("code") or f.get("fieldCode") or "")
                f_type = str(f.get("field_type") or f.get("type") or f.get("fieldType") or "")
                f_required = bool(f.get("required") or f.get("is_required") or False)
                f_desc = str(f.get("field_comment") or f.get("comment") or f.get("description") or "")
                md.append(
                    f"| {f_name} | `{f_code}` | {f_type} | "
                    f"{'是' if f_required else '否'} | {f_desc} |"
                )
                safe_fields.append({
                    "name": f_name,
                    "code": f_code,
                    "type": f_type,
                    "required": f_required,
                    "comment": f_desc,
                })
            safe_models.append({
                "name": m_name, "code": m_code, "fields": safe_fields,
            })
        else:
            md.append("_无字段_")
            safe_models.append({"name": m_name, "code": m_code, "fields": []})
        md.append("")
    return "\n".join(md), safe_models


async def _render_dicts(
    env_id: int, apaas_app_id: str
) -> tuple[str, list[dict[str, Any]]]:
    """四、数据字典 — list_apaas_app_dicts(with_options=True)."""
    md = ["## 四、数据字典", ""]
    ok, raw = await _call_tool(
        "list_apaas_app_dicts",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
        extra={"with_options": True},
    )
    if not ok:
        md.append(f"_拉取失败: {raw.get('error_code')} — {raw.get('message')}_")
        md.append("")
        return "\n".join(md), []
    dicts = raw.get("dicts") or raw.get("items") or []
    if not isinstance(dicts, list) or not dicts:
        md.append("_暂无字典_")
        md.append("")
        return "\n".join(md), []
    safe_dicts: list[dict[str, Any]] = []
    for d in dicts:
        if not isinstance(d, dict):
            continue
        d_name = str(d.get("dict_name") or d.get("name") or "")
        d_code = str(d.get("dict_code") or d.get("code") or "")
        options = d.get("options") or []
        md.append(f"### 4.{len(safe_dicts) + 1} {d_name} (`{d_code}`)")
        md.append("")
        if isinstance(options, list) and options:
            md.append("| 选项编码 | 选项名称 |")
            md.append("|---------|---------|")
            safe_options: list[dict[str, Any]] = []
            for o in options:
                if not isinstance(o, dict):
                    continue
                o_code = str(o.get("option_code") or o.get("code") or "")
                o_name = str(o.get("option_name") or o.get("name") or o.get("label") or "")
                md.append(f"| `{o_code}` | {o_name} |")
                safe_options.append({"code": o_code, "name": o_name})
            safe_dicts.append({"name": d_name, "code": d_code, "options": safe_options})
        else:
            md.append("_无选项_")
            safe_dicts.append({"name": d_name, "code": d_code, "options": []})
        md.append("")
    return "\n".join(md), safe_dicts


async def _render_menus(
    env_id: int, apaas_app_id: str
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """共享: 拉 list_apaas_app_menus, 返 (markdown 章五, full menus list, custom menus).

    章五完整列扁平菜单 (含 GROUP/MODEL/PROCESS/PAGE_CUSTOM_DEV 等所有 type).
    返的 custom menus 给章十 (集成 & 自开发) 复用.
    """
    md = ["## 五、菜单结构", ""]
    ok, raw = await _call_tool(
        "list_apaas_app_menus",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
    )
    if not ok:
        md.append(f"_拉取失败: {raw.get('error_code')} — {raw.get('message')}_")
        md.append("")
        return "\n".join(md), [], []
    menus = raw.get("menus") or raw.get("items") or []
    if not isinstance(menus, list) or not menus:
        md.append("_暂无菜单_")
        md.append("")
        return "\n".join(md), [], []

    md.append("| 菜单名称 | 菜单编码 | 类型 | form_id |")
    md.append("|---------|---------|------|---------|")
    safe_menus: list[dict[str, Any]] = []
    for m in menus:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("menu_name") or m.get("name") or "")
        m_code = str(m.get("menu_code") or m.get("code") or "")
        m_type = str(m.get("menu_type") or "").upper()
        form_id = str(m.get("form_id") or "")
        md.append(f"| {m_name} | `{m_code}` | {m_type} | `{form_id}` |")
        safe_menus.append({
            "name": m_name, "code": m_code, "type": m_type,
            "form_id": form_id,
            "datasource_id": str(m.get("datasource_id") or m.get("datasourceId") or ""),
        })
    md.append("")

    # 章十: 集成 & 自开发 菜单 (custom menus)
    custom_menus = [m for m in safe_menus if m.get("type") == "PAGE_CUSTOM_DEV"]
    return "\n".join(md), safe_menus, custom_menus


def _render_forms_lists(
    all_menus: list[dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]]]:
    """六、表单设计 + 七、列表设计 — 都过滤 menu_type=MODEL."""
    model_menus = [m for m in all_menus if m.get("type") == "MODEL"]

    md6 = ["## 六、表单设计", ""]
    md7 = ["## 七、列表设计", ""]
    if not model_menus:
        md6.append("_暂无表单_")
        md7.append("_暂无列表_")
        md6.append("")
        md7.append("")
        return "\n".join(md6), "\n".join(md7), []

    # 一个 MODEL 菜单 = 1 form + 1 list (一个 form 同时含表单视图 + 列表视图)
    md6.append("| 表单名称 | 菜单编码 | form_id |")
    md6.append("|---------|---------|---------|")
    md7.append("| 列表名称 | 菜单编码 | form_id |")
    md7.append("|---------|---------|---------|")
    for m in model_menus:
        md6.append(f"| {m['name']} | `{m['code']}` | `{m['form_id']}` |")
        md7.append(f"| {m['name']} | `{m['code']}` | `{m['form_id']}` |")
    md6.append("")
    md7.append("")
    return "\n".join(md6), "\n".join(md7), model_menus


async def _render_processes(
    env_id: int, apaas_app_id: str, all_menus: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """八、业务流程 — 优先 list_apaas_app_processes, 兜底 menus 过 PROCESS."""
    md = ["## 八、业务流程", ""]
    ok, raw = await _call_tool(
        "list_apaas_app_processes",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
    )
    if ok:
        procs = raw.get("processes") or raw.get("items") or raw.get("data") or []
        if isinstance(procs, list) and procs:
            md.append("| 流程名称 | 流程编码 |")
            md.append("|---------|---------|")
            safe_procs: list[dict[str, Any]] = []
            for p in procs:
                if not isinstance(p, dict):
                    continue
                p_name = str(p.get("process_name") or p.get("name") or p.get("processName") or "")
                p_code = str(p.get("process_code") or p.get("code") or p.get("processCode") or "")
                md.append(f"| {p_name} | `{p_code}` |")
                safe_procs.append({"name": p_name, "code": p_code})
            md.append("")
            return "\n".join(md), safe_procs

    # 兜底: menus 过 PROCESS
    proc_menus = [m for m in all_menus if m.get("type") == "PROCESS"]
    if not proc_menus:
        md.append("_暂无流程_")
        md.append("")
        return "\n".join(md), []
    md.append("| 流程菜单名称 | 菜单编码 |")
    md.append("|------------|---------|")
    safe_procs = []
    for m in proc_menus:
        md.append(f"| {m['name']} | `{m['code']}` |")
        safe_procs.append({"name": m["name"], "code": m["code"]})
    md.append("")
    return "\n".join(md), safe_procs


async def _render_business_events(
    env_id: int, apaas_app_id: str
) -> tuple[str, list[dict[str, Any]]]:
    """九、业务事件 — list_apaas_business_events (Y 新接通)."""
    md = ["## 九、业务事件", ""]
    ok, raw = await _call_tool(
        "list_apaas_business_events",
        env_id=env_id,
        apaas_app_id=apaas_app_id,
    )
    if not ok:
        md.append(f"_拉取失败: {raw.get('error_code')} — {raw.get('message')}_")
        md.append("")
        return "\n".join(md), []

    # tool 返 {ok, apaas_app_id, data: {table/records: [...], total: N}}
    data = raw.get("data")
    events: list[Any] = []
    if isinstance(data, dict):
        events = data.get("table") or data.get("records") or data.get("items") or []
    elif isinstance(data, list):
        events = data
    if not isinstance(events, list):
        events = []

    if not events:
        md.append("_暂无业务事件_")
        md.append("")
        return "\n".join(md), []

    md.append("| 事件名称 | 事件编码 | 类型 | 状态 |")
    md.append("|---------|---------|------|------|")
    safe_events: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        e_name = str(ev.get("eventName") or ev.get("name") or "")
        e_code = str(ev.get("eventCode") or ev.get("code") or "")
        e_type = str(ev.get("eventType") or ev.get("type") or "")
        e_status = str(ev.get("status") or "")
        md.append(f"| {e_name} | `{e_code}` | {e_type} | {e_status} |")
        safe_events.append({
            "name": e_name, "code": e_code,
            "type": e_type, "status": e_status,
        })
    md.append("")
    return "\n".join(md), safe_events


def _render_integration(
    custom_menus: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """十、集成 & 自开发 — menus 过 PAGE_CUSTOM_DEV."""
    md = ["## 十、集成 & 自开发", ""]
    if not custom_menus:
        md.append("_暂无自开发页面_")
        md.append("")
        return "\n".join(md), []
    md.append("| 页面名称 | 菜单编码 |")
    md.append("|---------|---------|")
    for m in custom_menus:
        md.append(f"| {m['name']} | `{m['code']}` |")
    md.append("")
    return "\n".join(md), custom_menus


def _render_datasources(
    all_menus: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """十一、数据源 — distinct datasource_id 聚合 (复用 section_content 简化逻辑).

    本服务不调 enrich 工具拿 name/type/host/port (留 P5), 只列 distinct id + 引用计数.
    用户要看完整数据源详情走 GET /datasources endpoint.
    """
    md = ["## 十一、数据源", ""]
    # 从 menus 聚 (含 datasource_id 字段)
    agg: dict[str, dict[str, int]] = {}
    for m in all_menus:
        ds_id = str(m.get("datasource_id") or "")
        if not ds_id:
            continue
        slot = agg.setdefault(ds_id, {"menu_count": 0, "model_count": 0})
        slot["menu_count"] += 1

    if not agg:
        md.append("_暂无独立数据源_")
        md.append("")
        return "\n".join(md), []
    md.append("| datasource_id | 被引用菜单数 |")
    md.append("|---------------|-------------|")
    safe_ds: list[dict[str, Any]] = []
    for ds_id, slot in agg.items():
        md.append(f"| `{ds_id}` | {slot['menu_count']} |")
        safe_ds.append({
            "datasource_id": ds_id,
            "menu_count": slot["menu_count"],
        })
    md.append("")
    return "\n".join(md), safe_ds


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
async def generate_spec_markdown(
    db: AsyncSession,
    app_id: int,
) -> tuple[str, str, dict[str, Any]]:
    """生成应用的完整 SPEC.md.

    2026-05-28 加返第 3 项 parsed_sections — 给前端 panel reload 用 (替代 8 个
    /section-content/* fetchSection 并发打 apaas).

    Args:
        db: 异步 session
        app_id: 本地应用 id

    Returns:
        (markdown_str, sections_hash, parsed_sections)
        - markdown_str: 完整 SPEC.md 字符串
        - sections_hash: sha256(sorted JSON of all section raw data) — cache key
        - parsed_sections: 结构化 dict (11 章 raw data) — 给 /spec/parsed 返

    raises:
        ValueError: 应用不存在
    """
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise ValueError(f"application {app_id} 不存在")

    parts: list[str] = []
    raw_sections: dict[str, Any] = {}

    # 文档头
    parts.append(f"# {app.app_name or '未命名应用'} — SPEC")
    parts.append("")
    parts.append(f"_生成时间: {datetime.utcnow().isoformat()}Z_")
    parts.append("")

    # 一、应用信息 (本地)
    md1, raw1 = _render_app_info(app)
    parts.append(md1)
    raw_sections["app_info"] = raw1

    # 应用未部署 — 后 10 章都没法拉, 渲染 placeholder
    if not app.platform_env_id or not app.apaas_app_id:
        for num, title in [
            ("二", "角色与权限"),
            ("三", "数据模型"),
            ("四", "数据字典"),
            ("五", "菜单结构"),
            ("六", "表单设计"),
            ("七", "列表设计"),
            ("八", "业务流程"),
            ("九", "业务事件"),
            ("十", "集成 & 自开发"),
            ("十一", "数据源"),
        ]:
            parts.append(f"## {num}、{title}")
            parts.append("")
            parts.append("_应用未部署到 apaas 平台, 无法拉取真实数据_")
            parts.append("")
        markdown = "\n".join(parts)
        unbound_parsed: dict[str, Any] = {
            "app_info": raw1,
            "_unbound_apaas": True,
        }
        sections_hash = _compute_hash(unbound_parsed)
        return markdown, sections_hash, unbound_parsed

    env_id = app.platform_env_id
    apaas_app_id = str(app.apaas_app_id)

    # 二、角色
    md2, raw2 = await _render_roles(env_id, apaas_app_id)
    parts.append(md2)
    raw_sections["roles"] = raw2

    # 三、数据模型
    md3, raw3 = await _render_data_models(env_id, apaas_app_id)
    parts.append(md3)
    raw_sections["models"] = raw3

    # 四、数据字典
    md4, raw4 = await _render_dicts(env_id, apaas_app_id)
    parts.append(md4)
    raw_sections["dicts"] = raw4

    # 五、菜单 — 同时给六/七/十/十一 复用
    md5, all_menus, custom_menus = await _render_menus(env_id, apaas_app_id)
    parts.append(md5)
    raw_sections["menus"] = all_menus

    # 六、表单 + 七、列表
    md6, md7, model_menus = _render_forms_lists(all_menus)
    parts.append(md6)
    parts.append(md7)
    raw_sections["forms"] = model_menus
    raw_sections["lists"] = model_menus  # 同一份, 不重复 hash

    # 八、业务流程
    md8, raw8 = await _render_processes(env_id, apaas_app_id, all_menus)
    parts.append(md8)
    raw_sections["processes"] = raw8

    # 九、业务事件 (Y 新接通)
    md9, raw9 = await _render_business_events(env_id, apaas_app_id)
    parts.append(md9)
    raw_sections["business_events"] = raw9

    # 十、集成 & 自开发
    md10, raw10 = _render_integration(custom_menus)
    parts.append(md10)
    raw_sections["integration"] = raw10

    # 十一、数据源
    md11, raw11 = _render_datasources(all_menus, raw3)
    parts.append(md11)
    raw_sections["datasources"] = raw11

    markdown = "\n".join(parts)
    sections_hash = _compute_hash(raw_sections)
    return markdown, sections_hash, raw_sections


def _compute_hash(raw: dict[str, Any]) -> str:
    """sha256(sorted JSON) — 任一章 raw data 变就 hash 变.

    用 sort_keys=True + ensure_ascii=False 保稳定. dict / list 嵌套深也覆盖.
    """
    try:
        canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning(f"_compute_hash: JSON 序列化失败 {exc}, 兜底用 repr")
        canonical = repr(raw)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
