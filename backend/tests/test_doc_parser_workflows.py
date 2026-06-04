"""第 7 章「审批流程」解析 → [{name, form_code, nodes:[{name, role_code}]}]。"""
from __future__ import annotations

from app.doc_parsers import workflows as wf_parser


SECTION = """### 检测报告审批流（关联表单：test_report）

| 顺序 | 审批节点 | 审批人角色编码 |
|---|---|---|
| 1 | 班组长审批 | role_team_leader |
| 2 | 质量经理审批 | role_quality_mgr |

### 原始记录审批流（关联表单：test_record）

| 顺序 | 审批节点 | 审批人角色编码 |
|---|---|---|
| 1 | 质量经理审批 | role_quality_mgr |
"""


def test_parses_multiple_workflows_with_ordered_nodes():
    flows, errors = wf_parser.parse(SECTION)
    assert len(flows) == 2
    f0 = flows[0]
    assert f0["name"] == "检测报告审批流"
    assert f0["form_code"] == "test_report"
    assert [n["name"] for n in f0["nodes"]] == ["班组长审批", "质量经理审批"]
    assert [n["role_code"] for n in f0["nodes"]] == ["role_team_leader", "role_quality_mgr"]
    assert flows[1]["form_code"] == "test_record"
    assert len(flows[1]["nodes"]) == 1


def test_empty_section_is_ok():
    flows, errors = wf_parser.parse("")
    assert flows == [] and errors == []


def test_missing_related_form_is_warned_not_crash():
    bad = "### 漏了关联表单的流程\n\n| 顺序 | 审批节点 | 审批人角色编码 |\n|---|---|---|\n| 1 | 审批 | role_a |\n"
    flows, errors = wf_parser.parse(bad)
    assert flows == []
    assert errors and "关联表单" in errors[0]


def test_workflow_without_valid_nodes_warned():
    bad = "### 空流程（关联表单：t1）\n\n| 顺序 | 审批节点 | 审批人角色编码 |\n|---|---|---|\n"
    flows, errors = wf_parser.parse(bad)
    assert flows == []
    assert errors
