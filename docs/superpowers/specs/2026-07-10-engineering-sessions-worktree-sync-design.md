---
title: 工程会话与 Worktree 同步机制设计
date: 2026-07-10
status: implemented
language: zh-CN
scope: agentic-ai-user 代码生命周期
---

# 工程会话、Worktree 与同步机制设计

> 实现状态：第一版后端模型、YAML registry、Git 状态读取、worktree 管理、checkpoint、archive、reconcile、本地 CLI 和 README 入口已落地。产品 UI、完整工程经理技能、验证记录和自动清理仍按 P3-P5 后续推进。

## 背景

当前 `builder-ai/code` 的工作流已经覆盖新建功能、修 BUG、本地运行、后台管理、认证配置、部署建议和文档沉淀等任务。问题不在于单个任务能不能完成，而在于多个任务或多个对话并行时，容易出现这些风险：

- 对话上下文归档了，但代码 worktree、运行进程、验证结果还在。
- 任务之间改动不同，但都落在同一个主工作区，互相污染验证结论。
- 绑定关系、README、部署说明、BUG 修复等工作混在一次会话里，后续很难追踪。
- 多个 worktree 长期存在后，状态、主线同步、是否已合并、是否可清理缺少统一判断。

这份设计把所有 code 工作统一成“工程会话”。工程会话不是聊天历史，而是一个有状态的工程任务实体。代码隔离交给 Git worktree，冲突检测交给 Git merge/rebase；系统重点管理会话状态、同步时机、checkpoint、reconcile、验证、合并和 worktree 保留/清理提醒。

## 目标

1. 所有 code 生命周期任务都有会话：新建应用、增加需求、修 BUG、部署运维、评审、文档修改、Spec 修改。
2. 所有可写任务默认创建独立 branch + worktree，主工作区保持默认分支和可运行状态。
3. 不做文件级 `touched_paths`、`risk_areas`、file lock、module lock，避免重造 Git 冲突系统。
4. 把同步时机设计成硬门禁：恢复、写入、测试、启动服务、合并、部署、归档前必须同步。
5. 用 checkpoint commit 解决长期 dirty worktree 无边界的问题。
6. 用 reconcile 解决 registry 与真实 Git worktree 不一致的问题。
7. worktree 默认不删除；已合并且 clean 的 worktree 进入提醒清理状态，是否自动删除由配置控制，默认关闭。

## 非目标

- 不在第一版实现完整 UI 看板。
- 不自动解决语义冲突；语义冲突靠主工作区总验证和人工评审暴露。
- 不从任意 dirty worktree 直接部署。
- 不把会话 registry 放进某个任务 worktree 里。
- 不替代 Git 分支、Git worktree、Git merge/rebase。

## 任务类型

工程会话支持以下类型：

| 类型 | 说明 | 默认策略 |
| --- | --- | --- |
| `new-app` | 新建完整应用、系统或复杂业务体验 | 完整 agentic-ai-user DAG，必须 worktree |
| `feature` | 增加需求或功能 | quick/standard 角色链，默认 worktree |
| `bugfix` | 修改 BUG、排查异常 | debugging + TDD + verification，默认 worktree |
| `deploy` | 部署、灰度、回滚、运维排障 | 独立 deploy 会话，只能部署 merged/default/release commit |
| `review` | 代码、方案、风险评审 | 可只读；若要改代码则转 feature/bugfix 会话 |
| `doc-change` | README、部署手册、运行说明、API 文档 | 默认 worktree，验证文档命令和路径真实性 |
| `spec-change` | 需求、架构、Superpowers Spec、Builder 投影文档 | 必须 worktree，必须 doctor/一致性检查 |

## 角色调度

所有任务先进入统一控制器：

```text
agentic-ai-user-engineering-manager
```

控制器负责：

- 判断任务类型和复杂度。
- 创建或恢复工程会话。
- 创建 branch + worktree。
- 决定角色链。
- 执行同步门禁。
- 调用 debugging、TDD、verification 等工程方法。
- 记录验证和 handoff。
- 驱动合并、部署或归档。

角色链按任务类型收敛：

