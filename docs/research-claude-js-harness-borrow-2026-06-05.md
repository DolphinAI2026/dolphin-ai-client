# 借鉴 claude-js(逆向版 Claude Code)harness + 工具 → ai-builder run_agent

> 调研日期 2026-06-05。来源:`claude-code-best/claude-code`(自述「逆向工程的 Anthropic Claude Code CLI」,`claude-js` v1.0.2,Bun/TS,本地在 `Vibe Coding/Claude/claude-code`)。
> 目的:提取它 harness 的**机制/模式**,用我们自己的 Python 重写借鉴进 `backend/app/ai_chat/agent.py` 的 `run_agent`。**不照搬逆向代码**(IP 不干净 + 它是 TS/Anthropic API,我们是 Python/OpenAI 兼容网关)。

## 先认清前提差异(决定哪些能直接借、哪些得改写)
- **它跑 Anthropic API,我们跑 OpenAI 兼容网关(omnigate gpt-5.5)**。它很多优雅设计依赖 Anthropic 独有特性:`tool_reference` beta 块、`cache_edits`(改 KV 缓存)、prompt cache `cache_control`。**这些我们没有,得用「每轮重建 tools 数组 / 自己截断重发」模拟。**
- **我们 `run_agent` 现状**:`_run_agent_inner` 单 `for turn in range(MAX_TURNS=25)` 循环;`get_all_tool_schemas()` 把 ~85 工具 schema **每轮全量内联**发;`execute_tool` 串行执行(无并行);工具结果粗暴截断;有 app-context 注入 + app 锁 + 护栏 + trace;**没有** 上下文压缩 / 延迟工具 / 子 agent(v2 orchestrator 已删)/ hooks / 一等 skills。
- 已部分有的:异步后台任务(`command_runs.py` + run_workspace_command async)、业务错 `error_code` dict、save_config_skill(自学习 skill 雏形)、edit 红绿 diff。

## 借鉴清单(按对我们的价值排序)

### 1. 延迟工具 + ToolSearch(最高价值,直击我们痛点)
- **它怎么做**:工具标 `defer_loading:true` → 只把名字+一句话放系统提示;模型先调 `ToolSearchTool(query)`(支持 `select:名字` 或关键词打分搜),返回 `tool_reference` 块让 API 就地展开 schema。`searchHint` 字段补名字里没有的词。压缩时把已发现工具名快照进 `compactMetadata` 续命。
- **我们现状**:~85 工具 schema **每轮内联**(~10–30k token/轮 + 注意力稀释,这次会话已实测吐槽过)。
- **映射(OpenAI 网关,无 tool_reference)**:系统提示放「工具名 + 一句话 + searchHint」清单;`tools` 数组里**只常驻一个** `search_tools(query)` + 少量核心工具;模型调 search_tools → 后端把命中的工具 schema **加进后续轮的 `tools` 数组**(per-call 重建)+ 记进会话状态(跨轮/压缩存活)。
- **价值/工效**:价值★★★★★ / 工效中。**建议第一个做** —— 它直接解决「全并 ~85」的 token+发散问题,且我们本来就因为全并选了它。

### 2. 三级上下文压缩(snip → microcompact → autocompact)
- **它怎么做**:每次 API 调用前级联:① snip 选择性删老 tool-result;② microcompact 把除最近 N 个外的可压缩工具结果**就地清内容**(不调 LLM);③ autocompact:token 超 `窗口-13k` 时**另起一次 LLM** 把前文总结成摘要替换,带熔断(连续 3 次失败停)。还有 413 `prompt_too_long` 的**反应式压缩**(报错后补压再续)。压缩边界用 `compactMetadata.preservedSegment` 续接。
- **我们现状**:`run_agent` **没有任何压缩**。长配置会话 / 大 SPEC 注入 → 直接撑爆窗口或被网关截。
- **映射**:写个 `shrink_messages()`:先把老的 tool result content 置空(便宜),还超就调一次 LLM 出摘要替换前文;413 时反应式补压再 retry。无 cache_edits,就纯内容改写。
- **价值/工效**:价值★★★★☆ / 工效中。长会话稳定性刚需。

### 3. 大工具结果落盘 + 稳定预览(frozen-by-id)
- **它怎么做**:结果超 `maxResultSizeChars` → 写 `tool-results/<id>.txt`,消息里换成 `<persisted-output>` + 2KB 预览。**关键**:换不换的决定**按 tool_use_id 冻结、永不改**(保 prompt cache 前缀稳定)。
- **我们现状**:粗暴截断(UI 600 / read_attachment 30k),大 schema dump(如 list_apaas_app_models)直接糊进上下文。
- **映射**:`@tool_result_budget` 装饰器:超阈值落盘(或落 `result_text` LONGTEXT 已有)+ 返回预览 + 引用 id;按 id 记「已截断」决定,跨轮重发同一截断内容。模型要全文再显式读。
- **价值/工效**:价值★★★★☆ / 工效低-中。

