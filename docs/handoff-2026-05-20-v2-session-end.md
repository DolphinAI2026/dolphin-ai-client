# Session Handoff · 2026-05-20 v2（接续 v1 之后的 11 commits）
> 接 `docs/handoff-2026-05-20-session-end.md` (v1)；本次 session 把 v1 留尾的 P0 全做了，加上用户陆续提出的 5+ 个新方向。

## 一、Branch 状态

- **Branch**: `local/ui-redesign-2026-05-20`
- **HEAD**: `5554225 feat(workspace): Phase 5 加大类分类 — 应用相关 vs 通用组件`
- **Base** (v1 末尾): `56fe00e docs(handoff): 2026-05-20 session 末完整交接`
- **本 session 累计**: 11 commits / 净 **-2629 行**（删 dead code -3500+，加新 feature +850+）
- **全部已 push origin**：`56fe00e..5554225  local/ui-redesign-2026-05-20`

## 二、11 commits 按时间顺序

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
