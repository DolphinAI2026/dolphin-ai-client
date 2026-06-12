"""aPaaS 应用生成器

执行流程:
  Phase 0  解析配置
  Phase 1  创建公共资源（角色 + 数据字典）
  Phase 2  创建数据模型
  Phase 3  创建表单 + 绑定字典
  Phase 4  配置权限
  Phase 5  创建审批流程（可选，非核心，失败不阻断）
"""
from __future__ import annotations

import copy
import hashlib
import logging
import random
import re
import string
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from app.apaas_client import APaaSClient
from app.config import settings
from app.form_component_sanitizer import sync_form_components_with_model_fields
from app.workflow_phase import create_workflows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

# id / 字段编码工具迁移到 operations 层，这里 re-export 保持向后兼容
# （step_executor.py / incremental_executor.py 仍 from app.generator_v2 import _rand 等）
from app.operations.identifiers import (  # noqa: F401
    _RESERVED,
    _rand,
    _apply_suffix,
    _sanitize_code,
    _safe_field_code,
)

# 表单配置原子工具同样迁移到 operations 层（5 个此前两份逐字相同的实现），
# 这里 re-export 保持 `from app.generator_v2 import _iter_form_components` 等历史引用可用。
from app.operations.form_config import (  # noqa: F401
    _iter_form_components,
    _component_field_code,
    _clone_for_form_config_permissions,
    _normalize_permission_range,
    _query_saveable_form_config,
)
# 组件↔字典绑定解析收敛到 operations 层，两条路径共用（保证 dict_codes 翻译语义一致）。
from app.operations.dict_binding import resolve_component_dict_code  # noqa: F401


# ---------------------------------------------------------------------------
# 类型映射（从集中注册表派生）
# ---------------------------------------------------------------------------

from app.field_types import get_field_type_map, get_comp_type_map, select_choose_type_for_component

FIELD_TYPE_MAP = get_field_type_map()
COMP_TYPE_MAP = get_comp_type_map()

_SELECT_COMPONENT_TYPES = {"FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT"}
_MULTI_SELECT_COMPONENT_TYPES = {"FORM_SELECT_INPUT"}


def _choose_type_for_select_component(component_type: str, component: Optional[dict] = None) -> str:
    return select_choose_type_for_component(component_type, component, multi_value="MULTIPLE")


# ---------------------------------------------------------------------------
# 辅助：解析平台模型 → fields 字典
# ---------------------------------------------------------------------------

from app.operations.identifiers import _extract_fields  # noqa: F401,E402 (re-export for back-compat)


def _permission_object_for_form_config(rule: dict, role_code_map: Dict[str, dict]) -> dict:
    role_code = str(rule.get("roleCode") or rule.get("role") or "").strip()
    if role_code and role_code != "all":
        role_info = role_code_map.get(role_code, {})
        role_id = str(role_info.get("id") or "").strip()
        role_code_value = str(role_info.get("roleCode") or role_code).strip()
        role_name = str(role_info.get("roleName") or rule.get("roleName") or role_code).strip()
        return {
            "permissionObjectType": "ROLE",
            "permissionObjectValue": role_id or role_code_value,
            "permissionObjectDisplayName": role_name,
        }
    return {
        "permissionObjectType": "ALL_USER",
        "permissionObjectValue": "",
        "permissionObjectDisplayName": "全部人员",
    }


def _parse_permission_ops(op_value: object) -> set[str]:
    if isinstance(op_value, str):
        return {part.strip() for part in op_value.split(",") if part.strip()}
    return {"all"}


def _build_permission_groups_for_form_config(
    rules: List[dict],
    role_code_map: Dict[str, dict],
) -> tuple[List[dict], List[dict], List[dict]]:
    permission_groups: List[dict] = []
    advanced_groups: List[dict] = []
    operation_groups: List[dict] = []

    for index, rule in enumerate(rules, start=1):
        perm_obj = _permission_object_for_form_config(rule, role_code_map)
        object_type = perm_obj["permissionObjectType"]
        object_value = perm_obj["permissionObjectValue"]
        object_name = perm_obj["permissionObjectDisplayName"]
        range_type = _normalize_permission_range(rule.get("data", "ALL"))
        ops = _parse_permission_ops(rule.get("op", "all"))
        can_view = "all" in ops or "view" in ops
        can_add = "all" in ops or "add" in ops
        can_edit = "all" in ops or "edit" in ops
        can_delete = "all" in ops or "delete" in ops
        can_import = bool(rule.get("canImport"))
        can_draft = bool(rule.get("canDraft"))
        can_export = bool(rule.get("canExport"))

        permission_groups.append({
            "groupConditions": [],
            "selectorFilterConditionList": [],
            "dataPermissions": [{
                "permissionType": object_type,
                "permissionValue": object_value,
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
                "addPermission": can_add,
            }],
        })

        advanced_groups.append({
            "permissionName": f"{object_name}权限",
            "permissionDescribe": "",
            "permissionOperationType": {
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
                "commentPermission": can_view,
                "dataSharePermission": can_view,
                "exportPermission": can_export,
                "logPermission": can_view,
                "printPermission": can_view,
                "queryApprovalInfoPermission": can_view,
            },
            "filterConditionGroups": [],
            "permissionObjects": [{
                "permissionObjectType": object_type,
                "permissionObjectValue": object_value,
                "permissionObjectDisplayName": object_name,
                "permissionRange": {"rangeType": range_type},
            }],
        })

        if any((can_add, can_import, can_draft)):
            operation_groups.append({
                "uuid": f"perm-op-{index}",
                "permissionName": f"{object_name}操作权限",
                "permissionDescribe": "",
                "permissionOperationType": {
                    "temporaryStoragePermission": can_draft,
                    "addPermission": can_add,
                    "importPermission": can_import,
                    "copyAddPermission": False,
                    "batchDeletePermission": False,
                    "batchRejectPermission": False,
                    "batchAgreePermission": False,
                    "shareFormPermission": False,
                    "processAnalysisPermission": False,
                },
                "permissionObjects": [{
                    "permissionObjectType": object_type,
                    "permissionObjectValue": object_value,
                    "permissionObjectDisplayName": object_name,
                }],
            })

    return permission_groups, advanced_groups, operation_groups


_STATE_CHANGED_MARKERS = ("页面状态已改变", "无法保存")


def _force_form_identity(
    form_config: dict,
    *,
    form_name: str,
    form_code: str,
    all_model_codes: List[str],
    app_id: str = "",
    form_id: str = "",
    menu_id: str = "",
) -> None:
    """save_form_config 前强制覆盖表单标识字段。

    平台 query_detail_page_config 在某些时机会返回 formName="我的待办"（默认占位值）。
    如果直接把这份配置存回去，会把建表时设置的真实表单名抹掉，所有表单都变成"我的待办"。
    """
    if not isinstance(form_config, dict):
        return
    desired_name = str(form_name or "").strip()
    desired_code = str(form_code or "").strip()
    desired_app_id = str(app_id or "").strip()
    desired_form_id = str(form_id or "").strip()
    desired_menu_id = str(menu_id or "").strip()
    desired_models = [str(c).strip() for c in (all_model_codes or []) if str(c).strip()]

    def _apply(target: dict) -> None:
        if not isinstance(target, dict):
            return
        if desired_name:
            target["formName"] = desired_name
        if desired_code:
            target["formCode"] = desired_code
        if desired_models:
            target["allModelCodes"] = desired_models
        if desired_app_id:
            target["appId"] = desired_app_id
        if desired_form_id and not target.get("id"):
            target["id"] = desired_form_id
        if desired_menu_id:
            target["menuId"] = desired_menu_id

    _apply(form_config)
    _apply(form_config.get("simpleFormConfig", {}))
    detail_page = form_config.setdefault("detailPage", {})
    if isinstance(detail_page, dict):
        _apply(detail_page)
        # ⚠️ 不要注入 webFormSettings / mobileFormSettings —— apaas 会把空 {} 展开成
        # formTitleConfigList 指向不存在的 "formName" 标题组件, 表单设计器加载时崩
        # (控制台报 renderLogic / engineContext null, 画布显"暂无数据"=字段渲染不出来)。
        # 原生 + 对话(build_apaas_feature_from_spec)建的表单都不带这俩, 交给 apaas 自处理。
        detail_page.setdefault("previewLanguage", "zh-CN")
        detail_page.setdefault("formVersionConfig", {})
    form_config.setdefault("formModelType", "DATABASE")


def _ensure_canvas_form_components(
    form_config: dict,
    fallback_components: Optional[List[dict]] = None,
) -> None:
    if not isinstance(form_config, dict):
        return
    detail_page = form_config.setdefault("detailPage", {})
    if not isinstance(detail_page, dict):
        form_config["detailPage"] = {}
        detail_page = form_config["detailPage"]

    components = detail_page.get("formComponents")
    if not isinstance(components, list):
        components = None
    if not components and fallback_components:
        components = copy.deepcopy(fallback_components)
    if components is None:
        return
    detail_page["formComponents"] = components

    def _prepare_component(component: dict, index_path: str) -> None:
        if not isinstance(component, dict):
            return
        if not str(component.get("uuid") or "").strip():
            field_code = str(component.get("modelField") or component.get("tableModelCode") or "").split(".")[-1]
            label = str(component.get("label") or component.get("name") or field_code or "component")
            base = _sanitize_code(label) or "component"
            component["uuid"] = f"{base}-{index_path}-{_rand(6)}"
        component.setdefault("componentType", "FORM_TEXT_INPUT")
        component.setdefault("width", 6)
        for column_index, column in enumerate(component.get("tableColumn", []) or [], start=1):
            _prepare_component(column, f"{index_path}-{column_index}")

    for index, component in enumerate(components, start=1):
        _prepare_component(component, str(index))


async def _save_form_config_with_retry(
    client: APaaSClient,
    app_id: str,
    form_config: dict,
    *,
    form_id: str,
    apply_latest=None,
    reason: str = "",
) -> None:
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            await client.save_form_config(app_id, form_config)
            return
        except Exception as exc:
            msg = str(exc)
            if any(marker in msg for marker in _STATE_CHANGED_MARKERS) and attempt == 0 and form_id:
                logger.warning("save_form_config 冲突，重查后重试 (formId=%s, reason=%s): %s", form_id, reason, msg)
                form_config = await _query_saveable_form_config(client, app_id, form_id)
                if apply_latest:
                    apply_latest(form_config)
                last_exc = exc
                continue
            raise
    if last_exc is not None:
        raise last_exc


