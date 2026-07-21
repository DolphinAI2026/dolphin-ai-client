# Task 6 实施报告：Tenant UUID Deep Link E2E

日期：2026-07-21

## 交付范围

- root 是唯一 Playwright owner，版本精确固定为 `1.61.1`。
- frontend 移除重复的 Playwright/Playwright Core 依赖，两个 lockfile 与各自
  `package.json` 一致。
- production HTML 注入真实 `VITE_BUILD_SHA`：
  `<meta name="builder-build-sha" content="%VITE_BUILD_SHA%">`。
- Docker frontend stage 声明 `ARG/ENV VITE_BUILD_SHA`，空值在构建命令前
  通过 `test -n` 失败；实现未提供默认值或伪造 SHA。
- 新增 Python build contract、自包含 SQLite/browser fixture 和同一份
  Chromium/Edge Playwright 场景。

## Fixture 与浏览器机制

Fixture 从 `git rev-parse HEAD` 获取 40 位 SHA，以该值构建 frontend，并同时
验证构建产物及静态服务返回的 meta。fixture 在临时目录创建 SQLite 数据库，
写入当前、授权目标、停用和无权租户，以及用户、membership、Code session 和
agent session；随后启动 backend、fake runtime 和 production dist 静态服务。
所有进程和临时目录由 trap 清理。

日志只记录方法、路径、状态和脱敏失败尾部，不记录请求 header/body。结束前
扫描密码 canary、Authorization/Cookie/JWT 形态和 runtime upstream
`tenantId=`；Chromium 与 Edge 均通过。

Chromium 使用 Linux Node 和 root Playwright。当前 WSL 环境的 Edge 使用
Windows Node `v24.18.0`：

- `wslpath -w` 转换 spec 和 repository root；
- spec 通过 `createRequire()` 从 UNC root
  `node_modules\playwright` 加载唯一 Playwright owner；
- `WSLENV` 白名单仅通过环境变量传递 fixture 参数和凭据，凭据不进入命令行；
- Windows Node 先证明可访问 WSL localhost builder URL，失败时才验证并使用
  WSL IP；
- Windows Playwright 原生执行 `chromium.launch({ channel: "msedge" })`，
  不使用 CDP/profile fallback。

在没有 `node.exe` 的 CI Linux 环境，fixture 保留 Linux Node 执行同一 spec
和原生 `msedge` channel 的路径，CI 需预先安装 Playwright Edge browser。

## E2E 覆盖

- 旧 URL canonicalize，保留 path、其他 query 和 hash。
- 授权跨租户只调用一次 `/api/auth/switch-tenant`。
- 无权和停用目标不挂载 Code iframe，不发起目标业务请求。
- 两个标签页在连续跨租户操作后最终收敛。
- Code agent activate 只走 browser-auth proxy
  `/api/code/sessions/.../agent-sessions/.../activate`，该 activate 无 401；
  不调用旧 `/api/code-runtime/.../activate`。
- outer `tenantId` 不进入 iframe URL 或 fake runtime upstream。

## 验证结果

依赖与浏览器：

- root `npm ci --no-audit --no-fund`：PASS，安装 4 packages。
- frontend `npm ci --no-audit --no-fund`：PASS，安装 278 packages。
- `npm exec -- playwright install chromium`：PASS。
- `npm exec -- playwright install chromium msedge`：本机 Linux Edge 安装未完成；
  Playwright 尝试 sudo 安装依赖，但当前会话无 sudo 密码。未静默跳过，改用机器
  已安装的 Windows Edge 完成真实 channel 验证。

Build contract：

```text
python -m pytest -q backend/tests/test_tenant_url_build_contract.py
4 passed in 0.06s
```

浏览器 fixture，构建 SHA
`ac9a19f501502fabc53728190dbfd786670b1db8`：

