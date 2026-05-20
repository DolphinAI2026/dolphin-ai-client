# Session Handoff · 2026-05-20 v2（接续 v1 之后的 11 commits）
> 接 `docs/handoff-2026-05-20-session-end.md` (v1)；本次 session 把 v1 留尾的 P0 全做了，加上用户陆续提出的 5+ 个新方向。

---

## 🚀 接手快速指南（给同事）

### 仓库 + 分支
- **GitHub repo**: https://github.com/Mars-hub404/apaas-builder-ai
- **分支**: `local/ui-redesign-2026-05-20`
- **最新 HEAD**: `a4b1685` (含本文档)
- **主分支**: `main`（**不要往 main 推 / 不要 PR**——这分支还有留尾任务，等本系列彻底稳定再考虑 merge）

### 拉代码

```bash
# === 情况 A：首次 clone ===
git clone -b local/ui-redesign-2026-05-20 \
  https://github.com/Mars-hub404/apaas-builder-ai.git
cd apaas-builder-ai

# === 情况 B：已有本地 repo ===
cd /path/to/apaas-builder-ai
git fetch origin
git checkout local/ui-redesign-2026-05-20
git pull --ff-only origin local/ui-redesign-2026-05-20

# 确认 HEAD
git log --oneline -1
# 应该看到: a4b1685 docs(handoff): 2026-05-20 v2 ...
```

### 跑起来（3 个进程）

```bash
# 装依赖（首次）
cd frontend  && pnpm install
cd ../admin-spa && pnpm install
cd ../backend && pip install -r requirements.txt
cd ..

# Terminal 1: backend (FastAPI 8000)
cd backend && python -m uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend (Vite 5173) — 主入口
cd frontend && pnpm dev

# Terminal 3: admin-spa (Vite 5174) — 平台管理 SPA，可选
cd admin-spa && pnpm dev
```

### 访问
- **Frontend 主入口**: http://localhost:5173/ai-builder/
- **Admin SPA**（平台管理）: http://localhost:5174/

### 验证本 session 改动是否生效（5 分钟自检）

| # | 操作 | 期望看到 |
|---|---|---|
| 1 | 打开 `/ai-builder/` | Landing 3 mode picker：睿鲸 AI Builder / 睿鲸 AI Coding / Vibe Coding |
| 2 | 顶部 topbar | 只有面包屑 `aPaaS Builder / 新建`，**没有** 成员管理 / 平台环境 / 铃铛 / 太阳 4 个按钮 |
| 3 | 左 sidebar | 7 项：首页 / 应用 / 睿鲸 AI Builder / 睿鲸 AI Coding / **Vibe Coding** / 数据库连接 / DB 问数（**没有** 组件市场） |
| 4 | 点 AI Builder mode | placeholder 末尾："应用内做自开发（页面 / 后端接口）建议先进入应用，从应用里发起" + "📎 添加附件（多文件）" 按钮 |
| 5 | 点 AI Coding mode | placeholder "描述要做的通用组件。例：做一个支持多选 + 异步加载的客户树组件…"，**没有** app 下拉选择器 |
| 6 | 进 `/apps` 点任意 app → 跳 `/chat?app_id=N` | 顶部应该有 `[查看应用]` + **`[→ 自开发]`** 两个按钮 |
| 7 | 点 "→ 自开发" | 跳 `/coding?app_id=N&from_ai_builder=1&dispatch=app-dev-XXX`，agent 自动发首条消息含 `[应用上下文] 用户已从 AI Builder 切到 AI Coding…app_id, app_code, 数据模型, 表单, 业务流程, 角色` |
| 8 | 进 `/workspace-catalog` | 顶部新增 **大类切换**：`全部 / 应用相关 / 通用组件` + count 徽章；卡片上有 `📦 app-name` badge（仅 project_id 不空时） |

如果有任何一条对不上，先看 `git log --oneline -15` 确认 HEAD 是 `a4b1685`，然后跑 `pnpm install` 重装（可能 lock 漂了）。

---

## 一、Branch 状态

- **Branch**: `local/ui-redesign-2026-05-20`
- **HEAD**: `5554225 feat(workspace): Phase 5 加大类分类 — 应用相关 vs 通用组件`
- **Base** (v1 末尾): `56fe00e docs(handoff): 2026-05-20 session 末完整交接`
- **本 session 累计**: 11 commits / 净 **-2629 行**（删 dead code -3500+，加新 feature +850+）
- **全部已 push origin**：`56fe00e..5554225  local/ui-redesign-2026-05-20`

