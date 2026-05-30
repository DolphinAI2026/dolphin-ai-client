# 06 测试基础设施评估

**日期**: 2026-05-30
**评审性质**: 只读源码 + 实跑测试套件（未改代码、未提交）
**仓库**: apaas-builder-ai — 得帆云低代码平台 AI 搭建助手

---

## 1. 测试配置总结

### 配置文件

| 文件 | 关键内容 |
|------|---------|
| `backend/pytest.ini` | `asyncio_mode = auto`、`testpaths = tests`、`addopts = -ra --strict-markers` |
| `backend/conftest.py` | 全局注入 `DATABASE_URL=sqlite+aiosqlite:///:memory:`（MySQL 不会被触碰）；注入 `LLM_API_KEY=test-key`、`JWT_SECRET_KEY=test-secret-do-not-use-in-prod` |
| `backend/tests/conftest.py` | 额外注入 `APAAS_ENCRYPTION_KEY=x*32` |
| `tests/conftest.py`（根目录） | 同样强制 SQLite，向 sys.path 插入 `backend/`（跨目录兼容） |

### 结论：无需任何外部依赖即可跑测试

- **数据库**: 强制 SQLite in-memory，MySQL/外部 apaas 数据库不会被访问
- **LLM / apaas API**: 全部用 mock / FakeClient / monkeypatch，不需要真实 key
- **venv**: 已存在于 `backend/venv/`（Python 3.13.12，pytest 9.0.3，FastAPI 0.115.0，SQLAlchemy 2.0.36，aiosqlite 已安装）
- **所需命令**: 直接在 `backend/` 目录运行 `venv/bin/python3 -m pytest -q --ignore=tests/test_spec_section_o1.py`

---

## 2. 依赖就绪状况

| 组件 | 状态 |
|------|------|
| venv | 已存在（`backend/venv/bin/python3`） |
| 主要包 | pytest 9.0.3 / fastapi 0.115.0 / sqlalchemy 2.0.36 / aiosqlite / httpx / jose 全部就位 |
| 外部服务 | **无需**（MySQL、aPaaS、LLM API 全部被 mock/SQLite 替代） |
| 必需环境变量 | 仅 `LLM_API_KEY`、`JWT_SECRET_KEY`（conftest 已自动注入测试值） |

---

## 3. pytest 实跑结果

### 命令

```bash
cd backend
venv/bin/python3 -m pytest -q --no-header -p no:cacheprovider \
    --ignore=tests/test_spec_section_o1.py 2>&1 | tail -60
```

### 结果

```
11 failed, 383 passed, 1416 warnings in 12.99s
```

| 状态 | 数量 |
|------|------|
| **通过** | **383** |
| **失败** | **11** |
| 收集错误（import 报错） | 1（`test_spec_section_o1.py`） |
| 跳过 | 0 |
| 总采集量（排除报错文件） | 394 |
| **总耗时** | **约 13 秒** |

### 收集错误（1 个，影响 1 个文件）

| 文件 | 错误 | 根因 |
|------|------|------|
| `tests/test_spec_section_o1.py` | `ImportError: cannot import name 'SpecSection' from 'app.models'` | `app.models.spec_section.SpecSection` 类存在，但 `app/models/__init__.py` 未 `re-export`；测试文件写了 `from app.models import SpecSection` 而 `__init__` 只导入了其他模型 |

---

### 11 个失败用例分类

#### A. JWT audience 字段变更（4 个失败）—— **真 Bug / 测试不同步**

| 用例 | 文件 |
|------|------|
| `test_switch_tenant_signs_new_token_for_member` | test_auth_switch_tenant.py |
| `test_platform_admin_can_switch_to_any_active_tenant` | test_auth_switch_tenant.py |
| `test_platform_admin_login_token_uses_default_tenant` | test_platform_admin_tenant_context.py |
| `test_platform_admin_legacy_token_resolves_default_tenant` | test_platform_admin_tenant_context.py |

**根因**: `jose.exceptions.JWTClaimsError: Invalid audience`——生产代码 `auth.py` 已在 JWT payload 中加入 `aud` 字段，测试解码时未传 `audience` 参数，导致 jose 校验拒绝。另外 `test_platform_admin_legacy_token_resolves_default_tenant` 还额外报 `AttributeError: 'dict' object has no attribute 'id'`（测试调用 `create_access_token({"sub": user.id}, ...)` 时把 dict 传给了期望 User 对象的参数）。

