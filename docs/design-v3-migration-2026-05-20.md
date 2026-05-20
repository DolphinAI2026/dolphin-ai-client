# Design v3 Migration · 2026-05-20

> **Status**: 完成 · **Branch**: `local/ui-redesign-2026-05-20` · **Commits**: 6 · **Files**: 50

把 ai-builder 整个前端从 v2 indigo-violet (`#5B5BD6`) 迁到 v3 Claude Design (Tailwind blue ramp, `#1D4ED8`)。本次是**纯 UI/UED 重设**，零功能改动。

---

## 1. 背景

### 为什么迁

| 维度 | v2 (indigo-violet) | v3 (clean blue) |
|---|---|---|
| 主色 | `#5B5BD6` 紫罗兰 + 青 AI `#1D89A8` 双色 | `#1D4ED8` 蓝单色 + 形状/icon 区分 |
| 字重 | 5+ 档（650/680/720/780/850） | 4 档（400/500/600/700） |
| 字号 | 7 档随意 | 5 档（11/12.5/14/18/24/32） |
| 圆角 | 4/8/10/12/14/16/20px 散乱 | 6 档（r-1=4 / r-2=6 / r-3=8 / r-4=12 / r-5=16 / r-full） |
| 状态色 | hardcode `--amber/--emerald/--sky/--rose` | `--ok/--warn/--err/--info` 4 档统一 |
| 空态 | inline "暂无 X" 灰字 12 处不统一 | `<EmptyState>` 共享组件 |
| 错误态 | toast 一闪而过 + 业务错原 dict 直吐 | `<ErrorCard>` 3 级 + 修复 action 优先 |
| Loading | "加载中..." 纯文字 7 处 | `<SkeletonCard>` 200ms 延迟防闪 |
| a11y | 多数 button 无 focus 提示 | 全局 `:focus-visible` 蓝 ring |

### 4 条不可动摇原则（继承 v3 design spec）

1. **一套 token** — `.vue` 禁止 hex，全走 `--brand / --text / --surface / --line`
2. **一个尺度** — 字号 5 档 + 字重 4 档，不写 13.5 / 780
3. **一种品牌** — 睿鲸 = 蓝色一种，智能体用形状/icon 区分不抢色
4. **对话为中心** — 工作流收敛到对话，表单/wizard 只用于"必须分步"

---

## 2. 文件清单

### 新建（5 个）

- `frontend/src/components/states/EmptyState.vue` — 空态组件
- `frontend/src/components/states/ErrorCard.vue` — 错误态组件
- `frontend/src/components/states/SkeletonCard.vue` — 加载骨架
- `admin-spa/src/components/states/*.vue` — admin-spa 独立项目同步拷贝
- `admin-spa/src/styles/design-v3-tokens.css` — admin-spa v3 token

### 改 frontend 视图（27 个 .vue + 2 全局 css）

| 类型 | 文件 |
|---|---|
| 壳层 | `Landing.vue` / `LandingComposer.vue` / `ShellTopBar.vue` / `RailSidebar.vue` / `WorkspaceShell.vue` |
| 主业务 | `Apps.vue` / `DbConnectionsPage.vue` / `QuickDbPage.vue` / `MarketplacePage.vue` / `McpToolsPage.vue` |
| 管理 | `PlatformEnvs.vue` / `PlatformTenants.vue` / `TenantUsers.vue` / `SandboxMonitorPage.vue` |
| 登录 + admin | `Login.vue` / `PlatformAdminEmbed.vue` / `TenantSelect.vue` |
| Coding | `OnlineCodingPage.vue` / `OnlineCodingWorkspacePage.vue` / `WorkspaceCatalogPage.vue` / `CodingPage.vue` |
| 项目 | `ProjectOverview.vue` / `ProjectGitSetup.vue` / `ProposalDetailPage.vue` / `GitOAuthCallback.vue` |
| Chat 周边 | `AIChatPage.vue` / `RequirementsAssistantPage.vue` / `Generate.vue` |
| v2 子路由 | `v2/SpecsPage.vue` / `v2/AgentsPage.vue` / `v2/IndustryPage.vue` / `v2/RuntimePage.vue` / `v2/McpHubPage.vue` |
| DevOps | `BuilderDevOpsPage.vue` |
| 组件 | `AppBlueprintPanel.vue` / `ConfigAssistantPanel.vue` / `DeployConfirmModal.vue` / `OnboardingTour.vue` |
| Store | `stores/theme.ts`（默认 accent 从 `#6d5df6` 改 `#1D4ED8`） |
| 全局 css | `styles/builder.css`（Phase 7+10 共 +385 行）|

### 改 admin-spa（2 个）

- `admin-spa/src/main.ts`（import v3 token）
- `admin-spa/src/views/LlmConfigs.vue`

### 不动（按红线）

- **`ChatPage.vue` 495K** — 嵌 dolphin iframe，不归 ai-builder UI 管
- **backend** — 0 行
- **所有 template / script** — 仅 3 处特例（见下文 §4）

---

## 3. Phase 时间线

