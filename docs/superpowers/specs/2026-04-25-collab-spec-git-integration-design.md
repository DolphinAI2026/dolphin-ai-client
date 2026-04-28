# 协作式 SPEC 管理 + Git 打通 — 设计 Spec

**Date**: 2026-04-25
**Status**: Approved (brainstorm 阶段已锁)
**Branch base**: `claude/coding-shell-alignment` (HEAD `7a9d808`)
**Predecessors**:
- `docs/superpowers/specs/2026-04-25-spec-state-machine-design.md`（SPEC 状态机三 phase）
- `docs/superpowers/HANDOFF-2026-04-25.md`（上一会话交接）

---

## 0. 一句话目标

让多人能在同一个低代码应用上协作编辑 SPEC（变更提案制）+ 把应用整个项目（SPEC + 自开发代码）双向同步到 GitLab/GitHub repo，**不能因为协作并发把平台搞坏**（低代码部署不可逆）。

---

## 1. 根因诊断：为什么不能直接套 git 心智

需求看起来是"做项目组 + 多 SPEC + git 打通"——一开始很容易设计成 git 风格自由分支 + merge。但低代码场景有个根本约束：

**SPEC 一旦 apply 到平台，许多操作物理不可逆**：
- 创建对象 / 字段 → 删除会丢业务数据
- 修改字段类型 → 数据精度可能丢失
- 删字段 / 删对象 → 历史数据不可恢复
- 改权限 → 真用户立即受影响

git merge 假设"代码是文本，merge 错了改一下就行"。低代码 SPEC 的"merge 错了"代价是丢生产数据。

**正确类比不是 git，是数据库 migration**（Flyway / Liquibase / Rails migrations）：变更有顺序、串行 apply、不可逆操作必须人工确认。

---

## 2. 五个核心架构决策（已锁）

### 2.1 多 SPEC 模型：E. Canonical + 变更提案制

```
[Personal Drafts]  ──promote──→  [Change Proposal]  ──apply (串行)──→  [Canonical SPEC]
   每人各自 fork                  评审 + 校验                            = 平台部署状态
```

- 一个 application 只有一个 canonical SPEC（与平台部署状态一一对应）
- 多人各自从 canonical fork personal draft，并行编辑互不影响
- draft 升级成 ChangeProposal 后进入评审 → apply
- **apply 永远串行**，每次 apply 后 canonical 推进一个版本

**否决的方案**：
- A/D（git 风格自由分支 + merge）：因 SPEC 不可逆，merge 后产生的平台冲突无法回退
- B（章节切片并行编辑）：跨章节引用一致性难保证，git 心智模型不对齐
- C（变体并行）：不解决"多人改同一应用"的协作问题

### 2.2 双层校验门

每个 ChangeProposal 经过两道独立的校验门：

**第一道门（promote 时）—— 文档校验**：
- 完整性（5 类卡片：goal / role / object / dict / permission 是否齐全）
- 一致性（角色引用对象是否存在、字段类型合法、命名无冲突）
- markdown 渲染干净（无 YAML 损坏）
- **不联平台**，快、便宜、可大量并行

**第二道门（apply 时）—— 平台校验**：
- 重新对比最新 canonical（rebase 检测）
- 平台 dry-run（命名是否冲突、API 是否可达）
- 标记每个 op 的可逆性（绿/黄/红）
- 红色 op 必须 owner 二次确认
- **联平台，串行执行**

人类审阅看到的永远是 markdown 视图（结构化 SPEC 是内部 source of truth，markdown 是 derived view）。

### 2.3 协作权限：C. 应用级审批 + 模块 owner 钩子

- 起步只做应用级审批：proposal 只需 application owner 之一 approve
- `Application.module_owners` 用 JSON 列预留扩展点（v1 默认空，v2 升级到正式表）
- 评审者列表 = ProjectMember（项目继承）+ ApplicationMember（应用直接邀请，可选）

### 2.4 仓库拓扑：A. 应用单仓（monorepo per app）

每个 Application 一个 git repo，业务和实现代码同仓：

