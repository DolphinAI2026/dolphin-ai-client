"""审批/流程配置解析器。"""
from __future__ import annotations

from typing import List, Tuple

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_all_tables


def _first(row: dict, *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def parse(section_text: str) -> Tuple[List[dict], List[str]]:
    """解析“流程配置/审批流程”章节。

    支持一张总表：
    流程名称 | 关联表单 | 步骤 | 动作 | 审批角色 | 状态/结果

    也支持多个子章节：
    ### 变更审批（关联表单：变更管理）
    | 步骤 | 动作 | 审批角色 | 状态/结果 |
    """
    errors: List[str] = []
    workflows_by_key: dict[str, dict] = {}

    def ensure_workflow(name: str, form: str, idx: int) -> dict:
        flow_name = name or (f"{form}审批流程" if form else f"审批流程{idx}")
        key = f"{flow_name}::{form}"
        if key not in workflows_by_key:
            code_base = f"workflow_{len(workflows_by_key) + 1}"
            workflows_by_key[key] = {
                "name": flow_name,
                "form": form,
                "nodes": [],
                "flow_name": flow_name,
                "flow_code": code_base,
                "steps": [],
            }
        return workflows_by_key[key]

    def append_step(workflow: dict, row: dict, fallback_step: int) -> None:
        action = _first(row, "动作", "节点名称", "步骤说明", "说明")
        role = _first(row, "审批角色", "角色", "审批人", "处理角色")
        status = _first(row, "状态/结果", "状态", "结果")
        step = _first(row, "步骤", "序号", "顺序") or str(fallback_step)
        node_name = action or role or f"审批节点 {fallback_step}"
        workflow["steps"].append({
            "step": step,
            "action": action or node_name,
            "role": role,
            "status": status,
        })
        workflow["nodes"].append({
            "name": node_name,
            "role": role,
            "type": "approve",
            "status": status,
        })

    subsections = split_subsections(section_text)
    if not subsections:
        tables = parse_all_tables(section_text)
        row_count = 0
        for table in tables:
            for row in table:
                row_count += 1
                flow_name = _first(row, "流程名称", "审批流程", "流程")
                form = _first(row, "关联表单", "表单名称", "表单")
                workflow = ensure_workflow(flow_name, form, row_count)
                append_step(workflow, row, len(workflow["steps"]) + 1)

    for sub_idx, (title, code, _tag, content) in enumerate(subsections, start=1):
        sub_tables = parse_all_tables(content)
        if not sub_tables:
            continue
        workflow = ensure_workflow(title, code or "", sub_idx)
        for table in sub_tables:
            for row in table:
                append_step(workflow, row, len(workflow["steps"]) + 1)

    workflows = [wf for wf in workflows_by_key.values() if wf.get("steps") or wf.get("nodes")]
    if not workflows:
        errors.append("流程配置：未找到有效流程表格")
    return workflows, errors
