---
title: 工程会话、按需 Worktree 与同步机制设计
date: 2026-07-10
updated: 2026-07-11
status: approved
language: zh-CN
scope: Builder AI Code 多会话、工程任务与 Agent Runtime
---

# 工程会话、按需 Worktree 与同步机制设计

## 1. 背景

Builder AI 的 Code 页面当前包含两层会话：

- aPaaS Builder AI 外层 Code 应用和会话导航。
- Agent Runtime 内层真实 Code 对话、Codex Session、Timeline 和数字员工活动。

外层通过 `externalSessionRail=true`、`hideHistory=true`、`hideNewSession=true` 隐藏内层重复的历史会话和新建按钮，因此产品入口已经明确由外层 Code 会话栏负责。

现有会话仍缺少稳定的工程任务和 Git worktree 绑定。多个会话同时修改同一工程时，容易出现以下问题：

- 新增会话等待 Runtime 或工作区初始化，用户感知很慢。
- 查询、解释代码等只读对话也被迫承担 worktree 成本。
- 多个会话可能写入同一工作区，验证结论互相污染。
- 对话归档和任务完成语义混在一起，导致 worktree 被误删或长期失联。
- Runtime 重启后，Session、任务、worktree、分支和 Git `HEAD` 可能无法恢复一致。
- 对话流中的完整 Plan 卡与右上角 TODO 弹层重复展示任务状态。

本设计将“聊天会话”“工程任务”“worktree”拆成独立实体，通过按需升级、Git 同步门禁和统一执行面板解决上述问题。

## 2. 目标

1. 新增 Code 会话立即返回并显示，不同步等待 worktree 初始化。
2. 查询和只读分析不创建 worktree。
3. 明确修改、构建、测试或写文档时，当前会话自动升级为工程任务并按需创建 worktree。
4. 不同任务通过独立 worktree 并行；同一任务保持一致的执行顺序。
5. 多个会话可以显式共享同一个任务和 worktree。
6. 同步、恢复、合并和清理由 Git 事实驱动，不建立文件级锁系统。
7. 归档会话不等于完成任务，也不等于删除 worktree。
8. 前端只保留一套会话导航和一套执行状态面板。
9. Runtime 重启后能够恢复 Session、Task、Worktree 和 Git 状态。
10. Worktree 路径和收尾行为遵循 Superpowers 约定。

## 3. 非目标

- 不实现 `touched_paths`、`risk_areas`、文件锁、模块锁或业务域锁。
- 不自动解决 Git 冲突或语义冲突。
- 不在 Agent Turn 结束后自动创建 checkpoint commit。
- 不从 dirty worktree 直接部署。
- 不把日常任务入口放到 Control Plane 管理页面。
- 不为查询会话提前创建空分支或空 worktree。
- 不允许 Agent 因 worktree 异常静默回退到主工作区写入。

## 4. 核心实体

### 4.1 关系模型

```text
CodeAppShell 1 --- N AgentSession
EngineeringTask 1 --- N AgentSession
AgentSession belongs_to 0..1 EngineeringTask
EngineeringTask owns 0..1 WorktreeBinding
```

含义：

- `CodeAppShell`：aPaaS Builder AI 中的 Code 应用外壳。
- `AgentSession`：用户看到的一次 Code 对话。
- `EngineeringTask`：一次可以被多个会话继续处理的工程任务。
- `WorktreeBinding`：任务需要本地代码隔离时绑定的 Git worktree。

普通查询会话没有 `EngineeringTask`。纯远程运维任务可以有 `EngineeringTask`，但不一定有 `WorktreeBinding`。

### 4.2 AgentSession

建议字段：

```yaml
id: runtime-session-id
shell_session_id: 123
engineering_task_id: null
workspace_mode: base_readonly
workspace_path: /workspace/repository
state: waiting_input
archived_at: null
created_at: 2026-07-11T12:00:00+08:00
updated_at: 2026-07-11T12:00:00+08:00
```

`workspace_mode`：