## 二、11 commits 按时间顺序（含每 commit 详细改动）

### 总览

```
─── P0 用户原 4 个反馈 (v1 handoff #3 章) ────────────────────────
f641ef7  fix(chat): 砍 AIChatPage 「按规范重写」按钮 (-31)
229e494  feat(chat): P0-B1 砍应用蓝图链路 (-850 行)
b63a8c8  chore(chat): P0-C(c) 清 ChatPage 两段 v-if="false" 死代码 (-510)
b7396a4  chore(chat): P0-C(a) 清非 dolphin 模式 fallback 死分支 (-275)

─── P0-D Landing 反转 (用户实测线上后决策) ─────────────────────
10484c4  feat(landing): cherry-pick 2550 行原 Landing.vue (错版本)
27748ec  fix(landing): 改用 xhh-cleanup@1bb5a9d 的 3-mode hub (正确版本, -2598)

─── 用户实时优化 #1-#4 ──────────────────────────────────────────
ab0a5ec  feat(nav): 加 Vibe Coding sidebar 入口 + 清 topbar 4 个重叠 action
0670155  feat(landing): 多文件上传 + 应用选择器
1428e57  refactor: 撤 Landing app picker + 删组件市场 (audit 后纠错)

─── 重定位 AI Coding (用户 audit 触发的方向调整) ────────────────
1f2a2d7  feat: 重定位 AI Coding + 加 Builder→Coding 自开发 handoff bridge
5554225  feat(workspace): Phase 5 Workspace 分类 — 应用相关 vs 通用组件
```

### 详细 per-commit 改动

#### `f641ef7` · P0-A 砍 AIChatPage "按规范重写" 按钮

| 项 | 内容 |
|---|---|
| **用户原话** | "按规范重写" 按钮也去掉，没啥卵用 |
| **改动文件** | `frontend/src/views/AIChatPage.vue` |
| **改动内容** | 删按钮 (line 226-232) + 删 `rewriteArtifactToSpec` 函数 (line 1339-1361, 23 行死代码) |
| **行数** | -31 |
| **如何验证** | /ai-chat 打开 artifact 时，右栏头部不再有"按规范重写" 按钮（保留"复制"⧉、"下载"⤓、"在 Builder 中调整"） |

#### `229e494` · P0-B1 砍应用蓝图链路

| 项 | 内容 |
|---|---|
| **用户原话** | "应用蓝图的 UI 渲染做了等于白做，要么 1:1 还原低代码组件，要么别做"——选 B1 别做 |
| **改动文件** | `frontend/src/views/AIChatPage.vue` (蓝图 tab 删 + computeds 删) / `frontend/src/views/ChatPage.vue` (dead imports 清) / `frontend/src/api/specsV2.ts` (删 parseMd + ParsedSpec*) |
| **删除文件** | `frontend/src/components/v2/AppBlueprintPanel.vue` (398 行) / `frontend/src/stores/aiChatBlueprint.ts` (60 行) / `frontend/src/views/chat/blueprint-adapter.ts` (153 行, dir 也删了) |
| **行数** | -850 |
| **如何验证** | /ai-chat 打开 artifact 时，右栏只有 2 tab（渲染 / 原文），不再有"应用蓝图" tab；DOM 0 处出现"应用蓝图" / .bp-* class |

#### `b63a8c8` · P0-C(c) 清 ChatPage 两段 v-if="false" 死代码

| 项 | 内容 |
|---|---|
| **用户决策** | C2 "全砍 + 清死代码 一气呵成" |
| **改动文件** | `frontend/src/views/ChatPage.vue` / 删 `frontend/src/components/v2/ChatConversationList.vue` |
| **改动内容** | 删顶部 `<ChatConversationList v-if="false">` 段 (-30) + 中部 `<div v-if="false && showBuilderArtifactPanel">` 整段 448 行 + 删支撑 computeds (v2ConversationItems / v2CurrentConversationId / onV2OpenConversation / currentIndustryPack) + 删 ChatConversationList 组件文件 |
| **行数** | -510 |
| **如何验证** | grep `v-if="false"` 在 ChatPage 0 match；/chat 页面渲染无变化（这本来就是死 DOM） |

