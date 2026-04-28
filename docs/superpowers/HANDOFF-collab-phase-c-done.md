# Phase C 完成交接 — Git 出方向（Builder → Git）

**Date**: 2026-04-25
**Branch**: `claude/coding-shell-alignment` (HEAD `f30aa2c`，handoff commit 落地后会再 +1)
**Tests**: backend pytest **144 passed**, frontend vue-tsc 干净
**Commits**: Phase C 共 **10 个 commit**（自 `b7b5ba8` plan 起：1 plan + 8 实现 + 1 token 清理 `f30aa2c`）

---

## 落地内容

### 后端

- `backend/app/git/provider/{base,gitlab,github}.py` — Provider 抽象 + GitLab + GitHub 双实现（PAT + OAuth token 都兼容）
- `backend/app/git/connection.py` — Fernet 加密 + `make_provider` 工厂
- `backend/app/git/repo_init.py` — `init_repo_for_application` 自动建 repo + 推 manifest+spec+README
- `backend/app/git/sync.py` — `push_proposal_branch`（promote 时）+ `finalize_apply_to_git`（apply 后 merge+tag）
- `backend/app/routes/git_connection.py` — 4 endpoints（project-level GitConnection CRUD + application-level git-init）
- `backend/app/routes/proposals.py` — promote 末尾接 git push hook（noop if 未绑 git）
- `backend/app/proposal/apply.py` — apply success 后接 `finalize_apply_to_git`（git 失败不阻断 apply）
- `backend/app/schemas.py` + `routes/applications/_helpers.py` — Application 序列化加 `git_*` 字段
- `backend/app/models/__init__.py` (Application) — 加 `git_repo_url` / `git_provider` / `git_default_branch` 列
- `backend/scripts/migrate_collab_phase_c.sql` — DDL（已 apply，记录在 `__builder_migrations`）

### 前端

- `frontend/src/api/gitConnection.ts` — 4 API methods（`get` / `connectPAT` / `disconnect` / `initRepo`）
- `frontend/src/views/ProjectGitSetup.vue` — Project `/project/:id/git` 配置页（PAT 连接 + 应用 repo 初始化）
- `frontend/src/views/ProjectOverview.vue` — 加 "Git 集成" entry card 跳转
- `frontend/src/views/BuilderDevOpsPage.vue` — 新增 "Git 仓库" tab 显示当前 application git 元数据
- `frontend/src/views/ProposalDetailPage.vue` — 加 "查看 PR ↗" 链接 + `apply_log.git_tag` 显示
- `frontend/src/types/index.ts` — Application/MergedApplication 加 `git_*` 字段
- `frontend/src/router/index.ts` — 加 `/project/:id/git` 路由

### 顺手清理

- `f30aa2c`：MembersPanel + DraftBanner dark 模式 token 化（补 Phase C 期间漏掉的两组件）
- 注：`95b675b`（BuilderDevOpsPage dark token 化）发生在 plan 之前，不计入 Phase C 10 commit

---

## 验证状态

### ✅ 已验证

- backend pytest **144 passed**（Phase C 新增约 44 个：providers 15 + connection/init 18 + sync hooks 11，含 `test_git_connection.py` / `test_git_repo_init.py` / `test_git_sync_apply.py` / `test_git_sync_promote.py`）
- frontend vue-tsc 干净（无输出）
- Application git 字段 schema 落地（`git_repo_url` / `git_provider` / `git_default_branch` 三列均存在）
- `__builder_migrations` 表含 `migrate_collab_phase_c` 行
- Provider 抽象 + GitLab/GitHub impl 全部 mock httpx 测试通过

### ⚠️ 未活体验证（需用户配 GitHub PAT 后真测）

- 真机端到端：ProjectGitSetup → 用 PAT 连接 GitHub → 选 application → init repo → GitHub 上看 repo + 文件 → ChatPage 编辑 → promote → GitHub 上看到 `spec/proposal-*` 分支 + PR → approve + apply → PR 被 merge + `apply-*` tag
- 用户已提供 GitHub PAT 存到 `backend/.env`（`GITHUB_PAT=ghp_***`），但 backend 服务需重启才能生效（`/api/projects/{id}/git-connection` 端点要 reload）
- dev MySQL 的 `git_connections` 表当前为 0 行（Phase C 未真插入数据；用户重启 backend 后通过 ProjectGitSetup 手动连）

### ⚠️ 安全提示

- 用户在对话中明文贴过 GitHub PAT，建议测完后立即去 https://github.com/settings/tokens 撤销，生成新 token 留给生产

---

## Phase D 启动指引

读 `docs/superpowers/specs/2026-04-25-collab-spec-git-integration-design.md` §10 Phase D（git 入方向 + workspace 集成 + webhook + 漂移检测）：

核心范围：

1. Webhook 入口 + 验签（`X-Hub-Signature` for GitHub, `X-Gitlab-Token` for GitLab）
2. push 事件 → 同步 repo 文件到对应 draft / 自动建 ChangeProposal
3. merged 事件 → **拦截！**自动 revert + comment "请在 Builder 中 apply"
4. 漂移检测（git HEAD vs Builder canonical sha 不一致）+ UI banner + 解决流（owner 决定方向）
5. CodingPage workspace ↔ repo `workspaces/<name>/` 子目录双向同步
6. ProjectGitSetup OAuth 流补全（替代 PAT 模式，正式 production-ready）

直接复用 Phase C 的：

- Provider 抽象（`revert_merge` / `add_pr_comment` 已存在 stub，待 Phase D 填充）
- GitConnection 表 + Fernet 加密
- `sync.py` 模式（反向加 `pull_from_git` / `sync_workspace_to_repo`）

---

## 已知 backlog（不阻塞 Phase D）

1. **OAuth 完整流没做** — Phase C 仅 PAT 直连，OAuth start/callback 端点没造（用户给的是 PAT，不需要 OAuth dance）。production 必须补
2. **`BUILDER_FERNET_KEY` 有 dev fallback** — `connection.py` 写了一个 hardcoded dummy key 作 fallback，注释标 "仅本地"，生产部署必须配真 key（用户的 `.env` 已配，无问题）
3. **commit_files (GitHub) 单文件循环** — 多文件场景每个文件一个 commit，git log 噪音大；后续可走 git data API（blob → tree → commit）一次提交
4. **execute_apply v1 仍不真调 platform API** — 仅切 `canonical_spec_id` 指针 + 推 git；真实部署到平台留 Phase E
5. **ChatPage 还没传 application_id** — Phase B fork hook 在生产侧未激活，需 ChatPage 改造一起 ship
6. **OAuth state CSRF 保护未做** — v2 OAuth 时一起补
7. **Repo init 用的 group_id_or_org 是字符串字段** — GitLab 实际需要 group path，GitHub 需要 org login。前端要根据 provider 切换提示文案，目前是同一个 input