```
<app-name>/
├── .builder/                  # 工具元信息
│   ├── manifest.json
│   └── apply-log/
├── spec/
│   ├── canonical.md           # 渲染视图（人读）
│   ├── canonical.json         # 结构化 source of truth
│   └── history/
├── workspaces/                # CodingPage 工作区
│   ├── <workspace-name-1>/
│   └── <workspace-name-2>/
└── README.md
```

业务方能在 PR 里同时看到 SPEC 改动 + 配套代码改动，原子性强。

### 2.5 同步方向：方向 3 双向同步

- Builder UI 操作 → 自动 commit + push（出方向）
- IDE/git push → webhook → 同步到 Builder draft / 自动建 ChangeProposal（入方向）
- **关键安全阀：apply 永远在 Builder 后端发生**。git 平台直接 merge MR/PR 会被 Builder 拦截（自动 revert + comment 提示"请在 Builder 中 apply"），保证不可逆操作必经 Builder 第二道门

### 2.6 组织层次：C. Project（组）+ Application（仓）双层

- `Project` = 项目组，对应 GitLab Group / GitHub Org
- `Application` = 单应用，对应 git Repo
- 默认 1 Project = 1 Application（建应用时自动建同名 Project）
- role 体系统一为 owner / maintainer / contributor / viewer（对齐 GitLab）

---

## 3. 数据模型变更

### 3.1 改造的表

| 表 | 改动 |
|----|------|
| `Project` | 取消"过渡"标注；统一 role 命名（owner/maintainer/contributor/viewer）；加 `git_connection_id` |
| `ProjectMember` | role 字段值统一为 4 档（旧 `member` → `contributor`，`admin` → `maintainer`） |
| `Application` | 加列：`git_repo_url`, `git_provider`, `git_default_branch`, `git_last_sync_sha`, `module_owners JSON nullable` |
| `Spec` | 加列：`kind: 'canonical' \| 'draft'`，`commit_sha nullable`（apply 后绑定的 git commit），`tenant_id` 改成 nullable=False without default |

### 3.2 新建的表

**`ChangeProposal`** — 一个变更提案的全生命周期：
```python
id: str                          # uuid
application_id: int (FK)
title: str
description: str                 # markdown body
draft_spec_id: str (FK Spec)
base_canonical_spec_id: str (FK)
status: str                      # draft|open|changes_requested|approved|applying|applied|apply_failed|closed
validation_report: JSON          # 第一道门结果
apply_plan: JSON                 # 第二道门 = ops 清单 + 可逆性标记
apply_log: JSON                  # 实际执行结果
git_branch: str                  # spec/proposal-xxx
git_pr_url: str | None
created_by: int (FK User)
created_at, updated_at, applied_at
```

**`ProposalReview`** — 多人评审记录：
```python
id, proposal_id, reviewer_id, action (approve|request_changes|comment), body, created_at
```

**`GitConnection`** — Project 级 git 平台凭证：
```python
id, project_id (FK), provider (gitlab|github), host, access_token_enc, group_id_or_org, status, created_at, updated_at
```

**`ApplicationMember`** — 应用级外部协作者：
```python
id, application_id (FK), user_id (FK), role, invited_by, created_at
```

**`PlatformDriftLog`** — 漂移检测日志：
```python
id, application_id, detected_at, git_sha, builder_canonical_sha, kind (drift_detected|resolved), resolution_direction, resolved_by, resolved_at
```

---

## 4. ChangeProposal 状态机

```
                 ┌──────── reject/close ───────┐
                 │                              │
                 ↓                              │
              [closed]                          │
                 ↑                              │
   ┌─────────────┴─────────────┐                │
   │                           │                │
[draft] ──promote──→ [open] ──┬─→ [changes_requested] ──update──→ [open]
                              │
                              └─→ [approved] ──apply──→ [applying]
                                                            │
                                                            ├─→ [applied]
                                                            └─→ [apply_failed]
```

| 转换 | 触发 | 校验门 |
|------|------|--------|
| draft → open | "Promote" | 第一道门 |
| open → changes_requested | reviewer "Request changes" | — |
| changes_requested → open | 提案者更新 draft 后重新 push | 重跑第一道门 |
| open → approved | reviewer "Approve" + role 满足 | 检查 reviewer count（默认 ≥1 owner） |
| approved → applying | apply 操作发起 | 第二道门 + rebase + 不可逆确认 |
| applying → applied | 所有 ops 成功 | canonical_spec_id 推进 + git tag |
| applying → apply_failed | 任何 op 失败 | **不回滚**（按规则记录），自动开 fix-up proposal |
| any → closed | 主动关闭 | 不能恢复（要新开 proposal） |

