# Phase D 完成交接 — Git 入方向 + Webhook + Workspace + OAuth

**Date**: 2026-04-25
**Branch**: `claude/coding-shell-alignment` (HEAD `cfa5b5b`)
**Tests**: backend pytest 191 passed, frontend vue-tsc 干净
**Commits**: Phase D 共 8 个 commit（自 `edcfa8f` plan 起到 `cfa5b5b`）

---

## 落地内容

### 后端
- `backend/app/git/webhook.py` — `WebhookEvent` 抽象 + `verify_signature_github/gitlab` + `parse_event` (跨 provider)
- `backend/app/git/inbound.py` — push/pr_opened/pr_synchronized/pr_review handlers + `dispatch_webhook_event`
- `backend/app/git/inbound_intercept.py` — `handle_direct_merge`（apply 必经 Builder 安全阀，自动 revert + comment + drift log）
- `backend/app/git/drift.py` — `check_drift` / `resolve_drift`（apply 前自动 gate）
- `backend/app/git/workspace_sync.py` — `push_workspace_to_repo`（v1 单向）
- `backend/app/routes/git_webhook.py` — `POST /api/webhooks/git/{provider}`
- `backend/app/routes/git_connection.py` — 加 OAuth start/callback + drift/resolve + workspace sync 端点
- `backend/app/proposal/apply.py` — `build_apply_plan` 集成 drift 检测
- Provider base/gitlab/github 加 `read_file` / `revert_commit` / `get_branch_head` 方法
- `backend/scripts/migrate_collab_phase_d.sql` — `git_connections` 加 `webhook_secret_enc`

### 前端
- `frontend/src/components/DriftBanner.vue` — warning 风格漂移横幅
- `frontend/src/views/GitOAuthCallback.vue` — OAuth 中转页（路由 `/git/callback/:provider`）
- `frontend/src/views/ProjectGitSetup.vue` — 加 OAuth 按钮 + PAT 表单折叠
- `frontend/src/views/ProposalDetailPage.vue` — 集成 DriftBanner
- `frontend/src/views/CodingPage.vue` — workspace 区加 "Sync to repo" 按钮
- `frontend/src/api/gitConnection.ts` — 加 `driftStatus` / `resolveDrift` / `syncWorkspace` methods

---

## 验证状态

### ✅ 已验证
- backend pytest 191 个 test pass（Phase D 新增约 47 个：webhook 12 + inbound 6 + intercept 4 + drift 9 + workspace 5 + provider 扩展 4 + OAuth 7）
- frontend vue-tsc 干净
- `migrate_collab_phase_d` 应用过（`__builder_migrations` 含 `migrate_collab_v1` + `migrate_collab_phase_c` + `migrate_collab_phase_d`）
- `git_connections.webhook_secret_enc` 列已落库

### ⚠️ 未活体验证（条件 + dependency 限制）
- webhook 入方向：需 ngrok 等公网暴露 + git 平台配 webhook URL + 存 `webhook_secret_enc` 才能真测；后端逻辑已通过 unit test（验签 + dispatch + handlers）
- OAuth 完整流：需用户配 `GITHUB_CLIENT_ID/SECRET` (+ `GITLAB_*`) 才能真测；当前 `.env` 仅有 `GITHUB_PAT`
- 直连 merge 拦截：GitHub 强推 ref 需 admin perm，生产 protected branch 需另接 PR revert 流
- workspace sync：需真实 workspace 文件 + git 已 init repo 才能真测

---

## Phase D 之后 — Phase E 启动指引（建议）

整套 ABCD 已完整落地协作 + git 双向同步。下一阶段 Phase E **真接 platform deploy**：

读 spec §10 backlog 第 1 项："execute_apply v1 不真调 platform API"。Phase E 范围：
1. apply 时调既有 `generation_steps` / `step_executor` 真部署到 aPaaS 平台
2. 不可逆操作的 platform 层确认（如已存在的对象）
3. apply_failed 时自动开 fix-up proposal（spec D7 决策）
4. ChatPage 改造：编辑时显式传 `application_id`，激活 fork hook

---

## 已知 backlog（不阻塞使用）

1. **execute_apply 仍不真调 platform** — 仅切 canonical 指针 + 推 git；Phase E 接入
2. **OAuth state 用 project_id 简化** — 生产应加 nonce 防 CSRF
3. **GitHub revert 用强推 ref** — 需 admin perm，protected branch 失败
4. **workspace 反向 sync (repo→workspace)** — webhook handler 未实现，留 v2
5. **drift resolve 仅 log** — 实际数据迁移留 v2
6. **webhook secret 存储** — `git_connections.webhook_secret_enc` 列加了，但 UI 上还没让用户输入并存入；实际接 webhook 前需手动 INSERT 到 DB 或加 UI
7. **CodingPage Sync 按钮的 currentAppGitRepoUrl 异步加载** — 首次切换 workspace 有短暂闪烁
8. **MembersPanel 用 alert/confirm** — UX 不统一，Phase E 视觉对齐时一起改
9. **ChatPage application_id 未传** — Phase B fork hook 在生产侧未激活
10. **审批数量阈值** — 当前 1 个 approve 即变 'approved'，未严格按 owner approve
