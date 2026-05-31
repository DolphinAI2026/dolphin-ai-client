# Handoff: aPaaS Builder AI — Information Architecture Redesign

## 概要

这是 `apaas-builder-ai`（得帆云低代码搭建助手）的完整 UX / 信息架构重设计。把原有的 8 个分散模块整合成一套**项目 → 应用 → SPEC → 部署**的清晰主链路，并新增 **行业知识库（Ontology）**、**智能体配置中心**、**运行与发布** 等关键功能。

**目标读者**：Claude Code（或人类开发者），负责把这套设计落地到真实的 `apaas-builder-ai` 代码仓库（Vue 3 + TypeScript + Element Plus + Pinia）。

---

## ⚠️ 关于设计文件的重要说明

`source/` 目录里的文件是 **HTML / React 设计原型**，不是生产代码。

它们的作用是**像素级地展示意图**——颜色、间距、布局、交互流。

**你的任务**：在原仓库的 Vue 3 + Element Plus 环境里**重新实现**这些设计，**而不是把 React 代码翻译过去**。
- 用现有 Vue 组件、Pinia store、Vue Router 实现
- 用 Element Plus 控件，必要时用 CSS 包装样式
- 复用现有 `frontend/src/styles/theme-vars.css` 的 token，缺什么补什么

---

## 保真度（Fidelity）

**高保真（Hi-Fi）**。具体表现：
- 颜色 / 字号 / 间距 / 圆角 / 阴影都是终稿
- 复杂交互（角色切换、对话流、蓝图同步、部署确认、Onboarding）都已实现可点击原型
- 唯一未实现：真实数据流（用 mock data 模拟）、跨页状态持久化（仅 theme + project 保存到 localStorage）

实现时建议**像素级对齐**：背景色、卡片圆角、阴影深度、字号差异都按设计稿走，不要凭感觉调整。

---

## 工程总览

### 新增页面 / 路由

| 路由 | 名称 | 关键作用 | 设计文件 |
|---|---|---|---|
| `/` | 新建（Landing） | AI 居中入口，3 模式 picker + 关系流图 | `page-landing.jsx` |
| `/projects` | 项目列表 | 一等公民容器，按客户实施分组 | `page-projects.jsx` |
| `/projects/:id` | 项目详情 | 概览 / 应用 / 成员 / 行业包 / 环境 5 个 Tab | `page-projects.jsx` (`ProjectDetail`) |
| `/apps` | 应用列表 | 筛选 + 卡片 / 列表双视图 | `page-apps.jsx` |
| `/chat` | 睿鲸 AI Builder | 三列：对话历史 + 主对话 + 应用蓝图 | `page-chat.jsx` |
| `/coding` | 睿鲸 AI Coding | 组件生成工厂，纯聊天驱动 | `page-coding.jsx` |
| `/vibe` | Vibe Coding | code-server 风格全代码 IDE | `page-vibe.jsx` |
| `/specs` | 设计文档 | SPEC 版本管理 + 模板 | `page-specs.jsx` |
| `/industry` | 行业知识库 | Ontology 视图，可视化业务对象图 | `page-industry.jsx` |
| `/agents` | 智能体配置 | 3 个 Agent 的 Skills + MCP + Knowledge 绑定 | `page-agents.jsx` |
| `/marketplace` | 组件市场 | 表单组件 / 页面 / 后端接口 | `page-misc.jsx` (`Marketplace`) |
| `/mcp` | MCP 管理 | Model Context Protocol 服务器接入 | `page-misc.jsx` (`MCP`) |
| `/runtime` | 运行与发布 | 沙箱池 / 流水线 / 环境 / 部署历史 | `page-runtime.jsx` |
| `/admin` | 平台管理 | 跨租户的资源管理 | `page-misc.jsx` (`Admin`) |
| `/login` | 登录 | 账号密码 + SSO | `page-misc.jsx` (`Login`) |

### 跨页组件

| 组件 | 文件 | 说明 |
|---|---|---|
| 侧边栏 | `shell.jsx` (`Sidebar`) | 4 个分组：搭建 / 开发 / 知识 & 智能体 / 管理 |
| 顶栏 | `shell.jsx` (`TopBar`) | 项目切换器 + 面包屑 + 全局搜索 + 主题切换 |
| Cmd+K 命令面板 | `shell.jsx` (`CmdK`) | ⌘K / `/` 唤起 |
| 部署确认 Modal | `enhancements.jsx` (`DeployModal`) | 三段式：选环境 → 看 diff → 确认 |
| Onboarding 引导 | `enhancements.jsx` (`Onboarding`) | 首次登录 3 步 tour |
| Tooltip / Term | `enhancements.jsx` | 术语带 `?` 提示 |