#### `b7396a4` · P0-C(a) 清非 dolphin 模式 fallback 死分支

| 项 | 内容 |
|---|---|
| **背景** | `useDolphinChat = ref(true)` 是冻结常量从未被赋值 false，所有 `!useDolphinChat` 分支运行时全 dead |
| **改动文件** | `frontend/src/views/ChatPage.vue` |
| **改动内容** | 删 5 段 template：SessionSidebar / mode-switcher / "部署到预览" / "运行流水线" / builder-chat-phase-strip + 删整段 195 行 `<template v-else>` (老 SPEC chat UI) + 删 `useDolphinChat` ref 本身 + 简化 2 个 `\|\| !useDolphinChat.value` guard |
| **行数** | -275 |
| **如何验证** | grep `useDolphinChat` 0 match；/chat 页面 dolphin agent iframe 渲染正常 |
| **⚠️ 留尾** | 此 commit 误删了 `dispatchCustomDevToCoding` / `dispatchGeneralSpecToCoding` 这两个 Builder→Coding handoff 发起方按钮（在死代码段里），后续 `1f2a2d7` commit 增强后恢复 |

#### `10484c4` · ❌ Landing 错 cherry-pick

| 项 | 内容 |
|---|---|
| **用户原话** | "agent.dfy.definesys.cn/ai-builder 那个首页是我想要的" |
| **错在哪** | 凭印象 cherry-pick `origin/merge-prod-and-integrate` 的 2550 行版本，但用户截图实际是 3-mode hub（更小） |
| **改动文件** | `frontend/src/views/Landing.vue` |
| **行数** | +2275 (后被 `27748ec` 完全覆盖) |
| **保留 commit 的原因** | git 历史诚实记录走过的弯路，可让人理解为什么 27748ec 是 -2598 |

#### `27748ec` · ✅ Landing 改用 1bb5a9d 240 行版本

| 项 | 内容 |
|---|---|
| **正确版本来源** | `git checkout 1bb5a9d -- frontend/src/views/Landing.vue frontend/src/components/v2/LandingComposer.vue` (xhh-cleanup-2026-05-20 分支的某中间 commit) |
| **改动文件** | `frontend/src/views/Landing.vue` (2550 → 240) / `frontend/src/components/v2/LandingComposer.vue` (376 → 88) |
| **UI 内容** | "APAAS CHAT AI · DESIGN + BUILD" header / "把想法或材料给 AI，它来搭应用" hero / 3-mode hub / 4-stat 卡 / flow strip / 最近应用 list |
| **行数** | -2598 |
| **如何验证** | 见快速指南验证 #1 |

#### `ab0a5ec` · 加 Vibe Coding sidebar 入口 + 清 topbar 4 个 action

| 项 | 内容 |
|---|---|
| **用户原话** | "Vibe Coding 入口找回" + "成员管理、平台环境、铃铛、太阳跟左下角重复，删" |
| **改动文件** | `frontend/src/components/v2/RailSidebar.vue` / `frontend/src/components/v2/ShellTopBar.vue` |
| **RailSidebar 改动** | NAV 数组加 Vibe Coding 项 + 加 sparkles icon SVG + 顺手把 "AI Builder / AI Coding" 重命名 "睿鲸 AI Builder / 睿鲸 AI Coding" 跟首页对齐 |
| **ShellTopBar 改动** | 删整段 `<div class="topbar-actions">` (4 个按钮) + 删 useThemeStore / useUserStore / useRouter imports + 删 toggleTheme + isDark (全是被删按钮专用 orphan) |
| **行数** | -19 |
| **如何验证** | 见快速指南验证 #2 #3 |

#### `0670155` · 多文件上传 + (历史) AI Coding app picker

| 项 | 内容 |
|---|---|
| **改动文件** | `frontend/src/components/v2/LandingComposer.vue` (大改) / `frontend/src/views/Landing.vue` |
| **LandingComposer 改动 (留)** | builder mode 支持 `<input multiple accept>` 任意类型多文件 + 文件 chip 列表 + 文件大小显示 + × 删除按钮 |
| **LandingComposer 改动 (后撤)** | coding mode app picker dropdown (后 `1428e57` 撤掉) |
| **submit 时** | Builder mode 把 files 塞 `previewStore.pendingAiChatFiles` + 路由 `/ai-chat?prompt=...`（AIChatPage 已有 `onMounted` 逻辑会消费）|
| **行数** | +96 |
| **如何验证** | 见快速指南验证 #4 |