### 4. 工具作用域 = 显式 Set 常量(不是 prompt 里靠模型自觉)
- **它怎么做**:`ALL_AGENT_DISALLOWED_TOOLS` / `ASYNC_AGENT_ALLOWED_TOOLS` / coordinator 只给 `{AgentTool,...}` 等**模块级字面 Set**,`resolveAgentTools()` spawn 时套用。安全属性**静态可审计**。
- **我们现状**:tool_registry 按 `agents:` 标签 + 这次的 app_context 过滤,散在 yaml + 代码;护栏靠注入 app_id。
- **映射**:把「app 锁定态工具集」「(未来)codegen 子 agent 工具集」「只读态」写成 Python 字面 set + 一个 `resolve_tools(mode)`。把这次硬排除 browser_* 那段也并进去。
- **价值/工效**:价值★★★☆☆ / 工效低。清爽 + 为子 agent 铺路。

### 5. validateInput 返回类型化 error_code + 写前「读过且未变」护栏
- **它怎么做**:工具 `validateInput()` 在 schema parse 后、权限检查前跑,返回 `{result:false, message, errorCode:数字}`。FileEdit 写前校验:该文件本会话读过 + mtime 未变 + old_string 唯一(多处匹配要求补上下文)。
- **我们现状**:有 business_error `error_code` dict(部分);edit 红绿 diff;但没有「写前确认读过 + 版本未变」的护栏。
- **映射**:`edit_artifact`/`update_apaas_*` 写前:查本会话是否 read 过该 artifact/模型 + revision/etag 未变;`validate_input()` 返回 `{ok:false, error_code, message}`,机读、可埋点。防并发覆盖。
- **价值/工效**:价值★★★☆☆ / 工效低-中。codegen/配置写入正确性。

### 6. 只读工具并行执行(isConcurrencySafe)
- **它怎么做**:每个工具声明 `isConcurrencySafe()`;只读的(read/grep/glob/fetch)批量并发(默认 10),改写的串行;Bash 错了 `abort` 同批兄弟。还有 StreamingToolExecutor:工具块一到就开跑、与模型生成重叠。
- **我们现状**:`execute_tool` 全串行。一轮多个 list_apaas_* 读 = 顺序等。
- **映射**:工具加 `is_concurrency_safe` 标;`execute_tool` 批量里只读的 `asyncio.gather` 并发,改写的串行。
- **价值/工效**:价值★★★☆☆ / 工效中。多读场景提速。

### 7. PreToolUse hooks(能改写入参 / allow-deny-ask)
- **它怎么做**:`PreToolUse` hook 收 `{tool_name, tool_input}`,可返回 `updatedInput` 改写、`allow/deny/ask`、注 `additionalContext`。横切逻辑(脱敏、加默认)从每个工具 call() 里抽出来。
- **我们现状**:无 hook 层;横切逻辑(如 apaas 保留字段 approver_id 双层防御)硬写在工具里。
- **映射**:`execute_tool` 前过一串 `pre_tool_hooks(name, args) -> args|deny`。先内置几个(注 app_id 护栏其实就是个 hook、保留字段脱敏)。
- **价值/工效**:价值★★☆☆☆ / 工效中。扩展性,非急需。

## 暂不借 / 谨慎
- **Anthropic API 专属**:`tool_reference` 原生展开、`cache_edits` 改 KV、prompt cache cache_control、model fallback tombstones —— 网关不支持,别照搬(延迟工具/压缩按上面的「映射」改写版做)。
- **子 agent / coordinator / swarms / teams**:我们刚**删了** v2 orchestrator(memory `agent_routing_and_redundancy`),重新引入是大方向决策,需求明确(如并行 codegen)再单独立项。`#4 工具 Set` 先把地基铺好。
- **skills 作为 .md 懒加载**:我们有 save_config_skill 雏形 + doc_spec_standard;改成 `.claude/skills/*.md` 体系是较大重构,价值中、优先级低。
- **withhold-until-recovery / 多级 recovery state machine**:优雅但绑定它的错误分类法;我们网关错误形态不同,挑「413 反应式压缩」「max-output 续写」两个具体的借即可,别整套搬。

## 下一步
这是调研产物。每个要真做的项 = **单独一轮 brainstorm→spec→plan→实现**(参考这次配置助手统一的流程)。建议优先级:**1 延迟工具 → 2 压缩 → 3 结果落盘**(这三个直接治我们当前 token/稳定性痛点),其余按需。