---

## 关键架构决策

实现时务必遵守这几条：

### 1. 项目（Project）是一等容器
- 现仓库已有 `api/projects.ts` 和 `ProjectOverview.vue`，请**升级它们**而不是绕过
- 所有应用 / 对话 / SPEC 都归属于某个项目
- 顶栏的「项目切换器」决定当前上下文，影响所有列表的过滤范围
- 路由结构建议：`/projects/:projectId/apps`、`/projects/:projectId/chat/:convId` 等（设计稿为简化用扁平路由，实际可以嵌套）

### 2. **不要按角色过滤导航**
- 之前的实施顾问 / 开发 / 管理员 角色 pill 已经移除
- 所有人看到完整 11 项导航
- 角色概念**降级到项目级**：在 `项目 → 成员` Tab 维护，仅用于权限和通知，不影响 UI
- 项目内角色：项目负责人 / 实施顾问 / 前端开发 / 后端开发 / 客户业务方 / 客户 IT / 观察员

### 3. 三个智能体边界要清晰
| Agent | 用户 | 写不写代码 | 产物 |
|---|---|---|---|
| **睿鲸 AI Builder** | 业务顾问 | 否 | SPEC 设计文档 + aPaaS 应用 |
| **睿鲸 AI Coding** | 业务顾问 / 开发 | 否（AI 自动写） | UMD 组件包 → 组件市场 |
| **Vibe Coding** | 开发 | 是（用户手写 + AI 协助） | 直接编辑代码 + git commit |

每个 Agent 在 `/agents` 页面有独立配置：Model + System Prompt + Skills + MCP + Knowledge Sources。

### 4. 行业知识库 → AI Builder 闭环
- `/industry` 页面定义行业包（业务对象 + 关系 + 流程 + 字典）
- 项目可绑定 1 个行业包（在 `项目详情 → 行业包` Tab）
- AI Builder 生成 SPEC 时**优先复用**包内对象
- Chat 页对话流顶部有青色提示条："本会话引用 制造装备 v2.1 (12 业务对象)"

### 5. 低代码组件不支持平台内实时预览
- 睿鲸 AI Coding 不要做"实时组件预览"
- 改为「**生成产物清单 + 接入说明**」：文件 diff、UMD 体积、3 步上线引导
- 因为得帆云平台架构上不支持自开发组件预览

### 6. 沙箱 + CI/CD 在 `/runtime`
- 睿鲸沙箱（2C/4G）+ Vibe 沙箱（4C/8G）默认 2h 空闲回收
- 4 个 Tab：沙箱池 / 流水线 / 平台环境（dev/test/prod 一对一固化）/ 部署历史
- Vibe 顶部 chip + 睿鲸状态条都有沙箱信息

---

## 设计令牌（Design Tokens）

所有 token 在 `source/styles.css` 顶部定义。**必须按这个色板实现**：

### 主色（紫罗兰 indigo-violet）
```
--brand-50:  #F2F0FE   --brand-500: #5B5BD6   ← 主色
--brand-100: #E6E3FD   --brand-600: #4747C2
--brand-200: #CDC8FB   --brand-700: #38379E
--brand-300: #ABA2F7   --brand-800: #2D2C7B
--brand-400: #847AF0
```

### AI 强调色（青色）
```
--ai-50:  #ECF8FB    --ai-400: #34A4C2
--ai-100: #D2EEF5    --ai-500: #1D89A8   ← AI 元素主色
--ai-200: #A5DDEB    --ai-600: #156F8C
--ai-300: #6BC2DA    --ai-700: #105A73
```
青色用在所有 AI 相关元素：Landing 顶部 AI 徽标、AI Builder 对话头像、知识源提示条、Onboarding tip 框、行业知识库引导卡。

### 状态色
- Emerald `#10A37F`（成功 / 已部署 / 测试环境）
- Amber `#D97706`（警告 / 草稿 / 测试环境）
- Rose `#DC2626`（错误 / 生产环境 / 危险操作）
- Sky `#0284C7`（信息 / 测试环境）

