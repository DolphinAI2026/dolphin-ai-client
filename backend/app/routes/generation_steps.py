"""Copilot 分步生成路由

GET  /applications/{app_id}/steps/status  — 获取所有步骤状态
POST /applications/{app_id}/steps/execute — 执行单个步骤
POST /applications/{app_id}/steps/reset   — 重置步骤
"""
from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt_password
from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, DeployRecord, User, ApiCallLog
from app.app_code import normalize_app_code
from app.routes.applications import _dump_preview_config
from app.schemas import (
    StepExecuteRequest, StepResetRequest,
    StepStatus, GenerationStatusResponse, StepExecuteResponse,
    ConflictInfo, ResolveConflictRequest,
)
from app.step_executor import (
    execute_create_app, execute_create_roles_dicts,
    execute_create_model, execute_create_form,
    execute_create_workflow, execute_configure_permissions,
)
from app.app_locks import acquire_app_lock
from app.json_utils import loads_if_str
from app.error_messages import APAAS_TOKEN_EXPIRED_STEP, is_apaas_token_error
from app.field_types import get_comp_type_map
from app.lowcode_standards import normalize_preview_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["生成步骤"])

# 审批流程作为独立步骤执行。单步失败会停在该步骤，用户可修正后重试。
WORKFLOW_STEPS_ENABLED = True

# 平台 / 历史数据偶尔会返回非规范组件码（缺 _INPUT / _SELECT 之类后缀），
# 这里列出这些别名到中文显示名的固定映射。
# 规范码的映射则从 field_types.FIELD_TYPES 自动反转——FIELD_TYPES 增改时此处无需手动同步。
_PLATFORM_LEGACY_COMPONENT_ALIASES = {
    "FORM_TEXTAREA": "多行输入",
    "FORM_SELECT": "下拉单选",
    "FORM_SELECT_MULTI": "下拉多选",
    "FORM_DATE_PICKER": "日期时间",
    "FORM_UPLOAD": "附件上传",
    "FORM_SWITCH": "开关",
    "FORM_USER_SELECT": "人员选择",
    "FORM_DEPT_SELECT": "部门选择",
    "FORM_RADIO": "单选框",
    "FORM_CHECKBOX": "复选框",
    "FORM_LINK": "超链接",
    "FORM_ID_CARD": "身份证号",
    "FORM_LOCATION": "地理位置",
    "FORM_ADDRESS": "地区地址",
    "FORM_SERIAL": "单据号",
}


def _build_component_type_labels() -> dict:
    """组件类型码 → 中文显示名。

    规范码：反转 field_types.get_comp_type_map()。多个中文名指向同一组件码时，
    用 setdefault 保证 FIELD_TYPES 里先注册的主要名字胜出（别名/兼容名来自
    _COMPAT_TYPES，按顺序在后，自动被忽略）。
    非规范码：由 _PLATFORM_LEGACY_COMPONENT_ALIASES 静态补齐。
    """
    labels: dict = {}
    for display_name, component_code in get_comp_type_map().items():
        labels.setdefault(component_code, display_name)
    # 规范码（来自 field_types）优先于 legacy 别名，合并时 legacy 放后备位
    merged: dict = dict(_PLATFORM_LEGACY_COMPONENT_ALIASES)
    merged.update(labels)
    return merged


_COMPONENT_TYPE_LABELS = _build_component_type_labels()


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _load_state(app: Application) -> dict:
    if app.generation_state:
        state = loads_if_str(app.generation_state)
    else:
        state = {"steps_completed": [], "step_errors": {}}
        # 仅首次（无 generation_state）时兼容旧流程
        if app.apaas_app_id:
            state["steps_completed"].append("create_app")
            state["apaas_app_id"] = app.apaas_app_id
    return state


def _save_state(app: Application, state: dict):
    app.generation_state = json.dumps(state, ensure_ascii=False)


def _first_meaningful_generation_error(*, state: dict | None = None, event_log: object = None) -> str | None:
    state_errors = (state or {}).get("step_errors") if isinstance(state, dict) else None
    if isinstance(state_errors, dict):
        for value in state_errors.values():
            if value not in (None, "", "未知错误"):
                return str(value)

    try:
        events = loads_if_str(event_log) if event_log else []
    except Exception:  # noqa: BLE001
        events = []
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            if event.get("status") == "error" or event.get("type") in ("error", "exception"):
                for key in ("error", "message", "step"):
                    value = event.get(key)
                    if value not in (None, "", "未知错误"):
                        return str(value)
    return None


async def _latest_generation_error(app: Application, db: AsyncSession) -> str | None:
    if app.status != "failed":
        return None
    state = _load_state(app)
    record = (await db.execute(
        select(DeployRecord)
        .where(DeployRecord.app_id == app.id, DeployRecord.status == "failed")
        .order_by(desc(DeployRecord.completed_at), desc(DeployRecord.id))
        .limit(1)
    )).scalar_one_or_none()
    record_message = record.error_message if record else None
    if record_message and record_message != "未知错误":
        return record_message
    recovered = _first_meaningful_generation_error(
        state=state,
        event_log=record.event_log_json if record else None,
    )
    return recovered or record_message or "应用生成失败，请检查平台连接后重试"


def _load_config(app: Application) -> dict:
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空，请先在对话中生成配置")
    return loads_if_str(app.config_preview)


def _normalized_config_for_steps(app: Application, *, persist: bool = False) -> dict:
    config = _load_config(app)
    normalized, changed, meta = normalize_preview_config(config)
    if changed:
        field_changes = sum(len(items) for items in (meta.get("field_code_map") or {}).values())
        logger.info("低代码配置已规范化: app_id=%s field_code_changes=%s", app.id, field_changes)
        if persist:
            app.config_preview = _dump_preview_config(normalized)
    return normalized


def _upsert_form_result(state: dict, entry: dict) -> None:
    """Store one form result without duplicating the same platform form."""
    results = state.setdefault("form_results", [])
    form_id = str(entry.get("formId") or "").strip()
    model_code = str(entry.get("modelCode") or "").strip()
    form_name = str(entry.get("formName") or "").strip()

    def _merged(existing: dict, incoming: dict) -> dict:
        merged = dict(existing)
        for key, value in incoming.items():
            if value not in (None, ""):
                merged[key] = value
            elif key not in merged:
                merged[key] = value
        return merged

    for idx, item in enumerate(results):
        if form_id and str(item.get("formId") or "").strip() == form_id:
            results[idx] = _merged(item, entry)
            return
        if model_code and str(item.get("modelCode") or "").strip() == model_code:
            results[idx] = _merged(item, entry)
            return
        if form_name and str(item.get("formName") or "").strip() == form_name:
            results[idx] = _merged(item, entry)
            return

    results.append(entry)


