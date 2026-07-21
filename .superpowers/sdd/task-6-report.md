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

## Chromium B 慢/C 快 fixture 确定性门闩

日期：2026-07-21

干净 revision `6a67ca0cafc6fa7c30c16eca75316b8d1d9722a1` 的 Chromium E2E
在等待 C switch response 时超时，frontend proxy 日志只有 B switch。原 fixture
仅把 B candidate `/auth/me` 固定延迟 1.5 秒；B 仍可能在第二标签发出 C switch 前
完成，并通过 storage navigation 改写第二标签位置，导致 C 请求根本没有启动。

生成的 Python proxy 现使用 `threading.Event` 建立因果门闩：

- B candidate `/auth/me` 最多等待 15 秒，直到 proxy 已观察到 C candidate
  `/auth/me` 进入；
- C 进入时记录 `candidate_me_latch=release-observed` 并释放事件；
- B 被释放后额外等待 250ms，再继续请求 backend，并记录 waiting、releasing 和
  released 顺序；
- 15 秒内未观察到 C 时记录明确 timeout，并返回 HTTP 504，不再静默退化为固定
  sleep。

提交前静态验证：

```text
bash -n tests/e2e/builder-tenant-url-public-uuid-fixture.sh
exit code 0

python3 <generated frontend_server.py AST contract check>
frontend_server.py ast-parse=PASS
event-release=PASS
event-wait-timeout-15=PASS
timeout-send-error-504=PASS
post-release-delay-250ms=PASS
release-before-wait-source-order=PASS
target-c-env=PASS

git diff --check
exit code 0
```

fixture 的 clean-input gate 会拒绝包含自身未提交修改的工作树，因此 Chromium
动态验证在提交后、clean HEAD 上执行；最终结果以该次命令输出和提交 SHA 为准。

## T6-FINAL-001 Docker build provenance 收口

日期：2026-07-21

最终复审发现人工文档和 Compose 仍可从 dirty build context 构建镜像，同时把未变的
`HEAD` 写入 `builder-build-sha`。本轮只修复 T6-FINAL-001，未处理复审中的两个
Minor。

TDD RED：

```text
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_tenant_url_build_contract.py

8 failed, 13 passed
```

失败覆盖：

- 直接 Dockerfile caller 集合仍包含 Compose、客户提示和三个人工文档；
- 人工入口未调用 `scripts/build_builder_image.sh`；
- Compose 仍包含 `build:`，compose env 仍要求 `VITE_BUILD_SHA`；
- 共享 wrapper 不存在，三类 dirty 输入与 clean fake-CLI 合同均失败。

实现后首次运行得到 `2 failed, 19 passed`：真实临时 Git 仓库测试证明
`(...) || die` 会抑制 subshell 内的 `set -e`，使 staged/unstaged 的非零状态被后续
命令覆盖。wrapper 随后改为显式 `&&` 链，确保任一 provenance 检查失败都在读取
`HEAD` 和调用 container CLI 前终止。

最终 GREEN：

```text
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_tenant_url_build_contract.py

21 passed in 0.25s
```

合同使用真实临时 Git 仓库分别制造 staged、unstaged 和 relevant untracked Docker
输入，均断言 fake container CLI 未被调用。clean 路径断言完整 40 位小写 HEAD、
`PLATFORM`、五个 Vite 参数、六个基础镜像参数、两个 registry 参数、Dockerfile、
image tag 和 build context 均通过独立 argv 传给 fake CLI。

实现结果：

- 新增 `scripts/build_builder_image.sh`，默认使用 `docker`，也可通过
  `CONTAINER_CLI=podman` 使用 Podman；
- wrapper 在读取 `HEAD` 前检查 `frontend`、`backend`、`admin-spa`、
  `deploy/docker` 和 `.dockerignore` 的 staged、unstaged、relevant untracked；
- wrapper 校验完整 40 位小写 SHA，并使用 Bash 数组传递 build 参数，不使用
  `eval` 或不安全字符串拆分；
- Compose 删除源码 `build:`，只消费本地或预载的
  `apaas-builder:${IMAGE_TAG:-latest}`；
- compose env 删除 `VITE_BUILD_SHA`；
- `DEPLOY_CONTAINER.md`、K8s、Rancher 和客户缺镜像提示统一调用共享 wrapper；
- 客户 `ensure_image` 的 tar load、本地 image inspect 和既有镜像命名契约保持不变。

其他验证：

```text
bash -n scripts/build_builder_image.sh deploy/customer/deploy.sh
bash-n=PASS

podman-compose --env-file deploy/docker/compose.env.example \
  -f deploy/docker/docker-compose.yml config
exit code 0; image=apaas-builder:latest; no build section

git diff --check
exit code 0
```

