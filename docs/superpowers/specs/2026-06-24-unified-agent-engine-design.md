# 统一智能体引擎设计(Unified Agent Engine)

日期:2026-06-24
状态:设计已与用户确认,待 writing-plans 出实施计划
作者:大明哥 + Claude(brainstorming)

## 1. 背景与问题

睿鲸 AI 的 coding 能力当前「根本没法用」。根因是架构,不是模型:

- **Code 标签 = coding 流水线**:`run_coding_pipeline` 是一条 ~750 行的过程式 async generator([backend/app/coding/pipeline.py:1656](../../../backend/app/coding/pipeline.py)),在真正写代码前要过一连串 LLM 闸门——`classify_coding_intent` / `classify_iteration_intent`([read_query.py:141/268](../../../backend/app/coding/read_query.py))、硬性 `detect_scene`、标记态 brainstorm/澄清状态机。一条「首轮+绑定应用+要澄清」的消息,写第一行代码前要过 3 个分类器,下一轮确认再 2 个。
  - 直接症状:用户在已有工作区说「改一下」,被 `classify_iteration_intent` 误判 READ,锁进只读路径拒绝改代码(2026-06-24 已临时止血,见 §9)。
- **Builder 标签 = `run_agent`**([ai_chat/agent.py:754](../../../backend/app/ai_chat/agent.py)),用户实测它做二次开发明显比 Code 标签好。原因:它**没有前置闸门**,消息直奔 agent 循环;工具集是 `builder ∪ coding ∪ config` 的并集(~85)+ MCP([ai_chat/tools.py:1563](../../../backend/app/ai_chat/tools.py)),手里同时握读+写+跑+aPaaS MCP,模型自己决定先读后写。

并存的还有第三/第四套手写循环:`SpecAgent`(builder_spec,只改结构化 Spec、不写代码,[builder_spec/agent.py:441](../../../backend/app/builder_spec/agent.py))和 `read_query` 只读循环([read_query.py:761](../../../backend/app/coding/read_query.py))。

**现状真相:后端有 4 个各自手写的 agent 循环,只有 1 个(CodingAgent)用了 BaseAgent。** 外加 3 套工具来源(`tool_registry.yaml`、`harness/tool_registry.py`、coding 硬编码),那个号称「单一真相源」的 yaml,build agent 根本不读。

### 为什么 builder/run_agent 写得比 coding 好(关键结论)

不是 agent 更聪明,而是:① 直奔循环、**无前置闸门**(没有「改一下」那类误路由);② **全集工具 + MCP**,读写在同一循环;③ 提示词与动作空间更克制。对照之下,coding 的代码质量还受一份 ~63KB 易碎提示词([agents/coding/prompts.py:728](../../../backend/app/agents/coding/prompts.py))拖累(逐字段格式规则,凭空吐 Vue+JSON 由黑盒平台校验器判生死)。

补充经验(来自 SpecAgent/generator_v2):**结构化、受校验的输出 + 确定性 applier**,天然比「LLM 自由写代码」可靠——`generator_v2` 读平台做「复用 vs 新建」归一([generator_v2.py:1412](../../../backend/app/generator_v2.py)),脏活由确定性代码扛,不是 LLM grounding。这条经验用于重塑 code 场景的「问题形状」。

## 2. 目标与非目标

### 目标
- **一套智能体引擎**:唯一循环内核 = `BaseAgent`([backend/app/agents/base.py:204](../../../backend/app/agents/base.py))。
- 场景差异全部外置为 **`AgentProfile`**(提示词 / 工具白名单 / skill 包 / MCP 集 / max_turns / 确定性钩子)。
- 砍掉所有前置 LLM 闸门,**让模型自己决定读/写/问**。
- 把 `run_agent`、`read_query`、`SpecAgent` 三个手写循环全部**收编**成 BaseAgent + profile。
- 保留 coding 流水线里真正有价值的**确定性环节**(autofix / 脚手架 / 契约校验),改挂为 profile 钩子。
- 修复上下文处理(喂真实历史、压缩、附件进上下文)。
- 优先级:**低代码二次开发(`dev-apaas`)先做**;全代码次之。

### 非目标
- 不重写 LLM 网关 / transport。
- 不改 aPaaS 平台侧协议。
- 本轮不追求全代码场景完备(留 Phase 4)。
- 不做与本目标无关的重构。

## 3. 关键决策(已与用户确认)

