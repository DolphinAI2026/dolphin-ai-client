# Phase F 完成交接 — UX WorkspaceShell + 简单/专业双轨

**Date**: 2026-04-25
**Branch**: `claude/coding-shell-alignment` (HEAD `f62c39f`)
**Tests**: backend pytest 210 passed, frontend vue-tsc 干净
**Commits**: Phase F 共 14 个 commit（自 ac9bdca spec / 3367764 plan 起）

整套 spec：[2026-04-25-phase-f-ux-workspace-shell-design.md](specs/2026-04-25-phase-f-ux-workspace-shell-design.md)

---

## 落地内容

### 后端
- `backend/scripts/migrate_phase_f.sql` — applied (user_preferences 表 + applications.default_mode 列)
- `backend/app/models/preference.py` — UserPreference ORM
- `backend/app/models/__init__.py` — Application.default_mode 列
- `backend/app/routes/preferences.py` — GET/PUT /api/me/preferences
- `backend/app/routes/applications/__init__.py` — GET/PATCH /api/applications/{id}/default-mode
- `backend/app/routes/work_state.py` — GET /api/applications/{id}/work-state（BFF 一站式聚合）

### 前端
- `frontend/src/views/WorkspaceShell.vue` — 主页面 /work/:appId（三栏 layout）
- `frontend/src/components/workspace/`:
  - `WorkspaceTopBar.vue` (app 名 + ModeToggle + 成员头像 + git 状态)
  - `ModeToggle.vue` (简单/专业切换 + 权限 disabled)
  - `ChatPanel.vue` (iframe 嵌入 /chat/:id?embed=true + PromoteApproveApplyCard)
  - `PreviewPanel.vue` (3 tabs: SPEC/Deploy/Code)
  - `preview/SpecView.vue` (v1 占位，spec id 元信息)
  - `preview/DeployIframe.vue` (真嵌入 platform_url + 1.5s 超时 fallback)
  - `preview/CodeView.vue` (iframe 嵌入 /coding?embed=true)
  - `ActivityPanel.vue` (聚合 draft/proposals/canonical/git，模式差异化显示)
  - `activity/{DraftCard,ProposalCard,DeployedCard,GitStatusCard}.vue`
  - `PromoteApproveApplyCard.vue` (in-chat 简单模式快捷批准)
- `frontend/src/stores/{workspace,userPreference}.ts`
- `frontend/src/api/{preferences,workState}.ts`
- `frontend/src/components/{BaseDialog,BaseToast}.vue` — 统一弹窗替原生 alert/confirm
- `frontend/src/views/Apps.vue` — 卡片点击默认跳 /work/:appId
- `frontend/src/views/{ChatPage,CodingPage}.vue` — 加 ?embed=true 模式（隐藏 topbar/PhaseBar）
- `frontend/src/views/{ProposalDetailPage,ProjectGitSetup,MembersPanel}.vue` — alert/confirm/prompt 替换为 BaseDialog/BaseToast

---

## 验证状态

### 已验证
- backend pytest 210 passed (Phase F 新增 11 测试：preferences_model 2 + preferences_api 4 + work_state 5)
- frontend vue-tsc 干净（14 commits 无新 type 错误）
- DB schema：`migrate_phase_f` 在 `__builder_migrations` 中；`user_preferences` 表存在；`applications.default_mode` 列存在
- 老路由全保留 (/chat/:id, /coding, /devops, /proposals/:id, /project/:id, /apps) — 向后兼容

### 未活体验证
- `/work/:appId` 完整体验需要：登录 + 选 app + chat send → fork hook 触发 + draft 出现 + 简单模式 PromoteApproveApplyCard 显示 + 一键 apply
- DeployIframe URL pattern `${platform_url}/app/${apaas_app_id}` 是 spec 假设；活体需验证 aPaaS 平台实际 URL pattern
- iframe 跨域：aPaaS 平台 X-Frame-Options 可能拒绝 builder 嵌入；实际部署需 ops 协调；DeployIframe 已 fallback "在新窗口打开"
- ChatPanel iframe 嵌入老 ChatPage 的 ?embed=true 模式 — 需真机看老 PhaseBar/topbar 是否成功隐藏
- CodingPage `is-embedded` CSS hack 隐藏 topbar — 需真机验证

