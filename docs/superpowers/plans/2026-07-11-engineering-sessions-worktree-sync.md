# Engineering Sessions Worktree Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Code 普通会话即时创建且默认只读，在明确修改时按需升级为工程任务并绑定 Superpowers 默认 worktree，同时提供任务级串行执行、Git 同步、恢复、收尾和统一执行活动界面。

**Architecture:** Agent Runtime 是 `AgentSession`、`EngineeringTask`、`WorktreeBinding`、任务队列和 Git 生命周期的唯一写入者；aPaaS Builder 只维护外层 Code 应用与 Runtime Session 归属，并通过现有 Runtime Proxy 转发任务 API 和展示任务投影。普通会话使用 `base_readonly`，首次消息前不创建 Codex Thread；写入意图先准备任务 worktree，再以该路径创建或恢复 Thread。相同任务通过 CAS 和单活跃 Turn 协调，不同任务依赖 Git worktree 隔离并行。

**Tech Stack:** Go 1.x、Codex App Server JSON-RPC、Git CLI、React + TypeScript + Vitest、Python 3.11 + FastAPI + SQLAlchemy + pytest、Vue 3 + TypeScript + Vitest。

---

## 实施工作区

本功能跨两个仓库，提交必须分别完成，不能把一个仓库的改动混入另一个仓库。

- aPaaS Builder 工作区：`/mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync`
- aPaaS Builder 分支：`session/S-001-engineering-sessions-worktree-sync`
- Agent Runtime 主工作区：`/mnt/d/workspaces/d-ai-code/agent-runtime`
- Agent Runtime 实施 worktree：`/mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync`
- Agent Runtime 实施分支：`task/engineering-sessions-worktree-sync`

Agent Runtime 主工作区当前存在用户改动。实施者必须先使用 `superpowers:using-git-worktrees` 创建上述 worktree，不能在主工作区直接编辑，也不能清理或还原现有脏文件。

### Task 1: 建立 Agent Runtime 独立实施 worktree 和基线

**Files:**
- Verify: `/mnt/d/workspaces/d-ai-code/agent-runtime/.gitignore`
- Create: `/mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync`

- [ ] **Step 1: 确认主工作区仍在默认分支且保留现有改动**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime
git status --short --branch
git symbolic-ref refs/remotes/origin/HEAD
```

Expected: 当前分支是 `main`，`origin/HEAD` 指向 `origin/main`，现有修改仍然存在。

- [ ] **Step 2: 确认 Superpowers 默认目录已被忽略**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime
git check-ignore -q .worktrees
```

Expected: exit code `0`。

- [ ] **Step 3: 创建隔离 worktree**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime
git fetch origin
git worktree add .worktrees/task-engineering-sessions-worktree-sync -b task/engineering-sessions-worktree-sync origin/main
```

Expected: 新 worktree 位于 `.worktrees/task-engineering-sessions-worktree-sync`，主工作区仍在 `main`。

- [ ] **Step 4: 跑两仓目标测试基线**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync
go test ./internal/application ./internal/adapters/builder ./internal/adapters/git ./internal/http
cd web/builder
npm test -- --runInBand
```

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync/backend
pytest -q tests/test_code_runtime_routes.py tests/test_engineering_sessions_models.py tests/test_engineering_sessions_service.py
cd ../frontend
npm test -- --run src/composables/railSessions.spec.ts src/components/v2/RailSidebar.spec.ts src/views/CodeConversationPage.spec.ts
```

Expected: 记录现有基线；任何既有失败单独记录，不能通过修改无关代码掩盖。

### Task 2: 定义 Session、Task、Worktree 和队列领域契约

**Files:**
- Create: `agent-runtime/internal/domain/engineering_task.go`
- Create: `agent-runtime/internal/domain/engineering_task_test.go`
- Modify: `agent-runtime/internal/domain/agent_session.go`
- Modify: `agent-runtime/internal/domain/contracts.go`
- Modify: `agent-runtime/internal/domain/contracts_test.go`

- [ ] **Step 1: 先写领域状态和兼容迁移测试**

在 `internal/domain/engineering_task_test.go` 增加覆盖：

```go
func TestNormalizeAgentSessionWorkspaceDefaultsToBaseReadonly(t *testing.T) {
	mapping := NormalizeAgentSessionWorkspace(AgentSessionMapping{
		RuntimeSessionID: "runtime-1",
		WorkspacePath:    "/workspace/repo",
	})
	if mapping.WorkspaceMode != AgentWorkspaceModeBaseReadonly {
		t.Fatalf("WorkspaceMode = %q", mapping.WorkspaceMode)
	}
	if mapping.EngineeringTaskID != "" {
		t.Fatalf("EngineeringTaskID = %q", mapping.EngineeringTaskID)
	}
}

func TestEngineeringTaskRegistryRejectsStaleRevision(t *testing.T) {
	registry := EngineeringTaskRegistry{SchemaVersion: EngineeringTaskRegistrySchemaVersion, Revision: 4}
	if err := registry.RequireRevision(3); !errors.Is(err, ErrEngineeringTaskRevisionConflict) {
		t.Fatalf("RequireRevision() error = %v", err)
	}
}

func TestTaskQueueItemRequiresExpectedHead(t *testing.T) {
	item := TaskQueueItem{ID: "queue-1", SessionID: "runtime-2", State: TaskQueueQueued}
	if err := item.Validate(); err == nil {
		t.Fatal("Validate() error = nil")
	}
}
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync
go test ./internal/domain -run 'TestNormalizeAgentSessionWorkspaceDefaultsToBaseReadonly|TestEngineeringTaskRegistryRejectsStaleRevision|TestTaskQueueItemRequiresExpectedHead'
```

Expected: FAIL，缺少工程任务领域类型和规范化函数。

- [ ] **Step 3: 添加完整领域类型**

在 `internal/domain/engineering_task.go` 定义：

```go
package domain

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

const EngineeringTaskRegistrySchemaVersion = "engineering-task-registry/v1"

var ErrEngineeringTaskRevisionConflict = errors.New("engineering task revision conflict")

type AgentWorkspaceMode string

const (
	AgentWorkspaceModeBaseReadonly AgentWorkspaceMode = "base_readonly"
	AgentWorkspaceModeTaskWorktree AgentWorkspaceMode = "task_worktree"
	AgentWorkspaceModeRemoteOnly   AgentWorkspaceMode = "remote_only"
)

type EngineeringTaskType string

const (
	EngineeringTaskNewApp    EngineeringTaskType = "new_app"
	EngineeringTaskFeature   EngineeringTaskType = "feature"
	EngineeringTaskBugfix    EngineeringTaskType = "bugfix"
	EngineeringTaskDocChange EngineeringTaskType = "doc_change"
	EngineeringTaskSpecChange EngineeringTaskType = "spec_change"
	EngineeringTaskTestBuild EngineeringTaskType = "test_build"
	EngineeringTaskDeployOps EngineeringTaskType = "deploy_ops"
	EngineeringTaskReview    EngineeringTaskType = "review"
)

type EngineeringTaskState string

const (
	EngineeringTaskPreparing    EngineeringTaskState = "preparing"
	EngineeringTaskActive       EngineeringTaskState = "active"
	EngineeringTaskWaitingMerge EngineeringTaskState = "waiting_merge"
	EngineeringTaskRetained     EngineeringTaskState = "retained"
	EngineeringTaskMerged       EngineeringTaskState = "merged"
	EngineeringTaskDiscarded    EngineeringTaskState = "discarded"
	EngineeringTaskBlocked      EngineeringTaskState = "blocked"
)

type WorktreeBindingState string

const (
	WorktreeBindingPreparing WorktreeBindingState = "preparing"
	WorktreeBindingReady     WorktreeBindingState = "ready"
	WorktreeBindingMissing   WorktreeBindingState = "missing"
	WorktreeBindingMismatch  WorktreeBindingState = "mismatch"
	WorktreeBindingRetained  WorktreeBindingState = "retained"
	WorktreeBindingRemoved   WorktreeBindingState = "removed"
)

type WorktreeBinding struct {
	ID                string               `json:"id"`
	EngineeringTaskID string               `json:"engineeringTaskId"`
	RepositoryID      string               `json:"repositoryId"`
	Branch            string               `json:"branch"`
	Path              string               `json:"path"`
	GitCommonDir      string               `json:"gitCommonDir"`
	BaseBranch        string               `json:"baseBranch"`
	BaseHead          string               `json:"baseHead"`
	CurrentHead       string               `json:"currentHead"`
	Clean             bool                 `json:"clean"`
	Ahead             int                  `json:"ahead"`
	Behind            int                  `json:"behind"`
	MergedToBase      bool                 `json:"mergedToBase"`
	State             WorktreeBindingState `json:"state"`
	CreatedAt         time.Time            `json:"createdAt"`
	LastVerifiedAt    time.Time            `json:"lastVerifiedAt"`
}