- `base_readonly`：默认工程的只读视图。
- `task_worktree`：已绑定任务 worktree。
- `remote_only`：远程运维任务，不访问本地代码。

### 4.3 EngineeringTask

建议字段：

```yaml
id: task-20260711-001
shell_session_id: 123
title: 修复登录状态丢失
task_type: bugfix
state: active
worktree_binding_id: worktree-001
active_turn_session_id: runtime-session-a
queue_revision: 4
created_from_session_id: runtime-session-a
created_at: 2026-07-11T12:05:00+08:00
updated_at: 2026-07-11T12:10:00+08:00
```

任务类型至少包括：

- `new_app`
- `feature`
- `bugfix`
- `doc_change`
- `spec_change`
- `test_build`
- `deploy_ops`
- `review`

### 4.4 WorktreeBinding

建议字段：

```yaml
id: worktree-001
engineering_task_id: task-20260711-001
repository_id: apaas-builder-ai
branch: task/task-20260711-001-fix-login-state
path: /workspace/repository/.worktrees/task-20260711-001-fix-login-state
git_common_dir: /workspace/repository/.git
base_branch: main
base_head: abc123
current_head: def456
state: ready
created_at: 2026-07-11T12:05:02+08:00
last_verified_at: 2026-07-11T12:10:00+08:00
```

## 5. 场景与 Worktree 策略

| 场景 | 是否创建任务 | 是否创建 worktree |
| --- | --- | --- |
| 查询代码、解释逻辑、讨论方案 | 否 | 否 |
| 查看 Git 状态、只读检索 | 否 | 否 |
| 新建应用、增加功能、修改 BUG | 是 | 是 |
| 修改 README、Spec、部署文档 | 是 | 是 |
| 运行测试、构建或可能产生文件的命令 | 是 | 是 |
| 代码评审但不修改 | 可选 | 否 |
| 查询日志、查看远程环境 | 是或否 | 否 |
| 修改部署清单、脚本或配置 | 是 | 是 |
| 纯远程发布或回滚 | 是 | 否 |

## 6. 按需升级

### 6.1 默认行为

点击“新建会话”只创建 `AgentSession`，立即返回并插入左侧会话栏：

```text
POST /api/agent/sessions
-> 202 Accepted
-> session.state = waiting_input
-> workspace_mode = base_readonly
-> engineering_task_id = null
```

不会在这个请求中创建分支或 worktree。

### 6.2 自动升级触发

以下意图明确时，Runtime 自动创建任务并准备 worktree：

- 新增、修改、删除代码或文档。
- 修复 BUG。
- 新建应用。
- 运行测试、构建、格式化、代码生成等可能写入文件的命令。
- 修改部署清单、运维脚本或本地配置。

流程：

```text
用户发送消息
  -> Runtime 判断为明确写入意图
  -> 持久化 EngineeringTask
  -> 返回 task_preparing 状态
  -> 后台创建 WorktreeBinding
  -> 启动或切换 Codex Thread 到 worktree cwd
  -> 执行首条消息
```

首条消息在 worktree 未就绪时进入任务队列，不丢失，也不要求用户重复发送。

### 6.3 不明确意图

当用户表达既可能是分析，也可能要求修改时，询问一次：

```text
仅分析当前实现，还是进入工程任务并修改？
```

明确的修改请求不重复询问。

### 6.4 首次写入保护

如果前置判断为只读，但 Agent 后续尝试写文件或执行写能力命令，Runtime 必须在实际写入前：

1. 暂停当前 Turn。
2. 创建或绑定工程任务。
3. 创建 worktree。
4. 将 Session 的 workspace 重新绑定到 worktree。
5. 恢复 Turn。

禁止写入主工作区后再补建 worktree。

## 7. 会话创建模式

前端和 API 支持三种显式模式：

### 7.1 `new_conversation`

- 新建普通查询会话。
- 不创建任务。
- 不创建 worktree。
- 是应用分组 `+` 的默认行为。

### 7.2 `continue_task`

