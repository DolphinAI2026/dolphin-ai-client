# AI Coding 主工作台 MVP — 第一刀切片设计（需求 → 预览闭环）

> 版本：v1.0
> 日期：2026-05-28
> 状态：已通过 brainstorm，待 writing-plans 拆解
> 切片：① / 共 6 片（见 §2 Roadmap）

---

## 0. 给实现 Agent 的执行摘要

在现有 `/chat` 应用搭建体系的 SPEC 家底之上，**新起一个干净的「AI Coding 主工作台」页面**，形态是「左对话主线 + 右 6 Tab 工作区 + 底部输入框」。本切片只做实其中 2 个 Tab：

- **需求 Tab** = 直接复用现成的 `SpecDesignPanel`（11 章需求基线）
- **预览 Tab** = 新建（HTML 原型 iframe sandbox + 点选回填对话）

其余 4 个 Tab（进度 / 产出 / 工具 / 可观测）本切片只放占位空壳。Swarm 多 Agent 引擎、任务 DAG、token 成本、治理后台 6 页 —— **整块不碰**，留后续切片。

闭环目标：业务 Owner 说需求 → 右侧需求基线实时更新 → 点「生成原型」→ 预览 Tab 看到 HTML 原型 → 在原型上点选某块 → 对话里说怎么改 → 原型 + 需求同步更新。

---

## 1. 背景与定位

### 1.1 三份源文档
本设计是以下三份产品文档的工程落地（均为产品稿，非工程稿）：
- 《睿鲸 AI Vibe Coding SPEC 设计说明》v0.1（5 Agent + Artifact 流 + Skill registry）
- `vibe-coding-open-design-prototype-ai-assistant.html`（5 阶段可交互原型）
- 《AI Coding 整体产品设计》（PRD：四层架构 + 3 类角色 + 14 页面 + Swarm）

### 1.2 北极星（不在本切片实现，仅作方向锚）
AI Coding = **企业级多 Agent 应用交付平台**：左对话 + 右 6 Tab（需求/预览/进度/产出/工具/可观测）+ Swarm 蜂群并行构建 + 任务 DAG + 应用基线 + 成本可观测 + 平台治理后台。

### 1.3 落点决策（关键，brainstorm 摸码后修正）
| 决策 | 结论 | 依据 |
|---|---|---|
| 与现有 3 入口关系 | **原地升级、渐进改造**，不另起 repo | 现有 3 入口框架 + SpecDesignPanel + 125 MCP 工具可复用 |
| 第一刀落哪个体系 | **落 `/chat` 体系（app_id 中心）**，形态借鉴 `/vibe-coding` 的左右布局 | 需求基线家底（SpecDesignPanel/spec_chat/spec_apply）全在 `/chat`；`/vibe-coding`（OnlineCodingWorkspacePage）是纯代码沙箱，无 SPEC 能力，且绑 workspace 不绑 aPaaS 应用 |
| 是否改造 ChatPage | **否，新起干净页面** | ChatPage 约 1.3 万行，直接动刀风险高；只复用其子组件 |
| 预览对象 | **HTML 静态原型**（iframe sandbox + mock 数据） | 最轻最快；真实 aPaaS iframe / 自开发 Vue 实时渲染留后续 |

---

## 2. 切片 Roadmap（北极星 → 切片序列）

| 切片 | 范围 | 状态 |
|---|---|---|
| **① 本次** | 主工作台骨架 + 需求 Tab（复用）+ 预览 Tab（新建 HTML 原型）| 设计完成 |
| ② | 需求 Tab 对话驱动深化（全 11 章可对话改 + 点选锚定到章节）| 待启动 |
| ③ | 预览增强（设备视图 / 版本切换 / 局部重生成）| 待启动 |
| ④ | Swarm 引擎（后端）：AgentRun/Artifact/SkillCall/DAG 表 + 多 Agent 并行 + handoff + 进度 Tab | 待启动（最重）|
| ⑤ | 产出 Tab / 工具 Tab / 可观测 Tab（复用 MCPCallLog + 新增成本聚合）| 待启动 |
| ⑥ | 平台治理后台 6 页（工具集成/模型 Agent/权限审计/模板规范/应用基线/成本治理）| 待启动 |

