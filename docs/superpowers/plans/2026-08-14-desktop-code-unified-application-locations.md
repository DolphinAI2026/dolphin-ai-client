# 桌面 Code 统一应用与运行位置实施计划

> **执行约束**：本计划用于后续逐任务实施；本轮只确认范围，不修改正式业务源码。实施时每个任务执行 `RED -> GREEN -> VERIFY -> REVIEW`，只保留能证明核心行为的专项测试。

**目标：** 将当前互斥的“本地应用 / 远程应用”改为统一逻辑应用，并让本机、远程成为应用可用位置；补齐已有项目接入、首次位置选择、会话位置绑定、项目初始化和失效恢复闭环。

**架构：** 本机与远程继续独立请求和独立失败，前端使用稳定关联标识合并为统一应用投影。桌面后端持久化本机位置及其可选远程关联；会话显式记录逻辑应用和运行位置，Runtime 技术目标继续使用现有 `execution_target`，两者不混用。

**技术栈：** Vue 3 + TypeScript + Pinia + Element Plus、FastAPI + SQLAlchemy、Tauri 2、本地 SQLite / 现有服务端数据库、现有 Code Runtime HTTP API。

## 全局约束

- 应用是唯一逻辑对象，本机和远程是位置，不再是互斥应用类型。
- 双位置应用首次打开必须选择位置；只在工作台真正 ready 后记住该应用选择。
- 已记住位置失效时不得静默切换；历史会话也不得迁移到另一位置。
- 本机已有目录不要求 Git，不修改源码、Git、依赖和工程配置。
- 同名应用不得自动合并；仅稳定远程标识或用户明确建立的关联可以合并。
- 本机与远程实际传输、增量同步和冲突合并协议不在本轮实现。
- 现有大文件只保留编排，新增职责必须提取到不超过 500 行的小模块。
- 不回退或覆盖当前 worktree 中已有的未提交修改。

---

## 文件结构与职责

### 新增前端模块

- `frontend/src/components/code/codeApplicationLocations.ts`
  - 定义统一应用、位置、可用性、同步占位状态和合并算法。
- `frontend/src/components/code/codeApplicationLocationPreference.ts`
  - 按远程部署、用户和逻辑应用保存“上次成功打开的位置”。
- `frontend/src/composables/useUnifiedCodeApplications.ts`
  - 并行加载本机/远程位置，分别维护 loading/error/retry，再输出统一列表。
- `frontend/src/components/code/CodeApplicationActions.vue`
  - 仅本机、仅远程、双位置、记忆失效时的主按钮和下拉操作。
- `frontend/src/components/code/CodeApplicationRecoveryPanel.vue`
  - 目录失效、远程不可用、两个位置都不可用和历史会话恢复页面。
- `frontend/src/components/code/AddCodeApplicationMenu.vue`
  - 桌面显示“新建本地项目 / 打开已有项目 / 添加远程应用”，Web 只显示远程入口。

### 新增后端模块

- `backend/app/code_runtime/application_locations.py`
  - 本机位置注册、路径规范化、重复路径、位置可用性和逻辑应用标识。
- `backend/app/code_runtime/session_location.py`
  - 会话运行位置、兼容推导、恢复策略和 rail 分组字段。
- `backend/app/code_runtime/project_initialization.py`
  - 初始化会话创建策略、只读初始化 prompt、确定性 `clientMessageId` 和发送状态。

### 现有大文件只做接线

- `frontend/src/views/Apps.vue`
  - 删除来源互斥状态，接入统一列表 composable 和拆出的操作组件。
- `backend/app/code_runtime/service.py`
  - 保留远程 API 适配；本机位置职责转发到 `application_locations.py`。
- `backend/app/routes/code_runtime.py`
  - 只定义请求/响应和路由接线；会话策略转发到新模块。
- `frontend/src/components/v2/RailSidebar.vue`
  - 只消费统一历史分组，不自行判断 `local-*`。

---

### 任务 1：修正架构事实源和 mapping

**文件：**

- 修改：`docs/solutions/l1/arch/ARCH-20260809-001-desktop-local-ai-cross-platform.md`
- 修改：`docs/assets/application-templates.lock.yaml`
- 参考：`docs/superpowers/specs/2026-07-28-desktop-code-local-remote-application-experience-design.md`

**改动：**

1. 删除“桌面 Code 只能读远程、不得有本地应用/会话”的过期结论。
2. 改成：远程应用元数据仍以远程平台为事实源；桌面可以维护设备侧本机位置和本机运行会话。
3. 冻结三个不同概念：
   - `logical_application_id`：逻辑应用身份。
   - `execution_location`：`local | remote`，会话创建后固定。
   - `execution_target`：现有 Runtime 技术目标，不替代产品位置。
