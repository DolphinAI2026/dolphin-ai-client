# 华宝 Code-only 产品边界实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `BUILDER_PRODUCT_BUILDER_ENABLED=false`、`BUILDER_PRODUCT_CODE_ENABLED=true` 的部署从入口、路由、后端 API 到登录恢复都稳定表现为 Code-only，并修复 Control Plane 委托身份与无验证码登录链路。

**Architecture:** 前端新增唯一的产品能力状态模块，基于公开鉴权设置计算启用模式、默认首页和禁用产品重定向；所有入口只消费该模块，不各自解释配置。后端以轻量 FastAPI dependency 保护明确属于 Builder 或 Code 的路由组，同时保留认证、系统助手和共享能力；Control Plane header 与验证码修复保持局部、向后兼容。

**Tech Stack:** Vue 3、Pinia、Vue Router、Vitest、TypeScript、FastAPI、Pydantic、Pytest。

**Design spec:** `docs/superpowers/specs/2026-08-10-huabo-code-only-product-boundary-design.md`

## Global Constraints

- Code-only 配置为 `BUILDER_PRODUCT_BUILDER_ENABLED=false`、`BUILDER_PRODUCT_CODE_ENABLED=true`。
- Builder-only 和 Builder + Code 双产品部署必须保持可用；双产品根路由仍进入 Builder。
- 公共配置读取失败时回退 `{ builder: true, code: true }`，不得因配置接口暂时失败锁死现有部署。
- `/login`、`/tenant-select`、`/desktop-setup`、`/desktop-settings` 等公共路由不属于 Builder 或 Code。
- 系统助手及其共享会话能力不得因 Builder 禁用而失效。
- 产品禁用 API 返回 HTTP `404`，响应 detail 为 `{"detail":"product is disabled","code":"PRODUCT_DISABLED"}`。
- 用户 Bearer token 与可信 delegated identity headers 必须能够同时发送。
- 只有存在 delegated context 时发送 delegated identity；远程委托仍要求 `X-AI-Builder-Delegation-Secret`。
- GitLab 保留名 `admin`、`root` 继续映射为 `ai-builder-<reserved-name>-<local-user-id>`。
- 验证码能力请求失败时前端按 `required=false` 继续登录；真实登录接口返回的验证码错误仍原样展示。
- 不处理 GitLab TLS、PAT 有效期、默认 seed、AI Provider Secret 初始化和通用 `WORKSPACE_PROVISION_FAILED`。
- 本次新增或重构代码文件不得超过 500 行，不向现有大文件继续堆入可独立职责。

---

### Task 1: 产品能力状态与显式路由边界

**Files:**
- Create: `frontend/src/stores/productAvailability.ts`
- Create: `frontend/src/stores/productAvailability.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/router/tenantUrlGuard.spec.ts`
- Modify: `frontend/src/stores/mode.ts`
- Modify: `frontend/src/stores/mode.spec.ts`

**Interfaces:**
- Consumes: `authSettingsApi.getPublic(): Promise<PublicBuilderAuthSettings>`。
- Produces: `ProductAvailability = { builder: boolean; code: boolean }`、`loadProductAvailability()`、`enabledProductModes()`、`defaultProductHome()`、`productForRoute()`、`redirectForDisabledProduct()`。
- Route meta 新增 `product?: 'builder' | 'code'`；公共路由不设置该字段。

- [ ] **Step 1: 为产品状态写失败测试**

测试必须覆盖：Code-only 返回 `['code']` 和 `/code/apps`；Builder-only 返回 `['builder']` 和 `/`；双产品保持 `['builder','code']` 和 `/`；公开设置请求失败回退双产品。

```ts
expect(enabledProductModes({ builder: false, code: true })).toEqual(['code'])
expect(defaultProductHome({ builder: false, code: true })).toBe('/code/apps')
expect(defaultProductHome({ builder: true, code: false })).toBe('/')
expect(defaultProductHome({ builder: true, code: true })).toBe('/')
```

- [ ] **Step 2: 运行产品状态测试并确认 RED**

Run: `cd frontend && npm test -- src/stores/productAvailability.spec.ts`

Expected: FAIL，原因是 `productAvailability.ts` 或导出函数尚不存在。