#### `1428e57` · 撤 app picker + 删组件市场

| 项 | 内容 |
|---|---|
| **用户原话** | "AI Coding 围绕应用做的话最好在 AI Builder 里实现" + "组件市场删掉先不搞了" |
| **方向纠错** | audit 后发现把 app 选择放 Landing 跳 /coding 跟"二开归 Builder"决策矛盾，撤回 0670155 加的 app picker |
| **改动文件** | `frontend/src/components/v2/LandingComposer.vue` / `frontend/src/views/Landing.vue` / `frontend/src/components/v2/RailSidebar.vue` / `frontend/src/components/v2/ShellTopBar.vue` / `frontend/src/router/index.ts` |
| **删除文件** | `frontend/src/views/MarketplacePage.vue` (762 行) / `frontend/src/api/marketplace.ts` (80 行) |
| **改动具体** | LandingComposer 撤 app picker (UI + script + CSS) / Landing 删 allApps fetch / RailSidebar 删 marketplace NAV / ShellTopBar 删 marketplace CRUMB / router 删 marketplace route |
| **行数** | -907 |
| **如何验证** | 见快速指南验证 #5；左 sidebar 不应有"组件市场"项 |

#### `1f2a2d7` · ⭐ Builder→Coding handoff bridge (核心架构落地)

| 项 | 内容 |
|---|---|
| **用户决策** | "AI Coding 重定位为通用组件库 / 应用相关二开在 Builder 入口 / handoff 时 agent 不要现查应用 menu/formid" + "暂停 dolphin admin 集成 先自己跑通" |
| **改动文件** | `frontend/src/components/v2/LandingComposer.vue` / `frontend/src/views/ChatPage.vue` |
| **LandingComposer 改动** | mode subs 文案更新："搭应用 + 应用内自开发（页面 / 接口）" / "通用组件库 — 跨应用复用" / 不变 |
| **ChatPage 改动** | TopBar `#center` slot 加 "→ 自开发" 按钮（v-if="builderCurrentAppId"，在"查看应用"旁）+ 加 `handoffToCodingForAppDev` handler 序列化 `store.preview` (models/forms/flows/roles) 写 sessionStorage('ai_builder_pending_coding') + router push `/coding?app_id=N&from_ai_builder=1&dispatch=app-dev-XXX` |
| **复用** | `AI_BUILDER_PENDING_CODING_KEY` 常量已存在 (ChatPage line 1975) / `buildCodingRouteQuery` + `openCodingWorkspace` helpers / `CodingPage.vue:1335 maybeConsumeAiBuilderDispatch` 接收端 0 改动 |
| **行数** | +65 |
| **E2E 实测** | Claude in Chrome 实测：进 `/chat?app_id=2` (通用费用报销) → 点 "→ 自开发" → /coding agent 真的收到 message 并在 SPEC 的"低代码复用"行写出 "app_id=2、app_code=expense-mgmt、模型 expense_report+expense_item、表单+角色" — **不再凭空猜** |
| **如何验证** | 见快速指南验证 #6 #7 |

#### `5554225` · Phase 5 Workspace 列表分类

| 项 | 内容 |
|---|---|
| **改动文件** | `frontend/src/views/WorkspaceCatalogPage.vue` |
| **新增** | 顶部 category-bar：全部 / 应用相关 (有 project_id) / 通用组件 (无 project_id) + count 徽章 + active 态下划线 / 第二维度 tab (PC组件/PC页面/...) 保留，先 category 后 project_type 双重过滤 / 卡片标题旁加 `📦 app_name` badge (有 project_id 时) / friendly empty 文案 |
| **新增 fetch** | `applicationApi.list` 建 `appNameMap: { project_id → app_name }` 索引 |
| **行数** | +131 |
| **如何验证** | 见快速指南验证 #8 |
| **⚠️ 留尾** | 现有 2 个 workspaces（CRM驾驶舱 / 人才管理总览看板）都无 `project_id` → 应用相关分类实际为空。handoff bridge 创建新 workspace 时需 backend 把 project_id set 上才能挂分类 |

