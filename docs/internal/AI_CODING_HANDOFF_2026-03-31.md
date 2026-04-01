# AI Coding 交接文档（2026-03-31）

> 更新时间：2026-03-31 晚
>
> 仓库路径：`/Users/mars/Vibe Coding/apaas-builder-ai`
>
> 当前分支：`main`
>
> 当前基线提交：`bf15a4c`
>
> 说明：本文覆盖的是 2026-03-31 下午至晚上的 AI Coding 相关改造。重点是模型配置统一、Chat/IDE 运行时收口、历史回放修复、规则文件清理、工作区排序与体验问题修复。

---

## 1. 本轮最重要的结论

### 1.1 AI Coding 现在已经不是完全“两套脑子”

之前：

- `Chat 模式` 走后端 `coding pipeline + VibeCodingAgent + tools`
- `IDE 内聊天` 走扩展内 `contextBuilder + /chat/completions + FILE 块落盘`

现在：

- `Chat 模式` 继续走后端统一 runtime
- `IDE 内聊天` 已优先切到后端统一 runtime
- 两边已经开始共享：
  - `workspace`
  - `conversationId`
  - `selected model`
  - `coding pipeline`

这意味着：

- IDE 不再主走“自己猜上下文 + 自己直连模型”的弱路径
- Chat 与 IDE 至少在“主执行脑子”上已经收口

但仍要注意：

- IDE 右侧原生聊天 UI 的“可视历史回放”仍受 VS Code / code-server `ChatParticipant` API 限制，不能完整恢复旧消息列表
- 现在做的是“上下文恢复 + 提示说明”，不是“原生聊天记录真正回灌”

### 1.2 Chat 重开后的内容已经明显更接近生成时内容

之前：

- 生成过程中，页面展示的是 SSE 实时事件流
- 重开 `Chat` 页面时，只从数据库 `messages` 恢复
- 而数据库里往往只保留“摘要化 assistant 回复”
- 所以会出现：
  - 第一张图：生成过程很丰富，有工具调用、构建、状态
  - 第二张图：重开后只剩总结版

现在：

- 工作区里增加了两套历史文件：
  - `.vscode/chat-history.json`
    - 给 IDE 扩展做精简上下文
  - `.vscode/chat-replay.json`
    - 给 Web Chat 做富回放
- `chat-replay.json` 现在不只是 `messages`，还会带 `stream_messages`
- Web Chat 重开优先用 `stream_messages` 还原结构化消息流

结果：

- 重开后的 Chat 已经更接近生成时内容
- 不再只是“助手摘要文本”

### 1.3 表单组件规则文件已经去重

之前：

- `.cursor/rules/apaas-form-component-dev.mdc`
- `.cursor/rules/form-component-dev-guide.mdc`

这两份内容有明显重复，而且扩展会同时加载，导致：

- 规则冗余
- 模型上下文重复
- 用户看起来像有两套近似指南

现在：

- 统一只保留 `apaas-form-component-dev.mdc`
- `form-component-dev-guide.mdc` 已从模板与工作区生成链路中清掉
- 历史工作区打开时会自动做一次规则文件纠正

### 1.4 工作区左侧顺序已经改成“最近活动优先”

之前：

- 左侧工作区基本是磁盘扫描顺序
- 没有明确的最近开发优先规则

现在：

- 按最近活动时间排序
- 活动时间综合参考：
  - `.workspace.json`
  - `.vscode/chat-history.json`
  - `.vscode/chat-replay.json`
  - `.vscode/ruijing-ai.json`
  - 工作区目录本身 mtime

所以：

- 正在开发的组件，理论上会更靠前

---

## 2. 本轮改造按主题拆解

## 2.1 模型配置统一与会话级模型切换

### 已完成

- 智能搭建、需求分析、AI Coding 三条链路统一接入租户模型配置
- 增加了会话级模型切换：
  - 智能搭建
  - 需求分析
  - AI Coding 欢迎页