4. 将本设计文档加入 `technical_design_refs`，重新计算 `mapping_digest`。

**完成标准：** mapping 不再与确认原型冲突；后续代码评审可以据此拒绝再次删除本地入口。

---

### 任务 2：建立位置与会话兼容数据契约

**文件：**

- 修改：`backend/app/models/__init__.py`
- 修改：`backend/app/models/ai_chat.py`
- 修改：`backend/app/database.py`
- 创建：`backend/app/code_runtime/application_locations.py`
- 创建：`backend/app/code_runtime/session_location.py`
- 修改：`frontend/src/api/codeRuntime.ts`

**接口：**

```ts
type CodeExecutionLocation = 'local' | 'remote'
type CodeLocationAvailability = 'ready' | 'missing' | 'unreadable' | 'unavailable'

interface CodeApplicationLocation {
  location: CodeExecutionLocation
  location_id: string
  availability: CodeLocationAvailability
  workspace_id?: string | null
  workspace_path?: string | null
  environment_name?: string | null
}

interface UnifiedCodeApplication {
  logical_application_id: string
  app_name: string
  app_code?: string | null
  local?: CodeApplicationLocation
  remote?: CodeApplicationLocation
  association: 'local_only' | 'remote_only' | 'linked'
}
```

**持久化：**

- `registered_workspaces` 增加：
  - `logical_application_id VARCHAR(160) NULL`
  - `linked_remote_application_id VARCHAR(120) NULL`
  - `linked_remote_deployment_id VARCHAR(120) NULL`
- `ai_chat_sessions` 增加：
  - `logical_application_id VARCHAR(160) NULL`
  - `execution_location VARCHAR(16) NULL`
  - `session_purpose VARCHAR(32) NOT NULL DEFAULT 'standard'`
  - `initialization_task_key VARCHAR(120) NULL`
  - `initialization_task_state VARCHAR(24) NULL`

**兼容：**

- 不强制全量迁移旧记录；读取旧会话时按 `external_application_id` 推导位置和临时逻辑 ID，并在下一次写操作补齐。
- 旧 `source=local|remote` 列表接口保留一个兼容周期，新的前端仅把它当作“位置来源请求”。
- `execution_target` 保持现状，不改枚举和已有 Runtime 绑定。

**专项验证：**

```bash
cd backend && pytest -q tests/test_code_runtime_service.py -k "location or execution_target"
```

---

### 任务 3：重做本机项目注册，支持新目录与已有目录

**文件：**

- 修改：`frontend/src/components/code/LocalCodeApplicationDialog.vue`
- 修改：`frontend/src/components/code/localApplicationForm.ts`
- 修改：`frontend/src/api/codeRuntime.ts`
- 修改：`backend/app/routes/code_runtime.py`
- 修改：`backend/app/code_runtime/local_runtime.py`
- 使用：`backend/app/code_runtime/application_locations.py`

**请求契约：**

```json
{
  "app_name": "CRM",
  "app_code": "crm",
  "local_application": true,
  "directory_mode": "new_directory | existing_directory",
  "local_workspace_path": "绝对路径",
  "initialize_project": true,
  "linked_remote_application_id": null
}
```

**行为：**

- `new_directory`：选择父目录，最终路径为 `<父目录>/<应用编码>`；只创建目录，不执行 `git init` 和空提交。
- `existing_directory`：选择项目目录本身；允许非空、非 Git 目录，只要求存在、是目录且可读。
- 规范化绝对路径后检查重复；同一用户重复选择同一路径返回既有应用和 `already_registered=true`。
- 其他用户或其他应用占用同一路径时返回明确错误，不覆盖绑定。
- 对已有目录默认勾选“初始化项目”；对新项目默认不自动扫描空目录。

**错误码：**

- `LOCAL_APPLICATION_PATH_NOT_ABSOLUTE`
- `LOCAL_APPLICATION_PATH_NOT_FOUND`
- `LOCAL_APPLICATION_PATH_NOT_DIRECTORY`
- `LOCAL_APPLICATION_PATH_UNREADABLE`
- `LOCAL_APPLICATION_PATH_ALREADY_BOUND`

**专项验证：**

```bash
cd frontend && npm test -- LocalCodeApplicationDialog.spec.ts
cd backend && pytest -q tests/test_code_runtime_local_runtime.py -k "register_existing or duplicate_path or non_git"
```

---

### 任务 4：统一应用列表和首次位置选择

**文件：**

