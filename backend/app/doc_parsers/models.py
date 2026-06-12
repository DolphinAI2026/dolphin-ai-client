"""数据模型解析器"""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Tuple

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table, parse_all_tables
from app.config_validator import _normalize_field_type, RESERVED_FIELD_CODES
from app.field_types import get_db_type_map, get_dict_field_types, get_ref_field_types
from app.lowcode_standards import normalize_component_type, normalize_database_field_type, safe_field_code, _snake


# 单一真相源都在 app.field_types；下面只是模块级缓存，保持名字不变、下游 0 改动。
# 新增/修改数据库映射、字典类、关联类都去 field_types.py 改。
_DB_TYPE_MAP = get_db_type_map()
_DICT_TYPES = get_dict_field_types()
_REF_TYPES = get_ref_field_types()
_SUB_TABLE_TYPE = "子表"

_MODEL_CODE_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')


def _sanitize_model_code(code: str) -> str:
    """不合规(含中文等)的模型编码 → 合法 ascii snake_case；纯非 ascii 退化成基于原编码
    的确定性 hash。

    历史 bug：旧逻辑正则一拦直接 continue，把整张模型连字段一起静默丢掉(文档还报高分)。
    改成规范化保留。**只依赖 code 本身、确定性**：聚合格式里字段归组(4.2)与模型行(4.1)
    两处要算出同一个 key，否则字段会被孤立丢掉。
    """
    snaked = _snake(code)
    if snaked and snaked[0].isalpha():
        return snaked
    return "c_" + hashlib.md5(str(code).encode("utf-8")).hexdigest()[:7]


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

        if not _MODEL_CODE_RE.match(code):
            fixed = _sanitize_model_code(code)
            errors.append(f"模型 '{name}'：编码 '{code}' 含非法字符，已规范化为 '{fixed}'")
            code = fixed
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
    """兼容两种"总表"结构：

    A. 聚合字段表：一张模型定义表 + 一张字段汇总表（字段表含"模型编码"列）
    B. 分块字段表：一张模型定义表 + 若干 ``#### `` 子节，每个子节用
       ``> 模型编码：`xxx` `` 声明归属，内部是单纯的
       ``字段编码 | 字段名称 | 数据库字段类型 | 长度/精度`` 表格
       （字段表本身不含"模型编码"列，归属靠子节元数据）

    两种格式都能让 28 个模型定义表 + 各自字段被正确关联。
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

    if field_rows:
        # 格式 A：聚合字段表
        for row in field_rows:
            model_code = (row.get("模型编码") or "").strip().lower()
            if not model_code:
                field_name = (row.get("字段名称") or row.get("字段编码") or "(未命名)").strip()
                errors.append(
                    f"数据模型：字段 '{field_name}' 所属模型编码为空，该字段已跳过（无法归属到任何模型）"
                )
                continue
            # 跟模型行用同一个确定性规范化，保证字段挂到规范化后的模型 code 上、不被孤立
            if not _MODEL_CODE_RE.match(model_code):
                model_code = _sanitize_model_code(model_code)
            field_rows_by_model.setdefault(model_code, []).append(row)
    else:
        # 格式 B：按 #### 子节分块，字段归属来自子节内的 "模型编码：xxx" 元数据
        block_pattern = re.compile(r"^####\s+.+$", re.MULTILINE)
        matches = list(block_pattern.finditer(section_text))
        for idx, m in enumerate(matches):
            block_start = m.start()
            block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(section_text)
            block = section_text[block_start:block_end]

            # 从引用块或普通文本里提取 "模型编码：xxx"（兼容反引号包裹）
            code_match = re.search(
                r"模型编码[：:]\s*`?([a-zA-Z][a-zA-Z0-9_]*)`?",
                block,
            )
            block_title = (m.group(0) or "").lstrip("# ").strip() or "(未命名)"
            if not code_match:
                errors.append(
                    f"数据模型：字段块 '{block_title}' 缺少 '模型编码：xxx' 声明，该块字段已整块跳过"
                )
                continue
            block_code = code_match.group(1).strip().lower()

            block_field_rows = parse_table(block)
            if not block_field_rows:
                errors.append(
                    f"数据模型：字段块 '{block_title}'（模型编码 '{block_code}'）未解析出字段表格，该块已跳过"
                )
                continue
            field_rows_by_model.setdefault(block_code, []).extend(block_field_rows)

    seen_codes: set[str] = set()
    models: List[dict] = []
    for row in model_rows:
        code = (row.get("模型编码") or "").strip().lower()
        name = (row.get("模型名称") or code).strip()
        if not code:
            errors.append(
                f"数据模型：模型 '{name or '(未命名)'}' 的模型编码为空，该模型已跳过"
            )
            continue
        if not _MODEL_CODE_RE.match(code):
            fixed = _sanitize_model_code(code)
            errors.append(f"模型 '{name}'：编码 '{code}' 含非法字符，已规范化为 '{fixed}'")
            code = fixed
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
        safe_code = safe_field_code(code, model_code=model_code, field_name=name, used_codes=set())
        if code.lower() != safe_code:
            errors.append(f"模型 '{model_name}' 字段 '{name}'：编码 '{code}' 与数据库/平台保留字冲突，已改为 '{safe_code}'")
            code = safe_code
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
        field_type = normalize_component_type(
            field_type,
            field_name=name,
            has_dict=bool(dict_code),
            has_ref=bool(ref_model),
        )
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
            "databaseFieldType": normalize_database_field_type(
                raw_db_type or raw_type,
                component_type=field_type,
                field_name=name,
            ),
            "database_field_type": normalize_database_field_type(
                raw_db_type or raw_type,
                component_type=field_type,
                field_name=name,
            ),
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
