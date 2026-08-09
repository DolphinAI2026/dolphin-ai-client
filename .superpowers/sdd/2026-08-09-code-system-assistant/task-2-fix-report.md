# Task 2 修复报告：绑定 Code 工作区的 system_assistant 隔离

## 修复内容

当 `assistant_profile=system_assistant` 且 `mode=code` 时，
`resolve_overrides_for_session` 现在按 `session.workspace_id` 复用
`narrow_tools_for_locked_ws`，并返回绑定的 `locked_ws_id`。既有
`_apply_session_overrides` 会继续把该 ID 交给 `ws_bind_view_context`，因此发送链路注入
单工作区约束，且不会枚举或切换到其他工作区。

未绑定 `workspace_id` 的系统助手 Code 会话仍保留完整系统助手工具集、返回 `None` 锁定 ID，
可以先发现目标工作区。`entry_agent` Code 会话的原有 `dev-apaas` 收窄和锁定行为未变。

## 验证

先运行新增回归测试确认旧实现失败：绑定场景断言发现多出未收窄工具并且没有锁定；未绑定场景通过。
修复后运行：

```text
pytest -q backend/tests/test_system_assistant_profile.py::test_system_assistant_code_session_locks_bound_workspace_and_context \
  backend/tests/test_system_assistant_profile.py::test_system_assistant_code_session_without_workspace_can_discover_one
2 passed
```

随后运行 Task 2 定向测试及既有 Code/附件/run-bus 回归测试，结果记录在交付回复中。