| 类型 | 角色链 |
| --- | --- |
| `new-app` | PM -> 业务分析 -> 产品 -> UI -> 技术 -> 测试 -> 原型 |
| `feature` | 需求澄清/产品 -> 技术 -> 测试 -> 实现 |
| `bugfix` | 问题分诊 -> 技术根因 -> 测试回归 -> 实现 |
| `deploy` | 发布协调 -> 运维/技术 -> 验证 -> 回滚记录 |
| `review` | 技术评审 -> 测试风险 -> findings |
| `doc-change` | 文档负责人 -> 技术校验 |
| `spec-change` | PM -> 技术 -> 测试/验收 -> spec doctor |

复杂度分三档：

```text
quick: 小修、小文档、小 BUG，1-2 个角色
standard: 普通需求/普通修复，2-4 个角色
full: 新应用、大架构、大权限、大部署，完整 DAG
```

## 会话 Registry

中央 registry 放在 Agentic/Codex 全局状态目录，而不是 repo worktree 内：

```text
~/.codex/.agentic-coding/workspaces/<repo-id>/sessions/
```

每个会话一份 YAML。示例：

```yaml
id: S-002
type: feature
title: aPaaS 账号绑定
status: running
repo: apaas-builder-ai
base_branch: main
branch: session/S-002-feature-apaas-binding
worktree_path: /mnt/d/workspaces/d-ai-code/worktrees/<repo-id>/S-002-feature-apaas-binding

base_commit: abc123
head_commit: def456
merged_commit: null

git_state:
  clean: false
  ahead: 1
  behind: 0
  merged_to_base: false
  dirty_uncheckpointed: false
  stale: false

runtime_profile:
  backend_port: 8001
  frontend_port: 5174
  db_profile: shared-local
  started_from_worktree: /mnt/d/workspaces/d-ai-code/worktrees/S-002-feature-apaas-binding

roles:
  - engineering-manager
  - technical
  - test

verification:
  last_status: pending
  last_commands: []

cleanup:
  suggested: false
  auto_delete: false

last_sync_at: 2026-07-10T04:00:00+08:00
```

明确不记录：

```yaml
touched_paths
risk_areas
file_locks
module_locks
```

代码冲突由 Git 决定，registry 只记录会话与 Git 状态。

## Worktree 策略

主工作区保持默认分支，用于总验证、运行和部署前检查。

```text
/mnt/d/workspaces/d-ai-code/apaas-builder-ai
  主工作区，保持默认分支

/mnt/d/workspaces/d-ai-code/worktrees/<repo-id>/
  S-001-bugfix-code-blank
  S-002-feature-apaas-binding
  S-003-doc-readme-runbook
```

默认父目录使用稳定 `repo_id` 命名空间，避免同级多个仓库产生同名 session worktree 冲突；显式 `--worktree-parent` 保持调用方给定路径。可写任务默认创建 worktree：

```text
session/S-001-bugfix-code-blank
session/S-002-feature-apaas-binding
session/S-003-doc-readme-runbook
```

只读分析可以不创建 worktree。部署会话不能从 dirty worktree 发版，只能部署已合并的 default/release commit。

## 同步门禁

同步是这套方案的核心。以下动作前必须同步：

1. 创建会话前。
2. 恢复会话前。
3. 写文件前。
4. 运行测试前。
5. 启动服务前。
6. 切换会话前。
7. 合并前。
8. 部署前。
9. 归档前。

同步命令以 Git 为权威：

```bash
git worktree list --porcelain
git -C <worktree> status --short
git -C <worktree> rev-parse HEAD
git -C <worktree> fetch origin
git -C <worktree> rev-list --left-right --count HEAD...origin/<default>
git -C <worktree> merge-base HEAD origin/<default>
```

每次恢复会话或开始写入前，必须展示或校验：

```text
current_session
cwd
worktree_path
branch
git clean/dirty
ahead/behind
last verification
```

这样避免“以为在 S-003，实际 shell 在 S-001”的事故。

## Git 状态判定

会话同步后只判断这些状态：

