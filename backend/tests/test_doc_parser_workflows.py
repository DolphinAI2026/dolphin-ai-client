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


def test_duplicate_form_code_keeps_first_warns_rest():
    dup = (
        "### 流程A（关联表单：test_report）\n| 顺序 | 审批节点 | 审批人角色编码 |\n|---|---|---|\n| 1 | 审批 | role_a |\n\n"
        "### 流程B（关联表单：test_report）\n| 顺序 | 审批节点 | 审批人角色编码 |\n|---|---|---|\n| 1 | 审批 | role_b |\n"
    )
    flows, errors = wf_parser.parse(dup)
    assert len(flows) == 1  # 同表单只留第一条
    assert flows[0]["name"] == "流程A"
    assert errors and "已有流程" in errors[0]


def test_numeric_prefix_stripped_from_name():
    flows, _ = wf_parser.parse(
        "### 7.1 报告审批流（关联表单：test_report）\n| 顺序 | 审批节点 | 审批人角色编码 |\n|---|---|---|\n| 1 | 审批 | role_a |\n"
    )
    assert flows[0]["name"] == "报告审批流"  # 7.1 前缀被去掉


def test_full_pipeline_routes_chapter_to_config():
    """端到端：整篇 doc 过 doc_standard_parser → config['workflows'] 非空。

    回归保护 split_sections 不再把 `### 名称（关联表单：…）` 当成章节边界吃掉「七、审批流程」。
    """
    from app.doc_standard_parser import parse as parse_doc

    doc = """## 一、应用信息
| 字段 | 值 |
|---|---|
| 应用名称 | 测试 |
| 应用编码 | test-app |
## 七、审批流程
### 报告审批流（关联表单：test_report）
| 顺序 | 审批节点 | 审批人角色编码 |
|---|---|---|
| 1 | 班组长审批 | role_a |
| 2 | 质量经理审批 | role_b |
"""
    r = parse_doc(doc)
    wfs = r.config.get("workflows")
    assert wfs, f"工作流没被解析进 config（split_sections 又把章节吃了？）：{wfs}"
    assert wfs[0]["form_code"] == "test_report"
    assert [n["role_code"] for n in wfs[0]["nodes"]] == ["role_a", "role_b"]
