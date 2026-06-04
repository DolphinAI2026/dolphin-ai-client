# 0-to-1 审批流程生成 V1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ai-builder 的 0-to-1 应用生成链路，当设计文档写了「七、审批流程」章节时，自动在 aPaaS 平台创建对应的线性多级审批流程（角色审批人，绑定到表单），失败只告警不阻断核心生成。

**Architecture:** 复用唯一抓包验证过的 payload builder（`mcp_server._build_process_payload_v2`，抽到共享模块 `app/process_payload.py`）+ `apaas_client.save_process_config`。文档侧加可选第 7 章；解析器把第 7 章变成 `config["data"]["workflows"]`（splitter 已天然支持 `workflows` key 和 `### 名称（关联表单：code）` 子章节，无需改）；generator 加 Phase 5 调一个独立可测的 `workflow_phase.create_workflows`，按 form_code 反查 formId、按 role_code 反查角色雪花 ID，组 payload 调平台。

**Tech Stack:** Python 3.13（`.venv`）、FastAPI、SQLAlchemy；pytest（`asyncio_mode=auto`）；后端无 Alembic。aPaaS HTTP API（`/xdap-app/process/save/processConfig`）。

**范围（V1）：** 线性多级审批 + 角色审批人。**不做**：条件分支/网关、会签、非角色审批人（这些是 spec 的 V2，已在 spec 设计、本计划不实现）；不动那两条坏路（`execute_create_workflow`/`process_translator`/`WORKFLOW_STEPS` flag）。

**相对 spec 的计划期细化（都是简化、向现有代码对齐）：**
1. 文档子章节格式用 `### 流程名（关联表单：form_code）`（不是 spec 里的「绑定表单」）——复用 `doc_section_splitter._WORKFLOW_SUBSECTION_RE`（已存在）。
2. splitter 无需改：`_SECTION_KEYWORDS` 已含 `审批流程/流程配置/业务流程 → workflows`，`split_subsections` 已解析 workflow 子章节。
3. Phase 5 抽到独立模块 `app/workflow_phase.py`（spec 说「在 generator_v2 里」）——为可测性。

---

## File Structure

新增：
- `backend/app/process_payload.py` — 从 mcp_server 抽出的纯 payload builder + 6 个 helper。导出 `build_process_payload(...)`。无 FastMCP/HTTP/DB 依赖。
- `backend/app/doc_parsers/workflows.py` — 第 7 章解析器，`parse(section_text) -> (workflows, errors)`。
- `backend/app/workflow_phase.py` — `build_workflow_payload(...)`（纯，组单条流程 payload）+ `create_workflows(...)`（async generator，跑 Phase 5、调 save_process_config、非致命）。
- `backend/tests/test_process_payload.py`
- `backend/tests/test_doc_parser_workflows.py`
- `backend/tests/test_workflow_phase.py`

修改：
- `backend/app/mcp_server.py:5624-5977` — 7 个流程 payload 函数搬走，改成从 `app.process_payload` import 回来（保持 `set_apaas_app_process` 等调用方不变）。
- `backend/app/doc_standard_parser.py` — import workflows 解析器；把 `"workflows": []` 换成解析结果。
- `backend/app/generator_v2.py` — Phase 4 之后加 Phase 5（`async for ev in create_workflows(...)`）。
- `backend/app/doc_spec_standard.py` — `STANDARD_DOC_FORMAT` 加第 7 章（可选）+ 字段约束补一句。
- `backend/app/ai_chat/agent.py` — 提示词：识别审批需求 → 产第 7 章。

---

## Task 1: 抽共享 payload 模块 `process_payload.py`

把唯一验证过的 builder 从 mcp_server 抽出来共享，**不改行为**。测试先从新模块 import（RED=ImportError），再搬代码（GREEN），并断言已验证的 payload 契约不变。

**Files:**
- Create: `backend/app/process_payload.py`
- Modify: `backend/app/mcp_server.py:5624-5977`
- Test: `backend/tests/test_process_payload.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_process_payload.py`:

```python
"""抽出的流程 payload builder 契约 —— 护住已抓包验证的字段，保证抽取不改行为。"""
from __future__ import annotations

import pytest

from app.process_payload import build_process_payload


def _fixed_stages():
    return [
        {"name": "班组长审批", "approver_type": "ROLE", "approver_value": "role_id_1", "approver_label": "班组长"},
        {"name": "质量经理审批", "approver_type": "ROLE", "approver_value": "role_id_2", "approver_label": "质量经理"},
    ]


def test_payload_has_verified_critical_fields():
    p = build_process_payload(
        app_id="app1", form_id="F123", menu_id="M9",
        process_name="检测报告审批流", process_code="proc_test_report",
        stages_with_role=_fixed_stages(),
    )
    # ★ 最致命字段：流程绑哪张表
    assert p["processDataSource"] == {"sourceType": "SOURCE_TYPE_BO", "objectId": "boc_code_F123"}
    assert p["appId"] == "app1"
    assert p["formId"] == "F123"
    assert p["menuId"] == "M9"
    assert p["processName"] == "检测报告审批流"
    assert p["processCode"] == "proc_test_report"
    assert p["status"] == "ENABLE"
    assert p["engine"] == "VERSION_1.1"
    assert p["boExist"] is True
    assert isinstance(p["bpmn"], str) and "<" in p["bpmn"]  # 真 BPMN XML
    # START + END + 2 审批节点 = 4
    assert len(p["nodes"]) == 4
    assert p["nodes"][0]["id"] == "START"
    assert p["nodes"][1]["id"] == "END"
    # 边：START→stage1, stage1→stage2, stage2→END = 3
    assert len(p["edges"]) == 3


def test_approver_is_role_id_not_code():
    p = build_process_payload(
        app_id="a", form_id="F", menu_id="M",
        process_name="n", process_code="c", stages_with_role=_fixed_stages(),
    )
    approve_nodes = [n for n in p["nodes"] if n["id"] not in ("START", "END")]
    approvers = approve_nodes[0]["data"]["approvers"]
    assert approvers[0]["type"] == "ROLE"
    assert approvers[0]["value"] == "role_id_1"  # 雪花 id，不是 role_code
    assert approvers[0]["displayData"]["label"] == "班组长"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_process_payload.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.process_payload'`

- [ ] **Step 3: 建新模块，把 7 个函数从 mcp_server 原样搬过来**

Create `backend/app/process_payload.py`. 把 `backend/app/mcp_server.py` 第 **5624-5977** 行的这 7 个函数**逐字剪切**过来（它们都是纯函数、只依赖 `secrets`，无 FastMCP/HTTP/DB 依赖）：`_bpmn_random_id`、`_approve_node_data_template`、`_start_node_data`、`_end_node_data`、`_process_edge_template`、`_build_executable_bpmn_xml`、`_build_process_payload_v2`。文件头：

```python
"""aPaaS 流程 payload builder（抓包验证过的 schema）。

从 mcp_server 抽出共享：set_apaas_app_process（MCP 工具）和 generator_v2 Phase 5 都用这一份。
线性多级审批链 → 平台 /xdap-app/process/save/processConfig 接受的完整 payload。
**只动文件位置，不改任何逻辑**（行为由 tests/test_process_payload.py 锁定）。
"""
from __future__ import annotations

# ↓↓↓ 以下 7 个函数从 mcp_server.py:5624-5977 原样搬入（不改逻辑）↓↓↓
# def _bpmn_random_id() -> str: ...
# def _approve_node_data_template(...): ...
# def _start_node_data() -> dict: ...
# def _end_node_data() -> dict: ...
# def _process_edge_template(...): ...
# def _build_executable_bpmn_xml(...): ...
# def _build_process_payload_v2(app_id, form_id, menu_id, process_name, process_code, stages_with_role) -> dict: ...
```

在文件末尾加一个公开别名（对外用清晰名字，内部别名兼容老调用）：

```python
# 对外公开名（generator_v2 / 新代码用这个）
build_process_payload = _build_process_payload_v2
```

- [ ] **Step 4: mcp_server 改成 import 回来（保持调用方不变）**

在 `backend/app/mcp_server.py` 删掉刚搬走的 5624-5977 那 7 个函数定义，原位置换成 import（放在文件顶部 import 区或原位置均可，确保在 `set_apaas_app_process`（~5981 行）之前）：

```python
from app.process_payload import (  # 流程 payload builder 已抽到共享模块（行为不变）
    _bpmn_random_id,
    _approve_node_data_template,
    _start_node_data,
    _end_node_data,
    _process_edge_template,
    _build_executable_bpmn_xml,
    _build_process_payload_v2,
)
```