async def _finalize_created_form_config(
    client: APaaSClient,
    app_id: str,
    *,
    form_id: str,
    form_name: str,
    form_code: str,
    all_model_codes: List[str],
    menu_id: str = "",
    form_components: Optional[List[dict]] = None,
) -> None:
    if not form_id:
        return

    def _apply_latest(config: dict) -> None:
        _force_form_identity(
            config,
            form_name=form_name,
            form_code=form_code,
            all_model_codes=all_model_codes,
            app_id=app_id,
            form_id=form_id,
            menu_id=menu_id,
        )
        _ensure_canvas_form_components(config, form_components)

    form_config = await _query_saveable_form_config(client, app_id, form_id)
    _apply_latest(form_config)
    logger.info("save_form_config reason: 创建后固化表单详情 (formId=%s, formName=%s)", form_id, form_name)
    await _save_form_config_with_retry(
        client,
        app_id,
        form_config,
        form_id=form_id,
        apply_latest=_apply_latest,
        reason="创建后固化表单详情",
    )


async def _sync_form_permissions_to_form_config(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    rules: List[dict],
    role_code_map: Dict[str, dict],
    form_name: str = "",
    form_code: str = "",
    all_model_codes: Optional[List[str]] = None,
    fallback_components: Optional[List[dict]] = None,
    menu_id: str = "",
) -> None:
    """回写表单权限到 formConfig。

    平台在并发场景下可能返回"当前页面状态已改变，无法保存"——此时重查再存一次，
    单次重试足以覆盖常见瞬时冲突；仍失败则把最新异常抛出（由调用方的 except 兜底）。

    重要：query_detail_page_config 返回的 formName 可能被平台覆盖成默认占位"我的待办"，
    save 前必须把建表时确定的 form_name/form_code/all_model_codes 强制写回去，
    否则所有表单的名字都会变成"我的待办"（参见 step_executor.py 同名函数注释）。
    """
    permission_groups, advanced_groups, operation_groups = _build_permission_groups_for_form_config(
        rules,
        role_code_map,
    )
    permission_groups = _clone_for_form_config_permissions(permission_groups)
    advanced_groups = _clone_for_form_config_permissions(advanced_groups)
    operation_groups = _clone_for_form_config_permissions(operation_groups)

    def _apply_latest(form_config: dict) -> None:
        permission_groups, advanced_groups, operation_groups = _build_permission_groups_for_form_config(
            rules,
            role_code_map,
        )
        permission_groups = _clone_for_form_config_permissions(permission_groups)
        advanced_groups = _clone_for_form_config_permissions(advanced_groups)
        operation_groups = _clone_for_form_config_permissions(operation_groups)
        form_config["permissionGroups"] = permission_groups
        form_config["advancedPermissionGroups"] = advanced_groups
        form_config["operationPermissionGroups"] = operation_groups
        detail_page = form_config.setdefault("detailPage", {})
        if isinstance(detail_page, dict):
            detail_page["permissionGroups"] = permission_groups
            detail_page["advancedPermissionGroups"] = advanced_groups
            detail_page["operationPermissionGroups"] = operation_groups
        _force_form_identity(
            form_config,
            form_name=form_name,
            form_code=form_code,
            all_model_codes=all_model_codes or [],
            app_id=app_id,
            form_id=form_id,
            menu_id=menu_id,
        )
        _ensure_canvas_form_components(form_config, fallback_components)

    form_config = await _query_saveable_form_config(client, app_id, form_id)
    _apply_latest(form_config)
    logger.info(
        "save_form_config reason: 回写表单权限 (formId=%s, formName=%s, permissionGroups=%s, advanced=%s, operation=%s)",
        form_id,
        form_name or "<unknown>",
        len(permission_groups),
        len(advanced_groups),
        len(operation_groups),
    )
    await _save_form_config_with_retry(
        client,
        app_id,
        form_config,
        form_id=form_id,
        apply_latest=_apply_latest,
        reason="回写表单权限",
    )


# ---------------------------------------------------------------------------
# 辅助：构建单个表单组件
# ---------------------------------------------------------------------------

def _build_component(
    field: dict,
    model_code: str,
    field_code: str,
    dict_codes: Dict[str, str],
    models: List[dict],
    model_info: dict,
) -> dict:
    ftype = field.get("type", "单行输入")
    comp: dict = {
        "componentType": COMP_TYPE_MAP.get(ftype, "FORM_TEXT_INPUT"),
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }

    # 必填属性
    if field.get("required"):
        comp["required"] = True
        comp["validators"] = [{"type": "REQUIRED", "message": f"{field['name']}不能为空"}]

    # 字典绑定
    if ftype in ("下拉单选", "下拉多选") and field.get("dict"):
        dcode = dict_codes.get(field["dict"])
        if dcode:
            if comp["componentType"] in _SELECT_COMPONENT_TYPES:
                comp["chooseType"] = _choose_type_for_select_component(comp["componentType"], comp)
            comp["dictionarySelectConfig"] = {
                "dictionaryCode": dcode,
                "dictionarySelectOptions": [],
            }

    # 数据选择器
    if ftype in ("数据单选", "数据选择", "数据多选") and field.get("ref"):
        ref = field["ref"]
        ref_model = ref.get("model", "") if isinstance(ref, dict) else str(ref)
        ref_field = ref.get("field", "") if isinstance(ref, dict) else ""
        # 按 code 和 name 都尝试匹配
        for ridx, rm in enumerate(models):
            if rm.get("name") == ref_model or rm.get("code") == ref_model:
                ref_mi = model_info.get(ridx)
                if ref_mi:
                    # 解析显示字段的平台编码
                    display_field_code = ref_field
                    if ref_mi.get("fields") and ref_field:
                        display_field_code = ref_mi["fields"].get(ref_field, ref_field)
                    comp["dataSelectorConfig"] = {
                        "type": "LOV_CHOOSE",
                        "otherModelCode": ref_mi["code"],
                        "otherFieldCode": display_field_code,
                    }
                    if ftype in ("数据选择", "数据多选"):
                        comp["componentType"] = "FORM_DATA_SELECTOR"
                break

    if ftype == "关联表单":
        comp["componentType"] = "FORM_ASSOCIATION"
        association = field.get("formAssociationConfig") or {}
        ref = field.get("ref") or {}
        target_model = (
            association.get("targetModelCode")
            or (ref.get("model") if isinstance(ref, dict) else "")
            or ""
        )
        target_field = (
            association.get("targetFieldCode")
            or (ref.get("target_field") if isinstance(ref, dict) else "")
            or (ref.get("display_field") if isinstance(ref, dict) else "")
            or (ref.get("field") if isinstance(ref, dict) else "")
            or ""
        )
        origin_field = association.get("originFieldCode") or field_code
        for ridx, rm in enumerate(models):
            if rm.get("name") == target_model or rm.get("code") == target_model:
                ref_mi = model_info.get(ridx)
                if ref_mi:
                    resolved_target_field = target_field
                    if ref_mi.get("fields") and target_field:
                        resolved_target_field = ref_mi["fields"].get(target_field, target_field)
                    comp["formAssociationConfig"] = {
                        "originFieldCode": origin_field,
                        "targetModelCode": ref_mi["code"],
                        "targetFieldCode": resolved_target_field,
                    }
                break

    return comp


def _build_model_lookup(models: List[dict], model_info: Dict) -> Dict[str, dict]:
    lookup: Dict[str, dict] = {}
    for idx, model in enumerate(models):
        mi = model_info.get(idx)
        if not mi:
            continue
        for key in (model.get("code"), model.get("name"), mi.get("code"), mi.get("name")):
            key = str(key or "").strip()
            if key:
                lookup[key] = mi
    return lookup


def _first_non_empty(*values, default=""):
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return value
    return default


def _resolve_reference_component(
    comp_def: dict,
    built: dict,
    model_lookup: Dict[str, dict],
) -> None:
    component_type = str(comp_def.get("componentType") or comp_def.get("component_type") or built.get("componentType") or "").strip()
    association = comp_def.get("formAssociationConfig") or comp_def.get("form_association_config") or {}
    selector = comp_def.get("dataSelectorConfig") or comp_def.get("data_selector_config") or {}
    ref = comp_def.get("ref") or {}
    target_model = (
        str(association.get("targetModelCode") or "").strip()
        or str(selector.get("otherModelCode") or "").strip()
        or str(comp_def.get("selector_form_code") or "").strip()
        or str(comp_def.get("association_form_code") or "").strip()
        or str(comp_def.get("ref_model_code") or "").strip()
        or (str(ref.get("model") or "").strip() if isinstance(ref, dict) else str(ref or "").strip())
    )
    target_field = (
        str(association.get("targetFieldCode") or "").strip()
        or str(selector.get("otherFieldCode") or "").strip()
        or str(comp_def.get("selector_field_code") or "").strip()
        or str(comp_def.get("association_target_field_code") or "").strip()
        or str(comp_def.get("ref_display_field_code") or "").strip()
        or (str(ref.get("target_field") or ref.get("display_field") or ref.get("field") or "").strip() if isinstance(ref, dict) else "")
    )
    if not target_model:
        return

    target_info = model_lookup.get(target_model)
    resolved_model_code = target_info.get("code", target_model) if target_info else target_model
    resolved_field_code = target_field
    if target_info and target_field:
        resolved_field_code = target_info.get("fields", {}).get(target_field, target_field)

    if component_type in ("FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR"):
        built["componentType"] = component_type
        built["dataSelectorConfig"] = {
            "type": "LOV_CHOOSE",
            "otherModelCode": resolved_model_code,
            "otherFieldCode": resolved_field_code,
        }
        built.pop("formAssociationConfig", None)
    elif component_type == "FORM_ASSOCIATION":
        origin_field = str(association.get("originFieldCode") or "").strip()
        if not origin_field:
            model_field = str(comp_def.get("modelField", comp_def.get("model_field", ""))).strip()
            origin_field = model_field.split(".", 1)[1] if "." in model_field else str(comp_def.get("code", "")).strip()
        built["formAssociationConfig"] = {
            "originFieldCode": origin_field,
            "targetModelCode": resolved_model_code,
            "targetFieldCode": resolved_field_code,
        }


def _form_identity_map(forms: List[dict]) -> Dict[str, dict]:
    mapping: Dict[str, dict] = {}
    for form in forms or []:
        for key in (
            form.get("formCode"), form.get("form_code"), form.get("code"),
            form.get("formName"), form.get("form_name"), form.get("name"),
            form.get("modelCode"), form.get("model_code"),
            form.get("mainModelCode"), form.get("main_model_code"), form.get("main_model"),
        ):
            value = str(key or "").strip()
            if value:
                mapping.setdefault(value, form)
    return mapping