### 中性色
浅色主题 + 深色主题完整 token 见 `styles.css :root` 和 `html[data-theme="dark"]`。深色必须实现。

### 字体
- 中英文 sans：`Inter`, `PingFang SC`, 系统字体
- 等宽：`JetBrains Mono`, `SF Mono`, `Menlo`
- 字号阶梯：22/17/15/14/13/12.5/12/11.5/11/10.5
- 行高：1.55（body）、1.2（titles）、1.65（code）

### 圆角
- 卡片：12px
- 按钮 / 输入框：8px
- 大容器：14-16px
- 头像 / 徽标：50% / 12-16px

### 阴影
四档：`--shadow-xs`（卡片默认）/ `--shadow-sm` / `--shadow-md`（hover）/ `--shadow-lg` / `--shadow-xl`（modal）

---

## 主要交互流程

### A. 首次登录 Onboarding
1. 检测 `localStorage['aPaaS:seenOnboarding']` 不为 `'1'`
2. 弹 3 步 modal：欢迎流程 → 关键概念 → 选择角色（4 张卡）
3. 关闭后写 `localStorage['aPaaS:seenOnboarding'] = '1'`

### B. 部署到 aPaaS（关键流程）
1. Chat 页点「部署到平台」按钮 → 打开 `DeployModal`
2. 3 段式：
   - **选环境**：开发 / 测试（默认）/ 生产，选生产时**强制二次确认**（输入应用 code）
   - **看 Diff**：列出本次 SPEC v2 → v3 的所有 + / ~ / - 变更
   - **看影响**：用户数 / 流程数 / 数据迁移 / 预计耗时
3. 点确认后进入「部署进行中」状态：3 阶段进度条 + 实时步骤文案
4. 完成后显示「部署成功」+ 后续操作（在 aPaaS 打开 / 晋级到生产 / 关闭）
5. 失败必须自动备份 + 一键回滚

### C. 项目切换
- 顶栏左侧紫色色条 + 项目名按钮
- 点击展开浮层，列出所有项目 + 各项目阶段 chip
- 切换后 localStorage 持久化
- 切换后所有列表（应用、对话、SPEC、部署历史）应过滤到当前项目

### D. 主题切换
- 顶栏右上角太阳/月亮 icon
- `document.documentElement.setAttribute('data-theme', 'light' | 'dark')`
- 持久化到 `localStorage['aPaaS:theme']`

### E. Cmd+K 命令面板
- `⌘K`（Mac）/ `Ctrl+K`（Windows）/ `/`（非输入框焦点）唤起
- 三组：导航 / 快捷操作 / 最近
- ↑↓ 选择，Enter 执行，Esc 关闭

---

## 文件清单（实现优先级）

按这个顺序在 `apaas-builder-ai` 仓库里逐步落地：

### P0 — 必须先做（架构层）
1. `frontend/src/styles/` — 复制 `source/styles.css` 的 token 系统（深浅双主题）
2. `frontend/src/components/AppSidebar.vue` 大改 → 实现 `Sidebar` 的 4 组导航
3. `frontend/src/components/TopBar.vue` 大改 → 加项目切换器
4. `frontend/src/router/index.ts` → 加 `/projects`、`/agents`、`/specs`、`/industry`、`/runtime` 等路由
5. 全局：移除现有的角色过滤逻辑（如果有）

### P1 — 核心页面（搭建主链路）
6. `frontend/src/views/Landing.vue` 大改 → 3 模式 picker + 关系流图 + 应用卡片
7. `frontend/src/views/ChatPage.vue` 大改 → 三列布局 + 应用蓝图同屏（替代 5 Tab） + 知识源提示条 + 部署确认 Modal
8. `frontend/src/views/Apps.vue` 改进 → 已有筛选 + 卡片 / 列表双视图
9. 新建 `views/Projects.vue` + `views/ProjectDetail.vue`
10. 新建 `views/Specs.vue` + 集成现有 SPEC 模板能力

### P2 — 开发者侧
11. `frontend/src/views/CodingPage.vue` 大改 → 移除现有的"组件预览"，改成"生成产物清单 + 接入说明"
12. 新建 `views/VibePage.vue`（嵌入 code-server iframe + 右侧 AI 对话面板）
13. 新建 `views/Agents.vue` — 3 个智能体配置中心
14. 新建 `views/MCP.vue`（已有 marketplace 可参考）

