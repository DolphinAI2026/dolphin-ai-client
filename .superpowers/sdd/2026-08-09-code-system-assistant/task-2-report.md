# Task 2 报告：复用 AIChat 的 system_assistant profile

## 状态

已完成。系统助手现在复用既有 AIChat 会话、SSE run bus、附件、历史恢复、run-status、attach
和 abort 协议；`assistant_profile` 与 `mode=chat|cowork|code` 保持正交。

## 变更

- 更新 `backend/app/routes/ai_chat.py`：创建、列表、详情和 SSE 会话表示返回
  `assistant_profile`；列表支持 profile 过滤；创建请求复用 Task 1 合法值校验，未知 profile
  返回校验错误；旧记录缺省序列化为 `entry_agent`。
- 更新 `backend/app/agents/profile.py`：新增 registry 派生的 `system_assistant` profile，保留
  工作区读写、诊断、lint、验证、Skill/知识读取能力，排除应用创建、doc pipeline、部署发布和
  平台配置写入；系统提示词要求先诊断、再执行受控动作、最后验证。未知会话 profile 不会因
  `mode=code` 被静默降级为 `dev-apaas`。
- 更新 `backend/app/ai_chat/agent.py`：让无显式 override 的会话解析优先消费
  `system_assistant`，entry-agent 的既有 Code 模式继续使用 `dev-apaas` 收窄工具集。
- 新增路由/profile 回归测试，覆盖创建/详情、列表过滤、未知 profile、历史附件形状和旧 Code
  profile 解析。

## 验证

使用任务专用环境 `/tmp/d-ai-code/system-assistant-p0-task2-venv/bin/pytest` 执行：

```text
pytest -q tests/test_system_assistant_profile.py tests/test_ai_chat_routes.py
9 passed, 26 warnings

pytest -q tests/test_run_agent_session_overrides.py tests/test_ai_chat_mode_scoping.py \
  tests/test_attachment_parse_failure_guard.py tests/test_aichat_workspace_id.py \
  tests/test_ai_chat_run_bus.py
27 passed, 54 warnings
```

告警均为既有 SQLAlchemy `datetime.utcnow()` 弃用告警；本任务未改动 run-bus 事件字段或附件协议。

## 范围边界

未实现 P1 的 Plan/operation 字段、节点暂停/恢复、Runtime snapshot 或新的系统助手 UI/API。
