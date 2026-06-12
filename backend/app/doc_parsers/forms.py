"""表单配置解析器"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table, parse_all_tables, bool_cell
from app.field_types import get_comp_type_map


_COMP_TYPE_MAP = get_comp_type_map()
_DEFAULT_LIST_SHOW_COUNT = 5
_REFERENCE_COMPONENT_TYPES = {
    "数据单选",
    "数据选择",
    "关联表单",
    "FORM_DATA_SELECTOR_SINGLE",
    "FORM_DATA_SELECTOR",
    "FORM_ASSOCIATION",
}


def _normalize_subtable_name(name: str) -> str:
    text = (name or "").strip()
    text = re.sub(r"[（(][^）)]+[）)]", "", text).strip()
    return text


def _apply_model_field_defaults(component: dict, model_field: dict, field_code: str) -> dict:
    """组件未显式声明时，继承模型字段上的字典/引用配置。"""
    if not component.get("dictCode"):
        component["dictCode"] = (
            model_field.get("dictCode")
            or model_field.get("dict_code")
            or model_field.get("dict")
            or ""
        )

    if not component.get("ref"):
        ref = model_field.get("ref") or {}
        if isinstance(ref, dict) and ref.get("model"):
            display_field = (
                ref.get("display_field")
                or ref.get("target_field")
                or ref.get("field")
                or ""
            )
            component["ref"] = {
                "model": ref.get("model", ""),
                "display_field": display_field,
                "target_field": display_field,
                "field": display_field,
            }
            if not component.get("selector_form_code"):
                component["selector_form_code"] = ref.get("model", "")
            if display_field and not component.get("selector_field_code"):
                component["selector_field_code"] = display_field
            if not component.get("ref_model_code"):
                component["ref_model_code"] = ref.get("model", "")
            if display_field and not component.get("ref_display_field_code"):
                component["ref_display_field_code"] = display_field

    if not component.get("formAssociationConfig"):
        association = model_field.get("formAssociationConfig") or {}
        if isinstance(association, dict) and association.get("targetModelCode"):
            component["formAssociationConfig"] = {
                "originFieldCode": association.get("originFieldCode") or field_code,
                "targetModelCode": association.get("targetModelCode", ""),
                "targetFieldCode": association.get("targetFieldCode", ""),
            }
    association = component.get("formAssociationConfig") or {}
    if isinstance(association, dict) and association.get("targetModelCode"):
        if not component.get("association_form_code"):
            component["association_form_code"] = association.get("targetModelCode", "")
        if not component.get("association_origin_field_code"):
            component["association_origin_field_code"] = association.get("originFieldCode") or field_code
        if not component.get("association_target_field_code"):
            component["association_target_field_code"] = association.get("targetFieldCode", "")

    return component


def _build_default_component(field_code: str, model_field: dict, model_code: str, show_in_list: bool) -> dict:
    field_type = model_field.get("type", "单行输入")
    return {
        "code": field_code,
        "label": model_field.get("name", field_code),
        "componentType": _COMP_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT"),
        "modelField": f"{model_code}.{field_code}",
        "modelCode": model_code,
        "sectionType": "main",
        "hidden": False,
        "readonly": False,
        "required": False,
        "showInList": show_in_list,
        "searchable": False,
    }


def _is_reference_component(comp_type_raw: str, field_type: str) -> bool:
    return bool((comp_type_raw or "").strip() in _REFERENCE_COMPONENT_TYPES or (field_type or "").strip() in _REFERENCE_COMPONENT_TYPES)


def _infer_target_model_code(
    field_code: str,
    field_label: str,
    description: str,
    current_model_code: str,
    models: List[dict],
) -> str:
    models_by_code = {
        str(model.get("code") or "").strip().lower(): model
        for model in models
        if str(model.get("code") or "").strip()
    }
    if not models_by_code:
        return ""

    suffix_candidates: list[str] = []
    label_candidates: list[str] = []
    desc_candidates: list[str] = []

    def add_candidate(bucket: list[str], code: str):
        normalized = str(code or "").strip().lower()
        if normalized and normalized in models_by_code and normalized != current_model_code and normalized not in bucket:
            bucket.append(normalized)

    for suffix in ("_ref", "_id"):
        if field_code.endswith(suffix):
            add_candidate(suffix_candidates, field_code[: -len(suffix)])

    normalized_label = str(field_label or "").strip()
    normalized_desc = str(description or "").strip()
    for code, model in models_by_code.items():
        model_name = str(model.get("name") or "").strip()
        if normalized_label and model_name and (
            normalized_label == model_name
            or normalized_label in model_name
            or model_name in normalized_label
        ):
            add_candidate(label_candidates, code)
        if normalized_desc and model_name and (
            model_name in normalized_desc
            or f"选择{model_name}" in normalized_desc
            or f"关联{model_name}" in normalized_desc
            or f"{model_name}主数据" in normalized_desc
        ):
            add_candidate(desc_candidates, code)

    for bucket in (suffix_candidates, label_candidates, desc_candidates):
        if len(bucket) == 1:
            return bucket[0]
    return ""


def _infer_target_field_code(target_model_code: str, field_label: str, model_field_index: dict) -> str:
    fields_map = model_field_index.get(target_model_code, {}) or {}
    if not fields_map:
        return ""

    preferred_codes = [f"{target_model_code}_name", "name"]
    preferred_names = [f"{field_label}名称", "名称", "名字"]

    for code in preferred_codes:
        if code in fields_map:
            return code

    for field in fields_map.values():
        if str(field.get("name") or "").strip() in preferred_names:
            return str(field.get("code") or "").strip()

    for field in fields_map.values():
        code = str(field.get("code") or "").strip()
        if code.endswith("_name"):
            return code

    for field in fields_map.values():
        if str(field.get("name") or "").strip().endswith("名称"):
            return str(field.get("code") or "").strip()

    return ""


def _field_code_from_model_field(model_field: str) -> str:
    raw = str(model_field or "").strip()
    return raw.split(".")[-1] if "." in raw else raw


def _infer_association_origin_field_code(
    explicit_origin_field_code: str,
    current_model_fields: dict,
    target_model_code: str,
    model_field_index: dict,
) -> str:
    explicit = str(explicit_origin_field_code or "").strip()
    if explicit:
        return explicit

    target_fields = model_field_index.get(target_model_code, {}) or {}
    if not current_model_fields or not target_fields:
        return ""

    shared_ref_codes = [
        code for code in current_model_fields.keys()
        if code in target_fields and str(code).endswith("_ref")
    ]
    if len(shared_ref_codes) == 1:
        return shared_ref_codes[0]

    shared_codes = [code for code in current_model_fields.keys() if code in target_fields]
    if len(shared_codes) == 1:
        return shared_codes[0]

    return ""


def _infer_association_target_field_code(
    explicit_target_field_code: str,
    origin_field_code: str,
    target_model_code: str,
    current_model_fields: dict,
    model_field_index: dict,
) -> str:
    explicit = str(explicit_target_field_code or "").strip()
    if explicit:
        return explicit

    target_fields = model_field_index.get(target_model_code, {}) or {}
    if not target_fields:
        return ""

    if origin_field_code and origin_field_code in target_fields:
        return origin_field_code

    origin_field = current_model_fields.get(origin_field_code or "", {}) if isinstance(current_model_fields, dict) else {}
    origin_ref = origin_field.get("ref") if isinstance(origin_field, dict) else {}
    origin_ref_model = str(origin_ref.get("model") or "").strip()

    if origin_ref_model:
        matched = [
            str(code)
            for code, field in target_fields.items()
            if isinstance(field, dict) and str((field.get("ref") or {}).get("model") or "").strip() == origin_ref_model
        ]
        if len(matched) == 1:
            return matched[0]

    return ""


def parse(section_text: str, models: List[dict]) -> Tuple[List[dict], List[str]]:
    errors: List[str] = []
    aggregate_forms, aggregate_errors = _parse_aggregate_tables(section_text, models)
    if aggregate_forms:
        return aggregate_forms, aggregate_errors

    forms: List[dict] = []

    model_field_index: dict = {}
    model_name_index: dict = {}
    for m in models:
        model_field_index[m["code"]] = {
            f["code"]: f for f in m.get("fields", [])
            if f.get("type") != "子表"
        }
        model_name_index[m["code"].strip().lower()] = m["code"]
        model_name_index[m.get("name", m["code"]).strip().lower()] = m["code"]

    subsections = split_subsections(section_text)
    if not subsections:
        errors.append("表单配置：未找到 ### 子章节")
        return [], errors

    for form_name, model_code, _tag, content in subsections:
        meta = _extract_form_meta(content)
        if meta["model_code"]:
            model_code = meta["model_code"]
        if meta["form_name"]:
            form_name = meta["form_name"]

        if not model_code:
            errors.append(f"表单 '{form_name}'：未能找到绑定模型编码")
            continue

        model_code = model_name_index.get(model_code.strip().lower(), model_code.lower())
        model_fields = model_field_index.get(model_code)
        if model_fields is None:
            errors.append(f"表单 '{form_name}'：模型编码 '{model_code}' 未在数据模型中定义")
            continue

        field_rows = meta["main_rows"] or _extract_field_rows(content)
        components = _build_components(
            field_rows,
            form_name,
            model_code,
            model_fields,
            errors,
            section_type="main",
            all_models=models,
            model_field_index=model_field_index,
        )

        subtable_defs = meta["subtable_defs"]
        subtable_components = _build_subtable_components(content, subtable_defs, model_field_index, errors)
        components.extend(subtable_components)

        # 未出现的模型字段用默认值补充
        seen = {c["code"] for c in components}
        list_shown = sum(1 for c in components if c["showInList"])
        for fc, mf in model_fields.items():
            if fc in seen:
                continue
            default_show = list_shown < _DEFAULT_LIST_SHOW_COUNT
            components.append(_build_default_component(fc, mf, model_code, default_show))
            if default_show:
                list_shown += 1

        all_model_codes = [model_code] + [
            d["model_code"] for d in subtable_defs if d.get("model_code")
        ]
        forms.append({
            "code": model_code,
            "name": form_name,
            "formName": form_name,
            "formCode": model_code,
            "modelCode": model_code,
            "allModelCodes": list(dict.fromkeys(all_model_codes)),
            "components": components,
        })

    return forms, errors


def _parse_aggregate_tables(section_text: str, models: List[dict]) -> Tuple[List[dict], List[str]]:
    """兼容标准模版的总表结构：
    - 表单清单
    - 主表字段定义
    - 子表区域定义
    - 子表字段定义
    """
    errors: List[str] = []
    all_tables = parse_all_tables(section_text)
    if not all_tables:
        return [], errors

    form_list_rows = None
    main_field_rows: list[dict] = []
    subtable_def_rows: list[dict] = []
    subfield_rows: list[dict] = []

    for table in all_tables:
        if not table:
            continue
        first_row = table[0]
        if form_list_rows is None and "表单名称" in first_row and "绑定主表模型" in first_row:
            form_list_rows = table
        elif (
            "表单名称" in first_row
            and "字段编码" in first_row
            and "子表区域名称" not in first_row
        ):
            main_field_rows.extend(table)
        elif (
            "表单名称" in first_row
            and "子表区域名称" in first_row
            and "绑定模型" in first_row
        ):
            subtable_def_rows.extend(table)
        elif (
            "表单名称" in first_row
            and "子表区域名称" in first_row
            and "字段编码" in first_row
        ):
            subfield_rows.extend(table)

    if not form_list_rows:
        return [], errors

    model_field_index: dict = {}
    model_name_index: dict = {}
    form_model_map: dict = {}
    for m in models:
        code = m["code"]
        model_field_index[code] = {f["code"]: f for f in m.get("fields", []) if f.get("type") != "子表"}
        model_name_index[code.strip().lower()] = code
        model_name_index[m.get("name", code).strip().lower()] = code
    for row in form_list_rows:
        form_code = (row.get("表单编码") or "").strip().lower()
        raw_model_code = (row.get("绑定主表模型") or "").strip()
        model_code = model_name_index.get(raw_model_code.strip().lower(), raw_model_code.lower())
        if form_code and model_code:
            form_model_map[form_code] = model_code

    forms: List[dict] = []
    for idx, row in enumerate(form_list_rows):
        form_name = (row.get("表单名称") or f"表单{idx + 1}").strip()
        raw_model_code = (row.get("绑定主表模型") or "").strip()
        form_code = (row.get("表单编码") or "").strip()
        model_code = model_name_index.get(raw_model_code.strip().lower(), raw_model_code.lower())
        if not model_code:
            errors.append(f"表单 '{form_name}'：未能找到绑定模型编码")
            continue

        model_fields = model_field_index.get(model_code)
        if model_fields is None:
            errors.append(f"表单 '{form_name}'：模型编码 '{model_code}' 未在数据模型中定义")
            continue

        form_main_rows = [r for r in main_field_rows if (r.get("表单名称") or "").strip() == form_name]
        components = _build_components(
            form_main_rows,
            form_name,
            model_code,
            model_fields,
            errors,
            section_type="main",
            form_model_map=form_model_map,
            all_models=models,
            model_field_index=model_field_index,
        )

        current_sub_defs = []
        for sub_idx, sub_row in enumerate(subtable_def_rows):
            if (sub_row.get("表单名称") or "").strip() != form_name:
                continue
            sub_model_code = (sub_row.get("绑定模型") or sub_row.get("子表模型编码") or "").strip().lower()
            if not sub_model_code:
                sub_display = (sub_row.get("子表区域名称") or sub_row.get("子表显示名称") or "(未命名)").strip()
                errors.append(
                    f"表单 '{form_name}' 子表 '{sub_display}'：绑定模型为空，该子表已跳过"
                )
                continue
            current_sub_defs.append({
                "model_code": sub_model_code,
                "model_name": sub_row.get("子表模型名称", "").strip(),
                "display_name": (sub_row.get("子表区域名称") or sub_row.get("子表显示名称") or f"子表{sub_idx + 1}").strip(),
            })

        for sub in current_sub_defs:
            sub_code = sub["model_code"]
            fields_map = model_field_index.get(sub_code, {})
            if not fields_map:
                errors.append(
                    f"表单 '{form_name}' 子表 '{sub['display_name']}'：绑定模型 '{sub_code}' "
                    f"在数据模型中查不到字段表，该子表字段已全部跳过"
                )
                continue
            current_sub_rows = [
                r for r in subfield_rows
                if (r.get("表单名称") or "").strip() == form_name
                and (r.get("子表区域名称") or "").strip() == sub["display_name"]
            ]
            for sub_row in current_sub_rows:
                field_code = (sub_row.get("字段编码") or sub_row.get("子表字段编码") or "").strip()
                model_field = fields_map.get(field_code)
                if not field_code:
                    field_label = (sub_row.get("字段名称") or sub_row.get("子表字段名称") or "(未命名)").strip()
                    errors.append(
                        f"表单 '{form_name}' 子表 '{sub['display_name']}' 字段 '{field_label}'："
                        f"字段编码为空，该字段已跳过"
                    )
                    continue
                if model_field is None:
                    errors.append(
                        f"表单 '{form_name}' 子表 '{sub['display_name']}' 字段编码 '{field_code}'："
                        f"在子表模型 '{sub_code}' 中找不到对应字段，该字段已跳过"
                    )
                    continue
                label = (sub_row.get("字段名称") or sub_row.get("子表字段名称") or model_field.get("name", field_code)).strip()
                comp_type_raw = (sub_row.get("组件类型") or "").strip()
                field_type = model_field.get("type", "单行输入")
                comp_type = _COMP_TYPE_MAP.get(comp_type_raw) or _COMP_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT")
                component = {
                    "code": field_code,
                    "label": label,
                    "componentType": comp_type,
                    "modelField": f"{sub_code}.{field_code}",
                    "modelCode": sub_code,
                    "tableModelCode": sub_code,
                    "subTableLabel": sub["display_name"],
                    "sectionType": "sub",
                    "hidden": bool_cell(sub_row.get("隐藏", sub_row.get("是否隐藏", "否"))),
                    "readonly": bool_cell(sub_row.get("只读", sub_row.get("是否只读", "否"))),
                    "required": bool_cell(sub_row.get("必填", sub_row.get("是否必填", "否"))),
                    "showInList": bool_cell(sub_row.get("列表展示", sub_row.get("是否列表展示", "否"))),
                    "searchable": bool_cell(sub_row.get("查询条件", sub_row.get("是否查询条件", "否"))),
                    "dictCode": (sub_row.get("字典编码") or "").strip(),
                    "description": (sub_row.get("说明") or "").strip(),
                }
                target_form_code = (sub_row.get("目标模型编码") or "").strip()
                target_model_code = form_model_map.get(target_form_code.lower(), target_form_code)
                target_field_code = (sub_row.get("目标字段编码") or "").strip()
                if target_model_code:
                    if comp_type_raw in ("关联表单", "FORM_ASSOCIATION"):
                        component["association_form_code"] = target_form_code or target_model_code
                        component["association_origin_field_code"] = (sub_row.get("本表关联字段编码") or field_code).strip()
                        component["association_target_field_code"] = target_field_code
                    else:
                        component["selector_form_code"] = target_form_code or target_model_code
                        component["selector_field_code"] = target_field_code
                    component["ref_model_code"] = target_model_code
                    component["ref_display_field_code"] = target_field_code
                    component["ref"] = {
                        "model": target_model_code,
                        "display_field": target_field_code,
                        "target_field": target_field_code,
                        "field": target_field_code,
                    }
                    component["formAssociationConfig"] = {
                        "originFieldCode": (sub_row.get("本表关联字段编码") or field_code).strip(),
                        "targetModelCode": target_model_code,
                        "targetFieldCode": target_field_code,
                    }
                _apply_model_field_defaults(component, model_field, field_code)
                components.append(component)

        seen = {c["code"] for c in components if c.get("sectionType") == "main"}
        list_shown = sum(1 for c in components if c.get("sectionType") == "main" and c.get("showInList"))
        for fc, mf in model_fields.items():
            if fc in seen:
                continue
            default_show = list_shown < _DEFAULT_LIST_SHOW_COUNT
            components.append(_build_default_component(fc, mf, model_code, default_show))
            if default_show:
                list_shown += 1

        all_model_codes = [model_code] + [d["model_code"] for d in current_sub_defs if d.get("model_code")]
        forms.append({
            "code": form_code or model_code,
            "name": form_name,
            "formName": form_name,
            "formCode": form_code or model_code,
            "modelCode": model_code,
            "allModelCodes": list(dict.fromkeys(all_model_codes)),
            "components": components,
        })

    return forms, errors


def _extract_form_meta(content: str):
    """从内容中提取表单元信息（支持 metadata 表 + #### 子节两种格式）

    返回 metadata dict
    """
    all_tables = parse_all_tables(content)
    model_code = form_name = None
    field_rows = None
    subtable_defs = []

    for table in all_tables:
        if not table:
            continue
        first_row = table[0]
        # metadata 表：含"绑定主表模型"或"模型编码"列
        if ("绑定主表模型" in first_row or "模型编码" in first_row) and model_code is None:
            model_code = (
                first_row.get("绑定主表模型")
                or first_row.get("模型编码", "")
            ).strip()
            form_name = (first_row.get("表单名称") or first_row.get("表单名") or "").strip() or None
        # 字段配置表：含"字段编码"列
        elif "字段编码" in first_row and field_rows is None:
            field_rows = table
        elif "子表模型编码" in first_row:
            for row in table:
                sub_code = row.get("子表模型编码", "").strip()
                if not sub_code:
                    continue
                subtable_defs.append({
                    "model_code": sub_code.lower(),
                    "model_name": row.get("子表模型名称", "").strip(),
                    "display_name": row.get("子表显示名称", "").strip() or row.get("子表模型名称", "").strip(),
                })

    if not model_code:
        for line in content.splitlines():
            stripped = line.strip()
            match = re.match(r"^(?:>?\s*)?主表模型[：:]\s*(.+?)\s*$", stripped)
            if match:
                model_code = match.group(1).strip()
                break

    return {
        "model_code": model_code,
        "form_name": form_name,
        "main_rows": field_rows,
        "subtable_defs": subtable_defs,
    }


def _extract_field_rows(content: str) -> List[dict]:
    """从内容中找到字段配置表（支持 #### 子节嵌套）"""
    # 先直接在 content 里找含 "字段编码" 的表
    all_tables = parse_all_tables(content)
    for table in all_tables:
        if table and "字段编码" in table[0]:
            return table
    return []