| 状态 | 含义 |
| --- | --- |
| `clean` / `dirty` | worktree 是否有未提交改动 |
| `ahead` / `behind` | session branch 相对默认分支的提交差异 |
| `merged_to_base` | session branch 是否已合入默认分支 |
| `stale` | 默认分支更新后，会话未同步 |
| `very_stale` | behind 超过阈值或超过指定天数未同步 |
| `orphan_session` | worktree/branch/registry 三者无法互相对应 |
| `retained` | 已合并但 worktree 仍保留 |

恢复 `very_stale` 会话时，第一步必须同步默认分支并重新验证，不能直接继续写。

## Checkpoint 规则

Git 对 commit 边界最可靠。长期 dirty worktree 是同步最大漏洞。

离开会话、归档、合并前，如果有改动，必须二选一：

```text
1. 创建本地 checkpoint commit
2. 标记 dirty_uncheckpointed
```

推荐默认创建本地 checkpoint commit，不一定 push：

```text
checkpoint: S-002 aPaaS binding backend endpoint
checkpoint: S-002 admin UI binding dialog
```

`dirty_uncheckpointed` 允许存在，但恢复和合并时必须高亮提示。未 checkpoint 的 dirty worktree 不允许自动清理。

## Reconcile 机制

需要一个手动或周期性命令：

```text
agentic session reconcile
```

reconcile 做双向修复：

| 发现 | 处理 |
| --- | --- |
| registry 有 session，但 worktree 不存在 | 标记 `missing_worktree` |
| worktree 存在，但 registry 没记录 | 创建 `orphan_session` |
| branch 已合并，但 session 未更新 | 标记 `merged_retained` |
| worktree dirty，registry 说 clean | 更新为 dirty |
| session 长期未同步 | 标记 `stale` 或 `very_stale` |
| registry branch 与 worktree branch 不一致 | 标记 `branch_mismatch`，停止写入 |

这解决“对话归档了，但 worktree 还在、状态不同步”的问题。

## 文档任务

文档作为一等会话，不再作为顺手改动。

`doc-change` 包括：

- README。
- 本地运行方式。
- 部署手册。
- 运维 runbook。
- API 文档。

验证方式：

- README 中的命令能跑通。
- 路径和端口真实存在。
- API 文档有 curl 或测试对应。
- 部署文档包含启动、停止、回滚和环境变量检查。

`spec-change` 包括：

- 需求规格。
- 架构设计。
- Superpowers Spec。
- Builder 投影文档。

验证方式：

- 必须运行对应 doctor 或一致性检查。
- 不能绕过 Builder 投影生成规则手写生成资产。

如果文档描述某个功能，会话要依赖对应功能会话：

```yaml
depends_on:
  - S-002-feature-apaas-binding
```

避免文档先合并，功能还未合并。

## 运行资源

worktree 不隔离运行资源。runtime 只做 profile 记录和启动时检测，不做复杂锁系统：

```yaml
runtime_profile:
  backend_port: 8001
  frontend_port: 5174
  db_profile: shared-local
  env_file: .env.session
  log_path: .run/S-002/
```

启动服务前必须校验：

- 当前 cwd 是否等于会话 worktree。
- 端口是否已被其他进程占用。
- 进程是否来自当前 worktree。
- 共享数据库是否会影响验证结论。

如果发现端口冲突，换端口或停止旧进程；如果发现服务来自其他 worktree，必须停止并重启，不能继续用旧服务验证新代码。

## 合并流程

合并完全走 Git：

```text
1. sync session
2. 确认 clean 或 checkpoint
3. fetch origin
4. merge/rebase default 到 session branch
5. 解决 Git 冲突
6. worktree 内跑验证
7. 合并到 default
8. 主工作区更新并跑总验证
9. 标记 merged_commit
10. session 状态改 merged_retained
11. 提示 worktree 可关闭/清理
```

Git 冲突进入：

```text
merge_conflict
```

不提前用文件锁预测。无 Git 冲突但行为可能冲突时，靠主工作区总验证暴露。

## 部署流程

部署作为独立 `deploy` 会话。

硬规则：

- 部署源必须是 default/release/merged commit。
- 不允许部署 dirty worktree。
- 部署前必须跑总验证。
- 部署记录必须包含 release commit、环境、回滚点、健康检查结果。

部署队列按环境串行：

```yaml
deploy_queue:
  environment: staging
  current_release_session: S-010
  pending_sessions:
    - S-011
```