**"partial apply 失败不回滚"是关键设计决策**：因为低代码不可逆，失败后已成功的 ops 不能撤销。设计上：
- apply_log 详细记录每一步成功/失败
- 失败 → proposal 标 `apply_failed`，自动开新 fix-up proposal 帮用户继续后面失败的 ops
- canonical 不立刻推进；要 fix-up proposal 也 apply 成功后才统一推进

---

## 5. 与现有 SpecAgent 的集成

现有 `backend/app/spec/agent.py` 的 `SpecAgent.run()` 已能修改 SPEC。增量改动：

1. **chat 时 SpecAgent 编辑的对象 = 当前用户的 personal draft**（自动 fork canonical）
2. ChatPage SpecInspector 加 "Promote to Proposal" 按钮 → 调 `POST /api/applications/{id}/proposals` → 第一道门 + 创建 proposal + push branch + open PR（如绑 git）
3. first-turn enforcement 保留，但聚焦"和 canonical 的差异点"
4. `bootstrap_from_doc(silent/interactive)` 输出 draft；`bootstrap_from_doc(diff_only)` 输出已 promote 的 ChangeProposal

---

## 6. Git 双向同步机制

### 6.1 Branch 约定

- `main` = canonical 分支（保护，只接受 PR merge）
- `spec/proposal-<short-id>` = 每个 ChangeProposal 自动建一个分支
- `code/workspace-<name>-<feature>` = CodingPage 主动开的代码协作分支
- 不允许直接 push main

### 6.2 出方向（Builder → Git）

| 触发 | 行为 |
|------|------|
| 用户在 ChatPage 编辑 draft | 内存中累积，**不立即推**（避免每条 message 一个 commit） |
| 用户点 "Promote to Proposal" | 第一道门通过后，create branch + commit `spec/canonical.md` + `spec/canonical.json` + open PR |
| Reviewer comment / approve | 通过 git API 写到 PR 上 |
| ChangeProposal apply 成功 | merge PR + tag commit（`apply-<timestamp>`） + 推 `apply-log/` |
| 用户在 CodingPage 改代码点 "Sync to repo" | commit + push 到当前 workspace 分支 |

### 6.3 入方向（Git → Builder）

| webhook event | Builder 行为 |
|---------------|-------------|
| `push` to feature branch | 同步 repo 文件到对应 draft SPEC / workspace 文件系统 |
| `merge_request opened` (GitLab) / `pull_request` (GitHub) | 自动创建对应 ChangeProposal |
| `merge_request comment` / `pull_request review` | 同步到 ProposalReview 表 |
| `merge_request merged` 直连点击 | **拦截！**自动 revert merge commit + 在 PR 上 comment："请在 Builder 中 apply" |

### 6.4 Workspace ↔ git subdir 映射

CodingPage workspace 与 repo 的 `workspaces/<name>/` 子目录双向同步：

- 创建 workspace → 在 repo 里建对应子目录 + 写 `.builder.workspace.json`
- 删 workspace → repo 里 `git rm -r workspaces/<name>` + push
- 用户编辑 workspace 文件 → 本地变更先存 builder DB，**用户主动点 "Sync to repo" 才 push**（避免半成品 commit）
- 反向：repo 里 push 改了 `workspaces/x/file.vue` → webhook → 同步到 builder workspace 文件系统

### 6.5 漂移检测

每次 apply 之前 + 定时（每 5 分钟）：

```python
git_canonical_sha = git.get_branch_head(repo, "main")
db_canonical_sha = application.git_last_sync_sha
if git_canonical_sha != db_canonical_sha:
    log to PlatformDriftLog
    block apply
    surface UI banner
```