type EngineeringTask struct {
	ID                   string               `json:"id"`
	Title                string               `json:"title"`
	TaskType             EngineeringTaskType  `json:"taskType"`
	State                EngineeringTaskState `json:"state"`
	WorktreeBindingID    string               `json:"worktreeBindingId,omitempty"`
	ActiveTurnSessionID  string               `json:"activeTurnSessionId,omitempty"`
	QueueRevision        int64                `json:"queueRevision"`
	CreatedFromSessionID string               `json:"createdFromSessionId"`
	SessionIDs           []string             `json:"sessionIds"`
	CreatedAt            time.Time            `json:"createdAt"`
	UpdatedAt            time.Time            `json:"updatedAt"`
}

type TaskQueueState string

const (
	TaskQueueQueued            TaskQueueState = "queued"
	TaskQueueNeedsConfirmation TaskQueueState = "needs_confirmation"
	TaskQueueRunning           TaskQueueState = "running"
	TaskQueueCancelled         TaskQueueState = "cancelled"
	TaskQueueCompleted         TaskQueueState = "completed"
)

type TaskQueueItem struct {
	ID              string         `json:"id"`
	EngineeringTaskID string       `json:"engineeringTaskId"`
	SessionID       string         `json:"sessionId"`
	ClientMessageID string         `json:"clientMessageId"`
	ExpectedHead    string         `json:"expectedHead"`
	Request         ChatRequest    `json:"request"`
	State           TaskQueueState `json:"state"`
	CreatedAt       time.Time      `json:"createdAt"`
	UpdatedAt       time.Time      `json:"updatedAt"`
}

func (item TaskQueueItem) Validate() error {
	if strings.TrimSpace(item.ID) == "" || strings.TrimSpace(item.SessionID) == "" {
		return fmt.Errorf("queue item id and session id are required")
	}
	if strings.TrimSpace(item.ExpectedHead) == "" {
		return fmt.Errorf("queue item expected head is required")
	}
	return nil
}

type SessionTurnEnvelopeState string

const (
	SessionTurnPending    SessionTurnEnvelopeState = "pending"
	SessionTurnRunning    SessionTurnEnvelopeState = "running"
	SessionTurnSuperseded SessionTurnEnvelopeState = "superseded"
	SessionTurnCompleted  SessionTurnEnvelopeState = "completed"
	SessionTurnFailed     SessionTurnEnvelopeState = "failed"
)

type SessionTurnEnvelope struct {
	RuntimeSessionID string                   `json:"runtimeSessionId"`
	ClientMessageID  string                   `json:"clientMessageId"`
	Request          ChatRequest              `json:"request"`
	State            SessionTurnEnvelopeState `json:"state"`
	ReplayCount      int                      `json:"replayCount"`
	CreatedAt        time.Time                `json:"createdAt"`
	UpdatedAt        time.Time                `json:"updatedAt"`
}

type EngineeringTaskRegistry struct {
	SchemaVersion string               `json:"schemaVersion"`
	Revision      int64                `json:"revision"`
	Tasks         []EngineeringTask    `json:"tasks"`
	Worktrees     []WorktreeBinding    `json:"worktrees"`
	Queue         []TaskQueueItem      `json:"queue"`
	PendingTurns  []SessionTurnEnvelope `json:"pendingTurns"`
	UpdatedAt     time.Time            `json:"updatedAt"`
}

func (registry EngineeringTaskRegistry) RequireRevision(expected int64) error {
	if expected != registry.Revision {
		return fmt.Errorf("%w: expected %d current %d", ErrEngineeringTaskRevisionConflict, expected, registry.Revision)
	}
	return nil
}

func NormalizeAgentSessionWorkspace(mapping AgentSessionMapping) AgentSessionMapping {
	if mapping.WorkspaceMode == "" {
		mapping.WorkspaceMode = AgentWorkspaceModeBaseReadonly
	}
	return mapping
}
```

在 `AgentSessionMapping` 增加：

```go
EngineeringTaskID string             `json:"engineeringTaskId,omitempty"`
WorkspaceMode     AgentWorkspaceMode `json:"workspaceMode"`
TaskState         EngineeringTaskState `json:"taskState,omitempty"`
TaskRevision      int64              `json:"taskRevision,omitempty"`
```

`AgentSessionMapping` 继续复用现有 `WorkspacePath` 字段。在 `AgentSessionRecord` 增加同样四个字段，并新增：

```go
WorkspacePath string `json:"workspacePath,omitempty"`
```

`AgentSessionIndex` schema 升级到 `agent-session-index/v2`，加载 v1 时调用 `NormalizeAgentSessionWorkspace`。

- [ ] **Step 4: 增加工程任务事件和错误码**

在 `internal/domain/contracts.go` 增加：

```go
const (
	BuilderEventEngineeringTaskStatus BuilderEventType = "engineering.task.status"
	BuilderEventEngineeringTaskQueue  BuilderEventType = "engineering.task.queue"
	BuilderEventWorkspaceEscalation   BuilderEventType = "agent.workspace.escalation_required"
)
```

并新增公共错误码常量：

```go
const (
	EngineeringTaskErrorBusy            = "TASK_BUSY"
	EngineeringTaskErrorHeadChanged     = "TASK_HEAD_CHANGED"
	EngineeringTaskErrorWorktreeInit    = "WORKTREE_INIT_FAILED"
	EngineeringTaskErrorWorktreeMissing = "WORKTREE_MISSING"
	EngineeringTaskErrorBindingMismatch = "WORKTREE_BINDING_MISMATCH"
	EngineeringTaskErrorFinishBlocked   = "TASK_FINISH_BLOCKED"
	EngineeringTaskErrorWriteRequiresWorktree = "TASK_WRITE_REQUIRES_WORKTREE"
)
```

- [ ] **Step 5: 运行领域测试**

Run:

```bash
go test ./internal/domain
```

Expected: PASS。

- [ ] **Step 6: 提交 Agent Runtime 领域契约**

Run:

```bash
git add internal/domain/engineering_task.go internal/domain/engineering_task_test.go internal/domain/agent_session.go internal/domain/contracts.go internal/domain/contracts_test.go
git commit -m "feat(runtime): define engineering task contracts"
```

### Task 3: 实现任务 Registry 的原子持久化和 CAS

**Files:**
- Modify: `agent-runtime/internal/ports/ports.go`
- Create: `agent-runtime/internal/adapters/builder/file_engineering_task_store.go`
- Create: `agent-runtime/internal/adapters/builder/file_engineering_task_store_test.go`

- [ ] **Step 1: 写 CAS、损坏备份和并发测试**

测试必须覆盖：

```go
func TestFileEngineeringTaskStoreRejectsStaleRevision(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	store := NewFileEngineeringTaskStore()
	first := domain.EngineeringTaskRegistry{
		SchemaVersion: domain.EngineeringTaskRegistrySchemaVersion,
		Revision:      1,
		Tasks:         []domain.EngineeringTask{},
		Worktrees:     []domain.WorktreeBinding{},
		Queue:         []domain.TaskQueueItem{},
		PendingTurns:  []domain.SessionTurnEnvelope{},
	}
	if err := store.Save(ctx, root, first, 0); err != nil {
		t.Fatal(err)
	}
	first.Revision = 2
	if err := store.Save(ctx, root, first, 0); !errors.Is(err, domain.ErrEngineeringTaskRevisionConflict) {
		t.Fatalf("Save() error = %v", err)
	}
}
```

另加：

- 空文件不存在时返回空 registry 和 `found=false`。
- JSON 损坏时重命名为 `.corrupt.<timestamp>`。
- 两个 goroutine 使用相同 revision 时只有一个成功。
- `Tasks`、`Worktrees`、`Queue`、`PendingTurns` 加载后永不为 `nil`。

- [ ] **Step 2: 确认测试失败**

Run:

```bash
go test ./internal/adapters/builder -run FileEngineeringTaskStore
```

Expected: FAIL，store 尚未实现。

- [ ] **Step 3: 增加端口**

在 `internal/ports/ports.go` 增加：

```go
type EngineeringTaskStore interface {
	Load(ctx context.Context, statePath string) (domain.EngineeringTaskRegistry, bool, error)
	Save(ctx context.Context, statePath string, registry domain.EngineeringTaskRegistry, expectedRevision int64) error
}
```

- [ ] **Step 4: 实现文件 Store**

文件固定为：

```text
<statePath>/.apaas/builder/engineering-tasks/index.json
```

`Save` 的关键顺序：

```go
func (s FileEngineeringTaskStore) Save(
	ctx context.Context,
	statePath string,
	registry domain.EngineeringTaskRegistry,
	expectedRevision int64,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	current, found, err := s.Load(ctx, statePath)
	if err != nil {
		return err
	}
	currentRevision := int64(0)
	if found {
		currentRevision = current.Revision
	}
	if currentRevision != expectedRevision {
		return fmt.Errorf("%w: expected %d current %d", domain.ErrEngineeringTaskRevisionConflict, expectedRevision, currentRevision)
	}
	registry.SchemaVersion = domain.EngineeringTaskRegistrySchemaVersion
	registry.Revision = expectedRevision + 1
	registry.UpdatedAt = time.Now().UTC()
	body, err := json.MarshalIndent(registry, "", "  ")
	if err != nil {
		return err
	}
	return atomicWriteFile(engineeringTaskRegistryPath(statePath), append(body, '\n'), 0o600)
}
```

进程内使用按绝对路径分组的 `sync.Mutex` 保护 Load-compare-Save；跨进程只允许 Runtime 单写入者，不增加业务文件锁模型。

- [ ] **Step 5: 运行 Store 测试**

Run:

```bash
go test ./internal/adapters/builder -run FileEngineeringTaskStore
```

Expected: PASS。

- [ ] **Step 6: 提交持久化层**

Run:

```bash
git add internal/ports/ports.go internal/adapters/builder/file_engineering_task_store.go internal/adapters/builder/file_engineering_task_store_test.go
git commit -m "feat(runtime): persist engineering tasks with cas"
```

### Task 4: 实现 Superpowers Worktree Manager 和 Git 同步

**Files:**
- Modify: `agent-runtime/internal/ports/ports.go`
- Create: `agent-runtime/internal/adapters/git/task_worktree_manager.go`
- Create: `agent-runtime/internal/adapters/git/task_worktree_manager_test.go`
- Reuse: `agent-runtime/internal/adapters/git/code_projection_repository.go`

- [ ] **Step 1: 写真实 Git 仓库集成测试**

测试使用 `t.TempDir()` 初始化 bare origin、control worktree 和任务 worktree，覆盖：

- 路径必须是 `<repo>/.worktrees/<task-id>-<slug>`。
- control worktree 始终停留在默认分支。
- branch 为 `task/<task-id>-<slug>`。
- `.agentic/task-worktree.yaml` 写入任务 ID、repository ID、branch、created_at。
- `Inspect` 检出 missing、branch mismatch、common-dir mismatch。
- `SyncFastForward` 只允许 clean 且未分叉时快进。
- dirty 源任务 fork 只从已提交 `HEAD` 创建，不复制未提交文件。
- merge、keep、discard 的安全条件。

核心断言：

```go
if got := filepath.Dir(binding.Path); got != filepath.Join(repo, ".worktrees") {
	t.Fatalf("worktree parent = %q", got)
}
if branch := gitOutput(t, repo, "branch", "--show-current"); branch != "main" {
	t.Fatalf("control branch = %q", branch)
}
```

- [ ] **Step 2: 确认测试失败**

Run:

```bash
go test ./internal/adapters/git -run TaskWorktree
```

Expected: FAIL，缺少 manager。

- [ ] **Step 3: 定义 Git 生命周期端口**

在 `internal/ports/ports.go` 增加：

```go
type TaskWorktreeCreateRequest struct {
	TaskID         string
	Title          string
	RepositoryID   string
	RepoPath       string
	BaseBranch     string
	SourceHead     string
}