- [ ] **Step 3: 实现产品状态模块**

模块初始值和请求失败值均为 `{ builder: true, code: true }`；同一加载过程复用 Promise，测试可调用显式 reset 方法隔离状态。`productForRoute()` 只读取 route meta，不用“不是 `/code` 就是 Builder”的反向推断。

- [ ] **Step 4: 为显式路由边界写失败测试**

测试至少断言：Builder 路由具有 `meta.product='builder'`，Code 路由具有 `meta.product='code'`，公共路由没有 product；Code-only 访问 `/`、`/apps`、`/ai-chat` 被重定向 `/code/apps`；Code-only 访问 `/login` 不重定向；Builder-only 访问 `/code/apps` 回 `/`。

- [ ] **Step 5: 运行路由测试并确认 RED**

Run: `cd frontend && npm test -- src/router/tenantUrlGuard.spec.ts src/stores/mode.spec.ts`

Expected: FAIL，原因是路由尚未声明显式产品归属或 guard 未应用产品开关。

- [ ] **Step 6: 在认证与租户解析完成后应用产品 guard**

路由守卫先加载产品状态，再对 `to.meta.product` 调用 `redirectForDisabledProduct()`；禁用产品使用 `replace` 重定向默认首页。`modeForRoutePath()` 只保留兼容用途，新增逻辑不得继续依赖它判断任意路由归属。

- [ ] **Step 7: 运行 Task 1 测试并确认 GREEN**

Run: `cd frontend && npm test -- src/stores/productAvailability.spec.ts src/router/tenantUrlGuard.spec.ts src/stores/mode.spec.ts`

Expected: PASS。

- [ ] **Step 8: 提交 Task 1**

```bash
git add frontend/src/stores/productAvailability.ts frontend/src/stores/productAvailability.spec.ts frontend/src/router/index.ts frontend/src/router/tenantUrlGuard.spec.ts frontend/src/stores/mode.ts frontend/src/stores/mode.spec.ts
git commit -m "feat(frontend): enforce configured product routes"
```

### Task 2: Rail、Logo、登录与租户切换统一默认首页

**Files:**
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Modify: `frontend/src/components/v2/RailSidebar.spec.ts`
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/views/Login.spec.ts`
- Modify: `frontend/src/stores/user.ts`
- Modify: `frontend/src/stores/user.tenantSwitch.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `loadProductAvailability()`、`enabledProductModes()`、`defaultProductHome()`。
- Produces: Web Rail 只显示启用模式；Logo、无 `entry_path` 登录、租户切换和跨标签会话恢复均使用产品能力状态计算的首页。

- [ ] **Step 1: 为 Code-only 导航入口写失败测试**

测试至少断言：Rail 的 Web 模式来源不是固定 `MODE_ORDER`；Code-only 只显示 Code；Logo 点击进入 `/code/apps`；双产品仍显示 Builder 与 Code。

- [ ] **Step 2: 为登录与租户切换回退写失败测试**

测试至少断言：登录响应没有合法 `entry_path` 时，Code-only 落 `/code/apps`；租户切换处于被禁用的 Builder 路由时，目的地为 `/code/apps?tenantId=<uuid>`；跨标签恢复同样不回到 `/`。

- [ ] **Step 3: 运行 Task 2 测试并确认 RED**

Run: `cd frontend && npm test -- src/components/v2/RailSidebar.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts`

Expected: FAIL，原因是入口仍消费固定模式顺序或固定 `/`。

- [ ] **Step 4: 接入统一产品能力状态**

Rail 对桌面端继续优先使用 discovery scope，对 Web 使用产品配置；当前 URL 属于禁用产品时选择第一个启用模式。Logo 绑定默认产品首页。登录保留安全 redirect 和服务端 `entry_path` 优先级，但二者为空或指向禁用产品时使用默认产品首页。租户切换保留 `tenantId` UUID 查询参数。

- [ ] **Step 5: 运行 Task 2 测试并确认 GREEN**