def _component_type_label(value: str, model_type: str = "") -> str:
    raw = str(value or "").strip()
    model_label = str(model_type or "").strip()
    label = _COMPONENT_TYPE_LABELS.get(raw, raw)
    if not label:
        return model_label or ""
    if label == "单行输入" and model_label and model_label != "单行输入":
        return model_label
    return label


def _field_ref_meta_from_component(
    component: dict,
    field_meta: dict,
    models_by_code: dict[str, dict],
    fields_by_model: dict[str, dict],
    form_name_by_code: dict[str, str],
) -> tuple[str, str, str]:
    association = component.get("formAssociationConfig") or component.get("form_association_config") or {}
    ref = component.get("ref") or field_meta.get("ref") or {}

    selector_form_code = str(component.get("selector_form_code") or "").strip()
    association_form_code = str(component.get("association_form_code") or "").strip()
    target_model_code = str(
        association.get("targetModelCode")
        or selector_form_code
        or association_form_code
        or component.get("ref_model_code")
        or (ref.get("model") if isinstance(ref, dict) else "")
        or ""
    ).strip()
    target_field_code = str(
        association.get("targetFieldCode")
        or component.get("selector_field_code")
        or component.get("selectorFieldCode")
        or component.get("association_target_field_code")
        or component.get("associationTargetFieldCode")
        or component.get("ref_display_field_code")
        or component.get("refDisplayFieldCode")
        or (ref.get("display_field") if isinstance(ref, dict) else "")
        or (ref.get("target_field") if isinstance(ref, dict) else "")
        or (ref.get("field") if isinstance(ref, dict) else "")
        or ""
    ).strip()
    origin_field_code = str(
        association.get("originFieldCode")
        or component.get("association_origin_field_code")
        or component.get("associationOriginFieldCode")
        or (
            field_meta.get("formAssociationConfig", {}).get("originFieldCode")
            if isinstance(field_meta.get("formAssociationConfig"), dict)
            else ""
        )
        or (
            field_meta.get("form_association_config", {}).get("originFieldCode")
            if isinstance(field_meta.get("form_association_config"), dict)
            else ""
        )
        or ""
    ).strip()

    return target_model_code, target_field_code, origin_field_code


def _data_scope_label(value: object) -> str:
    raw = str(value or "").strip().upper()
    mapping = {
        "ALL": "全部数据",
        "SELF": "本人数据",
        "CURRENT_USER_DEPT": "本部门数据",
        "CURRENT_USER_DEPT_LOW_LEVEL": "本部门及下属部门数据",
    }
    return mapping.get(raw, str(value or "").strip())


def _field_code_from_model_field(model_field: str) -> str:
    raw = str(model_field or "").strip()
    return raw.split(".")[-1] if "." in raw else raw


