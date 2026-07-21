# Task 3 Report: Python 本地 Runtime 编排审查修复

## 改动文件

- `backend/app/code_runtime/local_runtime.py`
- `backend/tests/test_code_runtime_local_runtime.py`
- `.superpowers/sdd/task-3-report.md`

未修改 routes、service、frontend、Rust、agent-runtime 或
`open_code_session`。

## 修复摘要

- `runtime-context.json` 的 `repoUrl` 优先使用同租户、同用户的
  `WorkspaceGitRemote.remote_url`，且仅接受无凭据 HTTPS URL；无绑定时使用
  `https://local.invalid/<application-id>.git`，不再写入本地工作区路径。
- 首次 start 前通过
  `resolve_llm_config(..., purpose="coding", selected_config_id=...)`
  解析模型。无配置返回
  `409/LOCAL_RUNTIME_MODEL_PROVIDER_REQUIRED`；原子写入 0600 的
  `model-provider.json`，并通过 `APAAS_MODEL_PROVIDER_PATH` 传给 manager。
- 为 `local_fixture` 原子写入 0600 的应用私有 `ci-provider.json`，使用
  `provider=mock`、`example.invalid` 地址和固定非真实 token，并设置
  `APAAS_CI_PROVIDER_PATH`。这是 Phase L1 本地 CI fixture，不是线上 CI
  成功证据，也不伪装 GitLab 凭据。
- manager URL 仅允许 `http://127.0.0.1:<port>`，拒绝 userinfo、HTTPS、
  非 loopback host、路径、query、fragment 和缺失端口，避免 Bearer token
  发往外部地址。
- 先确保应用级 Engineering Session，再 GET status。`ready/starting`
  直接复用，不创建目录、不分配端口、不解析模型、不覆盖配置；仅 404 时在
  应用锁内复查并执行一次 start。
- `sandbox_instance_id` 固定为
  `local-<engineering-session-id-lower>`，并执行安全组件及 160 字符上限校验。
- start JSON 锁定为：
  `application_id`、`sandbox_instance_id`、`workspace_id`、
  `worktree_path`、`git_common_dir`、`codex_home`、`runtime_dir`、
  `runtime_context_path`、`agent_runtime_path`、`runtime_addr`、
  `environment`。
- POST start 只接受 `state=ready`。`runtime_base_url` 必须为 loopback
  HTTP，`builder_url` 必须同 origin 且位于 `/builder/`。
- 外部应用绑定使用最多两条结果判断；多个 owned 绑定返回稳定 409，多个
  foreign 绑定返回 403，不再触发 `MultipleResultsFound`。
- 注册工作区路径必须是规范绝对文本路径；拒绝 `.`/`..`、重复分隔符、
  尾部分隔符、symlink、非 Git 目录和仓库子目录。
- desktop data、应用 runtime、Codex 目录权限为 0700；runtime context、
  model provider、CI provider 文件权限为 0600。mkdir、resolve、write、
  socket 和模型解析失败均映射为稳定、脱敏的 `HTTPException`。
- manager 网络/非 JSON/401/403/409/5xx 和无效响应均使用稳定错误语义，
  不返回 manager 正文、Bearer token、模型 token 或环境凭据。

## TDD 证据

### RED

审查场景加入后运行 focused suite：

```bash
cd backend
.venv/bin/pytest tests/test_code_runtime_local_runtime.py -q
```

输出：

```text
37 failed, 12 passed, 170 warnings in 7.65s
```

失败覆盖旧 instance/payload、404 前写文件、本地 `repoUrl`、缺模型/CI、
manager URL 未限环回、重复绑定、路径 alias、start 状态/URL 未校验和错误
未脱敏。

补齐 resolve 错误门禁时的定向 RED：

```text
1 failed, 4 passed, 45 deselected
```

首个失败是 desktop data 符号链接循环抛出裸 `RuntimeError`，随后最小修复为
`503/LOCAL_RUNTIME_PREPARATION_FAILED`。

### GREEN

Focused：

```bash
cd backend
.venv/bin/pytest tests/test_code_runtime_local_runtime.py -q
```

输出：

```text
50 passed, 174 warnings in 6.32s
```

直接关联回归：

```bash
cd backend
.venv/bin/pytest tests/test_engineering_sessions_service.py \
  tests/test_code_runtime_service.py -q
```

输出：

```text
236 passed, 73 warnings in 58.73s
```

补充验证：

```bash
.venv/bin/python -m py_compile \
  app/code_runtime/local_runtime.py \
  tests/test_code_runtime_local_runtime.py
git diff --check
```

均以退出码 `0` 完成。

## 提交

- 修复提交：
  `95ab70b06a5dcc735f84c9d39b5a20797adaebc1`
- 提交信息：`fix: harden local runtime preparation`

## 遗留关注点

- 本轮遵循 Task 3 brief：实例 ID 从稳定的应用级 Engineering Session
  身份派生，同一应用多个 Conversation 复用同一实例。
- 设计 spec 另有“每次 Runtime restart 使用新 sandbox_instance_id”的要求。
  本任务未自行引入代际存储；该跨文档差异留给 Task 4 或最终审查处理。
- 端口分配释放后的抢占窗口由 Task 4 manager 的同步 start 失败语义处理，
  Python 未保留 socket，也未启动 agent-runtime 或 MXC。
- 测试中的 `datetime.utcnow()` 弃用警告来自既有 SQLAlchemy/Jose 代码，
  未在本任务范围内修改。
