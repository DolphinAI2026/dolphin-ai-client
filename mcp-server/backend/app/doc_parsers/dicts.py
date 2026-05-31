"""数据字典解析器"""
from __future__ import annotations

import re
from typing import List, Tuple

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table, parse_all_tables


def parse(section_text: str) -> Tuple[List[dict], List[str]]:
    """解析"三、数据字典"章节内容

    支持两种格式：
    格式A（标准）: ### 字典名（dict_code）
                  | 选项编码 | 选项名称 |
    格式B（元表）: ### 3.1 字典名
                  | 字典编码 | 字典名称 |
                  | project_type | 项目类型 |
                  | 选项编码 | 选项名称 |
                  | internal | 内部项目 |
    """
    errors: List[str] = []
    dicts: List[dict] = []
    seen_codes: set = set()

    subsections = split_subsections(section_text)

    if not subsections:
        errors.append("数据字典：未找到 ### 子章节，章节可能不标准")
        return [], errors

    for name, code, _tag, content in subsections:
        # 格式B：code 不在标题里，从 metadata 表提取
        if not code:
            code, dict_name, option_rows = _extract_from_meta_table(content)
            if not code:
                errors.append(f"字典 '{name}'：未能找到字典编码（标题或表格均无）")
                continue
            name = dict_name or name
        else:
            # 格式A：选项直接在 content 里
            # 若第一张表是元数据表（字典编码/字典名称），则找含"选项编码"的表
            all_tables = parse_all_tables(content)
            option_rows = next(
                (t for t in all_tables if t and "选项编码" in t[0]),
                all_tables[0] if all_tables else []
            )
            dict_name = name

        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            errors.append(f"字典 '{name}'：编码 '{code}' 不合规")
            continue
        if code in seen_codes:
            errors.append(f"字典编码 '{code}' 重复，已跳过")
            continue

        if not option_rows:
            errors.append(f"字典 '{name}'（{code}）：未找到选项表格")
            continue

        options: List[dict] = []
        seen_opt_codes: set = set()
        for row in option_rows:
            opt_code = row.get("选项编码", "").strip()
            opt_name = row.get("选项名称", "").strip()
            if not opt_name:
                continue
            if not opt_code:
                errors.append(f"字典 '{name}' 选项 '{opt_name}'：缺少选项编码")
                continue
            if not re.match(r'^[a-zA-Z0-9_]+$', opt_code):
                errors.append(f"字典 '{name}' 选项 '{opt_name}'：编码 '{opt_code}' 不合规")
                continue
            if opt_code in seen_opt_codes:
                continue
            seen_opt_codes.add(opt_code)
            options.append({"code": opt_code.lower(), "name": opt_name})

        if len(options) < 2:
            errors.append(f"字典 '{name}'（{code}）：选项少于 2 个（当前 {len(options)} 个）")

        seen_codes.add(code)
        dicts.append({"code": code.lower(), "name": name, "options": options})

    return dicts, errors


def _extract_from_meta_table(content: str):
    """从内容中提取字典编码/名称 + 选项行

    返回 (code, name, option_rows)
    """
    all_tables = parse_all_tables(content)
    if not all_tables:
        return None, None, []

    code = None
    name = None
    option_rows = []

    for table in all_tables:
        if not table:
            continue
        first_row = table[0]
        # 识别 metadata 表（含"字典编码"列）
        if "字典编码" in first_row and code is None:
            code = first_row.get("字典编码", "").strip()
            name = first_row.get("字典名称", "").strip() or None
        # 识别选项表（含"选项编码"列）
        elif "选项编码" in first_row:
            option_rows = table

    return code, name, option_rows