```text
BROWSER_CHANNEL=chromium tests/e2e/builder-tenant-url-public-uuid-fixture.sh
TENANT_URL_E2E=PASS channel=chromium
TENANT_URL_FIXTURE=PASS channel=chromium

BROWSER_CHANNEL=msedge tests/e2e/builder-tenant-url-public-uuid-fixture.sh
TENANT_URL_E2E=PASS channel=msedge
TENANT_URL_FIXTURE=PASS channel=msedge
```

Task 3-5 frontend 回归：

```text
Test Files  9 passed (9)
Tests       175 passed (175)
```

Backend UUID/auth/build contracts：

```text
100 passed, 2 skipped, 391 warnings in 37.95s
```

Typecheck 与 production build：

```text
npm exec -- vue-tsc --build --noEmit --pretty false
exit code 0

VITE_BUILD_SHA="$(git rev-parse HEAD)" npm run build
exit code 0
2479 modules transformed
```

## 剩余风险

- 本机没有执行 Linux 安装版 `msedge`；CI Linux 必须先成功安装 Edge channel。
  fixture 已保留无 Windows Node 时的 Linux channel 路径，但该路径需由 CI
  环境验证。
- 两个 migration dialect 测试因未配置
  `TENANT_PUBLIC_ID_TEST_DATABASE_URL` 跳过；SQLite/auth contracts 已通过。
- Edge Code 页面还会触发既有的可选 `/api/code/applications` 请求；本地外部
  aPaaS 服务未配置时该请求返回 401。Task 6 要求的 browser-auth activate
  请求为 200，且旧 activate 路径未被调用。
- production build 保留既有的大 chunk warning，无新增 typecheck/build 失败。

未推送、未部署、未开始 Task 7。

## 独立评审修复

以下内容取代上文初始实现阶段的浏览器证据；初始 Chromium/Edge 运行发生在
Task 6 提交前，因工作树包含未提交构建输入，不作为 revision 绑定证据。

### 构建 provenance

- Dockerfile 现在要求 `VITE_BUILD_SHA` 为 40 位小写 Git SHA，而不是仅检查非空。
- GitLab 使用完整 `CI_COMMIT_SHA`。
- 本地、开发、热修和在线构建脚本在相关构建输入干净时读取完整 HEAD，并显式传入
  `VITE_BUILD_SHA`。
- Compose、客户部署示例和部署文档要求调用方提供明确的 40 位 revision。
- build contract 枚举现有 Dockerfile caller，防止新增必填 build arg 后遗漏调用方。
- E2E fixture 在构建前拒绝影响 frontend、backend、Docker 和 E2E 输入的 staged、
  unstaged 或相关 untracked 文件，防止脏树内容冒充 HEAD。

### 授权与浏览器场景

- 普通用户 `/auth/switch-tenant` 在签发 token 前联查 active membership 与
  `Tenant.status == 1`；停用租户返回 403。
- fixture 保存停用租户 numeric ID，并直接断言 switch endpoint 拒绝，不再只依赖前端
  active tenant list 过滤。
- Windows Node 使用全新、精确的 `WSLENV` allowlist，不继承调用 shell 的任意变量或
  modifier。
- 页面 init script 在 fetch/XHR 发起时记录当时 location 和请求 URL，并记录
  `iframe.code-frame` 是否曾经挂载；拒绝目标不再只检查最终 DOM。
- 多标签场景新增第三个 active tenant，通过延迟 B candidate `/auth/me`、快速完成 C，
  验证真实 B 慢/C 快乱序下两个标签最终收敛到 C。
- Code activate response 显式断言 200，成功路径 secret scan 包含 seed log。

### 提交后 revision 证据

Task 6 修复先提交，再在干净 HEAD 上运行 Chromium 和 Windows Edge。最终输出写入
`.superpowers/sdd/task-6-post-commit-verification.log`；该日志不属于构建输入，也不进入
commit，因此可以记录并核对最终 HEAD，而不会再次改变被验证 revision。

提交前快速门禁：

```text
backend build/auth contracts: 64 passed
Task 3-5 frontend: 9 files, 175 passed
vue-tsc --build --noEmit: PASS
bash -n / node --check / git diff --check: PASS
```

