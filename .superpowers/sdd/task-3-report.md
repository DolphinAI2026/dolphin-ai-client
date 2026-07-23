# Task 3 Report: Python 本地 Runtime 编排与第二轮安全修复

## 改动文件

- `backend/app/code_runtime/local_runtime.py`
- `backend/tests/test_code_runtime_local_runtime.py`
- `.superpowers/sdd/task-3-report.md`

未修改 service、frontend、Rust、agent-runtime 或
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
- `runtime_scope_id` 由 `tenant_id + user_id + application_id` 的稳定摘要生成，
  用于本地目录、Python/OS 锁和 manager status/start；产品 `application_id`
  保留为独立 RuntimeContext 字段。不同用户的同名应用不会复用 Runtime、Codex
  Home 或模型文件。
- status 按 `runtime_scope_id` 查询当前活跃 Runtime。`starting` 仅有界轮询，
  只有 `ready` 才返回 Builder URL；没有活跃实例时在 scope OS 锁内二次查询后生成
  新的 `local-<uuid>` 实例代际并 start。
- start JSON 锁定为：
  `runtime_scope_id`、`application_id`、`sandbox_instance_id`、`workspace_id`、
  `worktree_path`、`git_common_dir`、`codex_home`、`runtime_dir`、
  `runtime_context_path`、`agent_runtime_path`、`runtime_addr`、
  `environment`。
- POST/status 只接受 HTTP 200；最终 start 只接受 `state=ready`。manager/runtime
  URL 必须是端口 `1..65535` 的 loopback HTTP，Runtime base URL 只能为根路径，
  Builder URL 解码规范化后必须严格位于 `/builder/`，拒绝点段、编码点段、反斜杠
  和控制字符。
- 外部应用绑定使用最多两条结果判断；多个 owned 绑定返回稳定 409，多个
  foreign 绑定返回 403，不再触发 `MultipleResultsFound`。
- 注册工作区路径必须是规范绝对文本路径；拒绝 `.`/`..`、重复分隔符、
  尾部分隔符、symlink、非 Git 目录和仓库子目录。
- desktop data 根必须已存在、规范且不是 symlink。其下目录、锁文件和 JSON 全部
  使用 `dir_fd + O_NOFOLLOW`；JSON 在同目录 FD 内临时写入、文件 fsync、
  rename 和父目录 fsync，避免 symlink 把模型 token 写到受管目录外。目录为
  0700，runtime context、model provider、CI provider 和锁文件为 0600。
- 模型 provider 身份是应用 Runtime 级约束，包含 provider、规范 base URL 和
  token。首次启动写入同一身份下可用 Coding 模型；后续 Conversation 选择不兼容
  provider 返回 `409/LOCAL_RUNTIME_MODEL_PROVIDER_CONFLICT`，不静默沿用首个
  会话配置。
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
59 passed, 215 warnings in 10.69s
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

- 本轮安全修复提交：待本轮验证后统一提交。

## 遗留关注点

- 本轮已将实例代际与 Engineering Session 解耦：同一活跃 Runtime 可被多个
  Conversation 复用，但每次真实 restart 使用新的 `sandbox_instance_id`。
- 端口分配释放后的抢占窗口由 Task 4 manager 的同步 start 失败语义处理，
  Python 未保留 socket，也未启动 agent-runtime 或 MXC。
- Task 4 必须实现按 `runtime_scope_id` 的 status、journal 和 OS 锁，并提供真实
  MXC + agent-runtime 的端到端证据。
- 测试中的 `datetime.utcnow()` 弃用警告来自既有 SQLAlchemy/Jose 代码，
  未在本任务范围内修改。
