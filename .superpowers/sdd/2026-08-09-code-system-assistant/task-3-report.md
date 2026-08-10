# Task 3 报告：只读企业 Code 基线 bootstrap

## 状态

已完成。`GET /api/system-assistant/bootstrap` 现在基于当前 `AuthContext` 和已有本地事实源返回租户隔离的只读基线快照；P0 只生成一条最高价值推荐路线草稿，不创建 Plan、Runtime Dynamic Plan 或任何写操作。

## 变更

- 更新 `backend/app/system_assistant/contracts.py`：增加基线节点、来源状态、推荐动作和 bootstrap 响应契约；状态区分 `ready|partial|missing|stale|unavailable|not_needed`。
- 新增 `backend/app/system_assistant/baseline_service.py`：只读读取当前租户 `RegisteredWorkspace`、`PlatformEnv`、已发布平台知识、`SkillRegistry` 和当前角色/权限；Full Workspace 共享资产、远程能力和模板目录无可靠本地接口时保留 `unavailable|partial` 并在 metadata 说明。
- 新增 `backend/app/system_assistant/policy.py`：按通用 facts 选择一个推荐动作和简短 `available_actions`，完整基线返回 `not_needed`。
- 新增 `backend/app/routes/system_assistant.py` 并在 `backend/app/main.py` 注册 `/api/system-assistant/bootstrap`；鉴权失败由现有 `get_auth_context` 处理，源故障返回 `unavailable` 快照而不伪造数据。
- 新增基线与路由测试，覆盖四种通用 fixture、租户隔离、认证边界和 source failure。

## 验证

使用任务专用环境 `/tmp/d-ai-code-system-assistant-p0-venv/bin/pytest` 执行：

```text
pytest -q tests/test_system_assistant_contracts.py tests/test_system_assistant_profile.py \
  tests/test_system_assistant_baseline.py tests/test_system_assistant_routes.py
21 passed, 10 warnings
```

另行执行新增基线/路由测试：`9 passed`；`python -m compileall -q app/system_assistant app/routes/system_assistant.py` 通过。告警为既有 SQLAlchemy `datetime.utcnow()` 弃用告警。

## 范围边界与关注事项

本任务不实现 Full Workspace/Control Plane 资产投影、模板目录、远程能力查询、Runtime Dynamic Plan、Plan snapshot 或写操作；这些来源在快照中显式标记不可用或部分可用，供 P1 接入真实接口后扩展。
