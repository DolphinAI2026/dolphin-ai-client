# 华宝 Code-only 产品边界最终修复报告

## 状态

DONE_WITH_CONCERNS

实现与测试提交：`d7a92ad6 fix: close code-only boundary review gaps`

## 1. `/coding` 统一归属 Code 产品

### RED

命令：

```bash
cd frontend && npm test -- src/router/tenantUrlGuard.spec.ts src/stores/mode.spec.ts
```

结果：2 个测试文件失败，4 项失败、58 项通过。失败分别证明：

- `/coding` 的显式 route meta 仍为 `builder`。
- Code-only 访问 `/coding` 被错误重定向到 `/code/apps`。
- Builder-only 访问 `/coding` 未被产品 guard 重定向到 `/`。
- `isCodeRoutePath('/coding')` 仍返回 `false`，Rail/模式同步会选择 Builder。

### 修复

- `frontend/src/router/index.ts` 将 `/coding` 的 `meta.product` 改为 `code`。
- `frontend/src/stores/mode.ts` 将遗留 `/coding` 纳入 Code route helper。
- 路由测试覆盖 Code-only 可访问及 Builder-only 重定向。
- 模式测试覆盖 `/coding -> code`；Rail 既有测试确认其继续消费 `isCodeRoutePath()`。
- 后端既有产品组合测试继续以 `/api/coding/scenes` 验证 coding API 在 Builder-only 下被 Code guard 阻断、在 Code-only 下可用。

### GREEN

```bash
cd frontend && npm test -- src/router/tenantUrlGuard.spec.ts src/stores/mode.spec.ts src/components/v2/RailSidebar.spec.ts
```

结果：3 个测试文件、86 项全部通过。

## 2. 委托身份必须同时具备 context 与 secret

### RED

与第 3 项共用安全矩阵命令：

```bash
cd backend && /mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python -m pytest -q tests/test_code_runtime_service.py -k 'control_plane_headers or workspace_open_headers or default_workspace_open_sends_trusted_delegation'
```

结果：3 项失败、7 项通过、79 项未选择。其中 1 项证明 delegated context 存在但 secret 为空时仍发送 `X-AI-Builder-*`。

### 修复

- `_control_plane_headers()` 只有在 delegation secret 非空且 delegated context 存在时，才同时发送 secret 与 delegated identity headers。
- Bearer token 选择逻辑保持不变。
- 无 context 和无 secret 两种路径均有测试证明不会发送委托身份。
- 约 1555 行的旧 `default_workspace_open` 断言已更新为新安全矩阵：user Bearer + context + secret 时发送可信委托身份。

### GREEN

上述聚焦命令结果：10 项全部通过、79 项未选择。

## 3. Workspace coordinator token 合并可信委托身份

### RED

与第 2 项同一 RED 中，admin/root 两组 coordinator token 测试失败，均缺少 `X-Tenant-Id` 与可信委托头，证明 `_workspace_open_headers()` 提前返回丢失统一 header 组合结果。

### 修复

- `_workspace_open_headers()` 先调用 `_control_plane_headers(include_content_type=True)` 组合 Content-Type、租户与安全规则允许的委托头。
- 存在 workspace coordinator token 时，仅覆盖 `Authorization: Bearer <workspace-token>`。
- 参数化覆盖 `admin` 与 `root`，分别映射为 `ai-builder-admin-11`、`ai-builder-root-11`。
- 无 secret 场景仍不发送任何 `X-AI-Builder-*` 委托身份。

### GREEN

与第 2 项共同执行，10 项全部通过、79 项未选择。

## 4. Captcha 探测失败后的单次恢复

### RED

```bash
cd frontend && npm test -- src/views/Login.spec.ts
```

结果：2 项失败、11 项通过。首次 captcha probe reject 后，登录 reject 不会再次请求 captcha；验证码输入无法恢复，且缺少一次性重试上限证据。

### 修复

- 使用 `captchaProbeFailed` 记录挂载阶段探测失败。
- 首次登录 API 失败先显示真实错误，再消费该标记并调用一次 `refreshCaptcha()`。
- 恢复请求成功且后端返回 `required=true` 时显示验证码输入。
- 恢复请求再次失败不会重新设置探测失败标记，后续登录失败不再无限探测。
- 未根据错误文案判断是否需要验证码。

### GREEN

```bash
cd frontend && npm test -- src/views/Login.spec.ts
```

结果：1 个测试文件、13 项全部通过。

## 5. Product availability 失败后可重试

### RED

```bash
cd frontend && npm test -- src/stores/productAvailability.spec.ts
```

结果：1 项失败、6 项通过。首次公开配置失败返回双产品 fallback 后，第二次加载仍返回缓存 fallback，没有恢复为 Code-only。

### 修复

- catch 分支继续向当前调用返回 `{ builder: true, code: true }`，同时清空 `availabilityLoad`。
- 下一次调用重新请求公开配置；成功结果继续缓存。
- 并发测试直接断言两个调用返回同一个 Promise，并断言只请求一次 API。

### GREEN

```bash
cd frontend && npm test -- src/stores/productAvailability.spec.ts
```

结果：1 个测试文件、7 项全部通过。

## 最终验证

### 前端聚焦回归

```bash
cd frontend && npm test -- src/stores/productAvailability.spec.ts src/stores/mode.spec.ts src/components/v2/RailSidebar.spec.ts src/router/tenantUrlGuard.spec.ts src/views/Login.spec.ts src/stores/user.tenantSwitch.spec.ts
```

结果：6 个测试文件、159 项全部通过。

### 后端相关完整测试

```bash
cd backend && /mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python -m pytest -q tests/test_product_guard.py tests/test_builder_auth_settings.py tests/test_code_runtime_service.py
```

结果：100 项全部通过；`test_code_runtime_service.py` 完整执行，未使用 `-k`。输出包含 139 条既有 `datetime.utcnow()` 弃用警告。

### 前端生产构建

```bash
cd frontend && npm run build
```

结果：`vue-tsc -b` 与 Vite 生产构建通过。仍有既有 `%VITE_BUILD_SHA%` 未定义和大 chunk 警告。

### 范围与质量检查

- `git diff --check` 通过。
- 只修改本计划授权的前后端实现、测试及本报告。
- 未修改 Control Plane 仓库、部署配置或第二批内容。
- 未新增或重构超过 500 行的代码文件。
- Bearer、workspace token、delegation secret/context 的组合分支均有行为测试。

## 自审结论

- 5 项 final review Important 问题均有独立 RED 证据、最小修复和 GREEN 证据。
- `/coding` 前端产品归属、shell 模式与后端 coding API guard 现已统一为 Code。
- 委托身份只在 shared secret 与 context 同时存在时发送；workspace token 只替换 Authorization，不丢可信上下文。
- Captcha 恢复不依赖错误文案，且失败恢复只尝试一次。
- Product availability 保持失败兼容 fallback，同时消除永久缓存故障。

## 未解决项与残余风险

- 按本波次边界未扩展 WebSocket 产品禁用错误语义；WebSocket 握手是否能稳定呈现与 HTTP `404/PRODUCT_DISABLED` 相同的错误形状，仍是残余风险。
- 既有构建 warning 与后端弃用 warning 未在本波次处理。
- 未执行部署或真实环境浏览器验收；本报告只覆盖代码、组件交互、后端测试与生产构建。