**风险级别**: 中等——两个 auth 路径（切租户 + 平台管理员登录）的测试实际上无法验证业务逻辑。

#### B. Section hint 工具名过时（1 个失败）——**测试断言不同步**

| 用例 | 文件 |
|------|------|
| `test_hint_contains_section_specific_tools` | test_section_hint.py |

**根因**: 测试期望 hint 文本包含 `list_application_dev_kits`，但该工具名已改为 `list_dev_scenes`（hint 内容已更新，测试断言未跟进）。

#### C. step_executor 接口变更（2 个失败）——**测试 stub 落后于实现**

| 用例 | 文件 |
|------|------|
| `test_execute_create_model_merges_existing_model_by_code_and_adds_missing_fields` | test_step_executor_model_merge.py |
| `test_execute_create_model_reuses_existing_field_by_code` | test_step_executor_model_merge.py |

**根因**: `FakeModelClient.query_models()` 不接受 `with_fields` 关键字参数，但生产代码 `step_executor.py:443` 已加此参数。测试的 Fake 实现未同步更新。

#### D. tool_registry.yaml 与 mcp_server.py 漂移（4 个失败）——**配置未同步**

| 用例 | 失败原因 |
|------|---------|
| `test_config_whitelist_matches_current_expected` | yaml 新增 16 个工具（含 `create_dev_workspace`、`publish_dev_workspace` 等扩展工具）进入 config agent 白名单，硬编码的 `_EXPECTED_CONFIG_WHITELIST` 快照（62 工具）未更新 |
| `test_yaml_matches_mcp_server_source` | mcp_server.py 注册了 4 个工具（`get_apaas_form_detail`、`get_apaas_process_detail`、`list_apaas_app_processes`、`set_role_resource_permission`）但 tool_registry.yaml 缺对应 entry |
| `test_runtime_drift_check_passes_in_clean_state` | 同上（4 个工具注册了但 yaml 没 entry） |
| `test_runtime_drift_check_warns_when_yaml_has_extra` | 同上（fake 工具注入测试前置条件里已存在 4 个真实漂移） |

**根因**: 近期新增/重命名 MCP 工具后，`tool_registry.yaml` 未同步补 entry，测试拦截了这一漂移（这正是 drift 检测的设计意图）。

---

## 4. 按业务域分类的测试文件清单

### 4.1 Auth / 租户 / 权限（34 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_auth_switch_tenant.py` | 21 | 切租户、创建/删除租户、成员管理、密码重置 |
| `test_platform_admin_tenant_context.py` | 3 | 平台管理员登录 token、legacy token 解析 |
| `test_project_role_levels.py` | 8 | 项目角色权限层级 |
| `test_tenant_quota.py` | 6 | 租户配额检查 |
| `test_collaboration_models.py` | 6 | 协作模型 ORM |

### 4.2 Spec / SPEC文档（51 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_spec_tools.py` | 14 | MCP spec 工具 |
| `test_spec_converter.py` | 8 | SPEC 格式转换 |
| `test_section_hint.py` | 8 | section hint 文案 |
| `test_spec_schema.py` | 5 | SPEC JSON Schema 校验 |
| `test_spec_routes.py` | 4 | SPEC HTTP 路由 |
| `test_spec_agent.py` | 4 | spec agent 工具 |
| `test_spec_fork.py` | 3 | SPEC fork |
| `test_spec_orm.py` | 3 | SPEC ORM 映射 |
| `test_spec_optimistic_locking.py` | 3 | 乐观锁 |
| `test_spec_persistence.py` | 2 | SPEC 持久化 |
| `test_spec_orm_phase_a.py` | 2 | Phase A ORM |
| `test_smoke.py` | 2 | 冒烟（SPEC schema + import） |

### 4.3 Git / 版本控制（55 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_git_provider_github.py` | 11 | GitHub 适配器 |
| `test_git_provider_gitlab.py` | 8 | GitLab 适配器 |
| `test_git_connection.py` | 9 | Git 连接管理 |
| `test_git_drift.py` | 9 | 漂移检测 |
| `test_git_repo_init.py` | 9 | 仓库初始化 |
| `test_git_sync_apply.py` | 6 | Sync apply |
| `test_git_sync_promote.py` | 5 | Sync promote |
| `test_git_oauth.py` | 7 | OAuth 流程 |
| `test_webhook_verify.py` | 12 | Webhook 签名验证 |
| `test_webhook_inbound.py` | 6 | Webhook 入站处理 |