---

## 3. 范围（In / Out）

### 3.1 In Scope（本切片做）
- 新建主工作台页面 `AICodingWorkspace.vue` + 路由 `/ai-coding/:appId?`
- 左对话主线（复用 spec_chat SSE 对话能力）
- 右 6 Tab 容器组件（需求/预览做实，其余 4 个占位空壳）
- 需求 Tab：内嵌现成 `SpecDesignPanel`
- 预览 Tab：新建 `PreviewTab.vue`（iframe sandbox 渲染 + 点选回填）
- 后端新增「HTML 原型生成」能力（吃需求基线 → 吐单文件 HTML）
- 原型存储（轻量：新表 or 复用现有落盘）
- 安全：iframe sandbox 隔离 + 输入长度限制 + 原型不含密钥
- E2E 验收 §9 那条链路

### 3.2 Out of Scope（本切片明确不做，YAGNI）
- 进度 / 产出 / 工具 / 可观测 4 个 Tab 的真实功能（只占位）
- Swarm 多 Agent 编排、任务 DAG、Agent handoff
- token 成本聚合、工具调用审计链
- 平台治理后台 6 页
- 真实 aPaaS 应用 iframe 预览、自开发 Vue 页面 dev server 实时渲染
- 预览的设备视图切换、版本对比、局部重新生成（留切片 ③）
- 脱离 app_id 的「纯想法」启动（本切片强依赖 app_id）

---

## 4. 闭环流程

```
①说需求         用户在左侧对话输入「给供应商加个风险等级字段」
   ↓
②改需求基线     spec_chat SSE → LLM 产出 patch → update_spec_section
   ↓            → 需求 Tab(SpecDesignPanel) 第 3 章数据模型实时刷新
③生成原型       用户点「生成原型」→ 后端读需求基线 → LLM → 单文件 HTML
   ↓
④预览           预览 Tab iframe(sandbox) 渲染 HTML 原型 + mock 数据
   ↓
⑤点选           用户点原型里某张卡片 → iframe postMessage → 回填对话框
   ↓
⑥再修改         用户「这张卡片改成红色预警」→ 回到 ① 或重新生成原型
```

---

## 5. 架构与组件

### 5.1 前端（Vue3 + TS + Element Plus，目录 `frontend/src/`）

**新建页面容器**
- `views/AICodingWorkspace.vue` — 主工作台。布局：复用 `BuilderFrame` + 左 `ConversationPane` + 右 `WorkspaceTabs`，左右用可拖拽 splitter（参考 `OnlineCodingWorkspacePage.vue:115-124` 的 `startPreviewResize` 实现）。
  - 职责：装配左右两栏、持有 `appId`、协调对话与 Tab 的事件总线（点选回填、生成原型触发）。
  - 依赖：`appId`（路由参数）、`SpecDesignPanel`、`PreviewTab`、对话组件。

**新建 Tab 容器**
- `components/ai-coding/WorkspaceTabs.vue` — 6 Tab 切换容器。
  - Tab 定义：`需求 | 预览 | 进度 | 产出 | 工具 | 可观测`，后 4 个 `disabled` 显「敬请期待」占位。
  - 需求 Tab slot 内嵌 `SpecDesignPanel`；预览 Tab slot 内嵌 `PreviewTab`。

**复用组件（不改其内部，只做容器适配）**
- `components/v3/SpecDesignPanel.vue` — 需求基线 11 章（已有：版本 dropdown / 阅读↔对比 / 导出 .md / 「确认并生成」apply）。强依赖 `appId` prop。
- 左对话 `components/ai-coding/ConversationPane.vue`（新建）：对接 `spec-chat-stream` SSE（见 §6.1），渲染对话气泡 + 底部输入框 + 接收点选回填。**默认新建**；若实现时发现 `/chat` 体系有可直接抽出的对话组件，优先复用。