## Worktree 保留与清理

worktree 默认不删除。

会话状态：

```text
running
verifying
waiting_merge
merged_retained
archived_dirty
blocked_retained
abandoned_retained
missing_worktree
orphan_session
```

清理策略默认只提醒，不自动删：

```yaml
cleanup_policy:
  merged_clean:
    prompt_after_days: 1
    remind_after_days: 7
    cleanup_candidate_after_days: 30
    auto_delete: false

  dirty:
    auto_delete: false

  unmerged:
    auto_delete: false

  blocked:
    auto_delete: false
```

只有用户明确同意，或配置显式打开 `auto_delete`，才执行：

```bash
git worktree remove <path>
```

未合并、dirty、blocked 的 worktree 永不自动删除。

## 归档流程

对话归档不等于 worktree 删除。

归档前：

1. 同步 registry 与 Git。
2. 记录当前 branch/head/clean/dirty/ahead/behind。
3. 如果 dirty，要求 checkpoint 或标记 `dirty_uncheckpointed`。
4. 写 session summary。
5. 停止或释放运行进程。
6. 若已合并且 clean，标记 `merged_retained` 并提示可清理。
7. 若未合并或 dirty，保留 worktree。

## 第一版落地范围

第一版不做完整 UI，先实现协议和本地 registry。

### P0：规范文档

交付：

- 会话类型与状态。
- worktree 策略。
- 同步门禁。
- checkpoint 规则。
- reconcile 规则。
- cleanup 规则。

### P1：Session Registry

交付：

- `agentic session create`
- `agentic session resume`
- `agentic session sync`
- `agentic session archive`
- `agentic session list`
- YAML registry。

### P2：Worktree Manager

交付：

- 创建 branch + worktree。
- 检查 clean/dirty/ahead/behind/merged。
- 创建 checkpoint commit。
- 标记 `merged_retained`。
- 标记 `missing_worktree`、`orphan_session`。

### P3：Engineering Manager Skill

交付：

- feature/bugfix/doc-change 三类先接入。
- 角色链 quick/standard/full。
- 写入前同步校验。
- 验证前同步校验。

### P4：验证与合并流程

交付：

- pytest/build/curl/Playwright 结果记录。
- worktree 内验证。
- 主工作区总验证。
- merged commit 记录。

### P5：产品 UI

交付：

- 会话列表。
- 会话详情。
- worktree 状态。
- 验证记录。
- 已合并 worktree 清理提醒。

## 验收标准

1. 可写任务默认在独立 worktree 执行。
2. 恢复会话前能准确显示 worktree、branch、clean/dirty、ahead/behind。
3. registry 丢失或 worktree 孤儿时，reconcile 能发现并标记。
4. dirty worktree 离开会话前能 checkpoint 或标记 `dirty_uncheckpointed`。
5. 合并前能自动识别 stale/behind 并要求同步。
6. 合并后 worktree 不删除，状态变为 `merged_retained`，并提示清理。
7. doc-change 和 spec-change 能作为独立会话管理。
8. deploy 会话只能部署 merged/default/release commit。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| worktree 数量长期增长 | 已合并 clean worktree 定期提醒清理，默认不自动删除 |
| registry 与 Git 状态分叉 | 每次关键动作前 sync，定期 reconcile |
| dirty worktree 无边界 | 离开、归档、合并前 checkpoint 或标记 |
| agent 在错误目录执行 | 写入、测试、启动服务前校验 cwd/worktree/branch |
| 无 Git 冲突但语义冲突 | 合并后主工作区总验证作为硬门禁 |
| 文档提前合并 | doc-change 支持 depends_on，依赖功能会话合并后再合文档 |
| 部署幽灵版本 | deploy 只允许 merged/default/release commit |

## 后续决策点

1. registry 存储是否只用 YAML，还是同时提供 SQLite 索引。
2. checkpoint commit 是否默认自动创建，还是每次询问。
3. `very_stale` 阈值：按天数、commit 数，或两者结合。
4. 已合并 worktree 是否永远只提醒，还是允许配置自动删除。
5. 第一版 CLI 命令命名使用 `agentic session`，还是集成到现有 Builder/Code 后台命令体系。