1. **一个引擎、砍前置闸门、模型自己决策**;场景 = skill 包 + MCP + 工具白名单。
2. **二次开发优先**;aPaaS 只读 MCP + 平台规范作为该场景的 skill 包。
3. **仍需要写真代码**——删的是 coding 现在的「写法」(闸门 + 63KB 提示词 + 裸写),不是「写代码」这个能力;code 场景按 builder 范式重建。
4. **内核 = BaseAgent**(机制最全:hooks / 暂停恢复 / 重试 / 上下文压缩 / 可观测);`run_agent` 的「形状」(无闸门 + 全集工具 + MCP + skill)搬上去;三个手写循环都收编成 profile。
5. 不能跟着 coding 一起删的**确定性价值**:autofix、脚手架、workspace 契约、暂停/恢复。

## 4. 架构设计

### 4.1 引擎:BaseAgent(唯一循环)

`BaseAgent.run` 是唯一的 tool-calling 循环,保留并复用它已有的:13 个 hook、pause/resume 快照、并行工具执行、重试退避、上下文溢出压缩、observability recorder。`CodingAgent` 已经是它的子类,作为迁移的事实基线。

### 4.2 `AgentProfile`(场景配置对象)

```
AgentProfile:
  name                 # 场景名
  system_prompt        # 瘦人设 + 场景要点(不再塞 63KB 格式规则)
  tool_whitelist       # 工具名,从【唯一】注册表解析
  skill_pack           # 平台规范/约定 = 可加载 skill(不烤进提示词)
  mcp_set              # 挂哪些 MCP
  max_turns
  hooks:               # 确定性环节,挂成 profile 钩子
    pre_run            #   - 脚手架挑选/创建(新建工作区时)
    post_run           #   - autofix 自愈环(build→抓错→回灌修→再跑)
    finalize           #   - workspace 契约校验
  event_mapping        # 前端工具卡映射
```

引擎对 profile 无知:它只消费 `AgentProfile` 字段,profile 决定「这是什么场景」。

### 4.3 控制流(取代 ~750 行闸门)

```
请求 → 选 profile → (pre_run 钩子:必要时建/挑脚手架) → BaseAgent.run(profile)
     → (post_run 钩子:autofix) → (finalize 钩子:契约校验) → 收尾
```

无 `classify_*intent`、无硬 `detect_scene` 门、无标记态状态机。读=模型挂只读工具子集时自己不写;问=模型自己回答。

## 5. Profile 清单(初始)

- **`dev-apaas`(二次开发,先做)**:全集工具(读+写+跑+aPaaS MCP)、无闸门、skill 包 = aPaaS 自开发包约定、钩子 = 脚手架 + autofix + 契约。**同时取代今天 Code 标签和 Builder 标签的写代码行为。** 按 builder 范式:自开发包里结构已知的部分(`widget.config.json` / `editor.config.json` / 7 个 scene 脚手架)优先用脚手架 + 定向 `edit` 或受校验工具,少让 LLM 凭空吐 JSON;瘦提示词 + skill 包替代 63KB。
- **`builder-config`(后做)**:SpecAgent 的 22 个结构化 spec 工具收编成工具集/profile,继续走「结构化 spec → `spec_to_config` / `generator_v2` 确定性 applier」。
- **`dev-fullcode`(全代码,后做)**:纯仓库,砍掉 aPaaS 专属工具/脚手架/契约。

## 6. 删除清单 / 保留清单

### 删(纯负债)
- coding 流水线闸门:`classify_coding_intent`、`classify_iteration_intent`、硬性 `detect_scene` 门、标记态 brainstorm/澄清状态机([pipeline.py](../../../backend/app/coding/pipeline.py) 相关段)。
- `read_query` 手写循环 + READ/BUILD 分类器([read_query.py:761](../../../backend/app/coding/read_query.py))。
- `run_agent`、`SpecAgent` 两个手写循环(收编进 BaseAgent,保留各自工具)。
- 3 套工具来源 → 1 套:以 `tool_registry.yaml` 为唯一真相源,把 coding 硬编码 7 工具登记进去,删掉 `harness/tool_registry.py` 对 coding 形同虚设的 filter。

