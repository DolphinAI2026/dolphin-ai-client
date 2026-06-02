# AI Coding ↔ AI Builder 会话区 UI/UX 统一 — 设计 spec

> **状态**:✅ **已落地**(2026-06-02,分支 `feat/coding-builder-ui-unify`)。core 统一(thinking/tool/status→native)+ 表格列 prompt 完成,replay(公告通知 53 行)+ live READ + `vite build` 验证。详见文末「✅ 已落地记录」。
> **关键修正**:spec 原假设「Coding 没用 AgentConversation、要从零迁移」**不准** —— Coding 早已用 `<AgentConversation :messages>`,只是全走 `#custom` slot 重渲自有 markup;真正工作 = 把有 native 对应的 type 改走 native kind(窄、低风险)。
> **缘由**:用户反馈两边会话区体验不一致,要求统一 4 项:① 工具/状态卡样式 ② 应用表格列 ③ 间距/颜色细节 ④ 整体布局/空态。

## 目标
Coding 会话区(消息流)在视觉 + 交互上向 Builder 看齐,达到「一套 UI/UX」。**正解 = 让 Coding 复用 Builder 的 `AgentConversation` 组件**,而非逐条抄 CSS。

## 现状:两套不同的渲染系统(核心难点)
| | Builder | Coding |
|---|---|---|
| 渲染器 | `frontend/src/components/common/AgentConversation.vue`(timeline 驱动)| `frontend/src/views/CodingPage.vue` 模板内联 自定义(streamMessages 驱动)|
| 数据 | `timeline[]`,item 有 `kind`: user / assistant / streaming / thinking / tool / group | `streamMessages[]`,`streamCustom(m).sm` 有 `type`: thinking / status / tool / message / command …,带 stepKey/stepDone/collapsed |
| 结构 | `.ac-row` + `.ac-avatar.brand`「A」+ `.ac-bubble`(user-bubble / assistant-naked) + `.ac-tool-group` 折叠 + `ToolCard` | `.msg-thinking-card`(可折叠) / `.msg-status` / `.msg-step-badge` / `.tool-row`(🔧) / `.command-card`(命令+输出) |
| markdown | `marked`(breaks+gfm)| `renderMarkdown`(useStreamMessages.ts)|
| 工具卡 | `frontend/src/components/common/agent-conversation/ToolCard.vue` | 内联 .tool-row / .command-card |

### Builder 样式基准值(已读出,直接用)
- `.ac-list`: padding 16px 18px; gap 12px。`.ac-row`: gap 10px。
- `.ac-avatar.brand`「A」: 28×28, radius 6px, bg `#3b82f6`, color `#fff`, font 13px。
- `.ac-bubble`: max-width min(740px,78%), padding 10px 14px, radius 12px, font 13.5px, line-height 1.6。
- `.ac-bubble.assistant-naked`: 透明无边框, padding 4px 0 0(助手内容裸渲)。
- 用户:`.ac-bubble.user-bubble`(灰气泡,右)+ `.ac-user-tag`「我」。助手完成后 `.ac-feedback`(复制/👎)。

## 关键技术工作:streamMessages → AgentConversation timeline 映射
AgentConversation 的 timeline kind **不直接覆盖** Coding 的 status-step / command-card / file-write-list。需要二选一:
- **方案 A(推荐)**:扩展 AgentConversation 支持 Coding 专属 item(status 步骤、command+output、file-write 列表),Coding 把 streamMessages 映射成 timeline 后用 `<AgentConversation :timeline>` 渲染。两边彻底同源。
- **方案 B**:只把 Coding 的「普通消息 / 工具卡 / thinking」对齐 AgentConversation 样式(抄 ToolCard + ac-* CSS),保留 Coding 自定义结构。省事但仍两套代码、易漂移。

映射要点(方案 A):
- `sm.type='message'/assistant` → `kind:'assistant'`(裸渲 markdown + 复制/👎)。
- `sm.type='thinking'` → `kind:'thinking'`(AgentConversation 已有 thinking 渲染 + slot)。
- `sm.type='tool'`(READ 的 🔧 chip)→ `kind:'tool'`/`group` 用 ToolCard;**目标视觉 = Builder 的「✓ 已完成 · 查询 X · 找到 N ›」干净结果 chip**。
- `sm.type='status'`(detect_scene / 「正在理解你的需求」/ step-badge)→ AgentConversation 需新增 status item 或并入 thinking/tool 的 running 态。
- command-card(命令+输出)、file-write 列表 → AgentConversation 需新增对应 item kind(codegen 专属)。
- user 消息 → `kind:'user'`(灰气泡 + 「我」tag)。

## 4 项落点
1. **工具/状态卡** → 复用 ToolCard + ac-tool-group;READ 工具渲染成 Builder 那种结果 chip。
2. **应用表格列** → 这是 **LLM 生成的 markdown 表**,跟渲染器无关。统一 prompt/格式:Builder agent 与 `backend/app/coding/read_query.py` 的读答都用同一套列(建议 `序号 / 应用名称 / 应用编码 / 状态`,apaas_app_id 可去或两边都留)。注:数据源已统一(两边都查 apaas,见 commit 51e3cf8)。
3. **间距/颜色** → 复用 AgentConversation 的 `.ac-*` 值(上面基准值),自动一致。
4. **布局/空态** → 用 AgentConversation 的 `empty` slot + `.ac-list` 布局;Coding 空态「这个开发会话还没有消息」并入。