def _build_subtable_components(
    content: str,
    subtable_defs: List[dict],
    model_field_index: dict,
    errors: List[str],
) -> List[dict]:
    if not subtable_defs:
        return []

    tables = parse_all_tables(content)
    sub_rows_by_name: dict = {}
    current_sub_name: Optional[str] = None
    for line in content.splitlines():
        m = re.match(r"^\*\*子表[：:]\s*(.+?)\*\*\s*$", line.strip())
        if m:
            current_sub_name = m.group(1).strip()
            continue
        if current_sub_name:
            table_text = "\n".join([line])
            # nothing, marker only switches state; actual tables are parsed globally below
            pass

    # 用顺序把 "**子表：xxx**" 后面的子表字段表匹配出来
    marker_names = []
    for line in content.splitlines():
        stripped = line.strip()
        heading_match = re.match(r"^#{4,6}\s+.*?子表[：:]\s*(.+?)\s*$", stripped)
        bold_match = re.match(r"^\*\*子表[：:]\s*(.+?)\*\*\s*$", stripped)
        matched_name = heading_match.group(1).strip() if heading_match else (bold_match.group(1).strip() if bold_match else "")
        if matched_name:
            marker_names.append(_normalize_subtable_name(matched_name))
    sub_tables = [table for table in tables if table and "子表字段编码" in table[0]]
    for idx, table in enumerate(sub_tables):
        if idx < len(marker_names):
            sub_rows_by_name[marker_names[idx]] = table

    components: List[dict] = []
    for sub in subtable_defs:
        sub_code = sub.get("model_code", "")
        sub_name = sub.get("model_name") or sub.get("display_name") or sub_code
        rows = (
            sub_rows_by_name.get(_normalize_subtable_name(sub.get("display_name", "")))
            or sub_rows_by_name.get(_normalize_subtable_name(sub_name))
            or []
        )
        fields_map = model_field_index.get(sub_code, {})
        for row in rows:
            field_code = row.get("子表字段编码", "").strip()
            if not field_code:
                field_label = (row.get("子表字段名称") or "(未命名)").strip()
                errors.append(
                    f"子表 '{sub_name}' 字段 '{field_label}'：子表字段编码为空，该字段已跳过"
                )
                continue
            model_field = fields_map.get(field_code)
            if model_field is None:
                errors.append(
                    f"子表 '{sub_name}' 字段编码 '{field_code}'：在子表模型 '{sub_code}' 中找不到对应字段，该字段已跳过"
                )
                continue
            label = row.get("子表字段名称", "").strip() or model_field.get("name", field_code)
            comp_type_raw = row.get("组件类型", "").strip()
            field_type = model_field.get("type", "单行输入")
            comp_type = _COMP_TYPE_MAP.get(comp_type_raw) or _COMP_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT")
            components.append({
                "code": field_code,
                "label": label,
                "componentType": comp_type,
                "modelField": f"{sub_code}.{field_code}",
                "modelCode": sub_code,
                "tableModelCode": sub_code,
                "subTableLabel": sub.get("display_name") or sub_name,
                "sectionType": "sub",
                "hidden": False,
                "readonly": False,
                "required": bool_cell(row.get("是否必填", "否")),
                "showInList": False,
                "searchable": False,
            })
            _apply_model_field_defaults(components[-1], model_field, field_code)

    return components