（全部 7 个名字都 re-export，避免 mcp_server 里别处直接调某个 helper 时找不到。）

- [ ] **Step 5: 跑测试确认通过 + mcp_server 冒烟**

Run: `cd backend && .venv/bin/python -m pytest tests/test_process_payload.py -v`
Expected: PASS（2 passed）

Run: `cd backend && .venv/bin/python -c "import app.mcp_server; from app.mcp_server import _build_process_payload_v2, set_apaas_app_process; print('mcp ok')"`
Expected: `mcp ok`（证明 set_apaas_app_process 仍能解析到 builder，抽取没破坏在用的 MCP 工具）

- [ ] **Step 6: 提交**

```bash
git add backend/app/process_payload.py backend/app/mcp_server.py backend/tests/test_process_payload.py
git commit -m "refactor(process): extract verified process payload builder to app/process_payload.py"
```
End the commit body with:
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

---

## Task 2: 第 7 章解析器 `doc_parsers/workflows.py`

**Files:**
- Create: `backend/app/doc_parsers/workflows.py`
- Modify: `backend/app/doc_standard_parser.py`（import + 替换 `"workflows": []`）
- Test: `backend/tests/test_doc_parser_workflows.py`

> 复用现成：`split_subsections`（已识别 `### 名称（关联表单：code）` → 返回 `(name, form_code, None, content)`）+ `parse_table`（解析节点表）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_doc_parser_workflows.py`:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_doc_parser_workflows.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.doc_parsers.workflows'`

- [ ] **Step 3: 写解析器**

Create `backend/app/doc_parsers/workflows.py`:

```python
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

from app.doc_section_splitter import split_subsections
from app.doc_table_parser import parse_table


def parse(section_text: str) -> Tuple[List[dict], List[str]]:
    workflows: List[dict] = []
    errors: List[str] = []
    if not section_text or not section_text.strip():
        return workflows, errors

    for name, form_code, _tag, content in split_subsections(section_text):
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_doc_parser_workflows.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 接进 doc_standard_parser**

在 `backend/app/doc_standard_parser.py` 顶部的 `from app.doc_parsers import ...` 那一串后加：

```python
from app.doc_parsers import permissions as permissions_parser
from app.doc_parsers import workflows as workflows_parser
```

找到 config 组装处（`result.config = {...}`，约 137 行）把 `"workflows": []` 换成解析结果。在组装 config **之前**加解析（放在权限解析之后、`result.config = {...}` 之前）：

```python
    # ── 7. 审批流程（可选章节）──
    workflows, workflow_errors = workflows_parser.parse(sections.get("workflows", ""))
    if workflow_errors:
        result.errors.extend(workflow_errors)

    # ── 组装 config ───────────────────────────────────────────
    result.config = {
        "appName": app_name,
        "appCode": app_code,
        "roles": roles,
        "dicts": dicts,
        "models": models,
        "forms": forms,
        "workflows": workflows,
        "permissions": permissions,
    }
```

- [ ] **Step 6: 跑测试 + import 冒烟**

Run: `cd backend && .venv/bin/python -m pytest tests/test_doc_parser_workflows.py -v` → PASS
Run: `cd backend && .venv/bin/python -c "import app.doc_standard_parser; print('ok')"` → `ok`

- [ ] **Step 7: 提交**

```bash
git add backend/app/doc_parsers/workflows.py backend/app/doc_standard_parser.py backend/tests/test_doc_parser_workflows.py
git commit -m "feat(doc): parse 七、审批流程 chapter into config workflows"
```
End commit body with Co-Authored-By trailer.

---

## Task 3: `workflow_phase.py` —— payload 装配 + Phase 5 async generator

**Files:**
- Create: `backend/app/workflow_phase.py`
- Test: `backend/tests/test_workflow_phase.py`

> `build_workflow_payload` 纯函数（按 form_code 反查 formId、按 role_code 反查角色雪花 id、组 payload）；`create_workflows` async generator（跑一遍、调 save_process_config、单条失败只告警）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_workflow_phase.py`:

```python
"""Phase 5：workflow → payload 装配 + 非致命建流程循环。"""
from __future__ import annotations

import pytest

from app import workflow_phase


FORM_RESULTS = [
    {"formId": "F_report", "formCode": "test_report", "formName": "检测报告", "menuId": "M_report"},
]
ROLE_MAP = {
    "role_team_leader": {"roleCode": "role_team_leader", "roleName": "班组长", "id": "RID_1"},
    "role_quality_mgr": {"roleCode": "role_quality_mgr", "roleName": "质量经理", "id": "RID_2"},
}
WF = {
    "name": "检测报告审批流",
    "form_code": "test_report",
    "nodes": [
        {"name": "班组长审批", "role_code": "role_team_leader"},
        {"name": "质量经理审批", "role_code": "role_quality_mgr"},
    ],
}


def test_build_payload_binds_form_and_role_ids():
    payload, reason = workflow_phase.build_workflow_payload(WF, FORM_RESULTS, ROLE_MAP, app_id="app1")
    assert reason is None
    assert payload["processDataSource"]["objectId"] == "boc_code_F_report"
    assert payload["formId"] == "F_report"
    assert payload["menuId"] == "M_report"
    approve_nodes = [n for n in payload["nodes"] if n["id"] not in ("START", "END")]
    assert approve_nodes[0]["data"]["approvers"][0]["value"] == "RID_1"  # 角色 id 不是 code
    assert approve_nodes[1]["data"]["approvers"][0]["value"] == "RID_2"


def test_build_payload_missing_form_returns_reason():
    payload, reason = workflow_phase.build_workflow_payload(
        {**WF, "form_code": "nope"}, FORM_RESULTS, ROLE_MAP, app_id="app1"
    )
    assert payload is None
    assert reason and "nope" in reason


def test_build_payload_missing_role_returns_reason():
    wf = {**WF, "nodes": [{"name": "审批", "role_code": "role_unknown"}]}
    payload, reason = workflow_phase.build_workflow_payload(wf, FORM_RESULTS, ROLE_MAP, app_id="app1")
    assert payload is None
    assert reason and "role_unknown" in reason


@pytest.mark.asyncio
async def test_create_workflows_calls_save_and_is_non_fatal():
    saved = []

    class _FakeClient:
        async def save_process_config(self, app_id, payload):
            saved.append((app_id, payload))
            return {"code": "ok"}

    good = WF
    bad_form = {**WF, "name": "坏的", "form_code": "missing_form"}
    events = []
    async for ev in workflow_phase.create_workflows(
        _FakeClient(), "app1", [good, bad_form], FORM_RESULTS, ROLE_MAP
    ):
        events.append(ev)

    # 好的那条建了流程；坏的那条只告警、没崩、没中断
    assert len(saved) == 1
    assert saved[0][1]["processName"] == "检测报告审批流"
    assert any(e.get("stage") == 5 for e in events)
    assert any("坏的" in (e.get("step") or "") for e in events)  # 警告事件提到坏的那条


@pytest.mark.asyncio
async def test_create_workflows_save_failure_does_not_raise():
    class _BoomClient:
        async def save_process_config(self, app_id, payload):
            raise RuntimeError("platform 500")

    events = []
    async for ev in workflow_phase.create_workflows(
        _BoomClient(), "app1", [WF], FORM_RESULTS, ROLE_MAP
    ):
        events.append(ev)
    # 平台报错也不往外抛，只 yield 一个告警
    assert any(e.get("stage") == 5 for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workflow_phase.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.workflow_phase'`

- [ ] **Step 3: 写 workflow_phase**

Create `backend/app/workflow_phase.py`:

```python
"""generator_v2 Phase 5：把解析出的 workflows 在 aPaaS 平台建成审批流程。

build_workflow_payload —— 纯函数：按 form_code 反查 formId/menuId，按 role_code 反查角色雪花 id，
组成已验证的平台 payload。create_workflows —— async generator：逐条建、调 save_process_config，
单条失败（找不到表单/角色/平台报错）只 yield 一个 stage:5 告警，绝不中断（流程是增强、非核心）。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, List, Optional, Tuple

from app.process_payload import build_process_payload

logger = logging.getLogger(__name__)


def _workflow_process_code(form_code: str, name: str) -> str:
    """确定性 ascii 流程编码。V1 假设一表单一流程，proc_<form_code> 已足够唯一。"""
    return f"proc_{form_code}"


def build_workflow_payload(
    wf: dict, form_results: List[dict], role_code_map: dict, *, app_id: str
) -> Tuple[Optional[dict], Optional[str]]:
    """(payload, None) 成功；(None, reason) 跳过（reason 是给用户的告警文案）。纯函数，无 IO。"""
    form_code = wf.get("form_code")
    fr = next((f for f in form_results if f.get("formCode") == form_code), None)
    if not fr or not fr.get("formId"):
        return None, f"流程 '{wf.get('name')}'：关联表单 '{form_code}' 未找到或未创建成功，跳过"

    stages: List[dict] = []
    for node in wf.get("nodes", []):
        role_code = node.get("role_code")
        info = role_code_map.get(role_code) or {}
        role_id = info.get("id")
        if not role_id:
            return None, f"流程 '{wf.get('name')}'：审批人角色 '{role_code}' 未找到（需在第二章定义），跳过"
        stages.append({
            "name": node.get("name") or "审批",
            "approver_type": "ROLE",
            "approver_value": str(role_id),
            "approver_label": info.get("roleName") or role_code,
        })
    if not stages:
        return None, f"流程 '{wf.get('name')}'：无有效审批节点，跳过"

    payload = build_process_payload(
        app_id=app_id,
        form_id=fr["formId"],
        menu_id=fr.get("menuId", ""),
        process_name=wf.get("name") or "审批流程",
        process_code=_workflow_process_code(form_code, wf.get("name") or ""),
        stages_with_role=stages,
    )
    return payload, None


async def create_workflows(
    client, app_id: str, workflows: List[dict], form_results: List[dict], role_code_map: dict
) -> AsyncIterator[dict]:
    """Phase 5：逐条建审批流程。非致命 —— 任何一条失败只告警，继续下一条。"""
    if not workflows:
        return
    yield {"stage": 5, "status": "running", "step": f"创建审批流程（{len(workflows)} 条）..."}
    created = 0
    for wf in workflows:
        payload, reason = build_workflow_payload(wf, form_results, role_code_map, app_id=app_id)
        if reason:
            yield {"stage": 5, "status": "running", "step": f"⚠️ {reason}"}
            continue
        try:
            await client.save_process_config(app_id, payload)
            created += 1
            yield {"stage": 5, "status": "running", "step": f"流程: {wf.get('name')}"}
        except Exception as e:
            logger.warning("create workflow failed: %s", e, exc_info=True)
            yield {"stage": 5, "status": "running", "step": f"⚠️ 流程 '{wf.get('name')}' 创建失败（{e}），跳过"}
    yield {"stage": 5, "status": "done", "step": f"审批流程完成（{created}/{len(workflows)} 条）"}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workflow_phase.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/workflow_phase.py backend/tests/test_workflow_phase.py
git commit -m "feat(generator): add workflow_phase (payload assembly + non-fatal create loop)"
```
End commit body with Co-Authored-By trailer.

---

## Task 4: generator_v2 接 Phase 5

把 `create_workflows` 接进 `run_complete_generation`，放在 Phase 4（权限）之后。

**Files:**
- Modify: `backend/app/generator_v2.py`
- Test: `backend/tests/test_generator_v2_phase5_wiring.py`

- [ ] **Step 1: 先读代码确认 Phase 4 结束位置 + 作用域里有 `form_results` 和 `role_code_map`**

Run: `cd backend && grep -n "role_code_map\|form_results\|stage.*4.*done\|stage\": 4\|data.get(\"workflows\"\|run_complete_generation" app/generator_v2.py | head`
确认：`role_code_map`（Phase 1 建，`{doc_code: {roleCode, roleName, id}}`）、`form_results`（Phase 3 建，`[{formId, formCode, formName, menuId}]`）、`data`（`config.get("data", config)`）都在 `run_complete_generation` 函数作用域内、Phase 4 之后仍可见。记下 Phase 4 最后一个 `yield {"stage": 4, "status": "done", ...}` 的确切行与缩进。

- [ ] **Step 2: 写测试（整条 generator 走到 Phase 5 会建流程）**

Create `backend/tests/test_generator_v2_phase5_wiring.py`:

```python
"""run_complete_generation 接上 Phase 5：config 带 workflows 时会调 save_process_config。

只验证「接线」——Phase 5 被调用、save_process_config 收到正确 payload；前 4 个 phase 用
极简 mock client 让它们各自跑过即可（不验证 1-4 的细节，那是既有逻辑）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app import generator_v2


@pytest.mark.asyncio
async def test_phase5_creates_workflow_from_config(monkeypatch):
    # 极简 fake APaaSClient：让 1-4 phase 调到的方法都返回温和默认；记录 save_process_config
    client = MagicMock()
    client.create_roles = AsyncMock(return_value={"code": "ok"})
    client.query_roles = AsyncMock(return_value=[{"id": "RID_1", "roleCode": "role_a", "roleName": "审批角色"}])
    client.create_models = AsyncMock(return_value={"code": "ok"})
    client.create_dicts = AsyncMock(return_value={"code": "ok"})
    # create_form 返回带 id/formCode/menuId 的结果（Phase 3 form_results 来源）
    client.create_form = AsyncMock(return_value={"id": "F1", "formCode": "order", "menuId": "M1"})
    client.create_menu = AsyncMock(return_value={"code": "ok"})
    client.create_permissions = AsyncMock(return_value={"code": "ok"})
    client.save_process_config = AsyncMock(return_value={"code": "ok"})

    config = {
        "data": {
            "appName": "下单", "appCode": "order-app",
            "roles": [{"code": "role_a", "name": "审批角色"}],
            "dicts": [],
            "models": [{"code": "order", "name": "订单", "fields": [{"code": "amount", "name": "金额", "type": "金额"}]}],
            "forms": [{"code": "order", "name": "订单", "modelCode": "order"}],
            "permissions": [],
            "workflows": [{
                "name": "订单审批流", "form_code": "order",
                "nodes": [{"name": "审批", "role_code": "role_a"}],
            }],
        }
    }

    events = []
    async for ev in generator_v2.run_complete_generation(client, "app1", config):
        events.append(ev)

    # Phase 5 跑过 + save_process_config 被调
    assert any(e.get("stage") == 5 for e in events)
    client.save_process_config.assert_awaited()
    _app_id, payload = client.save_process_config.await_args.args
    assert payload["processName"] == "订单审批流"
    assert payload["processDataSource"]["objectId"] == "boc_code_F1"
```

> 注：上面 client 的方法名/返回结构需对齐 generator_v2 实际调用（Step 1 已读）。若实际方法名不同（如 create_form 实为 create_forms / 返回字段不同），按真实签名调整 mock；assert 部分（Phase 5 调 save_process_config + payload 绑定 boc_code_F1）保持不变。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generator_v2_phase5_wiring.py -v`
Expected: FAIL — 没有 `stage==5` 事件 / `save_process_config` 没被调（Phase 5 还没接）。

- [ ] **Step 4: 接 Phase 5**

在 `backend/app/generator_v2.py` 顶部 import 区加：

```python
from app.workflow_phase import create_workflows
```

在 `run_complete_generation` 里 Phase 4（权限）最后一个 `yield {"stage": 4, "status": "done", ...}` **之后**、函数 return/收尾之前，插入 Phase 5（缩进对齐 Step 1 记下的 phase 块）：

```python
        # ── Phase 5: 审批流程（可选；非核心，失败不阻断）──
        async for _wf_ev in create_workflows(
            client, app_id, data.get("workflows", []), form_results, role_code_map
        ):
            yield _wf_ev
```

（`data`、`form_results`、`role_code_map`、`client`、`app_id` 均为 Step 1 已确认在作用域内的既有变量。若某变量实际命名不同，用真实名替换。）

- [ ] **Step 5: 跑测试确认通过 + import 冒烟**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generator_v2_phase5_wiring.py -v`
Expected: PASS（1 passed）

Run: `cd backend && .venv/bin/python -c "import app.generator_v2; print('ok')"` → `ok`

- [ ] **Step 6: 提交**

```bash
git add backend/app/generator_v2.py backend/tests/test_generator_v2_phase5_wiring.py
git commit -m "feat(generator): wire Phase 5 workflow creation into run_complete_generation"
```
End commit body with Co-Authored-By trailer.

---

## Task 5: 文档规范第 7 章 + agent 提示词

让 agent 在有审批需求时产出第 7 章。纯文本改动（无单测；靠 detector 评分不变 + 上线实测验证）。