本轮没有执行真实容器镜像构建；container argv 与 fail-closed 行为由 fake CLI 合同
验证，Compose 由当前可用的 `podman-compose 1.0.6` 完成配置展开。

## Task6 第二轮 Important：HEAD snapshot 构建架构收口

日期：2026-07-21

第二轮复审指出两个相关问题：共享 wrapper 仍从 live worktree 构建，无法排除
Git-ignored 但会进入 Docker context 的文件，也存在 clean-check 与实际 build 之间的
TOCTOU；六个部署脚本仍各自复制直接 Docker/buildx 构建逻辑。本轮采用单一 HEAD
snapshot 架构收口，未处理复审中的三个 Minor。

测试扫描器初稿曾把合同文件里的命令 fixture 当成真实 caller，并漏识别
`${CONTAINER_CLI}` 形式；修正测试自身后取得有效 TDD RED：

```text
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_tenant_url_build_contract.py

12 failed, 16 passed
```

失败覆盖：

- 全仓 tracked caller 集合仍包含六个直接构建脚本；
- wrapper 没有 `REPO_ROOT` override、`git archive`、外部 snapshot 或 cleanup trap；
- staged/unstaged live 内容仍会被旧 clean gate 拒绝，ignored sentinel 的隔离合同失败；
- 最终 Docker context 仍是 live repository；
- `PUSH=1` 的 buildx `--push` 和普通 build 后 push 路径不存在；
- 六脚本尚未调用共享 wrapper。

实现：

- wrapper 解析并 canonicalize `REPO_ROOT`，确认它是 Git worktree，读取并校验完整
  40 位小写 `HEAD`；
- 使用 `git archive --format=tar "$BUILD_SHA"` 解到
  `/tmp/apaas-builder-image.XXXXXX`，校验 snapshot 内 Dockerfile，最终 Dockerfile
  和 context 都只指向 snapshot；
- `trap cleanup EXIT` 在成功、构建失败或 archive 失败时清理 snapshot；
- live staged、unstaged、普通 untracked、Git-ignored 但 Docker-included 文件均不
  进入 context，同时消除 check/build TOCTOU；
- wrapper 保留全部 Vite、基础镜像和 registry build args；
- 默认只执行本地 build；`PUSH=1` 且 buildx 可用时执行 `buildx build --push`，
  否则普通 build 后调用同一 `CONTAINER_CLI push`；
- 六个部署脚本删除 `assert_clean_build_inputs`、直接 Dockerfile、build/buildx/push
  逻辑，统一调用 wrapper；online clone 显式传 `REPO_ROOT="$WORKDIR"` 并执行克隆目录
  内 wrapper；双镜像 rebuild 通过两次 `build_image` 调用分别执行 wrapper。

GREEN：

```text
backend/.venv/bin/python -m pytest -q \
  backend/tests/test_tenant_url_build_contract.py

28 passed in 0.83s

backend/.venv/bin/python -m pytest -q \
  backend/tests/test_tenant_url_build_contract.py \
  -k 'shared_wrapper or direct_dockerfile_callers or direct_caller_scanner or git_docker_callers or rebuild_script'

20 passed, 8 deselected
```

动态 fake CLI snapshot 合同在真实临时 Git repo 中同时放入 staged frontend、
unstaged backend、non-ignored untracked Docker 文件和
`backend/.pytest_cache/sentinel.txt` ignored 文件。传入 CLI 的 snapshot 只包含
tracked HEAD 内容，完整 HEAD 作为 `VITE_BUILD_SHA`，所有 sentinel 均不存在；
wrapper 返回后原 snapshot path 已删除。buildx 与 fallback push 两条 argv 路径均
通过。

caller 合同通过 `git ls-files` 扫描全仓 tracked 文件，并识别反斜杠续行以及 `-f`、
`--file path`、`--file=path` 形式。允许的直接 Builder Dockerfile caller 仅为
GitLab CI BuildKit 和共享 wrapper；CI 继续使用完整 `${CI_COMMIT_SHA}`。

其他验证：

```text
bash -n scripts/build_builder_image.sh \
  scripts/deploy_k8s_dev.sh \
  scripts/deploy_k8s_dev_web_terminal.sh \
  scripts/deploy_login_sync_hotfix.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  scripts/deploy_platform_proxy_hotfix.sh \
  scripts/rebuild_images_dev_main.sh

bash-n-seven=PASS

git diff --check
exit code 0
```

本轮未执行真实 Docker/Podman 镜像构建或 push；snapshot 内容、完整 build args、
buildx push、fallback push 与 cleanup 由 fake CLI 合同验证。
