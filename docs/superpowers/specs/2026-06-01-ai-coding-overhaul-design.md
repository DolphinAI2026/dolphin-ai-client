# 设计:AI Coding 治理 + Builder 无缝衔接(子项目 ①)

> 日期 2026-06-01 · 状态:待用户复审 · 范围:仅主仓 `backend/` + `frontend/`(`mcp-server/` 副本本次不碰,后续单独删)

## 1. 背景与目标

用户反馈 AI Coding 的交互体验比 AI Builder 差、割裂。经调查,AI Builder 是「对话即结果」,AI Coding 是「先装配一个 IDE 环境」,且底层埋着双 coding 后端、session≠workspace 双轨身份等结构债。

经讨论否决了「把自开发折叠进 Builder(让 config-chat agent 驱动重 codegen)」的方案 —— 那会把重 codegen 塞进为轻量配置设计的 agent、复制 pipeline 逻辑、且不修 AI Coding 本身。

**最终方向:治本。把 AI Coding 本身修顺 + 把 Builder→Coding 衔接做到无缝。** 重 codegen 留在它该在的 pipeline 引擎里。

### 用户的三大痛点(本设计要解决的)
1. **交互/工具不可见**:Coding 把工具调用塞成 emoji 文本(`🔧`/`✅`/`❌`),历史靠正则反解;看不出它有没有真 read/write。Builder 是结构化工具 chip。
2. **Builder↔Coding 断层**:从 Builder 进 Coding 开发,两边是独立对话线程,上下文断了。
3. **workspace 还是 session 划分?**:当前两者并存(`Conversation` 行 + 磁盘 workspace 目录),0/1 关系、会出孤儿、侧栏 `conv:`/`ws:` 双轨 if-else。「没考虑好」的核心。

## 2. 关键决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | 治本(修 AI Coding + 无缝 handoff),**不**折叠进 Builder | 避免把重 codegen 塞进 config agent + 复制逻辑;直击根因 |
| D2 | **session(Conversation)为主单位**,1:1 拥有 workspace | 对齐 Builder 的会话式侧栏 + 消灭双轨;workspace 懒创建、永远经会话访问 |
| D3 | **分两期**:Phase 1 在现有 pipeline 上做;Phase 2 再评估接 v2 异步后端 | Phase 1 即可解决三大痛点且风险低;v2 重写风险大,先不上 |
| D4 | 仅改主仓;`mcp-server/` 副本本次忽略 | 用户确认后续单独删 |

## 3. 范围

**纳入(Phase 1)**:数据模型(session 为主)· 交互/工具卡可见 · Builder↔Coding 无缝衔接 · 流程顺滑(去强制 brainstorm 门)。
**暂不(Phase 2 / 后续)**:接 v2 异步后端(`coding/v2`)· 资产库按应用聚合(= 子项目 ②)· 删 `mcp-server/` 副本 · 引擎层(scenes/workspace/build/publish)不动。

## 4. Phase 1 设计

### 4.1 数据模型 —— session 为主(D2)
- **会话(`Conversation`,`agent_type='coding'`)是唯一主单位**;侧栏只列会话(对齐 Builder)。
- 一个会话**最多拥有一个 workspace**(`Conversation.workspace_id`),**动手开发时才懒创建**;纯聊天/brainstorm 阶段无 workspace。
- **workspace 在 AI Coding 侧栏永不独立展示**(资产库视图是子项目 ②,另算):消灭 `CodingPage.vue` 里 `sidebarCodingItems` + `sidebarWorkspaceFallbackItems` 的 `conv:`/`ws:` 双轨合并去重(`CodingPage.vue:854-895`)。侧栏项一律是会话;workspace 经其会话访问。
- **删除语义统一**:删会话 = 连带删其 workspace(已有雏形 `DELETE /coding/conversations/{id}` in `backend/app/routes/coding.py`,本设计将其确立为正式语义,移除 `deleteWorkspace` 独立入口在侧栏的暴露)。
- **迁移**:一次性幂等脚本把现有「孤儿 workspace」(无会话指向)→ 各补建一个 owner 会话挂上(**不丢数据**);确实无法关联的才标记归档。保证迁移后 AI Coding 侧栏无游离 workspace。

### 4.2 交互 / 工具可见性(痛点 #1)
- 工具调用渲染成**结构化卡片**:`正在读 X` / `已写 Y(+N 行)` / `跑了 Z(+ 输出折叠)`,带实时状态(进行中/成功/失败)。复用 Builder 那套(`AgentConversation.vue` 已是两边共享组件;参照 `AIChatPage.vue:561-648` 的 `summarizeToolResult` + tool chip 渲染)。
- 后端**结构化持久化**工具事件到 `stream_messages`(已有该机制,`useCodingPipeline.ts` 消费 12 类 SSE 事件 `:163`),让历史**按结构 replay**。
- **删除 emoji 正则反解**:移除 `CodingPage.vue:parseAssistantHistory`(`:1327`,靠 `🔧`/`> ✅`/`> ❌` 前缀正则猜历史)→ 统一走结构化 replay。

