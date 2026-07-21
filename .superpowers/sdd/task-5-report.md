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

## 独立评审修复（ADV-T5-001..004）

### 路由 query 类型与构建

- `nextAgentQuery()`、`RailSessionTarget.query` 和 active route query 改用 Vue Router
  `LocationQueryRaw`、`LocationQueryValueRaw`、`LocationQuery`。
- 保留 string、array、`null` 等合法 query 值，Task 5 的 RailSidebar 和
  CodeConversationPage 生产调用点通过 project-reference 类型检查。
- 清理同分支暴露的 Task 4 guard marker、`next(false)` 分支和测试 mock 类型错误。

### TenantSelect 选择事务

- 自动选择与人工点击共用单一 `selectionPending`。
- 租户卡片改为原生 button；选择请求和 `await router.replace()` 完成前全部 disabled。
- 新增 happy-dom 挂载测试：延迟导航 Promise 后点击第二张卡片，选择接口仍只调用一次。

### inactive tenant 后端边界

- 默认租户解析、普通用户登录 membership 投影同时要求 `UserTenant.status == 1`
  和 `Tenant.status == 1`。
- inactive tenant 不进入多租户 options；过滤后仅剩一个 active tenant 时只签发该
  active tenant token；仅剩 inactive tenant 时返回 403。
- `/auth/select-tenant` 在 membership 校验和签发 token 前再次权威校验 Tenant active。

### 候选 token 原子提交

- `selectTenant()` 先使用候选 access token 调用显式 `getMeWithToken()`。
- numeric tenant ID 和 server-returned public UUID 都匹配后，才一次提交共享 token、
  request adapter token 和 Pinia user。
- 候选 `/auth/me` 的 403、网络失败或上下文不匹配均不改变原 session。
- `TenantSelectRequest` 仍只发送 `selection_token + tenant_id`，public UUID 只用于
  客户端候选响应一致性验证。

### 唯一安全 redirect

- helper 提升到 `frontend/src/router/loginRedirect.ts`，Login、TenantSelect 和全局
  router guard 共用唯一 `safeLoginRedirectPath()`。
- 真实 memory-router 测试覆盖 encoded backslash authority、encoded
  scheme-relative authority 和 encoded dot-segment 登录回环，均 fail closed 到当前
  tenant home。

## 评审修复验证

```text
backend auth:
48 passed

Task 5 + Task 3/4 frontend:
Test Files  9 passed (9)
Tests       166 passed (166)

完整 frontend:
Test Files  92 passed (92)
Tests       501 passed (501)

npm exec -- vue-tsc --build --noEmit --pretty false:
exit code 0

npm run build:
exit code 0
2479 modules transformed

git diff --check:
exit code 0
```

构建仅保留既有大 chunk warning；测试仅保留既有 Vue Router `next()` deprecation、
Vue scope 和 onboarding 错误路径日志，无失败。未推送，未开始 Task 6。

## 复审新增修复（ADV-T5-005）

### pending 与取消边界

- TenantSelect 在选择请求、候选校验和导航完成前持续保持同一
  `selectionPending`；租户卡片和“返回登录”按钮均 disabled。
- `handleLogout()` 额外检查 pending，避免仅依赖按钮属性；非 pending 的明确退出会先
  取消现有 operation，再进入登录页。
- 组件为每次选择维护 generation 和 `AbortController`。组件卸载、明确取消或新 intent
  会使旧 operation 失效；旧 operation 即使晚到 commit handle，也会立即 rollback。

### 候选 session 与导航失败

- `authApi.selectTenant()`、候选 `getMeWithToken()` 和 store 的 `selectTenant()` 链路均
  支持 `AbortSignal`。
- store 在请求前、两次候选响应后及 commit 前检查 generation、abort 状态和源 session
  revision，失效候选抛出 `AbortError`，不得提交 token/user。
- 候选提交返回一次性 `rollback()/finalize()` handle；rollback 仅能回滚当前仍匹配的
  committed candidate，避免覆盖更新的 session。
- TenantSelect 检查 `router.replace()` resolved value；任何
  `isNavigationFailure()` 结果都不显示成功，并 rollback 本次 committed candidate，
  使页面停留时恢复源 session。

## ADV-T5-005 TDD 证据

### RED

- 新增测试首次运行共 10 项失败，分别复现：
  - pending 时返回登录仍可触发；
  - unmount/新 intent 未中止旧选择；
  - select/getMe 未透传 signal；
  - resolved NavigationFailure 被误报成功且未回滚 session。

### GREEN

```text
ADV-T5-005 定向:
Test Files  3 passed (3)
Tests       60 passed (60)

Task 5 + Task 3/4 frontend:
Test Files  9 passed (9)
Tests       173 passed (173)

完整 frontend:
Test Files  92 passed (92)
Tests       508 passed (508)

backend auth:
48 passed

npm exec -- vue-tsc --build --noEmit --pretty false:
exit code 0

npm run build:
exit code 0
2479 modules transformed

git diff --check:
exit code 0
```

构建仍仅有既有大 chunk warning；测试仍仅有既有 Vue Router `next()` deprecation、
Vue scope、onboarding 错误路径日志和后端 datetime deprecation warning。未推送，
未开始 Task 6。