- 创建：`frontend/src/components/code/codeApplicationLocations.ts`
- 创建：`frontend/src/components/code/codeApplicationLocationPreference.ts`
- 创建：`frontend/src/composables/useUnifiedCodeApplications.ts`
- 创建：`frontend/src/components/code/CodeApplicationActions.vue`
- 创建：`frontend/src/components/code/AddCodeApplicationMenu.vue`
- 修改：`frontend/src/stores/codeApplications.ts`
- 修改：`frontend/src/views/Apps.vue`

**行为：**

1. 桌面端并行请求本机和远程；Web 只请求远程。
2. 只按以下规则合并：
   - 本机记录含稳定 `linked_remote_application_id`；或
   - 两端返回相同稳定 `logical_application_id`。
3. 同名但无关联的记录保持两条，禁止猜测合并。
4. 旧“本地应用 / 远程应用”分段控件替换为 `全部 / 本机可用 / 远程可用`筛选。
5. 仅本机或仅远程直接打开；双位置且没有有效记忆时弹一次轻量位置选择。
6. 位置选择只在 `builder.ready` 后写入；创建会话或 iframe 尚未 ready 不算成功。
7. 本机失败不清空远程列表，远程失败不清空本机列表；重试只重试失败来源。

**兼容：**

- 旧 `dolphin-code-application-source-v1` 只用于一次性迁移提示，不再决定列表和打开位置。
- 新记忆键按 `deployment + user + logical_application_id` 隔离，避免不同环境串用。

**专项验证：**

```bash
cd frontend && npm test -- codeApplicationLocations.spec.ts codeApplicationLocationPreference.spec.ts codeApplications.spec.ts
```

---

### 任务 5：让会话固定绑定运行位置并支持恢复策略

**文件：**

- 修改：`backend/app/routes/code_runtime.py`
- 使用：`backend/app/code_runtime/session_location.py`
- 修改：`frontend/src/api/codeRuntime.ts`
- 修改：`frontend/src/views/CodeConversationPage.vue`
- 创建：`frontend/src/components/code/CodeApplicationRecoveryPanel.vue`

**会话请求：**

```ts
interface CreateCodeSessionFromApplicationRequest {
  logical_application_id: string
  external_application_id: string
  execution_location: 'local' | 'remote'
  session_policy: 'resume_recent' | 'create_new'
  session_purpose: 'standard' | 'project_initialization' | 'project_recheck'
  app_name?: string
  app_code?: string
}
```

**行为：**

- 普通打开只恢复“同一逻辑应用 + 同一运行位置”的最近会话。
- 当前会话运行期间不能切换位置；换位置会回到应用入口并创建/恢复另一位置会话。
- 历史会话的原位置失效时返回恢复状态，不创建另一位置会话。
- 双位置应用的记忆位置失效时先展示原因，再由用户选择恢复原位置或明确打开另一位置。
- 两个位置都不可用时保留应用和会话，显示恢复页。

**错误码：**

- `CODE_APPLICATION_LOCATION_REQUIRED`
- `CODE_APPLICATION_LOCATION_UNAVAILABLE`
- `CODE_APPLICATION_LOCAL_LOCATION_MISSING`
- `CODE_APPLICATION_REMOTE_LOCATION_UNAVAILABLE`
- `CODE_APPLICATION_ALL_LOCATIONS_UNAVAILABLE`

**专项验证：**

```bash
cd backend && pytest -q tests/test_code_runtime_routes.py -k "session_location or resume_recent or location_unavailable"
cd frontend && npm test -- CodeConversationPage.spec.ts codeApplicationLocations.spec.ts
```

---

### 任务 6：首次已有项目接入后创建并发送项目初始化会话

**文件：**

- 创建：`backend/app/code_runtime/project_initialization.py`
- 修改：`backend/app/routes/code_runtime.py`
- 修改：`frontend/src/api/codeRuntime.ts`
- 修改：`frontend/src/views/CodeConversationPage.vue`

**后端接口：**

```text
POST /api/code/sessions/{session_ref}/project-initialization/dispatch
```

**行为：**

1. 注册已有项目后创建标题为“项目初始化”的新 shell 会话，不复用普通最近会话。
2. `session_purpose=project_initialization`；重复进入未完成初始化时恢复该会话。
3. `CodeConversationPage` 收到可信 `builder.ready` 后调用 dispatch 接口。
4. 后端通过现有 Runtime API：

```text
POST /api/agent/sessions/{runtime_session_id}/messages
```

发送只读初始化 prompt，并携带确定性 `clientMessageId`。重复调用使用同一 ID，由 Runtime 幂等去重。
5. prompt 明确只允许读取项目结构、说明、常见清单、Git 状态和环境可用性；禁止安装、构建、启动和文件写入。
6. 识别失败只标记初始化失败，不删除应用、位置或会话；用户可在原会话重试。