type TaskWorktreeManager interface {
	Create(ctx context.Context, request TaskWorktreeCreateRequest) (domain.WorktreeBinding, error)
	Inspect(ctx context.Context, binding domain.WorktreeBinding) (domain.WorktreeBinding, error)
	SyncFastForward(ctx context.Context, binding domain.WorktreeBinding) (domain.WorktreeBinding, error)
	Fork(ctx context.Context, source domain.WorktreeBinding, request TaskWorktreeCreateRequest) (domain.WorktreeBinding, error)
	MergeToBase(ctx context.Context, binding domain.WorktreeBinding) (domain.WorktreeBinding, error)
	RemoveMerged(ctx context.Context, binding domain.WorktreeBinding) error
	Discard(ctx context.Context, binding domain.WorktreeBinding) error
}
```

- [ ] **Step 4: 实现 Git 命令序列**

创建流程严格使用：

```text
git fetch origin
git rev-parse <base-ref>
git worktree add -b task/<task-id>-<slug> <repo>/.worktrees/<task-id>-<slug> <base-ref>
git -C <worktree> rev-parse --git-common-dir
git -C <worktree> rev-parse HEAD
```

同步流程只使用：

```text
git fetch origin
git merge --ff-only <resolved-base-ref>
```

禁止在 manager 中调用 `commit`、`rebase`、非快进 merge、force push 或自动冲突解决。

- [ ] **Step 5: 实现 worktree 身份文件**

写入内容必须是：

```yaml
engineering_task_id: task-20260711-001
repository_id: apaas-builder-ai
branch: task/task-20260711-001-fix-login-state
created_at: 2026-07-11T12:05:02Z
```

读取身份文件时拒绝任务 ID、branch 或 common-dir 不一致。

- [ ] **Step 6: 运行 Git 集成测试**

Run:

```bash
go test ./internal/adapters/git -run 'TaskWorktree|ParseCodeProjectionWorktree'
```

Expected: PASS。

- [ ] **Step 7: 提交 Worktree Manager**

Run:

```bash
git add internal/ports/ports.go internal/adapters/git/task_worktree_manager.go internal/adapters/git/task_worktree_manager_test.go
git commit -m "feat(runtime): manage task worktrees"
```

### Task 5: 实现任务服务、意图判断和同任务协调器

**Files:**
- Create: `agent-runtime/internal/application/engineering_tasks.go`
- Create: `agent-runtime/internal/application/engineering_tasks_test.go`
- Create: `agent-runtime/internal/application/task_intent.go`
- Create: `agent-runtime/internal/application/task_intent_test.go`
- Create: `agent-runtime/internal/application/task_execution_coordinator.go`
- Create: `agent-runtime/internal/application/task_execution_coordinator_test.go`

- [ ] **Step 1: 写意图判断测试**

表驱动测试至少包含：

```go
tests := []struct {
	text string
	want TaskIntentKind
}{
	{"解释一下登录鉴权怎么走", TaskIntentReadOnly},
	{"查看当前 git 状态", TaskIntentReadOnly},
	{"修复登录状态丢失", TaskIntentWrite},
	{"把 README 的本地运行方式补充完整", TaskIntentWrite},
	{"运行测试并修复失败项", TaskIntentWrite},
	{"查看线上日志", TaskIntentRemoteOnly},
	{"看看这个登录问题", TaskIntentAmbiguous},
}
```

结构化原型实现请求、明确 `workspaceIntent=write` 必须直接判定为写；显式 `read_only` 必须覆盖文本启发式判断。

- [ ] **Step 2: 写任务升级和队列测试**

覆盖：

- 普通 Session 升级时先持久化 `preparing` Task，再创建 worktree。
- worktree 创建失败后 Task 为 `blocked`，Session 仍是 `base_readonly`。
- 绑定完成后 Session 变为 `task_worktree`。
- 相同 Task 只能获取一个活跃 Turn。
- 第二个 Session 可返回 `TASK_BUSY`、入队或 fork。
- `expectedHead` 改变后队列项变为 `needs_confirmation`。
- CAS 冲突时重读一次并重新计算；第二次冲突直接返回 revision 错误。

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
go test ./internal/application -run 'TaskIntent|EngineeringTask|TaskExecutionCoordinator'
```

Expected: FAIL。

- [ ] **Step 4: 实现显式且可测试的意图契约**

在 `ChatRequest` 增加：

```go
WorkspaceIntent string `json:"workspaceIntent,omitempty"`
TaskAction      string `json:"taskAction,omitempty"`
```

允许值：

```go
const (
	WorkspaceIntentAuto       = "auto"
	WorkspaceIntentReadOnly   = "read_only"
	WorkspaceIntentWrite      = "write"
	WorkspaceIntentRemoteOnly = "remote_only"
)
```

`ClassifyTaskIntent` 只负责前置路由，不承担最终写安全。它必须返回：

```go
type TaskIntentDecision struct {
	Kind     TaskIntentKind
	TaskType domain.EngineeringTaskType
	Reason   string
}
```

- [ ] **Step 5: 实现任务服务状态转换**

关键接口：

```go
type EngineeringTaskService struct {
	statePath     string
	repoPath      string
	repositoryID  string
	store         ports.EngineeringTaskStore
	worktrees     ports.TaskWorktreeManager
	coordinator   *TaskExecutionCoordinator
	now           func() time.Time
}

func (service EngineeringTaskService) UpgradeSession(
	ctx context.Context,
	mapping domain.AgentSessionMapping,
	request domain.ChatRequest,
	expectedRevision int64,
) (domain.AgentSessionMapping, domain.EngineeringTask, error)
```

升级顺序：

1. CAS 保存 `EngineeringTaskPreparing`。
2. 调用 `TaskWorktreeManager.Create`。
3. CAS 保存 `WorktreeBindingReady` 和 `EngineeringTaskActive`。
4. 更新 Session 的 `EngineeringTaskID`、`WorkspaceMode`、`WorkspacePath`。
5. 任何失败都不修改 Session 到主工作区可写状态。

- [ ] **Step 6: 实现协调器**

协调器结果固定为：

```go
type TaskTurnDecision string

const (
	TaskTurnAcquired          TaskTurnDecision = "acquired"
	TaskTurnBusy              TaskTurnDecision = "busy"
	TaskTurnQueued            TaskTurnDecision = "queued"
	TaskTurnHeadConfirmation  TaskTurnDecision = "head_confirmation"
)
```

协调器只锁任务状态和队列，不锁文件路径。Turn 完成时清空 `ActiveTurnSessionID`，刷新 Git 状态，再尝试推进下一条队列。