### P3 — 沉淀与运维
15. 新建 `views/Industry.vue` — 行业知识库 + Ontology SVG 图
16. 新建 `views/Runtime.vue` — 4 个 Tab
17. Onboarding 引导组件 + 首次登录触发

---

## 数据契约（Mock → Backend）

`source/data.js` 里所有 mock 数据都对应真实后端接口。落地时：

| Mock 字段 | 真实接口 |
|---|---|
| `apps` | `frontend/src/api/application.ts` 已有 |
| `conversations` | `api/conversation.ts` 已有 |
| `specs` | 需新建 `api/specs.ts`（SPEC 版本管理） |
| `projects` | `api/projects.ts` 已有，需扩展 members / industry binding |
| `agents` | 需新建 `api/agents.ts` |
| `mcpServers` | 需新建 `api/mcp.ts` |
| `industryPacks` | 需新建 `api/industry.ts` |
| `sandboxes` | 需新建 `api/runtime.ts` |
| `pipelines` | 需新建 `api/pipelines.ts` |
| `environments` | `api/platformEnv.ts` 已有 |

后端需对应实现 SPEC 版本表、Project 表、Agent 配置表、MCP 注册表、Industry Pack 表、Sandbox 调度等。

---

## Element Plus 映射

设计稿用的是 HTML/CSS，实际实现替换为 Element Plus：

| 设计稿元素 | Element Plus |
|---|---|
| `<button class="btn">` | `<el-button>` |
| `<input class="input">` | `<el-input>` |
| `<select>` | `<el-select> + <el-option>` |
| 自定义 Modal (`DeployModal`) | `<el-dialog>` |
| Tooltip (`Tooltip` 组件) | `<el-tooltip>` |
| Cmd+K | 自实现（Element Plus 没有命令面板） |
| 表格 (Apps list / Sandbox / Deployments) | `<el-table>` |
| Toast / Message | `ElMessage` |
| 表单校验 | `<el-form>` + rules |

CSS class 命名（`.btn-primary`、`.card`、`.badge` 等）**保留**，作为 Element Plus 之上的工具类。

---

## 不要做的事

- ❌ **不要用 React** — 原仓库是 Vue 3。`source/*.jsx` 仅作视觉参考
- ❌ **不要按角色隐藏菜单** — 项目级权限取代之
- ❌ **不要做组件实时预览** — 平台不支持
- ❌ **不要新增"租户切换"** — 一租户对应一得帆云租户，固化
- ❌ **不要丢失现有功能** — `ChatPage.vue` 已有的增量更新、ConfigDiff、StructuredDoc 渲染等都要保留
- ❌ **不要写中文 curly quotes 在 JSX/Vue 模板属性里** — 用 `'…'` 或 `{`…`}` 包裹

---

## 验证 checklist

实现完成后逐项过：

- [ ] 浅色 + 深色主题切换无破绽
- [ ] 项目切换器持久化生效
- [ ] Onboarding 首次弹出，关闭后不再弹
- [ ] Cmd+K 跳转 / 操作正确
- [ ] Chat 页应用蓝图与对话同屏，知识源 chip 显示行业包
- [ ] 部署 Modal 完整三段式 + 生产环境二次确认
- [ ] 项目详情 5 个 Tab 切换流畅
- [ ] 智能体配置页可保存修改
- [ ] 行业知识库 Ontology 图正确渲染 9 节点 8 边
- [ ] 运行与发布页 4 个 Tab 全部数据正确
- [ ] Element Plus 表单 / 表格 / 弹窗的样式与设计稿一致

---

## 设计稿如何使用

1. **打开 `source/aPaaS Builder AI — Redesign.html`** 在浏览器里看完整原型
2. 切换路由（左侧导航或 Cmd+K）逐页对照
3. 用 DevTools 看具体颜色 / 字号 / 间距值
4. JSX 文件主要看**结构 + 状态管理**，CSS 文件看**视觉细节**

设计稿用的是 React + Babel runtime，仅用于演示。**生产实现一律走 Vue 3**。

---

## 联系方式

设计稿在项目内可访问：`aPaaS Builder AI — Redesign.html`
如有疑问，参考 `frontend/src/` 现有代码结构，保持工程一致性。