def _build_components(rows: List[dict], form_name: str, model_code: str,
                      model_fields: dict, errors: List[str], section_type: str = "main",
                      form_model_map: dict | None = None,
                      all_models: List[dict] | None = None,
                      model_field_index: dict | None = None) -> List[dict]:
    components: List[dict] = []
    seen: set = set()
    form_model_map = form_model_map or {}
    all_models = all_models or []
    model_field_index = model_field_index or {}

    for row in rows:
        field_code = row.get("字段编码", "").strip()
        field_label = row.get("字段名称", "").strip()
        description = row.get("说明", "").strip()
        hidden = bool_cell(row.get("隐藏", row.get("是否隐藏", "否")))
        readonly = bool_cell(row.get("只读", row.get("是否只读", "否")))
        required = bool_cell(row.get("必填", row.get("是否必填", "否")))
        show_in_list = bool_cell(row.get("列表展示", row.get("是否列表展示", "否")))
        searchable = bool_cell(row.get("查询条件", row.get("是否查询条件", "否")))
        # 兼容"组件类型"列（直接写了 aPaaS 类型）
        comp_type_raw = row.get("组件类型", "").strip()

        if not field_code:
            if field_label:
                errors.append(
                    f"表单 '{form_name}' 字段 '{field_label}'：字段编码为空，该字段已跳过"
                )
            continue
        if field_code in seen:
            continue

        model_field = model_fields.get(field_code)
        ref_model_code = (row.get("目标模型编码") or "").strip()
        ref_display_field_code = (row.get("目标字段编码") or "").strip()
        resolved_ref_model_code = form_model_map.get(ref_model_code.lower(), ref_model_code) if ref_model_code else ""
        is_reference_component = _is_reference_component(comp_type_raw, model_field.get("type", "") if model_field else "")
        if not resolved_ref_model_code and is_reference_component:
            resolved_ref_model_code = _infer_target_model_code(
                field_code=field_code,
                field_label=field_label,
                description=description,
                current_model_code=model_code,
                models=all_models,
            )
        origin_field_code = _infer_association_origin_field_code(
            explicit_origin_field_code=(row.get("本表关联字段编码") or "").strip(),
            current_model_fields=model_fields,
            target_model_code=resolved_ref_model_code,
            model_field_index=model_field_index,
        ) if comp_type_raw in ("关联表单", "FORM_ASSOCIATION") else ""
        if resolved_ref_model_code and not ref_display_field_code and comp_type_raw in ("关联表单", "FORM_ASSOCIATION"):
            ref_display_field_code = _infer_association_target_field_code(
                explicit_target_field_code=ref_display_field_code,
                origin_field_code=origin_field_code,
                target_model_code=resolved_ref_model_code,
                current_model_fields=model_fields,
                model_field_index=model_field_index,
            )
        if resolved_ref_model_code and not ref_display_field_code and comp_type_raw not in ("关联表单", "FORM_ASSOCIATION"):
            ref_display_field_code = _infer_target_field_code(
                target_model_code=resolved_ref_model_code,
                field_label=field_label or (model_field.get("name", "") if model_field else ""),
                model_field_index=model_field_index,
            )
        if model_field is None:
            # 关联表单允许组件编码不在数据模型中，仍保留组件定义
            if resolved_ref_model_code or comp_type_raw in ("关联表单", "FORM_ASSOCIATION"):
                label = field_label or field_code
                seen.add(field_code)
                component = {
                    "code": field_code,
                    "label": label,
                    "componentType": _COMP_TYPE_MAP.get("关联表单", "FORM_ASSOCIATION"),
                    "modelField": f"{model_code}.{origin_field_code or field_code}",
                    "modelCode": model_code,
                    "sectionType": section_type,
                    "hidden": hidden,
                    "readonly": readonly,
                    "required": required,
                    "showInList": show_in_list,
                    "searchable": searchable,
                    "dictCode": row.get("字典编码", "").strip(),
                    "description": row.get("说明", "").strip(),
                }
                if resolved_ref_model_code:
                    if comp_type_raw in ("关联表单", "FORM_ASSOCIATION"):
                        component["association_form_code"] = ref_model_code or resolved_ref_model_code
                        component["association_origin_field_code"] = origin_field_code or field_code
                        component["association_target_field_code"] = ref_display_field_code
                        component["formAssociationConfig"] = {
                            "originFieldCode": origin_field_code or field_code,
                            "targetModelCode": resolved_ref_model_code,
                            "targetFieldCode": ref_display_field_code,
                        }
                    else:
                        component["selector_form_code"] = ref_model_code or resolved_ref_model_code
                        component["selector_field_code"] = ref_display_field_code
                    component["ref_model_code"] = resolved_ref_model_code
                    component["ref_display_field_code"] = ref_display_field_code
                    component["ref"] = {
                        "model": resolved_ref_model_code,
                        "display_field": ref_display_field_code,
                        "target_field": ref_display_field_code,
                        "field": ref_display_field_code,
                    }
                components.append(component)
            continue

        field_type = model_field.get("type", "单行输入")
        if comp_type_raw:
            from app.field_types import get_comp_type_map
            comp_map = get_comp_type_map()
            # 先按 aPaaS 类型名查，再按字段类型查
            comp_type = comp_map.get(comp_type_raw) or comp_map.get(field_type, "FORM_TEXT_INPUT")
        else:
            comp_type = _COMP_TYPE_MAP.get(field_type, "FORM_TEXT_INPUT")

        label = field_label or model_field.get("name", field_code)
        seen.add(field_code)
        components.append({
            "code": field_code,
            "label": label,
            "componentType": comp_type,
            "modelField": f"{model_code}.{field_code}",
            "modelCode": model_code,
            "sectionType": section_type,
            "hidden": hidden,
            "readonly": readonly,
            "required": required,
            "showInList": show_in_list,
            "searchable": searchable,
            "dictCode": row.get("字典编码", "").strip(),
            "description": description,
        })

        if resolved_ref_model_code:
            if comp_type_raw in ("关联表单", "FORM_ASSOCIATION"):
                components[-1]["association_form_code"] = ref_model_code or resolved_ref_model_code
                components[-1]["association_origin_field_code"] = origin_field_code or field_code
                components[-1]["association_target_field_code"] = ref_display_field_code
                components[-1]["formAssociationConfig"] = {
                    "originFieldCode": origin_field_code or field_code,
                    "targetModelCode": resolved_ref_model_code,
                    "targetFieldCode": ref_display_field_code,
                }
            else:
                components[-1]["selector_form_code"] = ref_model_code or resolved_ref_model_code
                components[-1]["selector_field_code"] = ref_display_field_code
            components[-1]["ref_model_code"] = resolved_ref_model_code
            components[-1]["ref_display_field_code"] = ref_display_field_code
            components[-1]["ref"] = {
                "model": resolved_ref_model_code,
                "display_field": ref_display_field_code,
                "target_field": ref_display_field_code,
                "field": ref_display_field_code,
            }
        _apply_model_field_defaults(components[-1], model_field, field_code)

    return components