- 模型解析优先级统一为：
  1. 当前会话显式选择的模型
  2. 当前租户默认的对应 `purpose` 模型
  3. 当前租户默认的 `all` 模型
  4. 环境变量兜底

### 新增能力

- 模型启用 / 禁用（全局）
- 禁用后的模型不会继续出现在对应页面的模型下拉中
- 禁止把未启用模型设为默认模型
- 自动补了一条通用模型：
  - `内置通用模型 (Qwen 3.5 Plus)`

### 相关文件

- `backend/app/routes/chat.py`
- `backend/app/routes/requirements.py`
- `backend/app/routes/coding.py`
- `backend/app/routes/conversations.py`
- `backend/app/routes/llm_configs.py`
- `backend/app/seed_data.py`
- `frontend/src/views/ChatPage.vue`
- `frontend/src/views/RequirementsPage.vue`
- `frontend/src/views/CodingPage.vue`
- `frontend/src/views/PlatformEnvs.vue`
- `frontend/src/api/llmConfig.ts`
- `frontend/src/api/conversation.ts`
- `frontend/src/api/coding.ts`

---

## 2.2 AI Coding：Chat 与 IDE 的统一 runtime 收口

### 改造前

#### Chat 模式

- 入口：`frontend/src/views/CodingPage.vue`
- 后端：`backend/app/coding/pipeline.py`
- Agent：`backend/app/coding/vibe_agent.py`
- 特征：
  - 有工具调用
  - 有 workspace
  - 有 conversation
  - 有模型路由
  - 比较像 harness

#### IDE 内聊天

- 入口：`extensions/ruijing-ai/src/chatHandler.ts`
- 直接调用：`extensions/ruijing-ai/src/llmClient.ts`
- 辅助上下文：`extensions/ruijing-ai/src/contextBuilder.ts`
- 特征：
  - 主要是 `/chat/completions`
  - 没有真正的 tool runtime
  - 读代码主要靠预拼上下文
  - 输出文件主要靠 FILE 块 + WorkspaceEdit

### 改造后

- IDE 内聊天优先走统一的后端 coding runtime
- 新增 / 接通了 IDE 侧统一入口
- IDE 配置文件会持久化：
  - `workspaceId`
  - `conversationId`
  - `model`
  - `ideToken`
  - `harnessApiBase`

### 结果

- Chat 和 IDE 已开始共享同一个主执行链路
- 同一个工作区的后续对话，可以续上同一个 `conversationId`
- 不再是“Chat 一套脑子，IDE 又一套脑子”

### 相关文件

- `backend/app/coding/pipeline.py`
- `backend/app/coding/vibe_agent.py`
- `backend/app/routes/coding.py`
- `backend/app/routes/harness.py`
- `backend/app/harness/manager.py`
- `backend/app/harness/profiles/coding.py`
- `extensions/ruijing-ai/src/config.ts`
- `extensions/ruijing-ai/src/llmClient.ts`
- `extensions/ruijing-ai/src/chatHandler.ts`

---

## 2.3 Chat 历史回放修复

### 问题现象

用户反馈：

1. 生成时的聊天内容很多，包含：
   - 场景识别
   - 脚手架初始化
   - 工具调用
   - 读文件 / 搜索 / 写文件 / 命令输出
   - 最终完成状态
2. 但生成后重新打开 Chat 页面时，只剩一份很短的总结

### 根因

- 生成过程展示的是实时 SSE 事件流
- 重开时读的是数据库里的 `messages`
- 数据库里的 assistant 内容在较新逻辑中更偏“最终总结”
- 所以两者天然不一致

### 解决方案

工作区现在写入两类历史：

#### 1. `chat-history.json`

用途：

- 供 IDE 扩展作为上下文读取
- 内容精简
- 主要是最近历史消息，不追求还原全部细节

#### 2. `chat-replay.json`

用途：

- 供 Web Chat 重开时回放
- 内容更丰富

