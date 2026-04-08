"""权限配置解析器"""
from __future__ import annotations

from typing import List, Tuple

from app.doc_table_parser import parse_table, bool_cell


# 权限列 → op 名称
_PERM_COLUMNS = {
    "可暂存": "draft",
    "可新增": "add",
    "可导入": "import",
    "可查看": "view",
    "可编辑": "edit",
    "可删除": "delete",
    "可导出": "export",
}

# 所有可操作的 op（用于判断是否 all）
_ALL_OPS = set(_PERM_COLUMNS.values()) - {"draft", "import", "export"}

# 数据范围文字 → 内部编码
_DATA_SCOPE_MAP = {
    "全公司": "ALL",
    "全部": "ALL",
    "all": "ALL",
    "本部门": "CURRENT_USER_DEPT",
    "本部门及下属部门": "CURRENT_USER_DEPT_LOW_LEVEL",
    "本部门及下级部门": "CURRENT_USER_DEPT_LOW_LEVEL",
    "仅本人": "SELF",
    "本人": "SELF",
    "自己": "SELF",
    # 自定义数据范围（无法映射到标准枚举，统一转为 ALL，保留原文到备注）
    "本人负责项目": "ALL",
    "本人参与项目": "ALL",
    "本人负责任务": "SELF",
}


def parse(
    section_text: str,
    role_codes: set,
) -> Tuple[List[dict], List[str]]:
    """解析"六、权限配置"章节内容

    Args:
        section_text: 章节原文
        role_codes: 已知角色编码集合（用于校验）

    Returns:
        (permissions, errors)
        permissions: [{
            "form": "供应商",
            "rules": [{
                "role": "admin",
                "op": "all",            # add/view/edit/delete 都有时为 all，否则逗号分隔
                "data": "ALL",
                "canDraft": True,
                "canImport": False,
                "canExport": True,
            }]
        }]
    """
    from app.doc_table_parser import parse_all_tables
    errors: List[str] = []

    # 支持权限表在 ### 子章节里（如 ### 6.1 表单权限）
    # 把整个 section 所有表格的行合并
    all_tables = parse_all_tables(section_text)
    rows = []
    for table in all_tables:
        if table and ("表单名称" in table[0] or "表单编码" in table[0]):
            rows.extend(table)

    if not rows:
        errors.append("权限配置：未找到有效表格")
        return [], errors

    # 按表单名/编码分组
    form_rules: dict = {}  # form_name → [rule]

    for row in rows:
        # 兼容 "表单名称" 和 "表单编码" 两种列名
        form_name = (row.get("表单名称") or row.get("表单编码") or "").strip()
        role_code = row.get("角色编码", "").strip()
        data_scope_raw = row.get("数据范围", "全公司").strip()

        if not form_name:
            errors.append(f"权限配置：某行缺少表单名称，已跳过")
            continue
        if not role_code:
            errors.append(f"权限配置 '{form_name}'：缺少角色编码")
            continue
        if role_codes and role_code not in role_codes:
            errors.append(f"权限配置 '{form_name}'：角色编码 '{role_code}' 未在角色列表中定义")

        data_scope = _DATA_SCOPE_MAP.get(data_scope_raw.lower(), _DATA_SCOPE_MAP.get(data_scope_raw, "ALL"))

        # 解析各权限列
        perms: dict = {}
        for col, op in _PERM_COLUMNS.items():
            perms[op] = bool_cell(row.get(col, "否"))

        # 判断是否 "all"（核心4个权限全开）
        core_ops = {op for op in _ALL_OPS}
        if all(perms.get(op, False) for op in core_ops):
            op_str = "all"
        else:
            op_list = [op for op in ["add", "view", "edit", "delete"] if perms.get(op)]
            op_str = ",".join(op_list) if op_list else "view"

        rule = {
            "role": role_code,
            "op": op_str,
            "data": data_scope,
            "canDraft": perms.get("draft", False),
            "canImport": perms.get("import", False),
            "canExport": perms.get("export", False),
        }

        if form_name not in form_rules:
            form_rules[form_name] = []
        form_rules[form_name].append(rule)

    permissions = [
        {"form": form_name, "rules": rules}
        for form_name, rules in form_rules.items()
    ]

    return permissions, errors