def _first_form_value(form: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = form.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
            continue
        return str(value)
    return default


def _build_model_maps(models: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    models_by_code: dict[str, dict] = {}
    fields_by_model: dict[str, dict] = {}
    for model in models:
        code = str(model.get("code", "")).strip()
        if not code:
            continue
        models_by_code[code] = model
        fields_by_model[code] = {
            str(field.get("code", "")).strip(): field
            for field in (model.get("fields") or [])
            if str(field.get("code", "")).strip()
        }
    return models_by_code, fields_by_model


def _iter_form_definitions(data: dict, models: list[dict]) -> list[dict]:
    forms = data.get("forms", []) or []
    if forms:
        return forms
    return [
        model for model in models
        if model.get("form_name") or model.get("form_code") or model.get("components")
    ]


def _form_identity_values(form: dict) -> set[str]:
    values = {
        str(form.get("formCode") or "").strip(),
        str(form.get("form_code") or "").strip(),
        str(form.get("code") or "").strip(),
        str(form.get("name") or "").strip(),
        str(form.get("formName") or "").strip(),
        str(form.get("form_name") or "").strip(),
        str(form.get("modelCode") or "").strip(),
        str(form.get("model_code") or "").strip(),
        str(form.get("mainModelCode") or "").strip(),
        str(form.get("main_model_code") or "").strip(),
        str(form.get("main_model") or "").strip(),
    }
    return {value for value in values if value}


def _extract_form_dependencies(forms: list[dict]) -> dict[int, set[int]]:
    identity_to_idx: dict[str, int] = {}
    for idx, form in enumerate(forms):
        for value in _form_identity_values(form):
            identity_to_idx.setdefault(value, idx)

    # 关联表单（FORM_ASSOCIATION）只是展示组件，创建表单时不需要目标先存在
    _ASSOCIATION_TYPES = {"FORM_ASSOCIATION", "关联表单"}

    deps_by_idx: dict[int, set[int]] = {}
    for idx, form in enumerate(forms):
        deps: set[int] = set()
        for component in form.get("components") or []:
            comp_type = str(component.get("componentType") or component.get("component_type") or "").strip()
            if comp_type in _ASSOCIATION_TYPES:
                continue  # 关联表单不产生创建顺序依赖
            ref = component.get("ref") or {}
            targets = [
                str(component.get("selector_form_code") or "").strip(),
                str(component.get("ref_model_code") or "").strip(),
                str(ref.get("model") or "").strip() if isinstance(ref, dict) else str(ref or "").strip(),
            ]
            for target in targets:
                if not target:
                    continue
                dep_idx = identity_to_idx.get(target)
                if dep_idx is not None and dep_idx != idx:
                    deps.add(dep_idx)
        deps_by_idx[idx] = deps
    return deps_by_idx


def _ordered_form_indices(forms: list[dict]) -> list[int]:
    deps_by_idx = _extract_form_dependencies(forms)
    remaining = set(range(len(forms)))
    ordered: list[int] = []

    while remaining:
        ready = sorted(idx for idx in remaining if deps_by_idx.get(idx, set()).issubset(set(ordered)))
        if not ready:
            ordered.extend(sorted(remaining))
            break
        ordered.extend(ready)
        remaining -= set(ready)

    return ordered


def _bool_label(value: object) -> str:
    return "是" if bool(value) else "否"


def _is_sub_table_component(component: dict) -> bool:
    component_type = str(component.get("componentType") or component.get("component_type") or "").strip()
    return component_type == "FORM_WIDGET_SON_TABLE"


def _render_design_doc_markdown(app_name: str, app_code: str, data: dict) -> str:
    """保持原对外签名；实现委托给 services.design_doc_renderer.render。"""
    from app.services.design_doc_renderer import render as _render
    return _render(
        app_name,
        app_code,
        data,
        build_model_maps=_build_model_maps,
        iter_form_definitions=_iter_form_definitions,
        field_code_from_model_field=_field_code_from_model_field,
        field_ref_meta_from_component=_field_ref_meta_from_component,
        component_type_label=_component_type_label,
        bool_label=_bool_label,
        is_sub_table_component=_is_sub_table_component,
        data_scope_label=_data_scope_label,
    )

def _build_steps(config: dict, state: dict, apaas_app_id: str = None) -> list[StepStatus]:
    """根据 config 和 state 构建完整步骤列表。"""
    data = config.get("data", config)
    models = data.get("models", [])
    completed = set(state.get("steps_completed", []))
    errors = state.get("step_errors", {})

    # 如果平台应用已存在，create_app 步骤视为已完成
    app_created = "create_app" in completed or bool(apaas_app_id)

    steps: list[StepStatus] = []

    # 1. 创建应用
    steps.append(StepStatus(
        key="create_app", label="创建平台应用",
        status="completed" if app_created else ("error" if "create_app" in errors else "pending"),
        deps_met=True,
        error=errors.get("create_app"),
    ))

    # 2. 角色（逐个）
    roles = data.get("roles", [])
    for idx, r in enumerate(roles):
        key = f"create_role:{idx}"
        err = errors.get(key)
        # 角色编码重复 → 视为已完成（复用已有）
        auto_ok = err and any(kw in err for kw in ["重复", "已存在", "duplicate"])
        steps.append(StepStatus(
            key=key, label=f"创建角色: {r.get('name', f'角色{idx}')}",
            status="completed" if (key in completed or auto_ok) else ("error" if key in errors else "pending"),
            deps_met=app_created,
            error=None if auto_ok else err,
        ))

    # 3. 字典（逐个）
    dicts = data.get("dicts", [])
    for idx, d in enumerate(dicts):
        key = f"create_dict:{idx}"
        err = errors.get(key)
        # 字典编码重复 → 视为已完成（复用已有）
        auto_ok = err and any(kw in err for kw in ["重复", "已存在", "duplicate"])
        steps.append(StepStatus(
            key=key, label=f"创建字典: {d.get('name', f'字典{idx}')}",
            status="completed" if (key in completed or auto_ok) else ("error" if key in errors else "pending"),
            deps_met=app_created,
            error=None if auto_ok else err,
        ))

    # 兼容旧的 create_roles_dicts 步骤（如果已完成，标记所有角色和字典步骤为已完成）
    if "create_roles_dicts" in completed:
        for idx in range(len(roles)):
            k = f"create_role:{idx}"
            if k not in completed:
                completed.add(k)
        for idx in range(len(dicts)):
            k = f"create_dict:{idx}"
            if k not in completed:
                completed.add(k)

    # 4. 数据模型（每个独立）
    all_roles_done = all(f"create_role:{i}" in completed for i in range(len(roles))) if roles else True
    all_dicts_done = all(f"create_dict:{i}" in completed for i in range(len(dicts))) if dicts else True
    for idx, m in enumerate(models):
        key = f"create_model:{idx}"
        steps.append(StepStatus(
            key=key, label=f"创建模型: {m['name']}",
            status="completed" if key in completed else ("error" if key in errors else "pending"),
            deps_met=app_created,
            model_index=idx,
            error=errors.get(key),
        ))

    # 5. 表单（每个独立）
    forms = data.get("forms", []) or []
    form_deps = _extract_form_dependencies(forms)
    for idx in _ordered_form_indices(forms):
        form = forms[idx]
        key = f"create_form:{idx}"
        form_model_code = _first_form_value(
            form,
            "modelCode",
            "model_code",
            "mainModelCode",
            "main_model_code",
            "main_model",
        )
        model_idx = next((i for i, m in enumerate(models) if str(m.get("code", "")).strip() == form_model_code), None)
        model_key = f"create_model:{model_idx}" if model_idx is not None else None
        form_dep_keys = [f"create_form:{dep_idx}" for dep_idx in sorted(form_deps.get(idx, set()))]
        deps_ok = (
            all_roles_done
            and all_dicts_done
            and (model_key in completed if model_key else app_created)
            and all(dep_key in completed for dep_key in form_dep_keys)
        )
        steps.append(StepStatus(
            key=key,
            label=f"创建表单: {_first_form_value(form, 'formName', 'form_name', 'name', default=f'表单{idx}')}",
            status="completed" if key in completed else ("error" if key in errors else "pending"),
            deps_met=deps_ok,
            model_index=model_idx if model_idx is not None else idx,
            error=errors.get(key),
        ))

    all_forms_done = all(f"create_form:{i}" in completed for i in range(len(forms)))
    workflows = data.get("workflows", [])
    if WORKFLOW_STEPS_ENABLED:
        for idx, wf in enumerate(workflows):
            key = f"create_workflow:{idx}"
            steps.append(StepStatus(
                key=key, label=f"创建流程: {wf.get('name', wf.get('form', f'流程{idx}'))}",
                status="completed" if key in completed else ("error" if key in errors else "pending"),
                deps_met=all_forms_done,
                error=errors.get(key),
            ))

    # 6. 权限
    all_workflows_done = all(f"create_workflow:{i}" in completed for i in range(len(workflows))) if workflows else True
    perm_deps = all_forms_done and all_workflows_done if WORKFLOW_STEPS_ENABLED else all_forms_done
    steps.append(StepStatus(
        key="configure_permissions", label="配置权限",
        status="completed" if "configure_permissions" in completed else ("error" if "configure_permissions" in errors else "pending"),
        deps_met=perm_deps,
        error=errors.get("configure_permissions"),
    ))

    return steps


def _critical_step_keys(config: dict) -> set[str]:
    """Steps that can be verified from platform objects."""
    data = config.get("data", config)
    keys = {"create_app"}
    keys.update(f"create_role:{i}" for i, _ in enumerate(data.get("roles") or []))
    keys.update(f"create_dict:{i}" for i, _ in enumerate(data.get("dicts") or []))
    keys.update(f"create_model:{i}" for i, _ in enumerate(data.get("models") or []))
    keys.update(f"create_form:{i}" for i, _ in enumerate(data.get("forms") or []))
    if WORKFLOW_STEPS_ENABLED:
        keys.update(f"create_workflow:{i}" for i, _ in enumerate(data.get("workflows") or []))
    return keys


def _sync_platform_codes_to_config(app: Application, state: dict, data: dict):
    """部署完成后，将平台真实编码回写到 config_preview"""
    try:
        config = loads_if_str(app.config_preview)
        cfg_data = config.get("data", config)

        # 回写平台最终应用编码
        platform_app_code = normalize_app_code(
            state.get("platform_app_code")
            or cfg_data.get("appCode")
            or cfg_data.get("app_code")
            or app.app_code
            or ""
        )
        if platform_app_code:
            cfg_data["appCode"] = platform_app_code
            cfg_data["app_code"] = platform_app_code
            app.app_code = platform_app_code

        # 回写角色编码
        role_codes = state.get("role_codes", {})
        for r in cfg_data.get("roles", []):
            rc = role_codes.get(r.get("code", r["name"]))
            if rc:
                r["platform_code"] = rc.get("roleCode", "")

        # 回写字典编码
        dict_codes = state.get("dict_codes", {})
        for d in cfg_data.get("dicts", []):
            dc = dict_codes.get(d.get("name")) or dict_codes.get(d.get("code", ""))
            if dc:
                d["platform_code"] = dc

        # 回写模型编码
        model_info = state.get("model_info", {})
        for idx, m in enumerate(cfg_data.get("models", [])):
            mi = model_info.get(str(idx))
            if mi:
                m["platform_code"] = mi.get("code", "")
                # 回写字段编码
                platform_fields = mi.get("fields", {})
                for f in m.get("fields", []):
                    pfc = platform_fields.get(f["name"])
                    if pfc:
                        f["platform_code"] = pfc

        # 回写 apaas_app_id
        cfg_data["apaas_app_id"] = state.get("apaas_app_id") or app.apaas_app_id

        app.config_preview = _dump_preview_config(config)
        logger.info(f"平台编码已回写到 config_preview (app_id={app.id})")
    except Exception as e:
        logger.warning(f"回写平台编码失败: {e}")


async def _sync_current_doc_version_content(db: AsyncSession, app: Application):
    if not app.current_doc_version or not app.config_preview:
        return
    try:
        from app.models import DocumentVersion
        import hashlib

        config = loads_if_str(app.config_preview)
        data = config.get("data", config)
        doc_version_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.application_id == app.id,
                DocumentVersion.version == app.current_doc_version,
            )
        )
        doc_version = doc_version_result.scalar_one_or_none()
        if not doc_version:
            return
        doc_version.parsed_config = json.dumps(config, ensure_ascii=False)
        final_app_code = (
            data.get("appCode")
            or data.get("app_code")
            or app.app_code
            or ""
        )
        doc_version.raw_content = _render_design_doc_markdown(app.app_name or data.get("appName", ""), final_app_code, data)
        doc_version.content_hash = hashlib.sha256(doc_version.parsed_config.encode()).hexdigest()
    except Exception:
        logger.warning("同步当前文档版本正文失败 app_id=%s", app.id, exc_info=True)