**新建预览组件**
- `components/ai-coding/PreviewTab.vue`
  - 职责：① 触发 / 展示 HTML 原型生成（SSE 进度）；② iframe sandbox 渲染原型；③ 监听 iframe postMessage 的点选事件，emit 给父容器回填对话框。
  - iframe：`<iframe sandbox="allow-scripts" :srcdoc="html">`（**不加 allow-same-origin**，隔离父窗 cookie/storage）。
  - 点选：原型 HTML 生成时注入轻量脚本（见 §6.3），点击带 `data-block` 的元素 → `postMessage({type:'ai-coding:select', label})` → 父窗回填「我选中了：{label}」到对话输入框。

**路由**（`router/index.ts`）
- 新增 `{ path: '/ai-coding/:appId?', component: AICodingWorkspace }`。
- 入口接线：本切片先支持直接 URL 进入 + 从现有应用列表跳转带 appId；Landing 模式 picker 的接线留切片 ②（不在本切片强求）。

**设计 token**：统一用 `design-v3-tokens.css`（`var(--brand)` / `var(--surface)` 等），跟 SpecDesignPanel 对齐。

### 5.2 后端（Python FastAPI，目录 `backend/app/`）

**复用（不改）**
- `routes/applications/spec_chat.py` — `/applications/{app_id}/spec-chat-stream` SSE：LLM → JSON patch → `update_spec_section()` → 推 token + spec_change 事件。已通。
- `routes/applications/spec_sections.py` — `GET/PUT /{app_id}/spec-sections/{section_type}/{section_key}`，`update_spec_section()`。已通。
- `routes/applications/section_content.py` — `GET /{appId}/section-content/{roles,models,dicts,menus,processes}`。已通。
- `routes/applications/spec_apply.py` — `/{app_id}/spec/apply`（2 动作真接通）。已通。

**新建：HTML 原型生成**
- 新增 endpoint：`POST /applications/{app_id}/prototype/generate`（**SSE 流式**，复用 spec_chat 的 SSE 模式，边生成边推进度，完成推 `prototype_ready` 事件带原型 id）。
  - 逻辑：读该 app 的需求基线（spec_sections / section-content）→ 拼 prompt → 调 LLM（复用现有 LLM client + 配置）→ 产出**单文件 HTML**（CDN 引 Element Plus / ECharts，内置 mock 数据，不依赖外部 API）→ 存储 → 返回 id。
  - Prompt 要点（参考 vibe-coding-spec §12.1）：企业级后台风格、信息密度适中、必须可在 iframe 独立预览、不依赖外部接口、给每个可点选区块加 `data-block="<人类可读label>"`。
- 读取 endpoint：`GET /applications/{app_id}/prototype/{prototype_id}` → 返回 HTML 内容。
- 列表（可选，本切片可省）：`GET /applications/{app_id}/prototypes`。

**新建：原型存储**
- 新表 `app_prototype`：`id, app_id(FK), version(int), html_content(TEXT), source_spec_version(int), created_at, created_by`。
- 为何不复用 `save_dev_spec` 落盘：那是 workspace 文件存储（`.dev-spec/<project>/mockup.html`），与 app_id 中心模型不一致；用 DB 表更贴合本切片 app 中心 + 可版本化。

---

## 6. 数据流（关键链路）

### 6.1 对话改需求
```
ConversationPane 输入 → POST /applications/{appId}/spec-chat-stream (SSE)
  → 后端 LLM → patch → update_spec_section() → 草稿 draft_version+1
  → SSE 事件 {token..., spec_change:{section}} 回前端
  → SpecDesignPanel 收到 spec_change → 重拉对应章节 section-content → 刷新
```

### 6.2 生成原型
```
PreviewTab「生成原型」→ POST /applications/{appId}/prototype/generate (SSE)
  → 后端读需求基线 → LLM 产单文件 HTML → 存 app_prototype
  → SSE {progress...} → 完成 {type:'prototype_ready', prototype_id}
  → PreviewTab GET /prototype/{id} → iframe srcdoc 渲染
```

### 6.3 点选回填
```
原型 HTML 内注入脚本(生成时拼入):
  document.querySelectorAll('[data-block]').forEach(el =>
    el.onclick = () => parent.postMessage(
      {type:'ai-coding:select', label: el.dataset.block}, '*'))
父窗 PreviewTab: window.addEventListener('message', e => {
  if (e.data?.type === 'ai-coding:select')
    emit('select-block', e.data.label) })  // → 回填对话输入框
```

