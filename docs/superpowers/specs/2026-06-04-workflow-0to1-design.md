# 0-to-1 审批流程生成 — 设计

> 日期: 2026-06-04
> 状态: 待用户 review spec
> 范围: 让 ai-builder 的 0-to-1 应用生成链路能产出并在 aPaaS 平台真创建审批流程（流程）。V1 = 线性多级审批 + 角色审批人；条件分支作为 V2 设计、后续开发。

## 背景

ai-builder 现在的 0-to-1 链路（设计文档 → `generate_app_from_doc` → deploy → publish）能建模型/表单/角色/权限，但**完全不产出任何审批流程**。用户在「印章管理系统设计」里提了"原始记录和检测报告需要审批流"，agent 在散文里识别到了，却没有任何结构化输出槽，最后被丢掉。三个 gap 同时成立：

- **文档 gap**：`doc_spec_standard.py` 的 `STANDARD_DOC_FORMAT` 只有 6 章（应用信息 / 角色 / 字典 / 模型 / 表单 / 权限），没有流程章节。
- **管线 gap**：`generator_v2.run_complete_generation` 只有 4 个 phase；标准 parser `doc_standard_parser.py:145` 直接 hardcode `"workflows": []`。
- **API 接线 gap（半接）**：平台**有**流程创建 API，仓库也有流程相关代码，但能用的只有一条。

### 关键发现：4 条流程创建路径，只有 1 条是验证过的

调查（2026-06-04）确认仓库里有 4 条流程创建路径，最终都 POST 到同一个端点 `/xdap-app/process/save/processConfig`（`apaas_client.save_process_config`），区别只在 **payload 完整度**：

| 路径 | 入口 | payload builder | 状态 |
|---|---|---|---|
| `set_apaas_app_process`（MCP 工具） | 用户触发 | `_build_process_payload_v2`（`mcp_server.py:5840`） | ✅ **抓包验证过、生产在用** |
| `deploy_process_to_apaas`（MCP） | 用户从 ProcessDesigner 触发 | `process_translator.translate_definition_to_apaas_schema` | ⚠️ payload 缺字段、未验证 |
| `execute_create_workflow`（generator step） | 0-to-1（flag 关闭） | `step_executor.py` 内联 | ❌ **已禁用、payload 坏** |
| `_create_process`（增量） | diff 重部署 | `incremental_executor.py` 内联 | ❌ 同类缺陷 |

`WORKFLOW_STEPS_ENABLED = False`（`generation_steps.py:45`）当年是 commit `951406e` 为了不阻塞部署**直接 flag 关掉**的，payload bug 没修——不是架构问题。坏在哪很具体：`execute_create_workflow` / `process_translator` 的 payload **缺** `processDataSource.objectId = boc_code_{form_id}`（平台靠它知道流程绑哪张表，少了直接 500）、`formId`、`status/engine`、真正可执行的 BPMN（`<userTask>`），审批人还用错了形（`approverCode` 而非角色雪花 ID）。

**唯一验证过的 `_build_process_payload_v2` 才是要复用的积木**，不碰那两条坏路。

## 目标（V1）

0-to-1 链路里，当设计文档描述了审批需求时，自动在 aPaaS 平台创建对应的**线性多级审批流程**：start → 审批节点（可多级，按角色指派审批人）→ end，绑定到一张表单。失败只告警、不阻断核心生成。

## 已验证的 payload 契约（复用的依据）

`_build_process_payload_v2`（`mcp_server.py:5840-5977`）产出的、平台真接受的 payload 形状（抓包验证）：

