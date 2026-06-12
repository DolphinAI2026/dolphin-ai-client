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
from typing import List

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
    "_clone_for_form_config_permissions",
    "_normalize_permission_range",
    "_query_saveable_form_config",
]