- 新建一个 AgentSession。
- 绑定已有 EngineeringTask。
- 复用已有 worktree。
- 多个会话共享任务，但遵守同一任务的执行协调。

### 7.3 `fork_task`

- 从已有任务的最后提交 `HEAD` 创建新任务和新 worktree。
- 不复制未提交修改。
- 如果源任务 dirty，必须明确提示未提交修改不会进入派生任务。

## 8. Worktree 约定

使用 Superpowers 默认目录：

```text
<repo>/.worktrees/<task-id>-<slug>
```

要求：

- `<repo>/.worktrees/` 必须在 `.gitignore` 中。
- 分支名包含稳定任务 ID，避免仅依赖易变标题。
- Agent Runtime 持久化绝对路径，但 UI 默认只显示分支名和 worktree 短名称。
- 主工作区保持默认分支，不切换到任务分支。
- Agent Turn 的写权限只覆盖当前任务 worktree、Git common-dir 和 Session Runtime 临时目录。
- 主工作区和其他 worktree 不进入本次 Turn 的写权限范围。

## 9. 并发模型

### 9.1 可以并行

- 普通查询会话之间。
- 不同 EngineeringTask 之间。
- 不同 worktree 之间。

### 9.2 同一任务

同一 EngineeringTask 同时只允许一个活跃 Agent Turn，包括读写 Turn，避免读取到修改一半的工作区。

第二个会话发送消息时提供：

- 排队执行。
- 派生新任务。
- 取消发送。

队列项记录：

```yaml
id: queue-item-id
session_id: runtime-session-b
expected_head: def456
message_ref: message-id
state: queued
```

轮到执行时，如果 `expected_head` 和当前任务 `HEAD` 不一致，队列项进入 `needs_confirmation`，要求刷新上下文后继续。

### 9.3 不建立文件锁

系统不记录：

```yaml
touched_paths
risk_areas
file_locks
module_locks
runtime_locks
```

代码冲突由 Git merge/rebase 判断。运行端口冲突由启动命令即时检查，不进入持久化锁模型。

## 10. 同步时机

同步只在明确时机执行，避免后台持续修改任务分支：

1. 会话升级为任务前。
2. 打开或恢复任务时。
3. Agent Turn 开始前。
4. 排队消息执行前。
5. Agent Turn 结束后刷新状态。
6. 完成任务前。
7. 合并、创建 PR 或恢复异常任务前。
8. Runtime 启动 reconcile 时。

同步规则：

- `git fetch` 获取远端事实。
- 只允许安全快进。
- 不自动 rebase、merge 或解决冲突。
- 不自动创建 checkpoint commit。
- Turn 结束后只刷新 `HEAD`、clean/dirty、ahead/behind 和 merged 状态。
- 分叉、冲突或 dirty 状态不符合动作前置条件时停止操作。

## 11. Runtime 组件边界

### 11.1 `EngineeringTaskService`

- 创建普通会话。
- 判断或接收任务升级意图。
- 创建、继续、派生和完成任务。

### 11.2 `EngineeringTaskStore`

- 持久化 Session、Task、WorktreeBinding 和队列。
- 提供 revision/CAS，避免并发覆盖。
- 保证 Agent Runtime 是任务状态的唯一写入者。

### 11.3 `TaskWorktreeManager`

- 创建和校验 worktree。
- 读取 Git 状态。
- 识别 worktree 缺失、分支不匹配和 Git common-dir 不匹配。
- 执行经过确认的清理。

### 11.4 `TaskExecutionCoordinator`

- 维护任务级活跃 Turn。
- 管理排队、取消和派生。
- 校验 `expectedHead`。

### 11.5 `TaskGitSynchronizer`

- fetch 和安全快进。
- 刷新 ahead/behind、clean/dirty、merged。
- 拒绝静默冲突处理。

### 11.6 `TaskLifecycleGateway`

- 在 Agent Turn 外执行 merge、PR、keep、discard。
- 完成前校验共享 Session、活跃 Turn、dirty 和 merged 状态。
- 避免 Agent 在对话中自行删除当前 cwd。

