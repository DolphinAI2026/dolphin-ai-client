# Plan · 配置助手做成 Claude-in-Chrome 级 agent

> 2026-05-21 立项。当前 HEAD: `d8db352` on `local/ui-redesign-2026-05-20`。

## 🎯 愿景

配置助手能像 **Claude-in-Chrome** 一样：

- 用户 1 句话发出复杂需求（"把所有报销表单的金额字段都改成必填 + 加金额上限 50000"），
  agent 自主 plan → 多步执行 → 验证 → 报告
- 不再需要用户一步步教 / 反复确认
- 操作面盖到 aPaaS API（已有 MCP 工具）+ aPaaS iframe 内的视觉 UI（暂没有）

---

## 📍 当前状态（必读，别重做）

### ✅ 已经有的（不要重新发明）

1. **`/ai-chat/X` (AIChatPage)** 已经接 71 MCP 工具
   - `backend/app/ai_chat/agent.py` 783 行 — LLM tool calling loop
   - `backend/app/ai_chat/mcp_bridge.py` — HTTP loopback 调本机 MCP server
   - `backend/app/ai_chat/tools.py` — 4 base 工具 (read_attachment / run_python / write_artifact / ask_clarifying_question) + MCP intercept (md → artifact)
   - 实测 E2E：物料管理系统、资产管理系统、招聘管理系统 都能完整 0-1 创建

2. **`/chat?app_id=X` (ChatPage) 配置助手面板** 在右侧 (`v-if="isPostDeploy"`)
   - 3 个 quick prompt：'把物料档案的物料编码改成必填' / '加一个角色叫"运维管理员"' / '物料类别 字典加一个"XX"选项'
   - 自由输入框：'描述你想调整的内容...' + 发送
   - 找：`frontend/src/views/ChatPage.vue` 搜 `ConfigAssistantPanel`
     或 grep "调整「" / "配置助手"

3. **70+ aPaaS MCP 工具**（精细操作 — 不走 SPEC 文档流）：
   - 角色：create_apaas_app_roles / update / delete
   - 字典：create_apaas_app_dict / add_apaas_dict_option / update_dict_option / disable
   - 模型：update_apaas_app_model / add_apaas_model_field / update / disable
   - 表单：create_apaas_form_menu / update_apaas_form_component / delete_apaas_app_form
   - 权限：set_apaas_form_permissions / set_apaas_app_access
   - 流程：set_apaas_app_process
   - 内省：list_apaas_app_menus / list_models / list_dicts / list_roles / list_form_views / list_form_components

### ❌ 缺什么

| 痛点 | 当前 | 期望 |
|------|------|------|
| Agent 主动性 | 用户教 1-2 句话，agent 调 1-2 个工具就停 | 1 个复杂指令 → agent 自主 plan + 多步 + 验证 |
| 配置助手 UI | 3 quick prompt 窄入口 + 自由输入框，但没"agent 在工作"的反馈 | plan 卡片可视化 + 多步进度 + 完成总结 |
| iframe 内操作 | 完全不能 — aPaaS iframe 跨域，前端没法 DOM 操控 | 后端 Playwright 驱动 iframe（视觉拖拽 / 复杂表单设计器） |

---

## 📦 3 个 Phase 分解

### Phase 1: Agent prompt + 多步自主执行（1-2 天）

**目标**：让 agent 默认进入"plan + execute 多步直到完成"模式，而不是答 1-2 句就停。

**做什么**：

1. **Prompt 升级** — `backend/app/ai_chat/agent.py:35-130` SYSTEM_PROMPT_UNIFIED
   - 加 "**默认主动多步执行**" 规则：用户描述完需求你应该一气呵成做完，不要每步问"要继续吗"
   - 加 "**先 plan 后 execute**" 规则：复杂任务（涉及 3+ 步）先用 `write_artifact` 写一个 `plan-{timestamp}.md` 给用户看，再开始调工具
   - 加 "**verify-after-execute**" 规则：deploy / update 类工具调完一定调对应 `list_*` / `get_application` 验证结果
   - 参考已有 builder agent prompt `docs/skills/ai-builder/prompt.md`

2. **多步循环上限** — `agent.py:_run_agent_turn` 已有 loop，但可能 LLM 早 stop。  
   现状：Agent A 已加 "无工具调用 + 空 content → inject 强制总结 system reminder + 再 stream 一次" (commit 03cba9c)。  
   要补：**有工具调用但任务没完成的中间状态** — 比如调了 update_form_component 改了 1 个字段，还有 4 个字段要改但 LLM 停下来等用户。需要 prompt 层面让它"全部改完才停"，或加循环硬限制（max_iterations=20）。

