# Task 1 报告：隔离 assistant_profile 与迁移边界

## 状态

已完成。`AIChatSession.assistant_profile` 作为独立列加入，默认值为
`entry_agent`；既有 `mode=chat|cowork|code` 未修改。P0 合同仅定义 profile、
附件引用与现有 run bus 的会话恢复快照，未引入 P1 Runtime operation 或资产合同。

## 变更

- 新增 `backend/app/system_assistant/contracts.py`：profile 枚举、合法值校验、
  旧会话默认解析、附件引用和恢复快照合同。
- 更新 `backend/app/models/ai_chat.py`：新增非空、带 server default 的
  `assistant_profile` 列及索引。
- 更新 `backend/app/database.py`：沿用现有 SQLite/MySQL best-effort 启动迁移，
  为旧表补 `assistant_profile` 和索引。
- 新增 `backend/tests/test_system_assistant_contracts.py`：覆盖合法/未知 profile、
  三种旧 mode 的默认持久化值及附件/恢复合同。

## 验证

通过：

```text
/tmp/d-ai-code/system-assistant-p0-task1/venv/bin/pytest -q \
  tests/test_system_assistant_contracts.py \
  tests/test_ai_chat_session_title.py \
  tests/test_attachment_parse_failure_guard.py \
  tests/test_aichat_workspace_id.py

16 passed, 19 warnings
```

简报指定的原始命令因当前 worktree 不存在
`backend/tests/test_ai_chat_routes.py` 而无法收集；该文件由后续 Task 2 负责。
系统 Python 环境缺少 FastAPI，已在任务专用临时虚拟环境
`/tmp/d-ai-code/system-assistant-p0-task1/venv` 安装 `backend/requirements.txt` 后完成可用回归测试。

## Concerns

- Task 2 必须将 `assistant_profile` 接入 `routes/ai_chat.py` 的创建、列表和恢复
  响应，并接入现有 agent/profile 解析；本任务按文件边界未修改这些文件。
- 现有测试有 19 条 SQLAlchemy `datetime.utcnow()` 弃用告警，均来自已有模型，
  与本任务无关。