漂移成因：有人绕过 Builder 直接 git merge / 强 push / 删分支。处理流：
- UI banner："Git main 比 Builder 状态新，请先同步"
- 进入"修复模式"，**只有 project owner** 能选解决方向：
  - "以 git 为准重置 Builder canonical"（危险，会改 builder 状态）
  - "以 Builder 为准强推 git"（覆盖 git 历史）

---

## 7. API 表面

### 7.1 新增 endpoints

```
# Project / 协作
POST   /api/projects                     创建项目（自动建同名 Application 选项）
GET    /api/projects/{id}/members        列出成员
POST   /api/projects/{id}/members        邀请成员
DELETE /api/projects/{id}/members/{uid}
PATCH  /api/projects/{id}/members/{uid}  改 role

# Application member
POST   /api/applications/{id}/members
GET    /api/applications/{id}/members

# ChangeProposal
POST   /api/applications/{id}/proposals          create from draft (promote)
GET    /api/applications/{id}/proposals          list (filter by status)
GET    /api/proposals/{id}                       detail
PATCH  /api/proposals/{id}                       update title/desc
POST   /api/proposals/{id}/refresh-validation    重跑第一道门
POST   /api/proposals/{id}/reviews               提交 review
POST   /api/proposals/{id}/apply                 触发 apply（含 confirm_irreversible: bool）
POST   /api/proposals/{id}/close

# Git connection
POST   /api/projects/{id}/git-connection         OAuth 启动
GET    /api/projects/{id}/git-connection
DELETE /api/projects/{id}/git-connection
POST   /api/applications/{id}/git-init           为应用初始化 repo

# Webhook 入口
POST   /api/webhooks/git/{provider}              统一入口，X-Hub-Signature 校验

# 漂移检测
GET    /api/applications/{id}/drift-status
POST   /api/applications/{id}/resolve-drift

# Workspace ↔ git
POST   /api/workspaces/{id}/sync-to-repo
POST   /api/workspaces/{id}/sync-from-repo
```

### 7.2 改动 endpoints

- `/api/conversations/{id}/send` 系列：SpecAgent 修改对象从 `conversation.spec_id` 改成 `current_user_draft_for(application_id)`，自动 fork canonical
- `/api/applications/{id}/upgrade-from-legacy`（已就绪）：扩展为同时初始化 ProjectMember 默认 owner=created_by

---

## 8. 前端 UI 改动

### 8.1 变更中心（重写 BuilderDevOpsPage）

5 个 tab：

| Tab | 内容 |
|-----|------|
| Proposals | 当前 application 的 PR 列表，按状态分组，每行显示标题、提案者、reviewer、status badge、git PR 链接 |
| Apply 历史 | canonical SPEC 推进历史 = git main 上的 commit 列表 |
| Git 仓库 | repo 绑定状态、漂移检测 banner、近 10 次 sync 日志 |
| 环境拓扑 | （现有 mock 保留） |
| 审批中心 | 待我审批的 proposal 集中视图（跨多个 application） |

路由保持 `/devops`。

### 8.2 ChatPage DraftBanner

SpecCanvas 顶部加 banner：
```
┌──────────────────────────────────────────────────────────────┐
│ ✏️ 你正在编辑草稿（基于 canonical v3）                       │
│ 🔗 当前提案：<None>     [Promote to Proposal] [Discard Draft] │
└──────────────────────────────────────────────────────────────┘
```

### 8.3 ProposalDetailPage（新增）

类似 GitHub PR 页面：
- 左：markdown diff（canonical vs draft）
- 右上：validation_report 状态、apply_plan 摘要（X 个可逆 / Y 个不可逆 → 红黄绿条）
- 右下：评审区（reviewers + comments）
- 底部 action bar：Approve / Request changes / Comment / Apply（仅 approved 状态可见，含不可逆确认 modal）

### 8.4 CodingPage workspace 同步控件

workspace 头部加：
- "Sync to repo" 按钮（如已绑定 git）
- 当前同步状态（in sync / 本地有未推变更 / 远端有未拉变更）
- 切换分支下拉

### 8.5 Apps 页 + Project 详情页

- Apps 页：每个 application 卡片加 "成员" 入口（管理 ApplicationMember 外部协作者）
- Project 详情页：新增 "成员" tab（管理 ProjectMember，role 增删改）+ "Git 集成" tab（OAuth 接入入口 + GitConnection 状态）