### 4.4 Proposal / 变更提案（34 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_proposal_apply.py` | 8 | 应用 proposal |
| `test_proposal_reviews.py` | 7 | 审核流程 |
| `test_proposals_routes.py` | 7 | HTTP 路由 |
| `test_proposal_validation.py` | 5 | 校验逻辑 |
| `test_proposal_persistence.py` | 4 | 持久化 |
| `test_proposal_fixup.py` | 3 | 修复逻辑 |

### 4.5 应用管理 / aPaaS 集成（30 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_update_app_info.py` | 10 | app 信息更新 |
| `test_application_members_api.py` | 6 | 成员 API |
| `test_apaas_base_url_allowlist.py` | 6 | URL 白名单 |
| `test_apaas_token_error_detection.py` | 4 | Token 错误检测 |
| `test_call_apaas_with_relogin.py` | 4 | 自动重登 |
| `test_application_pagination.py` | 3 | 分页 |
| `test_app_type.py` | 2 | 应用类型 |
| `test_app_code_rules.py` | 4 | 应用 code 规则（禁 apaas/xdap 前缀等） |

### 4.6 Preview / 工作区 / IDE（17 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_preview_runtime_contract.py` | 5 | Preview 协议 |
| `test_preview_runtime_local_runner.py` | 4 | 本地 Runner |
| `test_workspace_sync.py` | 5 | 工作区同步 |
| `test_ide_apply_edits.py` | 2 | IDE 文件编辑 |
| `test_vscode_patch_template.py` | 2 | VSCode patch 模板 |
| `test_code_server_local_url.py` | 3 | Code Server URL |

### 4.7 Projects / 偏好 / 配置（19 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_projects_routes_phase_a.py` | 8 | 项目路由 Phase A |
| `test_preferences_api.py` | 4 | 偏好 HTTP 路由 |
| `test_preferences_model.py` | 2 | 偏好 ORM |
| `test_seed_llm_configs.py` | 2 | LLM 配置种子数据 |
| `test_lowcode_standards.py` | 6 | 低代码规范（字段/模型 code 生成规则） |

### 4.8 工具注册 / MCP / 浏览器（66 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_tool_registry.py` | 31 | YAML 工具注册表完整性、agent 白名单、漂移检测 |
| `test_browser_frame_routing.py` | 23 | 浏览器控制 MCP 路由 |
| `test_step_executor_model_merge.py` | 2 | 模型合并逻辑 |

### 4.9 其他功能（28 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_inbound_intercept.py` | 4 | SSE 入站拦截 |
| `test_chat_decision_prompt.py` | 2 | Chat 决策 prompt |
| `test_design_doc_preflight.py` | 3 | 设计文档预检 |
| `test_doc_upload_spec_backfill.py` | 1 | 文档上传 spec 回填 |
| `test_draft_doc_update_helpers.py` | 7 | 草稿文档更新辅助函数 |
| `test_form_name_normalization.py` | 7 | 表单名称规范化 |
| `test_extension_p2_fixes.py` | 5 | P2 扩展修复 |
| `test_platform_apply_diff.py` | 4 | 平台 diff 应用 |
| `test_work_state.py` | 5 | 工作状态聚合 |

---

## 5. 覆盖缺口分析

### 5.1 前端（`frontend/src/`）

**零测试**。前端无任何 `.test.*` 或 `.spec.*` 文件。核心组件完全没有自动化覆盖：

- `FormBuilder.vue` / `DataSchema.vue` / `ProcessDesigner.vue` / `PermissionMatrix.vue`
- `ConfigAssistant.vue`（AI 配置助手，核心交互路径）
- `AIChatPage.vue` / `ChatPage.vue`（两条独立对话路径）
- RailSidebar、TabStrip 等 UI 组件

**风险**: 前端重构后无回归保障。

### 5.2 后端路由层 —— 零覆盖路由模块（32 个）

以下路由模块（位于 `app/routes/`）无对应测试文件：