- [ ] **Step 7: 运行应用层测试**

Run:

```bash
go test ./internal/application -run 'TaskIntent|EngineeringTask|TaskExecutionCoordinator'
```

Expected: PASS。

- [ ] **Step 8: 提交任务服务**

Run:

```bash
git add internal/domain/agent_session.go internal/application/engineering_tasks.go internal/application/engineering_tasks_test.go internal/application/task_intent.go internal/application/task_intent_test.go internal/application/task_execution_coordinator.go internal/application/task_execution_coordinator_test.go
git commit -m "feat(runtime): coordinate engineering tasks"
```

### Task 6: 让新会话即时创建并延迟创建 Codex Thread

**Files:**
- Modify: `agent-runtime/internal/application/agent_sessions.go`
- Modify: `agent-runtime/internal/application/agent_sessions_test.go`
- Modify: `agent-runtime/internal/http/agent_handlers.go`
- Modify: `agent-runtime/internal/http/agent_handlers_test.go`
- Modify: `agent-runtime/internal/http/handlers.go`

- [ ] **Step 1: 写即时创建测试**

增加测试：

```go
func TestAgentSessionsCreateNewPersistsReadonlySessionWithoutCreatingThread(t *testing.T) {
	runtime := &fakeAgentRuntime{}
	store := &fakeAgentSessionStore{}
	index := &fakeAgentSessionIndexStore{}
	uc := NewAgentSessionsWithSessionIndex(testRuntimeContext(), "/repo", "/state", store, index, nil, runtime, nil, nil)

	mapping, err := uc.CreateNew(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if runtime.createCalls != 0 {
		t.Fatalf("Create calls = %d", runtime.createCalls)
	}
	if mapping.WorkspaceMode != domain.AgentWorkspaceModeBaseReadonly {
		t.Fatalf("WorkspaceMode = %q", mapping.WorkspaceMode)
	}
	if mapping.State != domain.AgentSessionWaitingInput {
		t.Fatalf("State = %q", mapping.State)
	}
}
```

HTTP 测试断言 `POST /api/agent/sessions` 返回 `202`。

- [ ] **Step 2: 确认测试失败**

Run:

```bash
go test ./internal/application ./internal/http -run 'CreateNewPersistsReadonly|CreateAgentSession'
```

Expected: FAIL，当前实现会同步调用 `runtime.Create` 并返回 `200`。

- [ ] **Step 3: 拆分 Session 持久化和 Thread 初始化**

新增内部方法：

```go
func (uc AgentSessions) createSessionRecord(now time.Time) (domain.AgentSessionMapping, error) {
	mapping := uc.newMapping(now)
	mapping.WorkspaceMode = domain.AgentWorkspaceModeBaseReadonly
	mapping.WorkspacePath = uc.workspacePath
	mapping.State = domain.AgentSessionWaitingInput
	if err := uc.saveCurrentDetached(context.Background(), mapping); err != nil {
		return domain.AgentSessionMapping{}, err
	}
	uc.syncSessionIndex(context.Background(), mapping, sessionIndexSyncOptions{current: true})
	return mapping, nil
}
```

`CreateNew` 只调用该方法。`CreateOrResume` 仍可恢复已有真实 Thread，但新 fallback 也使用延迟创建。

- [ ] **Step 4: 保留任务工作区路径**

修改 `completeMapping`：

```go
if strings.TrimSpace(mapping.WorkspacePath) == "" {
	mapping.WorkspacePath = uc.workspacePath
}
mapping = domain.NormalizeAgentSessionWorkspace(mapping)
```

`mappingFromRecord` 必须恢复 `EngineeringTaskID`、`WorkspaceMode`、`WorkspacePath`、`TaskState`、`TaskRevision`，不得统一覆盖为 repo 根目录。

- [ ] **Step 5: 在首条消息前确保 Thread**

新增：

```go
func (uc AgentSessions) ensureRuntimeSession(
	ctx context.Context,
	mapping domain.AgentSessionMapping,
) (domain.AgentSessionMapping, error) {
	if current, ok := uc.runtime.Current(mapping.RuntimeSessionID); ok {
		return current, nil
	}
	if mapping.CodexSessionResumable && strings.TrimSpace(mapping.CodexSessionID) != "" {
		return uc.runtime.Resume(ctx, mapping)
	}
	return uc.runtime.Create(ctx, mapping)
}
```

该方法只在任务路由和 worktree 准备完成后调用。

- [ ] **Step 6: 返回 202**

`CreateAgentSession` 改为：

```go
writeJSON(w, http.StatusAccepted, newAgentSessionResponse(mapping))
```

`agentSessionResponse` 和 `agentSessionRecordResponse` 同时公开：

```go
EngineeringTaskID string                      `json:"engineeringTaskId,omitempty"`
WorkspaceMode     domain.AgentWorkspaceMode   `json:"workspaceMode"`
WorkspacePath     string                      `json:"workspacePath,omitempty"`
TaskState         domain.EngineeringTaskState `json:"taskState,omitempty"`
TaskRevision      int64                       `json:"taskRevision,omitempty"`
```

创建普通会话不再受 `WorkspaceReadiness.CanStartAgentSession` 阻塞；真正发送消息时仍检查 repo 可读性和任务准备状态。

- [ ] **Step 7: 跑测试**

Run:

```bash
go test ./internal/application ./internal/http -run 'CreateNew|CreateAgentSession|ActivateSession|DeleteSession'
```

Expected: PASS。

- [ ] **Step 8: 提交即时会话创建**

Run:

```bash
git add internal/application/agent_sessions.go internal/application/agent_sessions_test.go internal/http/agent_handlers.go internal/http/agent_handlers_test.go internal/http/handlers.go
git commit -m "feat(runtime): create readonly sessions immediately"
```

### Task 7: 接入只读 Sandbox、写入升级和首次写入保护

**Files:**
- Modify: `agent-runtime/internal/ports/ports.go`
- Modify: `agent-runtime/internal/adapters/agent/codexappserver/runtime.go`
- Modify: `agent-runtime/internal/adapters/agent/codexappserver/runtime_test.go`
- Modify: `agent-runtime/internal/application/agent_sessions.go`
- Modify: `agent-runtime/internal/application/agent_sessions_test.go`

- [ ] **Step 1: 写 Sandbox 和重绑定测试**

测试必须断言：

- `base_readonly` 的 `turn/start.sandboxPolicy.type` 是 `readOnly`。
- `task_worktree` 的 `turn/start.sandboxPolicy.type` 是 `workspaceWrite`，写根仅包含任务 worktree、Git common-dir 和 Runtime 临时目录。
- `remote_only` 不暴露 repo 写根。
- idle Session 可以用同一 Codex Thread ID 重绑定到任务 cwd。
- busy Session 重绑定返回冲突。

示例：

```go
policy := client.turnStartParams.SandboxPolicy.(map[string]any)
if policy["type"] != "readOnly" {
	t.Fatalf("sandbox type = %#v", policy["type"])
}
```

- [ ] **Step 2: 写首次写入拦截测试**

模拟 `item/fileChange/requestApproval` 和可写命令审批：

```go
func TestRuntimeBlocksWriteApprovalForReadonlySession(t *testing.T) {
	runtime, client, sessionID := newReadonlyRuntimeFixture(t)
	client.serverRequests <- ServerRequest{
		ID:     json.RawMessage(`"approval-1"`),
		Method: "item/fileChange/requestApproval",
		Params: json.RawMessage(`{"threadId":"thread-real-1","turnId":"turn-1","changes":[{"path":"README.md"}]}`),
	}
	event := receiveRuntimeEventEventually(t, runtime.events(sessionID), domain.BuilderEventWorkspaceEscalation)
	if event.Payload["errorCode"] != domain.EngineeringTaskErrorWriteRequiresWorktree {
		t.Fatalf("payload = %#v", event.Payload)
	}
}
```

- [ ] **Step 3: 确认测试失败**

Run:

```bash
go test ./internal/adapters/agent/codexappserver ./internal/application -run 'Readonly|Rebind|WriteApproval|WorkspaceEscalation'
```

Expected: FAIL。

- [ ] **Step 4: 增加 Runtime 重绑定端口**

```go
type AgentSessionRuntimeWorkspaceRebinder interface {
	RebindWorkspace(ctx context.Context, mapping domain.AgentSessionMapping) (domain.AgentSessionMapping, error)
}
```

`RebindWorkspace` 必须要求 Session idle，使用 `thread/resume` 的同一 `CodexSessionID` 和新 `CWD`，成功后原子替换内存 mapping。

- [ ] **Step 5: 根据 WorkspaceMode 生成 SandboxPolicy**

实现：

```go
func sandboxPolicyForMapping(mapping domain.AgentSessionMapping) map[string]any {
	switch mapping.WorkspaceMode {
	case domain.AgentWorkspaceModeTaskWorktree:
		return map[string]any{
			"type": "workspaceWrite",
			"writableRoots": []string{
				mapping.WorkspacePath,
				mapping.GitCommonDir,
				mapping.RuntimeWritablePath,
			},
			"networkAccess": true,
		}
	case domain.AgentWorkspaceModeRemoteOnly:
		return map[string]any{"type": "readOnly", "networkAccess": true}
	default:
		return map[string]any{"type": "readOnly", "networkAccess": true}
	}
}
```