## 必须保留的 Coding 行为(回归点)
- READ 路径(`read_query.py`):意图分类 → 只读工具 chip + 答案 + 持久化。
- BUILD 路径:detect_scene → SPEC → file_write/command/build 卡 → 32 产物。
- 历史回放:`restoreReplayStreamMessages`(从 workspace chat-replay.json 的 stream_messages)+ `loadConversationHistory` + `parseAssistantHistory` 兜底。F2(commit a71024b)已让直达 URL 也走富回放。
- 产物面板(`CustomPagePreviewPanel`)、IDE 抽屉、embedded 模式(右侧 `.embedded-panel`)—— 这些在消息区**之外**,不动。
- 模型选择器 `.coding-model-trigger`(底部 composer)+ 模型名 **dolphin.ai(预期名,勿改)**。

## 风险 / 约束
- CodingPage.vue **超大且复杂**(READ/BUILD/历史/IDE/产物/embedded),改消息区要全程保住这些。
- `vue-tsc` 严格检查 dev 上早已 400+ 陈旧错 → **用 `npx vite build` 验打包**,不靠 vue-tsc。
- **必须可视化迭代**:执行 session 要能登录看 live(本轮卡在登出态盲改才立项)。每改一步刷新截图收敛。
- composer 已是共用 `UnifiedChatComposer`(两边一致,不动)。

## 关键文件
- `frontend/src/components/common/AgentConversation.vue`(基准渲染器)
- `frontend/src/components/common/agent-conversation/ToolCard.vue`
- `frontend/src/views/CodingPage.vue`(消息区模板 ~行 108-260 + `.msg-*`/`.tool-row`/`.command-card` CSS)
- `frontend/src/views/coding/useStreamMessages.ts`(renderMarkdown / restoreReplayStreamMessages / STEP_*_PATTERNS)
- `frontend/src/views/coding/useCodingPipeline.ts`(streamMessages 事件 dispatch)
- `backend/app/coding/read_query.py`(READ 答案表格格式 — 第 2 项)

## 执行建议
独立 session + 可视化迭代。先方案 A 的最小闭环(普通消息 + thinking + READ 工具 chip 对齐),跑通 READ 体验与 Builder 一致,再逐步并入 BUILD 的 command/file-write 卡。每步 `vite build` + 刷新截图验证。

---

## ✅ 已落地记录(2026-06-02,分支 `feat/coding-builder-ui-unify`)

**做法**:方案 A,但因 AgentConversation 已是 Coding 的 shell,只改 `agentMessages` 映射把有 native 对应的 type 切到 native kind,不重建组件。

**改动文件(3 个)**:
- `frontend/src/views/CodingPage.vue`:`agentMessages` 新增 `thinking→kind:'thinking'` / `tool→kind:'tool'`(`toolPayloadFromStreamMsg` 去 emoji 解析 content,live 可带 `toolName`)/ `status→kind:'status'`(stepDone 补 `✓`);`#custom` slot 精简到只剩 `file_write/file_edit`+`command`(native 无对应 kind);删除已死的 `.msg-thinking-card`/`.msg-status`/`.msg-step-badge`/`.msg-tool-row` 等 ~165 行 CSS。
- `frontend/src/components/common/agent-conversation/ToolCard.vue`:`verbLabel` 当 `name` 含中文时返回 ''(Coding 把「读取 X」整段当 name,避免「调用 读取 X」冗余);`tc-verb` 加 `v-if`。Builder/AIChat 的 name 是 ASCII 工具名,无影响。
- `backend/app/coding/read_query.py`:`_READ_SYSTEM_PROMPT` 固定应用列表为 4 列 `序号|应用名称|应用编码|状态`,去掉 apaas_app_id 长数字。

**4 项达成**:① 工具/状态卡 ✅(native ToolCard +「已完成 · 读取 X ›」/ native status pill);② 表格列 ✅(read_query prompt 固定列;注:Builder 侧 AI Chat 走 `list_my_applications` 自由格式、且 prompt 含 doc 生成强约束不宜动,故只统一 Coding READ 侧);③ 间距/颜色 ✅(native kind 自动继承 `.ac-*`);④ 布局/空态 ✅(沿用 `.ac-list`,两个空态视觉 OK,未强行并入 empty slot)。

**验证**:`vite build` 多次通过(不靠 vue-tsc);公告通知 BUILD 会话 replay 53 行(thinking14/tool5/status10/file8/command9 全对);live READ 路径正常 + native 渲染;回归点(产物面板/IDE 按钮/embedded/dolphin.ai 模型名/composer/历史回放直达 URL)均无伤(改动只碰消息区映射)。

**遗留/备注**:
- replay 老数据里「command/工具输出被存成 status」的长 `✅ ...[exit code:0]` 会变成偏宽的 native status 块(可接受;真要收口可给 `.ac-status` 加 max-width+省略)。
- live tool 暂用 content 解析(未在 pipeline 落 `toolName`);如需 live 显示真实工具名 + Builder 式「✓ 找到 N」结果摘要,可在 `useCodingPipeline` 的 tool/agent_tool 处理里存 `toolName`,并把 AIChatPage 的 `summarizeToolResult` 抽到共享模块复用。
- `#custom` slot 的 dark-theme 变种里仍留少量死选择器引用(与 live 的 `.msg-command-card` 同选择器组,无害,未拆)。