3. **工具调用并行化（可选）** — 现 agent loop 串行调工具。多个独立操作（改 5 个字段）可以并发 — 但要小心 aPaaS API 是否支持并发写 / 是否有 race condition。先 audit 再加。

4. **错误恢复** — 工具失败时 agent 现在直接报错给用户。应当：
   - APAAS_TOKEN_EXPIRED → agent 自动调 refresh_apaas_token（如果有这个工具）
   - APAAS_APP_CODE_CONFLICT → agent 改 code 重试
   - 其他业务错 → agent 先 list_* 看现状再决定怎么改

**验收**：
- 用户在 ChatPage 配置助手发 "把所有报销表单的金额字段都改成必填 + 加金额上限 50000"
- Agent 自动：list_apaas_app_models 找金额字段 → 5 个并发/串行 update_apaas_model_field → list_apaas_form_views 找所有报销表单 → update_form_component 加校验规则 → list_form_components 验证
- Agent 给最终汇总："改了 X 个字段，加了 Y 个校验规则，请测试"

### Phase 2: Config Assistant UI 升级（1-2 天）

**目标**：让 ChatPage 配置助手面板的"agent 工作"感跟 Claude-in-Chrome 一样直观。

**做什么**：

1. **Plan 卡片可视化**
   - 当 agent 调 `write_artifact` 写 `plan-*.md` 时，配置助手面板顶部渲染一个 plan 卡片：
     - 标题 "📋 执行计划"
     - Markdown 渲染 plan 内容（一般是 list of steps）
     - "开始执行 →" 按钮（点了发送 "OK 执行" 给 agent）
     - 或自动执行 + 步骤进度条
   - 类似 dolphin 浮窗的"创建计划 1/2"卡片

2. **多步进度可视化**
   - 当前 ChatPage 的配置助手面板长啥样：截图看 `frontend/src/views/ChatPage.vue` `<ConfigAssistantPanel>` 或类似组件
   - 加一个 timeline view：每个工具调用一行 chip（复用 AIChatPage 的 ToolCard 组件）
   - 用 AIChatPage 一样的 SSE 流（`/api/ai-chat/sessions/X/send`），监听 tool_call_start / tool_call_end / artifact_created 事件
   - 关键：**配置助手现在用的 conversation 是 dolphin 还是 ai-chat？** 必须先 audit 这块
     - 检查 ChatPage.vue `sendMessage` / `useDolphinChat` / `aiChatApi.sendMessage`
     - 如果是 dolphin 路径，且 dolphin 已下线（commit 3a7a3d4），那这个面板已经断了 — Phase 2 第一步是把它接到 ai-chat session 上

3. **完成态 hero CTA**
   - 跟 ChatPage hero CTA（Agent C commit de3a041）一样的风格
   - "✅ 已完成 X 步调整 · 查看应用 →"

4. **历史复用**
   - 配置助手底部加"最近 5 个调整任务"折叠列表，点击展开看历史 + 一键 redo

**关键文件**：
- ChatPage 配置助手：`frontend/src/views/ChatPage.vue` 搜 `ConfigAssistantPanel` / `调整「` / `配置助手`
- 共用 ToolCard：`frontend/src/components/common/agent-conversation/ToolCard.vue`
- 共用 AgentConversation：`frontend/src/components/common/AgentConversation.vue` 或 `common/agent-conversation/`

### Phase 3: Browser automation Playwright proxy（4-6 周）

**目标**：让 agent 能操控 aPaaS iframe 内的视觉 UI（拖拽、复杂表单设计器、菜单层级等没 MCP 工具的场景）。

**为啥难**：
- aPaaS iframe 是跨域 — 前端 JS 完全没法访问其 DOM
- 必须后端代理：起一个 headless browser，跑 Playwright/Puppeteer，登 aPaaS，操作 UI，截图回传

**架构草图**：

```
ai-chat agent
  ↓ 调 mcp 工具 apaas_ui_action(action="drag", from="...", to="...")
backend/app/services/playwright_proxy.py
  ↓ 启动 / 复用 headless Chrome (per-tenant pool)
  ↓ navigate, click, type, screenshot
  ↓ 返回 screenshot base64 + DOM snapshot
agent 拿到结果继续决策
```