为此在 `AgentSessionMapping` 增加仅 Runtime 使用的：

```go
GitCommonDir       string `json:"gitCommonDir,omitempty"`
RuntimeWritablePath string `json:"runtimeWritablePath,omitempty"`
```

- [ ] **Step 6: 拦截只读会话的写审批**

在 server request 处理前判断：

```go
func writeApprovalRequiresTask(method string, params map[string]any) bool {
	switch method {
	case "item/fileChange/requestApproval", "applyPatchApproval":
		return true
	case "item/commandExecution/requestApproval", "execCommandApproval":
		return commandMayWrite(stringValue(params, "command"))
	default:
		return false
	}
}
```

命中时：

1. 向 App Server 返回拒绝决定。
2. 中断当前 Turn。
3. 发布 `BuilderEventWorkspaceEscalation`。
4. 不允许 approval auto-accept 绕过此检查。

- [ ] **Step 7: 在 AgentSessions 中处理升级和重放**

发送前将 `ChatRequest` 作为 `SessionTurnEnvelope` 持久化到任务 registry 的 `PendingTurns`。收到 escalation 事件后：

1. 调用 `EngineeringTaskService.UpgradeSession`。
2. 调用 `RebindWorkspace`。
3. 使用新的 `clientMessageId` 重放原请求。
4. 原 envelope 标记为 `superseded`，重放成功后删除。

同一 envelope 最多自动重放一次，第二次升级事件返回 `TASK_WRITE_REQUIRES_WORKTREE` 并停止。

- [ ] **Step 8: 跑 Runtime 和应用层测试**

Run:

```bash
go test ./internal/adapters/agent/codexappserver ./internal/application -run 'Readonly|WorkspaceWrite|Rebind|WriteApproval|WorkspaceEscalation|Replay'
```

Expected: PASS。

- [ ] **Step 9: 提交安全升级链路**

Run:

```bash
git add internal/ports/ports.go internal/domain/agent_session.go internal/adapters/agent/codexappserver/runtime.go internal/adapters/agent/codexappserver/runtime_test.go internal/application/agent_sessions.go internal/application/agent_sessions_test.go
git commit -m "feat(runtime): protect readonly sessions with task upgrade"
```

### Task 8: 接入消息协调、任务 API、活动投影和 Runtime 启动恢复

**Files:**
- Create: `agent-runtime/internal/http/engineering_task_handlers.go`
- Create: `agent-runtime/internal/http/engineering_task_handlers_test.go`
- Create: `agent-runtime/internal/adapters/git/task_pull_request_gateway.go`
- Create: `agent-runtime/internal/adapters/git/task_pull_request_gateway_test.go`
- Modify: `agent-runtime/internal/http/server.go`
- Modify: `agent-runtime/internal/http/handlers.go`
- Modify: `agent-runtime/internal/http/agent_handlers.go`
- Modify: `agent-runtime/internal/application/agent_sessions.go`
- Modify: `agent-runtime/cmd/sandbox-runtime/main.go`

- [ ] **Step 1: 写 HTTP 契约测试**

覆盖以下路由：

```text
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

所有修改请求必须携带：

```json
{"revision":4}
```

旧 revision 返回 HTTP `409` 和：

```json
{"code":"TASK_REVISION_CONFLICT","message":"任务状态已变化，请刷新后重试"}
```

- [ ] **Step 2: 写 SendMessage 状态测试**

明确断言：

- read-only 消息正常发送。
- write 消息返回 `202`、`status=task_preparing`。
- busy 返回 `409`、`code=TASK_BUSY`、actions 为 `queue`、`fork`、`cancel`。
- 入队返回 `202`、`status=queued`。
- head 变化返回 `409`、`code=TASK_HEAD_CHANGED`。

- [ ] **Step 3: 确认测试失败**

Run:

```bash
go test ./internal/http ./internal/application -run 'EngineeringTask|TaskBusy|TaskHeadChanged|TaskPreparing'
```

Expected: FAIL。

- [ ] **Step 4: 扩展 SendMessageResponse**

```go
const (
	SendMessageStatusAccepted          SendMessageStatus = "accepted"
	SendMessageStatusRecovering        SendMessageStatus = "recovering"
	SendMessageStatusTaskPreparing     SendMessageStatus = "task_preparing"
	SendMessageStatusQueued            SendMessageStatus = "queued"
	SendMessageStatusNeedsConfirmation SendMessageStatus = "needs_confirmation"
)
```

增加：

```go
EngineeringTaskID string   `json:"engineeringTaskId,omitempty"`
TaskRevision      int64    `json:"taskRevision,omitempty"`
QueueItemID       string   `json:"queueItemId,omitempty"`
AvailableActions  []string `json:"availableActions,omitempty"`
```

- [ ] **Step 5: 实现任务活动投影**

`GET /activity` 返回：

```go
type EngineeringTaskActivity struct {
	Task             domain.EngineeringTask       `json:"task"`
	Worktree         *domain.WorktreeBinding      `json:"worktree,omitempty"`
	Queue            []domain.TaskQueueItem       `json:"queue"`
	Plan             *domain.AgentPlanState       `json:"plan,omitempty"`
	DigitalEmployees []domain.DigitalEmployeeView `json:"digitalEmployees"`
	Trace            []domain.AgentTimelineEvent  `json:"trace"`
	Revision         int64                        `json:"revision"`
}
```

Trace 只返回当前任务关联 Session 的最近 200 条事件，保持现有脱敏逻辑。

- [ ] **Step 6: 实现任务收尾**

`finish.action` 允许：

```text
merge
pull_request
keep
discard
```

前置条件：

- 无活跃 Turn。
- 无 queued/running 项。
- 无其他 Session 正使用该 cwd。
- merge cleanup 要求 clean 且已合并。
- discard 要求 `confirmationTitle` 等于任务标题。

`pull_request` 首版通过 `TaskPullRequestGateway`：

```go
type TaskPullRequestGateway interface {
	Create(ctx context.Context, binding domain.WorktreeBinding, title string) (url string, err error)
}
```

在 `internal/adapters/git/task_pull_request_gateway.go` 实现默认 adapter：检测 remote host 后选择 `gh` 或 `glab`，先执行普通 `git push -u origin <branch>`，再创建 PR/MR；两者均不可用时返回 `TASK_FINISH_BLOCKED`，保留 worktree。测试使用临时可执行脚本记录参数，禁止访问真实远端。

- [ ] **Step 7: Runtime 启动 reconcile**

在 `cmd/sandbox-runtime/main.go`：

```go
taskStore := builder.NewFileEngineeringTaskStore()
taskWorktrees := git.NewTaskWorktreeManager()
engineeringTasks := application.NewEngineeringTaskService(
	runtimeWorkspacePath,
	repoWorkspacePath,
	runtimeContext.AppID,
	taskStore,
	taskWorktrees,
)
```

将其注入 `AgentSessions`、HTTP `Dependencies`，启动 goroutine：

```go
go func() {
	if err := engineeringTasks.ReconcileAll(ctx); err != nil {
		log.Printf("engineering task startup reconcile failed: %v", err)
	}
}()
```

- [ ] **Step 8: 跑 Runtime API 测试**

Run:

```bash
go test ./internal/application ./internal/http ./cmd/sandbox-runtime -run 'EngineeringTask|AgentSession|Reconcile|Finish'
```

Expected: PASS。

- [ ] **Step 9: 提交 API 和 wiring**

Run:

```bash
git add internal/domain/agent_session.go internal/application/agent_sessions.go internal/adapters/git/task_pull_request_gateway.go internal/adapters/git/task_pull_request_gateway_test.go internal/http/engineering_task_handlers.go internal/http/engineering_task_handlers_test.go internal/http/server.go internal/http/handlers.go internal/http/agent_handlers.go cmd/sandbox-runtime/main.go
git commit -m "feat(runtime): expose engineering task lifecycle"
```

### Task 9: 构建 Runtime 统一执行活动面板

**Files:**
- Modify: `agent-runtime/web/builder/src/api/types.ts`
- Modify: `agent-runtime/web/builder/src/api/client.ts`
- Create: `agent-runtime/web/builder/src/components/chat/ExecutionActivityPanel.tsx`
- Create: `agent-runtime/web/builder/src/components/chat/ExecutionActivityPanel.test.tsx`
- Modify: `agent-runtime/web/builder/src/components/chat/timelineStore.ts`
- Modify: `agent-runtime/web/builder/src/components/chat/timelineStore.test.ts`
- Modify: `agent-runtime/web/builder/src/components/chat/ChatPane.tsx`
- Modify: `agent-runtime/web/builder/src/components/chat/ChatPane.test.tsx`
- Modify: `agent-runtime/web/builder/src/styles/builder.less`

- [ ] **Step 1: 写 API 类型和 activity model 测试**

新增类型：

```ts
export type AgentWorkspaceMode = "base_readonly" | "task_worktree" | "remote_only";