#### `a4b1685` · 本 handoff 文档

| 项 | 内容 |
|---|---|
| **改动文件** | `docs/handoff-2026-05-20-v2-session-end.md` (本文件) |
| **行数** | +222 (后续会扩) |

## 三、🎯 用户最终产品架构（本 session 落地）

```
┌────────────────────────────────────────────────────────────────┐
│ Landing (3 mode picker — xhh-cleanup@1bb5a9d 240 行版)         │
│                                                                │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────┐ │
│  │ 睿鲸 AI Builder      │  │ 睿鲸 AI Coding       │  │Vibe  │ │
│  │ 搭应用+应用内自开发  │  │ 通用组件库—跨应用复用│  │Coding│ │
│  │ 多文件上传 (any type)│  │                      │  │      │ │
│  └──────────────────────┘  └──────────────────────┘  └──────┘ │
└────────────────────────────────────────────────────────────────┘
                │                       │                 │
                ▼                       ▼                 ▼
        /ai-chat?prompt=        /coding              /vibe-coding
        +pendingAiChatFiles
                │
                ▼
┌────────────────────────────────────────────────────────────────┐
│ ChatPage (应用上下文 — dolphin agent 23c93f30d8 iframe)        │
│                                                                │
│ Top actions: [查看应用]   [→ 自开发]                            │
│                          ─────────────                         │
│   点 → 自开发: handoffToCodingForAppDev()                       │
│   ├─ 收集 store.preview.{models, forms, flows, roles}          │
│   ├─ 序列化成 message:                                          │
│   │   [应用上下文] 用户已从 AI Builder 切到 AI Coding…          │
│   │   - app_id, app_code                                       │
│   │   - 数据模型 (N): name1(code1), name2(code2), …            │
│   │   - 表单 (M): formName→modelCode                           │
│   │   - 业务流程 / 角色                                          │
│   │   请问候我并询问要做什么类型的自开发任务，给 1-2 个建议      │
│   ├─ sessionStorage.setItem('ai_builder_pending_coding', JSON…) │
│   └─ router.push('/coding?app_id=N&from_ai_builder=1&dispatch') │
└────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────┐
│ CodingPage / WorkspaceCatalogPage                              │
│                                                                │
│ • maybeConsumeAiBuilderDispatch (line 1335) 读 sessionStorage  │
│   → userInput.value = message → sendMessage() (现成机制)        │
│ • Catalog 顶部 category-bar: [全部][应用相关][通用组件]+count   │
│ • 卡片带 📦 应用名 badge (有 project_id 时)                    │
│ • 点卡片 = openWorkspace → /coding?workspace_id=N → 直进 IDE   │
└────────────────────────────────────────────────────────────────┘
```

**E2E 实测通过**（Claude in Chrome, 通用费用报销系统 app_id=2）:
> Agent 收到 message 后，"低代码复用"行写: "应用信息 app_id=2、app_code=expense-mgmt；模型：expense_report、expense_item；表单：报销单 expense_report；角色：员工、部门主管、财务" — 全部是 frontend 注入的真实数据，**不再凭空猜**。Agent 进一步给出 2 个具体建议: 「我的报销工作台」+「费用明细统计看板」。

## 四、用户在本次 session 的关键决策时点

| 时点 | 用户原话 | 落地 commit |
|---|---|---|
| Session 中段 | "AI对话也支持多种文件上传 / 改名睿鲸 AI Builder" | 0670155 → 1428e57 |
| Audit 之后 | "AI Coding 围绕应用做的话最好在 AI Builder 里实现" | 1f2a2d7 |
| 再 audit 之后 | "Builder agent 不写代码 (37 lowcode 工具) / AI Coding 才是写自开发代码的" | 1f2a2d7（不砍 AI Coding，只改入口 + handoff） |
| 实战之后 | "Agent 不要现查应用 menu/formid" | 1f2a2d7 message 序列化所有应用结构 |
| Phase 5 之后 | "组件市场删掉先不搞了" | 1428e57 |
| Vibe Coding | "入口在左侧被隐藏，找回" | ab0a5ec |
| Top bar | "成员管理、平台环境、铃铛、太阳 跟左下角重复，删" | ab0a5ec |
| Agent prompt | "暂停 dolphin admin 集成，先自己跑通" | （未改 dolphin prompt — frontend 单边方案）|

