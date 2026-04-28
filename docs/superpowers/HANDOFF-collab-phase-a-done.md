# Phase A 完成交接 — 协作 SPEC + Git 集成

**Date**: 2026-04-25
**Branch**: `claude/coding-shell-alignment` (HEAD `1929e98`)
**Tests**: backend pytest 67 passed / 0 failed / 0 skipped, frontend vue-tsc 干净（无任何输出/错误）
**Commits**: 本次 Phase A（数据模型 + Project 协作）共约 16 个 commit（从 `5bd0272` 协作 spec 设计稿起到 `1929e98` Apps 页成员入口止）。整个 `claude/coding-shell-alignment` 分支相对 main 共 57 个 commit（含此前的 SPEC 状态机 Phase α/β/γ + UED + Tier 1 token 等前置工作）。详见 `git log --oneline main..HEAD`。

---

## 落地内容

### 数据库 + 后端
- DB migration（`backend/scripts/migrate_collab_v1.sql` + `run_migrations.py` 通用 runner）：
  - `__builder_migrations` 表追踪
  - 5 张协作空表：`application_members` / `change_proposals` / `proposal_reviews` / `git_connections` / `platform_drift_logs`
  - `specs.kind` ('canonical'|'draft') + `commit_sha`
  - `specs.tenant_id` 改 NOT NULL
  - `applications.module_owners JSON`
  - `project_members.role` 旧值映射（admin→maintainer, member→contributor）
- 5 个协作 ORM models（`backend/app/models/collaboration.py`）
- Spec 持久化乐观锁（`backend/app/spec/persistence.py` 加 `OptimisticLockError` + CAS 自增 + spec.version 同步回写）
- 4 档 role 体系（`backend/app/project_access.py`）含旧名 alias（admin/member 自动归一到 maintainer/contributor）
- `routes/projects.py` 接受新 role 名 + 旧名 alias 兼容
- `routes/application_members.py` 4 个 endpoints（GET/POST/PATCH/DELETE）
- Seed 脚本 `seed_default_projects.py` 已跑（dev MySQL backfill 28 个 orphan applications → Project + ProjectMember）

### 前端
- `types/collaboration.ts` — ProjectRole 4 档 + roleAtLeast / normalizeRole helpers + ROLE_DISPLAY_NAMES
- `api/applicationMembers.ts` — 4 个 API methods
- `components/MembersPanel.vue` — 可复用面板（list + 邀请 + 改 role + 移除）
- `views/Apps.vue` — 应用卡片 + 列表项加"成员"入口

---

## 验证状态

### 已验证
- 后端 pytest **67 个 test 全部 pass / 0 fail / 0 skip**（其中 Phase A 新增约 25 个：`test_application_members_api.py` / `test_collaboration_models.py` / `test_project_role_levels.py` / `test_projects_routes_phase_a.py` / `test_spec_optimistic_locking.py` / `test_spec_orm_phase_a.py`）
- 前端 vue-tsc 干净（无任何输出 = 无错误）
- DB schema 完整：
  - `__builder_migrations` 含 `migrate_collab_v1`
  - 5 张协作表全部建好：`application_members` / `change_proposals` / `git_connections` / `platform_drift_logs` / `proposal_reviews`
  - `specs.kind` + `specs.commit_sha` 列存在
  - `applications.module_owners` 列存在
  - `specs.tenant_id` IS_NULLABLE = `NO`
  - 0 个 orphan application（28 个已被 backfill）
  - `project_members.role` 当前实际值 `{owner, contributor}`（旧 admin/member 已 normalize 完毕）
- 乐观锁单元测试覆盖：单 save 自增 + 并发 stale version 抛 OptimisticLockError
- ApplicationMember 邀请流单元测试覆盖：list 合并 inherited+direct+creator / invite / 重复 400 / contributor 不能邀请 maintainer 403

### 未活体验证（推荐 Phase B 启动前先做）
- 真机点 Apps 页"成员"按钮 → 弹窗 → 邀请同 tenant 用户 → 用对方账号登录验证 role
- backend GET/POST/PATCH/DELETE `/api/applications/{id}/members` 用 curl 走一遍真实 token

---

## Phase B 开始指引

读 `docs/superpowers/specs/2026-04-25-collab-spec-git-integration-design.md` §10 Phase B 范围（ChangeProposal 提案制完整流程），按相同流程产出 `docs/superpowers/plans/2026-04-25-collab-phase-b-proposal-flow.md` 后开始执行。

Phase B 范围核心：
1. ChatPage SpecAgent 改打 personal draft（fork canonical），用 Spec.kind 区分
2. DraftBanner + Promote to Proposal 按钮
3. 第一道门 + 第二道门校验逻辑
4. ProposalDetailPage（diff + review + approve + apply）
5. 不可逆操作确认 modal
6. 变更中心 v1（重写 BuilderDevOpsPage，Proposals tab + Apply 历史 tab）

Phase B 直接复用：
- `ChangeProposal` ORM model（Phase A 已建空表）
- `ProposalReview` ORM model
- Spec 乐观锁（多 draft 并发安全）
- 4 档 role + ApplicationMember 体系（决定谁能 approve）

---

## 已知 backlog（不阻塞 Phase B）

1. **`coding.py` / `applications/__init__.py` 等其他 routes** 仍用旧 role 名 hardcode（如 `minimum_role="member"`）。靠 normalize alias 兼容工作正常，可在 Phase B 顺手统一到新名。
2. **MembersPanel 用了原生 `alert()` / `confirm()`**，和 Apps.vue 既有 ElMessageBox 风格不一致。Phase B/C 视觉对齐时一起改。
3. **ProjectOverview 页的"成员" tab** 还没用 MembersPanel（v1 走老 UI），Phase B 时可顺手切换。
4. **`run_migrations.py` 没做 file-content hash check**，编辑 `migrate_collab_v1.sql` 后再运行不会警告（只靠 errno 1060 兜底）。Phase B 起追加 migration 时如有需要再升级 runner。

## 临时数据（dev MySQL，不影响生产）

- 28 个 orphan Application 已被 seed 脚本配上 Project + ProjectMember(owner) — 描述"自动创建（来自应用 X 迁移）"
- 测试用的 `spec_smoke_*` / `cp_test_*` 等数据可能残留，Phase B 起会覆盖，无需清理
