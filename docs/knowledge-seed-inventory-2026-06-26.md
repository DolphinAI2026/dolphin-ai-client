# 现有「搭建/二次开发」规范盘点 — 知识库种子输入

> 日期：2026-06-26  
> 目标：找出散落在代码里的规范文本，判断哪些可以搬进平台知识库（可搬），哪些是工程接线（留代码），哪些是待用户提供的占位。  
> 供 Task 9（种子写入）直接用。

---

## 总体结论

扫描范围：`backend/app/agents/profile.py`、`backend/app/coding/prompts.py`、`backend/app/agents/coding/prompts.py`、`backend/app/coding/pipeline.py`（brainstorm 提示词）、`backend/app/coding/default_rules/*.mdc`、`docs/research-apaas-event-python-spec-2026-06-05.md`。

**核心发现**：现有提示词绝大多数是「域规范 + 工程约束混写」，不是纯分离的领域文档。真正可以移出去当独立 KB entry 的只有几块；其余或绑引擎行为，或太依赖上下文变量，搬了也无法独立 serve。

汇总：**可搬 5 | 留代码 7 | 占位 1**

---

## 候选清单

### C1 — df-sdk API 速查（全局 `window.df`）

| 项 | 内容 |
|---|---|
| 出处 | `backend/app/coding/prompts.py:42-49`（`AGENT_SYSTEM_PROMPT` §df-sdk 段）；`backend/app/coding/default_rules/前端SDK-v2介绍.mdc`（完整文档） |
| 规范主题 | df.getVue / df.getRouter / df.getStore / df.getEnv / $request / openFormModal / showToast 等平台全局 API |
| 建议 slug | `platform/df-sdk-api` |
| 建议 category | 平台规范 |
| **判定** | **可搬** — 这是平台 SDK 的客观事实，与引擎行为无关，完全可以作为独立 KB 条目维护；`前端SDK-v2介绍.mdc` 已有完整文档，直接搬 |
| 搬后处理 | `AGENT_SYSTEM_PROMPT` §df-sdk 段（prompts.py:42-49）可替换为 `{{platform/df-sdk-api}}` 注入占位，或保留精简版（仅 2-3 行摘要）；`.mdc` 文件可保留作 workspace-level cursor rules（它们是给老 VibeCodingAgent 用的，需确认 CodingAgent 是否还读） |

---

### C2 — formValue 存储规范

| 项 | 内容 |
|---|---|
| 出处 | `backend/app/agents/coding/prompts.py:341-348`（`_SHARED_FORMVALUE_STORAGE_SECTION`） |
| 规范主题 | formValue 只接受基本类型；复杂类型须 JSON.stringify；mounted 时 JSON.parse；handleChange 写回 formValue |
| 建议 slug | `二次开发/form-component-formvalue-storage` |
| 建议 category | 二次开发 |
| **判定** | **可搬** — 纯领域规范，描述平台数据持久化契约，无引擎变量 |
| 搬后处理 | `_SHARED_FORMVALUE_STORAGE_SECTION` 常量可改为从 KB 注入（Task 9 接入后），或保留常量但在 KB 中同步维护权威版本；prompt 里对应段保留一句话摘要即可 |

---

### C3 — formEngine API 白名单

| 项 | 内容 |
|---|---|
| 出处 | `backend/app/agents/coding/prompts.py:350-392`（`_SHARED_FORMENGINE_API_SECTION`） |
| 规范主题 | formEngine 的合法属性/方法（白名单）及臆想方法（黑名单 + 正确替代） |
| 建议 slug | `二次开发/form-engine-api-whitelist` |
| 建议 category | 二次开发 |
| **判定** | **可搬** — 描述平台运行时 API 事实，无引擎控制变量。是 LLM 最容易幻觉的地方，独立维护 KB 比散在 prompt 里更容易更新 |
| 搬后处理 | `_SHARED_FORMENGINE_API_SECTION` 常量可改为 KB 注入；prompt 里对应段可替换为 KB 引用 |

---

### C4 — aPaaS 后端接口规范（SpringBoot，包名/路径约定）

