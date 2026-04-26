# Phase E 完成交接 — Real Platform Deploy + Fix-up + ChatPage Hook

**Date**: 2026-04-25
**Branch**: `claude/coding-shell-alignment` (HEAD `8e810d8`)
**Tests**: backend pytest 199 passed, frontend vue-tsc 干净
**Commits**: Phase E 共 5 个 commit（自 0692961 plan 起，不含 plan 自身）

---

## 落地内容

### 后端
- `backend/app/proposal/platform_apply.py` — `spec_diff_to_config_diff` (Spec → ConfigDiff 翻译) + `execute_platform_apply` (调 IncrementalExecutor)，支持 dry_run mode
- `backend/app/proposal/apply.py` — `execute_apply` 替换 noop，真接 IncrementalExecutor.execute_diff，apply_log 含 executor.journal
- `backend/app/proposal/fixup.py` — `create_fixup_proposal`：partial failure 时 fork 当前 draft + 创建新 ChangeProposal status='draft'（不自动 promote）

### 前端
- `frontend/src/views/ChatPage.vue` — send/send-with-file 调用带 application_id（激活 Phase B fork hook）
- `frontend/src/types/proposal.ts` — 加 ExecutorJournalEntry / ExecutorResult / ApplyLogV2 interfaces
- `frontend/src/views/ProposalDetailPage.vue` — applied 卡片新增"平台部署详情"折叠面板；apply_failed 新增 errors 列表 + 自动 fix-up proposal 跳转按钮

### 复用关键既有设施
- `backend/app/incremental_executor.py:IncrementalExecutor.execute_diff` (V1→V2 文档增量场景已验证)
- `backend/app/config_diff.py:compute_config_diff` (注：plan 写的 compute_diff 是错的，实际是 compute_config_diff)
- `backend/app/spec/converter.py:spec_to_config`

---

## 验证状态

### ✅ 已验证
- backend pytest 199 个 test 全 pass（Phase E 新增约 8 个：platform_apply 4 + apply 1 + fixup 3）
- frontend vue-tsc 干净
- 所有平台部署调用单元测试都 mock，零真 HTTP 到 aPaaS

### ⚠️ 未活体验证（**需要测试 tenant**）

整个 Phase E 的核心价值——真接 platform deploy——只在 mock 环境验证过。**生产部署前必须**：

1. 用测试 aPaaS tenant 上的 application（platform_url + token + apaas_app_id 配过）走完整链路：
   - ChatPage 编辑（带 application_id）→ fork hook 真触发 → SpecAgent 改 draft
   - promote → ProposalDetail → approve → apply
   - apply 真在测试 tenant 上创建对象/字段（去 aPaaS 平台 UI 验证）
2. 故意构造一个会失败的 case（如重复字段名、apaas_app_id 错的）→ 验 fix-up proposal 自动建 + 描述含 errors 摘要
3. **如果测试 tenant 不可用**，至少跑 dry_run mode（execute_platform_apply(dry_run=True) 通过既有的 build_apply_plan 触发）

---

## 整套 ABCDE 5 phase 完成

到此 spec [2026-04-25-collab-spec-git-integration-design.md](specs/2026-04-25-collab-spec-git-integration-design.md) 全部 5 phase（A 数据 + B 提案 + C git 出 + D git 入 + E 真激活）落地。

PR 准备：

```bash
gh pr create --title "feat: 协作式 SPEC 管理 + Git 双向同步 + 真接平台部署（Phase A-E）" --body "见 HANDOFF-collab-ABCD-summary.md（Phase A-D）+ HANDOFF-collab-phase-e-done.md（Phase E）"
```

---

## 已知 backlog（不阻塞，留给 Phase F 或之后）

1. **#3 UX 整体优化未做** — 用户最早需求里的"主流 Vibe Coding 交互参考"，独立 spec，需要 brainstorm + 设计调研。建议 Phase F 启动
2. **fix-up proposal 不自动 promote** — safer 决策；用户人工 review 后才进入 review 流。可后期加 "auto-promote on success rate threshold" 选项
3. **dry_run mode 已实现但 Phase B 第二道门未真用** — `build_apply_plan` 当前用自家 diff_spec；可后期切换到 execute_platform_apply(dry_run=True) 拿更精确的 platform-aware 报告
4. **ChatPage send-with-file fork hook** — Phase B chat.py 的 fork 逻辑只在 send 入口，send-with-file 路径暂未集成 fork。文档场景需要补
5. **OAuth state 防 CSRF** — Phase D 标过的 backlog
6. **GitHub revert 需 admin perm** — Phase D 标过的 backlog
7. **Workspace 反向 sync (repo→workspace)** — Phase D 标过
8. **审批数量阈值** — 当前 1 个 approve 即变 'approved'

---

## 临时数据 / 环境

- dev MySQL 协作相关表干净（Phase E 没人手动 promote/apply 跑过）
- backend `.env` 已有 BUILDER_FERNET_KEY + GITHUB_PAT（用户 Phase C 时配的，**生产前应撤销并改 OAuth client_id/secret**）
- 总 commit 数 (main..HEAD): 99，整个分支 ready for PR