**新 MCP 工具集**（每个都要写 + 测）：
- `apaas_ui_screenshot(env_id, page_url)` — 拿截图
- `apaas_ui_click(env_id, selector or coordinate)` — 点击
- `apaas_ui_type(env_id, selector, text)` — 输入
- `apaas_ui_drag(env_id, from_selector, to_selector)` — 拖拽
- `apaas_ui_read_dom(env_id, selector)` — 读 DOM 文本
- `apaas_ui_wait(env_id, selector, timeout)` — 等元素

**复杂度**：
- 凭证 / SSO：headless Chrome 怎么登录 aPaaS？ 复用 PlatformEnv.token？ cookie 域怎么处理？
- 性能：每个用户 / 租户开一个 browser 实例不现实，需要 pool + LRU
- 稳定性：UI 变了 selector 失效，需要 vision-based fallback（截图 + LLM 判断点哪）
- 安全：headless browser 跑用户级权限，aPaaS API key 不能漏到客户端

**P0 决策**：先确认是否真的有 MCP 工具盖不到的场景！可能 70 个 MCP 工具已经够 99% 用例。Phase 3 启动前先开一个 audit 会，列出"必须 iframe 内 UI 操作"的真实场景，再决定是否值得花 4-6 周。

---

## 🔑 关键决策需要先定

下个 session 开干前先跟用户确认：

1. **Phase 1 prompt 大改** — 现 SYSTEM_PROMPT_UNIFIED 在多个 agent 共用（ai-builder / ai-coding / vibe）。Phase 1 的"主动多步"约束加进去会不会让 vibe-coding 等场景变得太激进？
   - 选项 A: 改 UNIFIED prompt（影响所有 agent）
   - 选项 B: 拆 prompt — 给 ai-builder / 配置助手用独立 prompt（更安全）

2. **Phase 2 配置助手底层 conversation 模型** — 当前到底走哪条路？
   - audit `ChatPage.vue` 看 `sendMessage` 调用栈
   - 如果走 dolphin: 已经断了，要迁到 ai-chat
   - 如果走 ai-chat: 继续就好

3. **Phase 3 是否启动** — 真的有"iframe 内 UI 操作"刚需吗？还是 70 MCP 工具够了？
   - 建议先做 Phase 1 + Phase 2，使用一段时间收集 "agent 答不了的场景"
   - 收集到 5+ 个真实场景再决定 Phase 3

---

## 📁 关键文件清单

### Phase 1（agent 后端）
- `backend/app/ai_chat/agent.py` — SYSTEM_PROMPT_UNIFIED + agent loop
- `backend/app/ai_chat/tools.py` — 4 base 工具 + execute_tool dispatcher
- `backend/app/ai_chat/mcp_bridge.py` — MCP HTTP 桥
- `backend/app/mcp_server.py` — 80+ MCP 工具实现（要加新工具就在这里）

### Phase 2（配置助手前端）
- `frontend/src/views/ChatPage.vue` — 配置助手面板（grep "配置助手" / "ConfigAssistantPanel")
- `frontend/src/components/common/agent-conversation/ToolCard.vue` — 工具卡（复用）
- `frontend/src/components/common/AgentConversation.vue` — 流式对话渲染（复用）
- `frontend/src/api/aiChat.ts` — SSE sendMessage 客户端

### Phase 3（Playwright proxy）
- 全新：`backend/app/services/playwright_proxy.py`
- 全新：`backend/app/mcp_server.py` 加 apaas_ui_* 工具集
- 部署：requirements.txt 加 playwright + 跑 `playwright install chromium`
- 配置：headless Chrome pool config

---

## 🚦 准备工作（给下个 session 第一句话）

下个 session 开始时，第一件事建议是：

```
跑 chrome MCP 打开 http://localhost:5173/ai-builder/chat?app_id=N
（拿一个已部署的应用 id），audit 配置助手到底走哪条 conversation 路径：
- grep ChatPage.vue 找 sendMessage 调用栈
- network 看实际 POST 到 /api/ai-chat/sessions/X/send 还是 dolphin omnigate
- 决定 Phase 2 接哪个

然后开始 Phase 1 prompt 改写。
```

---

## 📞 当前 session 的状态

- 9 commits 全部 push origin 截止 HEAD `d8db352`
- 同事接手日 handoff 文档：`docs/handoff-2026-05-21-session-end.md`
- 本 plan 文档：`docs/plan-2026-05-21-config-assistant-agent-mode.md`
- 留尾任务（task #4 #5）写在同事 handoff 里
- 0-1 创建 E2E 验证：物料管理系统 / 资产管理系统 / 招聘管理系统 / 图书借阅系统 / 费用报销系统 / PCCS 全部跑通

下个 session 拉最新代码即可开干 — 不需要再 rebase / merge。