def _resolve_component_reference(comp_def: dict, form_map: Dict[str, dict]) -> tuple[str, str, str]:
    association = comp_def.get("formAssociationConfig") or comp_def.get("form_association_config") or {}
    selector = comp_def.get("dataSelectorConfig") or comp_def.get("data_selector_config") or {}
    ref = comp_def.get("ref") or {}
    target = (
        str(association.get("targetModelCode") or "").strip()
        or str(selector.get("otherModelCode") or "").strip()
        or str(comp_def.get("selector_form_code") or "").strip()
        or str(comp_def.get("association_form_code") or "").strip()
        or str(comp_def.get("ref_model_code") or "").strip()
        or (str(ref.get("model") or "").strip() if isinstance(ref, dict) else str(ref or "").strip())
    )
    target_field = (
        str(association.get("targetFieldCode") or "").strip()
        or str(selector.get("otherFieldCode") or "").strip()
        or str(comp_def.get("selector_field_code") or "").strip()
        or str(comp_def.get("association_target_field_code") or "").strip()
        or str(comp_def.get("ref_display_field_code") or "").strip()
        or (str(ref.get("target_field") or ref.get("display_field") or ref.get("field") or "").strip() if isinstance(ref, dict) else "")
    )
    origin_field = str(association.get("originFieldCode") or comp_def.get("association_origin_field_code") or "").strip()
    resolved_form = form_map.get(target)
    if resolved_form:
        target_model_code = str(_first_non_empty(
            resolved_form.get("modelCode"),
            resolved_form.get("model_code"),
            resolved_form.get("mainModelCode"),
            resolved_form.get("main_model_code"),
            resolved_form.get("main_model"),
            default=target,
        )).strip() or target
        return target_model_code, target_field, origin_field
    return target, target_field, origin_field


def _resolve_target_form_result(
    comp_def: dict,
    form_map: Dict[str, dict],
    form_results: List[dict],
    target_model_code: str,
) -> Optional[dict]:
    ref = comp_def.get("ref") or {}
    for value in (
        comp_def.get("selector_form_code"),
        comp_def.get("association_form_code"),
        comp_def.get("formCode"),
        comp_def.get("form_code"),
        ref.get("formCode") if isinstance(ref, dict) else "",
        ref.get("form_code") if isinstance(ref, dict) else "",
    ):
        candidate = str(value or "").strip()
        form_def = form_map.get(candidate) if candidate else None
        if not form_def:
            continue
        for form_result in form_results:
            if (
                form_result.get("formCode") == form_def.get("formCode")
                or form_result.get("formCode") == form_def.get("code")
                or form_result.get("formCode") == form_def.get("form_code")
                or form_result.get("formName") == form_def.get("formName")
                or form_result.get("formName") == form_def.get("name")
                or form_result.get("formName") == form_def.get("form_name")
                or form_result.get("modelCode") == form_def.get("modelCode")
                or form_result.get("modelCode") == form_def.get("model_code")
                or form_result.get("modelCode") == form_def.get("mainModelCode")
                or form_result.get("modelCode") == form_def.get("main_model_code")
            ):
                return form_result
    for form_result in form_results:
        if str(form_result.get("modelCode", "")).strip() == target_model_code:
            return form_result
    return None


def _find_component_by_field(form_components: List[dict], field_code: str, *, label: str = "") -> Optional[dict]:
    normalized_field = str(field_code or "").strip()
    normalized_label = str(label or "").strip()
    for component in _iter_form_components(form_components):
        if normalized_field and _component_field_code(component) == normalized_field:
            return component
        if normalized_label and str(component.get("label", "")).strip() == normalized_label:
            return component
    return None


def _build_display_component_refs(form_components: List[dict], field_codes: List[str]) -> List[dict]:
    refs: List[dict] = []
    seen: set[str] = set()
    for field_code in field_codes:
        component = _find_component_by_field(form_components, field_code)
        component_uuid = str(component.get("uuid", "")).strip() if component else ""
        if not component_uuid or component_uuid in seen:
            continue
        seen.add(component_uuid)
        item = {
            "id": component_uuid,
            "componentType": component.get("componentType", "FORM_TEXT_INPUT"),
            "name": component.get("label", "") or component.get("modelFieldName", "") or field_code,
        }
        if component.get("chooseOptions"):
            item["chooseOptions"] = component.get("chooseOptions")
        if "multicolor" in component:
            item["multicolor"] = bool(component.get("multicolor"))
        refs.append(item)
    return refs


_DATA_SELECTOR_TYPES = {
    "FORM_DATA_SELECTOR_SINGLE",
    "FORM_DATA_SELECTOR",
    "数据单选",
    "数据选择",
    "数据多选",
}

_ASSOCIATION_TYPES = {"FORM_ASSOCIATION", "关联表单"}


def _form_display_name(form: dict, fallback: str = "") -> str:
    return str(_first_non_empty(
        form.get("formName"),
        form.get("form_name"),
        form.get("name"),
        form.get("formCode"),
        form.get("form_code"),
        form.get("code"),
        form.get("modelCode"),
        form.get("model_code"),
        form.get("mainModelCode"),
        form.get("main_model_code"),
        default=fallback,
    ))


def _iter_component_defs(components: List[dict]) -> List[dict]:
    items: List[dict] = []
    for comp in components or []:
        if not isinstance(comp, dict):
            continue
        items.append(comp)
        table_cols = comp.get("tableColumn")
        if isinstance(table_cols, list):
            items.extend(_iter_component_defs(table_cols))
    return items


def _component_def_type(comp: dict) -> str:
    return str(
        comp.get("componentType")
        or comp.get("component_type")
        or comp.get("type")
        or ""
    ).strip()


def _component_label(comp: dict) -> str:
    return str(comp.get("label") or comp.get("name") or comp.get("code") or "").strip()


def _target_identity_from_component(comp: dict) -> str:
    association = comp.get("formAssociationConfig") or comp.get("form_association_config") or {}
    selector = comp.get("dataSelectorConfig") or comp.get("data_selector_config") or {}
    ref = comp.get("ref") or {}
    return str(
        association.get("targetModelCode")
        or selector.get("otherModelCode")
        or comp.get("selector_form_code")
        or comp.get("association_form_code")
        or comp.get("ref_model_code")
        or comp.get("refModelCode")
        or (ref.get("model") if isinstance(ref, dict) else ref)
        or ""
    ).strip()


def _sort_forms_by_data_selector_dependencies(
    forms: List[dict],
    existing_forms: Dict[str, str],
) -> tuple[List[dict], List[str]]:
    """数据选择组件创建时需要目标表单先存在；按该硬依赖排序。

    关联表单可以最后追加，不参与排序。若数据选择依赖缺失或有环，返回 issues。
    """
    identity_to_idx: Dict[str, int] = {}
    for idx, form in enumerate(forms):
        for value in _form_identity_map([form]).keys():
            identity_to_idx.setdefault(value, idx)

    deps_by_idx: Dict[int, set[int]] = {idx: set() for idx in range(len(forms))}
    issues: List[str] = []
    for idx, form in enumerate(forms):
        for comp in _iter_component_defs(form.get("components") or []):
            comp_type = _component_def_type(comp)
            if comp_type not in _DATA_SELECTOR_TYPES:
                continue
            target = _target_identity_from_component(comp)
            if not target:
                issues.append(f"{_form_display_name(form, str(idx + 1))}.{_component_label(comp)} 缺少数据选择目标表单")
                continue
            target_idx = identity_to_idx.get(target)
            if target_idx is not None:
                if target_idx != idx:
                    deps_by_idx[idx].add(target_idx)
                continue
            if target in existing_forms:
                continue
            issues.append(
                f"{_form_display_name(form, str(idx + 1))}.{_component_label(comp)} "
                f"引用目标「{target}」不在本次创建表单中，也未找到已存在表单"
            )
    if issues:
        return forms, issues

    ordered_indices: List[int] = []
    visiting: set[int] = set()
    visited: set[int] = set()
    stack: List[int] = []
    cycle: List[int] = []

    def _visit(idx: int) -> bool:
        nonlocal cycle
        if idx in visited:
            return True
        if idx in visiting:
            start = stack.index(idx) if idx in stack else 0
            cycle = stack[start:] + [idx]
            return False
        visiting.add(idx)
        stack.append(idx)
        for dep in deps_by_idx.get(idx, set()):
            if not _visit(dep):
                return False
        stack.pop()
        visiting.remove(idx)
        visited.add(idx)
        ordered_indices.append(idx)
        return True

    for idx in range(len(forms)):
        if idx not in visited and not _visit(idx):
            names = [_form_display_name(forms[i], str(i + 1)) for i in cycle]
            return forms, [f"数据选择引用存在循环：{' -> '.join(names)}"]

    return [forms[idx] for idx in ordered_indices], []


def _find_form_definition_for_result(form_result: dict, form_map: Dict[str, dict]) -> Optional[dict]:
    for value in (
        form_result.get("formCode"),
        form_result.get("formName"),
        form_result.get("modelCode"),
    ):
        text = str(value or "").strip()
        if text and text in form_map:
            return form_map[text]
    return None


def _find_existing_association_component(components: List[dict], comp_def: dict) -> Optional[dict]:
    label = _component_label(comp_def)
    code = str(comp_def.get("code") or comp_def.get("field_code") or "").strip()
    model_field = str(comp_def.get("modelField") or comp_def.get("model_field") or "").strip()
    for comp in _iter_form_components(components):
        if comp.get("componentType") != "FORM_ASSOCIATION":
            continue
        if label and str(comp.get("label") or "").strip() == label:
            return comp
        if code and _component_field_code(comp) == code:
            return comp
        if model_field and str(comp.get("modelField") or "").strip() == model_field:
            return comp
    return None


