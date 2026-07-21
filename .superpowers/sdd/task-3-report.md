# Task 3 Report: Python 本地 Runtime 编排

## 改动文件

- `backend/app/code_runtime/local_runtime.py`
- `backend/tests/test_code_runtime_local_runtime.py`
- `.superpowers/sdd/task-3-report.md`

## 实现摘要

- 新增 `LocalRuntimeClient`，将现有 Code session、`RegisteredWorkspace` 和
  `EngineeringSessionService.ensure_application_session(...)` 转换为 desktop Runtime
  manager 的明确 status/start 请求。
- 按 `session.workspace_id`、内部 `Application.source_workspace_id`、外部
  `RegisteredWorkspace.apaas_app_id` 的顺序解析工作区，并严格以
  `ws_id + tenant_id + user_id` 查询。未绑定返回
  `409/LOCAL_APPLICATION_WORKSPACE_REQUIRED`，其他用户工作区返回
  `403/LOCAL_APPLICATION_WORKSPACE_FORBIDDEN`。
- 工作区必须是存在的 Git 顶层目录且与登记的 `abs_path` 完全一致；拒绝普通目录、
  仓库子目录和 symlink 别名。
- 应用身份优先 `session.app_id`，否则 `session.external_application_id`；空值或
  非安全路径组件返回 `400/LOCAL_APPLICATION_ID_INVALID`。
- `sandbox_instance_id` 由应用级 Engineering Session 的稳定 `id` 派生；同一应用的
  多个 Conversation 查询并复用同一个 `ready` 或 `starting` 实例。
- manager 使用 Bearer 认证，并遵循：
  `GET /v1/local-runtime/instances/{application_id}/{sandbox_instance_id}`，
  只有 404 才 `POST /v1/local-runtime/instances/start`。冲突和其它异常不会生成新实例。
- start JSON 使用 snake_case，携带 application/instance 身份、managed worktree、
  Git common dir、Codex Home、runtime dir、runtime context 路径、agent-runtime 路径、
  loopback runtime address 和显式环境变量 allowlist。
- runtime context 使用受控目录内的原子文件替换写入；Python 不启动
  agent-runtime 或 MXC。
- `LocalRuntimeClient.from_environment()` 读取四个 `DOLPHIN_*` 变量；缺失配置返回
  `503/LOCAL_RUNTIME_MANAGER_UNAVAILABLE`。显式构造可注入 URL、token、路径、
  HTTP client 和 Engineering Session service，单测不依赖无关环境。

## RED 证据

命令：

```bash
cd backend
.venv/bin/pytest tests/test_code_runtime_local_runtime.py -q
```

输出：

```text
ModuleNotFoundError: No module named 'app.code_runtime.local_runtime'
1 error in 0.46s
```

补充路径门禁 RED：

```bash
cd backend
.venv/bin/pytest tests/test_code_runtime_local_runtime.py::test_open_rejects_symlinked_repository_alias -q
```

输出：

```text
1 failed
```

失败证明 symlink 注册路径此前会被解析后错误接受，而不是与 Git 顶层的登记
`abs_path` 精确比较。

## GREEN 证据

新增模块：

```bash
cd backend
.venv/bin/pytest tests/test_code_runtime_local_runtime.py -q
```

输出：

```text
16 passed, 68 warnings in 2.61s
```

关联既有模块：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py tests/test_code_runtime_service.py -q
```

输出：

```text
236 passed, 73 warnings in 57.87s
```

编译与空白检查：

```bash
cd backend
.venv/bin/python -m py_compile app/code_runtime/local_runtime.py
git diff --check --no-index /dev/null ../backend/app/code_runtime/local_runtime.py
git diff --check --no-index /dev/null ../backend/tests/test_code_runtime_local_runtime.py
```

输出：退出码 `0`。

## 提交

- Task 3 代码提交：`78d0f6ff88fe45edf646b39013578fcafbef6e57`
- 提交信息：`feat: prepare local application runtimes`

## 遗留关注点

- 本任务未接入现有 open route，也未修改 service/routes；该集成留给 Task 5。
- Rust manager 的状态机、路径二次校验、journal、MXC 启停仍属于 Task 4，尚未实现。
- 测试中的 `datetime.utcnow()` 弃用警告来自既有 SQLAlchemy/Jose 模型代码，未在本任务范围内修改。