def derive_default_forms(models: List[dict]) -> List[dict]:
    from app.field_types import get_comp_type_map
    comp_map = get_comp_type_map()
    forms: List[dict] = []

    for model in models:
        if model.get("table_type") == "子表":
            continue
        model_code = model["code"]
        model_name = model["name"]
        components: List[dict] = []
        list_count = 0

        for field in model.get("fields", []):
            if field.get("type") == "子表":
                sub_code = field.get("sub_code", "")
                sub_cols = [
                    {
                        "label": sf.get("name", ""),
                        "componentType": comp_map.get(sf.get("type", "单行输入"), "FORM_TEXT_INPUT"),
                        "modelField": f"{sub_code}.{sf.get('code', '')}",
                        "required": False,
                    }
                    for sf in field.get("sub_fields", [])
                ]
                components.append({
                    "code": field["code"],
                    "label": field["name"],
                    "componentType": "FORM_WIDGET_SON_TABLE",
                    "modelCode": model_code,
                    "sectionType": "sub",
                    "tableModelCode": sub_code,
                    "tableColumn": sub_cols,
                    "hidden": False, "readonly": False, "required": False,
                    "showInList": False, "searchable": False,
                })
                continue

            show_in_list = list_count < _DEFAULT_LIST_SHOW_COUNT
            components.append({
                "code": field["code"],
                "label": field["name"],
                "componentType": comp_map.get(field.get("type", "单行输入"), "FORM_TEXT_INPUT"),
                "modelField": f"{model_code}.{field['code']}",
                "modelCode": model_code,
                "sectionType": "main",
                "hidden": False, "readonly": False, "required": False,
                "showInList": show_in_list, "searchable": False,
            })
            _apply_model_field_defaults(components[-1], field, field.get("code", ""))
            if show_in_list:
                list_count += 1

        forms.append({
            "code": model_code, "name": model_name,
            "formName": model_name, "formCode": model_code,
            "modelCode": model_code, "_auto_generated": True,
            "components": components,
        })

    return forms
