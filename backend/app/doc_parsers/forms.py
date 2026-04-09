"""表单配置解析器"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table, parse_all_tables, bool_cell
from app.field_types import get_comp_type_map


_COMP_TYPE_MAP = get_comp_type_map()
_DEFAULT_LIST_SHOW_COUNT = 5


def _normalize_subtable_name(name: str) -> str:
    text = (name or "").strip()
    text = re.sub(r"[（(][^）)]+[）)]", "", text).strip()
    return text


def parse(section_text: str, models: List[dict]) -> Tuple[List[dict], List[str]]:
    errors: List[str] = []
    forms: List[dict] = []

    model_field_index: dict = {}
    model_name_index: dict = {}
    for m in models:
        model_field_index[m["code"]] = {
            f["code"]: f for f in m.get("fields", [])
            if f.get("type") != "子表"
        }
        model_name_index[m["code"]] = m.get("name", m["code"])

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

        model_code = model_code.lower()
        model_fields = model_field_index.get(model_code)
        if model_fields is None:
            errors.append(f"表单 '{form_name}'：模型编码 '{model_code}' 未在数据模型中定义")
            continue

        field_rows = meta["main_rows"] or _extract_field_rows(content)
        components = _build_components(field_rows, form_name, model_code, model_fields, errors, section_type="main")

        subtable_defs = meta["subtable_defs"]
        subtable_components = _build_subtable_components(content, subtable_defs, model_field_index, errors)
        components.extend(subtable_components)

        # 未出现的模型字段用默认值补充
        seen = {c["code"] for c in components}
        list_shown = sum(1 for c in components if c["showInList"])
        for fc, mf in model_fields.items():
            if fc in seen:
                continue
            ft = mf.get("type", "单行输入")
            default_show = list_shown < _DEFAULT_LIST_SHOW_COUNT
            components.append({
                "code": fc,
                "label": mf.get("name", fc),
                "componentType": _COMP_TYPE_MAP.get(ft, "FORM_TEXT_INPUT"),
                "modelField": f"{model_code}.{fc}",
                "modelCode": model_code,
                "sectionType": "main",
                "hidden": False, "readonly": False, "required": False,
                "showInList": default_show, "searchable": False,
            })
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
        # metadata 表：含"绑定主表模型编码"或"模型编码"列
        if ("绑定主表模型编码" in first_row or "模型编码" in first_row) and model_code is None:
            model_code = (first_row.get("绑定主表模型编码") or first_row.get("模型编码", "")).strip()
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
    marker_names = [
        _normalize_subtable_name(re.match(r"^\*\*子表[：:]\s*(.+?)\*\*\s*$", line.strip()).group(1).strip())
        for line in content.splitlines()
        if re.match(r"^\*\*子表[：:]\s*(.+?)\*\*\s*$", line.strip())
    ]
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
                continue
            model_field = fields_map.get(field_code)
            if model_field is None:
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

    return components


def _build_components(rows: List[dict], form_name: str, model_code: str,
                      model_fields: dict, errors: List[str], section_type: str = "main") -> List[dict]:
    components: List[dict] = []
    seen: set = set()

    for row in rows:
        field_code = row.get("字段编码", "").strip()
        field_label = row.get("字段名称", "").strip()
        hidden = bool_cell(row.get("是否隐藏", "否"))
        readonly = bool_cell(row.get("是否只读", "否"))
        required = bool_cell(row.get("是否必填", "否"))
        show_in_list = bool_cell(row.get("是否列表展示", "否"))
        searchable = bool_cell(row.get("是否查询条件", "否"))
        # 兼容"组件类型"列（直接写了 aPaaS 类型）
        comp_type_raw = row.get("组件类型", "").strip()

        if not field_code or field_code in seen:
            continue

        model_field = model_fields.get(field_code)
        if model_field is None:
            # 宽松：不报错，跳过不在模型里的字段
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
        })

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
            if show_in_list:
                list_count += 1

        forms.append({
            "code": model_code, "name": model_name,
            "formName": model_name, "formCode": model_code,
            "modelCode": model_code, "_auto_generated": True,
            "components": components,
        })

    return forms
