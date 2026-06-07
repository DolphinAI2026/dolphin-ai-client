"""Keep parsed form components aligned with canonical model field definitions."""
from __future__ import annotations

from typing import Any, Dict, List

from app.field_types import get_comp_type_map, get_dict_field_types, get_ref_field_types


_COMP_TYPE_MAP = get_comp_type_map()
_DICT_FIELD_TYPES = get_dict_field_types()
_REF_FIELD_TYPES = get_ref_field_types()
_REFERENCE_KEYS = (
    "ref",
    "selector_form_code",
    "selector_field_code",
    "association_form_code",
    "association_origin_field_code",
    "association_target_field_code",
    "ref_model_code",
    "ref_display_field_code",
    "dataSelectorConfig",
    "data_selector_config",
    "formAssociationConfig",
    "form_association_config",
)
_DICT_KEYS = (
    "dict",
    "dictCode",
    "dict_code",
    "dictionaryCode",
    "dictionarySelectConfig",
    "dictionary_choose_options",
)
_REFERENCE_COMPONENT_TYPES = {
    "FORM_DATA_SELECTOR_SINGLE",
    "FORM_DATA_SELECTOR",
    "FORM_ASSOCIATION",
}


def _model_field_index(models: List[dict]) -> Dict[str, Dict[str, dict]]:
    index: Dict[str, Dict[str, dict]] = {}
    for model in models or []:
        if not isinstance(model, dict):
            continue
        model_code = str(model.get("code") or "").strip()
        if not model_code:
            continue
        fields = index.setdefault(model_code, {})
        for field in model.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_code = str(field.get("code") or "").strip()
            field_type = str(field.get("type") or "").strip()
            if field_code and field_type != "子表":
                fields[field_code] = field
            if field_type == "子表":
                sub_code = str(field.get("sub_code") or "").strip()
                if not sub_code:
                    continue
                sub_fields = index.setdefault(sub_code, {})
                for sub_field in field.get("sub_fields") or []:
                    if isinstance(sub_field, dict) and sub_field.get("code"):
                        sub_fields[str(sub_field["code"]).strip()] = sub_field
    return index


def _component_model_and_field(component: dict) -> tuple[str, str]:
    model_field = str(component.get("modelField") or component.get("model_field") or "").strip()
    if "." in model_field:
        model_code, field_code = model_field.split(".", 1)
        return model_code.strip(), field_code.strip()
    model_code = str(
        component.get("modelCode")
        or component.get("model_code")
        or component.get("tableModelCode")
        or component.get("table_model_code")
        or ""
    ).strip()
    field_code = str(component.get("code") or component.get("field_code") or "").strip()
    return model_code, field_code


def _has_reference_target(component: dict) -> bool:
    association = component.get("formAssociationConfig") or component.get("form_association_config") or {}
    selector = component.get("dataSelectorConfig") or component.get("data_selector_config") or {}
    ref = component.get("ref") or {}
    if association.get("targetModelCode") or selector.get("otherModelCode"):
        return True
    if component.get("selector_form_code") or component.get("association_form_code"):
        return True
    if component.get("ref_model_code"):
        return True
    if isinstance(ref, dict):
        return bool(ref.get("model"))
    return bool(ref)


def _sync_component(component: dict, field: dict) -> bool:
    changed = False
    field_type = str(field.get("type") or "单行输入").strip() or "单行输入"
    expected_component_type = _COMP_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT")
    component_type = str(component.get("componentType") or component.get("component_type") or "").strip()
    is_reference_component = component_type in _REFERENCE_COMPONENT_TYPES

    should_force_component_type = (
        field_type in _REF_FIELD_TYPES
        or (is_reference_component and not _has_reference_target(component))
    )
    if should_force_component_type and component.get("componentType") != expected_component_type:
        component["componentType"] = expected_component_type
        changed = True

    if field_type not in _REF_FIELD_TYPES and is_reference_component and not _has_reference_target(component):
        for key in _REFERENCE_KEYS:
            if key in component:
                component.pop(key, None)
                changed = True
    elif isinstance(field.get("ref"), dict) and field.get("ref"):
        ref = field["ref"]
        display_field = (
            ref.get("display_field")
            or ref.get("target_field")
            or ref.get("field")
            or ""
        )
        desired_ref = {
            "model": ref.get("model", ""),
            "display_field": display_field,
            "target_field": display_field,
            "field": display_field,
        }
        if component.get("ref") != desired_ref:
            component["ref"] = desired_ref
            changed = True
        if field_type in {"数据单选", "数据选择", "数据多选"}:
            if component.get("selector_form_code") != desired_ref["model"]:
                component["selector_form_code"] = desired_ref["model"]
                changed = True
            if display_field and component.get("selector_field_code") != display_field:
                component["selector_field_code"] = display_field
                changed = True

    if field_type in _DICT_FIELD_TYPES:
        dict_code = str(field.get("dict") or "").strip()
        if dict_code:
            for key in ("dict", "dictCode", "dict_code"):
                if component.get(key) != dict_code:
                    component[key] = dict_code
                    changed = True

    return changed


def sync_form_components_with_model_fields(config: Dict[str, Any]) -> List[dict]:
    """Mutate config forms so component types match the latest model field types.

    Returns a small list of changed components for diagnostics/tests.
    """
    if not isinstance(config, dict):
        return []
    data = config.get("data") if isinstance(config.get("data"), dict) else config
    models = data.get("models") or []
    forms = data.get("forms") or []
    field_index = _model_field_index(models)
    changes: List[dict] = []

    def visit(component: dict, form: dict) -> None:
        if not isinstance(component, dict):
            return
        model_code, field_code = _component_model_and_field(component)
        field = field_index.get(model_code, {}).get(field_code)
        before = component.get("componentType")
        if field and _sync_component(component, field):
            changes.append({
                "form": form.get("code") or form.get("formCode") or form.get("name"),
                "model": model_code,
                "field": field_code,
                "from": before,
                "to": component.get("componentType"),
                "field_type": field.get("type"),
            })
        for child in component.get("tableColumn") or []:
            visit(child, form)

    for form in forms:
        if not isinstance(form, dict):
            continue
        for component in form.get("components") or form.get("fields") or []:
            visit(component, form)

    return changes