---

## 9. 迁移策略

| 类型 | 迁移策略 |
|------|----------|
| 已存在 application + 无 canonical_spec_id | 老路径继续工作；UI banner 引导 "升级到 SPEC 模式"（已有后端 endpoint） |
| 已存在 application + 有 canonical_spec_id 但无 Project | 自动建同名 Project + 把 created_by 加为 owner + Application.project_id 指过去 |
| Project 表里有数据 | role 字段值映射：旧 `member` → 新 `contributor`，`admin` → `maintainer`，`owner` 不变 |
| ChangeProposal / GitConnection / ApplicationMember / ProposalReview / PlatformDriftLog | 新建空表，无历史数据 |

迁移脚本：
- `backend/scripts/migrate_collab_v1.sql`（DDL + role 字段值更新）
- `backend/scripts/seed_default_projects.py`（为孤立 Application 建 Project + ProjectMember）

幂等可重跑。

---

## 10. 分阶段交付节奏（5-6 周）

### Phase A — 数据模型 + Project 协作（第 1 周）

纯后端 + Project/Application 协作能力，不动 git。

- 改 `Project` / `ProjectMember`，统一 role
- 新建 `ApplicationMember` / `ChangeProposal` / `ProposalReview` / `GitConnection` / `PlatformDriftLog` 空表
- 改 `Spec.kind` 列 + draft fork 逻辑
- API：`/api/projects/*` member 管理
- 前端：Apps 页加 "成员" tab
- 迁移脚本

ship 价值：多人能加入同一 project，但 SPEC 编辑还是单人。

### Phase B — ChangeProposal 提案制（第 2-3 周）

完整的 promote → review → apply 流程，但不接 git。

- ChatPage SpecAgent 改打 personal draft（fork canonical）
- DraftBanner + Promote 按钮
- 第一道门 + 第二道门校验逻辑
- ProposalDetailPage（diff + review + approve + apply）
- 不可逆操作确认 modal
- 变更中心 v1（Proposals tab + Apply 历史 tab）

ship 价值：协作完整，覆盖"多人改一个应用 + 串行 apply + 不可逆保护"核心价值。

### Phase C — Git 出方向（第 4 周）

单向 Builder → Git，git 是只读镜像。

- GitConnection OAuth 流（GitLab + GitHub 各做一遍，pluggable provider 抽象）
- repo 自动初始化（`/api/applications/{id}/git-init`）
- promote → push branch + open MR/PR
- apply → merge + tag + 推 apply-log
- 变更中心 Git 仓库 tab + Apply 历史里的 git commit 链接

ship 价值：业务 + 开发者能在 git 上看 PR 和代码，但 git 不能反向触发 Builder。

### Phase D — Git 入方向（第 5-6 周）

双向同步 + 漂移检测 + workspace 集成。

- Webhook 入口 + 验签
- push 同步到 draft / proposal
- 直连 merge 拦截（revert + comment）
- 漂移检测 + UI banner + 解决流
- CodingPage workspace ↔ repo subdir 同步
- Sync to repo 按钮 / 分支切换

ship 价值：完整双向 git 集成。

### Phase 0（可选）— 清现有 backlog

如果决定先把现有交接文档列的 4 项中优先级 backlog 清完再做 Phase A，单独 0.5-1 周：
1. β follow：「升级到 SPEC 模式」UI banner
2. γ follow：前端 v2_doc_text 字段
3. α 安全 follow：`Spec.version` optimistic locking（多人并发场景必须）
4. `Spec.tenant_id default=1` 改成显式赋值

**推荐 Phase 0 与 Phase A 并行启动**，A 中"统一 role 命名"和 "Spec.tenant_id 修正"本身就是 schema 改动，可以合一起 ship。

---

