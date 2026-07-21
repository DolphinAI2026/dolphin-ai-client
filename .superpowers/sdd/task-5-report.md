# Task 5 实施报告

- 日期：2026-07-21
- 工作区：`/home/shitou/worktrees/d-ai-code/apaas-builder-ai/tenant-url-uuid`
- 基线：`d0d172a6f4f7cad70d9ebabf91933059db3de475`
- 分支：`feat/2026-07-20-tenant-url-uuid`
- 范围：登录、多租户选择、RailSidebar 与 Code URL 集成

## 交付结果

### 登录与多租户选择

- 新增 `frontend/src/views/loginTenantRedirect.ts` 纯 helper：
  - 仅接受站内相对 redirect，拒绝 absolute、scheme-relative、反斜杠 authority、
    `/login` 和 `/tenant-select` 回环。
  - 从 redirect query 提取并规范化 canonical tenant UUID。
  - 仅在登录响应 tenant 列表中按 `tenant_public_id` 命中时返回对应
    `TenantOption.tenant_id`。
- `Login.vue` 和 `TenantSelect.vue` 复用同一安全 redirect 解析。
- TenantSelect 仅在目标 UUID 命中 tenant 列表时自动选择；非法或未命中目标保持人工选择。
- 自动与人工选择都继续调用 `selectTenant(selectionToken, tenantId)`；请求体保持
  `selection_token + tenant_id`，未发送 `tenant_public_id`。

### RailSidebar

- 租户菜单 value、active state 和 key 改为 `tenant_public_id`。
- numeric `tenant_id` 只从 `user.availableTenants` 按 public UUID 查找。
- 点击租户时先推进 Task 4 shared navigation epoch，再调用 Task 3
  `switchTenantContext(numericId, publicUuid, destination, epoch)`。
- destination 使用当前 `MODE_META[currentMode].home`、Vite base path 和目标
  `tenantId` UUID。
- 删除 `switchTenant()` 后额外 `router.push('/')`，租户切换只保留 adapter 的一次
  `window.location.replace()`。

### Code URL

- 新增 `nextAgentQuery()`，复制现有 query，仅替换或删除 `agent`。
- rail session target、创建 Code agent、删除当前 rail session 后回退均保留
  `tenantId` 和其他 query。
- `CodeConversationPage` 清理失效 agent、创建 Code 应用后跳转时保留现有 query，
  仅删除 `agent`。
- `codeFrameLifecycle` 在构造 iframe URL 时显式删除 `tenantId`，保留 runtime token、
  `frameKey` 和其他 upstream query。

## TDD 证据

### RED

- `Login.spec.ts`：helper 不存在，suite 按预期失败。
- `RailSidebar.spec.ts`：3 项失败，复现 numeric option、旧 wrapper 和重复导航。
- Code 批次：4 suites 共 7 项失败，覆盖 query 丢失与 iframe `tenantId` 泄漏。

### GREEN

- 登录定向：1 file，9 tests passed。
- RailSidebar 定向：1 file，16 tests passed。
- Code 定向：4 files，60 tests passed。

## 最终验证

```text
Task 5 定向:
Test Files  5 passed (5)
Tests       69 passed (69)

Task 3/4 回归:
Test Files  3 passed (3)
Tests       91 passed (91)

完整 frontend:
Test Files  91 passed (91)
Tests       495 passed (495)

vue-tsc --noEmit:
exit code 0

git diff --check:
exit code 0
```

Task 3/4 回归保留既有 Vue Router `next()` deprecation warning；无失败。

## 风险与边界

- 自动选择使用登录响应 tenants 序列化后的现有 TenantSelect 路由契约；最终授权仍由
  `/auth/select-tenant` 对 `selection_token + tenant_id` 服务端校验，URL UUID 不参与授权。
- 本任务未执行真实浏览器跨标签页或网络乱序 E2E；Task 3/4 状态机回归 91 项保持通过。
- 未修改主工作区、未推送、未开始 Task 6。