async def _sync_association_components_on_forms(
    client: APaaSClient,
    app_id: str,
    form_results: List[dict],
    all_forms: List[dict],
) -> int:
    """所有表单创建完成后，再统一新增/补齐 FORM_ASSOCIATION 组件。"""
    form_map = _form_identity_map(all_forms)
    updated_forms = 0
    target_form_cache: Dict[str, dict] = {}

    async def _target_payload(target_form_result: dict) -> dict:
        target_form_id = str(target_form_result.get("formId") or "").strip()
        if not target_form_id:
            return {}
        if target_form_id not in target_form_cache:
            target_form_cache[target_form_id] = await client.query_detail_page_config(app_id, target_form_id)
        return target_form_cache[target_form_id]

    for form_result in form_results:
        form_id = str(form_result.get("formId") or "").strip()
        if not form_id:
            continue
        form_def = _find_form_definition_for_result(form_result, form_map)
        assoc_defs = [
            comp for comp in _iter_component_defs((form_def or {}).get("components") or [])
            if _component_def_type(comp) in _ASSOCIATION_TYPES
        ]
        if not form_def or not assoc_defs:
            continue

        form_config = await _query_saveable_form_config(client, app_id, form_id)
        _ensure_canvas_form_components(form_config, form_result.get("formComponents") or [])
        components = form_config.get("detailPage", {}).get("formComponents", [])
        changed = False

        for comp_def in assoc_defs:
            target_model_code, target_field, origin_field = _resolve_component_reference(comp_def, form_map)
            target_form_result = _resolve_target_form_result(comp_def, form_map, form_results, target_model_code)
            if not target_form_result:
                logger.warning("关联表单目标不存在，跳过: form=%s component=%s target=%s",
                               form_result.get("formName"), _component_label(comp_def), target_model_code)
                continue
            target_payload = await _target_payload(target_form_result)
            _ensure_canvas_form_components(
                target_payload,
                target_form_result.get("formComponents") or target_form_result.get("components") or [],
            )
            target_components = target_payload.get("detailPage", {}).get("formComponents", [])
            target_component = _find_component_by_field(target_components, target_field)
            origin = origin_field or str(comp_def.get("association_origin_field_code") or "").strip()
            if not origin:
                model_field = str(comp_def.get("modelField") or comp_def.get("model_field") or "").strip()
                origin = model_field.split(".", 1)[1] if "." in model_field else str(comp_def.get("code") or "").strip()
            origin_component = _find_component_by_field(components, origin)
            if not target_component or not origin_component:
                logger.warning(
                    "关联表单组件定位失败，跳过: form=%s component=%s origin=%s targetField=%s",
                    form_result.get("formName"), _component_label(comp_def), origin, target_field,
                )
                continue

            display_field_codes: List[str] = []
            target_form_def = _find_form_definition_for_result(target_form_result, form_map)
            if target_form_def:
                for target_comp_def in target_form_def.get("components", []) or []:
                    if bool(target_comp_def.get("showInList")):
                        model_field = str(target_comp_def.get("modelField", target_comp_def.get("model_field", ""))).strip()
                        display_code = model_field.split(".", 1)[1] if "." in model_field else str(target_comp_def.get("code", "")).strip()
                        if display_code:
                            display_field_codes.append(display_code)
            if target_field and target_field not in display_field_codes:
                display_field_codes.append(target_field)
            display_refs = _build_display_component_refs(target_components, display_field_codes) or [{
                "id": target_component.get("uuid", ""),
                "componentType": target_component.get("componentType", "FORM_TEXT_INPUT"),
            }]

            assoc_comp = _find_existing_association_component(components, comp_def)
            if not assoc_comp:
                assoc_comp = {
                    "componentType": "FORM_ASSOCIATION",
                    "label": _component_label(comp_def) or f"关联{target_form_result.get('formName') or '表单'}",
                    "width": int(comp_def.get("width") or 6),
                }
                components.append(assoc_comp)
                changed = True

            desired = {
                "componentType": "FORM_ASSOCIATION",
                "associationField": {
                    "originUuid": origin_component.get("uuid", ""),
                    "targetUuid": target_component.get("uuid", ""),
                },
                "associationFormId": target_form_result.get("formId", ""),
                "displayFields": [item["id"] for item in display_refs if item.get("id")],
                "displayStyle": "PAGE_TABLE",
                "quoteViewType": "LIST_VIEW",
                "assocAllowNew": False,
                "assocTabId": "",
                "tableOrders": [],
                "businessObjectComponentType": "BOF_ASSOCIATION",
            }
            for key, value in desired.items():
                if assoc_comp.get(key) != value:
                    assoc_comp[key] = value
                    changed = True

        if changed:
            _ensure_canvas_form_components(form_config)

            def _apply_latest(latest: dict) -> None:
                _force_form_identity(
                    latest,
                    form_name=str(form_result.get("formName") or ""),
                    form_code=str(form_result.get("formCode") or ""),
                    all_model_codes=list(form_result.get("allModelCodes") or []),
                    app_id=app_id,
                    form_id=form_id,
                    menu_id=str(form_result.get("menuId") or ""),
                )
                _ensure_canvas_form_components(latest, form_result.get("formComponents") or [])
                latest_components = latest.get("detailPage", {}).get("formComponents", [])
                latest_components[:] = components

            _apply_latest(form_config)
            await _save_form_config_with_retry(
                client,
                app_id,
                form_config,
                form_id=form_id,
                apply_latest=_apply_latest,
                reason="新增/补齐关联表单组件",
            )
            updated_forms += 1

    return updated_forms


def _build_form_components_from_definition(
    form: dict,
    default_model_code: str,
    model_lookup: Dict[str, dict],
) -> tuple[List[dict], List[str], List[str]]:
    components: List[dict] = []
    query_conditions: List[str] = []
    query_list: List[str] = []
    listable = 0
    sub_groups: Dict[str, dict] = {}

    for comp in form.get("components", []) or []:
        if _component_def_type(comp) in _ASSOCIATION_TYPES:
            continue
        section_type = str(comp.get("sectionType", comp.get("section_type", "main"))).strip() or "main"
        component_model_code = str(comp.get("modelCode", comp.get("model_code", ""))).strip() or default_model_code
        resolved_model_code = model_lookup.get(component_model_code, {}).get("code", component_model_code)
        table_model_code = str(comp.get("tableModelCode", comp.get("table_model_code", ""))).strip() or component_model_code
        resolved_table_model_code = model_lookup.get(table_model_code, {}).get("code", table_model_code)
        model_field = str(comp.get("modelField", comp.get("model_field", ""))).strip()
        field_code = model_field.split(".", 1)[1] if "." in model_field else str(comp.get("code", "")).strip()
        if not field_code and str(comp.get("componentType", "")).strip() != "FORM_ASSOCIATION":
            continue

        built = {
            "componentType": comp.get("componentType") or comp.get("component_type") or "FORM_TEXT_INPUT",
            "label": comp.get("label") or comp.get("name") or field_code,
        }
        if field_code:
            built["modelField"] = f"{resolved_model_code}.{field_code}"
        dict_ref = (
            comp.get("dict")
            or comp.get("dictCode")
            or comp.get("dict_code")
            or comp.get("dictionaryCode")
        )
        if dict_ref:
            built["dictCode"] = dict_ref
            built["dict"] = dict_ref
        if built.get("componentType") in _SELECT_COMPONENT_TYPES:
            built["chooseType"] = _choose_type_for_select_component(str(built.get("componentType") or ""), built)
        for key in ("hidden", "readonly", "required", "showInList", "searchable"):
            if key in comp:
                built[key] = bool(comp.get(key))

        _resolve_reference_component(comp, built, model_lookup)

        if section_type == "sub":
            group = sub_groups.setdefault(resolved_table_model_code, {
                "componentType": "FORM_WIDGET_SON_TABLE",
                "label": comp.get("subTableLabel") or built["label"] or resolved_table_model_code,
                "tableColumn": [],
            })
            if comp.get("subTableLabel"):
                group["label"] = comp.get("subTableLabel")
            group["tableColumn"].append(built)
            continue

        components.append(built)
        if built.get("showInList") and listable < 8 and built.get("modelField"):
            mf = built["modelField"]
            if built.get("searchable") and len(query_conditions) < 4:
                query_conditions.append(mf)
            query_list.append(mf)
            listable += 1

    components.extend(sub_groups.values())
    return components, query_conditions, query_list


# ---------------------------------------------------------------------------
# Phase 0 预处理
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 2 数据模型辅助
# ---------------------------------------------------------------------------

def _classify_models_reuse_vs_new(
    models: List[dict],
    existing_by_name: Dict[str, dict],
    model_info: Dict,
) -> tuple[List[dict], List[tuple]]:
    """把 models 拆成 (reused, new_models_to_create)。

    副作用：为复用模型（含子表）原地写入 model_info。
    new_models_to_create 形如 [(idx, model_dict), ...]，子表登记留给 _build_model_payload_with_subs。
    """
    reused: List[dict] = []
    new_models_to_create: List[tuple] = []
    for idx, m in enumerate(models):
        em = existing_by_name.get(m["name"])
        if em:
            model_info[idx] = {"name": m["name"], "code": em["modelCode"], "fields": _extract_fields(em)}
            reused.append(m)
            for f in m.get("fields", []):
                if f.get("type") == "子表" and f.get("sub_fields"):
                    sub_em = existing_by_name.get(f["name"])
                    if sub_em:
                        model_info[f"{idx}_sub_{f['name']}"] = {
                            "name": f["name"], "code": sub_em["modelCode"], "fields": _extract_fields(sub_em),
                        }
        else:
            new_models_to_create.append((idx, m))
    return reused, new_models_to_create


def _build_model_payload_with_subs(
    new_models_to_create: List[tuple],
    app_id: str,
    suffix: str,
    model_info: Dict,
) -> dict:
    """构造 create_models 的 payload，同时登记 model_info（主模型 + 子表）。"""
    data_models: List[dict] = []
    for idx, m in new_models_to_create:
        # 2026-05-30 修尾下划线: enable_code_suffix=False 时 suffix="", 旧写法 f"{code}_{suffix}"
        # 会留下尾 "_"(idm_erp_bom_)。改用 _apply_suffix —— 空 suffix 时返回 code 原样不加 "_"。
        mc = _apply_suffix(_sanitize_code(m.get('code', 'model')), suffix)
        fields_map = {}

        # 子表模型
        for f in m.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                sub_code = _apply_suffix(_sanitize_code(f.get('sub_code') or m.get('code', 'model') + '_sub'), suffix)
                sub_fields = []
                sub_fields_map = {}
                for sf in f["sub_fields"]:
                    sfc = _safe_field_code(sf.get("code") or sf["name"])
                    sub_fields.append({
                        "fieldName": sf["name"], "fieldCode": sfc,
                        "fieldType": FIELD_TYPE_MAP.get(sf.get("type", ""), "STRING"),
                        "fieldDescription": sf.get("type", ""),
                    })
                    sub_fields_map[sf["name"]] = sfc
                data_models.append({
                    "appId": app_id, "modelName": f["name"],
                    "modelCode": sub_code, "modelDescription": f["name"],
                    "fields": sub_fields,
                })
                model_info[f"{idx}_sub_{f['name']}"] = {"name": f["name"], "code": sub_code, "fields": sub_fields_map}

        # 主模型字段
        main_fields = []
        for f in m.get("fields", []):
            if f.get("type") == "子表":
                continue
            fc = _safe_field_code(f.get("code") or f["name"])
            main_fields.append({
                "fieldName": f["name"], "fieldCode": fc,
                "fieldType": FIELD_TYPE_MAP.get(f.get("type", ""), "STRING"),
                "fieldDescription": f.get("type", ""),
            })
            fields_map[f["name"]] = fc

        data_models.append({
            "appId": app_id, "modelName": m["name"],
            "modelCode": mc, "modelDescription": m.get("description", m["name"]),
            "fields": main_fields,
        })
        model_info[idx] = {"name": m["name"], "code": mc, "fields": fields_map}

    return {"appId": app_id, "datasourceId": "", "dataModels": data_models}