```python
{
    "appId": app_id,
    "formId": form_id,                      # 表单的平台 ObjectId
    "menuId": menu_id,
    "processName": ..., "processCode": ...,
    "bpmn": bpmn_xml,                        # 真可执行 BPMN（userTask + listeners）
    "status": "ENABLE", "engine": "VERSION_1.1",
    "nodes": nodes, "edges": edges,         # 完整 data 模板（非精简）
    "processGlobalConfig": {...},
    "processDataSource": {                   # ★绑定流程到表，缺它 500
        "sourceType": "SOURCE_TYPE_BO",
        "objectId": f"boc_code_{form_id}",
    },
    "boExist": True, "boRemindExist": True, ...
}
```

关键细节（都已抓包验证）：
- **`processDataSource.objectId = boc_code_{form_id}`** 必填，否则平台不知道流程绑哪张表 → 500。这是坏路缺的最致命字段。
- START/END 节点要带完整 `data`（`_start_node_data`/`_end_node_data`），否则平台 NPE `newData is null`。
- BPMN 要真可执行（`_build_executable_bpmn_xml`：`<userTask>` + assignee + 多实例 loop + 执行监听器），不是 `<startEvent/><endEvent/>` 空壳。
- 审批人形：`{"type": "ROLE", "value": <角色雪花ID>, "displayData": {"id", "label"}}`。`value` 是**角色雪花 ID**（`query_roles` 拿），不是 roleCode。
- builder 的输入是 `stages_with_role = [{name, approver_type, approver_value(角色ID), approver_label}]` —— 正好是一条线性审批链。

## 设计（V1）

### 单元 1：抽共享 payload 模块 `app/process_payload.py`

把 `_build_process_payload_v2` + 它的纯函数 helper（`_start_node_data`、`_end_node_data`、`_approve_node_data_template`、`_process_edge_template`、`_build_executable_bpmn_xml`、`_bpmn_random_id`，`mcp_server.py:5624-5977`）抽到一个无 FastMCP 依赖的新模块 `app/process_payload.py`，导出 `build_process_payload(...)`。`mcp_server.py` 改为从该模块 import（保持 `set_apaas_app_process` 行为逐字不变），`generator_v2` 也 import 同一个。

- **职责**：纯函数，给定 `(app_id, form_id, menu_id, process_name, process_code, stages_with_role)` → 返回平台 payload dict。不发 HTTP、不碰 DB。
- **接口**：`build_process_payload(*, app_id, form_id, menu_id, process_name, process_code, stages_with_role) -> dict`。
- **依赖**：仅标准库 + 现有 helper 的依赖（BPMN 字符串拼装）。
- **护栏**：golden test —— 抽取后对同一组输入产出的 payload 跟抽取前**逐字一致**，保证不破坏在用的 `set_apaas_app_process`。

> 抽取风险点：`_build_process_payload_v2` 若依赖 mcp_server 内的全局/闭包，要一并迁移或显式传参。实现时先把这些纯函数原样剪切到新模块，mcp_server 里换成 import + 跑现有 MCP 路径冒烟。

### 单元 2：文档第 7 章「审批流程」（可选章节）

`doc_spec_standard.py` 的 `STANDARD_DOC_FORMAT` 加第 7 章。**可选**——只在确有审批需求时填，没有就整章省略（不影响现有 6 章评分）。格式：每条流程一个 `###` 小节，标题注明绑定表单编码，节点表按顺序列：

```
## 七、审批流程

> 可选章节。只在确实需要审批/流转时写；审批人**必须**引用「二、角色列表」里已定义的角色编码。

### 7.1 检测报告审批流（绑定表单：test_report）

| 顺序 | 审批节点 | 审批人角色编码 |
|---|---|---|
| 1 | 班组长审批 | role_team_leader |
| 2 | 质量经理审批 | role_quality_mgr |
```

为 V2 预留：节点表**未来**会增一列"进入条件"，V1 解析器遇到该列忽略即可（向后兼容）。

### 单元 3：流程解析器 `doc_parsers/workflows.py`