| 域 | 无测试路由模块 |
|---|--------------|
| **AI 对话** | `ai_chat.py`、`chat.py`、`conversations.py`、`config_chat_sessions.py` |
| **aPaaS 部署** | `applications/`（含 deploy、generate 子路由）、`generation_steps.py`、`incremental_update.py` |
| **MCP 服务** | `admin_mcp.py`、`builder_mcp.py`、`mcp_hub.py`、`mcp_platform.py` |
| **Coding** | `coding.py`、`coding_v2.py`、`coding_v2_spec.py` |
| **平台管理** | `platform_envs.py`、`platform_proxy.py`、`db_connections.py`、`llm_configs.py` |
| **其他** | `marketplace.py`、`industry.py`、`templates.py`、`voice.py`、`quick_db.py`、`requirements.py`、`runtime_v2.py`、`specs_v2.py`、`sse.py`、`harness.py`、`help_assistant.py`、`agent_prompts.py`、`agents_config.py`、`browser_ext_ws.py`、`current_app.py`、`git_webhook.py` |

### 5.3 后端核心逻辑 —— 高风险无测试模块

| 模块 | 风险说明 |
|------|---------|
| `app/generator_v2.py` | 低代码生成核心，含字段/模型/权限生成逻辑，无专项单元测试（仅 step_executor 有 2 个 stub 测试） |
| `app/mcp_server.py`（工具实现层） | 约 80+ MCP 工具的实现体，tool_registry 仅测试注册表结构，业务逻辑本身无 mock 测试 |
| `app/apaas_client.py` | aPaaS 平台 HTTP 客户端（所有平台 API 调用入口），无专项测试 |
| `app/step_executor.py` | 建模/字典/权限执行逻辑，仅 2 个失败用例覆盖 model merge，其他 step 类型无测试 |
| `app/config_assembler.py` / `config_diff.py` | 配置装配与差异计算，无测试 |
| `app/deploy_*.py` / `app/routes/applications/` | 部署链路（deploy、publish、rollback），无测试 |
| `app/auth.py`（`create_access_token` 含 audience） | 4 个测试失败——实际上 JWT audience 路径无法验证 |

---

## 6. 跑全套测试所需前置条件

```bash
# 前置（venv 已就位，直接跑）:
cd /path/to/apaas-builder-ai/backend
venv/bin/python3 -m pytest -q --no-header -p no:cacheprovider \
    --ignore=tests/test_spec_section_o1.py

# 无需:
# - MySQL / PostgreSQL
# - aPaaS 外部环境
# - LLM API Key（测试值已注入）
# - 任何网络访问
```

**注意**:
- `test_spec_section_o1.py` 收集即报 `ImportError`，必须 `--ignore` 才能跑全套，否则 pytest 提前退出
- 所有 1416 个 deprecation warning 来自 `datetime.utcnow()`，是 Python 3.12+ 升级警告，不影响功能

---

## 7. 参考既有测试用例文档风格

`docs/internal/TEST_CASES_*.md` 三份文档（`SMART_BUILDER`、`ONLINE_CODING`、`RUIJING_CODING`，均为 2026-04-26）是**端到端手动测试用例**，格式为：

- 表格列: `ID | 优先级 | 场景 | 操作步骤 | 预期结果 | 证据`
- 通过标准（AC-01~AC-06）附在文档头
- 测试数据用真实业务场景（如「供应商准入与风险管理系统」）

这与现有 pytest 单元测试（纯 Python mock + SQLite）是**不同层次**：前者是验收场景，后者是逻辑单元。编写新 pytest 用例时应对齐现有风格（async + `db_session` fixture + httpx AsyncClient）。

---

## 8. 关键结论

| 项目 | 结论 |
|------|------|
| 基础设施 | **健康**：SQLite in-memory、venv 就位，无需任何外部服务，13 秒跑完 |
| 通过率 | **97.2%**（383/394，排除 1 个 import 报错文件） |
| 真实失败 | **11 个**，分 4 类：JWT audience 不同步（4）、hint 文案不同步（1）、stub 接口落后（2）、YAML 漂移（4） |
| 前端覆盖 | **0%** —— 零测试 |
| 后端路由覆盖 | 约 **35%** 路由有测试，65% 路由无任何测试（含最关键的 deploy、MCP 工具、ai_chat 路径） |
| 最高风险缺口 | `generator_v2.py`（生成核心）、`mcp_server.py`（工具实现）、部署链路、auth JWT audience 验证 |