## 12. aPaaS Builder 与 Runtime 所有权

### 12.1 aPaaS Builder AI

负责：

- Code 应用外壳。
- 外层左侧会话栏。
- 调用 Agent Runtime Session/Task API。
- 展示任务状态投影。
- 将 Session 切换和用户操作代理到 Runtime。

不负责：

- 直接创建 Git worktree。
- 直接修改 Runtime 任务状态。
- 自己维护第二套任务 registry。

### 12.2 Agent Runtime

负责：

- AgentSession、EngineeringTask、WorktreeBinding 的真实状态。
- Codex Thread cwd 和写权限。
- 并发协调、同步、恢复和任务收尾。
- 任务、数字员工和 Trace 的统一数据源。

### 12.3 Control Plane

负责沙箱和部署级运维能力，不作为日常会话、任务和 worktree 的主要产品入口。

## 13. 前端设计

### 13.1 页面归属

主要改造位置：

- `apaas-builder-ai/frontend/src/components/v2/RailSidebar.vue`
- `apaas-builder-ai/frontend/src/views/CodeConversationPage.vue`
- `agent-runtime/web/builder/src/components/chat/ChatPane.tsx`

内嵌 Runtime 保持：

```text
externalSessionRail = true
hideHistory = true
hideNewSession = true
```

不在 iframe 内重复增加完整会话历史。

### 13.2 左侧会话栏

应用分组 `+`：

- 默认立即创建普通会话。
- 不等待任务或 worktree。

会话行按状态显示：

- 等待输入。
- 准备工作区。
- 执行中。
- 排队中。
- 上下文已变化。
- 等待合并。
- 已合并。
- 工作区异常。

只有绑定 EngineeringTask 的会话才显示 Git 和任务状态。

会话菜单：

- 继续此任务。
- 派生新任务。
- 完成任务。
- 归档会话。

普通查询会话只显示归档；在明确要求修改时原地升级。

多个会话共享任务时显示：

```text
共享任务 · N 个会话
```

### 13.3 对话区

对话头部只显示当前上下文：

- 普通会话不显示 branch/worktree。
- 任务会话显示任务名、分支和同步状态。
- 并发、准备、`HEAD` 变化等提示显示在输入框上方。

对话流不再展示完整 Plan 卡，只保留一条进度摘要：

```text
计划执行中 · 2/4 · 正在派发专业设计角色 · 查看任务
```

点击摘要打开统一执行面板的“任务”Tab。

### 13.4 统一执行面板

右上角只保留一个“执行活动”入口，使用一个面板和三个 Tab：

#### 任务

- 当前工程任务。
- 是否已创建 worktree。
- branch、同步状态、当前 `HEAD` 摘要。
- 活跃会话和排队数量。
- 执行计划步骤。
- 完成任务入口。

#### 数字员工

- 角色名称。
- waiting/running/completed/blocked 状态。
- 当前工作摘要。
- 打开数字员工详细 Timeline。

#### Trace

- 工具调用。
- 技能调用。
- Runtime 状态变更。
- 原始错误代码和诊断信息。

面板在桌面端作为 Code 工作区内的右侧停靠面板，打开时收缩对话区域，不覆盖内容。窄屏使用全宽 Drawer。

移除：

- 对话右侧重复的完整 Plan 卡。
- 活动弹层中任务和数字员工的纵向混排。
- 两套独立任务完成状态。

## 14. 归档

归档只作用于 AgentSession：

1. 中断该 Session 的活跃 Turn。
2. 将 Session 标记为 archived。
3. 不提交、不合并、不删除 worktree。
4. 不自动完成 EngineeringTask。

如果归档的是任务的最后一个可见 Session：

- EngineeringTask 保持 active/retained。
- 任务出现在应用的“继续任务”列表。
- 用户可以创建新会话重新绑定任务。

## 15. 完成任务

完成任务提供四种结果：

### 15.1 本地合并

