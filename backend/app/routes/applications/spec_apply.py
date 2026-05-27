"""SPEC apply — 总览 + 模拟执行 (设计 tab "确认并生成" modal 后端).

URL prefix:  /applications/{app_id}/spec/apply-plan
             /applications/{app_id}/spec/apply

定位 (跟 spec_chat 区分):

    spec_chat                     spec_apply (本模块)
    ────────────────────          ─────────────────────────
    用对话生成 SPEC 草稿           把 SPEC 草稿 propagate 到 apaas
    每条用户消息一次小补丁         一次性消费所有 draft > base 的差异
    SSE 流式回复                   plan: 返一次 JSON; apply: 串行执行
    写 spec_sections.spec_json     dry-run: 不真调 MCP; P5: 串调 MCP

mockup `docs/internal/design-tab-mockup-2026-05-27.html` 视图 ③ 是设计稿:
    - 4 分组 (数据模型 / 表单 / 菜单 / 流程)
    - 每条 change-item 含 typ chip (+模型 / +字段 / +角色 / ~关系) + desc + mcp_tool
    - 警告 banner "失败自动回滚" (P5 真接 MCP 时落地)
    - foot: 取消 / 仅保存 SPEC / 确认并生成 [N 步]

数据来源:
    SELECT * FROM spec_sections
    WHERE application_id = X AND draft_version > base_version

    每条 spec_sections row 的 spec_json 含 spec_chat 写入的 marker key:
        data_model section  → _added_fields[], _added_dict_options[]
        permission section  → _added_roles[]
        page section        → _added_menus[]
        form section        → _added_forms[] (P5; 当前 spec_chat 不写, 用整 spec_json 兜底)
        process section     → _added_processes[]

    本模块把每条 marker → 1 个 change-item, 按 section_type 归组.

MVP 策略 (用户决策):
    - apply endpoint = dry-run, sleep 1.5s * N, 不真调 MCP
    - 接通 MCP 真调时改 _execute_step() 函数 (P5 接入点已标注)
    - 不写 last_applied_at (因为没真 apply); 不动 spec_sections row

可选: SSE 进度流 — 当前为一次性 dict 返 (MVP 简单足够). P5 可改 SSE 让前端实时
显进度. 留 stub 标记位 `_use_sse=False`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        mcp_tool — P5 接通时真调的 MCP 工具名 (mono 字体显示)

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
    防重复 apply. MVP dry-run 不动 last_applied_at, 不需要.
    """
    result = await db.execute(
        select(SpecSection)
        .where(SpecSection.application_id == app_id)
        .where(SpecSection.draft_version > SpecSection.base_version)
        .order_by(SpecSection.section_type, SpecSection.id)
    )
    return list(result.scalars().all())


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
        try:
            spec_json = json.loads(row.spec_json) if row.spec_json else {}
        except json.JSONDecodeError:
            spec_json = {}
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
    """MVP 不收参 — 直接按当前 draft 状态 apply.

    P5 加: dry_run: bool / step_filter: list[str] / abort_on_error: bool.
    """

    dry_run: bool = True  # MVP 强制 true, 等 P5 真接 MCP 后默认 false


async def _execute_step(
    db: AsyncSession,
    app_id: int,
    item: dict[str, str],
) -> dict[str, Any]:
    """执行单步 — MVP 仅 sleep 1.5s + 返成功.

    ⚠️ P5 接通 MCP 真调的接入点 — 改这里:

        from app.mcp_apaas_apps import (
            create_apaas_app_model,
            add_apaas_model_field,
            create_apaas_app_roles,
            ...
        )

        tool_name = item["mcp_tool"]
        if tool_name == "add_apaas_model_field":
            result = await add_apaas_model_field(db, app_id=app_id, ...)
        elif tool_name == "create_apaas_app_roles":
            result = await create_apaas_app_roles(db, app_id=app_id, ...)
        # ...

    每个 mcp_tool 的入参从 spec_sections.spec_json 取 (entity name / code / fields).
    item desc 含 <strong>{name}</strong> 标记 — P5 实际不靠它取参, 解析 spec_json 取
    完整结构 (避免 desc 跟 spec drift).

    成功后写 last_applied_at + reset draft_version=base_version (避免重复 apply).
    失败按 abort_on_error 决定回滚还是继续.
    """
    # MVP — 模拟执行延迟 (1.5s/step, mockup "预计 ~12 秒" 6 步 = 2s/step;
    # 1.5s 留点 buffer 给 frontend animate transition).
    await asyncio.sleep(1.5)
    return {
        "ok": True,
        "mcp_tool": item.get("mcp_tool"),
        "desc": item.get("desc"),
        "mode": "dry-run",
    }


@router.post("/{app_id}/spec/apply")
async def apply_spec(
    app_id: int,
    body: SpecApplyBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """MVP dry-run — 不真调 MCP, 仅模拟串行执行 + 返进度.

    flow:
      1. 复用 get_apply_plan 逻辑 (权限 + plan 构造)
      2. 串行跑每个 item _execute_step (MVP sleep 1.5s)
      3. 返 {ok, applied_steps, total_steps, mode, results}

    返 (非 SSE — 一次性 dict, 客户端阻塞 N*1.5s):
      {
        ok: true,
        app_id: 13,
        mode: 'dry-run',
        total_steps: 6,
        applied_steps: 6,
        results: [
          { ok, mcp_tool, desc, mode }
        ],
        duration_ms: 9023,
      }

    P5 接通 MCP 真调后:
      - 改 _execute_step 体
      - body.dry_run=false 时真调; true 时仍 sleep
      - 任一 step 失败 → abort + 返 partial results + 触发 spec_sections 回滚
        (last_applied_at 清空, draft_version 复原)
      - 考虑改成 SSE 给 frontend 实时显进度 (本模块 _use_sse=False 留位)
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

    # 2. 拉 plan (复用)
    rows = await _collect_drafted_sections(db, app_id)
    plan = _build_plan(rows)

    if plan["total_steps"] == 0:
        return {
            "ok": True,
            "app_id": app_id,
            "mode": "dry-run",
            "total_steps": 0,
            "applied_steps": 0,
            "results": [],
            "duration_ms": 0,
            "message": "没有未 apply 的 SPEC 草稿改动",
        }

    # 3. 串行执行
    start = datetime.utcnow()
    results: list[dict[str, Any]] = []
    applied = 0
    for group in plan["groups"]:
        for item in group["items"]:
            try:
                step_result = await _execute_step(db, app_id, item)
                results.append(step_result)
                if step_result.get("ok"):
                    applied += 1
            except Exception as exc:
                logger.exception(
                    "spec_apply: step failed app_id=%s tool=%s",
                    app_id,
                    item.get("mcp_tool"),
                )
                # P5: 这里触发回滚. MVP dry-run 不会到这.
                results.append(
                    {
                        "ok": False,
                        "mcp_tool": item.get("mcp_tool"),
                        "desc": item.get("desc"),
                        "error": str(exc),
                    }
                )
                # MVP 不 abort — 继续跑后续 step (因为都是 sleep 没真副作用).
                # P5 真接 MCP 时这里 break 触发回滚.

    duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

    return {
        "ok": True,
        "app_id": app_id,
        "mode": "dry-run",
        "total_steps": plan["total_steps"],
        "applied_steps": applied,
        "results": results,
        "duration_ms": duration_ms,
        # P5: 真 apply 后这里加 deployed_section_ids / rollback_token 给前端回滚 btn 用.
    }