现在的 `chat-replay.json` 包含：

- `messages`
- `stream_messages`

其中 `stream_messages` 是结构化流消息，形如：

- `user`
- `thinking`
- `tool`
- `file_write`
- `file_edit`
- `command`
- `status`
- `error`

### Web 端改造结果

`frontend/src/views/CodingPage.vue` 现在打开工作区时会：

1. 调 `getWorkspaceConversation`
2. 后端优先返回 `chat-replay.json` 中的 `stream_messages`
3. 前端优先恢复结构化 `streamMessages`
4. 如果没有 `stream_messages`，再回退到旧的 assistant 文本解析模式

### 额外修复

我还顺手补了一个以前的实时流缺口：

- 实时生成过程中，前端之前没有完整处理：
  - `content`
  - `agent_command_output`

这会导致：

- 生成时也不是完全还原后端事件

现在这两个事件也补上了，所以：

- 生成时更完整
- 重开后更接近生成时

### 相关文件

- `backend/app/coding/pipeline.py`
- `backend/app/routes/coding.py`
- `frontend/src/api/coding.ts`
- `frontend/src/views/CodingPage.vue`

---

## 2.4 IDE 原生聊天“历史丢失”问题的真实边界

### 用户看到的现象

- 重开某个工作区后，IDE 右侧原生聊天面板看起来像是空的
- 用户会以为“历史会话没了”

### 实际情况

通常并不是 `conversationId` 丢了。

例如 OCR 工作区里，我确认过：

- `conversationId` 仍然在 `.vscode/ruijing-ai.json` 中
- 后端数据库里对应 conversation 也还在
- 真正丢的是“原生聊天 UI 的可视历史”

### 为什么做不到完全恢复

因为当前用的是 VS Code / code-server 原生 `ChatParticipant` 能力。

在这套 API 里：

- 可以读取 `context.history`
- 但没有一个官方接口允许我们把旧聊天 turn 重新写回到原生面板可视历史里

所以：

- 可以把旧历史作为上下文继续喂给模型
- 但不能把它像真实聊天记录那样“回灌显示”

### 这轮做了什么

为了缓解用户误解，我在 IDE 扩展里加了显式提示：

- 如果 IDE 原生 `context.history` 是空
- 但工作区里有 `.vscode/chat-history.json`
- 扩展会提示：
  - 已加载当前工作区最近若干条 AI Coding 历史作为上下文
  - 只是原生面板不会自动回放旧消息

这样至少不会再让用户误以为：

- “系统完全失忆了”

### 相关文件

- `extensions/ruijing-ai/src/chatHandler.ts`

### 结论

#### 已解决

- “历史上下文真的丢了吗？” → 没丢，已经会加载

#### 未彻底解决

- “为什么 IDE 原生右侧面板看不到旧聊天记录？” → 目前受平台 API 限制

#### 真正彻底的解决方案

- 不再依赖原生 `ChatParticipant` 面板作为唯一聊天 UI
- 做自定义 IDE Chat 面板，自己渲染历史、事件流、文件变更、命令输出

---

## 2.5 规则文件清理

### 之前的问题

工作区 `.cursor/rules` 下有三份相关规则：

- `apaas-form-component-dev.mdc`
- `form-component-dev-guide.mdc`
- `前端SDK-v2介绍.mdc`

其中：

- 前两份高度重复
- 第三份是 SDK 说明，不重复，但用户怀疑是否无用

### 结论

#### `apaas-form-component-dev.mdc`

- 保留
- 作为表单组件主规范

#### `form-component-dev-guide.mdc`

- 删除
- 已从模板和工作区生成逻辑里移除
- 老工作区打开时会自动纠正

#### `前端SDK-v2介绍.mdc`

- 保留
- 仍然有用
- 因为扩展会加载 `.cursor/rules/**/*.mdc`，这份会被真实注入模型上下文
- 作用主要是平台 SDK / API / 运行时能力说明

### 相关文件

