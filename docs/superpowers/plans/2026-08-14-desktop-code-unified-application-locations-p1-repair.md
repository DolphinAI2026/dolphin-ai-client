# 桌面 Code 统一应用位置 P1 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭统一应用位置最终复审剩余的目录唯一性、跨 Shell 激活、位置恢复竞态和普通会话误用初始化 Shell 问题。

**Architecture:** 使用规范化路径摘要承载设备级唯一性，并把旧重复数据显式保留为冲突状态；Runtime 激活只由会话页发起并按共享 Runtime scope 串行；打开响应和错误携带本次会话位置上下文；Rail 保留 `session_purpose` 并只在 `standard` Shell 创建普通 Agent 会话。

**Tech Stack:** FastAPI、SQLAlchemy async、SQLite/MySQL/PostgreSQL、Vue 3、TypeScript、Vitest、Pytest。

---

## 文件结构

- `backend/app/code_runtime/workspace_path_identity.py`：规范化路径摘要和迁移冲突分类，保持小型纯函数边界。
- `backend/app/database.py`：执行路径摘要列、回填、旧索引替换和新唯一索引迁移。
- `backend/app/models/__init__.py`：声明路径摘要字段及唯一索引。
- `backend/app/code_runtime/local_runtime.py`：注册/rebind 使用设备级摘要，稳定映射并发冲突为 409。
- `backend/app/code_runtime/agent_activation.py`：按共享 Runtime scope 串行 Runtime current 变更。
- `backend/app/code_runtime/session_location.py`：生成结构化位置错误上下文。
- `backend/app/routes/code_runtime.py`：打开成功/失败透传单次请求的位置合同。
- `frontend/src/api/codeRuntime.ts`：声明结构化打开结果和错误上下文。
- `frontend/src/views/CodeConversationPage.vue`：恢复语义只读取本次打开结果，不依赖异步 rail 默认值。
- `frontend/src/components/v2/codeRailHistory.ts`：保留 purpose，并分别选择位置代表 Shell 与 standard Shell。
- `frontend/src/components/v2/RailSidebar.vue`：移除预激活，普通新会话只使用 standard Shell。

### Task 1: 设备级路径身份和迁移

**Files:**
- Create: `backend/app/code_runtime/workspace_path_identity.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/code_runtime/local_runtime.py`
- Test: `backend/tests/test_registered_workspace.py`
- Test: `backend/tests/test_code_runtime_local_runtime.py`

- [ ] **Step 1: 添加旧重复路径、不同长路径和跨租户 rebind 的失败测试**
- [ ] **Step 2: 运行专项测试，确认分别因缺少摘要迁移和 rebind 500 而失败**
- [ ] **Step 3: 增加 SHA-256 路径身份列，回填唯一行，重复组保留 NULL 并报告 409**
- [ ] **Step 4: 注册/rebind 写入摘要并在 `IntegrityError` 后重读分类**
- [ ] **Step 5: 运行路径专项和数据库方言专项**

### Task 2: 共享 Runtime 激活和打开位置合同

**Files:**
- Modify: `backend/app/code_runtime/agent_activation.py`
- Modify: `backend/app/code_runtime/session_location.py`
- Modify: `backend/app/routes/code_runtime.py`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: 添加不同 Shell 同 Runtime 并发激活和结构化位置错误测试**
- [ ] **Step 2: 运行专项测试，确认 binding 级锁和字符串错误合同无法满足测试**
- [ ] **Step 3: 激活事务改用共享 Runtime scope，保留不同 scope 并发**
- [ ] **Step 4: 打开成功及位置失败返回 `execution_location`、逻辑应用和 shell 上下文**
- [ ] **Step 5: 运行激活/打开专项测试**

### Task 3: Rail 与会话页消费正确位置和 standard Shell

**Files:**
- Modify: `frontend/src/api/codeRuntime.ts`
- Modify: `frontend/src/components/v2/codeRailHistory.ts`
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Modify: `frontend/src/views/CodeConversationPage.vue`
- Test: `frontend/src/components/v2/RailSidebar.spec.ts`
- Test: `frontend/src/views/CodeConversationPage.spec.ts`

- [ ] **Step 1: 添加 Rail 不预激活、初始化 Shell 不承载普通会话、本机错误不被默认 remote 覆盖的失败测试**
- [ ] **Step 2: 运行前端专项，确认失败原因对应三个 P1**
- [ ] **Step 3: Rail 导航只更新路由；分组同时保留位置代表 Shell 和 standard Shell**
- [ ] **Step 4: 目标位置没有 standard Shell 时先创建/恢复 `standard` Shell，再创建 Agent 会话**
- [ ] **Step 5: 页面恢复只消费本次 open 成功/错误载荷，旧字符串错误无位置时退化为普通错误**
- [ ] **Step 6: 运行前端专项测试**

### Task 4: 聚焦验证和复审

**Files:**
- Update: `.superpowers/sdd/2026-08-14-desktop-code-unified-application-locations-p1-repair/progress.md`
- Create: `.superpowers/sdd/2026-08-14-desktop-code-unified-application-locations-p1-repair/final-report.md`

- [ ] **Step 1: 运行后端路径、位置、激活专项**
- [ ] **Step 2: 运行前端 Rail、会话页专项**
- [ ] **Step 3: 运行 `npm run build:desktop` 和 `cargo check`**
- [ ] **Step 4: 检查差异只包含 P1 修复，完成最终独立复审**
- [ ] **Step 5: 保持分支未合并、未推送、未打包，等待用户后续决定**