- 同步并验证。
- 合并到默认分支。
- 按 Superpowers 默认执行 cleanup，但必须先满足 Runtime 安全前置条件。

安全前置条件：

- 没有活跃 Agent Turn。
- 没有待执行队列。
- 没有其他 Session 正在使用该 cwd。
- worktree clean。
- 分支已经合并。

前置条件不满足时保留 worktree并提示处理。

### 15.2 创建 PR

- 创建或记录 PR。
- 保留分支和 worktree。

### 15.3 保留任务

- 保留任务、分支和 worktree。
- 状态进入 retained。

### 15.4 放弃任务

- 要求输入任务名确认。
- 检查 active turn、dirty 和未提交修改。
- 确认后删除 worktree和任务分支。

未合并、dirty、blocked 的 worktree 不进入自动清理。

已合并且 clean 的保留 worktree可以进入定期清理候选。

## 16. 恢复与 Reconcile

Runtime 启动和任务打开时执行 reconcile。

每个 worktree 根目录写入：

```text
.agentic/task-worktree.yaml
```

只记录非敏感身份信息：

```yaml
engineering_task_id: task-20260711-001
repository_id: apaas-builder-ai
branch: task/task-20260711-001-fix-login-state
created_at: 2026-07-11T12:05:02+08:00
```

恢复矩阵：

| Store | Worktree | Git 状态 | 处理 |
| --- | --- | --- | --- |
| 有 | 有 | 匹配 | 恢复 ready |
| 有 | 无 | - | `WORKTREE_MISSING` |
| 无 | 有 | 元数据完整 | 提示恢复绑定 |
| 有 | 有 | branch 不匹配 | `WORKTREE_BINDING_MISMATCH` |
| 有 | 有 | common-dir 不匹配 | 停止执行 |
| 有 | 有 | `HEAD` 变化 | 刷新或要求确认 |

任何恢复失败都不能回退到主工作区写入。

## 17. 错误码

| 错误码 | 含义 | 用户动作 |
| --- | --- | --- |
| `TASK_BUSY` | 同一任务已有活跃 Turn | 排队、派生或取消 |
| `TASK_HEAD_CHANGED` | 入队后任务 `HEAD` 已变化 | 刷新上下文后继续 |
| `WORKTREE_INIT_FAILED` | worktree 创建失败 | 重试、仅分析、绑定已有任务 |
| `WORKTREE_MISSING` | 持久化目录不存在 | 重建或重新绑定 |
| `WORKTREE_BINDING_MISMATCH` | branch/path/common-dir 不匹配 | 停止并恢复 |
| `TASK_FINISH_BLOCKED` | 任务不满足收尾条件 | 处理 active/dirty/queue |
| `TASK_WRITE_REQUIRES_WORKTREE` | 查询会话准备写入 | 自动升级或等待确认 |

任务 Tab 显示可理解的处理建议；Trace Tab 保留原始错误码和诊断。

## 18. API 方向

建议接口：

```text
POST   /api/agent/sessions
POST   /api/agent/sessions/{sessionId}/upgrade-task
POST   /api/engineering-tasks/{taskId}/sessions
POST   /api/engineering-tasks/{taskId}/fork
GET    /api/engineering-tasks/{taskId}
GET    /api/engineering-tasks/{taskId}/activity
POST   /api/engineering-tasks/{taskId}/queue
DELETE /api/engineering-tasks/{taskId}/queue/{queueItemId}
POST   /api/engineering-tasks/{taskId}/finish
POST   /api/engineering-tasks/{taskId}/reconcile
```

aPaaS Builder 通过现有 Code Runtime Proxy 转发，不直接访问 Runtime 持久化目录。

所有修改 Task/Worktree 状态的请求携带 revision，使用 CAS 防止重复点击和并发覆盖。

## 19. 迁移

现有 Agent Runtime Session 迁移规则：

- 保持原 Session ID 和对话历史。
- 默认 `engineering_task_id = null`。
- 默认 `workspace_mode = base_readonly`。
- 如果现有 Session 已有明确独立 workspace 映射，可以由 reconcile 建议绑定任务，不自动修改。
- 首次明确写入时按新流程升级。

