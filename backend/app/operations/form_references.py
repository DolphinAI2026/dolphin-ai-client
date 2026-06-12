"""表单引用解析（数据选择 / 关联表单）的共享原子工具。

generator_v2 与 step_executor 都要把 spec 组件定义里的「目标表单 / 目标模型 / 目标字段」
引用解析成平台模型 code 与对应已创建表单。两侧此前各有一份实现且**双向漂移**：

  - _resolve_component_reference: generator_v2 侧领先——多了 dataSelectorConfig
    (selector.otherModelCode / otherFieldCode) 分支(c706e18e 加)。step 侧的 spec 组件
    定义此时只带 selector_form_code 等 spec 键、还没有 dataSelectorConfig，所以该分支对
    step 的实际入参是 no-op；取并集对两侧都安全。
  - _resolve_target_form_result: step 侧领先——多试 code / formName / form_name / name
    四个候选键(bb181dd6「stabilize ai builder workflow」加)。匹配 guard 两侧已一致，
    多试候选键只会多命中、不会错配(命中后仍走同一套严格 guard)。

这里取「两侧并集」收敛成单一实现，两条路径共用，消除漂移。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.operations.form_config import _first_non_empty


def _resolve_component_reference(comp_def: dict, form_map: Dict[str, dict]) -> tuple[str, str, str]:
    """解析组件引用的 (目标模型 code, 目标字段 code, 来源字段 code)。

    覆盖 formAssociationConfig（关联表单）/ dataSelectorConfig（数据选择）/ spec 键
    （selector_form_code 等）/ ref 字典等多种引用形态，按优先级取第一个非空。
    """
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
    """在已创建的 form_results 中找到组件引用指向的那张表单。

    先按组件定义里的多种身份键（selector/association/formCode/code/formName/... 及 ref
    里的 formCode）在 form_map 里定位目标表单定义，再用 formCode/formName/modelCode 的
    多别名严格 guard 在 form_results 中匹配；都不中时按 target_model_code 兜底。
    """
    ref = comp_def.get("ref") or {}
    for value in (
        comp_def.get("selector_form_code"),
        comp_def.get("association_form_code"),
        comp_def.get("formCode"),
        comp_def.get("form_code"),
        comp_def.get("code"),
        comp_def.get("formName"),
        comp_def.get("form_name"),
        comp_def.get("name"),
        ref.get("formCode") if isinstance(ref, dict) else "",
        ref.get("form_code") if isinstance(ref, dict) else "",
    ):
        candidate = str(value or "").strip()
        if not candidate:
            continue
        form_def = form_map.get(candidate)
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


__all__ = [
    "_resolve_component_reference",
    "_resolve_target_form_result",
]