async def _refresh_model_codes_from_platform(
    client: APaaSClient,
    app_id: str,
    new_models_to_create: List[tuple],
    model_info: Dict,
) -> None:
    """创建后回查，用平台真实 fieldCode 覆盖 model_info（平台可能追加后缀）。"""
    refreshed = await client.query_models(app_id)
    ref_by_code = {rm.get("modelCode"): rm for rm in refreshed}
    for idx, m in new_models_to_create:
        mi = model_info.get(idx)
        if mi and mi["code"] in ref_by_code:
            mi["fields"] = _extract_fields(ref_by_code[mi["code"]])
        for f in m.get("fields", []):
            if f.get("type") == "子表":
                sub_key = f"{idx}_sub_{f['name']}"
                sub_mi = model_info.get(sub_key)
                if sub_mi and sub_mi["code"] in ref_by_code:
                    sub_mi["fields"] = _extract_fields(ref_by_code[sub_mi["code"]])


async def _rollback_models_to_reuse_by_name(
    client: APaaSClient,
    app_id: str,
    new_models_to_create: List[tuple],
    model_info: Dict,
) -> None:
    """编码冲突时回退：按 modelName 匹配平台已有模型覆盖 model_info。"""
    refreshed = await client.query_models(app_id)
    ref_by_name = {rm.get("modelName"): rm for rm in refreshed}
    for idx, m in new_models_to_create:
        rm = ref_by_name.get(m["name"])
        if rm:
            model_info[idx] = {"name": m["name"], "code": rm["modelCode"], "fields": _extract_fields(rm)}
            for f in m.get("fields", []):
                if f.get("type") == "子表":
                    srm = ref_by_name.get(f["name"])
                    if srm:
                        model_info[f"{idx}_sub_{f['name']}"] = {
                            "name": f["name"], "code": srm["modelCode"], "fields": _extract_fields(srm),
                        }


# ---------------------------------------------------------------------------
# Phase 3 表单辅助
# ---------------------------------------------------------------------------

async def _load_existing_form_menus(client: APaaSClient, app_id: str) -> Dict[str, str]:
    """查询应用已有表单菜单，返回 {可识别表单键: formId}。异常吞掉返回空表。"""
    existing_forms: Dict[str, str] = {}
    try:
        menus = await client.query_menus(app_id)

        def _collect(items: list):
            for item in items:
                if item.get("formId"):
                    for key in (
                        item.get("menuName"),
                        item.get("formName"),
                        item.get("formCode"),
                        item.get("modelCode"),
                        item.get("name"),
                    ):
                        text = str(key or "").strip()
                        if text:
                            existing_forms[text] = item["formId"]
                _collect(item.get("submenus", []) or item.get("children", []) or [])

        _collect(menus)
    except Exception:
        pass
    return existing_forms


def _resolve_forms_to_build(all_forms: List[dict], models: List[dict]) -> List[dict]:
    """用户提供 all_forms 则用之；否则按 models 自动生成每模型一份空 form。"""
    forms_to_build = all_forms or []
    if not forms_to_build:
        forms_to_build = [
            {
                "name": m["name"],
                "modelCode": m.get("code"),
                "allModelCodes": [m.get("code")],
                "components": [],
            }
            for m in models
        ]
    return forms_to_build


# ---------------------------------------------------------------------------
# Phase 4 权限辅助
# ---------------------------------------------------------------------------

def _build_permission_payload_for_form(
    form_result: dict,
    user_perm: Optional[dict],
    role_code_map: Dict[str, dict],
    app_id: str,
) -> Optional[tuple[dict, dict]]:
    """根据单个表单的用户权限规则，构造 (perm_payload, sync_job)。

    user_perm 为 None 或无 rules 时返回 None。
    """
    if not user_perm or not user_perm.get("rules"):
        return None

    form_code = form_result.get("formCode", "")
    form_id = form_result.get("formId", "")
    op_groups: List[dict] = []
    data_groups: List[dict] = []

    for rule in user_perm["rules"]:
        role_code = rule.get("role", "")
        # 找到对应角色的平台编码
        perm_obj_type = "ALL_USER"
        perm_obj_value = ""
        perm_obj_name = "全部人员"
        if role_code and role_code != "all":
            role_info = role_code_map.get(role_code, {})
            perm_obj_type = "ROLE"
            perm_obj_value = role_info.get("id") or role_info.get("roleCode", role_code)
            perm_obj_name = role_info.get("roleName", role_code)

        op = rule.get("op", "all")
        op_set = {part.strip() for part in str(op).split(",") if part.strip()} if isinstance(op, str) else {"all"}
        can_view = "all" in op_set or "view" in op_set
        can_add = "all" in op_set or "add" in op_set
        can_edit = "all" in op_set or "edit" in op_set
        can_delete = "all" in op_set or "delete" in op_set
        can_import = bool(rule.get("canImport"))
        can_draft = bool(rule.get("canDraft"))
        can_export = bool(rule.get("canExport"))
        perm_op = {
            "addPermission": can_add,
            "batchAgreePermission": False,
            "batchDeletePermission": False,
            "batchRejectPermission": False,
            "copyAddPermission": False,
            "importPermission": can_import,
            "shareFormPermission": False,
            "temporaryStoragePermission": can_draft,
        }

        data_range = rule.get("data", "ALL")
        range_map = {
            "all": "ALL", "self": "SELF", "dept": "CURRENT_USER_DEPT",
            "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
        }
        range_type = range_map.get(data_range, data_range.upper() if isinstance(data_range, str) else "ALL")

        if any((can_add, can_import, can_draft)):
            op_groups.append({
                "permissionName": f"{perm_obj_name}操作权限",
                "permissionDescribe": "",
                "permissionObjects": [{
                    "permissionObjectDisplayName": perm_obj_name,
                    "permissionObjectType": perm_obj_type,
                    "permissionObjectValue": perm_obj_value,
                    "permissionRange": {"rangeType": "ALL"},
                }],
                "permissionOperationType": perm_op,
            })
        data_groups.append({
            "permissionName": f"{perm_obj_name}数据权限",
            "permissionDescribe": "",
            "permissionObjects": [{
                "permissionObjectDisplayName": perm_obj_name,
                "permissionObjectType": perm_obj_type,
                "permissionObjectValue": perm_obj_value,
                "permissionRange": {"rangeType": range_type},
            }],
            "permissionOperationType": {
                "queryPermission": can_view,
                "deletePermission": can_delete,
                "updatePermission": can_edit,
                "commentPermission": can_view,
                "dataSharePermission": can_view,
                "exportPermission": can_export,
                "logPermission": can_view,
                "printPermission": can_view,
                "queryApprovalInfoPermission": can_view,
            },
        })

    perm_payload = {
        "formCode": form_code,
        "appId": app_id,
        "tenantId": "",
        "formId": form_id,
        "operationPermissionGroups": op_groups,
        "dataPermissionGroups": data_groups,
    }
    # 把建表时的表单名/编码/绑定模型一起传出去，让权限回写阶段能在 save_form_config
    # 前把这些字段重新覆盖到 form_config 上，避免被平台默认值"我的待办"抹掉。
    sync_job = {
        "form_id": form_id,
        "rules": user_perm["rules"],
        "form_name": form_result.get("formName", ""),
        "form_code": form_code,
        "all_model_codes": list(form_result.get("allModelCodes") or []),
        "form_components": copy.deepcopy(form_result.get("formComponents") or []),
        "menu_id": form_result.get("menuId", ""),
    }
    return perm_payload, sync_job


def _find_permission_for_form(form_result: dict, permissions: List[dict]) -> Optional[dict]:
    form_code = str(form_result.get("formCode") or "").strip()
    form_name = str(form_result.get("formName") or "").strip()
    model_code = str(form_result.get("modelCode") or "").strip()
    if form_code:
        matched = next((
            p for p in permissions
            if str(p.get("formCode") or p.get("form_code") or "").strip() == form_code
        ), None)
        if matched:
            return matched
    if form_name:
        matched = next((
            p for p in permissions
            if str(p.get("form") or p.get("formName") or p.get("form_name") or "").strip() == form_name
        ), None)
        if matched:
            return matched
    if model_code:
        matched = next((
            p for p in permissions
            if str(p.get("modelCode") or p.get("model_code") or "").strip() == model_code
        ), None)
        if matched:
            return matched
    return None


async def _apply_permissions_and_sync(
    client: APaaSClient,
    app_id: str,
    perm_payloads: List[dict],
    sync_jobs: List[dict],
    role_code_map: Dict[str, dict],
) -> None:
    """下发表单权限并回写到 formConfig（两步：批量 create + 逐个 sync）。"""
    await client.create_form_permissions(app_id, perm_payloads)
    for job in sync_jobs:
        await _sync_form_permissions_to_form_config(
            client=client,
            app_id=app_id,
            form_id=job["form_id"],
            rules=job["rules"],
            role_code_map=role_code_map,
            form_name=job.get("form_name", ""),
            form_code=job.get("form_code", ""),
            all_model_codes=job.get("all_model_codes", []),
            fallback_components=job.get("form_components") or [],
            menu_id=job.get("menu_id", ""),
        )


