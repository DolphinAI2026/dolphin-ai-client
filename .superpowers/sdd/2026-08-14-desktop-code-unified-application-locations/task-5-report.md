# 任务 5A 报告：Code 会话位置合同

## 范围

本次只完成任务 5A：后端会话位置合同、前端请求类型和 pending 偏好的 shell session 精确索引。Apps、CodeConversationPage 和恢复面板留给 5B。

## 实现

- `POST /api/code/sessions/from-external-app` 接收 `logical_application_id`、`execution_location`、`session_policy` 和 `session_purpose`。
- `resume_recent` 只复用同租户、同用户、同逻辑应用、同位置、同用途的未归档 Code 会话；`create_new` 始终新建。
- 旧会话只有推导位置与请求位置一致才复用，并在当前写操作补齐位置字段。
- 会话响应返回 `logical_application_id`、`execution_location` 和 `session_purpose`。位置请求错误使用 `CODE_APPLICATION_LOCATION_REQUIRED` 并保留中文说明；未触碰 Runtime `execution_target`。
- 前端 API 可发送完整新合同，同时仍接受旧的最小外部应用请求。
- pending 偏好通过 sessionStorage 中的 `shellSessionRef -> scope key` 索引精确提交或丢弃，不扫描其他 scope。

## TDD 证据

### RED

后端新增合同测试先以项目虚拟环境执行：

```text
./.venv/bin/python -m pytest -q tests/test_code_runtime_routes.py -k "session_location or resume_recent or location_unavailable"
4 failed, 144 deselected
```

失败原因分别为响应缺少位置字段、按外部应用 ID 而非位置/用途复用、旧会话未回填，以及无效位置未返回 `CODE_APPLICATION_LOCATION_REQUIRED`。

前端 shell 精确索引的首个 RED 在专项前端运行中表现为导出函数不存在；该断言随后移动到 `codeApplicationLocationPreference.spec.ts`，避免把 5B 的页面/恢复断言带入 5A。

### GREEN

```text
cd backend && ./.venv/bin/python -m pytest -q tests/test_code_runtime_routes.py -k "session_location or resume_recent or location_unavailable"
4 passed, 144 deselected, 11 warnings

cd frontend && npm test -- codeApplicationLocationPreference.spec.ts
Test Files  1 passed (1)
Tests  5 passed (5)
```

系统 Python 环境缺少 `fastapi` 和 `httpx`，因此后端专项使用仓库已有 `backend/.venv`；测试范围未扩大。

## 遗留

5B 负责 Apps 的完整请求接线、CodeConversationPage 的可信 `builder.ready` 提交与失败丢弃，以及恢复面板与位置不可用错误呈现。
