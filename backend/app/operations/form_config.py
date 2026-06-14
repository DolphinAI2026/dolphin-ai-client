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


def _apply_form_identity_to_form_config(
    form_config: dict,
    *,
    form_name: str,
    form_code: str = "",
    all_model_codes: Optional[List[str]] = None,
    app_id: str = "",
    form_id: str = "",
    menu_id: str = "",
) -> bool:
    """save_form_config 前强制覆盖表单标识字段(canonical, 收口自 step_executor)。

    平台 query_detail_page_config 某些时机返回 formName="我的待办"(默认占位)。直接存回
    会把建表时的真实表单名抹掉,所有表单都变"我的待办"。本函数在保存前固化标识字段。
    返回 bool 标识是否有改动(供分步/增量路径做变更追踪;一把梭路径忽略返回即可)。

    收口前 generator_v2._force_form_identity(无条件设、返 None)与本实现(带 != 守卫、
    返 bool)对 form_config 的最终 mutation 逐字段等价;两侧均不注入 webFormSettings/
    mobileFormSettings(见下)。
    """
    if not isinstance(form_config, dict):
        return False

    changed = False
    desired_name = str(form_name or "").strip()
    desired_code = str(form_code or "").strip()
    desired_app_id = str(app_id or "").strip()
    desired_form_id = str(form_id or "").strip()
    desired_menu_id = str(menu_id or "").strip()
    desired_models = [
        str(code).strip()
        for code in (all_model_codes or [])
        if str(code).strip()
    ]

    def _apply(target: dict) -> None:
        nonlocal changed
        if not isinstance(target, dict):
            return
        if desired_name and target.get("formName") != desired_name:
            target["formName"] = desired_name
            changed = True
        if desired_code and target.get("formCode") != desired_code:
            target["formCode"] = desired_code
            changed = True
        if desired_models and target.get("allModelCodes") != desired_models:
            target["allModelCodes"] = desired_models
            changed = True
        if desired_app_id and target.get("appId") != desired_app_id:
            target["appId"] = desired_app_id
            changed = True
        if desired_form_id and not target.get("id"):
            target["id"] = desired_form_id
            changed = True
        if desired_menu_id and target.get("menuId") != desired_menu_id:
            target["menuId"] = desired_menu_id
            changed = True

    _apply(form_config)
    _apply(form_config.get("simpleFormConfig", {}))
    if not isinstance(form_config.get("detailPage"), dict):
        form_config["detailPage"] = {}
        changed = True
    detail_page = form_config["detailPage"]
    _apply(detail_page)
    for required_key, default_value in (
        # ⚠️ 不要注入 webFormSettings / mobileFormSettings —— apaas 把空 {} 展开成指向不存在
        # "formName" 标题组件的 formTitleConfigList, 表单设计器画布渲染崩(暂无数据)。
        # 原生/对话建的表单都不带这俩, 交给 apaas 自处理。
        ("previewLanguage", "zh-CN"),
        ("formVersionConfig", {}),
    ):
        if required_key not in detail_page:
            detail_page[required_key] = default_value
            changed = True
    if "formModelType" not in form_config:
        form_config["formModelType"] = "DATABASE"
        changed = True
    return changed


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
    "_apply_form_identity_to_form_config",
]
