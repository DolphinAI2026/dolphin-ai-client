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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt_password
from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, User, ApiCallLog
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["生成步骤"])

# 临时关闭审批流程创建步骤，避免部署链路被当前流程配置问题阻塞。
WORKFLOW_STEPS_ENABLED = False

_COMPONENT_TYPE_LABELS = {
    "FORM_DOCUMENT_NUMBER": "单据号",
    "FORM_TEXT_INPUT": "单行输入",
    "FORM_TEXTAREA_INPUT": "多行输入",
    "FORM_TEXTAREA": "多行输入",
    "FORM_PHONE_INPUT": "手机号码",
    "FORM_EMAIL_INPUT": "电子邮箱",
    "FORM_SELECT_INPUT_SINGLE": "下拉单选",
    "FORM_SELECT_INPUT": "下拉多选",
    "FORM_SELECT": "下拉单选",
    "FORM_SELECT_MULTI": "下拉多选",
    "FORM_DATA_SELECTOR_SINGLE": "数据单选",
    "FORM_DATA_SELECTOR": "数据选择",
    "FORM_DATEPICK_INPUT": "日期时间",
    "FORM_DATE_PICKER": "日期时间",
    "FORM_MONEY_INPUT": "金额",
    "FORM_NUMBER_INPUT": "数字",
    "FORM_FILE_UPLOAD": "附件上传",
    "FORM_UPLOAD": "附件上传",
    "FORM_SWITCH_SELECT": "开关",
    "FORM_SWITCH": "开关",
    "FORM_PEOPLE_SELECT": "人员选择",
    "FORM_USER_SELECT": "人员选择",
    "FORM_DEPARTMENT_SELECT": "部门选择",
    "FORM_DEPT_SELECT": "部门选择",
    "FORM_WIDGET_LOCATION": "地理位置",
    "FORM_WIDGET_SON_TABLE": "子表",
    "FORM_RADIO_INPUT": "单选框",
    "FORM_RADIO": "单选框",
    "FORM_CHECKBOX_INPUT": "复选框",
    "FORM_CHECKBOX": "复选框",
    "FORM_RICH_TEXT": "富文本",
    "FORM_HYPERLINK_INPUT": "超链接",
    "FORM_LINK": "超链接",
    "FORM_IDCARD_INPUT": "身份证号",
    "FORM_ID_CARD": "身份证号",
    "FORM_WIDGET_AREA": "地区地址",
    "FORM_LOCATION": "地理位置",
    "FORM_ADDRESS": "地区地址",
    "FORM_ASSOCIATION": "关联表单",
    "FORM_SERIAL": "单据号",
}


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _load_state(app: Application) -> dict:
    if app.generation_state:
        state = json.loads(app.generation_state) if isinstance(app.generation_state, str) else app.generation_state
    else:
        state = {"steps_completed": [], "step_errors": {}}
        # 仅首次（无 generation_state）时兼容旧流程
        if app.apaas_app_id:
            state["steps_completed"].append("create_app")
            state["apaas_app_id"] = app.apaas_app_id
    return state


def _save_state(app: Application, state: dict):
    app.generation_state = json.dumps(state, ensure_ascii=False)


def _load_config(app: Application) -> dict:
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空，请先在对话中生成配置")
    return json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview


def _component_type_label(value: str, model_type: str = "") -> str:
    raw = str(value or "").strip()
    model_label = str(model_type or "").strip()
    label = _COMPONENT_TYPE_LABELS.get(raw, raw)
    if not label:
        return model_label or ""
    if label == "单行输入" and model_label and model_label != "单行输入":
        return model_label
    return label


