# Desktop Code Local and Remote Application Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让桌面 Code 用户通过一个弹窗创建可持久化的本地应用项目，在独立的本地/远程分区中管理应用，并通过可诊断、可恢复的本地 Runtime 启动流程直接进入工作台。

**Architecture:** 本地应用继续以 `RegisteredWorkspace` 为唯一持久化记录，使用 `workspace_type=code-local-application`、`apaas_app_id=local-*`、`display_name` 和项目目录 basename 恢复应用元数据，不增加新表。前端按 `source=local|remote` 独立加载列表，桌面显示分段控件，Web 固定远程；本地工作台打开期间轮询轻量状态接口并复用现有同步 open 请求。

**Tech Stack:** Vue 3、Element Plus、Pinia、Vite desktop build、FastAPI、SQLAlchemy、Tauri local runtime manager、Vitest、pytest。

## Global Constraints

- 本地创建、列表、会话打开、状态查询和恢复不得调用 Code Control Plane。
- Web/远程部署不得显示或请求本地应用能力。
- 应用编码创建前可编辑，创建后永久只读；一个本地应用对应一个项目目录。
- 不增加应用详情页、创建向导、第二次确认弹窗或未实现的转换入口。
- 不使用 mock 代替最终 Windows 桌面 Runtime 验收。
- 保留主工作区现有未提交修改，只在任务 worktree 中写入。

---

### Task 1: 本地应用持久化与来源隔离

**Files:**
- Modify: `backend/app/code_runtime/local_runtime.py`
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/app/routes/code_runtime.py`
- Test: `backend/tests/test_code_runtime_service.py`
- Test: `backend/tests/test_code_runtime_routes.py`

**Interfaces:**
- Consumes: `RegisteredWorkspace`、`AuthContext`、`default_local_workspace_root()`。
- Produces: `GET /api/code/applications?source=local|remote`、扩展后的默认目录和本地应用 create/list 合同。

- [ ] **Step 1: 写失败测试**

本地列表测试创建当前用户和其他用户的 workspace，断言只返回当前用户的 `local-*` 应用，且名称、编码、目录和时间可以从 DB 恢复。路由测试把 `_control_plane_request_auth` monkeypatch 为抛错，确认 `source=local` 的 list/create 仍成功，`source=remote` 仍调用远程认证。

- [ ] **Step 2: 运行测试确认失败**

```bash
backend/venv/bin/python -m pytest -q backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py -k 'local_application_list or local_application_route or local_application_create'
```

Expected: FAIL，因为当前本地 list 返回空、路由在分流前请求远程认证。

- [ ] **Step 3: 实现本地持久化恢复**

`ensure_registered_local_workspace()` 把本地应用记录写为 `workspace_type="code-local-application"`，保留原始 `display_name`，并绑定 `apaas_app_id=local-*`。本地列表按当前 `tenant_id`、`user_id` 和 `apaas_app_id LIKE 'local-%'` 查询；兼容此前 `workspace_type=external` 的本地记录。编码来自 `Path(abs_path).name`，名称来自 `display_name`。

`list_code_applications()` 增加 `source: Literal["local", "remote"] = "remote"`、`db` 和 `ctx`。local 分支只查 DB，remote 分支保留现有 Control Plane 行为。路由判断 source 或 `local_application` 后才获取远程认证。

默认目录接口返回：

```json
{"workspace_root":"<desktop-data>/workspaces","workspace_path":"<desktop-data>/workspaces/<app-code>"}
```

- [ ] **Step 4: 运行测试并提交**

```bash
backend/venv/bin/python -m pytest -q backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py -k 'code_application'
git add backend/app/code_runtime/local_runtime.py backend/app/code_runtime/service.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py
git commit -m "feat(code): persist and list local applications"
```

Expected: PASS，本地与远程认证边界均被覆盖。

### Task 2: 单弹窗创建与本地/远程应用分区

**Files:**
- Create: `frontend/src/components/code/LocalCodeApplicationDialog.vue`
- Test: `frontend/src/components/code/LocalCodeApplicationDialog.spec.ts`
- Modify: `frontend/src/api/codeRuntime.ts`
- Modify: `frontend/src/stores/codeApplications.ts`
- Test: `frontend/src/stores/codeApplications.spec.ts`
- Modify: `frontend/src/stores/mode.ts`
- Test: `frontend/src/stores/mode.spec.ts`
- Modify: `frontend/src/views/Apps.vue`
- Test: `frontend/src/views/Apps.codeMode.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `source` list 参数和 `{workspace_root, workspace_path}` 默认目录。
- Produces: `LocalCodeApplicationDialog` 的 `created` 事件、桌面 `local|remote` 分段状态。

