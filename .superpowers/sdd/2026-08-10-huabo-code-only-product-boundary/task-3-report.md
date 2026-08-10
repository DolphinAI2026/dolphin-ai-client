# Task 3 报告

## 状态

DONE_WITH_CONCERNS

## 修改文件

- `backend/app/builder_auth/product_guard.py`
- `backend/tests/test_product_guard.py`
- `backend/app/main.py`

## RED

1. Dependency guard

   `/mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python -m pytest -q tests/test_product_guard.py`

   - 按预期在收集阶段失败：`ModuleNotFoundError: No module named 'app.builder_auth.product_guard'`。
   - 默认 shell Python 缺少 FastAPI；改用工程已有 Linux venv 后得到上述预期 RED。

2. 主应用路由分组

   `/mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python -m pytest -q tests/test_product_guard.py`

   - 按预期 2 项失败：Code-only 的 `/api/applications` 返回原有 `403`，Builder-only 的 `/api/coding/scenes` 返回原有 `200`，说明 `main.py` 还没有为独占路由注入产品 dependency。

## GREEN

`/mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python -m pytest -q tests/test_product_guard.py tests/test_builder_auth_settings.py`

- 2 个测试文件、11 项测试全部通过。
- 测试输出有 6 条既有 SQLAlchemy `datetime.utcnow()` 弃用警告；本任务未修改该部分。

## Commit

`feat(backend): guard disabled product APIs`

## 自审

- `ProductDisabledError` 由全局异常处理器映射为顶层 `{"detail":"product is disabled","code":"PRODUCT_DISABLED"}` 和 HTTP 404，不会产生 FastAPI 嵌套 `detail`。
- Builder guard 覆盖 `applications`、`apaas`、`generation_steps`、`requirements`、`current_app`、`builder_mcp`；Code guard 覆盖 `coding`、`code_runtime`（含 proxy router）、`browser`、`harness`。
- `auth`、`ai_chat`、`conversations`、`knowledge`、`skills_routes` 和 `system_assistant` 未注入产品 dependency。共享端点仍保留自身认证和数据依赖的既有行为。
- guard 只读取 Builder 鉴权配置，不要求用户身份；路由原有认证依赖仍负责身份校验。