### 留(确定性价值,搬成 profile 钩子)
- autofix 自愈环 + signals([autofix_driver.py:60](../../../backend/app/agents/coding/autofix_driver.py) / [autofix_signals.py:18](../../../backend/app/agents/coding/autofix_signals.py))→ `dev-apaas` post_run 钩子。
- 脚手架模板(`CLI_TEMPLATE_MAP`,[workspace.py:614](../../../backend/app/coding/workspace.py))→ pre_run 钩子。
- workspace 契约校验 → finalize 钩子。
- `spec_to_config` / `generator_v2` 确定性 applier → `builder-config` 复用。
- BaseAgent 自带暂停/恢复 + 上下文压缩 → 白捡。

## 7. 上下文处理修复

- 跨轮喂**最近若干轮原文**,替换当前 codegen 首条 prompt 的「6 行历史摘要」([prompts.py:728](../../../backend/app/agents/coding/prompts.py))。
- 溢出走 BaseAgent 既有压缩。
- 附件(图/文件)进模型上下文。

## 8. 分阶段实施

- **Phase 0**:统一工具注册表(低风险铺垫)。把 coding 基础工具登记进 yaml;删掉 harness 死 filter。
- **Phase 1**:把 `run_agent` 搬到 BaseAgent + `dev-apaas` profile——保留它现在好用的行为(全集工具/MCP/无闸门),白捡 BaseAgent 机制。Builder 标签即刻跑在统一引擎上。← 二次开发先变扎实。
- **Phase 2**:把 coding 的 autofix/脚手架/契约 接成 `dev-apaas` 钩子;**退役整条 coding 流水线 + Code 标签 + 闸门 + read_query**。← 删代码最多、消灭 bug 类。
- **Phase 3**:SpecAgent 收编成 `builder-config` profile。
- **Phase 4**:`dev-fullcode` profile + 上下文处理收尾。

每个 Phase 自己能跑、能验、能回滚,不一次性爆改。

## 9. 风险与回滚

- **主链路改动**:`run_agent` / coding 流水线都是 load-bearing。每 Phase 独立可回滚;Phase 1 与旧 coding 流水线并存,验证通过再做 Phase 2 退役。
- **临时止血会被取代**:2026-06-24 对 `classify_iteration_intent` 的「改一下」修复,只是 Phase 2 删闸门前的止血;闸门删除后该补丁自然作废(届时连同分类器一并移除)。
- **行为回归**:每 Phase 配测试;尤其 Phase 1 要覆盖 Builder 现有「读→写→build」链路不退化。
- **桌面打包**:后端改动需重建 sidecar 才进桌面 app(本地 dev `:8000` 仅供 web 验证)。

## 10. 验收标准

- 在已有工作区说「改一下」→ 直接改代码(不再只读)。
- Code 与 Builder 两种二次开发体验合一,跑在同一引擎。
- 新增/修改 agent 场景 = 加/改一个 `AgentProfile`,不碰引擎。
- 后端只剩一个 agent 循环;只剩一套工具注册表。
- autofix / 脚手架 / 契约 / 暂停恢复 在 `dev-apaas` 下仍生效。

## 11. 现状证据(grounding)

- 引擎:[agents/base.py:204](../../../backend/app/agents/base.py)(BaseAgent.run);[agents/coding/agent.py:126](../../../backend/app/agents/coding/agent.py)(CodingAgent 已是子类)。
- coding 流水线/闸门:[coding/pipeline.py:1656/1633](../../../backend/app/coding/pipeline.py)。
- 意图分类器/只读循环:[coding/read_query.py:141/268/761](../../../backend/app/coding/read_query.py)。
- Builder=run_agent + 工具并集:[ai_chat/agent.py:754](../../../backend/app/ai_chat/agent.py);[ai_chat/tools.py:1563](../../../backend/app/ai_chat/tools.py);workspace 工具 [mcp_tools/workspace_core.py:166](../../../backend/app/mcp_tools/workspace_core.py)。
- SpecAgent(结构化、无代码):[builder_spec/agent.py:441](../../../backend/app/builder_spec/agent.py);[builder_spec/tools.py:38](../../../backend/app/builder_spec/tools.py);[converter.py](../../../backend/app/builder_spec/converter.py);[generator_v2.py:1412](../../../backend/app/generator_v2.py)。
- autofix/脚手架:[autofix_driver.py:60](../../../backend/app/agents/coding/autofix_driver.py);[workspace.py:614](../../../backend/app/coding/workspace.py)。
- 工具注册表:[tool_registry.py:115](../../../backend/app/tool_registry.py);[harness/tool_registry.py:9](../../../backend/app/harness/tool_registry.py)。
