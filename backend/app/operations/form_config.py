"""表单配置原子工具——generator_v2 / step_executor 两条路径共享。

内容（从 app/generator_v2.py / app/step_executor.py 逐字搬入，行为完全一致）：
  _iter_form_components               展开表单组件（含子表 FORM_WIDGET_SON_TABLE 列）
  _component_field_code               从组件解析字段编码（modelField 优先）
  _clone_for_form_config_permissions  深拷贝并归一化权限对象（ROLE→ROLE_USER 等）
  _normalize_permission_range         数据范围字符串归一化（all→ALL 等）
  _query_saveable_form_config         查询可保存的表单配置（带回退）

这 5 个函数此前在 generator_v2.py 与 step_executor.py 中各有一份逐字相同的实现，
现收敛到本模块作为单一来源。两侧改为从这里 import；generator_v2 / step_executor
保留 re-export 以兼容历史 `from app.step_executor import _iter_form_components` 之类引用。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.apaas_client import APaaSClient

logger = logging.getLogger(__name__)


def _iter_form_components(form_components: List[dict]) -> List[dict]:
    items: List[dict] = []
    for component in form_components or []:
        items.append(component)
        if component.get("componentType") == "FORM_WIDGET_SON_TABLE":
            items.extend(component.get("tableColumn", []) or [])
    return items


def _component_field_code(component: dict) -> str:
    model_field = str(component.get("modelField", "")).strip()
    if "." in model_field:
        return model_field.split(".", 1)[1]
    return str(component.get("code", "")).strip()


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


def _find_component_by_field(form_components: List[dict], field_code: str, *, label: str = "") -> Optional[dict]:
    normalized_field = str(field_code or "").strip()
    normalized_label = str(label or "").strip()
    for component in _iter_form_components(form_components):
        if normalized_field and _component_field_code(component) == normalized_field:
            return component
        if normalized_label and str(component.get("label", "")).strip() == normalized_label:
            return component
    return None


def _form_identity_map(forms: List[dict]) -> Dict[str, dict]:
    """按表单的各种身份键（code/name/modelCode 等）建 {身份值: form} 映射。

    两侧此前实现仅差一处空值保护（generator_v2 用 ``forms or []`` 防 None，step_executor
    直接 ``forms`` 在 None 时会抛）。收敛取空安全版本，行为对非 None 入参完全一致。
    """
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


def _clone_for_form_config_permissions(value):
    if isinstance(value, list):
        return [_clone_for_form_config_permissions(item) for item in value]
    if isinstance(value, dict):
        cloned = {k: _clone_for_form_config_permissions(v) for k, v in value.items()}
        for type_key, value_key in (
            ("permissionObjectType", "permissionObjectValue"),
            ("permissionType", "permissionValue"),
        ):
            if cloned.get(type_key) == "ROLE":
                cloned[type_key] = "ROLE_USER"
            if cloned.get(type_key) == "ALL_USER":
                cloned[value_key] = ""
        return cloned
    return value


def _normalize_permission_range(data_range: object) -> str:
    range_map = {
        "all": "ALL",
        "self": "SELF",
        "dept": "CURRENT_USER_DEPT",
        "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
    }
    if isinstance(data_range, str):
        return range_map.get(data_range, data_range.upper())
    return "ALL"


async def _query_saveable_form_config(client: APaaSClient, app_id: str, form_id: str) -> dict:
    query_context = getattr(client, "query_form_context_config", None)
    if callable(query_context):
        try:
            return await query_context(app_id, form_id)
        except Exception as exc:
            logger.warning("query_form_context_config 失败，回退 detailPageConfigById (formId=%s): %s", form_id, exc)
    return await client.query_detail_page_config(app_id, form_id)


__all__ = [
    "_iter_form_components",
    "_component_field_code",
    "_first_non_empty",
    "_form_identity_map",
    "_find_component_by_field",
    "_build_display_component_refs",
    "_clone_for_form_config_permissions",
    "_normalize_permission_range",
    "_query_saveable_form_config",
]