export interface EngineeringTaskSummary {
  id: string;
  title: string;
  taskType: string;
  state: string;
  branch?: string;
  worktreeName?: string;
  clean?: boolean;
  ahead?: number;
  behind?: number;
  mergedToBase?: boolean;
  activeTurnSessionId?: string;
  sessionCount: number;
  queueCount: number;
  revision: number;
}
```

`AgentSessionMapping` 和 `AgentSessionRecord` 增加 `engineeringTaskId`、`workspaceMode`、`taskState`、`taskRevision`。

- [ ] **Step 2: 写面板行为测试**

覆盖：

- 一个入口按钮，标签为“执行活动”。
- 三个 Tab：任务、数字员工、Trace。
- 默认打开任务 Tab。
- 点击 Plan 摘要打开任务 Tab。
- 普通会话任务 Tab 显示“当前是查询会话”，不显示 branch/worktree。
- 桌面端面板使用 docked class，不是浮层。
- 小于 `768px` 使用 drawer class。
- 旧 `TODO 任务列表`、`MCP` 独立区块和完整 `TodoListPanel` 不再渲染。

- [ ] **Step 3: 确认测试失败**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync/web/builder
npm exec -- vitest run --config vitest.unit.config.mjs src/components/chat/ExecutionActivityPanel.test.tsx src/components/chat/ChatPane.test.tsx src/components/chat/timelineStore.test.ts
```

Expected: FAIL。

- [ ] **Step 4: 增加 API client**

```ts
export function getEngineeringTask(taskId: string): Promise<EngineeringTaskSummary> {
  return request(`/api/engineering-tasks/${encodeURIComponent(taskId)}`);
}

export function getEngineeringTaskActivity(taskId: string): Promise<EngineeringTaskActivity> {
  return request(`/api/engineering-tasks/${encodeURIComponent(taskId)}/activity`);
}

export function finishEngineeringTask(
  taskId: string,
  body: EngineeringTaskFinishRequest
): Promise<EngineeringTaskActivity> {
  return request(`/api/engineering-tasks/${encodeURIComponent(taskId)}/finish`, {
    method: "POST",
    body: JSON.stringify(body)
  });
}
```

- [ ] **Step 5: 将控制行改成任务、数字员工、Trace**

`TimelineControlRows` 改为：

```ts
export interface TimelineControlRows {
  tasks: TimelineControlRow[];
  digitalEmployees: TimelineControlRow[];
  trace: TimelineControlRow[];
}
```

Trace 包含 tool、skill、MCP、Runtime 状态和 error；不再把 MCP 单独作为一级区域。

- [ ] **Step 6: 实现停靠面板**

`ExecutionActivityPanel` 使用 Ant Design `Tabs`、Lucide `ListChecks`、`UsersRound`、`Activity`、`X` 图标。桌面布局：

```tsx
<div className="chat-execution-layout" data-panel-open={open ? "true" : "false"}>
  <div className="chat-pane-main">{main}</div>
  {open ? <aside className="execution-activity-panel">{panel}</aside> : null}
</div>
```

CSS 使用固定响应约束：

```less
.chat-execution-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
}

.chat-execution-layout[data-panel-open="true"] {
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
}

.execution-activity-panel {
  min-width: 0;
  border-left: 1px solid var(--border);
  background: var(--panel);
}

@media (max-width: 767px) {
  .execution-activity-panel {
    position: fixed;
    inset: 0;
    z-index: 60;
    width: 100%;
  }
}
```

- [ ] **Step 7: 用 Plan 摘要替换完整任务卡**

删除：

```tsx
<TodoListPanel panel={effectiveTodoPanel} debug={timelineDebug} />
```

替换为：

```tsx
<PlanProgressSummary
  panel={effectiveTodoPanel}
  onOpen={() => {
    setExecutionActivityTab("tasks");
    setExecutionActivityOpen(true);
  }}
/>
```

摘要只显示当前步骤、完成数和“查看任务”。

- [ ] **Step 8: 跑前端测试和类型检查**

Run:

```bash
npm exec -- vitest run --config vitest.unit.config.mjs src/components/chat/ExecutionActivityPanel.test.tsx src/components/chat/ChatPane.test.tsx src/components/chat/timelineStore.test.ts
npm run typecheck
```

Expected: PASS。

- [ ] **Step 9: 提交 Runtime 前端**

Run:

```bash
git add src/api/types.ts src/api/client.ts src/components/chat/ExecutionActivityPanel.tsx src/components/chat/ExecutionActivityPanel.test.tsx src/components/chat/timelineStore.ts src/components/chat/timelineStore.test.ts src/components/chat/ChatPane.tsx src/components/chat/ChatPane.test.tsx src/styles/builder.less
git commit -m "feat(builder): unify execution activity panel"
```

### Task 10: 扩展 Runtime 到 aPaaS Shell 的状态事件

**Files:**
- Modify: `agent-runtime/web/builder/src/lib/shellEvents.ts`
- Modify: `agent-runtime/web/builder/src/lib/shellEvents.test.ts`
- Modify: `agent-runtime/web/builder/src/app/BuilderApp.tsx`
- Modify: `agent-runtime/web/builder/src/app/BuilderApp.test.tsx`

- [ ] **Step 1: 写事件 payload 测试**

要求 `agent.sessionStateChanged` 包含：

```json
{
  "runtimeSessionId": "runtime-1",
  "state": "waiting_input",
  "engineeringTaskId": "task-20260711-001",
  "workspaceMode": "task_worktree",
  "taskState": "active",
  "taskRevision": 4
}
```

普通会话必须包含 `workspaceMode=base_readonly`，任务字段可省略。

- [ ] **Step 2: 确认测试失败**

Run:

```bash
npm exec -- vitest run --config vitest.unit.config.mjs src/lib/shellEvents.test.ts src/app/BuilderApp.test.tsx
```

Expected: FAIL。

- [ ] **Step 3: 扩展事件类型和去重 key**

`BuilderApp.tsx` 的 `sessionStateKey` 加入任务 ID、workspace mode、task state、revision，避免任务升级后外层 Rail 不刷新。

- [ ] **Step 4: 跑测试**

Run:

```bash
npm exec -- vitest run --config vitest.unit.config.mjs src/lib/shellEvents.test.ts src/app/BuilderApp.test.tsx
```

Expected: PASS。

- [ ] **Step 5: 提交 Shell 事件**

Run:

```bash
git add src/lib/shellEvents.ts src/lib/shellEvents.test.ts src/app/BuilderApp.tsx src/app/BuilderApp.test.tsx
git commit -m "feat(builder): publish task state to shell"
```

### Task 11: 扩展 aPaaS Runtime Proxy 和会话投影

**Files:**
- Modify: `apaas-builder-ai/backend/app/models/ai_chat.py`
- Modify: `apaas-builder-ai/backend/app/database.py`
- Modify: `apaas-builder-ai/backend/app/routes/code_runtime.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_routes.py`
- Modify: `apaas-builder-ai/backend/tests/test_ai_chat_app_id_column.py`

- [ ] **Step 1: 写后端代理和迁移测试**

覆盖：

- `CodeRuntimeAgentSession` 保存 `engineering_task_id`、`workspace_mode`、`task_state`、`task_revision`。
- rail history 将 Runtime 返回的任务投影原样返回。
- continue、fork、finish、queue、reconcile 路由只做代理，不调用 Python `EngineeringSessionService`。
- Runtime `202` 保持为 `202`，不转换成 `200`。
- Runtime 错误 body 保留 `code` 和 `message`。

- [ ] **Step 2: 确认测试失败**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync/backend
pytest -q tests/test_code_runtime_routes.py tests/test_ai_chat_app_id_column.py
```

Expected: FAIL。

- [ ] **Step 3: 增加投影字段**

在 `CodeRuntimeAgentSession` 增加：

```python
engineering_task_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
workspace_mode: Mapped[str] = mapped_column(String(32), default="base_readonly", nullable=False)
task_state: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
task_revision: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
```

这些字段只是查询投影，不是任务真实状态。

- [ ] **Step 4: 添加 SQLite/MySQL 兼容迁移**

在 `database.py` 使用现有 inspect + `ALTER TABLE ADD COLUMN` 风格补列，并为 `engineering_task_id` 建索引。迁移必须可重复执行。

- [ ] **Step 5: 让 Runtime 请求返回状态码**

将 `_runtime_json_request` 返回值改为：

```python
class RuntimeJSONResponse(BaseModel):
    status_code: int
    payload: Any
