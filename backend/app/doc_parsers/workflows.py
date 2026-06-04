"""审批流程（第 7 章）解析器。

文档格式（可选章节）：
    ## 七、审批流程
    ### 流程名（关联表单：form_code）
    | 顺序 | 审批节点 | 审批人角色编码 |
    |---|---|---|
    | 1 | 班组长审批 | role_team_leader |

输出：[{name, form_code, nodes: [{name, role_code}]}]。节点按表格行顺序（顺序列仅供人读）。
缺关联表单 / 无有效节点 → 记 error（非致命），跳过该条。
"""
from __future__ import annotations

from typing import List, Tuple

import re

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table

_NUM_PREFIX_RE = re.compile(r"^\d+\.\d+\s*")


def parse(section_text: str) -> Tuple[List[dict], List[str]]:
    workflows: List[dict] = []
    errors: List[str] = []
    if not section_text or not section_text.strip():
        return workflows, errors

    for name, form_code, _tag, content in split_subsections(section_text):
        # 容忍 agent 写成 `### 7.1 报告审批流（…）`：去掉 7.1 这种数字前缀，流程名才干净
        name = _NUM_PREFIX_RE.sub("", name).strip()
        if not form_code:
            errors.append(
                f"审批流程 '{name}'：未标注关联表单，跳过（正确写法：### {name}（关联表单：form_code））"
            )
            continue
        nodes: List[dict] = []
        for row in parse_table(content):
            node_name = (row.get("审批节点") or "").strip()
            role_code = (row.get("审批人角色编码") or "").strip()
            if not node_name or not role_code:
                continue
            nodes.append({"name": node_name, "role_code": role_code})
        if not nodes:
            errors.append(f"审批流程 '{name}'：没有有效审批节点（需要『审批节点』+『审批人角色编码』两列），跳过")
            continue
        workflows.append({"name": name, "form_code": form_code, "nodes": nodes})

    return workflows, errors
