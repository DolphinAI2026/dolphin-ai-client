"""SpecSection MCP 工具 — spec-driven 草稿层 (O1)

提供 4 个工具，对外行为接近 @mcp.tool() 装饰函数：

    read_spec_section          读应用某 section 的草稿 SPEC
    init_spec_section_from_apaas  从 apaas 真状态拉一次初始化草稿
    update_spec_section        修改草稿 (draft_version+1)
    diff_spec_vs_apaas         算 SPEC 草稿 vs apaas 真状态的 diff

整体目标：让 AI agent 在对话里能"先改本地草稿、确认后再 push apaas"。

注意：
- 本模块只调已有 apaas_client 方法 (query_detail_page_config / query_models 等)，
  不直接做 HTTP 写操作。
- 失败一律 return 错误 dict（不抛），便于工具层向 LLM 透传 user_action_required。
- O1 阶段 spec_json 为自由 JSON 字符串；O3 引入 strict schema 校验。

依赖：
- 调用方必须自行注入合法的 AsyncSession (由 FastAPI 端点的 Depends(get_db) 提供)。
- init / diff 需要 apaas 平台访问，调用方负责传 base_url + tenant_id + token。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apaas_client import APaaSClient
from app.models import PlatformEnv
from app.models.spec_section import SpecSection, VALID_SECTION_TYPES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部 helper
# ---------------------------------------------------------------------------


def _validate_section_type(section_type: str) -> Optional[dict]:
    """Return error dict if section_type 不合法，否则 None。"""
    if section_type not in VALID_SECTION_TYPES:
        return {
            "ok": False,
            "error_code": "INVALID_SECTION_TYPE",
            "message": f"section_type 必须是 {VALID_SECTION_TYPES} 之一, 实际: {section_type!r}",
        }
    return None


def _serialize_section(row: SpecSection) -> dict:
    """SpecSection ORM → 可序列化 dict (spec_json 解为 dict)。"""
    try:
        spec = json.loads(row.spec_json) if row.spec_json else {}
    except json.JSONDecodeError:
        spec = {"_raw": row.spec_json}
    return {
        "id": row.id,
        "application_id": row.application_id,
        "section_type": row.section_type,
        "section_key": row.section_key,
        "spec_json": spec,
        "base_version": row.base_version,
        "draft_version": row.draft_version,
        "last_applied_at": row.last_applied_at.isoformat() if row.last_applied_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _get_or_none(
    db: AsyncSession,
    app_id: int,
    section_type: str,
    section_key: str,
) -> Optional[SpecSection]:
    result = await db.execute(
        select(SpecSection).where(
            SpecSection.application_id == app_id,
            SpecSection.section_type == section_type,
            SpecSection.section_key == section_key,
        )
    )
    return result.scalar_one_or_none()


async def _resolve_env(
    db: AsyncSession, env_id: int
) -> tuple[Optional[PlatformEnv], Optional[dict]]:
    """Return (env, error_dict)；env=None 时 error_dict 必有。"""
    result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == env_id))
    env = result.scalar_one_or_none()
    if not env:
        return None, {
            "ok": False,
            "error_code": "ENV_NOT_FOUND",
            "message": f"env_id={env_id} 不存在",
        }
    if not env.token:
        return None, {
            "ok": False,
            "error_code": "ENV_NOT_CONNECTED",
            "message": f"env_id={env_id} 未登录 (token 为空)",
            "user_action_required": "请在环境管理中重新登录该平台",
        }
    return env, None


# ---------------------------------------------------------------------------
# MCP 工具实现
# ---------------------------------------------------------------------------


async def read_spec_section(
    db: AsyncSession,
    app_id: int,
    section_type: str,
    section_key: str,
) -> dict:
    """读应用某 section 的草稿 SPEC.

    不存在返 {ok:True, exists:False, hint:'调 init_spec_section_from_apaas 初始化'}.
    存在返 {ok:True, exists:True, section:{...}}.
    """
    err = _validate_section_type(section_type)
    if err:
        return err
    row = await _get_or_none(db, app_id, section_type, section_key)
    if not row:
        return {
            "ok": True,
            "exists": False,
            "hint": "调 init_spec_section_from_apaas 初始化",
        }
    return {"ok": True, "exists": True, "section": _serialize_section(row)}


async def init_spec_section_from_apaas(
    db: AsyncSession,
    env_id: int,
    apaas_app_id: str,
    app_id: int,
    section_type: str,
    section_key: str,
) -> dict:
    """从 apaas 真状态拉数据 → 初始化 spec (base_version=1)。

    已存在返 {ok:True, already_exists:True, section:{...}}, 不覆盖。
    section_type 路由:
      form        → query_detail_page_config(formId=section_key)
      process     → 暂返 NOT_IMPLEMENTED (apaas_client 没暴露 process detail)
      data_model  → query_models 找 modelCode == section_key
      其他        → NOT_IMPLEMENTED
    """
    err = _validate_section_type(section_type)
    if err:
        return err

    # 已存在不覆盖
    existing = await _get_or_none(db, app_id, section_type, section_key)
    if existing:
        return {
            "ok": True,
            "already_exists": True,
            "section": _serialize_section(existing),
        }

    env, env_err = await _resolve_env(db, env_id)
    if env_err:
        return env_err
    # type narrowing for static checkers
    assert env is not None

    client = APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id,
        token=env.token,
    )

    # 从 apaas 拉数据
    try:
        if section_type == "form":
            raw = await client.query_detail_page_config(apaas_app_id, section_key)
            spec = _form_apaas_to_spec(raw)
        elif section_type == "data_model":
            models = await client.query_models(apaas_app_id)
            matched = next(
                (m for m in models if str(m.get("modelCode") or "") == section_key),
                None,
            )
            if not matched:
                return {
                    "ok": False,
                    "error_code": "APAAS_MODEL_NOT_FOUND",
                    "message": f"apaas_app={apaas_app_id} 下未找到 modelCode={section_key!r}",
                }
            spec = _data_model_apaas_to_spec(matched)
        elif section_type in ("process", "list", "page", "permission"):
            return {
                "ok": False,
                "error_code": "NOT_IMPLEMENTED",
                "message": f"O1 阶段尚未支持 section_type={section_type!r} 的 init",
            }
        else:
            return {
                "ok": False,
                "error_code": "NOT_IMPLEMENTED",
                "message": f"未知 section_type {section_type!r}",
            }
    except Exception as exc:  # noqa: BLE001 — 把 apaas 失败包成业务错误
        logger.warning(
            "init_spec_section_from_apaas: apaas 调用失败 type=%s key=%s: %s",
            section_type,
            section_key,
            exc,
        )
        return {
            "ok": False,
            "error_code": "APAAS_FETCH_FAILED",
            "message": str(exc),
        }

    row = SpecSection(
        application_id=app_id,
        section_type=section_type,
        section_key=section_key,
        spec_json=json.dumps(spec, ensure_ascii=False),
        base_version=1,
        draft_version=1,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "already_exists": False, "section": _serialize_section(row)}


async def update_spec_section(
    db: AsyncSession,
    app_id: int,
    section_type: str,
    section_key: str,
    spec_json: Any,
    diff_summary: str = "",
) -> dict:
    """改某 section 的 spec_json (草稿). draft_version + 1.

    用法: AI agent 在对话中 "加字段 X" → agent 拿当前 spec → 改 → 调本工具存草稿。

    spec_json: dict 或 JSON string，最终序列化为 TEXT 存。
    diff_summary: 给 UI / 审计日志展示用的一句话变更说明（O1 阶段不入表）。
    """
    err = _validate_section_type(section_type)
    if err:
        return err

    if isinstance(spec_json, str):
        try:
            spec_dict = json.loads(spec_json)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "error_code": "INVALID_JSON",
                "message": f"spec_json 不是合法 JSON: {exc}",
            }
    elif isinstance(spec_json, (dict, list)):
        spec_dict = spec_json
    else:
        return {
            "ok": False,
            "error_code": "INVALID_JSON",
            "message": f"spec_json 必须是 dict / list / JSON 字符串, 实际: {type(spec_json).__name__}",
        }

    row = await _get_or_none(db, app_id, section_type, section_key)
    if not row:
        return {
            "ok": False,
            "error_code": "NOT_FOUND",
            "message": "section 不存在，先调 init_spec_section_from_apaas",
        }

    row.spec_json = json.dumps(spec_dict, ensure_ascii=False)
    row.draft_version = (row.draft_version or 0) + 1
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)

    if diff_summary:
        logger.info(
            "update_spec_section app=%s type=%s key=%s draft_v=%s summary=%s",
            app_id,
            section_type,
            section_key,
            row.draft_version,
            diff_summary[:200],
        )
    return {"ok": True, "section": _serialize_section(row), "diff_summary": diff_summary}


async def diff_spec_vs_apaas(
    db: AsyncSession,
    app_id: int,
    section_type: str,
    section_key: str,
    *,
    env_id: Optional[int] = None,
    apaas_app_id: Optional[str] = None,
) -> dict:
    """算 SPEC 草稿 vs apaas 真状态 diff. 返 {add:[], update:[], remove:[]} list.

    O1 阶段：仅 section_type='form' 真做（按字段 code 对照 add/update/remove），
    其他 section_type 返 NOT_IMPLEMENTED。

    env_id / apaas_app_id 为可选: 不传时尝试从 SpecSection 关联的 Application 反查。
    O1 简化版要求调用方主动传 (避免给 helper 加更多 join 逻辑)。
    """
    err = _validate_section_type(section_type)
    if err:
        return err

    if section_type != "form":
        return {
            "ok": False,
            "error_code": "NOT_IMPLEMENTED",
            "message": f"O1 阶段 diff 只支持 section_type='form', 实际 {section_type!r}",
        }

    row = await _get_or_none(db, app_id, section_type, section_key)
    if not row:
        return {
            "ok": False,
            "error_code": "NOT_FOUND",
            "message": "section 草稿不存在",
        }

    if env_id is None or apaas_app_id is None:
        return {
            "ok": False,
            "error_code": "ENV_REQUIRED",
            "message": "diff 需要 env_id + apaas_app_id (O1 简化版)",
        }

    env, env_err = await _resolve_env(db, env_id)
    if env_err:
        return env_err
    assert env is not None

    try:
        spec = json.loads(row.spec_json) if row.spec_json else {}
    except json.JSONDecodeError:
        spec = {}

    client = APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id,
        token=env.token,
    )
    try:
        apaas_raw = await client.query_detail_page_config(apaas_app_id, section_key)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error_code": "APAAS_FETCH_FAILED",
            "message": str(exc),
        }
    apaas_spec = _form_apaas_to_spec(apaas_raw)

    diff = _diff_form_fields(spec, apaas_spec)
    return {"ok": True, "diff": diff, "spec": spec, "apaas_spec": apaas_spec}


# ---------------------------------------------------------------------------
# apaas → spec 投影 (最小子集, O1 不追求完美)
# ---------------------------------------------------------------------------


def _form_apaas_to_spec(raw: dict | None) -> dict:
    """把 query_detail_page_config 返回的 apaas form 拍成最小 SPEC.

    spec 结构（O1）::

      {
        "type": "form",
        "form_id": str,
        "form_name": str,
        "fields": [
          {"code": "name", "label": "姓名", "widget": "input", "required": True, ...},
          ...
        ],
      }
    """
    raw = raw or {}
    detail = raw.get("detailPage") or {}
    components = detail.get("formComponents") or []
    fields: list[dict] = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        code = (
            comp.get("componentCode")
            or comp.get("code")
            or comp.get("fieldCode")
            or comp.get("name")
            or ""
        )
        if not code:
            continue
        fields.append(
            {
                "code": str(code),
                "label": comp.get("componentLabel")
                or comp.get("label")
                or comp.get("title")
                or "",
                "widget": comp.get("componentType")
                or comp.get("widget")
                or "input",
                "required": bool(comp.get("required")),
            }
        )
    return {
        "type": "form",
        "form_id": str(detail.get("formId") or detail.get("id") or raw.get("formId") or ""),
        "form_name": detail.get("formName") or raw.get("formName") or "",
        "fields": fields,
    }


def _data_model_apaas_to_spec(model: dict | None) -> dict:
    """把 query_models 返回的单个 model 拍成最小 SPEC."""
    model = model or {}
    fields = []
    for f in model.get("fields") or model.get("dataModelFields") or []:
        if not isinstance(f, dict):
            continue
        code = f.get("fieldCode") or f.get("code") or f.get("columnName") or ""
        if not code:
            continue
        fields.append(
            {
                "code": str(code),
                "label": f.get("fieldName") or f.get("name") or "",
                "field_type": f.get("fieldType") or f.get("type") or "STRING",
                "required": bool(f.get("required")),
            }
        )
    return {
        "type": "data_model",
        "model_code": str(model.get("modelCode") or model.get("code") or ""),
        "model_name": model.get("modelName") or model.get("name") or "",
        "fields": fields,
    }


def _diff_form_fields(spec: dict, apaas_spec: dict) -> dict:
    """form section 字段级 diff. 返 {add:[], update:[], remove:[]}.

    - add: SPEC 草稿里有 / apaas 没有 → 等部署
    - remove: apaas 里有 / SPEC 草稿删了 → 等部署
    - update: 两边都有但字段 attr 不一致 → 等部署
    """
    spec_fields = {f.get("code"): f for f in (spec.get("fields") or []) if isinstance(f, dict)}
    apaas_fields = {
        f.get("code"): f for f in (apaas_spec.get("fields") or []) if isinstance(f, dict)
    }
    add: list[dict] = []
    update: list[dict] = []
    remove: list[dict] = []
    for code, spec_f in spec_fields.items():
        if not code:
            continue
        if code not in apaas_fields:
            add.append(spec_f)
        else:
            apaas_f = apaas_fields[code]
            # 简单对比 label / widget / required，其他字段忽略
            changed = {}
            for k in ("label", "widget", "required"):
                if spec_f.get(k) != apaas_f.get(k):
                    changed[k] = {"from": apaas_f.get(k), "to": spec_f.get(k)}
            if changed:
                update.append({"code": code, "changes": changed})
    for code, apaas_f in apaas_fields.items():
        if not code:
            continue
        if code not in spec_fields:
            remove.append(apaas_f)
    return {"add": add, "update": update, "remove": remove}