def _field_ref_meta(field_meta: dict) -> tuple[str, str, str]:
    ref = field_meta.get("ref") or {}
    association = field_meta.get("formAssociationConfig") or field_meta.get("form_association_config") or {}
    if isinstance(association, dict) and association.get("targetModelCode"):
        return (
            str(association.get("targetModelCode") or ""),
            str(association.get("targetFieldCode") or ""),
            str(association.get("originFieldCode") or ""),
        )
    if isinstance(ref, dict):
        return (
            str(ref.get("model") or ""),
            str(ref.get("display_field") or ref.get("target_field") or ref.get("field") or ""),
            "",
        )
    return "", "", ""


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
        str(form.get("modelCode") or "").strip(),
        str(form.get("model_code") or "").strip(),
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
    roles = data.get("roles", []) or []
    dicts = data.get("dicts", []) or []
    models = data.get("models", []) or []
    permissions = data.get("permissions", []) or []
    models_by_code, fields_by_model = _build_model_maps(models)
    app_description = str(data.get("description") or data.get("appDescription") or data.get("remark") or "").strip()

    lines: list[str] = [
        "# 应用设计文档",
        "",
        "## 一、应用信息",
        "",
        "| 项目 | 内容 |",
        "|---|---|",
        f"| 应用名称 | {app_name or ''} |",
        f"| 应用编码 | {app_code or ''} |",
        f"| 说明 | {app_description} |",
        "",
        "---",
        "",
        "## 二、角色列表",
        "",
        "| 角色编码 | 角色名称 |",
        "|---|---|",
    ]
    if roles:
        lines.extend([f"| {r.get('code', '')} | {r.get('name', '')} |" for r in roles])
    else:
        lines.append("|  |  |")

    lines.extend(["", "---", "", "## 三、数据字典", ""])
    if dicts:
        for idx, item in enumerate(dicts, start=1):
            lines.extend([
                f"### 3.{idx} {item.get('name') or item.get('code') or f'字典{idx}'}",
                "",
                "| 字典编码 | 字典名称 |",
                "|---|---|",
                f"| {item.get('code', '')} | {item.get('name', '')} |",
                "",
                "| 选项编码 | 选项名称 |",
                "|---|---|",
            ])
            options = item.get("options") or item.get("values") or []
            if options:
                for option in options:
                    if isinstance(option, str):
                        lines.append(f"|  | {option} |")
                    else:
                        lines.append(f"| {option.get('code') or option.get('item_code') or ''} | {option.get('name') or option.get('item_name') or ''} |")
            else:
                lines.append("|  |  |")
            lines.append("")
    else:
        lines.append("暂无")
        lines.append("")

    lines.extend(["---", "", "## 四、数据模型", ""])
    if models:
        lines.extend([
            "### 4.1 模型定义",
            "",
            "| 模型编码 | 模型名称 |",
            "|---|---|",
        ])
        lines.extend([
            f"| {model.get('code', '')} | {model.get('name', '')} |"
            for model in models
        ] or ["|  |  |"])
        lines.extend([
            "",
            "### 4.2 模型字段",
            "",
            "| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |",
            "|---|---|---|---|---|",
        ])
        model_field_rows: list[str] = []
        for model in models:
            for field in (model.get("fields") or []):
                database_field_type = (
                    field.get("database_field_type")
                    or field.get("databaseFieldType")
                    or field.get("db_type")
                    or field.get("field_type")
                    or ""
                )
                length_or_precision = (
                    field.get("max_length")
                    or field.get("maxLength")
                    or field.get("length")
                    or field.get("precision")
                    or ""
                )
                model_field_rows.append(
                    f"| {model.get('code', '')} | {field.get('code', '')} | {field.get('name', '')} | {database_field_type} | {length_or_precision} |"
                )
        lines.extend(model_field_rows or ["|  |  |  |  |  |"])
        lines.append("")
    else:
        lines.append("暂无")
        lines.append("")

    lines.extend(["---", "", "## 五、表单定义", ""])
    form_defs = _iter_form_definitions(data, models)
    form_name_by_code: dict[str, str] = {}
    if form_defs:
        form_summary_rows: list[str] = []
        main_field_rows: list[str] = []
        sub_region_rows: list[str] = []
        sub_field_rows: list[str] = []
        for idx, form in enumerate(form_defs, start=1):
            form_name = form.get("formName") or form.get("form_name") or form.get("name") or form.get("code") or f"表单{idx}"
            form_code = form.get("formCode") or form.get("form_code") or form.get("code") or ""
            model_code = form.get("modelCode") or form.get("model_code") or form.get("bindModelCode") or form.get("code") or ""
            if form_code:
                form_name_by_code[str(form_code)] = str(form_name)
            if model_code:
                form_name_by_code[str(model_code)] = str(form_name)
            form_summary_rows.append(
                f"| {form_code} | {form_name} | {model_code} | {form.get('description') or form.get('remark') or ''} |"
            )
            components = form.get("components") or form.get("formComponents") or form.get("fields") or []
            main_components = [comp for comp in components if not _is_sub_table_component(comp)]
            sub_tables = [comp for comp in components if _is_sub_table_component(comp)]
            if main_components:
                for component in main_components:
                    field_code = str(component.get("code") or _field_code_from_model_field(component.get("modelField", ""))).strip()
                    field_meta = fields_by_model.get(str(model_code).strip(), {}).get(field_code, {})
                    ref_model_code, ref_field_code, origin_field_code = _field_ref_meta_from_component(
                        component,
                        field_meta,
                        models_by_code,
                        fields_by_model,
                        form_name_by_code,
                    )
                    main_field_rows.append(
                        f"| {form_name} | {field_code} | {component.get('label') or component.get('name') or field_meta.get('name', '')} | "
                        f"{_component_type_label(component.get('componentType') or component.get('component_type'), field_meta.get('type', ''))} | "
                        f"{_bool_label(component.get('required'))} | {_bool_label(component.get('hidden'))} | {_bool_label(component.get('readonly') or component.get('readOnly'))} | "
                        f"{_bool_label(component.get('showInList') or component.get('list_visible'))} | {_bool_label(component.get('searchable') or component.get('queryable'))} | "
                        f"{component.get('dict_code') or component.get('dictCode') or component.get('dict') or field_meta.get('dict_code') or field_meta.get('dict') or ''} | {ref_model_code} | {ref_field_code} | {origin_field_code} | "
                        f"{component.get('description') or field_meta.get('description', '')} |"
                    )
            if sub_tables:
                for sub_table in sub_tables:
                    table_model_code = str(sub_table.get("tableModelCode") or sub_table.get("table_model_code") or "").strip()
                    sub_model = models_by_code.get(table_model_code, {})
                    sub_model_name = sub_model.get("name", "")
                    sub_label = sub_table.get("label") or sub_table.get("name") or sub_model_name or table_model_code
                    sub_region_rows.append(
                        f"| {form_name} | {sub_label} | {table_model_code} | {sub_table.get('description') or ''} |"
                    )
                    table_columns = sub_table.get("tableColumn") or sub_table.get("table_column") or []
                    if table_columns:
                        sub_fields = fields_by_model.get(table_model_code, {})
                        for column in table_columns:
                            column_code = str(column.get("code") or _field_code_from_model_field(column.get("modelField", ""))).strip()
                            field_meta = sub_fields.get(column_code, {})
                            ref_model_code, ref_field_code, origin_field_code = _field_ref_meta_from_component(
                                column,
                                field_meta,
                                models_by_code,
                                fields_by_model,
                                form_name_by_code,
                            )
                            sub_field_rows.append(
                                f"| {form_name} | {sub_label} | {column_code} | {column.get('label') or column.get('name') or field_meta.get('name', '')} | "
                                f"{_component_type_label(column.get('componentType') or column.get('component_type'), field_meta.get('type', ''))} | "
                                f"{_bool_label(column.get('required'))} | {_bool_label(column.get('hidden'))} | {_bool_label(column.get('readonly') or column.get('readOnly'))} | "
                                f"{_bool_label(column.get('showInList') or column.get('list_visible'))} | {_bool_label(column.get('searchable') or column.get('queryable'))} | "
                                f"{column.get('dict_code') or column.get('dictCode') or column.get('dict') or field_meta.get('dict_code') or field_meta.get('dict') or ''} | {ref_model_code} | {ref_field_code} | {origin_field_code} | "
                                f"{column.get('description') or field_meta.get('description', '')} |"
                            )
        lines.extend([
            "### 5.1 表单清单",
            "",
            "| 表单编码 | 表单名称 | 绑定主表模型 | 说明 |",
            "|---|---|---|---|",
        ])
        lines.extend(form_summary_rows or ["|  |  |  |  |"])
        lines.extend([
            "",
            "### 5.2 主表字段定义",
            "",
            "| 表单名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        lines.extend(main_field_rows or ["|  |  |  |  | 否 | 否 | 否 | 否 | 否 |  |  |  |  |  |"])
        lines.extend([
            "",
            "### 5.3 子表区域定义",
            "",
            "| 表单名称 | 子表区域名称 | 绑定模型 | 说明 |",
            "|---|---|---|---|",
        ])
        lines.extend(sub_region_rows or ["|  |  |  |  |"])
        lines.extend([
            "",
            "### 5.4 子表字段定义",
            "",
            "| 表单名称 | 子表区域名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        lines.extend(sub_field_rows or ["|  |  |  |  |  | 否 | 否 | 否 | 否 | 否 |  |  |  |  |  |"])
    else:
        lines.append("暂无")
        lines.append("")

    lines.extend(["---", "", "## 六、权限定义", "", "| 表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |", "|---|---|---|---|---|---|---|---|---|---|"])
    if permissions:
        for perm in permissions:
            form_code = perm.get("form_code") or perm.get("table_code") or perm.get("code") or perm.get("form") or ""
            form_name = form_name_by_code.get(form_code) or form_code
            role_rows = perm.get("roles") or perm.get("rules") or perm.get("permissions") or []
            if not role_rows:
                lines.append(f"| {form_name} |  | 否 | 否 | 否 | 否 | 否 | 否 | 否 |  |")
                continue
            for role in role_rows:
                raw_actions = role.get("actions") or role.get("operations") or role.get("permissions") or role.get("op") or []
                if isinstance(raw_actions, str):
                    actions = {item.strip() for item in raw_actions.split(",") if item.strip()}
                else:
                    actions = {str(action).strip() for action in raw_actions}
                is_all = "all" in actions
                can_draft = bool(role.get("canDraft")) or "draft" in actions or "stash" in actions or "save" in actions
                can_import = bool(role.get("canImport")) or "import" in actions
                can_export = bool(role.get("canExport")) or "export" in actions
                lines.append(
                    f"| {form_name} | {role.get('role_code') or role.get('roleCode') or role.get('code') or role.get('role') or ''} | "
                    f"{'是' if can_draft else '否'} | "
                    f"{'是' if is_all or 'add' in actions or '新增' in actions or 'create' in actions else '否'} | "
                    f"{'是' if can_import else '否'} | "
                    f"{'是' if is_all or 'view' in actions or '查看' in actions or 'read' in actions else '否'} | "
                    f"{'是' if is_all or 'edit' in actions or '编辑' in actions or 'update' in actions else '否'} | "
                    f"{'是' if is_all or 'delete' in actions or '删除' in actions else '否'} | "
                    f"{'是' if can_export else '否'} | "
                    f"{_data_scope_label(role.get('data_scope') or role.get('scope') or role.get('dataScope') or role.get('data') or '')} |"
                )
    else:
        lines.append("|  |  | 否 | 否 | 否 | 否 | 否 | 否 | 否 |  |")

    return "\n".join(lines).strip() + "\n"

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
        form_model_code = str(form.get("modelCode", form.get("model_code", ""))).strip()
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
            key=key, label=f"创建表单: {form.get('name', form.get('formName', f'表单{idx}'))}",
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


def _sync_platform_codes_to_config(app: Application, state: dict, data: dict):
    """部署完成后，将平台真实编码回写到 config_preview"""
    try:
        config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
        cfg_data = config.get("data", config)

        # 回写平台最终应用编码
        platform_app_code = str(
            state.get("platform_app_code")
            or cfg_data.get("appCode")
            or cfg_data.get("app_code")
            or app.app_code
            or ""
        ).strip()
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

        config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
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

@router.get("/applications/{app_id}/steps/status", response_model=GenerationStatusResponse)
async def get_step_status(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = await _get_app(app_id, ctx, db)
    config = _load_config(app)
    state = _load_state(app)
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id
    steps = _build_steps(config, state, apaas_app_id)
    return GenerationStatusResponse(
        apaas_app_id=apaas_app_id,
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
    config = _load_config(app)
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
            except Exception:
                pass

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
            if "Token已过期" in error_msg or "401" in error_msg:
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
                    step_exception = HTTPException(status_code=401, detail="APaaS平台Token已过期，请在环境管理中重新登录")
            else:
                # 编码冲突时自动处理
                is_dict_or_role_step = step_key.startswith("create_dict:") or step_key.startswith("create_role:") or step_key == "create_roles_dicts"
                is_model_step = step_key.startswith("create_model:")
                is_form_step = step_key.startswith("create_form:")
                is_duplicate = any(kw in error_msg for kw in ["编码重复", "已存在", "duplicate"])

                if is_dict_or_role_step and is_duplicate:
                    # 字典/角色：直接复用
                    logger.info(f"步骤 {step_key} 编码已存在，自动跳过: {error_msg}")
                    state.setdefault("steps_completed", []).append(step_key)
                    state.get("step_errors", {}).pop(step_key, None)
                    _save_state(app, state)
                    step_response = StepExecuteResponse(step=step_key, status="ok", error=None)
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
        state.setdefault("role_codes", {})[original_code] = {"roleCode": platform_code, "roleName": r["name"]}
        return {"role": r["name"], "code": platform_code}

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
        state.setdefault("form_results", [])
        state["form_results"].append({
            "formId": result.get("formId", ""),
            "formCode": result.get("formCode", ""),
            "formName": result.get("formName", ""),
            "modelCode": form_def.get("modelCode") or form_def.get("model_code") or "",
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