Task 6 只有在 post-commit 日志同时包含以下结果且 `git status` 保持干净时才完成：

```text
TENANT_URL_FIXTURE=PASS channel=chromium build_sha=<final HEAD>
TENANT_URL_FIXTURE=PASS channel=msedge build_sha=<final HEAD>
```

## Chromium rejected redirect 聚焦修复

日期：2026-07-21

干净 revision `9ada89d7160121407af477759f59ad43ba4435f9` 的 Chromium E2E
证明：bootstrap 后访问无权 `tenantId` 时，`/apaas/status` 可能在浏览器地址仍为
被拒绝 URL 时发起。根因是 preview status pending 在 router `beforeEach` 中、
导航最终提交前被消费。

本轮将恢复时机移到 router `afterEach`。只有同时满足以下条件才清除 pending 并
异步请求 `/apaas/status`：

- navigation 没有 failure；
- 路由要求认证；
- `tenantContext=required`；
- URL 中规范化后的 tenant UUID 与已提交用户的 tenant UUID 相等；
- auth session 已提交。

`tenantContext=none`、未认证路由、navigation failure、rejected URL 和尚未完成的
canonical redirect 均不恢复 preview status。

TDD RED：

```text
cd frontend
npm exec -- vitest run src/router/tenantUrlGuard.spec.ts

Test Files  1 failed (1)
Tests       5 failed | 44 passed (49)
```

五个新增场景均因 `router afterEach was not registered` 按预期失败。首次 RED 还发现
rejected 场景的 tenant-list refresh mock 返回 `undefined`；修正测试 fixture 后重新
取得上述有效 RED，再修改 production router。

GREEN：

```text
cd frontend
npm exec -- vitest run src/router/tenantUrlGuard.spec.ts

Test Files  1 passed (1)
Tests       49 passed (49)
```

Typecheck：

```text
cd frontend
npm exec -- vue-tsc --build --noEmit --pretty false

exit code 0
```

本轮按聚焦范围未重跑 Chromium/msedge 长 E2E；该风险保留给后续 clean-HEAD
浏览器验证。

## Edge 跨标签 tenant switch 竞态修复

日期：2026-07-21

Windows Edge 的 B 慢/C 快场景暴露出跨标签竞态：第二个标签已将共享 token 更新为
C，但第一个标签的 storage listener 只启动 C alignment，没有立即取消本标签在途的
B switch。若 B candidate `/auth/me` 在 C alignment 完成前返回，B 仍满足原有
generation、epoch 和 auth revision 检查，并把共享 token 覆盖回 B。

修复保持 storage event 的 fail-closed 检查：仅当非空 event token 仍等于当前
`localStorage.token` 时，先推进 tenant navigation epoch、取消本标签在途 switch，
再启动原有 storage alignment。storage alignment 使用独立 generation 和
AbortController，因此不会被这次 tenant epoch 推进取消。

TDD RED：

```text
cd frontend
npm exec -- vitest run src/stores/user.tenantSwitch.spec.ts \
  -t "cancels an in-flight local switch before aligning a confirmed cross-tab token"

Test Files  1 failed (1)
Tests       1 failed | 44 skipped (45)
Expected: stale_cancelled
Received: committed_reload
```

聚焦 GREEN：

```text
Test Files  1 passed (1)
Tests       1 passed | 44 skipped (45)
```

完整 store 与 router 回归：

```text
npm exec -- vitest run src/stores/user.tenantSwitch.spec.ts
Test Files  1 passed (1)
Tests       45 passed (45)

npm exec -- vitest run src/router/tenantUrlGuard.spec.ts
Test Files  1 passed (1)
Tests       49 passed (49)
```

Typecheck：

```text
npm exec -- vue-tsc --build --noEmit --pretty false
exit code 0
```

本轮未重跑 Windows Edge 长 E2E；修复后的 clean-HEAD Edge 验证仍是最终浏览器证据。