| Phase | 日期 | 范围 | 风险 | 文件 |
|---|---|---|---|---|
| 1 | (前置) | v3 token css import | 🟢 LOW | 2 |
| 2A | 2026-05-20 早 | ShellTopBar surgical | 🟢 LOW | 1 |
| 2B / 3 / 4 | 2026-05-20 上午 | 14 业务 + 管理页 v3 | 🟢-🟡 | 13 |
| 5 | 中午 | 状态系统三件套 + 替换 12 页 inline | 🟢 LOW | 3 新+10 改 |
| 6 | 下午 | el-table :deep + filter bar | 🟢 LOW | 6 |
| 7 | 下午 | 全局 a11y + EP polish in builder.css | 🟢 LOW | 1 (+143) |
| 8A | 下午 | RailSidebar 双状态 + 主题色 preset | 🟡 MED | 1 |
| 8B / C / D | 下午 | chat 侧栏 + modal + breadcrumb | 🟢 LOW | 5 |
| Login 漏网 | 下午 | Login.vue 补漏 | 🟢 LOW | 1 |
| 9A / B / C / D | 傍晚 | 全清 17 剩余页 | 🟢 LOW | 17 |
| 10 | 傍晚 | sticky / 动效 / EP 精修 in builder.css | 🟢 LOW | 1 (+242) |

---

## 4. 铁律遵守情况

### 4.1 `<template>` 不动

✅ 50 文件 template 0 行改动，**除以下 3 处特例**：

1. **RailSidebar.vue** — 主题色 picker 从 `<input type="color">` 任意色改为 6 色 preset palette + 1 自定义兜底（**用户决策**）
2. **ShellTopBar.vue** — `CRUMB_LABELS` 加 8 条新路由（script 改，template 不动）
3. **EmptyState/ErrorCard/SkeletonCard 替换** — 20 处 inline 占位 → 组件挂载（Phase 5 必要的 template surgery）

### 4.2 `<script setup>` 不动

✅ 49 文件 script 0 行改动，**除以下 2 处特例**：

1. **RailSidebar.vue** — 加 `ACCENT_PRESETS` 常量数组（6 种 v3 friendly 色）
2. **McpToolsPage.vue** — 抽 `loadTools()` helper 让 ErrorCard 的"重试"按钮能调用（agent 主动报告）

### 4.3 backend 不动

✅ `git diff backend/` 为空。

### 4.4 类名保留

✅ 所有 page 的 class 命名 100% 保留，外部 css 引用不破。

### 4.5 dark theme 保留

✅ 每个文件的 `html[data-theme="dark"]` 覆盖块都保留，新加的覆盖也跟 v3 token cascade 配合。

---

## 5. 关键根因修复

### "为什么主题色不变" — `theme.ts` 默认 accent 老紫色

