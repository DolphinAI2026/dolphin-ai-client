"""SPEC apply — 总览 + 真调 apaas (设计 tab "确认并生成" modal 后端).

URL prefix:  /applications/{app_id}/spec/apply-plan
             /applications/{app_id}/spec/apply

定位 (跟 spec_chat 区分):

    spec_chat                     spec_apply (本模块)
    ────────────────────          ─────────────────────────
    用对话生成 SPEC 草稿           把 SPEC 草稿 propagate 到 apaas
    每条用户消息一次小补丁         一次性消费所有 draft > base 的差异
    SSE 流式回复                   plan: 返一次 JSON; apply: 串行执行
    写 spec_sections.spec_json     真调 apaas API + bump base_version

mockup `docs/internal/design-tab-mockup-2026-05-27.html` 视图 ③ 是设计稿:
    - 4 分组 (数据模型 / 表单 / 菜单 / 流程)
    - 每条 change-item 含 typ chip (+模型 / +字段 / +角色 / ~关系) + desc + mcp_tool
    - 警告 banner "失败自动回滚"
    - foot: 取消 / 仅保存 SPEC / 确认并生成 [N 步]

数据来源:
    SELECT * FROM spec_sections
    WHERE application_id = X AND draft_version > base_version

    每条 spec_sections row 的 spec_json 含 spec_chat 写入的 marker key:
        data_model section  → _added_fields[], _added_dict_options[]
        permission section  → _added_roles[]
        page section        → _added_menus[]
        form section        → _added_forms[] (P6; 当前 spec_chat 不写)
        process section     → _added_processes[]

    本模块把每条 marker → 1 个 change-item, 按 section_type 归组.

W 阶段策略:
    - 真调 apaas (通过 APaaSClient 实例方法; 之前 mock sleep 1.5s 已删)
    - 2 tool 完整接通: create_apaas_app_roles + add_apaas_model_field
    - 6 tool 兜底 NOT_IMPLEMENTED_P6: dict_options / menus / forms / processes
      / business_rules / lists / models
    - 成功的 step 把 spec_sections.base_version = draft_version (avoid 重复 apply)
    - 失败的 step 不动 base_version (草稿仍在, 用户可改后再 apply)
    - 不 abort — 跑完所有 step 返 partial results (用户能看到哪些成 / 哪些败)

P6 留尾的 6 tool 需要 apaas API 复杂参数 (e.g. add_dict_option 需 dict_id 反查 +
displayOrder, save_apaas_process 需完整 BPMN). 接通后改 _dispatch_to_apaas() 的
elif 分支即可.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apaas_client import APaaSClient
from app.database import get_db
from app.models import Application
from app.models.spec_section import SpecSection
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section group / item rendering — 把 spec_sections diff 翻译成 modal 显的 plan
# ---------------------------------------------------------------------------
#
# section_type → group meta. mockup 视图 ③ 4 分组, 这里完整保留 6 类:
#
#   data_model   → 数据模型 group   (含字段 + 字典)
#   form         → 表单 group
#   page         → 菜单 group       (menu = page section)
#   list         → 列表 group       (mockup 没列, 加进来防丢)
#   process      → 流程 group       (含业务规则)
#   permission   → 权限 group       (角色 / 矩阵)
#
# 注: mockup 视图 ③ 把流程含「业务规则」condensed; 我们留 2 个 item 类型 (process + rule)
# 都归到流程 group. mockup 4 个 group label 完全照搬.

_SECTION_GROUP_META: dict[str, dict[str, str]] = {
    "data_model": {
        "title": "数据模型",
        "spec_section_ref": "spec_sections.models",
    },
    "form": {
        "title": "表单",
        "spec_section_ref": "spec_sections.forms",
    },
    "page": {
        "title": "菜单",
        "spec_section_ref": "spec_sections.menus",
    },
    "list": {
        "title": "列表",
        "spec_section_ref": "spec_sections.lists",
    },
    "process": {
        "title": "流程",
        "spec_section_ref": "spec_sections.processes",
    },
    "permission": {
        "title": "权限",
        "spec_section_ref": "spec_sections.roles",
    },
}

# group 显示顺序 — 跟 mockup 视图 ③ 一致 (数据模型 → 表单 → 菜单 → 流程 → 列表 → 权限).
_GROUP_ORDER: tuple[str, ...] = (
    "data_model",
    "form",
    "page",
    "process",
    "list",
    "permission",
)


def _items_from_section(section_type: str, spec_json: dict) -> list[dict[str, str]]:
    """单个 spec_sections row 的 spec_json → change-item 列表.

    每条 item: { typ, desc, mcp_tool }
        typ      — 显示在 chip (+字段 / +角色 / ~关系), 颜色由 typ 前缀决定 (add/del/mod)
        desc     — 给人读的描述 (一句话, 含核心实体名 bold 标 — frontend 用 <strong>)
        mcp_tool — 真调的 apaas tool 名 (mono 字体显示)

    spec_json 是 spec_chat 累积 merge 出的结果, 用 marker key 取增量:
        _added_fields[]        — data_model
        _added_dict_options[]  — data_model
        _added_roles[]         — permission
        _added_menus[]         — page
        _added_processes[]     — process

    如果 spec_json 没 marker, 退回到 spec_sections 整体作 "整 section 重建" 一条
    (rare path — base_version=0 init 时没用 spec_chat 改, 直接 spec_json 全量).
    """
    items: list[dict[str, str]] = []

    if not isinstance(spec_json, dict):
        return items

    if section_type == "data_model":
        for f in spec_json.get("_added_fields") or []:
            name = (f.get("name") if isinstance(f, dict) else None) or "未命名字段"
            items.append(
                {
                    "typ": "+字段",
                    "typ_color": "add",
                    "desc": f"在数据模型加字段 <strong>{name}</strong>",
                    "mcp_tool": "add_apaas_model_field",
                }
            )
        for o in spec_json.get("_added_dict_options") or []:
            name = (o.get("name") if isinstance(o, dict) else None) or "未命名选项"
            items.append(
                {
                    "typ": "+字典",
                    "typ_color": "add",
                    "desc": f"加字典选项 <strong>{name}</strong>",
                    "mcp_tool": "add_apaas_dict_option",
                }
            )

    elif section_type == "form":
        for f in spec_json.get("_added_forms") or []:
            name = (f.get("name") if isinstance(f, dict) else None) or "未命名表单"
            items.append(
                {
                    "typ": "+表单",
                    "typ_color": "add",
                    "desc": f"新建表单 <strong>{name}</strong>",
                    "mcp_tool": "create_apaas_form",
                }
            )

    elif section_type == "page":
        for m in spec_json.get("_added_menus") or []:
            name = (m.get("name") if isinstance(m, dict) else None) or "未命名菜单"
            items.append(
                {
                    "typ": "+菜单",
                    "typ_color": "add",
                    "desc": f"加菜单 <strong>{name}</strong>",
                    "mcp_tool": "create_apaas_menu",
                }
            )

    elif section_type == "process":
        for p in spec_json.get("_added_processes") or []:
            name = (p.get("name") if isinstance(p, dict) else None) or "未命名流程"
            items.append(
                {
                    "typ": "+流程",
                    "typ_color": "add",
                    "desc": f"新建流程 <strong>{name}</strong>",
                    "mcp_tool": "save_apaas_process",
                }
            )
        for r in spec_json.get("_added_business_rules") or []:
            name = (r.get("name") if isinstance(r, dict) else None) or "未命名规则"
            items.append(
                {
                    "typ": "+规则",
                    "typ_color": "add",
                    "desc": f"加业务规则 <strong>{name}</strong>",
                    "mcp_tool": "save_apaas_business_rule",
                }
            )

    elif section_type == "permission":
        for r in spec_json.get("_added_roles") or []:
            name = (r.get("name") if isinstance(r, dict) else None) or "未命名角色"
            items.append(
                {
                    "typ": "+角色",
                    "typ_color": "add",
                    "desc": f"加角色 <strong>{name}</strong>",
                    "mcp_tool": "create_apaas_app_roles",
                }
            )

    elif section_type == "list":
        for l in spec_json.get("_added_lists") or []:
            name = (l.get("name") if isinstance(l, dict) else None) or "未命名列表"
            items.append(
                {
                    "typ": "+列表",
                    "typ_color": "add",
                    "desc": f"新建列表 <strong>{name}</strong>",
                    "mcp_tool": "create_apaas_list",
                }
            )

    # Fallback — section 有 draft 但没 marker (rare, 用户直接编辑 spec_json).
    # 给一条 placeholder item 让用户知道这个 section 有改动, 但工具未明确.
    if not items and isinstance(spec_json, dict) and spec_json:
        items.append(
            {
                "typ": "~改动",
                "typ_color": "mod",
                "desc": f"section <strong>{section_type}</strong> 有未分类草稿改动 (无 marker)",
                "mcp_tool": f"apply_apaas_{section_type}",
            }
        )

    return items


async def _collect_drafted_sections(
    db: AsyncSession, app_id: int
) -> list[SpecSection]:
    """读所有 draft_version > base_version 的 spec_sections row.

    P2 后再考虑加 `WHERE last_applied_at IS NULL OR updated_at > last_applied_at`
    防重复 apply. 当前用 base_version bump 防重复 (apply 成功 → base = draft).
    """
    result = await db.execute(
        select(SpecSection)
        .where(SpecSection.application_id == app_id)
        .where(SpecSection.draft_version > SpecSection.base_version)
        .order_by(SpecSection.section_type, SpecSection.id)
    )
    return list(result.scalars().all())


def _parse_spec_json(spec_section: SpecSection) -> dict[str, Any]:
    """spec_sections.spec_json (text col) → dict."""
    raw = spec_section.spec_json
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _build_plan(rows: list[SpecSection]) -> dict[str, Any]:
    """spec_sections rows → modal 显的 plan 结构 (跟 mockup 视图 ③ 对齐).

    返:
        {
          groups: [
            { section_type, title, spec_section_ref, items: [{typ, desc, mcp_tool, typ_color}] }
          ],
          total_steps: N,
          estimated_seconds: N * 2,
        }

    group 按 _GROUP_ORDER 排; 空 group (没 item) 不返.
    """
    # 收集每 section_type 的所有 item — 多个 row (e.g. data_model.main + data_model.dict) 合并
    items_by_type: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        spec_json = _parse_spec_json(row)
        items = _items_from_section(row.section_type, spec_json)
        if not items:
            continue
        items_by_type.setdefault(row.section_type, []).extend(items)

    groups: list[dict[str, Any]] = []
    total = 0
    for stype in _GROUP_ORDER:
        items = items_by_type.get(stype) or []
        if not items:
            continue
        meta = _SECTION_GROUP_META.get(stype) or {}
        groups.append(
            {
                "section_type": stype,
                "title": meta.get("title") or stype,
                "spec_section_ref": meta.get("spec_section_ref")
                or f"spec_sections.{stype}",
                "items": items,
            }
        )
        total += len(items)

    # estimated_seconds: 每步 ~2 秒 (mockup "预计 ~12 秒" 6 步 = 12s = 2 秒/步).
    return {
        "groups": groups,
        "total_steps": total,
        "estimated_seconds": total * 2,
    }


# ---------------------------------------------------------------------------
# Endpoint 1 — GET /spec/apply-plan
# ---------------------------------------------------------------------------


@router.get("/{app_id}/spec/apply-plan")
async def get_apply_plan(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """返 modal 显的 plan — 不真执行, 只列改动 + 对应 MCP 工具.

    flow:
      1. 权限校验 (跟 spec_chat 同 pattern)
      2. 读 spec_sections WHERE draft_version > base_version
      3. 每 row 的 spec_json marker key 翻译成 change-item
      4. 按 section_type 归组, 跟 mockup 视图 ③ 4 分组对齐

    返结构:
      {
        ok: true,
        app_id: 13,
        groups: [
          {
            section_type: "data_model",
            title: "数据模型",
            spec_section_ref: "spec_sections.models",
            items: [
              { typ, typ_color, desc, mcp_tool }
            ]
          }
        ],
        total_steps: 6,
        estimated_seconds: 12,
      }

    空 (没草稿改动): groups=[], total_steps=0 — frontend 显 "没改动" 空态.
    """
    # 1. 权限
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    # 2-4. 拉 draft + 建 plan
    rows = await _collect_drafted_sections(db, app_id)
    plan = _build_plan(rows)

    return {
        "ok": True,
        "app_id": app_id,
        **plan,
    }


# ---------------------------------------------------------------------------
# Endpoint 2 — POST /spec/apply
# ---------------------------------------------------------------------------


class SpecApplyBody(BaseModel):
    """apply 入参.

    dry_run: 默认 False — 真调 apaas. 为 True 时仍走 plan 收集逻辑但所有 step 返
    {ok: True, mode: 'dry-run'} 不调底层 client (留给 frontend QA 自测 + 排查
    plan 翻译逻辑).
    """

    dry_run: bool = False


def _section_match_for_item(
    rows: list[SpecSection], section_type: str, mcp_tool: str
) -> Optional[SpecSection]:
    """从 rows 里找跟 (section_type, mcp_tool) 匹配的第一条 spec_section.

    用于 _execute_step 取草稿 marker. 同一 section_type 多 row 时 (e.g.
    data_model.main + data_model.dict) 取第一条有对应 marker 的.

    匹配规则 — mcp_tool 反推 marker key:
        add_apaas_model_field  → _added_fields
        add_apaas_dict_option  → _added_dict_options
        create_apaas_app_roles → _added_roles
        create_apaas_menu      → _added_menus
        ...
    """
    marker_by_tool = {
        "add_apaas_model_field": "_added_fields",
        "add_apaas_dict_option": "_added_dict_options",
        "create_apaas_app_roles": "_added_roles",
        "create_apaas_menu": "_added_menus",
        "save_apaas_process": "_added_processes",
        "save_apaas_business_rule": "_added_business_rules",
        "create_apaas_form": "_added_forms",
        "create_apaas_list": "_added_lists",
    }
    marker = marker_by_tool.get(mcp_tool)
    for row in rows:
        if row.section_type != section_type:
            continue
        if not marker:
            return row
        spec_json = _parse_spec_json(row)
        if spec_json.get(marker):
            return row
    # 兜底 — 没匹配 marker 也返第一个 section_type 一致的 row (P6 fallback).
    for row in rows:
        if row.section_type == section_type:
            return row
    return None


async def _dispatch_to_apaas(
    client: APaaSClient,
    apaas_app_id: str,
    item: dict[str, str],
    spec_section: SpecSection,
) -> dict[str, Any]:
    """真调 apaas — 按 mcp_tool 分支.

    返:
        {ok: bool, mcp_tool, ...result-specific-fields}
        失败时含 error_code + message + (optional) details.

    完整接通的 2 个 tool:
        - create_apaas_app_roles
        - add_apaas_model_field (多字段循环)

    P6 留尾的 6 个 tool:
        - add_apaas_dict_option (需 dict_id 反查, 用 client.query_dicts)
        - create_apaas_menu (需 form_id + datasource 反查)
        - save_apaas_process (需完整 BPMN 翻译)
        - save_apaas_business_rule (apaas 端 schema 未探完)
        - create_apaas_form (需完整 formConfig)
        - create_apaas_list (apaas 列表配置 schema)
        - create_apaas_app_model (需完整 modelData)
    """
    tool_name = item.get("mcp_tool") or ""
    spec_json = _parse_spec_json(spec_section)

    # ---- 1. 角色: roles 直接是 (code, name) tuple list ----
    if tool_name == "create_apaas_app_roles":
        roles_raw = spec_json.get("_added_roles") or []
        roles_payload = []
        for r in roles_raw:
            if not isinstance(r, dict):
                continue
            code = r.get("code") or r.get("role_code")
            name = r.get("name") or r.get("role_name")
            if not code or not name:
                continue
            roles_payload.append({"roleCode": code, "roleName": name})
        if not roles_payload:
            return {
                "ok": False,
                "mcp_tool": tool_name,
                "error_code": "EMPTY_ROLES",
                "message": "草稿无角色待 apply (缺 name / code)",
            }
        try:
            result = await client.create_roles(apaas_app_id, roles_payload)
        except Exception as exc:
            logger.exception("create_apaas_app_roles failed apaas_app_id=%s", apaas_app_id)
            return {
                "ok": False,
                "mcp_tool": tool_name,
                "error_code": "APAAS_CALL_FAILED",
                "message": str(exc),
            }
        return {
            "ok": True,
            "mcp_tool": tool_name,
            "applied_count": len(roles_payload),
            "raw_result": result if isinstance(result, dict) else {"data": result},
        }

    # ---- 2. 字段: 反查 model_id + 多字段循环 ----
    if tool_name == "add_apaas_model_field":
        fields_raw = spec_json.get("_added_fields") or []
        if not fields_raw:
            return {
                "ok": False,
                "mcp_tool": tool_name,
                "error_code": "EMPTY_FIELDS",
                "message": "草稿无字段待 apply",
            }

        # 拉 apaas model 列表, 反查 model_id by section_key (e.g. 'main' = 主表)
        # 或第一个 model 作 fallback.
        try:
            apaas_models = await client.query_models(apaas_app_id)
        except Exception as exc:
            logger.exception("query_models failed apaas_app_id=%s", apaas_app_id)
            return {
                "ok": False,
                "mcp_tool": tool_name,
                "error_code": "MODEL_LIST_FAIL",
                "message": f"无法拉取 apaas 模型列表: {exc}",
            }
        if not apaas_models:
            return {
                "ok": False,
                "mcp_tool": tool_name,
                "error_code": "MODEL_NOT_FOUND",
                "message": "apaas 应用下没数据模型 (先建模再加字段)",
            }

        section_key = spec_section.section_key or ""
        target_model = next(
            (
                m for m in apaas_models
                if str(m.get("modelCode") or "") == section_key
            ),
            None,
        )
        if not target_model:
            target_model = apaas_models[0]
            logger.info(
                "add_apaas_model_field: section_key=%r 没对应 modelCode, 用第一个 model %s",
                section_key,
                target_model.get("modelCode"),
            )

        model_id = str(target_model.get("id") or target_model.get("modelId") or "")
        model_code = str(target_model.get("modelCode") or target_model.get("code") or "")
        if not model_id:
            return {
                "ok": False,
                "mcp_tool": tool_name,
                "error_code": "MODEL_ID_MISSING",
                "message": f"apaas model 没 id: code={model_code}",
            }

        # 多字段循环 — apaas 端 modelField/add 一次只加 1 个
        details: list[dict[str, Any]] = []
        for f in fields_raw:
            if not isinstance(f, dict):
                continue
            field_code = f.get("code") or f.get("field_code") or ""
            field_name = f.get("name") or f.get("field_name") or ""
            if not field_code or not field_name:
                details.append({
                    "field": field_name or field_code or "(未命名)",
                    "ok": False,
                    "error_code": "MISSING_FIELD_NAME_OR_CODE",
                })
                continue

            field_payload = {
                "appId": apaas_app_id,
                "modelId": model_id,
                "dataModelId": model_id,
                "modelCode": model_code,
                "fieldCode": field_code,
                "fieldName": field_name,
                "fieldType": (f.get("type") or "STRING").upper(),
                "fieldStatus": "ENABLE",
                "fieldComment": f.get("description") or f.get("comment") or "",
            }
            max_length = f.get("max_length") or f.get("maxLength")
            if max_length:
                field_payload["maxLength"] = int(max_length)

            try:
                # 用底层 _post_resource 调 /xdap-app/modelField/add (apaas_client 没暴露
                # add_field 方法; 直接复用 _post_resource pattern, 跟 incremental_executor
                # 一致).
                result = await client._post_resource(  # noqa: SLF001
                    "/modelField/add", field_payload, apaas_app_id
                )
                details.append({
                    "field": field_name,
                    "code": field_code,
                    "ok": True,
                    "raw_result": result if isinstance(result, (dict, list)) else None,
                })
            except Exception as exc:
                logger.exception(
                    "add_apaas_model_field failed apaas_app_id=%s code=%s",
                    apaas_app_id, field_code,
                )
                details.append({
                    "field": field_name,
                    "code": field_code,
                    "ok": False,
                    "error_code": "APAAS_CALL_FAILED",
                    "message": str(exc),
                })

        all_ok = bool(details) and all(d.get("ok") for d in details)
        return {
            "ok": all_ok,
            "mcp_tool": tool_name,
            "model_id": model_id,
            "model_code": model_code,
            "details": details,
        }

    # ---- 3. P6 留尾的 6 个 tool — 都返 NOT_IMPLEMENTED_P6 ----
    not_impl_tools = {
        "add_apaas_dict_option",      # 需 dict_id 反查 + displayOrder 累计
        "create_apaas_menu",          # 需 form_id + datasource 反查
        "save_apaas_process",         # 需完整 BPMN 翻译 (incremental_executor 有 logic 但复杂)
        "save_apaas_business_rule",   # apaas 端 schema 未探完
        "create_apaas_form",          # 需完整 formConfig
        "create_apaas_list",          # apaas 列表配置 schema
        "create_apaas_app_model",     # 需完整 modelData
    }
    if tool_name in not_impl_tools:
        return {
            "ok": False,
            "mcp_tool": tool_name,
            "error_code": "NOT_IMPLEMENTED_P6",
            "message": f"{tool_name} P6 接通中 — 当前 W 阶段只接通 roles + fields",
        }

    # ---- 4. 未识别工具 ----
    return {
        "ok": False,
        "mcp_tool": tool_name,
        "error_code": "UNKNOWN_TOOL",
        "message": f"未识别 mcp_tool: {tool_name}",
    }


async def _execute_step(
    db: AsyncSession,
    client: Optional[APaaSClient],
    apaas_app_id: Optional[str],
    rows: list[SpecSection],
    item: dict[str, str],
    section_type: str,
    dry_run: bool,
) -> dict[str, Any]:
    """执行单步 — dispatch 到 _dispatch_to_apaas, 失败返 ok:False + error_code.

    dry_run=True: 不调 apaas, 直接返 {ok: True, mode: 'dry-run'}.

    成功逻辑分两层:
      _dispatch_to_apaas 返 ok=True → 上游 apply_spec 把对应 spec_section 的
      base_version bump 成 draft_version (在 apply_spec 主循环里集中做, 不在这里).
    """
    tool_name = item.get("mcp_tool") or ""

    if dry_run:
        return {
            "ok": True,
            "mcp_tool": tool_name,
            "desc": item.get("desc"),
            "mode": "dry-run",
        }

    # 不是 dry-run 就要有 client + apaas_app_id
    if not client or not apaas_app_id:
        return {
            "ok": False,
            "mcp_tool": tool_name,
            "error_code": "APP_NOT_DEPLOYED",
            "message": "应用未部署到 apaas — 无 client / apaas_app_id",
        }

    spec_section = _section_match_for_item(rows, section_type, tool_name)
    if not spec_section:
        return {
            "ok": False,
            "mcp_tool": tool_name,
            "error_code": "SPEC_SECTION_NOT_FOUND",
            "message": f"找不到 section_type={section_type} 的草稿 (apply 进行中 spec 被删?)",
        }

    result = await _dispatch_to_apaas(client, apaas_app_id, item, spec_section)
    result["desc"] = item.get("desc")
    result["mode"] = "live"
    # 把 section_type / section_key 透传给上游 — bump base_version 时用
    result["_section_type"] = section_type
    result["_section_id"] = spec_section.id
    return result


@router.post("/{app_id}/spec/apply")
async def apply_spec(
    app_id: int,
    body: SpecApplyBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """串行执行 apply plan — 真调 apaas (除非 body.dry_run=True).

    flow:
      1. 权限校验 + 拉应用
      2. 拉 spec_sections plan (复用 get_apply_plan 逻辑)
      3. 准备 APaaSClient (非 dry-run 时)
      4. 串行跑每个 item _execute_step → _dispatch_to_apaas
      5. 成功的 step 把对应 spec_section.base_version = draft_version (单 section 全
         step 成功才 bump — 防 P6 部分 NOT_IMPLEMENTED step 误判成功)
      6. 返 {ok, applied_steps, failed_steps, total_steps, mode, results}

    返结构:
      {
        ok: true,
        app_id: 13,
        mode: 'live' | 'dry-run',
        total_steps: 6,
        applied_steps: 4,
        failed_steps: 2,
        results: [
          { ok, mcp_tool, desc, mode, raw_result? / details? / error_code? }
        ],
        synced_sections: ["data_model:main"],  # 哪些 section 真 bump base_version
        duration_ms: 9023,
      }

    错误策略: 不 abort — 跑完所有 step. 失败的 step 不 bump base_version, 草稿仍在.
    用户在 SPEC 设计 tab 里能继续改 + 重 apply.
    """
    # 1. 权限 + 拉应用
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    # 2. 拉 plan + rows (rows 用于 _execute_step 反查 spec_json)
    rows = await _collect_drafted_sections(db, app_id)
    plan = _build_plan(rows)

    if plan["total_steps"] == 0:
        return {
            "ok": True,
            "app_id": app_id,
            "mode": "dry-run" if body.dry_run else "live",
            "total_steps": 0,
            "applied_steps": 0,
            "failed_steps": 0,
            "results": [],
            "synced_sections": [],
            "duration_ms": 0,
            "message": "没有未 apply 的 SPEC 草稿改动",
        }

    # 3. 准备 APaaSClient (非 dry-run)
    client: Optional[APaaSClient] = None
    apaas_app_id: Optional[str] = None
    if not body.dry_run:
        if not app.apaas_app_id:
            raise HTTPException(
                status_code=400,
                detail="应用未关联 apaas 应用 (apaas_app_id 为空), 无法 apply. 先在生成 tab 部署.",
            )
        apaas_app_id = str(app.apaas_app_id)
        try:
            from app.routes.incremental_update import _get_platform_client_for_app
            client = await _get_platform_client_for_app(app, ctx.user, db)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("准备 apaas client 失败 app_id=%s", app_id)
            raise HTTPException(
                status_code=400,
                detail=f"无法连接 apaas 平台: {exc}",
            )

    # 4. 串行执行 — 同时统计每个 spec_section 的 step 成败 (全成才 bump base_version)
    start = datetime.utcnow()
    results: list[dict[str, Any]] = []
    applied = 0
    failed = 0
    # section_id → {"all_ok": bool, "any_step": bool} — 跑完一节才决定 bump
    section_step_status: dict[int, dict[str, Any]] = {}

    for group in plan["groups"]:
        section_type = group["section_type"]
        for item in group["items"]:
            try:
                step_result = await _execute_step(
                    db, client, apaas_app_id, rows, item, section_type, body.dry_run,
                )
            except Exception as exc:
                # _execute_step 自己 catch 一般不漏出来. 兜底 — 不让一条 step 崩整批.
                logger.exception(
                    "spec_apply: step crashed app_id=%s tool=%s",
                    app_id,
                    item.get("mcp_tool"),
                )
                step_result = {
                    "ok": False,
                    "mcp_tool": item.get("mcp_tool"),
                    "desc": item.get("desc"),
                    "error_code": "STEP_CRASHED",
                    "message": str(exc),
                    "mode": "live",
                }

            # 把 _execute_step 留的 _section_id / _section_type 内部字段 pop 掉 (不返客户端)
            step_result.pop("_section_type", None)
            step_result.pop("_section_id", None)

            # 跟踪 section bump base_version 用 — 同一 section 全 step 成才 bump
            sec = _section_match_for_item(rows, section_type, item.get("mcp_tool") or "")
            if sec:
                track = section_step_status.setdefault(
                    sec.id,
                    {"all_ok": True, "any_step": False, "section": sec},
                )
                track["any_step"] = True
                if not step_result.get("ok"):
                    track["all_ok"] = False

            results.append(step_result)
            if step_result.get("ok"):
                applied += 1
            else:
                failed += 1

    # 5. bump base_version — 仅当该 section 全 step 成功 + 非 dry-run
    synced_sections: list[str] = []
    if not body.dry_run:
        for sid, track in section_step_status.items():
            if not track["any_step"] or not track["all_ok"]:
                continue
            sec: SpecSection = track["section"]
            old_base = sec.base_version
            sec.base_version = sec.draft_version
            sec.last_applied_at = datetime.utcnow()
            synced_sections.append(f"{sec.section_type}:{sec.section_key}")
            logger.info(
                "spec_apply: bumped base_version app_id=%s section=%s:%s %d→%d",
                app_id, sec.section_type, sec.section_key,
                old_base, sec.draft_version,
            )
        if synced_sections:
            await db.commit()

    # 6. SPEC 版本快照 — Y 阶段加, 不影响 dry-run (dry-run 没改 db 状态).
    #
    # 即使 failed_steps > 0 也写一行 SpecAppliedVersion (审计用), 但 is_active=False;
    # 全成时新行 is_active=True, 老 active 行降 False.
    #
    # version_label 规则 — 查最新 active 行 minor-bump (v1.0 → v1.1):
    #   - 没历史 → v1.0
    #   - v1.X → v1.(X+1)
    #   - v1.X.Y → v1.X.(Y+1) (回滚专用 patch-bump, 这里不走)
    #
    # 同时 invalidate SpecDocument cache — 强 reset hash 让下次 GET /spec/markdown
    # 重新生成 (因为 base_version bump 后 spec_sections 状态变了, raw apaas 也大概率变).
    spec_version_id: Optional[int] = None
    version_label: Optional[str] = None
    if not body.dry_run:
        try:
            spec_version_id, version_label = await _create_spec_version_snapshot(
                db=db,
                app=app,
                user_id=ctx.user.id,
                total_steps=plan["total_steps"],
                applied_steps=applied,
                failed_steps=failed,
                results=results,
            )
        except Exception as exc:  # noqa: BLE001 — 快照失败不挡 apply 主结果
            logger.exception(
                "spec_apply: 创建 SpecAppliedVersion 失败 (非致命) app_id=%s: %s",
                app_id, exc,
            )

        # 7. apply 后 invalidate section-content TTL 缓存 — 让前端 reload 拿新 apaas 状态.
        # apaas 真改了后老缓存 stale, 不清的话用户看到的还是改前的资源列表.
        if apaas_app_id:
            try:
                from app.routes.applications.section_content import (
                    invalidate_section_cache_for_app,
                )
                cleared = invalidate_section_cache_for_app(apaas_app_id)
                logger.info(
                    "spec_apply: cleared %d section-content cache entries for apaas_app_id=%s",
                    cleared, apaas_app_id,
                )
            except Exception as exc:  # noqa: BLE001 — 缓存清失败不挡 apply 主结果
                logger.warning("spec_apply: section-content cache invalidate failed: %s", exc)

    duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

    return {
        "ok": failed == 0,
        "app_id": app_id,
        "mode": "dry-run" if body.dry_run else "live",
        "total_steps": plan["total_steps"],
        "applied_steps": applied,
        "failed_steps": failed,
        "results": results,
        "synced_sections": synced_sections,
        "duration_ms": duration_ms,
        "spec_version_id": spec_version_id,
        "version_label": version_label,
    }


# ---------------------------------------------------------------------------
# Snapshot helper — apply_spec 末尾调
# ---------------------------------------------------------------------------
async def _compute_next_version_label(db: AsyncSession, app_id: int) -> str:
    """查最新 active SpecAppliedVersion 算 next minor-bump.

    规则:
      - 没历史 → "v1.0"
      - "v1.X" → "v1.(X+1)"
      - "v1.X.Y" → "v1.(X+1)" (patch 标记忽略, 走 minor-bump)
      - "vN" / 其他 → "v(N+1).0"
    """
    from app.models.spec_applied_version import SpecAppliedVersion

    q = await db.execute(
        select(SpecAppliedVersion)
        .where(SpecAppliedVersion.application_id == app_id)
        .where(SpecAppliedVersion.is_active.is_(True))
        .order_by(SpecAppliedVersion.applied_at.desc())
        .limit(1)
    )
    latest = q.scalar_one_or_none()
    if not latest:
        # 也查 inactive 兜底 (避免重 v1.0 撞 unique)
        q2 = await db.execute(
            select(SpecAppliedVersion)
            .where(SpecAppliedVersion.application_id == app_id)
            .order_by(SpecAppliedVersion.applied_at.desc())
            .limit(1)
        )
        latest = q2.scalar_one_or_none()

    if not latest:
        return "v1.0"

    label = (latest.version_label or "").lstrip("v").lstrip("V")
    parts = label.split(".")
    try:
        if len(parts) >= 2:
            major = int(parts[0])
            minor = int(parts[1])
            return f"v{major}.{minor + 1}"
        return f"v{int(parts[0]) + 1}.0"
    except (ValueError, IndexError):
        # 非标准 label 兜底
        return f"v1.{int(datetime.utcnow().timestamp())}"


async def _create_spec_version_snapshot(
    db: AsyncSession,
    app: Application,
    user_id: int,
    total_steps: int,
    applied_steps: int,
    failed_steps: int,
    results: list[dict[str, Any]],
) -> tuple[int, str]:
    """新建一行 SpecAppliedVersion + invalidate SpecDocument cache.

    Returns: (version_id, version_label).

    全成 (failed=0) → is_active=True, 老 active 降 False.
    部分失败 (failed>0) → is_active=False, 老 active 不动.
    """
    from app.models.spec_applied_version import SpecAppliedVersion
    from app.models.spec_document import SpecDocument

    version_label = await _compute_next_version_label(db, app.id)

    # 收集所有 spec_sections 行 → sections_snapshot
    sec_q = await db.execute(
        select(SpecSection).where(SpecSection.application_id == app.id)
    )
    sec_rows = list(sec_q.scalars().all())
    sections_payload: list[dict[str, Any]] = []
    for sec in sec_rows:
        try:
            spec_json_parsed = json.loads(sec.spec_json) if sec.spec_json else {}
        except (json.JSONDecodeError, TypeError):
            spec_json_parsed = {}
        sections_payload.append({
            "id": sec.id,
            "section_type": sec.section_type,
            "section_key": sec.section_key,
            "spec_json": spec_json_parsed,
            "base_version": sec.base_version,
            "draft_version": sec.draft_version,
            "last_applied_at": (
                sec.last_applied_at.isoformat() if sec.last_applied_at else None
            ),
        })

    # 生成完整 SPEC.md 快照 — 调 generate_spec_markdown (capture apaas 实时状态)
    markdown_snapshot: Optional[str] = None
    try:
        from app.services.spec_markdown_generator import generate_spec_markdown
        # 2026-05-28: generator 返 3 元组 (md, hash, parsed_sections), 这里只要 md.
        markdown_snapshot, _hash, _parsed = await generate_spec_markdown(db, app.id)
    except Exception as exc:  # noqa: BLE001 — markdown 生成失败不挡 snapshot 落库
        logger.warning(
            "snapshot: generate_spec_markdown 失败 app_id=%s: %s", app.id, exc,
        )

    sections_snapshot = {
        "sections": sections_payload,
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "app_meta": {
            "app_name": app.app_name,
            "app_code": app.app_code,
            "apaas_app_id": str(app.apaas_app_id) if app.apaas_app_id else None,
        },
    }

    is_active_new = failed_steps == 0
    if is_active_new:
        # 老的 active 行全降 False
        old_active_q = await db.execute(
            select(SpecAppliedVersion).where(
                SpecAppliedVersion.application_id == app.id,
                SpecAppliedVersion.is_active.is_(True),
            )
        )
        for old in old_active_q.scalars().all():
            old.is_active = False

    new_row = SpecAppliedVersion(
        application_id=app.id,
        version_label=version_label,
        applied_by_user_id=user_id,
        sections_snapshot=sections_snapshot,
        markdown_snapshot=markdown_snapshot,
        total_steps=total_steps,
        applied_steps=applied_steps,
        failed_steps=failed_steps,
        apply_results=results,
        is_active=is_active_new,
    )
    db.add(new_row)

    # Invalidate SpecDocument cache — 把 hash 清空让下次 GET /spec/markdown 重生成.
    # (markdown_snapshot 我们已写 SpecAppliedVersion, 这里 SpecDocument cache 也更新一致.)
    cache_q = await db.execute(
        select(SpecDocument).where(SpecDocument.application_id == app.id)
    )
    cached = cache_q.scalar_one_or_none()
    if cached:
        # 强 invalidate 让下次 read 重算 hash — 清 hash + markdown + parsed_sections
        # 三处, 任一不空就不会触发 cache miss → 必须全清.
        cached.sections_hash = ""
        cached.markdown_content = ""
        cached.parsed_sections_json = "{}"

    await db.commit()
    await db.refresh(new_row)

    logger.info(
        "spec_apply snapshot: app_id=%s version=%s id=%s is_active=%s "
        "(total=%s applied=%s failed=%s)",
        app.id, version_label, new_row.id, is_active_new,
        total_steps, applied_steps, failed_steps,
    )
    return new_row.id, version_label