- `backend/app/coding/workspace.py`
- `backend/app/routes/coding.py`
- `extensions/ruijing-ai/src/guidesLoader.ts`
- 已删除：`backend/templates/cursor-rules/form-component-dev-guide.mdc`

---

## 2.6 左侧工作区顺序修复

### 问题

用户提到：

- OCR 正在开发
- 但左侧顺序看起来并不符合“最近开发优先”

### 根因

- 工作区列表以前没有真正定义排序规则
- 更多是“扫到什么就展示什么”

### 现在的规则

工作区排序按“最近活动时间”倒序。

活动时间参考：

- 工作区目录 mtime
- `.workspace.json`
- `.vscode/chat-history.json`
- `.vscode/chat-replay.json`
- `.vscode/ruijing-ai.json`

### 结果

- 当前正在开发、最近有对话或刚写过配置的工作区会更靠前

### 相关文件

- `backend/app/coding/workspace.py`

---

## 3. 真实验证记录

## 3.1 真实组件生成测试

我实际跑过“二维码组件”这条链路，不是只看代码。

结果：

- 场景识别：成功
- 工作区创建：成功
- conversation 创建：成功
- IDE 地址生成：成功
- 组件关键文件生成：成功
- `npm run build`：成功

这一轮验证说明：

- Chat 模式主链路能跑通
- 生成出来的自开发组件不是空壳

## 3.2 Chat 与 IDE 联动验证

我验证过：

- 同一个工作区
- 同一个 `conversationId`
- Chat 发起生成后，再到 IDE 内继续对话

结果：

- IDE 第二轮请求已经沿用同一个 conversation
- 不再完全是另起一轮独立聊天

## 3.3 规则文件验证

我检查过工作区：

- OCR 工作区现在只保留：
  - `apaas-form-component-dev.mdc`
  - `前端SDK-v2介绍.mdc`

## 3.4 replay 回填验证

我给两个已有工作区回填了结构化 `chat-replay.json`：

- `评分组件`
- `OCR识别组件`

回填后：

- `chat-replay.json` 版本已提升为 `2`
- 已包含 `stream_messages`

注意：

- 老工作区如果数据库里原本就只剩摘要，那么回填出的 replay 也只能基于现有摘要重建，无法凭空恢复丢掉的旧实时流

---

## 4. 已跑过的构建 / 编译验证

以下验证已执行通过：

- `backend/venv/bin/python -m py_compile backend/app/coding/pipeline.py backend/app/routes/coding.py backend/app/coding/workspace.py backend/app/coding/vibe_agent.py`
- `npm run build` in `extensions/ruijing-ai`
- `npx vite build` in `frontend`

---

## 5. 当前工作区状态（很重要）

当前不是干净工作区。

### 已修改但未提交的主要文件

- `backend/app/coding/vibe_agent.py`
- `backend/app/coding/workspace.py`
- `backend/app/routes/coding.py`
- `extensions/ruijing-ai/dist/extension.js`
- `extensions/ruijing-ai/dist/extension.js.map`
- `extensions/ruijing-ai/src/chatHandler.ts`
- `extensions/ruijing-ai/src/config.ts`
- `extensions/ruijing-ai/src/contextBuilder.ts`
- `extensions/ruijing-ai/src/llmClient.ts`
- `frontend/src/api/coding.ts`
- `frontend/src/views/CodingPage.vue`

### 未跟踪文件里有两类内容

#### 1. 本轮相关但尚未正式纳入版本的关键文件

- `backend/app/coding/pipeline.py`
- `backend/app/routes/harness.py`
- `backend/app/harness/`
- `frontend/src/api/harness.ts`

#### 2. 明显不是这轮主线的草稿 / 工具 / 资料

- `.playwright-mcp/`
- `docs/mark/`
- `docs/reference/training/`
- `extensions/ruijing-ai/ruijing-ai-0.1.0.vsix`
- `scripts/ocr_image.swift`
- 其他文档和脚本草稿