现有 aPaaS `CodeRuntimeAgentSession` 映射继续保留，新增 `engineering_task_id` 和任务状态投影字段。

## 20. 实施阶段

### Phase 1：Runtime 基础

- 可选任务和 worktree 绑定。
- 按需升级。
- Worktree Manager。
- Task Execution Coordinator。
- 持久化、revision 和 reconcile。

### Phase 2：Builder AI 前端

- 左栏任务状态和菜单。
- 普通会话即时创建。
- 统一执行活动三 Tab。
- Plan 摘要入口。
- 并发和 `HEAD` 变化交互。

### Phase 3：任务收尾

- merge、PR、keep、discard。
- 清理安全前置条件。
- 已合并 worktree 清理提醒。
- 异常恢复入口。

## 21. 测试

### 21.1 Runtime 单元测试

- 普通会话不创建任务和 worktree。
- 明确写入意图创建任务。
- 不明确意图等待确认。
- 首次写入保护不会写入主工作区。
- revision/CAS 拒绝旧写入。
- 同一任务只允许一个活跃 Turn。
- `expectedHead` 变化进入确认。

### 21.2 Git 集成测试

- 创建、继续和派生真实 worktree。
- dirty 源任务派生不复制未提交修改。
- ahead/behind/merged 判定。
- worktree missing、branch mismatch、common-dir mismatch。
- merge cleanup 安全前置条件。
- PR/keep 保留 worktree。
- discard 需要确认。

### 21.3 前端测试

- 普通会话即时插入左栏。
- 任务升级状态切换。
- 只有任务会话显示 Git 状态。
- 继续任务、派生任务、完成任务菜单。
- 任务、数字员工、Trace 三 Tab。
- Plan 摘要点击打开任务 Tab。
- 移除重复 Plan/TODO。
- 桌面停靠面板和窄屏 Drawer。

### 21.4 端到端测试

- 查询会话全程不创建 worktree。
- 查询会话后续修改时原地升级。
- 新增会话期间立即输入首条消息。
- 不同任务并行执行。
- 同一任务排队和派生。
- Runtime 重启后恢复任务。
- 归档最后一个会话后仍可继续任务。
- 合并、PR、保留和放弃完整流程。

## 22. 验收标准

1. 新增普通会话在持久化后立即显示，不等待 Runtime 工作区初始化。
2. 查询、解释和只读分析不会创建 worktree。
3. 明确修改请求在实际写入前自动创建任务和 worktree。
4. Agent 永远不能因任务绑定失败而写入主工作区。
5. 不同任务可以并行，同一任务正确串行。
6. 多个会话可以共享任务和 worktree。
7. 归档会话不会完成任务或删除 worktree。
8. Runtime 重启后能够恢复 Session、Task、Worktree 和 Git 状态。
9. 同步只执行 fetch 和安全快进，不自动 merge/rebase/checkpoint。
10. 冲突完全交给 Git，不引入文件锁。
11. 前端只保留一个会话导航和一个执行活动面板。
12. 任务、数字员工、Trace 使用三个 Tab 展示。
13. 对话流只显示 Plan 摘要，不再出现重复 TODO/Plan。
14. 合并、PR、保留、放弃遵循 Superpowers 和 Runtime 安全前置条件。
15. 未合并或 dirty worktree 不会被自动清理。

## 23. 已确认决策

- 采用方案 B：外层左栏管理会话，对话区展示当前上下文。
- 使用一个统一执行活动面板。
- 面板分为“任务 / 数字员工 / Trace”三个 Tab。
- 普通查询会话不创建 worktree。
- 明确写入请求自动升级，语义不明确时询问。
- 同一任务串行，不同任务并行。
- 不做文件锁。
- 不自动 checkpoint。
- 归档不删除 worktree。
- 合并和清理遵循 Superpowers 默认流程，并增加 Runtime 共享任务安全检查。
