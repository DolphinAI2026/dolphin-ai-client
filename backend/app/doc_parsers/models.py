"""数据模型解析器"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table, parse_all_tables
from app.config_validator import _normalize_field_type, RESERVED_FIELD_CODES


# 数据库字段类型 → aPaaS 字段类型（兜底映射）
_DB_TYPE_MAP = {
    "varchar": "单行输入",
    "char": "单行输入",
    "text": "多行输入",
    "longtext": "多行输入",
    "clob": "多行输入",
    "int": "数字",
    "integer": "数字",
    "bigint": "数字",
    "smallint": "数字",
    "float": "数字",
    "double": "数字",
    "decimal": "数字",
    "numeric": "数字",
    "date": "日期时间",
    "datetime": "日期时间",
    "timestamp": "日期时间",
    "boolean": "开关",
    "bool": "开关",
    "tinyint": "开关",
    "blob": "附件上传",
}

_DICT_TYPES = {"下拉单选", "下拉多选", "单选框", "复选框"}
_REF_TYPES = {"数据单选", "数据选择", "关联表单"}
_SUB_TABLE_TYPE = "子表"


def parse(section_text: str) -> Tuple[List[dict], List[str]]:
    errors: List[str] = []
    aggregate_models, aggregate_errors = _parse_aggregate_tables(section_text)
    if aggregate_models:
        return aggregate_models, aggregate_errors

    models: List[dict] = []
    seen_codes: set = set()

    subsections = split_subsections(section_text)

    if not subsections:
        errors.append("数据模型：未找到 ### 子章节")
        return [], errors

    for name, code, tag, content in subsections:
        meta_code, meta_name, meta_tag, parent_code, field_rows = _extract_from_meta_table(content)
        if meta_code:
            code = meta_code
        if meta_name:
            name = meta_name
        if meta_tag:
            tag = meta_tag

        if not code:
            errors.append(f"模型 '{name}'：未能找到模型编码（标题或表格均无）")
            continue

        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            errors.append(f"模型 '{name}'：编码 '{code}' 不合规")
            continue
        if code in seen_codes:
            errors.append(f"模型编码 '{code}' 重复，已跳过")
            continue

        is_sub = (tag == "子表") if tag else False
        fields, field_errors = _parse_fields(content, code, name, preloaded_rows=field_rows)
        errors.extend(field_errors)

        seen_codes.add(code)
        model = {"code": code.lower(), "name": name, "fields": fields}
        if is_sub:
            model["table_type"] = "子表"
            if parent_code:
                model["parent_model_code"] = parent_code.lower()
        else:
            model["table_type"] = "主表"
        models.append(model)

    _inline_sub_tables(models, errors)
    return models, errors


def _parse_aggregate_tables(section_text: str) -> Tuple[List[dict], List[str]]:
    """兼容标准模版的总表结构：
    - 模型定义：模型编码 / 模型名称
    - 模型字段：模型编码 / 字段编码 / 字段名称 / 数据库字段类型 / 长度
    """
    errors: List[str] = []
    all_tables = parse_all_tables(section_text)
    if not all_tables:
        return [], errors

    model_rows = None
    field_rows = None
    for table in all_tables:
        if not table:
            continue
        first_row = table[0]
        if (
            model_rows is None
            and "模型编码" in first_row
            and "模型名称" in first_row
            and "字段编码" not in first_row
        ):
            model_rows = table
        elif (
            field_rows is None
            and "模型编码" in first_row
            and "字段编码" in first_row
            and "字段名称" in first_row
        ):
            field_rows = table

    if not model_rows:
        return [], errors

    field_rows_by_model: dict[str, list[dict]] = {}
    for row in field_rows or []:
        model_code = (row.get("模型编码") or "").strip().lower()
        if not model_code:
            continue
        field_rows_by_model.setdefault(model_code, []).append(row)

    seen_codes: set[str] = set()
    models: List[dict] = []
    for row in model_rows:
        code = (row.get("模型编码") or "").strip().lower()
        name = (row.get("模型名称") or code).strip()
        if not code:
            continue
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            errors.append(f"模型 '{name}'：编码 '{code}' 不合规")
            continue
        if code in seen_codes:
            errors.append(f"模型编码 '{code}' 重复，已跳过")
            continue
        seen_codes.add(code)
        fields, field_errors = _parse_fields(
            "",
            code,
            name,
            preloaded_rows=field_rows_by_model.get(code, []),
        )
        errors.extend(field_errors)
        models.append({
            "code": code,
            "name": name,
            "fields": fields,
            "table_type": "主表",
        })

    return models, errors


def _extract_from_meta_table(content: str):
    """从内容中提取模型编码/名称/类型 + 字段行

    返回 (code, name, tag, field_rows_or_None)
    """
    all_tables = parse_all_tables(content)
    code = name = tag = parent_code = None
    field_rows = None

    for table in all_tables:
        if not table:
            continue
        first_row = table[0]
        if "模型编码" in first_row and code is None:
            code = first_row.get("模型编码", "").strip()
            name = first_row.get("模型名称", "").strip() or None
            raw_tag = (first_row.get("类型") or first_row.get("字段类型") or "").strip()
            tag = raw_tag if raw_tag in ("主表", "子表") else None
            parent_code = first_row.get("所属主表模型编码", "").strip() or None
        elif "字段编码" in first_row and field_rows is None:
            field_rows = table

    return code, name, tag, parent_code, field_rows


def _resolve_field_type(raw: str) -> Tuple[str, Optional[str]]:
    """将字段类型（含DB类型）转换为 aPaaS 类型"""
    if not raw:
        return "单行输入", None
    # 先尝试 aPaaS 标准类型
    normalized, warn = _normalize_field_type(raw)
    if not warn:
        return normalized, None
    # 再尝试数据库类型映射
    key = raw.strip().lower().split("(")[0].strip()
    mapped = _DB_TYPE_MAP.get(key)
    if mapped:
        return mapped, None
    return "单行输入", f"未知字段类型 '{raw}'，已默认为单行输入"


def _parse_fields(content: str, model_code: str, model_name: str,
                  preloaded_rows=None) -> Tuple[List[dict], List[str]]:
    errors: List[str] = []
    rows = preloaded_rows if preloaded_rows is not None else parse_table(content)

    if not rows:
        errors.append(f"模型 '{model_name}'（{model_code}）：未找到字段表格")
        return [], errors

    fields: List[dict] = []
    seen_codes: set = set()

    for row in rows:
        code = row.get("字段编码", "").strip()
        name = row.get("字段名称", "").strip()
        # 兼容 "字段类型" 和 "数据库字段类型" 两种列名
        raw_type = (row.get("字段类型") or row.get("数据库字段类型") or "单行输入").strip()
        raw_db_type = (row.get("数据库字段类型") or row.get("字段类型") or "").strip()
        raw_length = (row.get("长度/精度") or row.get("长度") or "").strip()
        dict_code = row.get("字典编码", "").strip() or None
        ref_model = row.get("关联模型编码", "").strip() or None
        ref_field = row.get("关联显示字段编码", "").strip() or None
        required = str(row.get("必填", "")).strip() in {"是", "yes", "true", "1", "Y", "y"}
        comment = row.get("说明", "").strip()

        if not name:
            continue
        if not code:
            errors.append(f"模型 '{model_name}' 字段 '{name}'：缺少字段编码")
            continue
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            errors.append(f"模型 '{model_name}' 字段 '{name}'：编码 '{code}' 不合规")
            continue
        if code in seen_codes:
            errors.append(f"模型 '{model_name}' 字段编码 '{code}' 重复，已跳过")
            continue
        if code in RESERVED_FIELD_CODES:
            errors.append(f"模型 '{model_name}' 字段 '{name}'：编码 '{code}' 是平台系统字段，已自动跳过")
            continue

        field_type, type_warn = _resolve_field_type(raw_type)
        if type_warn:
            errors.append(f"模型 '{model_name}' 字段 '{name}'：{type_warn}")

        # 有字典编码时推断为下拉单选
        if dict_code and field_type == "单行输入":
            field_type = "下拉单选"
        # 有关联模型时推断为数据单选
        if ref_model and field_type == "单行输入":
            field_type = "数据单选"

        seen_codes.add(code)
        field: dict = {
            "code": code.lower(),
            "name": name,
            "type": field_type,
            "databaseFieldType": raw_db_type or raw_type,
            "database_field_type": raw_db_type or raw_type,
        }

        if raw_length:
            field["maxLength"] = raw_length
            field["max_length"] = raw_length
            field["length"] = raw_length
        if required:
            field["required"] = True
        if comment:
            field["comment"] = comment

        if field_type in _DICT_TYPES:
            if dict_code:
                field["dict"] = dict_code.lower()
            else:
                errors.append(f"模型 '{model_name}' 字段 '{name}'：类型 '{field_type}' 需要字典编码")
        elif dict_code:
            pass  # 宽松：忽略多余的字典编码，不报错

        if field_type in _REF_TYPES:
            if ref_model:
                field["ref"] = {"model": ref_model.lower(), "field": ref_field or ""}
            else:
                errors.append(f"模型 '{model_name}' 字段 '{name}'：类型 '{field_type}' 需要关联模型编码")
        elif field_type == _SUB_TABLE_TYPE:
            if ref_model:
                field["sub_code"] = ref_model.lower()
            else:
                errors.append(f"模型 '{model_name}' 字段 '{name}'：子表类型需要填写子表模型编码")

        fields.append(field)

    return fields, errors


def _inline_sub_tables(models: List[dict], errors: List[str]) -> None:
    model_by_code = {m["code"]: m for m in models}
    for model in models:
        for field in model.get("fields", []):
            if field.get("type") == _SUB_TABLE_TYPE and field.get("sub_code"):
                sub_code = field["sub_code"]
                sub_model = model_by_code.get(sub_code)
                if sub_model:
                    field["sub_fields"] = sub_model.get("fields", [])
                else:
                    errors.append(
                        f"模型 '{model['name']}' 字段 '{field['name']}'：子表 '{sub_code}' 未在数据模型章节定义"
                    )
