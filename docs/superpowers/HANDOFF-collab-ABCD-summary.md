# 协作 SPEC + Git 集成（4 phase）整套交付总结

**Date**: 2026-04-25
**Branch**: `claude/coding-shell-alignment` (HEAD `cfa5b5b`)
**Tests**: backend pytest 191 passed, frontend vue-tsc 干净
**Total commits since main**: 91

整套 spec：[2026-04-25-collab-spec-git-integration-design.md](specs/2026-04-25-collab-spec-git-integration-design.md)

---

## 4 个 phase 落地一览

### Phase A — 数据底座 + Project 协作（已完成）
- DB migration（5 张协作空表 + `Spec.kind/commit_sha` + `Application.module_owners`）
- 5 个协作 ORM models
- Spec 乐观锁
- 4 档 role（owner/maintainer/contributor/viewer，旧名 alias）
- ApplicationMember 邀请 API + Apps 页成员入口
- Seed 28 个 orphan applications 配 Project + ProjectMember
- HANDOFF: [HANDOFF-collab-phase-a-done.md](HANDOFF-collab-phase-a-done.md)

### Phase B — ChangeProposal 提案制（已完成）
- `proposal/{persistence,validation,apply}.py`
- `routes/proposals.py` — 8 endpoints (promote/list/get/patch/refresh/close + reviews + apply)
- `spec/persistence.py` 加 `fork_canonical_to_draft`
- 第一道门（doc 校验）+ 第二道门（reversibility + 不可逆确认）
- 前端 DraftBanner + ProposalDetailPage + 变更中心 v1
- HANDOFF: [HANDOFF-collab-phase-b-done.md](HANDOFF-collab-phase-b-done.md)

### Phase C — Git 出方向（已完成）
- `git/provider/{base,gitlab,github}.py` — Protocol + 双 impl
- `git/{connection,repo_init,sync}.py` — Fernet + repo init + promote/apply hook
- `routes/git_connection.py` — PAT connection + git-init + drift（Phase D 扩展）
- 前端 ProjectGitSetup + BuilderDevOpsPage Git tab + ProposalDetail PR 链接
- HANDOFF: [HANDOFF-collab-phase-c-done.md](HANDOFF-collab-phase-c-done.md)

### Phase D — Git 入方向 + Webhook + Workspace + OAuth（已完成）
- `git/webhook.py` + `inbound.py` + `inbound_intercept.py` — 验签/handlers/拦截
- `git/drift.py` + `workspace_sync.py`
- `routes/git_webhook.py` + OAuth start/callback 端点
- 前端 DriftBanner + GitOAuthCallback + CodingPage Sync 按钮 + ProjectGitSetup OAuth 按钮
- HANDOFF: [HANDOFF-collab-phase-d-done.md](HANDOFF-collab-phase-d-done.md)

---

## 测试 / 编译状态

- **Backend**: pytest 191 passed, 0 failed, 0 skipped
- **Frontend**: vue-tsc clean
- **DB migrations applied**: `migrate_collab_v1`, `migrate_collab_phase_c`, `migrate_collab_phase_d`

---

## 关键架构决策（spec §14 决策日志）

| # | 决策 | 落地位置 |
|---|------|----------|
| D1 | Canonical + Proposal 制（非 git-merge） | Phase A schema + Phase B proposals |
| D2 | 双层校验门 | Phase B validation + apply |
| D3 | 应用级审批 + module_owner JSON 钩子 | Phase A models |
| D4 | 应用单仓 | Phase C repo_init |
| D5 | 双向同步，apply 必经 Builder | Phase C outbound + Phase D inbound + 拦截 |
| D6 | Project + Application 双层 | Phase A 角色体系 |
| D7 | partial apply 失败不回滚 | Phase B execute_apply（v1：失败仅 log，fix-up auto-open 留 v2） |
| D8 | 直连 git merge 拦截 | Phase D inbound_intercept |
| D9 | workspace 用户主动 sync | Phase D workspace_sync + CodingPage 按钮 |

---

## 准备 PR

整套 4 phase 在 `claude/coding-shell-alignment` 分支，91 commits ahead of main。建议：

```bash
gh pr create --title "feat: 协作式 SPEC 管理 + Git 双向同步（Phase A+B+C+D）" --body "见 HANDOFF-collab-ABCD-summary.md 总览"
```

PR 描述大纲：
- 协作 4 档 role + ApplicationMember
- ChangeProposal 提案制（promote/review/apply 含不可逆确认）
- GitLab + GitHub 双 provider + OAuth + PAT 双连接模式
- Webhook 入方向 + 直连 merge 拦截 + 漂移检测
- Workspace 单向 push 同步

---

## 下一阶段 — Phase E（建议范围）

1. apply 真接 platform deploy（替代当前的 canonical 指针切换 noop）
2. fix-up proposal 自动开机制（D7 决策的完整版）
3. ChatPage 改造传 `application_id` 激活 fork hook
4. UX 整体优化（spec 第 3 个原始需求 #UED）

读 spec §10 Phase E hint 启动。