## 五、关键 backend / 工具调用链（不变，从 v1 沿用）

agent 体系跟 v1 一样：
- **Builder agent** `23c93f30d8`: 37 个 apaas 工具（**禁用 workspace 工具**）
- **Coding agent** `41fe6f2479`: workspace + 37 apaas 工具，支持 6 种 templateType（form-page / form-component / mobile-page / backend-api / backend-feign / backend-scheduled）
- **Vibe agent** `51ebb5937b`: 11 个 `vibe_*` 沙箱工具，独立全代码

**handoff 协议**:
- ChatPage 用 sessionStorage 桥接 (`AI_BUILDER_PENDING_CODING_KEY`)
- 不依赖 dolphin agent-to-agent（dolphin 没这功能，靠 [SYSTEM CTX] message 注入）
- 当前 handoff payload = 完整应用结构序列化（不是凭空让 agent 现查 menu/formid）

## 六、当前未完成的工作（按优先度）

### 🟠 P1 — 待用户决策后做

#### A. Backend Stage 1 余 — parser models.py add_rewrite 接入
- 来自 v1 handoff，handoff_2026_05_20.md 章 4 P1
- 文件：`backend/app/doc_parsers/models.py` `_parse_fields`
- 触动 backend，**铁律 0 改动**——下次专门 session 跟用户对齐

#### B. Stage 2 — backend /upload-doc 返 code_rewrites
- 同上铁律

#### C. Stage 2 — v2 mcp-server 加 preview_app_from_doc 工具
- sister repo: `/Users/mars/Vibe Coding/apaas-builder-mcp-server`
- 部署需 docker buildx + kubectl set image

#### D. Stage 4 — agent prompt 更新（dolphin admin）
- 用户本次 session 决策"先不动 dolphin admin"
- 等用户重新决策后做

### 🟡 P2 — code hygiene 可后续做

#### E. ChatPage orphan script 清理（28+ 死 symbols）
- 来自 commit b7396a4 之后留尾
- setActiveView / startDeployFromTopbar / showViewSwitcher / showBuildHistoryButton /
  showStartDeployButton cluster / builderCanvasTabs+canvasTab+openArtifactPanel cluster /
  specOverviewStats cluster / builderPhaseSteps+builderLifecycleStatus / publishCurrentApp 等
- 预估 -800~1200 行
- 风险：cluster 互相调用，深入清理需逐个验证

#### F. workspace 实测数据：现存 workspaces 都无 project_id
- Phase 5 加的"应用相关"分类目前实际为空（CRM驾驶舱 / 人才管理总览看板都没 project_id）
- 解决：handoff bridge 创建的新 workspace 应该 set project_id (需 backend ws 创建工具配合)，或者根据 ws.project_name 反查应用
- 不是 bug，是数据未填充。下次有 backend 决策权 session 再做

#### G. Backend `/marketplace/*` route 留 dead 在 backend
- 铁律 0 改动；前端已删干净

## 七、Tools / Skills 清单（沿用 v1）

unchanged from v1 handoff section 6. ai-chat agent 4 工具 / Builder agent 71+ / Coding 等。

## 八、Browser tools 状态

✅ **本 session 重新接通**：
- `mcp__Claude_in_Chrome__*` E2E 实测通 (`/chat?app_id=2` → 点 "→ 自开发" → `/coding` agent 收到 app context + 输出 SPEC)
- `mcp__Claude_Preview__preview_*` 持续可用（dev server 9b46.../f96d... 仍跑）

## 九、本次 session 学到的关键经验

1. **凭印象答之前先 audit**：第 5 次 commit (10484c4) 错 cherry-pick 2550 行 Landing — 我假设是用户要的版本，没对比线上 hash。被用户截图打脸。下次先 fetch 线上 build hash 反查具体 commit
2. **凭印象答 #2**：我建议"AI Coding 砍掉合并到 Builder" — 用户问"你确定？"我才去 audit，发现 Builder 不写代码，Coding 才是写自开发的。**正确做法：发表方向建议前先 spawn audit agent**
3. **Vue tool invocation pattern 不要被 LLM template 误代入**：commit 0670155 时 Write 工具尾部多写了 `</content></invoke>` — 是 LLM 把工具调用模板的尾部带进了 `content` 字段。Edit/Read 写代码时小心。
4. **dolphin agent handoff 当前只能靠 sessionStorage + [SYSTEM CTX] message 注入**：没有 agent-to-agent 协议；frontend 序列化整个 app context 注入到 first user message 是 work-around，实测 work
5. **`useDolphinChat = ref(true)` 这种冻结常量需要清掉**：本 session commit b7396a4 删了 5 处 `!useDolphinChat` 死分支 -275 行。类似 "history-frozen" 状态在 ChatPage 还有不少 (P2 orphan 一起做)

