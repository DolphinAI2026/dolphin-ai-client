# Builder Code 外层嵌入体验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Builder 外层 Code 页面以可信 `builder.ready` 为切换点，完成无串会话、可恢复的 iframe 进入与切换。

**Architecture:** 把 frame 生命周期提取为可测试状态模型；Vue 页面只负责 API 调用、DOM iframe 引用和协议分发。宿主校验 `origin + source + frame identity`，使用遮罩冻结旧 frame，并向内层发布可见性和激活状态。

**Tech Stack:** Vue 3、TypeScript、Vitest、postMessage、FastAPI 注入配置

---

### Task 1: 建立 frame 生命周期状态模型

**Files:**
- Create: `frontend/src/views/codeFrameLifecycle.ts`
- Create: `frontend/src/views/codeFrameLifecycle.spec.ts`
- Modify: `frontend/src/views/CodeConversationPage.vue`

- [ ] 先写失败测试，覆盖首次打开、切换、迟到 ready、失败回滚和重复 URL。
- [ ] 实现 `active / pending / failed` 状态转移和 frame identity。
- [ ] 页面改为由状态模型驱动 iframe 列表与遮罩。
- [ ] 原生 iframe `load` 只记录已加载，不再直接提升为 active。

### Task 2: 建立可信 shell 协议

**Files:**
- Create: `frontend/src/views/codeShellProtocol.ts`
- Create: `frontend/src/views/codeShellProtocol.spec.ts`
- Modify: `frontend/src/views/CodeConversationPage.vue`

- [ ] 先写失败测试，覆盖 origin、source、frame key 和消息类型校验。
- [ ] 收到 pending frame 的可信 `builder.ready` 后原子提升。
- [ ] 向 active/pending frame 发送 `shell.visibilityChanged` 和 `shell.sessionActivationChanged`。
- [ ] 切换期间冻结旧 iframe；失败时恢复旧 iframe 并显示重试。

### Task 3: 收敛宿主注入配置

**Files:**
- Modify: `backend/app/routes/code_runtime.py`
- Modify: relevant backend tests

- [ ] 为 shell 配置和 embed URL 写失败测试。
- [ ] 保留结构化 `__APAAS_SHELL__` 配置，删除会与内层布局冲突的重复 DOM/CSS 注入。
- [ ] 保证 `webConsoleOrigin`、外部会话栏和历史显示配置准确。

### Task 4: 验证

- [ ] 运行 `frontend` 聚焦测试和全量测试。
- [ ] 运行相关后端测试。
- [ ] 运行 `frontend` 生产构建。
- [ ] 与 `agent-runtime` 当前分支联调首次进入、快速切换、失败回滚和迟到消息。