def _collect_label_dict_map(
    models: List[dict],
    dict_codes: Dict[str, str],
    model_info: Optional[Dict] = None,
) -> Dict[str, str]:
    """收集字段可用的字典映射，含子表字段。

    既保留历史的 label 兜底，也登记 modelField / field code 等更精确的键，避免多个
    表单都有「状态」「类型」时被全局 label 映射错绑。
    """
    label_dict: Dict[str, str] = {}

    def _put(key: object, code: str) -> None:
        text = str(key or "").strip()
        if text and code:
            label_dict[text] = code

    def _field_code(field: dict) -> str:
        return str(field.get("code") or field.get("fieldCode") or field.get("field_code") or "").strip()

    def _field_name(field: dict) -> str:
        return str(field.get("name") or field.get("fieldName") or "").strip()

    def _field_dict(field: dict) -> str:
        return str(field.get("dict") or field.get("dictCode") or field.get("dictionaryCode") or "").strip()

    def _register(model_code: str, platform_model_code: str, platform_fields: dict, field: dict) -> None:
        dc = dict_codes.get(_field_dict(field), _field_dict(field))
        if not dc:
            return
        fc = _field_code(field)
        name = _field_name(field)
        platform_fc = str(platform_fields.get(name) or platform_fields.get(fc) or fc).strip()
        for key in (
            f"{model_code}.{fc}" if model_code and fc else "",
            f"{platform_model_code}.{platform_fc}" if platform_model_code and platform_fc else "",
            f"{platform_model_code}.{fc}" if platform_model_code and fc else "",
            platform_fc,
            fc,
            name,
        ):
            _put(key, dc)

    for idx, m in enumerate(models):
        model_code = str(m.get("code") or m.get("modelCode") or "").strip()
        mi = (model_info or {}).get(idx) or (model_info or {}).get(str(idx)) or {}
        platform_model_code = str(mi.get("code") or model_code).strip()
        platform_fields = mi.get("fields") if isinstance(mi.get("fields"), dict) else {}
        for f in m.get("fields", []):
            if f.get("type") in ("下拉单选", "下拉多选") and _field_dict(f):
                _register(model_code, platform_model_code, platform_fields, f)
            if f.get("type") == "子表":
                sub_model_code = str(f.get("sub_code") or f.get("subCode") or f.get("code") or "").strip()
                sub_key = f"{idx}_sub_{f.get('name')}"
                sub_mi = (model_info or {}).get(sub_key) or {}
                sub_platform_code = str(sub_mi.get("code") or sub_model_code or model_code).strip()
                sub_platform_fields = sub_mi.get("fields") if isinstance(sub_mi.get("fields"), dict) else {}
                for sf in f.get("sub_fields", []):
                    if sf.get("type") in ("下拉单选", "下拉多选") and _field_dict(sf):
                        _register(sub_model_code or model_code, sub_platform_code, sub_platform_fields, sf)
    return label_dict


def _collect_spec_component_dict_map(
    form_results: Optional[List[dict]],
    dict_codes: Dict[str, str],
) -> Dict[str, str]:
    """从 spec 表单组件收集 {组件匹配键: 平台字典 code}。

    spec 生成的表单组件自带权威 dict 引用(comp.dictCode/dict), 且其 label 与平台保存后的
    组件 label 一致(如「化学体系」)。平台 save_form_config 会把 dict/dictCode 从组件上剥掉,
    所以回写绑定时只能从 spec 组件(form_results[*].formComponents)取这个引用。优先登记
    modelField / code 等精确键, label 仅作为当前表单内兜底。
    """
    out: Dict[str, str] = {}

    def _put(key: object, code: str) -> None:
        text = str(key or "").strip()
        if text and code:
            out[text] = code

    def _walk(comps: Optional[List[dict]]) -> None:
        for c in comps or []:
            if not isinstance(c, dict):
                continue
            ref = c.get("dictCode") or c.get("dict")
            dc = dict_codes.get(ref, ref) if ref else ""
            if dc:
                for key in (
                    c.get("modelField"),
                    c.get("model_field"),
                    c.get("code"),
                    c.get("field_code"),
                    c.get("label"),
                    c.get("name"),
                ):
                    _put(key, dc)
            # 子表列组件
            if c.get("componentType") == "FORM_WIDGET_SON_TABLE":
                _walk(c.get("tableColumn"))

    for fr in form_results or []:
        if isinstance(fr, dict):
            _walk(fr.get("formComponents"))
    return out


def _bind_dict_on_component(
    comp: dict,
    dict_lookup: Dict[str, str],
    dict_id_map: Dict[str, str],
    dict_options_map: Dict[str, list],
    dict_codes: Optional[Dict[str, str]] = None,
) -> bool:
    """把单个下拉组件绑定到平台字典选项；命中改动返回 True。

    绑定优先级:
      1) 组件自带的权威 dict 引用(comp.dictCode/dict)—— spec 生成时就写在组件上,
         经 dict_codes 翻译成平台 dictionaryCode(空表/缺键时按原值)。
      2) 兜底:按 modelField / code / label 等组件键在 dict_lookup 里查。
    历史只走 (2),当平台字典名 ≠ 字段 label 时(如 字典「电池化学体系」vs 字段「化学体系」)
    会漏绑;(1) 用组件自带 code 直绑,不依赖名字巧合。
    """
    ct = comp.get("componentType")
    if ct not in ("FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT"):
        return False
    dc = resolve_component_dict_code(comp, dict_lookup, dict_codes, dict_id_map)
    if not dc or dc not in dict_id_map:
        return False
    did = dict_id_map[dc]
    opts = dict_options_map.get(dc, [])
    choose = [
        {
            "id": o.get("valueCode"),
            "label": o.get("valueName"),
            "labelI18nAssociated": False,
            "color": o.get("valueMulticolor", "#027AFF"),
            "status": o.get("valueStatus", "ENABLE"),
            "checked": False,
            "displayOrder": o.get("displayOrder", 0),
        }
        for o in opts
    ]
    comp["source"] = {"type": "DICTIONARY_TYPE", "id": did}
    comp["chooseOptions"] = choose
    comp["dictionaryChooseOptions"] = choose
    comp["chooseType"] = _choose_type_for_select_component(ct, comp)
    comp["multicolor"] = True
    comp["dictionaryMulticolorStatus"] = "ENABLE"
    comp["dictionarySelectConfig"] = {
        "dictionaryCode": dc,
        "dictionarySelectOptions": choose,
    }
    if ct == "FORM_SELECT_INPUT_SINGLE":
        comp["componentType"] = "FORM_SELECT_INPUT"
    return True


async def _load_dict_binding_maps(
    client: APaaSClient,
    app_id: str,
) -> tuple[List[dict], Dict[str, str], Dict[str, list]]:
    """加载平台字典 id 与选项，供创建表单时直接绑定下拉。"""
    all_platform_dicts = await client.query_dicts(app_id)
    dict_id_map = {
        d.get("dictionaryCode"): d.get("id")
        for d in all_platform_dicts
        if d.get("dictionaryCode") and d.get("id")
    }
    dict_options_map: Dict[str, list] = {}
    for dc, did in dict_id_map.items():
        dict_options_map[dc] = await client.query_dict_options(app_id, did)
    return all_platform_dicts, dict_id_map, dict_options_map


def _build_base_dict_lookup(
    models: List[dict],
    dict_codes: Dict[str, str],
    model_info: Optional[Dict],
    all_platform_dicts: List[dict],
) -> Dict[str, str]:
    """构建下拉字典 lookup，显式模型字段优先，字典名仅兜底。"""
    lookup = _collect_label_dict_map(models, dict_codes, model_info)
    for _d in all_platform_dicts:
        _dn = str(_d.get("dictionaryName") or "").strip()
        _dcode = _d.get("dictionaryCode")
        if _dn and _dcode and _dn not in lookup:
            lookup[_dn] = _dcode
    return lookup


def _bind_dicts_on_component_tree(
    components: List[dict],
    dict_lookup: Dict[str, str],
    dict_id_map: Dict[str, str],
    dict_options_map: Dict[str, list],
    dict_codes: Dict[str, str],
) -> int:
    """对一棵表单组件树执行字典绑定，返回命中的组件数。"""
    bound = 0
    for comp in components or []:
        if _bind_dict_on_component(comp, dict_lookup, dict_id_map, dict_options_map, dict_codes):
            bound += 1
        if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
            for col in comp.get("tableColumn", []) or []:
                if _bind_dict_on_component(col, dict_lookup, dict_id_map, dict_options_map, dict_codes):
                    bound += 1
    return bound


async def _rebind_dicts_on_forms(
    client: APaaSClient,
    app_id: str,
    form_ids: List[str],
    models: List[dict],
    dict_codes: Dict[str, str],
    form_results: Optional[List[dict]] = None,
) -> int:
    """用平台实际字典选项回写到每个表单的下拉组件。返回成功更新的表单数。"""
    all_platform_dicts, dict_id_map, dict_options_map = await _load_dict_binding_maps(client, app_id)
    base_dict_lookup = _build_base_dict_lookup(models, dict_codes, None, all_platform_dicts)
    form_result_by_id = {
        str(item.get("formId") or "").strip(): item
        for item in (form_results or [])
        if str(item.get("formId") or "").strip()
    }

    bound_count = 0
    for form_id in form_ids:
        try:
            fc = await client.query_form_config(app_id, form_id)
            form_result = form_result_by_id.get(str(form_id).strip(), {})
            fallback_components = form_result.get("formComponents") or []
            dict_lookup = dict(base_dict_lookup)
            # 权威补充只取当前表单, 避免不同表单同名下拉(如「状态」)互相覆盖。
            dict_lookup.update(_collect_spec_component_dict_map([form_result], dict_codes))
            updated = _ensure_canvas_form_components(fc, fallback_components)
            comps = fc.get("detailPage", {}).get("formComponents", [])

            for comp in comps:
                if _bind_dicts_on_component_tree([comp], dict_lookup, dict_id_map, dict_options_map, dict_codes):
                    updated = True

            if updated:
                def _apply_latest(latest: dict) -> None:
                    _force_form_identity(
                        latest,
                        form_name=str(form_result.get("formName") or ""),
                        form_code=str(form_result.get("formCode") or ""),
                        all_model_codes=list(form_result.get("allModelCodes") or []),
                        app_id=app_id,
                        form_id=str(form_id),
                        menu_id=str(form_result.get("menuId") or ""),
                    )
                    _ensure_canvas_form_components(latest, fallback_components)

                _apply_latest(fc)
                await _save_form_config_with_retry(
                    client,
                    app_id,
                    fc,
                    form_id=str(form_id),
                    apply_latest=_apply_latest,
                    reason="字典绑定回写",
                )
                bound_count += 1
        except Exception as e:
            logger.warning(f"绑定表单 {form_id} 字典失败: {e}")

    return bound_count


def _build_form_create_payload(
    form: dict,
    form_name: str,
    all_model_codes: List[str],
    components: List[dict],
    query_conditions: List[str],
    query_list: List[str],
) -> List[dict]:
    """构造单表单的 create_form_config 请求体（list 包裹一个 dict）。"""
    return [{
        "formName": form_name,
        "formCode": str(form.get("formCode") or form.get("form_code") or form.get("code") or f"form_{_rand(6)}"),
        "allModelCodes": all_model_codes,
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        },
    }]


# ---------------------------------------------------------------------------
# Phase 1 字典辅助
# ---------------------------------------------------------------------------