**返回：**

```json
{
  "state": "sent | already_sent | retryable_failed",
  "session_id": "...",
  "client_message_id": "msg_project_init_<digest>"
}
```

**专项验证：**

```bash
cd backend && pytest -q tests/test_code_runtime_routes.py -k "project_initialization"
cd frontend && npm test -- CodeConversationPage.spec.ts -t "project initialization"
```

---

### 任务 7：统一侧边栏会话分组和位置展示

**文件：**

- 修改：`backend/app/routes/code_runtime.py`
- 修改：`frontend/src/api/codeRuntime.ts`
- 修改：`frontend/src/components/v2/RailSidebar.vue`
- 修改：`frontend/src/components/v2/SystemAssistantSessionSections.vue`
- 修改：`frontend/src/views/CodeConversationPage.vue`

**行为：**

- rail history 返回 `logical_application_id` 和每条会话的 `execution_location`。
- 侧边栏按逻辑应用分组，不再按旧来源开关只展示一半历史。
- 应用组显示位置标签；会话项显示其固定运行位置。
- 没有本机位置时不显示可点击的“本机打开”。
- 输入框附近显示 `本机 · <目录末级>` 或 `远程 · <环境>`。
- 折叠、切换和刷新只更新数据，不重新打开已就绪 iframe。

**专项验证：**

```bash
cd frontend && npm test -- RailSidebar.spec.ts CodeConversationPage.spec.ts
cd backend && pytest -q tests/test_code_runtime_routes.py -k "rail_history and logical_application"
```

---

### 任务 8：聚焦集成验证和桌面三平台兼容检查

**不新增大范围测试套件。只执行：**

```bash
cd frontend && npm test -- \
  LocalCodeApplicationDialog.spec.ts \
  codeApplicationLocations.spec.ts \
  codeApplicationLocationPreference.spec.ts \
  codeApplications.spec.ts \
  RailSidebar.spec.ts \
  CodeConversationPage.spec.ts

cd frontend && npm run build:desktop

cd backend && pytest -q \
  tests/test_code_runtime_local_runtime.py \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py \
  -k "application_location or register_existing or session_location or project_initialization or rail_history"

cd src-tauri && cargo check
```

**桌面人工主路径：**

1. Windows 选择一个非 Git、非空已有目录，确认不弹命令行、不修改目录内容，并进入“项目初始化”会话。
2. 同一路径再次接入，确认复用应用，不重复创建初始化任务。
3. 双位置应用首次打开选择远程，ready 后退出再进入，确认按应用记忆远程。
4. 让已记住位置不可用，确认不会静默切到另一位置。
5. 远程接口失败时本机应用仍显示；本机路径失效时远程应用仍可打开。
6. Linux/macOS 至少执行目录选择、路径规范化和 `cargo check`；平台包验证沿用现有构建脚本，不引入第二套 Runtime。

---

## 实施顺序与提交边界

1. 先完成任务 1，消除架构冲突。
2. 任务 2、3 完成后，本机已有项目接入可独立验收。
3. 任务 4、5 完成后，统一列表和位置选择可独立验收。
4. 任务 6 完成后，项目初始化闭环可独立验收。
5. 任务 7、8 收口会话导航、恢复和三平台兼容。

每个任务单独 review；任何任务发现需要实现真实本机/远程内容同步时立即停止，该内容必须另立协议，不得塞入本轮。

## 主要风险与处理

| 风险 | 处理 |
| --- | --- |
| 现有架构文档再次驱动代码删除本地入口 | 任务 1 先修正事实源和 mapping，代码评审绑定新 digest |
| 仅按应用名合并造成误关联 | 只接受稳定 ID 或明确关联字段 |
| 旧会话没有位置字段 | 读取时兼容推导，写时补齐，不做破坏性全表迁移 |
| 初始化 prompt 重复发送 | 确定性 `clientMessageId` + 后端状态；仅在 `builder.ready` 后发送 |
| 本机路径失效导致自动打开远程 | 显式恢复页，禁止静默 fallback |
| `Apps.vue`、`service.py`、`code_runtime.py` 继续膨胀 | 新职责放入小模块，大文件只接线 |
| 当前 worktree 存在大量既有修改 | 实施前逐文件核对 diff，只叠加，不回退用户改动 |

## 本轮明确不做

- 本机与远程副本内容传输。
- Git push/pull 作为同步实现。
- 增量同步、冲突合并和自动覆盖方向。
- 自动安装依赖、自动构建、自动测试或自动启动项目。
- 重写 Code 内层编辑器和 Agent Runtime。