| 项 | 内容 |
|---|---|
| 出处 | `backend/app/coding/pipeline.py:824-875`（`_BRAINSTORM_PROMPT_BACKEND_API`）；`backend/app/agents/coding/prompts.py` `_WORKFLOW_BACKEND_API` 段（`/custom` 前缀，`com.xdap` 包名）；`backend/app/coding/workspace.py:4869,5054`（scaffold 代码里的 `@ComponentScan({"com.definesys.mpaas","com.xdap.*"})` 约定） |
| 规范主题 | 后端自开发接口路径以 `/custom` 开头；包名 `com.xdap`；`@ComponentScan` 扫描 `com.definesys.mpaas` + `com.xdap.*`；得帆私有 Maven 源 `registry.dfy.definesys.cn/repository/maven-public/` |
| 建议 slug | `二次开发/backend-api-conventions` |
| 建议 category | 二次开发 |
| **判定** | **可搬**（部分）— 路径/包名/Maven 源是平台约定事实，可独立维护；但 BRAINSTORM_PROMPT 里的 SPEC 输出模板格式（§参数表/§响应结构）是引擎输出约定，应留代码 |
| 搬后处理 | 只抽路径/包名/Maven 源约定进 KB；SPEC 输出模板留在 `_BRAINSTORM_PROMPT_BACKEND_API` 中 |

---

### C5 — aPaaS npm 私有源 + 技术栈约定（前端）

| 项 | 内容 |
|---|---|
| 出处 | `backend/app/coding/prompts.py:38`（`AGENT_SYSTEM_PROMPT` §通用技术规范）；`backend/app/coding/workspace.py:407`（`APAAS_PRIVATE_NPM_REGISTRY_FALLBACK`） |
| 规范主题 | 得帆私有 npm 源 URL；Vue 2.7；Element UI 全局注册无需 import；`$dayjs`/`$lodash`；`console.info` 代替 `console.log` |
| 建议 slug | `二次开发/frontend-tech-stack` |
| 建议 category | 二次开发 |
| **判定** | **可搬** — 平台约定事实，与引擎无关 |
| 搬后处理 | `AGENT_SYSTEM_PROMPT` §通用技术规范段可改为 KB 引用；`APAAS_PRIVATE_NPM_REGISTRY_FALLBACK` 常量保留（它是运行时回退值，不是文档） |

---

### C6 — definesys Python 读侧契约（`definesys.input()` + afterFormData/afterTableData）

| 项 | 内容 |
|---|---|
| 出处 | `docs/research-apaas-event-python-spec-2026-06-05.md`（§1-§2）；`backend/app/mcp_server.py::create_form_event_with_python_code`（docstring 目前未含此规范——是 gap） |
| 规范主题 | 业务事件自定义节点 Python 契约：`def invoke():` + `definesys.input()` 取 `customNodeData[0]['afterFormData'][<uuid>]`（主表）/ `afterTableData[<uuid>]`（子表）；返回合法 JSON |
| 建议 slug | `平台规范/apaas-event-python-read-contract` |
| 建议 category | 平台规范 |
| **判定** | **占位（status=draft）** — 读侧规范已调研清楚（见研究文档 §1-§2），可直接写入 KB；但写侧 SDK（definesys.create/update）在平台 AI prompt 库和帮助文档中均未找到，属于「仓库内无权威来源」。**当前只能写读侧 seed，写侧留 draft 占位，等用户提供 definesys 写 SDK 文档后补充。** KB entry 需标注「写侧未决」 |
| 搬后处理 | 在 KB 中建 `apaas-event-python-read-contract`，内容来自研究文档 §1-§2；写侧单独建 `apaas-event-python-write-sdk`（status=draft，body=「待用户提供 definesys 写 API 文档」）；`create_form_event_with_python_code` docstring 更新引用读侧规范（Gap 修复，Task 9 或后续轮） |

---

### 留代码项

以下候选**不适合搬进 KB**，原因逐一说明：