def _classify_dicts(
    dicts: List[dict],
    existing: Dict[str, dict],
    dict_codes: Dict[str, str],
    suffix: str,
) -> tuple[List[dict], List[str]]:
    """把 dicts 拆成 (new_dicts, reused_names)。

    副作用：写入 dict_codes 映射（复用用平台已有 code，新建用本地生成 code）。
    """
    new_dicts: List[dict] = []
    reused_names: List[str] = []
    for d in dicts:
        ed = existing.get(d["name"])
        if ed:
            pc = ed["dictionaryCode"]
            dict_codes[d["name"]] = pc
            dict_codes[d.get("code", d["name"])] = pc
            reused_names.append(d["name"])
        else:
            dc = _apply_suffix(_sanitize_code(d.get('code', 'dict')), suffix)
            dict_codes[d["name"]] = dc
            dict_codes[d.get("code", d["name"])] = dc
            new_dicts.append(d)
    return new_dicts, reused_names


async def _seed_dict_options(
    client: APaaSClient,
    app_id: str,
    new_dicts: List[dict],
    dict_codes: Dict[str, str],
    suffix: str,
) -> int:
    """为新建字典灌入选项（直连 httpx，因 client 未封装该接口）。

    返回写入的选项总数。
    """
    all_platform_dicts = await client.query_dicts(app_id)
    dict_by_code = {d.get("dictionaryCode"): d for d in all_platform_dicts}
    total_opts = 0
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        headers = client._get_headers(app_id)
        for d in new_dicts:
            dc = dict_codes[d["name"]]
            obj = dict_by_code.get(dc)
            if not obj or not d.get("options"):
                continue
            dict_id = obj["id"]
            for idx, opt in enumerate(d["options"]):
                opt_name = opt["name"] if isinstance(opt, dict) else str(opt)
                opt_code_raw = opt.get("code", f"opt{idx}") if isinstance(opt, dict) else f"opt{idx}"
                await http.post(
                    f"{client.base_url}/xdap-app/dataDictionary/add/dictionaryValue",
                    headers=headers,
                    json={
                        "appId": app_id,
                        "dictionaryId": dict_id,
                        "valueCode": _apply_suffix(_sanitize_code(opt_code_raw), suffix),
                        "valueName": opt_name,
                        "valueNameI18nAssociated": False,
                        "valueNameI18nResourceCode": "",
                        "valueNameI18n": {},
                        "displayOrder": idx,
                        "valueDescribe": "",
                        "valueStatus": "ENABLE",
                        "valueMulticolor": "#027AFF",
                    },
                )
                total_opts += 1
    return total_opts


def _select_models_and_dicts(
    all_models: List[dict],
    dicts: List[dict],
    selected_indices: Optional[List[int]],
) -> tuple[List[dict], List[dict]]:
    """根据 selected_model_indices 过滤模型与字典。

    字典只保留被选中模型（含子字段）引用的。
    """
    if selected_indices is not None and len(selected_indices) < len(all_models):
        models = [all_models[i] for i in selected_indices if i < len(all_models)]
    else:
        models = all_models

    if selected_indices is not None:
        used = set()
        for m in models:
            for f in m.get("fields", []):
                if f.get("dict"):
                    used.add(f["dict"])
                for sf in f.get("sub_fields", []):
                    if sf.get("dict"):
                        used.add(sf["dict"])
        if used:
            dicts = [d for d in dicts if d.get("code") in used]

    return models, dicts


# ---------------------------------------------------------------------------
# 主生成流程
# ---------------------------------------------------------------------------

