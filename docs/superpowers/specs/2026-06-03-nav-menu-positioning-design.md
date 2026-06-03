# 一级导航菜单定位优化 — 设计

> 日期: 2026-06-03
> 范围: 一级导航 + AI Builder 与首页融合。不碰命令面板设置类入口归位、stub 页处置、二级导航。
> 状态: 已实现(待提交)

## 背景

原一级导航 4 项:首页 / 应用资产库 / AI Builder / 自开发资产库。问题:

- 新建应用三个入口重叠(首页 `/`、AI Builder 菜单 → `/ai-chat`、`/chat`)。
- "AI Builder" 既是平台品牌名又是菜单名,有歧义。
- 关键:`/ai-chat`(AIChatPage)左栏的「历史会话」(AIChatSession,`aiChatApi.listSessions`)只有 AI Builder 菜单这一个一级入口 —— 它和 `/chat` 侧栏的「应用」是两套数据。先前一版方案砍掉 AI Builder 菜单,导致历史会话失去入口(已纠正)。

## 决策:AI Builder 与首页融合

把首页 `/`(Landing 的新建)和 `/ai-chat`(对话 + 历史会话)融合成一个入口:

| 菜单 | 路由 | 定位 |
|---|---|---|
| AI Builder | `/` | 融合页:新建对话(hero + 输入框)+ 左栏历史会话。`/` 与 `/ai-chat` 同组件(AIChatPage)。 |
| 应用资产库 | `/apps` | 已建成应用,点进工作室 `/chat` 继续改 / 部署。 |
| 自开发资产库 | `/workspace-catalog` | 二次开发工作区 + 资产,点开全屏 IDE。 |
| 平台管理(底部,管理员) | `/platform-admin` | 平台运维配置。 |

- 进 AI Builder:没选会话 = hero + 输入框(新建);左栏 SessionSidebar 历史会话长驻,点开继续。
- 新建:输入需求 → 就地建会话进对话(`onStartNew`)→ 生成应用后跳 `/chat`(不变)。
- 删掉原来分开的「AI Builder」菜单项;`/ai-chat` 路由保留(start-dev 二次开发 dispatch 还在用)。
- 命名用温和版,沿用现有词。

## 实现(已落地)

- `router/index.ts`:`/`(Home)的 component 从 Landing → AIChatPage。
- `AIChatPage.vue`:空状态从"👋 AI Chat"换成 hero + `<LandingComposer @submit="onStartNew">`;新增 `onStartNew`(建会话 + 发首条,复用 onMounted 里 Landing prompt 那套);加 hero 样式(`.welcome-hero/.welcome-badge/.welcome-title/.welcome-sub`)。
- `LandingComposer.vue`:submit 从 `router.push('/ai-chat')` 改成 `emit('submit', {prompt, files})`(就地新建,删 router/previewStore 依赖)。
- `RailSidebar.vue`:home 项 label "AI Builder"、icon `chat`、path `/`;`isActive` 让 `/` 在 `/ai-chat*` 也高亮。
- `ShellTopBar.vue` 面包屑 `/` → "AI Builder";`BuilderCommandPalette.vue` 第 1 项 → "AI Builder"。
- `Landing.vue`:退役(无引用,死文件,待删)。

## 验证

preview 实测:`/` 渲染融合页(hero + 输入框 + 左栏历史会话 + 菜单高亮 AI Builder),无编译错;输入需求点发送 → 建会话(URL → `/ai-chat/:id`)进对话视图,`onStartNew` 工作。

## 不在本次范围

- 命令面板 6 个设置类入口(模型配置 / 平台环境 / 成员 / DevOps)归位。
- stub 页(智能体配置 / 设计文档 / 行业知识库 / MCP)处置。
- TabStrip 旧 tab 持久化残留(localStorage,新用户无,可加一次性迁移)。
- 二级导航(ApaasMenuSidebar / SessionSidebar)命名。