| # | 出处 | 主题 | 留代码原因 |
|---|---|---|---|
| L1 | `profile.py:83-93`（`_DEV_APAAS_SYSTEM_PROMPT`） | 「确认即开干」行为规则 + ws_id 约定 | 全是引擎行为控制（即开干/最多问一次/绑 ws_id/不部署不重建），是 agent 的工作方式定义，不是领域知识；搬出去 agent 就丧失这段行为约束 |
| L2 | `profile.py:117-141`（`_WS_LOCK_DROP_TOOLS` + `_WS_LOCK_DROP_APP_TOOLS`）| 工作区锁定时砍掉的工具集 | 纯工程接线：哪些工具在 code 模式下不暴露，由代码决定，KB 管不了 |
| L3 | `profile.py:179-184`（`ws_bind_view_context`）| 单工作区锁定硬性约束文本 | 含运行时变量 `ws_id`，是注入到 context 的约束字符串，不是静态规范 |
| L4 | `pipeline.py:629-711`（`_BRAINSTORM_PROMPT_FORM_COMPONENT`）、`:713-774`（PAGE）、`:776-821`（LIST）、`:823-875`（BACKEND_API`）| brainstorm SPEC 输出模板 | 是「LLM 应该按什么格式输出 SPEC」的结构约束，属于引擎协议（上游产出格式 → 下游 codegen 解析），不是面向用户维护的领域规范。改格式=改引擎，必须留代码 |
| L5 | `pipeline.py:885-920`（`_BRAINSTORM_REVISION_PROMPT`）| 修改 SPEC 的元约束 | 同上，LLM 行为指令，非领域知识 |
| L6 | `agents/coding/prompts.py:20-84`（`_SHARED_WIDGET_CONFIG_SECTION`）| widget.config.json 字段规范 | 内容一半是领域规范（componentModelField/BOF_TEXT 对应关系），一半是工程约束（edit_file 不 write_file / excludeInTable 只填 WIDTH / 模板路径变量 `__WIDGET_CONFIG_TEMPLATE_PATH__`）。两者深度混写，且含 `__xxx__` 模板变量由 `render_form_component_sections()` 运行时替换 → **不能整体搬**。componentModelField/BOF 类型对应关系那一张表单独抽出来可搬（≈ C2 延伸），但其余工程约束留代码 |
| L7 | `agents/coding/prompts.py:86-103`（`_SHARED_EDITOR_CONFIG_SECTION`）和 `:106-338`（`_SHARED_SETTING_VUE_SECTION`） | editor.config.json 格式 + setting.vue 铁则 | 是平台脚手架的文件结构约定，但与引擎工作流（何时写/如何注册/路径变量）深度耦合，且被 `render_form_component_sections()` 做路径替换。**componentModelField/BOF 类型对应表**（prompts.py:69-79）可单独抽为 KB；其余注册流程、路径铁则留代码 |

---

## 可搬条目一览（给 Task 9 的快速清单）

| slug | category | 出处（主） | 搬入后 prompt 处理 |
|---|---|---|---|
| `platform/df-sdk-api` | 平台规范 | `prompts.py:42-49` + `前端SDK-v2介绍.mdc` | prompts.py 该段简化为 1-2 行摘要或 KB 引用 |
| `二次开发/form-component-formvalue-storage` | 二次开发 | `agents/coding/prompts.py:341-348` | 常量保留，KB 为权威；或改为 KB 注入 |
| `二次开发/form-engine-api-whitelist` | 二次开发 | `agents/coding/prompts.py:350-392` | 同上；白名单/黑名单表格易变，KB 更好维护 |
| `二次开发/backend-api-conventions` | 二次开发 | `pipeline.py:824-875` + `workspace.py:4869` | 只抽路径/包名/Maven 源片段；SPEC 模板留代码 |
| `二次开发/frontend-tech-stack` | 二次开发 | `prompts.py:35-49` + `workspace.py:407` | prompts.py 该段可引用 KB，REGISTRY 常量留代码 |
| `平台规范/apaas-event-python-read-contract` *(draft 占位)* | 平台规范 | `docs/research-apaas-event-python-spec-2026-06-05.md §1-§2` | 读侧已清楚可入 KB；写侧单独 draft 占位待用户提供文档 |

---

## 可搬可行性评估（给 Task 9 的诚实判断）

- **可搬的 5 条**中，C1（df-sdk）和 C6（definesys 读侧）是最有价值的：C1 文档已存在（.mdc 可直接转），C6 研究文档已整理好内容，conversion 工作量小。
- C2/C3（formValue/formEngine）是真正的防幻觉高频规范，搬进 KB 后便于单独迭代更新，不用改 prompts.py 常量，值得做。
- C4/C5（后端/前端约定）是轻量事实，搬入价值一般但成本很低。
- **definesys 写 SDK（C6 写侧）是硬卡点**：仓库内真的没有权威来源，只能建占位 draft，等用户提供文档。
- **BRAINSTORM 输出格式模板（L4/L5）绝对不能动**：它是引擎协议的核心，改格式要同步改 codegen 解析逻辑，必须留代码。
- **大量 setting.vue / widget.config.json 铁则（L6/L7）**：内容本身是领域知识，但因模板变量替换机制（`__BASE_PATH__` 等）与运行时深度耦合，整体搬入不可行；可按「领域事实 vs 工程约束」细拆，但 Task 9 应谨慎评估拆分成本是否值得。