```

同一次提交必须更新 `code_runtime.py` 内全部调用点：读取 Session、rail history、current alignment、create、activate、delete 和通用 proxy helper 都显式取 `.payload`；只有需要向浏览器保留 Runtime 状态码的 mutation 路由使用 `.status_code`。

创建 Session 时：

```python
runtime_response = await _runtime_json_request(
    binding,
    "POST",
    "/api/agent/sessions",
    json_body={},
)
response = JSONResponse(
    status_code=runtime_response.status_code,
    content={
        "shell_session_id": int(session_id),
        "runtime_session_id": runtime_session_id,
        "session": runtime_response.payload,
    },
)
return response
```

读取类调用使用 `runtime_response.payload`。

- [ ] **Step 6: 增加任务代理路由**

```text
POST   /code/sessions/{shellSessionId}/agent-sessions/{runtimeSessionId}/upgrade-task
POST   /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/sessions
POST   /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/fork
GET    /code/sessions/{shellSessionId}/engineering-tasks/{taskId}
GET    /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/activity
POST   /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/queue
DELETE /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/queue/{queueItemId}
POST   /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/finish
POST   /code/sessions/{shellSessionId}/engineering-tasks/{taskId}/reconcile
```

每个路由先通过 `_authorized_code_runtime_binding` 校验租户、用户和 shell session，再转发 Runtime。

- [ ] **Step 7: 同步投影**

`_remember_runtime_agent_session` 从 Runtime Session payload 更新四个投影字段。`agent.sessionStateChanged` 仍触发 rail refresh，下一次 history 读取 Runtime 事实后覆盖旧投影。

- [ ] **Step 8: 运行后端测试**

Run:

```bash
pytest -q tests/test_code_runtime_routes.py tests/test_ai_chat_app_id_column.py tests/test_code_runtime_service.py
```

Expected: PASS。

- [ ] **Step 9: 提交 aPaaS 后端**

Run:

```bash
git add backend/app/models/ai_chat.py backend/app/database.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_routes.py backend/tests/test_ai_chat_app_id_column.py
git commit -m "feat(code): proxy engineering task lifecycle"
```

### Task 12: 改造 aPaaS Code Rail 的任务状态和菜单

**Files:**
- Modify: `apaas-builder-ai/frontend/src/api/codeRuntime.ts`
- Modify: `apaas-builder-ai/frontend/src/composables/railSessions.ts`
- Modify: `apaas-builder-ai/frontend/src/composables/railSessions.spec.ts`
- Modify: `apaas-builder-ai/frontend/src/components/v2/RailSidebar.vue`
- Modify: `apaas-builder-ai/frontend/src/components/v2/RailSidebar.spec.ts`

- [ ] **Step 1: 写 Rail 归一化测试**

增加任务会话输入：

```ts
{
  runtimeSessionId: "runtime-2",
  title: "修复登录问题",
  state: "waiting_input",
  engineeringTaskId: "task-20260711-001",
  workspaceMode: "task_worktree",
  taskState: "active",
  taskRevision: 4,
  branch: "task/task-20260711-001-fix-login",
  sharedSessionCount: 2
}
```

期望 RailSession 包含任务 badge、共享会话数和可用菜单；普通会话不包含 Git 信息。

- [ ] **Step 2: 写交互源码测试**

断言：

- 应用分组 `+` 仍只调用 `createAgentSession`。
- 菜单包含“继续此任务”“派生新任务”“完成任务”“归档会话”。
- 普通查询会话只显示“归档会话”。
- 删除文案改为归档，不再暗示删除 worktree。
- 状态文字包含准备工作区、执行中、排队中、上下文已变化、等待合并、已合并、工作区异常。

- [ ] **Step 3: 确认测试失败**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync/frontend
npm test -- --run src/composables/railSessions.spec.ts src/components/v2/RailSidebar.spec.ts
```

Expected: FAIL。

- [ ] **Step 4: 扩展 API 类型**

`CodeAgentSessionRecord` 增加：

```ts
engineeringTaskId?: string | null
workspaceMode?: 'base_readonly' | 'task_worktree' | 'remote_only' | null
taskState?: string | null
taskRevision?: number | null
branch?: string | null
worktreeName?: string | null
sharedSessionCount?: number | null
queueCount?: number | null
```

增加 continue、fork、finish、queue、reconcile 方法，所有 mutation body 带 revision。

- [ ] **Step 5: 扩展 RailSession**

```ts
engineeringTaskId?: string
workspaceMode?: 'base_readonly' | 'task_worktree' | 'remote_only'
taskState?: string
taskRevision?: number
branch?: string
sharedSessionCount?: number
queueCount?: number
```

- [ ] **Step 6: 实现会话菜单**

菜单使用 Element Plus dropdown 和图标，不使用行内文本按钮堆叠。完成任务打开 modal，四个动作分别是本地合并、创建 PR、保留任务、放弃任务；放弃要求输入任务标题。

- [ ] **Step 7: 归档语义**

现有 `deleteAgentSession` 前端方法改名为 `archiveAgentSession`，后端仍可在迁移期调用 Runtime `DELETE /api/agent/sessions/{id}`，但 UI 文案和测试统一为归档。Runtime 删除实现只标记 `DeletedAt`，不触碰 Task 或 worktree。

- [ ] **Step 8: 跑 Rail 测试和构建**

Run:

```bash
npm test -- --run src/composables/railSessions.spec.ts src/components/v2/RailSidebar.spec.ts
npm run build
```

Expected: PASS。

- [ ] **Step 9: 提交 aPaaS Rail**

Run:

```bash
git add frontend/src/api/codeRuntime.ts frontend/src/composables/railSessions.ts frontend/src/composables/railSessions.spec.ts frontend/src/components/v2/RailSidebar.vue frontend/src/components/v2/RailSidebar.spec.ts
git commit -m "feat(code): show task-aware session rail"
```

### Task 13: 完成 iframe 状态联动和任务操作反馈

**Files:**
- Modify: `apaas-builder-ai/frontend/src/views/CodeConversationPage.vue`
- Modify: `apaas-builder-ai/frontend/src/views/CodeConversationPage.spec.ts`
- Modify: `agent-runtime/web/builder/src/lib/shellEvents.ts`
- Modify: `agent-runtime/web/builder/src/app/BuilderApp.tsx`

- [ ] **Step 1: 写 Shell 消息联动测试**

覆盖：

- 收到 Session 任务升级后立即刷新外层 Rail。
- `TASK_BUSY`、`TASK_HEAD_CHANGED`、`WORKTREE_INIT_FAILED` 通过 Shell event 显示非遮挡提示。
- route agent 激活顺序保持先 open shell，再 activate runtime session。
- iframe 切换期间旧 frame 保持可见。

- [ ] **Step 2: 增加 Shell event**

允许：

```ts
| "engineering.taskStateChanged"
| "engineering.taskActionRequired"
```

`taskActionRequired` payload 包含：

```ts
{
  code: string;
  runtimeSessionId: string;
  engineeringTaskId?: string;
  message: string;
  availableActions: string[];
}
```

- [ ] **Step 3: 在 CodeConversationPage 处理消息**

`taskStateChanged` 只刷新 Rail；`taskActionRequired` 设置输入框上方或页面顶部 toast，不替换 iframe，不造成白屏。

- [ ] **Step 4: 跑两仓前端测试**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync/web/builder
npm exec -- vitest run --config vitest.unit.config.mjs src/lib/shellEvents.test.ts src/app/BuilderApp.test.tsx
cd /mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync/frontend
npm test -- --run src/views/CodeConversationPage.spec.ts src/components/v2/RailSidebar.spec.ts
```

Expected: PASS。

- [ ] **Step 5: 分别提交**

Agent Runtime:

```bash
git add web/builder/src/lib/shellEvents.ts web/builder/src/lib/shellEvents.test.ts web/builder/src/app/BuilderApp.tsx web/builder/src/app/BuilderApp.test.tsx
git commit -m "feat(builder): notify shell about task actions"
```

aPaaS Builder:

```bash
git add frontend/src/views/CodeConversationPage.vue frontend/src/views/CodeConversationPage.spec.ts
git commit -m "feat(code): react to runtime task events"
```

### Task 14: 收敛旧 Python Engineering Session CLI 的定位

**Files:**
- Modify: `apaas-builder-ai/backend/app/engineering_sessions/paths.py`
- Modify: `apaas-builder-ai/backend/app/engineering_sessions/cli.py`
- Modify: `apaas-builder-ai/backend/app/engineering_sessions/service.py`
- Modify: `apaas-builder-ai/backend/tests/test_engineering_sessions_cli.py`
- Modify: `apaas-builder-ai/backend/tests/test_engineering_sessions_service.py`
- Modify: `apaas-builder-ai/README.md`

- [ ] **Step 1: 写兼容工具边界测试**

断言：

- 默认目录改为 `<repo>/.worktrees`。
- `archive` 默认不 checkpoint。
- CLI 输出包含 `compatibility_mode=true`。
- Code Runtime routes 不导入 `app.engineering_sessions`。
- README 明确该 CLI 只用于独立本地 Git 运维，不是 Builder Code 产品状态源。

- [ ] **Step 2: 确认测试失败**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync/backend
pytest -q tests/test_engineering_sessions_cli.py tests/test_engineering_sessions_service.py tests/test_code_runtime_routes.py
```

Expected: FAIL。

- [ ] **Step 3: 对齐 Superpowers 目录**

`default_worktree_parent` 改为：

```python
def default_worktree_parent(repo_path: str | Path) -> Path:
    control_repo = git_control_worktree(Path(repo_path).resolve())
    return control_repo / ".worktrees"
```

- [ ] **Step 4: 取消自动 checkpoint**