**Files:**
- Modify: `backend/app/doc_spec_standard.py`（`STANDARD_DOC_FORMAT` 加第 7 章 + 字段约束补一句）
- Modify: `backend/app/ai_chat/agent.py`（提示词）

- [ ] **Step 1: doc_spec_standard 加第 7 章**

在 `backend/app/doc_spec_standard.py` 的 `STANDARD_DOC_FORMAT` 里，「## 六、权限定义」那段之后、「# 字段约束」之前，插入第 7 章：

```python
## 七、审批流程
> **可选章节**：只在确实需要审批 / 流转时才写；没有审批流就整章省略。审批人**必须**引用「二、角色列表」里已定义的角色编码。V1 仅支持线性多级审批（按顺序一个节点接一个节点），暂不支持条件分支 / 会签。
> 每条流程一个 `### ` 子章节，标题写 `### 流程名（关联表单：表单编码）`（表单编码必须是「五、表单定义」里已定义的）。节点表三列：

### 报告审批流（关联表单：test_report）

| 顺序 | 审批节点 | 审批人角色编码 |
|---|---|---|
| 1 | 班组长审批 | role_team_leader |
| 2 | 质量经理审批 | role_quality_mgr |
```

- [ ] **Step 2: 字段约束补一句（在「### 内容约束」列表里加一条）**

在 `backend/app/doc_spec_standard.py` 的「### 内容约束」那个列表末尾加：

```python
- 用户提到「需要审批 / 审批流 / 流转 / 送审」等流程需求时，在「七、审批流程」里结构化写出（关联到对应表单 + 列出审批节点与审批人角色）；没提就省略该章节
```

- [ ] **Step 3: agent.py 提示词点一句**

在 `backend/app/ai_chat/agent.py` 的 `SYSTEM_PROMPT_UNIFIED` 里、讲文档章节产出的地方（如「6 章 markdown 设计文档」附近，约 87/139 行），把「6 章」表述补成涵盖可选第 7 章。找到形如 `(应用信息 / 角色 / 字典 / 模型 / 表单 / 权限)` 的串，改为：

```python
(应用信息 / 角色 / 字典 / 模型 / 表单 / 权限，有审批需求再加可选的「七、审批流程」)
```

（`STANDARD_DOC_FORMAT` 已经被 `_FORMAT_CONSTRAINTS` 注入，agent 能看到第 7 章的完整格式；这里只是再点一句让它别忘了在有审批需求时填。）

- [ ] **Step 4: detector 评分不掉 + import 冒烟**

Run: `cd backend && .venv/bin/python -c "import app.doc_spec_standard, app.ai_chat.agent; print('ok')"` → `ok`

Run（确认加了第 7 章的文档不被现有 6 章 detector 扣分 / 不报错）:
```bash
cd backend && .venv/bin/python -c "
from app.doc_standard_detector import detect
doc = open('/dev/stdin').read()
" <<'EOF'
## 一、应用信息
| 字段 | 值 |
|---|---|
| 应用名称 | 测试 |
| 应用编码 | test-app |
## 二、角色列表
| 角色编码 | 角色名称 |
|---|---|
| role_a | 角色A |
## 七、审批流程
### 流程（关联表单：t1）
| 顺序 | 审批节点 | 审批人角色编码 |
|---|---|---|
| 1 | 审批 | role_a |
EOF
echo "detector import ok"
```
Expected: 不报错（detector 只认 6 章，额外第 7 章被忽略、不影响评分）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/doc_spec_standard.py backend/app/ai_chat/agent.py
git commit -m "feat(doc): add optional 七、审批流程 chapter to doc standard + prompt"
```
End commit body with Co-Authored-By trailer.

---

## Task 6: 全量回归 + 端到端验证（preview）

**Files:** 无（验证）。

- [ ] **Step 1: 全量后端测试，确认无回归**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 新增 ~11 个 workflow 测试全绿；既有失败数与基线一致（已知 6 个 SQLite 预存失败，不应新增）。

- [ ] **Step 2: 重启 preview backend（改了 generator/mcp_server/parser，必须重启）**

用 preview 工具重启后端。

- [ ] **Step 3: 端到端建一个带审批流的应用**