- [ ] **Step 1: 写失败测试**

组件测试断言名称生成编码、编码可手改、系统目录选择器只选择父目录、最终路径为 `<父目录>/<编码>`，提交体包含 `local_application: true` 和完整 `local_workspace_path`。页面测试覆盖桌面分段、首次默认 local、切换后分别发送 source；Web 只请求 remote。模式测试断言左栏不再包含泛化 `c-new`。

- [ ] **Step 2: 运行测试确认失败**

```bash
npm run test -- src/components/code/LocalCodeApplicationDialog.spec.ts src/views/Apps.codeMode.spec.ts src/stores/codeApplications.spec.ts src/stores/mode.spec.ts
```

Expected: FAIL，因为组件、source 参数和分段状态尚不存在。

- [ ] **Step 3: 实现 API、缓存和单弹窗**

新增 `CodeApplicationSource = 'local' | 'remote'`；`listApplications` 接受 source，`CodeApplication.source` 接受 `desktop-local | d-ai-code`，Pinia cache key 纳入 source。

弹窗只维护名称、自动编码、编码是否手改、保存位置和提交中。编码按现有 slug 规则生成并限制为 50 字符；`pickDirectory('选择本地应用保存位置')` 只选择父目录。字段固定为应用名称、应用编码、保存位置和只读最终项目目录，操作固定为取消、创建并打开。

- [ ] **Step 4: 实现应用页分区**

桌面读取 `localStorage['dolphin-code-application-source-v1']`，缺省 local；Web 固定 remote。切换时独立刷新对应 source。本地列表显示本地标签和截断目录；远程列表显示远程标签与原状态。远程失败只渲染分区内错误和重试。左栏只保留新建本地应用和我的应用。

- [ ] **Step 5: 运行验证并提交**

```bash
npm run test -- src/components/code/LocalCodeApplicationDialog.spec.ts src/views/Apps.codeMode.spec.ts src/stores/codeApplications.spec.ts src/stores/mode.spec.ts src/utils/desktop/guard.spec.ts
npm run build:desktop
git add frontend/src/components/code frontend/src/api/codeRuntime.ts frontend/src/stores/codeApplications.ts frontend/src/stores/codeApplications.spec.ts frontend/src/stores/mode.ts frontend/src/stores/mode.spec.ts frontend/src/views/Apps.vue frontend/src/views/Apps.codeMode.spec.ts
git commit -m "feat(code): add local application creation flow"
```

Expected: 测试和 desktop build 通过，业务组件没有直接导入 `@tauri-apps/*`。

### Task 3: Runtime 启动阶段与恢复动作

