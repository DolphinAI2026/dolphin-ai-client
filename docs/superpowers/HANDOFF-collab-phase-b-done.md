# Phase B 完成交接 — ChangeProposal 提案制流程

**Date**: 2026-04-26
**Branch**: `claude/coding-shell-alignment` (HEAD `3742b86`)
**Tests**: backend pytest 100 passed (442 warnings, 0 failed/skipped, 1.45s), frontend vue-tsc 干净
**Commits**: Phase B 共 12 个 commit（详见 `git log --oneline e055644..HEAD`，含 1 个 plan 文档 + 11 个实现 commit）

---

## 落地内容

### 后端
- `backend/app/proposal/persistence.py` — `create_proposal / load_proposal / list_proposals / ProposalView`
- `backend/app/proposal/validation.py` — 第一道门 4 个 check（completeness / consistency / naming / markdown）+ 聚合 `validate(spec) → ValidationReport`
- `backend/app/proposal/apply.py` — 第二道门：`build_apply_plan` 算 diff + reversibility 标 + rebase 检测；`execute_apply` v1 简化版仅切 canonical_spec_id 指针
- `backend/app/spec/persistence.py` — 加 `fork_canonical_to_draft` helper
- `backend/app/routes/proposals.py` — 6 个 endpoints + reviews + apply
- `backend/app/routes/chat.py` — fork on first edit hook（chat 入口若 conversation.spec_id 空 + application_id 给 + canonical 存在 → fork）
- `backend/app/schemas.py` — `ChatRequest.application_id` 可选

### 前端
- `frontend/src/types/proposal.ts` — types
- `frontend/src/api/proposals.ts` — API client (7 methods)
- `frontend/src/components/spec/DraftBanner.vue` — 草稿提示 banner
- `frontend/src/views/ProposalDetailPage.vue` — 提案详情页（左 description+plan / 右 validation+reviews+actions / 不可逆 modal）
- `frontend/src/views/BuilderDevOpsPage.vue` — 重写为变更中心 v1（Proposals tab + Apply 历史 tab + 老 mock）
- `frontend/src/router/index.ts` — 加 `/proposals/:id` 路由

---

## 验证状态

### ✅ 已验证
- backend pytest **100/100 passed**（Phase B 新增约 33 个：persistence 3 + fork 3 + validation 5 + routes 7 + reviews 7 + apply 7 + 1 个 chat fork hook test）
- frontend vue-tsc 干净（无类型错误）
- 第一道门 4 项 check 单元测试覆盖
- 第二道门 reversibility 计算 + rebase 检测 + 不可逆确认流单元测试覆盖
- ApplicationMember 权限沿用 Phase A，maintainer+ 才能 approve / apply
- dev MySQL schema 可正常 query：`change_proposals`、`proposal_reviews`、`specs.kind` 索引完整（当前 22 条 draft、0 条 canonical、0 个 proposal/review，符合 Phase B 未活体跑过的预期）

### ⚠️ 未活体验证（推荐 Phase C 启动前先做）
- 真机端到端：登录 → 进 ChatPage（带 application_id） → SpecAgent 编辑 → fork 触发 → DraftBanner 显示 → Promote → ProposalDetailPage → approve（换账号） → apply（含不可逆 modal） → canonical 推进
- chat.py `send-with-file` 端点暂未注入 fork hook（Task 9 仅改 `send`），如需文档上传场景下走 fork 流，要 Phase C 补
- ChatPage 当前还没传 `application_id`（fork hook 还在等调用方），上线前需要 ChatPage 改造

---

## Phase C 启动指引

读 `docs/superpowers/specs/2026-04-25-collab-spec-git-integration-design.md` §10 Phase C（git 出方向）：

核心范围：
1. GitConnection OAuth 流（GitLab + GitHub）
2. repo 自动初始化（POST /api/applications/{id}/git-init）
3. promote → push branch + open MR/PR
4. apply success → merge + tag + 推 apply-log
5. 变更中心 Git 仓库 tab + Apply 历史里的 git commit 链接

直接复用：
- `GitConnection` ORM model（Phase A 已建空表）
- `ChangeProposal.git_branch / git_pr_url` 字段（Phase A schema 就有）
- 第二道门完整流（apply 后的 hook 加 push）

---

## 已知 backlog（不阻塞 Phase C）

1. **`execute_apply` v1 不真调 platform API** — 仅切 canonical_spec_id 指针。Phase C 后接 git，apply 真链路（部署到平台）建议放到 Phase D 之后单独作为 Phase E 重整 generation flow
2. **diff 渲染 v1 是文本摘要** — ProposalDetailPage 左侧没做并排 markdown diff。Phase C 加 git 后用 `diff` 包做真 diff
3. **chat.py `send-with-file` 没注入 fork hook** — 文档上传场景下 fork 不触发
4. **fix-up proposal 自动开机制未实现** — apply_failed 时不会自动开新 fix-up proposal（spec D7 决策原话："失败 → 自动开新 fix-up proposal 帮用户继续"）
5. **ChatPage 还没传 `application_id`** — 当前 fork hook 在生产侧不会触发，要 ChatPage 改造一起 ship
6. **审批数量阈值** — 当前 1 个 approve 即变 'approved'。Spec 提到"≥1 个 owner approve"未严格实现，目前是 maintainer+ 也能 approve
7. **MembersPanel + 各 modal 用了原生 alert/confirm** — UX 不统一，Phase C/D 视觉对齐时一起改

## 临时数据

dev MySQL 有 5 张协作表（Phase A 创建的），Phase B 没在 dev 数据上跑 promote/apply 流，仍是空表（proposals=0, reviews=0, canonical=0, draft=22）。