### 风险提示

另一个会话接手时，不要直接：

- 大范围 `git add .`
- 大范围回滚

因为当前工作区里混有：

- 本轮功能改造
- 旧改动
- 草稿文件
- 外部工具临时文件

更安全的方式是：

- 只围绕 AI Coding 主链路相关文件做精确处理

---

## 6. 还没彻底做完的点

## 6.1 IDE 原生聊天可视历史

现状：

- 上下文恢复了
- 可视历史仍不能真正回放

如果要彻底解决：

- 做自定义 IDE Chat 面板

## 6.2 Chat / IDE 事件协议仍不够完全统一

虽然运行时主链路已经共用很多了，但还不算彻底统一的“一个 Coding Harness，两个视图”。

后续建议：

- 统一成 `turn / item / artifact` 模型
- Chat 和 IDE 都只消费统一事件协议

## 6.3 `run_command` 结果判定还有继续优化空间

虽然前面已经修过一轮 build 误报，但 `run_command` 这块后续仍值得继续做：

- 成功 / 失败判定更稳
- 构建日志结构化
- 针对 `df-apaas-cli` 这种链路做更专门的成功判定

## 6.4 replay 的历史精度受历史数据质量影响

对于旧工作区：

- 如果之前已经只把 assistant 总结存库
- 那再怎么回填，也恢复不到完整实时过程

新工作区和新的对话轮次会更好，因为现在已经开始写结构化 replay。

---

## 7. 推荐的下一步工作顺序

### P1：自定义 IDE Chat 面板方案

目标：

- 不再依赖原生 `ChatParticipant` 的历史 UI
- 自己展示：
  - 历史
  - thinking
  - 工具调用
  - 命令输出
  - 文件变更
  - 完成状态

### P2：统一 Coding Harness 事件协议

目标：

- 把 Chat 和 IDE 都切到同一套事件模型
- 减少前端/扩展各自写一套翻译逻辑

### P3：把 replay / artifact 做得更正式

目标：

- 工作区里不仅有 `chat-history.json` / `chat-replay.json`
- 还可以有：
  - `tool-results.json`
  - `build-log.txt`
  - `changed-files.json`
  - `preview-artifacts.json`

### P4：进一步收 IDE 弱路径

现在 IDE 已优先走统一 runtime，但还保留了 fallback 兼容模式。

后续可以继续：

- 把旧直连 `/chat/completions` 逻辑进一步降级
- 减少“fallback 在某些边界条件下偷偷生效”的心智负担

---

## 8. 另一个会话接手时建议先做什么

建议按这个顺序接：

1. 先读本文
2. 再看：
   - `backend/app/coding/pipeline.py`
   - `backend/app/routes/coding.py`
   - `frontend/src/views/CodingPage.vue`
   - `extensions/ruijing-ai/src/chatHandler.ts`
   - `backend/app/coding/workspace.py`
3. 再决定下一步是：
   - 继续做 IDE 自定义历史面板
   - 还是继续做 Coding Harness 统一

如果只是继续修体验问题，最值得优先看的文件是：

- `frontend/src/views/CodingPage.vue`
- `extensions/ruijing-ai/src/chatHandler.ts`

如果要继续做架构统一，最值得优先看的文件是：

- `backend/app/coding/pipeline.py`
- `backend/app/routes/harness.py`
- `backend/app/harness/`

---

## 9. 一句话总结

这轮 AI Coding 的关键进展，不是单点修了一个 bug，而是把它从“Chat 和 IDE 两套逻辑、历史还容易失忆、规则还重复、排序还随机”的状态，推进到了：

- 模型链路统一
- Chat / IDE 开始共用同一条 coding runtime
- Chat 重开历史可结构化回放
- IDE 至少不再“悄悄失忆”
- 表单组件规则去重
- 工作区按最近活动排序

离真正完整的 `Coding Harness` 还差一步，但这一步已经明显往前推了。