### 4.3 Builder ↔ Coding 无缝衔接(痛点 #2)
- **修 handoff 字段不一致 bug**:
  - 生产端 `ChatPage.vue:handoffToCodingForAppDev`(`:2319-2355`)写 `sessionStorage` payload = `{message, app_id, app_name}`;route query 另带 `project_id`。
  - 消费端 `CodingPage.vue:maybeConsumeAiBuilderDispatch`(`:1147-1181`)却按 `{message, projectId, sceneCategory}` 读 → `app_id/app_name` 被丢、`projectId/sceneCategory` 永远落空。
  - 修:消费端读 `app_id`/`app_name`,`project_id` 从 route query 取;统一 payload 形状。
- **带上下文**:handoff 把应用上下文(app + 相关 spec/讨论摘要)写进新建 Coding 会话当种子消息/上下文块。
- **可回跳 + 归属**:Coding 会话记录来源 `app_id`,UI 给「← 回 Builder 配置」链;两边读同一份应用上下文(经 `current_app` / app_id)。

### 4.4 流程顺滑
- **去掉强制两段式 brainstorm 确认门**:现状首条消息只产提案就 `return waiting_confirmation:True`(`backend/app/coding/pipeline.py:1604-1641`),必须再发一条才动工。改为:首条消息直接进入开发(brainstorm 作为可选/inline 提示,不阻塞);workspace 在确需 codegen 时懒创建。
- 结果 **inline 在对话里**呈现(工具卡 + 产物摘要),不强迫开全屏 IDE;需要 IDE 时再点开(IDE 入口已存在)。

## 5. Phase 2(后续评估,不在本次实施)
- 接已写好却未接 UI 的 **v2 异步后端**(`backend/app/routes/coding_v2.py`:POST 即返 202 + 后台 task + 独立 SSE 订阅 + Phase 状态机 + **autofix 循环**),取代老的单条同步阻塞 SSE(`harness/coding/pipeline`)。
- 触发条件:Phase 1 落地后,若「同步阻塞 + 流程重」仍是体感瓶颈,再启 Phase 2。届时单独出 spec。

## 6. 数据流(Phase 1 目标态)
```
用户在 AI Coding 输入一句需求
  → 创建/复用 会话(主单位);首条消息直接开干(无强制确认门)
  → pipeline 跑:detect_scene → 懒创建 workspace(挂到会话)→ codegen
     每个工具调用 → 结构化事件 → 前端实时渲染工具卡(读/写/跑+状态)
  → 结果 inline 在对话里;产物落 workspace(经会话访问)
  → 需要时点开 IDE / 需要时发布
从 Builder 进:一键带应用上下文 → 新建 Coding 会话(记来源 app)→ 同上;可「← 回 Builder」
```

## 7. 错误处理 & 迁移风险
- **数据迁移**:现有「无 workspace 的会话」「孤儿 workspace」「会话↔workspace 关系」需一次性 reconcile 脚本;迁移失败要可重跑、不破坏现有可用会话。
- **去 brainstorm 门**的回归面:确认没有别处依赖 `waiting_confirmation` 语义(pipeline 内 + 前端 STEP_HANDLERS)。
- **删 parseAssistantHistory** 前需确认所有历史会话都有可靠的 `stream_messages` 可 replay,否则给一个降级(纯文本展示)而非报错。
- 老 pipeline 退役不在 Phase 1(Phase 1 仍用它),故不涉及双后端切换风险。

## 8. 测试
- 端到端:新建会话 → 一句话直接出代码(工具卡实时可见、能看出 read/write/run)→ inline 结果 → 需要时开 IDE。
- 从 Builder 一键进 Coding:带应用上下文 + 能回跳。
- 删会话 → 连带清 workspace;侧栏无游离 workspace 项。
- 历史会话 replay 不依赖 emoji 正则;迁移脚本幂等可重跑。

## 9. 主要涉及文件
- 前端:`frontend/src/views/CodingPage.vue`(侧栏/历史/handoff 消费/IDE)、`frontend/src/views/coding/useCodingPipeline.ts`(SSE 消费/工具事件)、`frontend/src/stores/coding.ts`、`frontend/src/views/ChatPage.vue`(handoff 生产)、`frontend/src/components/common/AgentConversation.vue`(工具卡渲染,共享)。
- 后端:`backend/app/routes/coding.py`(会话/workspace 端点、删除语义)、`backend/app/coding/pipeline.py`(brainstorm 门、workspace 懒创建、结构化事件)、`Conversation` 模型(workspace_id 1:1)。