**Files:**
- Create: `frontend/src/components/code/CodeWorkspaceOpening.vue`
- Test: `frontend/src/components/code/CodeWorkspaceOpening.spec.ts`
- Modify: `frontend/src/api/codeRuntime.ts`
- Modify: `frontend/src/views/CodeConversationPage.vue`
- Test: `frontend/src/views/CodeConversationPage.spec.ts`
- Modify: `backend/app/code_runtime/local_runtime.py`
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/app/routes/code_runtime.py`
- Test: `backend/tests/test_code_runtime_local_runtime.py`
- Test: `backend/tests/test_code_runtime_routes.py`

**Interfaces:**
- Consumes: 本地 Code session 和 Tauri manager 的 GET/DELETE instance API。
- Produces: `GET /api/code/sessions/{session_ref}/open-status`、`POST /api/code/sessions/{session_ref}/local-runtime/restart`、`PATCH /api/code/sessions/{session_ref}/local-workspace`。

- [ ] **Step 1: 写失败测试**

后端测试覆盖 status 的 `checking_project | starting_runtime | opening_workbench`，local status/restart/rebind 不调用远程认证，非法 workspace 在 manager 不可用时仍先返回 `409 LOCAL_APPLICATION_WORKSPACE_INVALID`。前端测试覆盖三阶段、累计耗时、轮询停止和按错误码显示恢复动作。

- [ ] **Step 2: 运行测试确认失败**

```bash
backend/venv/bin/python -m pytest -q backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_routes.py -k 'open_status or restart or rebind or unmanaged_workspace'
npm run test -- src/components/code/CodeWorkspaceOpening.spec.ts src/views/CodeConversationPage.spec.ts
```

Expected: FAIL，因为状态和恢复接口尚不存在，当前 fast path 先探测 manager。

- [ ] **Step 3: 修复 fast path 并提供状态**

`open_application_with_entry_token()` 先用 `resolve_registered_workspace(..., validate_git=False)` 和 `_validate_workspace_path()` 校验 workspace，再查询 manager。warm open 复用已验证 workspace；cold path 才做完整 Git/session 准备。

`application_open_status()` 单次查询 manager：404 返回 checking_project，starting 返回 starting_runtime，ready 返回 opening_workbench，不进入 `_existing_status()` 等待循环。manager starting 的硬预算由 30 秒改为可配置的 120 秒，其他非预期状态立即失败。

- [ ] **Step 4: 实现最小恢复动作**

restart 调用 manager `DELETE /v1/local-runtime/instances/{runtime_scope_id}`，前端随后重试 open。rebind 接受完整项目目录，复用 workspace helper 初始化 Git并更新当前 local application 记录，应用 ID 和编码保持不变。

- [ ] **Step 5: 实现工作台启动层**

`CodeWorkspaceOpening` 接受 phase、startedAt、error、canRestart 和 canRebind。`CodeConversationPage` 在本地 open 请求期间每 500ms 轮询；请求完成并排队 iframe 后切到 opening，收到 `builder.ready` 后卸载。错误留在当前页面，提供重试、返回列表、重启环境或重新选择目录，技术详情默认折叠。

- [ ] **Step 6: 运行验证并提交**

```bash
backend/venv/bin/python -m pytest -q backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py
npm run test -- src/components/code/CodeWorkspaceOpening.spec.ts src/views/CodeConversationPage.spec.ts src/views/codeFrameLifecycle.spec.ts
git add frontend/src/components/code/CodeWorkspaceOpening.vue frontend/src/components/code/CodeWorkspaceOpening.spec.ts frontend/src/api/codeRuntime.ts frontend/src/views/CodeConversationPage.vue frontend/src/views/CodeConversationPage.spec.ts backend/app/code_runtime/local_runtime.py backend/app/code_runtime/service.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_routes.py
git commit -m "fix(code): expose recoverable local runtime startup"
```

Expected: PASS；warm path 不做 Git 准备，错误优先级和恢复按钮正确。

### Task 4: 桌面构建与真实 Windows 验收

**Files:**
- Build: `frontend/dist/`
- Build: `backend/dist/ruijing-sidecar.exe`
- Deploy: `C:\Users\Administrator\dolphin-code-win\ruijing-sidecar.exe`

**Interfaces:**
- Consumes: Tasks 1-3 的 desktop bundle 和 sidecar。
- Produces: 可直接试用的 Windows 桌面客户端。

- [ ] **Step 1: 运行完整定向验证**

```bash
backend/venv/bin/python -m pytest -q backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_routes.py
npm run test -- src/views/Apps.codeMode.spec.ts src/components/code/LocalCodeApplicationDialog.spec.ts src/components/code/CodeWorkspaceOpening.spec.ts src/views/CodeConversationPage.spec.ts src/stores/codeApplications.spec.ts src/stores/mode.spec.ts src/utils/desktop/guard.spec.ts
npm run build:desktop
```

- [ ] **Step 2: 构建和替换 Windows sidecar**

```powershell
Set-Location "D:\workspaces\d-ai-code\apaas-builder-ai\backend"
& "C:\tmp\ruijing-sidecar-build-py312\Scripts\python.exe" -m PyInstaller ruijing-sidecar.spec --noconfirm
Get-Process app,ruijing-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force
Copy-Item "D:\workspaces\d-ai-code\apaas-builder-ai\backend\dist\ruijing-sidecar.exe" "C:\Users\Administrator\dolphin-code-win\ruijing-sidecar.exe" -Force
Start-Process "C:\Users\Administrator\dolphin-code-win\app.exe"
```

- [ ] **Step 3: 执行真实交互验收**

确认桌面首次默认本地；用一个弹窗创建应用并使用系统目录选择器；创建后直接进入工作台；重启客户端后应用仍存在；再次打开 warm open 明显更快。切到远程并模拟不可用，本地分区仍正常。

Expected: 不出现命令行窗口、登录循环、持续重连、空白页、`LOCAL_APPLICATION_WORKSPACE_REQUIRED`、错误覆盖后的 `LOCAL_RUNTIME_MANAGER_UNAVAILABLE` 或固定 30 秒伪超时。

---

## Self-Review

- Spec coverage: Tasks 1-4 覆盖独立分区、单弹窗、持久化、直接打开、启动阶段、恢复动作、性能和 Windows E2E。
- Placeholder scan: 无待定步骤或未定义接口。
- Type consistency: `source=local|remote`、`phase=checking_project|starting_runtime|opening_workbench`、`local_workspace_path` 在前后端一致。
