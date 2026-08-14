# 任务 6：已有项目初始化会话派发报告

## 实现

- 新增 `backend/app/code_runtime/project_initialization.py`：生成稳定且符合 Runtime 约束的 `msg_project_init_<digest>`，定义只读项目初始化提示词，并维护 `sent`、`already_sent`、`retryable_failed` 状态。
- 新增 `POST /api/code/sessions/{session_ref}/project-initialization/dispatch`：仅接受 `project_initialization` shell，会向当前 Runtime agent session 发送 `clientMessageId` 与只读提示词，并在失败时仅保存可重试状态。
- 本机既有目录注册后，`Apps.vue` 使用 `local`、`resume_recent`、`project_initialization` 和“项目初始化”标题创建或恢复独立 shell；普通最近 shell 不会被复用。
- `CodeConversationPage.vue` 仅在可信 `builder.ready` 成功提升 pending iframe 后派发初始化消息，并以每个 shell 的 in-flight 集合避免浏览器端重复派发。

## RED / GREEN

### RED

- `cd backend && ./.venv/bin/python -m pytest -q tests/test_code_runtime_routes.py -k "project_initialization"`：新增接口尚未实现，3 项用例均因无法从 `app.routes.code_runtime` 导入 `dispatch_project_initialization` 失败。
- `cd frontend && npm test -- CodeConversationPage.spec.ts -t "project initialization"`：页面尚未定义初始化路由和派发函数，专项断言失败。

### GREEN

- 同一后端专项命令：`3 passed, 156 deselected`。
- 同一前端专项命令：`1 passed, 25 skipped`。
- 后端相关完整文件：`159 passed`。
- 前端相关完整文件：`26 passed`。

## 自检

- 成功、重复派发和 Runtime 上游失败后重试均有后端回归覆盖；失败用例验证应用逻辑身份、位置、初始化用途及 binding runtime session 均保留。
- 提示词明确允许读取结构、说明、清单/锁、入口/脚本、Git 状态和环境可用性，明确禁止写入、安装、构建、测试、启动、迁移及 Git 修改。
- 运行 `git diff --check` 未发现空白错误。

## 已知限制

- `frontend` 的 `npm run build` 未通过，但报错来自未在本任务修改范围内的既有严格类型问题：`src/views/Apps.vue:1266` 的 `list?.items` 联合类型，以及 `src/views/codeAgentActivation.ts:17` 的三个隐式 `any` 参数。聚焦 Vitest 与后端回归均通过。

## 提交

实现以提交信息 `feat(code): dispatch read-only project initialization` 收口；实际提交号以 Git 提交结果为准。