async def _get_app(app_id: int, ctx: AuthContext, db: AsyncSession) -> Application:
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app


def _detect_code_conflict(error_msg: str, step_key: str, data: dict, models: list) -> Optional[ConflictInfo]:
    """检测错误信息中是否包含编码冲突，返回 ConflictInfo 或 None。"""
    # 常见的编码冲突错误关键词
    conflict_patterns = [
        r"编码[「\"]?(\w+)[」\"]?.*(?:重复|已存在|冲突)",
        r"code[「\"]?(\w+)[」\"]?.*(?:already exists|duplicate|conflict)",
        r"(?:重复|已存在|冲突).*编码[「\"]?(\w+)[」\"]?",
        r"模型编码(\w+)已存在",
        r"字典编码(\w+)已存在",
        r"角色编码(\w+)已存在",
        r"编码(\w+)重复",
    ]

    # 也检测 HTTP 400/409 + 编码相关信息
    is_conflict_error = any(kw in error_msg for kw in [
        "编码重复", "编码已存在", "code already exists", "duplicate",
        "编码冲突", "code duplicate", "已存在同名",
    ])

    if not is_conflict_error:
        return None

    # 尝试从错误信息中提取冲突编码
    conflict_code = None
    for pattern in conflict_patterns:
        match = re.search(pattern, error_msg, re.IGNORECASE)
        if match:
            conflict_code = match.group(1)
            break

    # 根据步骤类型确定名称和编码
    entity_name = "未知"
    entity_code = conflict_code or "unknown"

    if step_key.startswith("create_model:"):
        idx = int(step_key.split(":")[1])
        if idx < len(models):
            entity_name = models[idx].get("name", f"模型{idx}")
            if not conflict_code:
                entity_code = models[idx].get("code", "unknown")
    elif step_key.startswith("create_role:"):
        idx = int(step_key.split(":")[1])
        roles = data.get("roles", [])
        if idx < len(roles):
            entity_name = roles[idx].get("name", f"角色{idx}")
            if not conflict_code:
                entity_code = roles[idx].get("code", entity_code)
    elif step_key.startswith("create_dict:"):
        idx = int(step_key.split(":")[1])
        dicts = data.get("dicts", [])
        if idx < len(dicts):
            entity_name = dicts[idx].get("name", f"字典{idx}")
            if not conflict_code:
                entity_code = dicts[idx].get("code", entity_code)
    elif step_key == "create_roles_dicts":
        entity_name = "角色/字典"
        name_match = re.search(r"[「\"](.+?)[」\"]", error_msg)
        if name_match:
            entity_name = name_match.group(1)
    elif step_key.startswith("create_form:"):
        idx = int(step_key.split(":")[1])
        if idx < len(models):
            entity_name = models[idx].get("name", f"表单{idx}")
            if not conflict_code:
                entity_code = models[idx].get("code", "unknown")

    return ConflictInfo(
        conflict_type="code_duplicate",
        model_name=entity_name,
        current_code=entity_code,
        message=f"编码 {entity_code} 在平台上已存在，请提供一个新的编码",
    )


# ------------------------------------------------------------------
# GET /status
# ------------------------------------------------------------------

# 2026-05-29: 进度面板按 apaas 真实对象重建（修「服务端 generate-run 跑完面板还显 1/182」）。
# 根因：_build_steps 只读 state.steps_completed；逐步 /execute 路径会回写它，但服务端
# 一把梭的 generate-run（run_complete_generation）不写 → 面板永远停在 create_app。
# 这里查 apaas 真有的模型/角色/字典/菜单，把对应 step 标完成，与构建路径无关。
# 进程内缓存 8s，避免前端轮询把 apaas 打爆（4 次 list 调用 / 8s）。
_REALITY_TTL_S = 8.0
_REALITY_CACHE: dict[int, tuple[float, set[str]]] = {}


def _lc(v: object) -> str:
    return str(v or "").strip().lower()