Run: `cd frontend && npm test -- src/components/v2/RailSidebar.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

```bash
git add frontend/src/components/v2/RailSidebar.vue frontend/src/components/v2/RailSidebar.spec.ts frontend/src/views/Login.vue frontend/src/views/Login.spec.ts frontend/src/stores/user.ts frontend/src/stores/user.tenantSwitch.spec.ts
git commit -m "fix(frontend): honor code-only default entry"
```

### Task 3: 后端产品 API 边界

**Files:**
- Create: `backend/app/builder_auth/product_guard.py`
- Create: `backend/tests/test_product_guard.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `get_builder_auth_config()` 和 `BuilderAuthConfig.settings.products`。
- Produces: `ProductDisabledError`、`product_disabled_exception_handler()`、`require_builder_product()`、`require_code_product()` FastAPI dependencies。
- Builder-exclusive routers: `applications.router`、`apaas.router`、`generation_steps.router`、`requirements.router`、`current_app.router`、`builder_mcp.router`。
- Code-exclusive routers: `coding.router`、`code_runtime.router`、`code_runtime.proxy_router`、`browser.router`、`harness.router`。
- Shared routers including `auth`、`ai_chat`、`conversations`、`knowledge`、`skills_routes`、`system_assistant` remain unguarded because Code system assistant uses them.

- [ ] **Step 1: 为 dependency 写失败测试**

使用最小 FastAPI app、注册 `product_disabled_exception_handler()` 并 monkeypatch 产品配置，分别断言禁用 Builder/Code 返回：

```json
{"detail":"product is disabled","code":"PRODUCT_DISABLED"}
```

HTTP 状态为 `404`；启用产品返回原测试路由内容。

- [ ] **Step 2: 运行 dependency 测试并确认 RED**

Run: `cd backend && pytest -q tests/test_product_guard.py`

Expected: FAIL，原因是 `product_guard.py` 尚不存在。

- [ ] **Step 3: 实现产品 guard**

dependency 抛出 `ProductDisabledError`；exception handler 返回 `JSONResponse(status_code=404, content={"detail":"product is disabled","code":"PRODUCT_DISABLED"})`。依赖只读取配置，不要求用户身份，认证依赖仍由原路由负责。

- [ ] **Step 4: 为主应用路由分组写失败测试**

在 `test_product_guard.py` 检查主应用的代表端点：Code-only 下 Builder 代表 API 返回 `404/PRODUCT_DISABLED`，Code 代表 API 不返回 `PRODUCT_DISABLED`；Builder-only 反向验证；`/api/auth/settings/public` 与系统助手代表 API 不返回 `PRODUCT_DISABLED`。

- [ ] **Step 5: 运行路由分组测试并确认 RED**

Run: `cd backend && pytest -q tests/test_product_guard.py`

Expected: FAIL，原因是 `main.py` 尚未给产品独占路由注入 dependency。

- [ ] **Step 6: 在 include_router 层注入 guard**

在 `main.py` 注册 `ProductDisabledError` handler，并使用 `dependencies=[Depends(require_builder_product)]` 或 `dependencies=[Depends(require_code_product)]` 注入明确产品路由，不修改每个 endpoint。共享路由保持原样。

- [ ] **Step 7: 运行 Task 3 测试并确认 GREEN**

Run: `cd backend && pytest -q tests/test_product_guard.py tests/test_builder_auth_settings.py`

Expected: PASS。

- [ ] **Step 8: 提交 Task 3**

```bash
git add backend/app/builder_auth/product_guard.py backend/tests/test_product_guard.py backend/app/main.py
git commit -m "feat(backend): guard disabled product APIs"
```

### Task 4: 委托身份 header 与无验证码登录

**Files:**
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/tests/test_code_runtime_service.py`
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/views/Login.spec.ts`

**Interfaces:**
- Consumes: 现有 `_delegated_identity_headers()` 和 `DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET`。
- Produces: Bearer 与 delegated headers 并存；验证码读取失败时 `captchaRequired=false`。

- [ ] **Step 1: 为 Bearer + delegated headers 写失败测试**

测试输入必须同时包含 `authorization_header="Bearer user-token"`、delegated context 和 shared secret，并断言输出同时包含：

```text
Authorization: Bearer user-token
X-AI-Builder-Delegation-Secret: shared-secret
X-AI-Builder-Delegated-User-Id
X-AI-Builder-Delegated-Username
X-AI-Builder-Delegated-Display-Name-B64
```