## 十、最重要的工程铁律（沿用 v1 + 本次新增）

- ✅ **backend 0 改动**：本 session 严格守住（除非 d2ef414 那种用户明确授权的）
- ✅ **不动 dolphin admin agent prompt**：本 session 用户明确"暂停 dolphin admin 集成"
- ✅ **每次 commit 前 verify**：本 session 大部分 commit 都做了 vite HMR + DOM grep + Chrome E2E
- 🔥 **方向决策前先 audit，不要凭印象答**：本 session 两次踩坑（10484c4, 1f2a2d7 前 hand-wave 阶段）

## 十一、下次 session 第一步要做什么

> 不要凭印象，按这个顺序：
>
> 1. **`git pull` 到最新 `local/ui-redesign-2026-05-20`** (HEAD `5554225`)
> 2. **完整读本文档 + v1 (`docs/handoff-2026-05-20-session-end.md`) 两份**
> 3. **跟用户对齐方向**：
>    - dolphin admin 集成现在能恢复了吗？P1 backend Stage 1-4 还做不做？
>    - Phase 5 留尾的 "应用相关 = 空" 问题要不要做 backend 给 ws 加 project_id？
>    - P2 ChatPage orphan 清理需要吗？
> 4. **如果做 P1 backend**：先确认 backend 改动是用户明确授权，再动 `backend/app/doc_parsers/models.py`
> 5. **如果做 P2 orphan**：用 `compound-engineering:ce-correctness-reviewer` 或类似 agent 帮 batch verify orphan 范围，不要单点 grep 后凭印象砍

## 十二、文件清单（接手者快速 grep 用）

```
# 本 session 改的核心文件
frontend/src/views/Landing.vue                      — 240 行 1bb5a9d 版（不要再换）
frontend/src/components/v2/LandingComposer.vue      — 211 行 3-mode hub
frontend/src/components/v2/RailSidebar.vue          — 8 项 nav (含 Vibe Coding)
frontend/src/components/v2/ShellTopBar.vue          — 干净 (无 actions 区)
frontend/src/views/ChatPage.vue                     — "→ 自开发" 按钮 + handoffToCodingForAppDev
                                                       (line ~1996-2050)
                                                       AI_BUILDER_PENDING_CODING_KEY 常量 (line 1975)
                                                       still 12842 行，下次 P2 orphan 清
frontend/src/views/WorkspaceCatalogPage.vue         — Phase 5 大类分类 + app-name badge

# 删的文件（不要回滚）
frontend/src/components/v2/AppBlueprintPanel.vue    — DELETED (B1)
frontend/src/components/v2/ChatConversationList.vue — DELETED (P0-C)
frontend/src/stores/aiChatBlueprint.ts              — DELETED (B1)
frontend/src/views/chat/blueprint-adapter.ts        — DELETED (B1)
frontend/src/views/MarketplacePage.vue              — DELETED (组件市场)
frontend/src/api/marketplace.ts                     — DELETED (组件市场)

# 关键 backend 文件（铁律 0 改动）
backend/app/doc_parsers/models.py                   — Stage 1 余还没接 add_rewrite
backend/app/routes/applications/docs.py             — /upload-doc 还没返 code_rewrites
backend/app/generator_v2.py:543                     — v2 已修，v1 未同步 _apply_suffix
backend/app/routes/marketplace*.py                  — frontend 已删，backend 留 dead

# 待动的 sister repo
/Users/mars/Vibe Coding/apaas-builder-mcp-server/backend/app/mcp_server.py
                                                    — 加 preview_app_from_doc 工具
```

---

**就这些。** 下个 session 接手时记得：先读完整两份 handoff (v1 + v2) → 跟用户对齐方向 → 小步快跑 → 每步 verify → 方向决策前先 audit。