---

## 已知 backlog（不阻塞使用）

1. **SPEC tab v1 是占位**：完整 SPEC 编辑界面在 ChatPanel iframe 内，PreviewPanel SPEC tab 只显示 spec id 元信息。**v2 抽出 SpecCanvas 组件嵌入 PreviewPanel**
2. **CodeView v1 不绑 application**：iframe 嵌入老 /coding，显示全局 workspace 列表。**v2 抽出 workspace 列表 + 文件树独立组件按 app 过滤**
3. **ChatPanel iframe 限制**：iframe 内的 chat events 不能直接通知外层（PromoteApproveApplyCard 不能"跟随 AI 完成一轮编辑"自动出现）。**v2 抽出 chat 核心组件不靠 iframe**
4. **ChatPanel application_id ↔ conversation_id 关联**：v1 是手动开新对话；v2 后端加端点查"此应用关联的活跃 conversation"自动复用
5. **PromoteApproveApplyCard 不可逆 confirm 用 window.confirm**：v2 用 BaseDialog 替（组件已有，简单替换工作）
6. **CodingPage embedded NavRail 隐藏靠 ?embed_nav=0**：复用既有 WorkbenchShell 机制 OK，但是 hack 性质
7. **dark mode**：所有新组件用 Tier 1 token，自动兼容
8. **OAuth state CSRF**：Phase D 标过的 backlog（不在 Phase F 范围）

---

## Phase G 启动建议

UX 进一步深化 + 真链路 e2e：
- **真机 e2e smoke**：登录 admin → /apps → 点应用 → /work/:id → 顶栏 mode toggle / 成员头像 / git 状态都对 → ChatPanel iframe 加载 → 编辑 → fork → PromoteApproveApplyCard 出现 → 一键 apply → ActivityPanel 实时更新
- **DeployIframe URL pattern 校准**：跟 aPaaS 平台运维确认 `/app/{id}` 是否对，可能要 `/runtime/app/{code}` 等
- **iframe 跨域协调**：aPaaS 平台 CSP frame-ancestors 加 builder 域名
- **v2 抽出**：SpecCanvas / workspace 列表 / chat 核心组件不靠 iframe（消除 v1 妥协）
- **ChatPanel application_id ↔ conversation_id 关联** — 后端加端点 + 前端自动复用
- **完整 PR-style review UI**：diff 行内 comment（spec 12 节 v2 列表）

---

## 整套 ABCDEF 6 phase 完成

到此 spec [2026-04-25-collab-spec-git-integration-design.md](specs/2026-04-25-collab-spec-git-integration-design.md) + [2026-04-25-phase-f-ux-workspace-shell-design.md](specs/2026-04-25-phase-f-ux-workspace-shell-design.md) 全部 6 phase 落地：

- A 数据底座 + Project 协作
- B ChangeProposal 提案制
- C Git 出方向
- D Git 入方向 + Webhook
- E Real Platform Deploy + ChatPage hook
- F UX WorkspaceShell + 双轨

`claude/coding-shell-alignment` 分支 ahead of main 共 116 commits（含 Tier 1 token + 早期 SPEC 状态机 phase）。

PR 准备：

```bash
gh pr create --title "feat: 协作式 SPEC 管理 + Git 双向同步 + 真接平台部署 + UX WorkspaceShell（Phase A-F）" --body "见 HANDOFF-collab-ABCDEF-summary.md（总览）+ HANDOFF-collab-phase-{a,b,c,d}-done.md + HANDOFF-collab-phase-e-done.md + HANDOFF-phase-f-done.md"
```

---

## 临时数据

- dev MySQL 的 user_preferences 表为空首次 GET /me/preferences 自动建行（当前 1 行 — admin 已访问过 stub）
- applications.default_mode 全部 NULL（即跟随 user pref；可在 ProjectGitSetup 或新 settings 页加 UI 修改）