- **职责**：解析第 7 章文本 → `[{name, form_code, nodes: [{seq, name, role_code}]}]`。
- **接口**：`parse(section_text: str) -> Tuple[List[dict], List[str]]`（与现有 `doc_parsers/models.py` 同款 `(结果, errors)` 签名）。
- 章节缺失/空 → 返回 `([], [])`（合法，多数应用没有审批流）。
- 接进 `doc_standard_parser`：把 hardcode 的 `"workflows": []`（`doc_standard_parser.py:145`）换成调本解析器，使 `config["data"]["workflows"]` 真正带数据。
- `form_code` 不在文档表单列表里 / `role_code` 不在角色列表里 → 记 error（非致命警告），保留能解析的部分。

### 单元 4：generator Phase 5（建流程）

`generator_v2.run_complete_generation` 在 Phase 4（权限）**之后**加 Phase 5（放最后，因为流程是增强、非核心，失败不该阻断已建好的模型/表单/权限）：

```
for wf in data.get("workflows", []):
    # 1. 按 form_code 从 Phase 3 form_results 反查 formId + menuId
    fr = next((f for f in form_results if f.get("formCode") == wf["form_code"]), None)
    若无 → yield {stage:5, warning}; 跳过
    # 2. 每个节点 role_code → 角色雪花ID（用 Phase 1 角色表反查，镜像 set_apaas_app_process）
    stages_with_role = [{name, approver_type:"ROLE", approver_value:role_id, approver_label:role_name} ...]
    跳过解析不到 role_id 的节点（告警）
    # 3. 组 payload（含 processDataSource.objectId = boc_code_{formId}）→ save_process_config
    payload = build_process_payload(app_id, formId, menuId, wf["name"], process_code, stages_with_role)
    await client.save_process_config(payload)
    yield {stage:5, status:running, step: f"流程: {wf['name']}"}
yield {stage:5, status:done, step: f"审批流程完成（N 条）"}
```

- `form_results` 已是 `[{formId, formCode, formName, menuId}]`（`generator_v2.py:1214/1296`，已核实），formId 绑定数据齐。
- Phase 1 角色表已含 `role_code → 角色ID`（`generator_v2.py:1095`，来自 `query_roles`）。
- 每条流程独立 try/except，单条失败只 yield 一个 warning、继续下一条，**绝不 return 中断**（流程是 enhancement）。
- `process_code` 由 `wf` 名/form_code 生成（确定性、ascii）。

### 单元 5：提示词

- `doc_spec_standard.py`：把第 7 章写进标准，标注"可选；有审批/流转需求才填；审批人必须引用第二章角色编码；线性多级，V1 不支持条件分支"。
- `agent.py`（`SYSTEM_PROMPT_UNIFIED` / `_FORMAT_CONSTRAINTS`）：让 agent 识别到材料/对话里的审批需求（如"需要审批""审批流""流转""会签"）时产出第 7 章。正好接上印章 doc 那句被丢的"原始记录和检测报告需要审批流"。

## 测试（V1）

- **golden test**（单元 1）：抽取后 `build_process_payload(...)` 对固定输入产出 payload 跟抽取前逐字一致。
- **parser 单测**（单元 3）：第 7 章 → workflows 列表；可选章节缺失 → 空；多级节点顺序正确；form_code/role_code 不存在 → 告警但不崩。
- **Phase 5 装配单测**（单元 4）：给定 form_results + 角色表 + 解析出的 workflow，mock `save_process_config`，断言传入 payload 的 `processDataSource.objectId == boc_code_{formId}`、审批人 `value` 是角色 ID（非 code）、节点顺序/数量正确；单条失败不中断其余。
- **真平台建流程**：没法单测（需平台），跟印章 doc 一样上线后实测一条端到端。

## 风险与处理（V1）

