"""角色列表解析器"""
from __future__ import annotations

import re
from typing import List, Tuple

from app.doc_table_parser import parse_table


def parse(section_text: str) -> Tuple[List[dict], List[str]]:
    """解析"二、角色列表"章节内容

    Returns:
        (roles, errors)
        roles: [{"code": "admin", "name": "管理员"}, ...]
        errors: 解析过程中的问题描述
    """
    errors: List[str] = []
    rows = parse_table(section_text)

    if not rows:
        errors.append("角色列表：未找到有效表格")
        return [], errors

    roles: List[dict] = []
    seen_codes: set = set()

    for row in rows:
        code = row.get("角色编码", "").strip()
        name = row.get("角色名称", "").strip()

        if not name:
            errors.append(f"角色列表：跳过缺少名称的行 {row}")
            continue
        if not code:
            errors.append(f"角色 '{name}'：缺少角色编码")
            continue
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            errors.append(f"角色 '{name}'：编码 '{code}' 不合规（需英文字母开头+下划线）")
            continue
        if code in seen_codes:
            errors.append(f"角色编码 '{code}' 重复，已跳过")
            continue

        seen_codes.add(code)
        roles.append({"code": code.lower(), "name": name})

    if not roles:
        errors.append("角色列表：解析后没有有效角色")

    return roles, errors