另保留无 delegated context 不发送这些 header，以及 `admin`/`root` 安全映射的覆盖。

- [ ] **Step 2: 运行 header 测试并确认 RED**

Run: `cd backend && pytest -q tests/test_code_runtime_service.py -k 'control_plane_headers'`

Expected: FAIL，原因是现有 `has_user_bearer` 条件会丢弃 delegated headers。

- [ ] **Step 3: 最小修改 `_control_plane_headers()`**

Bearer 选择逻辑不变；`delegation_secret` 和 `_delegated_identity_headers()` 的判断只依赖 delegated context，其中远程 secret header 仍需配置值存在。

- [ ] **Step 4: 为验证码能力失败写失败测试**

mock `authApi.getCaptcha()` reject，挂载登录页后断言验证码输入不显示，账号密码仍可提交；登录接口自身返回的错误仍通过 `ElMessage.error` 展示。

- [ ] **Step 5: 运行验证码测试并确认 RED**

Run: `cd frontend && npm test -- src/views/Login.spec.ts`

Expected: FAIL，原因是 catch 分支把 `captchaRequired` 设置为 `true`。

- [ ] **Step 6: 实现无验证码降级**

验证码请求失败时清空 `captchaId`、`captchaImage`、`captcha_code` 并设置 `captchaRequired=false`，不得吞掉登录接口错误。

- [ ] **Step 7: 运行 Task 4 测试并确认 GREEN**

Run: `cd backend && pytest -q tests/test_code_runtime_service.py -k 'control_plane_headers' && cd ../frontend && npm test -- src/views/Login.spec.ts`

Expected: PASS。

- [ ] **Step 8: 提交 Task 4**

```bash
git add backend/app/code_runtime/service.py backend/tests/test_code_runtime_service.py frontend/src/views/Login.vue frontend/src/views/Login.spec.ts
git commit -m "fix(auth): preserve delegated identity and optional captcha"
```

### Task 5: 聚焦回归与构建验证

**Files:**
- Modify only when a verification failure proves a regression in Task 1-4 owned files.

**Interfaces:**
- Consumes: Task 1-4 的最终实现。
- Produces: 可复现的前后端测试和构建证据，不包含部署发布。

- [ ] **Step 1: 运行前端聚焦回归**

Run: `cd frontend && npm test -- src/stores/productAvailability.spec.ts src/stores/mode.spec.ts src/components/v2/RailSidebar.spec.ts src/router/tenantUrlGuard.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts`

Expected: PASS。

- [ ] **Step 2: 运行后端聚焦回归**

Run: `cd backend && pytest -q tests/test_product_guard.py tests/test_builder_auth_settings.py tests/test_code_runtime_service.py -k 'product_guard or builder_auth_settings or control_plane_headers'`

Expected: PASS。

- [ ] **Step 3: 运行前端类型检查与生产构建**

Run: `cd frontend && npm run build`

Expected: exit code `0`。

- [ ] **Step 4: 检查分支范围**

Run: `git diff --check && git status --short && git log --oneline --decorate main..HEAD`

Expected: 无 whitespace error；只包含本计划设计、计划和实现提交；不包含 Control Plane 第二批改动。

- [ ] **Step 5: 提交仅由验证发现的必要修复**

若 Step 1-4 未产生修复则不创建空提交；若有修复：

```bash
git add backend/app/builder_auth/product_guard.py backend/app/main.py backend/app/code_runtime/service.py backend/tests/test_product_guard.py backend/tests/test_code_runtime_service.py frontend/src/stores/productAvailability.ts frontend/src/stores/productAvailability.spec.ts frontend/src/stores/mode.ts frontend/src/stores/mode.spec.ts frontend/src/router/index.ts frontend/src/router/tenantUrlGuard.spec.ts frontend/src/components/v2/RailSidebar.vue frontend/src/components/v2/RailSidebar.spec.ts frontend/src/views/Login.vue frontend/src/views/Login.spec.ts frontend/src/stores/user.ts frontend/src/stores/user.tenantSwitch.spec.ts
git commit -m "test: stabilize code-only product boundary"
```