1. **formId → `boc_code_{form_id}` 绑定**（最致命）：已核实 `form_results` 带 `formId`，Phase 5 按 `formCode` 反查后传入 builder。
2. **审批人 = 角色 ID 不是 code**：镜像 `set_apaas_app_process` 的 `query_roles` 反查（`mcp_server.py:6067-6116`）；Phase 1 角色表已有 id。
3. **可选第 7 章不能拉低现有 6 章评分**：加章节后跑 `doc_standard_detector` 确认 6 章评分不变（detector 只校 6 章；额外章节应被忽略）。
4. **抽取破坏在用的 MCP 工具**：golden test + 抽完跑 `set_apaas_app_process` 冒烟。
5. **`menuId` vs `formId` 语义**：builder 需要两者，`form_results` 都有，直接透传。

## V2（条件分支 — 设计，后续开发）

> 不在 V1 实现。V1 的数据模型/parser/Phase 5 故意预留扩展位，V2 是加法不是重构。

### V2-a 条件节点（准入条件）
最常见的"金额大于 X 才要高层审批"。文档节点表加一列"进入条件"，引用绑定表单的字段编码：

```
| 顺序 | 审批节点 | 审批人角色编码 | 进入条件 |
|---|---|---|---|
| 1 | 部门经理审批 | role_dept_mgr |  |
| 2 | 总经理审批 | role_ceo | amount > 10000 |
```

含义：该节点仅当条件成立才执行，否则跳到下一节点。数据模型：node 加可选 `condition: {field_code, op, value}`（op ∈ `> < = != >= <= contains`，value 常量）。V1 解析器遇到"进入条件"列**忽略**，V2 填上。

### V2-b 条件网关（真二选一分支）
A 路 / B 路二选一再汇合，引入"条件网关"节点：一个 gateway 多条出边、每边一个条件、最后汇合。文档格式（草案）：

```
### 网关：按金额分流（绑定表单：expense_apply）
- amount > 10000 → 总经理审批(role_ceo) → 财务复核(role_finance)
- else → 财务复核(role_finance)
```

### V2 的真风险点：gateway payload 未验证
现有验证过的 `build_process_payload` **只会线性链**。aPaaS 条件分支要 BPMN 里的 `exclusiveGateway` 节点 + 边上的 `conditionExpression`，这块**没有抓包验证过的样板**。

**V2 第一步必须先抓包验证**：在 ProcessDesigner 里手画一个条件分支流程、抓它的 `/xdap-app/process/save/processConfig` save 请求，拿到 gateway 节点的 `data` 模板、边的条件表达式格式、条件如何引用表单字段。验证出格式后，再给 `build_process_payload` 加一个 branching 变体（保持线性变体不动）。

`process_translator.py` 声称支持 24 种节点类型 + gateway，可作为格式参考来源，但**它的 payload 同样缺 `processDataSource`/formId、未验证**，不能直接拿来当 V2 的 builder —— 只能参考它的拓扑/节点类型枚举。

### V2 解析器/管线扩展
- parser：解析"进入条件"列 → node.condition；解析网关小节 → gateway 节点 + 带条件的边。
- Phase 5：把 condition/gateway 翻成 BPMN conditionExpression（依赖上面抓包验证的格式）。

## 不在范围（V1 + V2 都先不做）
- 会签（一个节点多人/多角色同时审批，按比例通过）。
- 非角色审批人（指定具体人 / 上级 / 部门负责人 / 表单字段指定人）。
- 抄送、超时自动流转、定时器节点、外部消息节点。
- 修改/删除已创建的流程（0-to-1 只管创建；改流程走现有 ProcessDesigner / update 路径）。
- 清理那两条坏路（`execute_create_workflow` / `process_translator` / `WORKFLOW_STEPS` flag）—— 与本功能解耦，可单独评估是否删除。

## 开放问题
- `process_code` 生成规则：用 form_code + 流程名 hash？还是平台自动分配？实现时确认 builder 是否需要调用方给 processCode（看 `_build_process_payload_v2` 现有签名）。
- 多条流程绑同一张表单是否允许？（V1 假设一表单一流程；多流程先不支持，parser 遇到重复 form_code 告警取第一条。）
