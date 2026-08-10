# Task 2 报告

## 状态

DONE_WITH_CONCERNS

## 修改文件

- `frontend/src/components/v2/RailSidebar.vue`
- `frontend/src/components/v2/RailSidebar.spec.ts`
- `frontend/src/views/Login.vue`
- `frontend/src/views/Login.spec.ts`
- `frontend/src/stores/user.ts`
- `frontend/src/stores/user.tenantSwitch.spec.ts`

## RED

`cd frontend && npm test -- src/components/v2/RailSidebar.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts`

- 新增断言首次运行时有 7 项失败：Rail 仍使用固定 `MODE_ORDER` 与 `/`，登录没有产品能力回退，租户切换和跨标签恢复仍落到 Builder 首页。
- 随后的构建还发现 Rail Logo 模板错误访问了自动解包 `ref` 的 `.value`；已用构建错误定位并修复。
- 自审补充了桌面 discovery 租户跳转的 RED 断言，确认 Web 默认首页不能覆盖桌面当前模式首页。

## GREEN

`cd frontend && npm test -- src/components/v2/RailSidebar.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts`

- 3 个测试文件、85 项测试全部通过。

`cd frontend && npm run build`

- `vue-tsc -b` 与 Vite 生产构建通过。

## Commit

`fix(frontend): honor code-only default entry`

## 自审发现

- Web Rail 异步读取公开产品配置，只展示启用模式；当前路由属于禁用产品时 Rail 选择首个可用模式。桌面继续使用 discovery scope，且桌面租户切换保留当前模式首页。
- Logo、无有效登录入口、Web 租户切换与跨标签认证对齐均通过 `defaultProductHome()` 计算默认首页；Web 租户切换仍保留 UUID `tenantId` 查询参数。
- 登录仍保持外部安全 redirect、内部安全 redirect 和服务端 `entry_path` 的原有优先级，只有缺失或已禁用产品才回退默认首页。
- 构建仍报告既有 `%VITE_BUILD_SHA%` 未定义和大 chunk 警告；本任务未修改构建配置。

## Fix round 1

### RED

`cd frontend && npm test -- src/components/v2/RailSidebar.spec.ts src/stores/user.tenantSwitch.spec.ts`

- 5 项测试失败：桌面 Code discovery 租户跳转没有保留 `/code/apps`，Rail 仍调用兼容 `switchTenant`；跨标签认证对齐在公开产品配置异步加载期间，令牌被清空或替换后仍会触发 reload。

### GREEN

`cd frontend && npm test -- src/components/v2/RailSidebar.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts`

- 3 个测试文件、88 项测试全部通过。

`cd frontend && npm run build`

- `vue-tsc -b` 与 Vite 生产构建通过。

### 修复内容

- Rail 桌面租户切换改为与 Web 相同的 `switchTenantContext` 原子提交路径；桌面入口继续根据当前 discovery 模式选取首页，Code 始终保留 `/code/apps`。
- storage 对齐回调在异步公开产品配置返回后，校验会话所有权、触发令牌、bootstrap 令牌和认证 revision；已过期回调不再导航。
- 构建仍有既有 `%VITE_BUILD_SHA%` 未定义及大 chunk 警告，本轮未修改构建配置。

### Commit

`fix(frontend): preserve desktop tenant entry`