## 11. 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| **partial apply 失败 → 平台状态半成品** | 设计 fix-up proposal 自动开机制；apply_log 详细记录；canonical 不推进直到全部 success |
| **直连 git merge 绕过第二道门** | webhook 拦截 + 自动 revert + comment 提示 |
| **多 git 平台抽象成本** | 起步只做 GitLab + GitHub 两家，pluggable interface 但不过度抽象（不做 generic git daemon） |
| **漂移检测误报** | sync 时正确记录 sha；漂移阻断 apply 但不阻断编辑（编辑 draft 不需要 sha 一致） |
| **现有用户迁移失败** | 迁移脚本幂等可重跑；保留老路径（无 canonical_spec_id 的 application 走老流程）作为 fallback |
| **优先级反转：UX 不友好导致功能没人用** | UX 优化（#3 任务）单独 spec 推进，与本 spec 解耦，可并行做 |

---

## 12. 不在范围内（Out of scope）

明确划出去：

- **#3 UED 优化**：单独 spec，本设计不涉及视觉重设
- **跨 application 复用 SPEC 模板库**：v2 议题
- **跨平台 git daemon 抽象**：起步只做 GitLab + GitHub
- **审批工作流引擎**：不实现复杂的多级审批 / 串行审批 / 自动指派，起步只做"≥1 个 owner approve"
- **冲突自动 merge**：rebase 冲突由人工解决，不实现 SPEC 字段级三方 merge 算法
- **细粒度章节锁**：`module_owners` 字段预留但不实现 v1 章节级锁
- **PR 之外的协作单位**（如 issue / discussion）：起步不做

---

## 13. 验收标准

每个 phase 必须满足：

**Phase A**：
- 后端 pytest 全过 + 新增 model 单元测试
- 迁移脚本在 dev MySQL 跑通
- 前端 Apps 页能创建 Project、邀请成员、改 role

**Phase B**：
- 多人 chat 编辑同一应用产生独立 draft，互不影响
- promote → 第一道门拦截不合法 SPEC（缺卡片/类型不匹配）
- approve + apply 链路全过，不可逆操作确认 modal 弹出
- 变更中心列出至少 1 个 applied + 1 个 open proposal

**Phase C**：
- GitLab + GitHub 各跑通一次端到端：创建 application → 绑 git connection → init repo → 推 spec/canonical.json + spec/canonical.md
- promote → 在 git 平台上看到 MR/PR 自动创建
- apply → git 平台上 PR 被 merge + tag

**Phase D**：
- IDE 端 push 触发 Builder 自动建 ChangeProposal
- 直连 merge 被拦截 + 自动 revert
- workspace 编辑 sync 到 repo 后，从另一个浏览器拉 repo 能看到一致内容
- 漂移检测 banner 在伪造场景下正确触发

---

## 14. 决策日志（供下游 plan 引用）

| # | 决策 | 否决方案 | 锁定理由 |
|---|------|----------|----------|
| D1 | E. Canonical + Proposal 制 | A/D（git-merge）、B（章节切片）、C（变体） | 低代码不可逆，git merge 心智不适用 |
| D2 | 双层校验门 | 单层 | 第一道门快+多人并行，第二道门保证不可逆安全 |
| D3 | C. 应用级审批 + module_owner JSON 钩子 | A（仅应用级）、B（全章节锁） | 兼顾 v1 简单和 v2 扩展 |
| D4 | A. 应用单仓 | B（双仓）、C（租户 monorepo）、D（先只做 SPEC repo） | 业务 ↔ 实现强耦合天然存在；GitLab/GitHub 一一对应 |
| D5 | 方向 3 双向同步 | 1（builder 主导）、2（git 主导） | 业务方走 UI、开发者走 git，apply 必经 builder |
| D6 | C. Project + Application 双层 | A（仅 Project 继承）、B（仅 ApplicationMember） | 与 GitLab Group/Org → Repo 1:1 对齐 |
| D7 | partial apply 失败不回滚 | 自动反向 ops | 违背"不可逆"原则；自动开 fix-up proposal 替代 |
| D8 | 直连 git merge 拦截 | 不拦截 + git CI 钩子 | apply 必经 builder 第二道门，否则不可逆操作无法保护 |
| D9 | workspace 用户主动 sync | 自动每次保存 push | 避免半成品 commit + 工程量低 |

---

## 15. 下一步

完成本 spec 评审后，进入 `writing-plans` 流程，按 Phase A → B → C → D 顺序产出 4 个独立 implementation plan。每个 phase 一个 plan，可独立执行 + 独立 ship。