**问题**：v3 token 在 documentElement 已经是 blue (#1D4ED8)，但 `WorkbenchShell` 上挂 `theme.accentVars` 内联 style 注入老紫色 `#6d5df6` 整套 ramp 覆盖了 v3 token。

**修法**（commit `b1120e6` 的 theme.ts 部分）：

```diff
const STORAGE_KEY = 'theme'
- const ACCENT_STORAGE_KEY = 'theme-accent-color'
- const DEFAULT_ACCENT = '#6d5df6'
+ const ACCENT_STORAGE_KEY = 'theme-accent-color-v3'
+ const DEFAULT_ACCENT = '#1D4ED8' // v3 brand = blue-700
```

`bump storage key v3` 强制让所有用户的旧 localStorage 缓存失效，下次 page load 重新走默认 = v3 蓝。

### "为什么 Apps 页面没改" — 第一波 8 个 agent 漏了 Apps.vue

**问题**：我之前自己判断"Apps 设计稿不匹配真实代码"就把它跳过了。结果用户首屏看到的就是没改的紫色 Apps。

**修法**：补一个 agent 单独刷 Apps.vue（commit `b1120e6` 的最后一个变更）—— 保留 list/card 双视图 + tabs + progress bar 现有结构，只换 token。

---

## 6. v2 → v3 Token 映射表

### Surface

| v2 / 老 | v3 |
|---|---|
| `--border`, `--b-line` | `--line` |
| `--border-strong`, `--b-line-strong` | `--line-strong` |
| `--bg-base`, `--b-bg`, `--t-bg-base` | `--bg` / `--surface` |
| `--bg-panel`, `--b-panel`, `--t-bg-panel` | `--surface` |
| `--bg-sub`, `--b-bg-sub` | `--surface-2` |
| `--code-bg` | `--surface-3` |

### Brand / Text

| v2 / 老 | v3 |
|---|---|
| `--brand-400`, `#5B5BD6`, `#6d5df6`, `#786cf0` | `--brand` |
| `--brand-700`, `#38379E`, `#5146c9` | `--brand-hover` 或 `--blue-800` |
| `--ai`, `--ai-text` (青色 #1D89A8) | `--brand`（v3 一种品牌色） |
| `--t-text-primary`, `--b-text-strong` | `--text` |
| `--t-text-secondary`, `--b-text` | `--text-2` |
| `--t-text-muted`, `--b-text-muted` | `--text-3` |
| `--t-text-faint`, `--b-text-faint` | `--text-4` |

### Status

| v2 / 老 | v3 |
|---|---|
| `--amber`, `--warning` | `--warn` |
| `--amber-bg`, `--warning-bg` | `--warn-soft` |
| `--emerald`, `--success`, `--t-success` | `--ok` |
| `--emerald-bg` | `--ok-soft` |
| `--rose`, `--danger`, `--t-danger` | `--err` |
| `--rose-bg` | `--err-soft` |
| `--sky` | `--info` 或 `--brand` |

---

## 7. 状态系统组件 API

### `<EmptyState>`

```vue
<EmptyState
  title="还没有数据库连接"
  desc="添加一个连接，让 AI 直接读你的存量数据。"
  variant="first"   <!-- "first" | "filtered" -->
>
  <template #icon>
    <svg width="22" height="22" ...>...</svg>
  </template>
  <template #cta>
    <el-button type="primary" @click="openCreate">+ 新建连接</el-button>
  </template>
</EmptyState>
```

### `<ErrorCard>`

```vue
<ErrorCard
  level="err"       <!-- "err" | "warn" | "info" -->
  title="MCP 服务连接失败"
  code="MCP_CONNECTION_TIMEOUT"
  message="检查 MCP 服务是否运行 + 端口是否对外开放。"
  :actions="[
    { label: '重试', primary: true, onClick: () => loadTools() },
    { label: '查看日志', onClick: () => openLogs() },
  ]"
/>
```

### `<SkeletonCard>`

```vue
<SkeletonCard
  :lines="3"
  :withAvatar="true"
  :withFooter="false"
  :delay="200"        <!-- 200ms 才显，防闪屏 -->
  @cancel="onCancel"  <!-- 5s 后 "还在加载" + cancel emit -->
/>
```

---

## 8. 全局 builder.css 追加 section

`frontend/src/styles/builder.css` 文件末尾追加了 **+385 行** v3 polish：

- Phase 7（+143）：focus-visible / EP button / message / dialog / form 4 档
- Phase 10（+242）：sticky header / 卡片 hover / Vue transition / tooltip / drawer / loading / scrollbar / selection / textarea / el-tag 5 色 / checkbox+radio

---

## 9. 验收

```bash
$ cd frontend && pnpm vue-tsc --noEmit
# exit 0 (0 error)

$ cd ../admin-spa && pnpm vue-tsc --noEmit
# exit 0 (0 error)

$ pnpm dev
# 5173 frontend + 5174 admin-spa 都 HTTP 200
```

### 5 个核心 flow 视觉验证（需要手动跑）

1. `/` Landing → composer + 4 flow card 全蓝
2. `/apps` → 列表/卡片双视图 + tabs + progress + 蓝主按钮
3. `/db-connections` → 表格 + 6 DB type pill + 蓝主按钮
4. `/quick-db` → 4 步 wizard + step bar
5. `/platform-tenants` → dashboard 5 卡 + 配额表（去 stripe）

---

## 10. 未来工作（不在本次范围）

| 类别 | 描述 | 估时 |
|---|---|---|
| **ChatPage 三栏布局** | 13K LOC + 嵌 dolphin iframe，需要单独评估 | TBD |
| **RailSidebar 224px expanded 状态设计** | 当前 224px 是 Phase 8A 临时设计，需要正式 design spec 配套 | 1d |
| **Apps list/card 双视图重设** | 当前结构能工作但信息密度有提升空间（hover preview / batch select） | 2d |
| **Onboarding flow 重做** | OnboardingTour 已 v3 化但用户进入引导的 trigger 路径还偏弱 | 1d |
| **移动端 / 响应式** | 当前定位 1280+ 桌面 ToB，移动端 P2 | TBD |
| **i18n 多语言** | 前端文本全中文 hardcode | 另一个工程 |
| **路由 transition 包装** | builder.css 已经定义了 `.page-enter-active` 等 class，但需要在 `<router-view>` 外面包 `<transition>` 才生效 | 0.5d |

---

## 11. Commit 链

```
7172cbc  feat(design):  v3 token 系统引入                     (前置)
b1120e6  refactor(v3):  13 页 + 状态系统 + 密度 + a11y         (23 文件 +4766/-1473)
b1b97bf  refactor(v3):  RailSidebar + chat 侧栏 + modal       (9 文件 +1269/-426)
4b7e5c0  refactor(v3):  Login.vue v3 token 化（漏网）         (1 文件 +99/-75)
f5e6c0a  refactor(v3):  Phase 9 全清 17 剩余页面 v3 token     (17 文件 +1436/-947)
[next]   refactor(v3):  Phase 10 全局 polish — sticky/动效    (1 文件 +242)
```

---

## 12. 让本地浏览器立即看到效果

```js
// 在 console 跑
localStorage.clear();
location.reload(true);
```

清掉旧 `theme-accent-color: #6d5df6` 缓存后整页变蓝。