---

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| spec_chat LLM 配置不可用 | 复用现有 fallback：mock parser（`spec_chat.py` 已有 `_real_llm_enabled()` + mock 兜底）|
| HTML 原型生成失败 / LLM 超时 | 预览 Tab 显错误态 + 「重试」按钮；SSE 推 `error` 事件；不留半成品原型 |
| 生成的 HTML 不合法 / 空 | 后端基本校验（非空、含 `<html`/`<body`）；失败则返 error 不入库 |
| `app_id` 缺失或无权限 | 复用 `_load_app_and_check_view()` 权限校验；前端引导先选/建应用 |
| iframe 加载失败 | 显占位 + 重新生成入口 |
| SSE 断连（参考既往 deeplink 跳页断 SSE 教训）| 前端断连重连 / 显「生成中断，点重试」|

---

## 8. 安全（来自 vibe-coding-spec §11 + PRD 工具最小权限）

- **iframe sandbox 隔离**：`sandbox="allow-scripts"`，**不开 allow-same-origin** → 原型 JS 无法读父窗 cookie/localStorage/会话。
- **原型不含密钥**：生成 prompt 明确禁止输出任何 token/key/真实接口地址；只用 mock 数据。
- **用户输入限制**：对话输入做长度上限 + 基本敏感信息提示（复用现有 spec_chat 限制）。
- **LLM 输出不执行**：原型 HTML 仅在 sandbox iframe 渲染展示，绝不作为可执行命令进入后端。
- **不影响现有模块**：新页面 + 新 endpoint + 新表，零侵入 ChatPage / OnlineCodingWorkspacePage / Builder / 现有 spec_chat 链路。

---

## 9. 验收标准（demo 必须走通这一条）

1. 进入 `/ai-coding/{已有appId}` → 看到左对话 + 右 6 Tab（需求 Tab 默认激活，显 11 章需求基线）。
2. 左对话输入「给供应商加个风险等级字段」→ 需求 Tab 第 3 章（数据模型）实时多出该字段。
3. 切到预览 Tab，点「生成原型」→ 几秒内 iframe 显示带该字段的企业级后台 HTML 界面（有 mock 数据）。
4. 点原型里某张卡片 → 对话输入框自动回填「我选中了：{卡片名}」。
5. 接着输入「这张卡片改成红色预警」→ 再次生成原型 → 看到更新。
6. 刷新页面 → 需求基线草稿 + 最近原型不丢。
7. 后 4 个 Tab 点击 → 显「敬请期待」占位，不报错。

**技术验收**：后端 endpoint 有鉴权；原型 HTML iframe sandbox 隔离；新增表/接口零影响现有 Builder/Coding/Requirements 模块；前端刷新可恢复。

---

## 10. 实现切分建议（供 writing-plans 参考，可并行）

- **A 后端·原型生成**：`app_prototype` 表 + `POST/GET /prototype/*` endpoint + LLM prompt + 安全校验。（独立，可先行）
- **B 前端·工作台骨架**：`AICodingWorkspace.vue` + `WorkspaceTabs.vue` + 路由 + 左右 splitter + `ConversationPane` 空壳（仅 UI、不接 SSE）+ 4 占位 Tab。（独立）
- **C 前端·需求 Tab 接线**：把 `SpecDesignPanel` 嵌入需求 Tab + 左对话对接 `spec-chat-stream` SSE + spec_change 刷新。（依赖 B）
- **D 前端·预览 Tab**：`PreviewTab.vue` iframe sandbox + 生成触发(SSE) + 点选回填。（依赖 A、B）
- **E 集成·E2E**：chrome-devtools 实测 §9 验收链路。（依赖 A-D）

依赖：A、B 可并行起步；C 依赖 B；D 依赖 A+B；E 最后。

---

## 11. 待澄清 / 后续切片预留

- 入口接线（Landing picker → `/ai-coding`）→ 切片 ②
- 全 11 章对话驱动 + 点选锚定到具体章节 → 切片 ②
- 原型从「整页重生成」升级到「局部重生成 / 版本对比」→ 切片 ③
- 原型 → 真实 aPaaS 应用（接 spec_apply 全 8 动作）→ 切片 ④+
