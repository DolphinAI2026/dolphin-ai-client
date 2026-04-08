"""Markdown 表格防御性解析器

设计原则：
- 宽松解析：多余空格、列数不匹配都能处理
- 列头模糊匹配：允许同义词、大小写、全半角差异
- 永远返回 list，不抛异常
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


# ── 列头同义词映射（文档写法 → 标准 key）──────────────────────
_HEADER_ALIASES: Dict[str, str] = {
    # 应用信息
    "应用编码": "应用编码", "appcode": "应用编码", "app_code": "应用编码",
    "应用名称": "应用名称", "appname": "应用名称", "app_name": "应用名称",
    "项目": "项目", "值": "值",
    # 角色
    "角色编码": "角色编码", "rolecode": "角色编码", "role_code": "角色编码",
    "角色名称": "角色名称", "rolename": "角色名称", "role_name": "角色名称", "角色名": "角色名称",
    # 字典
    "字典编码": "字典编码", "字典名称": "字典名称",
    "选项编码": "选项编码", "valuecode": "选项编码", "optioncode": "选项编码",
    "选项名称": "选项名称", "valuename": "选项名称", "optionname": "选项名称", "选项名": "选项名称",
    # 数据模型
    "模型编码": "模型编码", "模型名称": "模型名称",
    "所属主表模型编码": "所属主表模型编码",
    "字段编码": "字段编码", "fieldcode": "字段编码", "field_code": "字段编码",
    "字段名称": "字段名称", "fieldname": "字段名称", "field_name": "字段名称", "字段名": "字段名称",
    "字段类型": "字段类型", "fieldtype": "字段类型", "field_type": "字段类型", "类型": "字段类型",
    "数据库字段类型": "数据库字段类型", "databasefieldtype": "数据库字段类型", "database_field_type": "数据库字段类型",
    "存储类型": "数据库字段类型", "dbtype": "数据库字段类型", "db_type": "数据库字段类型",
    "长度/精度": "长度/精度", "长度": "长度", "精度": "长度/精度", "maxlength": "长度", "max_length": "长度",
    "必填": "必填", "说明": "说明",
    "字典编码": "字典编码", "dictcode": "字典编码", "dict_code": "字典编码",
    "关联模型编码": "关联模型编码", "ref_model": "关联模型编码", "refmodel": "关联模型编码",
    "关联显示字段编码": "关联显示字段编码", "ref_field": "关联显示字段编码", "reffield": "关联显示字段编码",
    # 表单配置
    "表单编码": "表单编码", "表单名称": "表单名称", "表单名": "表单名称",
    "绑定主表模型编码": "绑定主表模型编码",
    "组件类型": "组件类型",
    "子表模型编码": "子表模型编码", "子表模型名称": "子表模型名称", "子表显示名称": "子表显示名称",
    "子表字段编码": "子表字段编码", "子表字段名称": "子表字段名称",
    "是否隐藏": "是否隐藏", "hidden": "是否隐藏",
    "是否只读": "是否只读", "readonly": "是否只读",
    "是否必填": "是否必填", "required": "是否必填",
    "是否列表展示": "是否列表展示", "showinlist": "是否列表展示", "列表展示": "是否列表展示",
    "是否查询条件": "是否查询条件", "searchable": "是否查询条件", "查询条件": "是否查询条件",
    # 权限配置
    "表单名称": "表单名称", "formname": "表单名称", "form_name": "表单名称", "表单": "表单名称",
    "角色编码": "角色编码",
    "可暂存": "可暂存", "draft": "可暂存",
    "可新增": "可新增", "add": "可新增", "新增": "可新增",
    "可导入": "可导入", "import": "可导入", "导入": "可导入",
    "可查看": "可查看", "view": "可查看", "查看": "可查看",
    "可编辑": "可编辑", "edit": "可编辑", "编辑": "可编辑",
    "可删除": "可删除", "delete": "可删除", "删除": "可删除",
    "可导出": "可导出", "export": "可导出", "导出": "可导出",
    "数据范围": "数据范围", "datascope": "数据范围", "data_scope": "数据范围",
    # 审批流程
    "节点名称": "节点名称",
    "节点类型": "节点类型",
    "审批角色": "审批角色",
}


def _normalize_header(h: str) -> str:
    """归一化列头：去空格、转小写、去全角"""
    h = h.strip()
    h = h.replace("（", "(").replace("）", ")")
    return h.lower()


def _resolve_header(raw: str) -> str:
    """将原始列头映射到标准 key，找不到时返回原始值（stripped）"""
    norm = _normalize_header(raw)
    return _HEADER_ALIASES.get(norm, _HEADER_ALIASES.get(raw.strip(), raw.strip()))


def _split_row(line: str) -> List[str]:
    """拆分一行 | a | b | c | → ['a', 'b', 'c']"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_separator(line: str) -> bool:
    """判断是否是分隔行 |---|---|"""
    stripped = line.strip().replace(" ", "")
    return bool(re.match(r"^\|?[-:]+(\|[-:]+)+\|?$", stripped))


def find_tables(text: str) -> List[str]:
    """从文本中提取所有 markdown 表格（返回每个表格的原始文本）"""
    lines = text.splitlines()
    tables: List[str] = []
    i = 0
    while i < len(lines):
        # 找表格起始行（含 |）
        if "|" in lines[i] and not _is_separator(lines[i]):
            # 检查下一行是否是分隔行
            if i + 1 < len(lines) and _is_separator(lines[i + 1]):
                j = i + 2
                while j < len(lines) and "|" in lines[j]:
                    j += 1
                tables.append("\n".join(lines[i:j]))
                i = j
                continue
        i += 1
    return tables


def parse_table(text: str) -> List[Dict[str, str]]:
    """解析文本中第一个 markdown 表格，返回 [{列头: 值}, ...]

    - 列数不匹配时：多余列忽略，缺少列补空字符串
    - 无表格时返回空列表
    """
    tables = find_tables(text)
    if not tables:
        return []
    return _parse_single_table(tables[0])


def parse_all_tables(text: str) -> List[List[Dict[str, str]]]:
    """解析文本中所有表格"""
    return [_parse_single_table(t) for t in find_tables(text)]


def _parse_single_table(table_text: str) -> List[Dict[str, str]]:
    lines = [l for l in table_text.splitlines() if l.strip()]
    if len(lines) < 2:
        return []

    # 表头
    raw_headers = _split_row(lines[0])
    headers = [_resolve_header(h) for h in raw_headers]
    col_count = len(headers)

    rows: List[Dict[str, str]] = []
    for line in lines[2:]:  # 跳过分隔行
        if not line.strip() or not "|" in line:
            continue
        cells = _split_row(line)
        # 补齐或截断
        if len(cells) < col_count:
            cells.extend([""] * (col_count - len(cells)))
        row = {headers[i]: cells[i] for i in range(col_count)}
        rows.append(row)

    return rows


def bool_cell(value: str) -> bool:
    """将单元格值转换为布尔值：是/yes/true/1 → True"""
    return value.strip().lower() in {"是", "yes", "true", "1", "y"}