async def _reality_completed_step_keys(app: Application, config: dict, db: AsyncSession) -> set[str]:
    """查 apaas 真实对象 → 已完成的 step key 集合（进程内 8s 缓存）。失败返回已知部分，不抛。"""
    import time as _time

    apaas_app_id = app.apaas_app_id
    if not apaas_app_id:
        return set()
    now = _time.time()
    cached = _REALITY_CACHE.get(app.id)
    if cached and (now - cached[0]) < _REALITY_TTL_S:
        return cached[1]

    keys: set[str] = {"create_app"}
    data = config.get("data", config)
    try:
        # 局部 import 避免模块级循环依赖
        from app.routes.applications.generate import _resolve_env_and_client
        client, _env = await _resolve_env_and_client(app, db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("steps reality reconcile: 解析 client 失败 app=%s: %s", app.id, exc)
        _REALITY_CACHE[app.id] = (now, keys)  # 缓存以免反复重试
        return keys

    aid = str(apaas_app_id)
    # 模型（按 code 比对，apaas 实测 code 与 config 一致）
    try:
        ms = await client.query_models(aid, with_fields=False)
        codes = {_lc(m.get("modelCode")) for m in ms}
        names = {_lc(m.get("modelName")) for m in ms}
        for idx, m in enumerate(data.get("models") or []):
            if _lc(m.get("code") or m.get("modelCode")) in codes or _lc(m.get("name") or m.get("modelName")) in names:
                keys.add(f"create_model:{idx}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("steps reality reconcile models 失败 app=%s: %s", app.id, exc)
    # 角色（按名）
    try:
        rs = await client.query_roles(aid)
        rnames = {_lc(r.get("roleName") or r.get("name")) for r in rs}
        for idx, r in enumerate(data.get("roles") or []):
            if _lc(r.get("name") or r.get("roleName")) in rnames:
                keys.add(f"create_role:{idx}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("steps reality reconcile roles 失败 app=%s: %s", app.id, exc)
    # 字典（按名 / code）
    try:
        ds = await client.query_dicts(aid)
        dnames = {_lc(d.get("name") or d.get("dictName") or d.get("dictionaryName")) for d in ds}
        dcodes = {_lc(d.get("code") or d.get("dictCode") or d.get("dictionaryCode")) for d in ds}
        for idx, d in enumerate(data.get("dicts") or []):
            if _lc(d.get("name") or d.get("dictName")) in dnames or _lc(d.get("code") or d.get("dictCode")) in dcodes:
                keys.add(f"create_dict:{idx}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("steps reality reconcile dicts 失败 app=%s: %s", app.id, exc)
    # 表单（按表单名比对 apaas 菜单名）
    try:
        menus = await client.query_menus(aid)
        mnames = {_lc(x.get("name") or x.get("menuName") or x.get("title")) for x in menus}
        for idx, form in enumerate(data.get("forms") or []):
            fname = _lc(_first_form_value(form, "formName", "form_name", "name", default=""))
            if fname and fname in mnames:
                keys.add(f"create_form:{idx}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("steps reality reconcile forms 失败 app=%s: %s", app.id, exc)

    _REALITY_CACHE[app.id] = (now, keys)
    return keys


@router.get("/applications/{app_id}/steps/status", response_model=GenerationStatusResponse)
async def get_step_status(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = await _get_app(app_id, ctx, db)
    config = _normalized_config_for_steps(app)
    state = _load_state(app)
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id
    error_message = await _latest_generation_error(app, db)

    # 按 apaas 真实对象补全进度（与构建路径无关）。不能因为本地 status=completed
    # 就全量置绿；平台对象缺失时必须让进度面板暴露出来。
    if apaas_app_id:
        try:
            reality = await _reality_completed_step_keys(app, config, db)
            if reality:
                state = {**state, "steps_completed": list(set(state.get("steps_completed", [])) | reality)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("steps reality reconcile 整体失败 app=%s: %s", app.id, exc)

    steps = _build_steps(config, state, apaas_app_id)
    if app.status == "completed":
        critical = _critical_step_keys(config)
        done = {s.key for s in steps if s.status == "completed"}
        # 权限步骤当前没有稳定查询接口。只有当平台可核对对象均真实存在时，
        # 才允许把本地 completed 作为权限完成的佐证。
        if critical.issubset(done):
            for s in steps:
                if s.key == "configure_permissions":
                    s.status = "completed"
                    s.deps_met = True
    return GenerationStatusResponse(
        apaas_app_id=apaas_app_id,
        app_status=app.status,
        error_message=error_message,
        steps=steps,
    )


# ------------------------------------------------------------------
# POST /execute
# ------------------------------------------------------------------

@router.post("/applications/{app_id}/steps/execute", response_model=StepExecuteResponse)
async def execute_step(
    app_id: int,
    body: StepExecuteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.apaas_client import APaaSClient

    app = await _get_app(app_id, ctx, db)
    config = _normalized_config_for_steps(app, persist=True)
    state = _load_state(app)
    data = config.get("data", config)
    models = data.get("models", [])
    step_key = body.step
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id

    # 验证步骤存在
    steps = _build_steps(config, state, apaas_app_id)
    step_info = next((s for s in steps if s.key == step_key), None)
    if not step_info:
        raise HTTPException(status_code=400, detail=f"无效步骤: {step_key}")

    # 验证依赖
    if not step_info.deps_met:
        raise HTTPException(status_code=400, detail=f"步骤 {step_key} 的依赖尚未完成")

    # 如果已完成，跳过
    completed = set(state.get("steps_completed", []))
    if step_key in completed:
        return StepExecuteResponse(step=step_key, status="completed", result={"message": "已完成，跳过"})

    # 特殊处理：如果平台应用已存在，create_app 步骤直接跳过
    if step_key == "create_app" and apaas_app_id:
        # 确保 state 中记录了 apaas_app_id
        state["apaas_app_id"] = apaas_app_id
        state.setdefault("steps_completed", [])
        if "create_app" not in state["steps_completed"]:
            state["steps_completed"].append("create_app")
        _save_state(app, state)
        await db.commit()
        return StepExecuteResponse(step=step_key, status="completed", result={"message": "平台应用已存在，跳过创建"})

    # 获取连接信息：优先从 PlatformEnv → 回退到 User
    from app.models import PlatformEnv
    env = None
    if hasattr(app, 'platform_env_id') and app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()

    if not env:
        # 回退：查找默认环境
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
        )
        env = env_result.scalar_one_or_none()

    if not env:
        # 兜底：取第一个已连接的环境
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env = env_result.scalar_one_or_none()

    if env and env.token:
        client = APaaSClient(
            base_url=env.base_url,
            tenant_id=env.platform_tenant_id,
            token=env.token,
        )
    else:
        # 最终回退：用户级连接（兼容旧逻辑）
        user_result = await db.execute(select(User).where(User.id == ctx.user.id))
        user = user_result.scalar_one()

        from app.models import Project
        from app.routes.projects import ensure_platform_token
        project_result = await db.execute(
            select(Project).where(Project.id == app.project_id) if hasattr(app, 'project_id') and app.project_id else select(Project).where(Project.user_id == ctx.user.id).order_by(Project.updated_at.desc()).limit(1)
        )
        project = project_result.scalar_one_or_none()

        if project and project.platform_url:
            try:
                token = await ensure_platform_token(project, db)
                user.apaas_token = token
                await db.commit()
            except Exception as token_err:
                # 平台 token 回退失败：保留原控制流（下方仍会校验 apaas_token 是否为空），
                # 但不再完全静默——记录 warning 便于排查为何回退到用户级连接失败。
                logger.warning(f"应用 {app.id} 平台 token 回退获取失败: {token_err}")

        if not user.apaas_token:
            raise HTTPException(status_code=400, detail="未配置平台环境，请在环境管理中添加并连接")
        client = APaaSClient(
            base_url=user.apaas_base_url or (project.platform_url if project else None),
            tenant_id=user.apaas_tenant_id or (project.platform_tenant_id if project else None),
            token=user.apaas_token,
        )

    # 执行（加并发锁保护）
    from app.apaas_client import flush_call_logs

    async with acquire_app_lock(app_id, f"步骤执行:{step_key}"):
        step_response: Optional[StepExecuteResponse] = None
        step_exception: Optional[Exception] = None
        try:
            result = await _execute_step_impl(client, app, config, state, step_key, data, models)
            # 标记完成
            state.setdefault("steps_completed", [])
            if step_key not in state["steps_completed"]:
                state["steps_completed"].append(step_key)
            state.get("step_errors", {}).pop(step_key, None)
            _save_state(app, state)

            # 检查是否所有步骤都完成了
            all_steps = _build_steps(config, state, state.get("apaas_app_id") or app.apaas_app_id)
            if all(s.status == "completed" for s in all_steps):
                app.status = "completed"
                # 回写平台编码到 config_preview
                _sync_platform_codes_to_config(app, state, data)
                await _sync_current_doc_version_content(db, app)
                logger.info(f"应用 {app.id} 所有步骤完成，状态更新为 completed")

            step_response = StepExecuteResponse(step=step_key, status="completed", result=result)

        except Exception as e:
            error_msg = str(e).strip() or repr(e).strip() or e.__class__.__name__
            logger.error(f"步骤 {step_key} 执行失败: {error_msg}", exc_info=True)

            # Token 过期时，优先尝试使用环境里保存的账号密码自动重登并重试当前步骤
            if is_apaas_token_error(error_msg) or "401" in error_msg:
                relogin_success = False
                if env and env.username and getattr(env, "password_enc", None):
                    try:
                        password = decrypt_password(env.password_enc)
                        refresh_client = APaaSClient(
                            base_url=env.base_url,
                            tenant_id=env.platform_tenant_id,
                        )
                        login_result = await refresh_client.login(env.username, password)
                        new_token = login_result.get("token") if isinstance(login_result, dict) else None
                        if new_token:
                            env.token = new_token
                            env.status = "connected"
                            await db.commit()
                            client = APaaSClient(
                                base_url=env.base_url,
                                tenant_id=env.platform_tenant_id,
                                token=new_token,
                            )
                            result = await _execute_step_impl(client, app, config, state, step_key, data, models)
                            state.setdefault("steps_completed", [])
                            if step_key not in state["steps_completed"]:
                                state["steps_completed"].append(step_key)
                            state.get("step_errors", {}).pop(step_key, None)
                            _save_state(app, state)

                            all_steps = _build_steps(config, state, state.get("apaas_app_id") or app.apaas_app_id)
                            if all(s.status == "completed" for s in all_steps):
                                app.status = "completed"
                                _sync_platform_codes_to_config(app, state, data)
                                await _sync_current_doc_version_content(db, app)
                                logger.info(f"应用 {app.id} 所有步骤完成，状态更新为 completed")

                            step_response = StepExecuteResponse(step=step_key, status="completed", result=result)
                            relogin_success = True
                            logger.info(f"步骤 {step_key} 在自动刷新平台 token 后执行成功")
                    except Exception as relogin_err:
                        logger.warning(f"步骤 {step_key} 自动刷新平台 token 失败: {relogin_err}")

                if not relogin_success:
                    if env:
                        env.token = None
                        env.status = "disconnected"
                    await db.commit()
                    step_exception = HTTPException(status_code=401, detail=APAAS_TOKEN_EXPIRED_STEP)
            else:
                # 编码冲突时自动处理
                is_dict_or_role_step = step_key.startswith("create_dict:") or step_key.startswith("create_role:") or step_key == "create_roles_dicts"
                is_model_step = step_key.startswith("create_model:")
                is_form_step = step_key.startswith("create_form:")
                is_duplicate = any(kw in error_msg for kw in ["编码重复", "已存在", "duplicate"])

                if is_dict_or_role_step and is_duplicate:
                    # 字典/角色：编码已存在直接复用，视同该步骤完成。
                    # 统一返回 completed（schema 文档允许值 completed|error|conflict），
                    # 避免歧义的 "ok" —— 前端 execute 仅区分 conflict/error，其余按成功处理，
                    # 且该步骤已写入 steps_completed，下次拉取状态即显示已完成。
                    logger.info(f"步骤 {step_key} 编码已存在，自动跳过（复用）: {error_msg}")
                    state.setdefault("steps_completed", []).append(step_key)
                    state.get("step_errors", {}).pop(step_key, None)
                    _save_state(app, state)
                    step_response = StepExecuteResponse(step=step_key, status="completed", error=None)
                elif (is_model_step or is_form_step) and is_duplicate:
                    # 模型/表单：不要自动改名，直接回到左侧对话区等待用户确认
                    logger.info(f"步骤 {step_key} 编码冲突，等待用户确认新编码: {error_msg}")
                    conflict = _detect_code_conflict(error_msg, step_key, data, models)
                    state.setdefault("step_errors", {})[step_key] = error_msg
                    _save_state(app, state)
                    step_response = StepExecuteResponse(
                        step=step_key,
                        status="conflict",
                        error=error_msg,
                        conflict=conflict,
                    )
                else:
                    # 其他错误：原样报错
                    conflict = _detect_code_conflict(error_msg, step_key, data, models)
                    if conflict:
                        state.setdefault("step_errors", {})[step_key] = error_msg
                        _save_state(app, state)
                        step_response = StepExecuteResponse(step=step_key, status="conflict", error=error_msg, conflict=conflict)
                    else:
                        state.setdefault("step_errors", {})[step_key] = error_msg
                        _save_state(app, state)
                        step_response = StepExecuteResponse(step=step_key, status="error", error=error_msg)

        finally:
            # 持久化 API 调用日志
            try:
                logs = flush_call_logs()
                if logs:
                    for log_entry in logs:
                        db.add(ApiCallLog(
                            tenant_id=ctx.tenant_id,
                            user_id=ctx.user.id,
                            application_id=app.id,
                            step_key=step_key,
                            **log_entry,
                        ))
            except Exception as log_err:
                logger.warning(f"持久化 API 调用日志失败: {log_err}")

            await db.commit()

        if step_exception:
            raise step_exception
        return step_response


async def _execute_step_impl(
    client, app: Application, config: dict, state: dict,
    step_key: str, data: dict, models: list,
) -> dict:
    """路由到具体步骤函数。"""
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id
    suffix = state.get("suffix", "")

    if step_key == "create_app":
        result = await execute_create_app(client, app.app_name, app.app_code, app.description or "")
        state["apaas_app_id"] = result["apaas_app_id"]
        state["platform_app_code"] = result.get("platform_app_code") or app.app_code
        state["suffix"] = result["suffix"]
        app.apaas_app_id = result["apaas_app_id"]
        if result.get("platform_app_code"):
            app.app_code = result["platform_app_code"]
        return result

    elif step_key == "create_roles_dicts":
        # 兼容旧步骤
        result = await execute_create_roles_dicts(
            client, apaas_app_id,
            data.get("roles", []), data.get("dicts", []), suffix,
        )
        state["dict_codes"] = result["dict_codes"]
        state["role_codes"] = result.get("role_codes", {})
        return result

    elif step_key.startswith("create_role:"):
        idx = int(step_key.split(":")[1])
        roles = data.get("roles", [])
        if idx >= len(roles):
            raise ValueError(f"角色索引 {idx} 超出范围")
        r = roles[idx]
        from app.step_executor import _apply_suffix, _sanitize_code
        original_code = r.get("code", r["name"])
        platform_code = _apply_suffix(_sanitize_code(original_code), suffix)
        try:
            await client.create_roles(apaas_app_id, [{
                "appId": apaas_app_id,
                "roleCode": platform_code,
                "roleName": r["name"],
            }])
        except Exception as e:
            if "已存在" not in str(e) and "重复" not in str(e):
                raise
        role_info = {"roleCode": platform_code, "roleName": r["name"]}
        try:
            remote_roles = await client.query_roles(apaas_app_id)
            matched = next((
                item for item in remote_roles
                if item.get("roleCode") == platform_code or item.get("roleName") == r.get("name")
            ), None)
            if matched:
                role_info.update({
                    "id": matched.get("id", ""),
                    "roleCode": matched.get("roleCode", platform_code),
                    "roleName": matched.get("roleName", r["name"]),
                })
        except Exception as e:
            logger.warning("创建角色后回查角色 id 失败: %s", e)
        state.setdefault("role_codes", {})[original_code] = role_info
        return {"role": r["name"], "code": role_info.get("roleCode", platform_code), "id": role_info.get("id", "")}

    elif step_key.startswith("create_dict:"):
        idx = int(step_key.split(":")[1])
        dicts_list = data.get("dicts", [])
        if idx >= len(dicts_list):
            raise ValueError(f"字典索引 {idx} 超出范围")
        d = dicts_list[idx]
        from app.step_executor import _apply_suffix, _sanitize_code
        # 查询已有字典
        existing = {dd.get("dictionaryName"): dd for dd in await client.query_dicts(apaas_app_id)}
        ed = existing.get(d["name"])
        if ed:
            pc = ed["dictionaryCode"]
            state.setdefault("dict_codes", {})[d["name"]] = pc
            state["dict_codes"][d.get("code", d["name"])] = pc
        else:
            dc = _apply_suffix(_sanitize_code(d.get('code', 'dict')), suffix)
            state.setdefault("dict_codes", {})[d["name"]] = dc
            state["dict_codes"][d.get("code", d["name"])] = dc
            try:
                await client.create_dicts(apaas_app_id, [{
                    "appId": apaas_app_id,
                    "dictionaryName": d["name"],
                    "dictionaryCode": dc,
                    "dictionaryType": "CUSTOM",
                }])
            except Exception as e:
                if "重复" in str(e) or "已存在" in str(e) or "duplicate" in str(e).lower():
                    # 编码重复，尝试按名称或编码查找已有字典并复用
                    logger.warning(f"字典编码冲突，尝试复用: {d['name']} ({dc})")
                    refreshed = {dd.get("dictionaryName"): dd for dd in await client.query_dicts(apaas_app_id)}
                    # 按名称查
                    found = refreshed.get(d["name"])
                    if not found:
                        # 按编码查
                        found = next((dd for dd in refreshed.values() if dd.get("dictionaryCode") == dc), None)
                    if found:
                        pc = found["dictionaryCode"]
                        state["dict_codes"][d["name"]] = pc
                        state["dict_codes"][d.get("code", d["name"])] = pc
                        logger.info(f"复用已有字典: {d['name']} -> {pc}")
                    else:
                        raise
                else:
                    raise
        # 创建选项
        if d.get("options"):
            final_code = state["dict_codes"].get(d["name"], "")
            all_dicts = await client.query_dicts(apaas_app_id)
            dict_obj = next((dd for dd in all_dicts if dd.get("dictionaryCode") == final_code), None)
            if dict_obj:
                dict_id = dict_obj.get("id")
                # 按名称和编码建索引
                existing_by_name = {o.get("optionName"): o for o in dict_obj.get("options", [])}
                existing_by_code = {o.get("valueCode"): o for o in dict_obj.get("options", [])}
                for i, o in enumerate(d["options"]):
                    oc = _sanitize_code(o.get("code", o["name"]))
                    if o["name"] in existing_by_name:
                        continue  # 名称完全匹配，跳过
                    existing_opt = existing_by_code.get(oc)
                    if existing_opt:
                        # 编码相同但名称不同 → 更新选项名
                        opt_id = existing_opt.get("id")
                        if opt_id and existing_opt.get("optionName") != o["name"]:
                            try:
                                await client._post_resource(
                                    "/dataDictionary/edit/dictionaryValue/fromApp",
                                    {"id": opt_id, "appId": apaas_app_id,
                                     "dictionaryId": dict_id, "valueCode": oc,
                                     "valueName": o["name"], "valueStatus": "ENABLE",
                                     "displayOrder": i},
                                    app_id=apaas_app_id)
                                logger.info(f"更新字典选项: {existing_opt.get('optionName')} → {o['name']}")
                            except Exception as ue:
                                logger.warning(f"更新字典选项 {o['name']} 失败: {ue}")
                    else:
                        # 新选项 → 添加
                        await client.add_dict_option(apaas_app_id, dict_id, oc, o["name"], display_order=i)
        return {"dict": d["name"], "options": len(d.get("options", []))}

    elif step_key.startswith("create_model:"):
        idx = int(step_key.split(":")[1])
        if idx >= len(models):
            raise ValueError(f"模型索引 {idx} 超出范围")
        result = await execute_create_model(client, apaas_app_id, models[idx], idx, suffix)
        # 合并 model_info
        state.setdefault("model_info", {})
        state["model_info"].update(result["model_info_entries"])
        return result

    elif step_key.startswith("create_form:"):
        idx = int(step_key.split(":")[1])
        forms = data.get("forms", []) or []
        if idx >= len(forms):
            raise ValueError(f"表单索引 {idx} 超出范围")
        dict_codes = state.get("dict_codes", {})
        model_info = state.get("model_info", {})
        form_def = forms[idx]
        existing_form_results = state.get("form_results", [])
        result = await execute_create_form(
            client, apaas_app_id, form_def, idx,
            dict_codes, model_info, models,
            all_forms=forms,
            form_results=existing_form_results,
        )
        _upsert_form_result(state, {
            "formId": result.get("formId", ""),
            "formCode": result.get("formCode", ""),
            "formName": result.get("formName", ""),
            "modelCode": _first_form_value(
                form_def,
                "modelCode",
                "model_code",
                "mainModelCode",
                "main_model_code",
                "main_model",
            ),
            "menuId": result.get("menuId", ""),
        })
        return result

    elif step_key.startswith("create_workflow:"):
        idx = int(step_key.split(":")[1])
        workflows = data.get("workflows", [])
        if idx >= len(workflows):
            raise ValueError(f"流程索引 {idx} 超出范围")
        form_results = state.get("form_results", [])
        role_codes = state.get("role_codes", {})
        return await execute_create_workflow(client, apaas_app_id, workflows[idx], form_results, role_codes)

    elif step_key == "configure_permissions":
        form_results = state.get("form_results", [])
        permissions = data.get("permissions", [])
        role_codes = state.get("role_codes", {})
        forms = data.get("forms", [])
        return await execute_configure_permissions(client, apaas_app_id, permissions, form_results, role_codes, forms)

    else:
        raise ValueError(f"未知步骤: {step_key}")


# ------------------------------------------------------------------
# POST /reset
# ------------------------------------------------------------------

@router.post("/applications/{app_id}/steps/reset")
async def reset_step(
    app_id: int,
    body: StepResetRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = await _get_app(app_id, ctx, db)
    state = _load_state(app)

    if body.step:
        # 重置单个步骤
        completed = state.get("steps_completed", [])
        if body.step in completed:
            completed.remove(body.step)
        state.get("step_errors", {}).pop(body.step, None)
        # 重置特定步骤时清除关联数据
        if body.step == "create_app":
            app.apaas_app_id = None
            state.pop("apaas_app_id", None)
            state.pop("suffix", None)
        elif body.step == "create_roles_dicts":
            state.pop("dict_codes", None)
            state.pop("role_codes", None)
    else:
        # 重置全部
        state = {"steps_completed": [], "step_errors": {}}
        app.apaas_app_id = None

    _save_state(app, state)
    app.status = "draft"
    await db.commit()
    return {"ok": True}


# ------------------------------------------------------------------
# POST /resolve-conflict
# ------------------------------------------------------------------

def _replace_code_in_obj(obj, old_code: str, new_code: str):
    """递归遍历 dict/list，将所有值等于 old_code 的字符串替换为 new_code。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v == old_code:
                obj[k] = new_code
            elif isinstance(v, str) and "." in v:
                head, tail = v.split(".", 1)
                if head == old_code:
                    obj[k] = f"{new_code}.{tail}"
            elif isinstance(v, (dict, list)):
                _replace_code_in_obj(v, old_code, new_code)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and item == old_code:
                obj[i] = new_code
            elif isinstance(item, str) and "." in item:
                head, tail = item.split(".", 1)
                if head == old_code:
                    obj[i] = f"{new_code}.{tail}"
            elif isinstance(item, (dict, list)):
                _replace_code_in_obj(item, old_code, new_code)


@router.post("/applications/{app_id}/resolve-conflict")
async def resolve_conflict(
    app_id: int,
    body: ResolveConflictRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """编码冲突修复：将 config_preview 中 old_code 替换为 new_code，并更新所有引用。"""
    app = await _get_app(app_id, ctx, db)
    config = _load_config(app)
    data = config.get("data", config)

    old_code = body.old_code
    new_code = body.new_code

    if old_code == new_code:
        raise HTTPException(status_code=400, detail="新编码不能和旧编码相同")
    if not new_code.strip():
        raise HTTPException(status_code=400, detail="新编码不能为空")

    # 1. 在 models 中查找并替换主 code
    models = data.get("models", [])
    found = False
    for m in models:
        if m.get("code") == old_code:
            m["code"] = new_code
            found = True
        # 替换字段中引用该 code 的地方（如 ref 关联）
        for f in m.get("fields", []):
            if isinstance(f.get("ref"), str) and f["ref"] == old_code:
                f["ref"] = new_code
            elif isinstance(f.get("ref"), dict) and f["ref"].get("model") == old_code:
                f["ref"]["model"] = new_code

    # 2. 在 dicts 中查找并替换
    for d in data.get("dicts", []):
        if d.get("code") == old_code:
            d["code"] = new_code
            found = True

    # 3. 在 roles 中查找并替换
    for r in data.get("roles", []):
        if r.get("code") == old_code:
            r["code"] = new_code
            found = True

    # 4. 在 workflows 中替换引用
    for wf in data.get("workflows", []):
        if wf.get("form") == old_code:
            wf["form"] = new_code
        # 替换 nodes 中的引用
        _replace_code_in_obj(wf.get("nodes", []), old_code, new_code)

    # 5. 在 permissions 中替换引用
    for perm in data.get("permissions", []):
        if perm.get("role") == old_code:
            perm["role"] = new_code
        forms = perm.get("forms", [])
        for fp in forms:
            if fp.get("form") == old_code:
                fp["form"] = new_code

    if not found:
        raise HTTPException(status_code=404, detail=f"未找到编码 {old_code} 对应的模型/字典/角色")

    # 6. 全局同步更新所有引用
    # 例如：forms[].modelCode / allModelCodes / components[].modelCode / tableModelCode / modelField
    # 以及 permissions / workflows / meta 中仍残留的旧编码引用。
    _replace_code_in_obj(data, old_code, new_code)

    # 7. 记录编码映射到 meta
    meta = data.setdefault("meta", {})
    code_remaps = meta.setdefault("code_remaps", {})
    code_remaps[old_code] = new_code

    # 8. 保存更新后的 config_preview
    app.config_preview = _dump_preview_config(config)

    # 9. 清除该步骤的错误状态，让重试可以执行
    state = _load_state(app)
    state.get("step_errors", {}).pop(body.step, None)
    _save_state(app, state)

    # 10. 如果有文档版本，覆盖当前版本，避免一次创建过程产生多条中间版
    doc_version_id = None
    if app.current_doc_version:
        from app.models import DocumentVersion
        import hashlib
        config_json = json.dumps(config, ensure_ascii=False)
        rendered_doc = _render_design_doc_markdown(app.app_name, app.app_code, data)
        version_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.application_id == app.id,
                DocumentVersion.version == app.current_doc_version,
            )
        )
        dv = version_result.scalar_one_or_none()
        if dv:
            dv.filename = f"{app.app_name or '设计文档'}-V{app.current_doc_version}.md"
            dv.content_hash = hashlib.sha256(config_json.encode()).hexdigest()
            dv.raw_content = rendered_doc
            dv.parsed_config = config_json
            dv.summary = f"初始版本（已完成编码冲突修复：{old_code} → {new_code}）"
            doc_version_id = dv.id

    await db.commit()

    return {
        "ok": True,
        "old_code": old_code,
        "new_code": new_code,
        "step": body.step,
        "doc_version": doc_version_id,
        "app_name": app.app_name,
        "app_code": app.app_code,
        "config_preview": config,
        "message": f"编码已从 {old_code} 更新为 {new_code}，请重试该步骤",
    }