在 `/ai-chat` 用有 LLM + 平台环境的租户（如租户 57），发一个含审批需求的需求（或直接复用印章场景，让它在设计文档里产出「七、审批流程」），跑完整 Phase 1 设计 → 确认 → Phase 2 generate + deploy + publish。`preview_network` 看 SSE 里出现 `stage:5` 事件；确认设计文档右栏含「七、审批流程」章节。

- [ ] **Step 4: 平台核验流程真创建**

应用上线后，在 aPaaS 平台打开该应用对应表单，确认审批流程已创建、节点与审批人角色正确。若 `save_process_config` 报错（如 payload 字段问题），抓 `preview_logs`/SSE 里的 `stage:5` 告警文案定位；因 Phase 5 非致命，应用本体（模型/表单/权限）仍应已正常上线。

> 这是无法单测的部分（需真平台）；`_build_process_payload_v2` 是抓包验证过的同一份 payload，理论上与 `set_apaas_app_process` 等效，但首次端到端必实测一条。

- [ ] **Step 5: 没有审批需求的应用不受影响**

跑一个不含审批需求的需求，确认设计文档无第 7 章、generate 正常（Phase 5 因 `workflows=[]` 直接跳过、不 yield 任何 stage:5）。

---

## Self-Review（对照 spec）

**Spec 覆盖：**
- 单元 1 抽共享 payload 模块 + golden test → Task 1 ✓（契约测试锁 `boc_code_{form_id}` 绑定 + 审批人角色 id）。
- 单元 2 文档第 7 章可选 → Task 5 ✓（格式细化为「关联表单」对齐现有 regex）。
- 单元 3 流程 parser + 接 doc_standard_parser → Task 2 ✓（splitter 无需改，spec 单元 3 的 splitter 部分被现有代码覆盖）。
- 单元 4 generator Phase 5 → Task 3（装配/循环，抽 workflow_phase）+ Task 4（接线）✓。
- 单元 5 提示词 → Task 5 ✓。
- 测试（golden / parser / Phase5 装配 / 真平台）→ Task 1/2/3 单测 + Task 6 端到端 ✓。
- 风险①formId 绑定 → build_workflow_payload 按 formCode 反查 formId（Task 3 测试断言 `boc_code_F_report`）✓；②审批人=角色 id → role_code_map.id（Task 3 测试断言 RID）✓；③可选章节不掉评分 → Task 5 Step 4 ✓；④抽取不破坏 MCP 工具 → Task 1 Step 5 冒烟 ✓；⑤menuId/formId 都透传 ✓。
- V2 条件分支：spec 设计、本计划不实现（范围声明已列）✓。

**Placeholder 扫描：** 无 TBD/占位。Task 4 Step 1/Step 2 note 明确要求按 generator_v2 真实变量名/方法签名对齐（这是「读真实代码再写」的指令，非占位）。

**类型一致性：** `build_process_payload(app_id, form_id, menu_id, process_name, process_code, stages_with_role)` 全计划一致；`stages_with_role` 元素 `{name, approver_type, approver_value, approver_label}` 与 mcp_server 原 builder 期望一致；workflow dict `{name, form_code, nodes:[{name, role_code}]}` 在 Task 2 产出、Task 3 消费一致；`form_results` 元素 `{formId, formCode, formName, menuId}`、`role_code_map` 值 `{roleCode, roleName, id}` 与 generator_v2 实际一致（已读）。

## 风险 / 注意
- **Task 1 抽取**是动在用的生产代码（set_apaas_app_process）。务必逐字搬、不改逻辑，靠契约测试 + import 冒烟兜底。若某 helper 在 mcp_server 别处也被直接调用，re-export 已覆盖（全 7 个名字都导回）。
- **Task 4** 是真接线点，generator_v2 的变量名/client 方法签名以实际为准（Step 1 先读）。`create_form` 等方法的真实名与返回结构若与测试 mock 不符，按真实调整 mock，但「Phase 5 调 save_process_config + payload 绑 boc_code」的断言不变。
- **真平台 payload**：理论等效 set_apaas_app_process（同一 builder），但 generator 上下文里 formId/menuId/角色 id 的来源不同，首次端到端必实测（Task 6 Step 4）。非致命设计保证即便流程建失败，应用主体仍上线。
- 重启 preview backend 后浏览器可能缓存旧 JS，刷新即可（非 bug）。