```python
def archive(self, session_id: str, *, checkpoint: bool = False) -> EngineeringSession:
```

CLI 的 `archive` 改为显式 `--checkpoint`，不再使用 `--no-checkpoint` 反向参数。手动 `checkpoint` 命令保留。

- [ ] **Step 5: 写清兼容边界**

README 必须说明：

- 产品会话、任务、队列和 worktree 状态由 Agent Runtime 管理。
- `backend/scripts/agentic_session.py` 不被 Code Runtime 路由调用。
- 兼容 CLI 创建的记录不会自动出现在 Code Rail。
- 不要同时用 CLI 和 Builder Code 操作同一任务分支。

- [ ] **Step 6: 跑测试**

Run:

```bash
pytest -q tests/test_engineering_sessions_cli.py tests/test_engineering_sessions_service.py tests/test_code_runtime_routes.py
```

Expected: PASS。

- [ ] **Step 7: 提交兼容收敛**

Run:

```bash
git add backend/app/engineering_sessions/paths.py backend/app/engineering_sessions/cli.py backend/app/engineering_sessions/service.py backend/tests/test_engineering_sessions_cli.py backend/tests/test_engineering_sessions_service.py README.md
git commit -m "refactor(code): demote legacy engineering session cli"
```

### Task 15: 全链路验证、浏览器验收和故障恢复测试

**Files:**
- Create: `agent-runtime/internal/application/engineering_tasks_e2e_test.go`
- Create: `apaas-builder-ai/backend/tests/test_code_runtime_engineering_tasks_e2e.py`
- Modify: `agent-runtime/README.md`
- Modify: `apaas-builder-ai/README.md`

- [ ] **Step 1: 增加 Runtime E2E 测试**

真实 Git fixture 覆盖：

1. 创建普通 Session，无 `.worktrees` 子目录。
2. 发送只读问题，创建只读 Thread，不产生 worktree。
3. 后续发送修改请求，创建 Task 和 worktree，Thread cwd 切换。
4. 两个不同 Task 并行获取 Turn。
5. 两个 Session 共享 Task，第二个进入队列。
6. Runtime 重建 service 后 reconcile 恢复 Task 和 binding。
7. 归档最后一个 Session 后 Task 保持 retained。
8. merge、keep、discard 安全条件。

- [ ] **Step 2: 增加 aPaaS 代理 E2E 测试**

使用 `httpx.MockTransport` 模拟 Runtime，验证 `202`、`409`、revision 和任务字段不丢失。

- [ ] **Step 3: 跑 Agent Runtime 全量测试**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/agent-runtime/.worktrees/task-engineering-sessions-worktree-sync
go test ./...
cd web/builder
npm test
npm run typecheck
npm run build
```

Expected: PASS。

- [ ] **Step 4: 跑 aPaaS Builder 全量目标测试**

Run:

```bash
cd /mnt/d/workspaces/d-ai-code/worktrees/S-001-engineering-sessions-worktree-sync/backend
pytest -q tests/test_code_runtime_routes.py tests/test_code_runtime_service.py tests/test_code_runtime_engineering_tasks_e2e.py tests/test_engineering_sessions_models.py tests/test_engineering_sessions_git_state.py tests/test_engineering_sessions_registry.py tests/test_engineering_sessions_service.py tests/test_engineering_sessions_cli.py
cd ../frontend
npm test
npm run build
```

Expected: PASS。

- [ ] **Step 5: 启动本地服务并使用 Runtime Preview**

按两仓 README 的本地方式启动后，使用 `agentic-runtime-preview` 获取公开 preview URL。不得向用户返回 `localhost` 或 `127.0.0.1`。

- [ ] **Step 6: Playwright 桌面和移动验收**

验证视口：

```text
1440x900
390x844
```

场景：

- 新建普通会话立即出现在 Rail。
- 普通会话没有 branch/worktree 标识。
- 修改请求显示准备工作区，再进入 task_worktree。
- 执行活动面板桌面停靠且不覆盖对话。
- 移动端全宽 Drawer，无文字和按钮重叠。
- 三个 Tab 正确显示任务、数字员工、Trace。
- 对话流只有 Plan 摘要。
- busy、head changed、worktree failed 均有可操作提示。

若 Chromium 缺失，先运行：

```bash
npm exec -- playwright install chromium
```

- [ ] **Step 7: 验证恢复和清理**

手工停止 Runtime 后重启，确认 Task、Session、worktree、branch、HEAD 和 queue 状态恢复。已合并且 clean 的 worktree只提示清理；dirty 或未合并 worktree不自动删除。

- [ ] **Step 8: 更新 README**

两仓 README 记录：

- 普通会话和工程任务的区别。
- `.worktrees/<task-id>-<slug>` 目录。
- Runtime 状态文件位置。
- reconcile 和错误码排查。
- 归档、完成、保留和放弃语义。
- 本地启动和验证命令。

- [ ] **Step 9: 提交验证和文档**

Agent Runtime:

```bash
git add internal/application/engineering_tasks_e2e_test.go README.md
git commit -m "test(runtime): verify engineering task lifecycle"
```

aPaaS Builder:

```bash
git add backend/tests/test_code_runtime_engineering_tasks_e2e.py README.md
git commit -m "test(code): verify task-aware runtime proxy"
```

### Task 16: 代码审查、同步和双仓收尾

**Files:**
- Review: Agent Runtime 本分支全部改动
- Review: aPaaS Builder 本分支全部改动

- [ ] **Step 1: 使用代码审查技能**

调用 `superpowers:requesting-code-review`，优先检查：

- 主工作区写入逃逸。
- Session path 被 `completeMapping` 覆盖。
- stale revision 丢失。
- 同任务多活跃 Turn。
- 自动 checkpoint、merge、rebase 或删除。
- aPaaS 写入第二套任务状态。
- iframe 内外重复会话和重复任务面板。

- [ ] **Step 2: 修复审查问题并重复目标测试**

每个修复保持仓库和提交边界清晰。

- [ ] **Step 3: 运行最终验证**

Agent Runtime:

```bash
go test ./...
cd web/builder
npm test
npm run typecheck
npm run build
```

aPaaS Builder:

```bash
cd backend
pytest -q tests/test_code_runtime_routes.py tests/test_code_runtime_service.py tests/test_code_runtime_engineering_tasks_e2e.py tests/test_engineering_sessions_models.py tests/test_engineering_sessions_git_state.py tests/test_engineering_sessions_registry.py tests/test_engineering_sessions_service.py tests/test_engineering_sessions_cli.py
cd ../frontend
npm test
npm run build
```

Expected: 全部 PASS。

- [ ] **Step 4: 使用 Agentic Git Sync 完成两仓同步**

分别在两个 worktree 使用 `agentic-git-sync`：

1. 检查 owned paths。
2. 同步上游默认分支。
3. 解决普通 Git 冲突，不覆盖用户改动。
4. 将完成分支集成到默认分支。
5. 推送默认分支。

任何凭据、上游同步或 push 失败都按 blocked 处理，不能声明完成。

- [ ] **Step 5: 收尾 worktree**

Agent Runtime 分支合并并推送后，使用 `superpowers:finishing-a-development-branch` 给出保留或删除 worktree 的选择。默认只提示关闭或删除；未合并、dirty、blocked 的 worktree不删除。

## 验收映射

| Spec 验收项 | 实施任务 |
| --- | --- |
| 普通会话即时创建 | Task 6、Task 11、Task 12 |
| 查询不创建 worktree | Task 5、Task 6、Task 7、Task 15 |
| 明确修改自动升级 | Task 5、Task 7、Task 8 |
| 首次写入保护 | Task 7 |
| 不同任务并行、同任务串行 | Task 5、Task 8、Task 15 |
| 多会话共享任务 | Task 5、Task 8、Task 12 |
| 归档不完成任务 | Task 8、Task 12、Task 15 |
| Runtime 重启恢复 | Task 4、Task 8、Task 15 |
| 只 fetch 和安全快进 | Task 4 |
| 不做文件锁 | Task 3、Task 5 |
| 单一会话导航 | Task 12、Task 13 |
| 单一执行活动面板 | Task 9 |
| 任务、数字员工、Trace 三 Tab | Task 9 |
| Plan 只显示摘要 | Task 9 |
| merge、PR、keep、discard | Task 8、Task 12、Task 15 |
| dirty/未合并 worktree 不清理 | Task 4、Task 8、Task 15 |

## 关键实现约束

- Agent Runtime 是任务状态唯一写入者。
- aPaaS 的 `CodeRuntimeAgentSession` 字段只是投影缓存。
- 现有 Python `engineering_sessions` 只保留为独立兼容 CLI。
- 普通 Session 的 Codex Thread 必须使用只读 sandbox。
- 自动审批不能绕过只读写入保护。
- worktree 初始化失败时禁止回退到主工作区写入。
- 不实现 touched paths、risk areas、文件锁、模块锁或持久化端口锁。
- 不自动 checkpoint、rebase、merge、解决冲突或清理 dirty worktree。
- 主工作区始终保持默认分支，功能分支只在 `.worktrees/` 中实施。