async def run_complete_generation(
    client: APaaSClient,
    app_id: str,
    config: dict,
) -> AsyncGenerator[Dict, None]:
    """完整的应用生成流程，通过 SSE yield 进度事件"""

    data = config.get("data", config)
    app_name = data.get("appName", "应用")
    roles = data.get("roles", [])
    dicts = data.get("dicts", [])
    all_models = data.get("models", [])
    all_forms = data.get("forms", [])

    models, dicts = _select_models_and_dicts(
        all_models, dicts, config.get("selected_model_indices")
    )

    suffix = _rand()

    # ==================================================================
    # Phase 0: 解析配置
    # ==================================================================
    yield {"stage": 0, "status": "running", "step": f"{len(models)} 个表单、{len(dicts)} 个字典、{len(roles)} 个角色"}
    yield {"stage": 0, "status": "done", "step": "配置解析完成"}

    # ==================================================================
    # Phase 1: 公共资源（角色 + 字典）
    # ==================================================================
    yield {"stage": 1, "status": "running", "step": "创建公共资源..."}
    dict_codes: Dict[str, str] = {}  # {原始name或code: 平台dictCode}
    role_code_map: Dict[str, dict] = {}

    # --- 角色 ---
    if roles:
        try:
            roles_payload = []
            for r in roles:
                original_code = str(r.get("code", r["name"]))
                platform_code = _apply_suffix(_sanitize_code(original_code), suffix)
                role_code_map[original_code] = {"roleCode": platform_code, "roleName": r["name"]}
                roles_payload.append({
                    "appId": app_id,
                    "roleCode": platform_code,
                    "roleName": r["name"],
                })
            await client.create_roles(app_id, roles_payload)
            try:
                remote_roles = await client.query_roles(app_id)
                for r in roles:
                    original_code = str(r.get("code", r["name"]))
                    local_info = role_code_map.setdefault(original_code, {})
                    platform_code = local_info.get("roleCode")
                    matched = next((
                        item for item in remote_roles
                        if item.get("roleCode") == platform_code
                        or item.get("roleName") == r.get("name")
                    ), None)
                    if matched:
                        local_info["id"] = matched.get("id", "")
                        local_info["roleCode"] = matched.get("roleCode", platform_code)
                        local_info["roleName"] = matched.get("roleName", r.get("name", original_code))
            except Exception as exc:
                logger.warning("查询平台角色ID失败，权限下发将退回角色编码: %s", exc)
            yield {"stage": 1, "status": "running", "step": f"角色: {', '.join(r['name'] for r in roles)}"}
        except Exception as e:
            if "已存在" in str(e) or "重复" in str(e):
                yield {"stage": 1, "status": "running", "step": "角色已存在，跳过"}
            else:
                yield {"stage": 1, "status": "running", "step": f"角色创建失败（继续）: {e}"}

    # --- 字典 ---
    if dicts:
        try:
            existing = {d.get("dictionaryName"): d for d in await client.query_dicts(app_id)}
            new_dicts, reused_names = _classify_dicts(dicts, existing, dict_codes, suffix)
            for name in reused_names:
                yield {"stage": 1, "status": "running", "step": f"复用字典: {name}"}

            if new_dicts:
                payload = [
                    {
                        "appId": app_id,
                        "dictionaryCode": dict_codes[d["name"]],
                        "dictionaryName": d["name"],
                        "dictionaryOptions": [],
                    }
                    for d in new_dicts
                ]
                await client.create_dicts(app_id, payload)
                total_opts = await _seed_dict_options(client, app_id, new_dicts, dict_codes, suffix)
                yield {"stage": 1, "status": "running", "step": f"新建 {len(new_dicts)} 个字典，{total_opts} 个选项"}
        except Exception as e:
            logger.error(f"字典创建失败: {e}", exc_info=True)
            yield {"stage": 1, "status": "error", "step": f"字典创建失败: {e}"}
            return

    yield {"stage": 1, "status": "done", "step": "公共资源完成"}

    # ==================================================================
    # Phase 2: 数据模型
    # ==================================================================
    yield {"stage": 2, "status": "running", "step": "创建数据模型..."}

    if not models:
        yield {"stage": 2, "status": "error", "step": "没有数据模型"}
        return

    # model_info: {idx: {name, code, fields: {fieldName: fieldCode}}}
    # 子表 key 格式: "{idx}_sub_{子表名}"
    model_info: Dict = {}

    try:
        existing_models = await client.query_models(app_id)
        existing_by_name = {m.get("modelName"): m for m in existing_models}
        reused, new_models_to_create = _classify_models_reuse_vs_new(
            models, existing_by_name, model_info
        )
        for m in reused:
            yield {"stage": 2, "status": "running", "step": f"复用: {m['name']}"}

        if new_models_to_create:
            payload = _build_model_payload_with_subs(
                new_models_to_create, app_id, suffix, model_info
            )

            try:
                await client.create_models(app_id, payload)
                yield {"stage": 2, "status": "running", "step": f"新建: {'、'.join(m['name'] for _, m in new_models_to_create)}"}
                await _refresh_model_codes_from_platform(
                    client, app_id, new_models_to_create, model_info
                )
            except Exception as e:
                if "编码重复" in str(e) or "已存在" in str(e):
                    yield {"stage": 2, "status": "running", "step": "编码冲突，回退到复用模式..."}
                    await _rollback_models_to_reuse_by_name(
                        client, app_id, new_models_to_create, model_info
                    )
                else:
                    # 2026-05-30 韧性修复: 批量建模型失败(如某模型"字段总体超长")不再 raise
                    # 崩掉整个生成 → 降级逐个建, 单个失败就跳过记录, 让其余模型 + 后续表单照常生成。
                    logger.warning("批量建模型失败(%s), 降级逐个建", e)
                    yield {"stage": 2, "status": "running", "step": f"批量建模型遇错({str(e)[:40]}), 降级逐个建…"}
                    skipped_models: List[str] = []
                    for one in new_models_to_create:
                        m_name = str(one[1].get("name", "?"))
                        try:
                            one_payload = _build_model_payload_with_subs(
                                [one], app_id, suffix, model_info
                            )
                            await client.create_models(app_id, one_payload)
                        except Exception as e1:
                            if "编码重复" in str(e1) or "已存在" in str(e1):
                                await _rollback_models_to_reuse_by_name(
                                    client, app_id, [one], model_info
                                )
                            else:
                                skipped_models.append(m_name)
                                logger.warning("模型 %s 建失败已跳过: %s", m_name, e1)
                    await _refresh_model_codes_from_platform(
                        client, app_id, new_models_to_create, model_info
                    )
                    if skipped_models:
                        yield {"stage": 2, "status": "running",
                               "step": f"⚠️ {len(skipped_models)} 个模型建失败已跳过(字段超长等): {'、'.join(skipped_models)}"}

        if len(model_info) < len(models):
            missing_count = len(models) - len(model_info)
            yield {
                "stage": 2,
                "status": "error",
                "step": f"模型未完整创建，缺少 {missing_count} 个",
            }
            return
        yield {"stage": 2, "status": "done", "step": f"模型完成（{len(model_info)} 个）"}

    except Exception as e:
        logger.error(f"模型创建失败: {e}", exc_info=True)
        yield {"stage": 2, "status": "error", "step": f"模型创建失败: {e}"}
        return

    # ==================================================================
    # Phase 3: 表单 + 字典绑定
    # ==================================================================
    yield {"stage": 3, "status": "running", "step": "创建表单..."}

    form_results: List[dict] = []  # [{formId, formCode, formName, menuId}]
    try:
        model_lookup = _build_model_lookup(models, model_info)
        existing_forms = await _load_existing_form_menus(client, app_id)
        forms_to_build = _resolve_forms_to_build(all_forms, models)
        component_fixes = sync_form_components_with_model_fields({"models": models, "forms": forms_to_build})
        if component_fixes:
            yield {
                "stage": 3,
                "status": "running",
                "step": f"已按最新模型字段类型同步 {len(component_fixes)} 个表单组件",
            }
        forms_to_build, dependency_issues = _sort_forms_by_data_selector_dependencies(forms_to_build, existing_forms)
        if dependency_issues:
            message = (
                "表单数据选择依赖无法直接创建；字典和数据模型已创建完成，表单创建已停止。"
                "可选择：1) 降级冲突的数据选择组件后继续创建；2) 保留当前进度并调整配置后重试。"
                " 问题："
                + "；".join(dependency_issues)
            )
            yield {"stage": 3, "status": "error", "step": message}
            return
        dict_binding_context = None
        if dicts:
            try:
                all_platform_dicts, dict_id_map, dict_options_map = await _load_dict_binding_maps(client, app_id)
                base_dict_lookup = _build_base_dict_lookup(models, dict_codes, model_info, all_platform_dicts)
                dict_binding_context = (base_dict_lookup, dict_id_map, dict_options_map)
            except Exception as e:
                logger.warning("创建表单前加载字典绑定信息失败，将退回二次回写兜底: %s", e)

        for idx, form in enumerate(forms_to_build):
            form_name = _first_non_empty(
                form.get("formName"),
                form.get("form_name"),
                form.get("name"),
                form.get("modelCode"),
                form.get("model_code"),
                form.get("mainModelCode"),
                form.get("main_model_code"),
                default=f"表单{idx+1}",
            )
            model_code = str(_first_non_empty(
                form.get("modelCode"),
                form.get("model_code"),
                form.get("mainModelCode"),
                form.get("main_model_code"),
                form.get("main_model"),
                default="",
            )).strip()
            mi = model_lookup.get(model_code) if model_code else None
            if not mi and idx < len(models):
                mi = model_info.get(idx)
            if not mi:
                yield {"stage": 3, "status": "running", "step": f"跳过 {form_name}（无模型）"}
                continue

            all_model_codes = []
            all_model_source = form.get("allModelCodes") or form.get("all_model_codes") or [model_code]
            if isinstance(all_model_source, str):
                all_model_source = [all_model_source]
            for raw_code in all_model_source:
                resolved_code = model_lookup.get(str(raw_code).strip(), {}).get("code", raw_code)
                if resolved_code:
                    all_model_codes.append(resolved_code)
            all_model_codes = list(dict.fromkeys(all_model_codes or [mi["code"]]))
            requested_form_code = str(
                form.get("formCode") or form.get("form_code") or form.get("code") or ""
            ).strip()

            components, query_conditions, query_list = _build_form_components_from_definition(
                form=form,
                default_model_code=mi["code"],
                model_lookup=model_lookup,
            )

            if not components:
                model_fields = mi["fields"]
                for field_name, field_code in model_fields.items():
                    fallback_field = {"name": field_name, "type": "单行输入", "required": False}
                    components.append(_build_component(fallback_field, mi["code"], field_code, dict_codes, models, model_info))
                    if len(query_list) < 8:
                        mf = f"{mi['code']}.{field_code}"
                        if len(query_conditions) < 4:
                            query_conditions.append(mf)
                        query_list.append(mf)

            if not components:
                yield {"stage": 3, "status": "running", "step": f"跳过 {form_name}（无可用字段）"}
                continue

            if dict_binding_context:
                base_dict_lookup, dict_id_map, dict_options_map = dict_binding_context
                dict_lookup = dict(base_dict_lookup)
                dict_lookup.update(_collect_spec_component_dict_map([{"formComponents": components}], dict_codes))
                bound_at_create = _bind_dicts_on_component_tree(
                    components, dict_lookup, dict_id_map, dict_options_map, dict_codes
                )
                if bound_at_create:
                    logger.info("创建表单前已绑定下拉字典: form=%s count=%s", form_name, bound_at_create)

            if form_name in existing_forms:
                existing_form_id = existing_forms[form_name]
                form_results.append({
                    "formId": existing_form_id,
                    "formName": form_name,
                    "formCode": requested_form_code,
                    "modelCode": model_code or mi["code"],
                    "allModelCodes": all_model_codes,
                    "formComponents": copy.deepcopy(components),
                })
                try:
                    await _finalize_created_form_config(
                        client,
                        app_id,
                        form_id=existing_form_id,
                        form_name=form_name,
                        form_code=requested_form_code,
                        all_model_codes=all_model_codes,
                        form_components=components,
                    )
                except Exception as save_err:
                    logger.warning("复用表单固化详情失败（%s）: %s", form_name, save_err)
                yield {"stage": 3, "status": "running", "step": f"复用: {form_name}"}
                continue

            form_payload = _build_form_create_payload(
                form=form,
                form_name=form_name,
                all_model_codes=all_model_codes,
                components=components,
                query_conditions=query_conditions,
                query_list=query_list,
            )

            try:
                result = await client.create_form_config(app_id, form_payload)
                if isinstance(result, list):
                    for fr in result:
                        if isinstance(fr, dict) and "id" in fr:
                            form_id = fr["id"]
                            form_results.append({
                                "formId": form_id,
                                "formName": form_name,
                                "formCode": fr.get("formCode") or form_payload[0].get("formCode", ""),
                                "menuId": fr.get("menuId", ""),
                                "modelCode": model_code or mi["code"],
                                "allModelCodes": all_model_codes,
                                "formComponents": copy.deepcopy(form_payload[0].get("formComponents", [])),
                            })
                            # formConfig API 创建的菜单不可见，需要额外创建菜单
                            menu_id = str(fr.get("menuId") or "")
                            try:
                                menu_result = await client.create_menu(app_id, form_name, form_id, menu_order=idx)
                                menu_id = str(
                                    (menu_result or {}).get("id")
                                    or (menu_result or {}).get("menuId")
                                    or menu_id
                                )
                            except Exception as menu_err:
                                logger.warning(f"创建菜单失败（{form_name}）: {menu_err}")
                            form_results[-1]["menuId"] = menu_id
                            try:
                                await _finalize_created_form_config(
                                    client,
                                    app_id,
                                    form_id=form_id,
                                    form_name=form_name,
                                    form_code=form_results[-1]["formCode"],
                                    all_model_codes=all_model_codes,
                                    menu_id=menu_id,
                                    form_components=form_payload[0].get("formComponents", []),
                                )
                            except Exception as save_err:
                                logger.warning("创建后固化表单详情失败（%s）: %s", form_name, save_err)
                yield {"stage": 3, "status": "running", "step": f"创建: {form_name}"}
            except Exception as e:
                yield {"stage": 3, "status": "running", "step": f"失败 {form_name}: {e}"}

        # --- 绑定字典到表单（第二遍：用平台真实选项回写） ---
        form_ids = [fr["formId"] for fr in form_results if fr.get("formId")]
        if dicts and form_ids:
            try:
                bound_count = await _rebind_dicts_on_forms(
                    client, app_id, form_ids, models, dict_codes, form_results
                )
                if bound_count:
                    yield {"stage": 3, "status": "running", "step": f"字典绑定: {bound_count} 个表单"}
            except Exception as e:
                logger.warning(f"字典绑定阶段失败（不阻断）: {e}")

        expected_form_count = len(forms_to_build)
        if len(form_results) < expected_form_count:
            missing_count = expected_form_count - len(form_results)
            yield {
                "stage": 3,
                "status": "error",
                "step": f"表单未完整创建，缺少 {missing_count} 个",
            }
            return

        try:
            assoc_count = await _sync_association_components_on_forms(
                client=client,
                app_id=app_id,
                form_results=form_results,
                all_forms=forms_to_build,
            )
            if assoc_count:
                yield {"stage": 3, "status": "running", "step": f"关联表单补齐: {assoc_count} 个表单"}
        except Exception as e:
            logger.warning("关联表单补齐失败（不阻断）: %s", e)

        yield {"stage": 3, "status": "done", "step": f"表单完成（{len(form_results)} 个）"}

    except Exception as e:
        logger.error(f"表单创建失败: {e}", exc_info=True)
        yield {"stage": 3, "status": "error", "step": f"表单创建失败: {e}"}
        return

    # ==================================================================
    # Phase 4: 权限配置
    # ==================================================================
    permissions = data.get("permissions", [])
    if permissions or form_results:
        yield {"stage": 4, "status": "running", "step": "配置权限..."}
        try:
            perm_payloads: List[dict] = []
            permission_sync_jobs: List[dict] = []
            for fr in form_results:
                user_perm = _find_permission_for_form(fr, permissions)
                built = _build_permission_payload_for_form(fr, user_perm, role_code_map, app_id)
                if built is not None:
                    perm_payload, sync_job = built
                    perm_payloads.append(perm_payload)
                    permission_sync_jobs.append(sync_job)

            if perm_payloads:
                await _apply_permissions_and_sync(
                    client, app_id, perm_payloads, permission_sync_jobs, role_code_map
                )
                yield {"stage": 4, "status": "running", "step": f"配置 {len(perm_payloads)} 个表单权限"}

            yield {"stage": 4, "status": "done", "step": "权限配置完成"}
        except Exception as e:
            # 权限失败不阻断整体流程
            logger.warning(f"权限配置失败: {e}")
            yield {"stage": 4, "status": "done", "step": f"权限配置跳过: {e}"}
    else:
        yield {"stage": 4, "status": "done", "step": "无权限配置"}

    # ==================================================================
    # Phase 5: 审批流程（可选；非核心，失败不阻断 —— create_workflows 自带逐条容错）
    # ==================================================================
    async for _wf_ev in create_workflows(
        client, app_id, data.get("workflows", []), form_results, role_code_map
    ):
        yield _wf_ev

    # ==================================================================
    # 完成
    # ==================================================================
    yield {
        "type": "complete",
        "message": f"应用 {app_name} 生成完成！共 {len(form_results)} 个表单",
    }
