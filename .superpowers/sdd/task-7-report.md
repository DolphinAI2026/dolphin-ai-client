# Task 7 Report: 不可变 digest 发布与逐 Pod smoke

## RED

- 新增 `tests/release/test_builder_tenant_url_smoke.sh`，要求：
  - BuildKit 写入 `build/metadata.json` 并读取 `containerimage.digest`。
  - `build/release.env` 输出 digest 形式的 `BUILDER_IMAGE` 和完整 `DEPLOYED_REVISION`。
  - 存在固定 Playwright 1.61.1、Edge、kubectl 1.30.7 的发布 smoke job。
  - 共享 helper 校验 `containerStatuses`、`initContainerStatuses`、唯一
    `builder-build-sha`、reconciliation CLI 和 Code session。
  - online deploy 从已推送 tag 解析 digest，并在 rollout 后运行 helper。
- RED 命令：`bash tests/release/test_builder_tenant_url_smoke.sh`
- RED 结果：退出码 `1`，失败信息为
  `.gitlab-ci.yml is missing: --metadata-file build/metadata.json`。

## GREEN

- `build_release_image` 使用 `--metadata-file build/metadata.json`，从
  `containerimage.digest` 写入
  `BUILDER_IMAGE=${BUILDER_IMAGE_REPOSITORY}@${digest}`，并写入完整
  `DEPLOYED_REVISION=${CI_COMMIT_SHA}`。
- release job 的 backend 与 `copy-frontend-dist` 均使用 dotenv 中的相同
  digest 引用；它将 release dotenv 继续交给
  `release_builder_browser_smoke`。
- 新增 `release_builder_browser_smoke`：
  - 固定 `mcr.microsoft.com/playwright:v1.61.1-noble`；
  - 下载固定 kubectl `v1.30.7`；
  - 使用根 `npm ci` 和 `npm exec -- playwright install msedge`；
  - 配置 kubeconfig 后调用共享 helper。
- 新增 `scripts/verify_builder_tenant_url_smoke.sh`：
  - 所有必需 kubeconfig、受控账号、目标租户 UUID、Code session、revision
    和不可变 image digest 均为 fail-closed 前置条件。
  - 对 selector 匹配的每个 Pod 要求 Ready，检查 backend
    `containerStatuses` 和 dist init `initContainerStatuses` 的 imageID
    digest 与期望 digest 一致。
  - 从每个 web sidecar 的 `/ai-builder/` HTML 读取且仅接受一个
    `builder-build-sha`，并要求等于 `DEPLOYED_REVISION`。
  - 在一个已验证 Pod 内执行
    `python -m app.tenant_public_id reconcile --verify-only-after-write`。
  - 强制根 Playwright `1.61.1` 并通过 `BROWSER_CHANNEL=msedge` 调用既有
    tenant URL Playwright 规格，以覆盖受控登录、候选 token 验证、租户 URL
    对齐与 Code 深链接。
- online deploy 保留 `scripts/build_builder_image.sh` 的 Git archive HEAD
  snapshot 构建方式；推送后解析远程 image digest，使 StatefulSet backend 和
  initContainer 使用 `${IMAGE_REPO}@sha256:...`，并在 rollout 后调用 helper。

已执行并通过：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
bash -n scripts/verify_builder_tenant_url_smoke.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  tests/release/test_builder_tenant_url_smoke.sh
ruby -e 'require "yaml"; YAML.load_file(".gitlab-ci.yml"); puts "gitlab yaml parse OK"'
git diff --check
```

额外 fail-closed 检查通过：在没有 `BUILDER_IMAGE` 等发布输入时 helper 以非零
退出，并只报告缺失环境变量名，不输出密码、token 或 Secret。

## Concerns

- 按任务约束，未连接 Kubernetes、未构建或推送镜像，未执行真实 rollout、Pod
  imageID/HTML 检查、reconciliation 或 Edge 浏览器 smoke。
- CI/online 运行需要预先配置 kubeconfig、受控测试账号、完整 tenant UUID
  集合、Code session/agent session、公开 Builder URL 和 Edge；任意缺失会保持
  fail-closed。
- online 部署环境还必须具备根目录依赖已安装的 Node/Playwright 1.61.1 与 Edge；
  helper 不会为了绕过该前置条件降级浏览器验证。

## 修复波次

### RED

- 扩展 `tests/release/test_builder_tenant_url_smoke.sh` 为动态合同：
  - 解析 GitLab YAML job、needs/artifacts、变量映射和发布前依赖；
  - 从 YAML 提取 metadata Python parser，并以有效/无效 BuildKit metadata 实际执行；
  - fake Podman 验证 `push --digestfile` 返回本次 push digest；
  - fake kubectl 验证多 Pod、selector、container topology、StatefulSet revision、
    image digest、reconcile 计数和日志凭证 canary；
  - 验证线上 release spec 不使用本地 fixture 的 target-C、disabled、unauthorized 或
    delay 输入。
- RED 命令：`bash tests/release/test_builder_tenant_url_smoke.sh`
- RED 结果：退出码 `1`，关键输出：

```text
build job parses metadata directly
```

这证明 BuildKit rootless job 仍直接依赖 `python3`，且不存在独立 metadata
发布链。

### GREEN

- `.gitlab-ci.yml`
  - rootless `build_release_image` 只 push 并产出 `build/metadata.json` artifact；
  - 新增 `publish_release_metadata`，使用可配置
    `$BUILDER_METADATA_PYTHON_IMAGE` 严格校验
    `containerimage.digest` 为 `sha256:<64 hex>`，再写 dotenv；
  - 新增 `release_builder_preflight`，在 `release_and_update_server` 的
    Kubernetes mutation 之前验证 root Playwright 1.61.1、Edge、kubectl context、
    selector 与 StatefulSet container topology；
  - 显式映射 namespace、StatefulSet、backend、dist init、label selector 和 web
    container；默认 selector 为 `app.kubernetes.io/name=ai-builder`，web 为 `web`。
- `scripts/deploy_online_latest_kubesphere.sh`
  - Podman 改为本地 build 后以 `podman push --digestfile` 获取本次 push digest；
  - Docker 仅在 `buildx imagetools` 明确可用时解析 digest，去除不可靠的
    `RepoDigests[0]` fallback；
  - 在任何 Kubernetes 写入前调用 helper `--preflight`；
  - StatefulSet template 增加 `app.kubernetes.io/name=ai-builder` label。
- `scripts/verify_builder_tenant_url_smoke.sh`
  - 使用正式线上输入，并提供 `--preflight`；
  - 验证 provenance floor、公开 `/ai-builder/` SHA、StatefulSet
    current/update revision、逐 Ready Pod controller revision、backend/init imageID
    digest 和 web sidecar SHA；
  - 安全解析 reconciliation `key=value` 输出，仅记录扫描/补齐/零值计数；
  - 采样 backend rollout logs，检测 smoke password、Authorization、JWT-like 与 Cookie，
    且只输出类别和 Pod。
- 新增 `tests/e2e/builder-tenant-url-release-smoke.spec.mjs`：
  - 仅使用线上受控输入；
  - 覆盖登录/必要 tenant selection、available UUID、从另一个租户切换、候选 token
    的显式 `/auth/me`、Code 新 activation endpoint、无旧 endpoint/401、iframe
    tenantId 隔离与最终 URL 对齐。

本波次已执行并通过：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
bash -n scripts/verify_builder_tenant_url_smoke.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  tests/release/test_builder_tenant_url_smoke.sh
node --check tests/e2e/builder-tenant-url-release-smoke.spec.mjs
ruby -e 'require "yaml"; YAML.load_file(".gitlab-ci.yml"); puts "gitlab yaml parse OK"'
git diff --check
```

关键输出：

```text
CI_METADATA_MAPPING=PASS
CI_METADATA_FLOW=PASS
PODMAN_DIGESTFILE=PASS
FAKE_KUBECTL_RELEASE_CONTRACT=PASS
RELEASE_SPEC_CONTRACT=PASS
PASS: builder tenant URL release smoke contract
gitlab yaml parse OK
```

### 本波次 Concerns

- 未连接或修改 Kubernetes，未构建/推送镜像，未执行真实 GitLab runner、受控账号、
  Edge 或线上 Code session smoke。
- 发布前 preflight 会对既有目标 StatefulSet 的
  `app.kubernetes.io/name=ai-builder` selector 和 container topology fail closed；
  历史工作负载若尚无该 label，需先通过受控发布迁移到该标签契约。
- GitLab dotenv artifact 的实际下载与 protected variables 可见性仍需隔离 pipeline
  验证；本地 YAML/metadata parser/fake kubectl 测试未替代真实 runner 证据。

## 第二修复波次

### RED

先扩展 release fake 合同与后端公共合同，覆盖评审 I-1..I-6、M-1：

- 在线 clone/source provenance 必须在 build/push 前通过 floor
  `49a4bef4`，Docker `buildx`/`imagetools` 也必须在 wrapper 前可用；
- fake Podman 检查 wrapper `PUSH=0` 且只执行一次
  `push --digestfile`；fake Docker 检查可用/不可用分支以及不可用时 wrapper
  不得启动；
- fake kubectl 覆盖 fresh namespace、legacy `app=<APP_NAME>` selector、dev/prod
  碰撞 Pod owner、StatefulSet template 与逐 Pod spec image、status imageID；
- reconcile 覆盖缺 key、重复 key、追加换行截断，并检查 password 不进入 grep argv；
- 浏览器完成后才出现的 JSON `Authorization` 与 JSON `Cookie` log canary 必须失败；
- release Code spec 对可选 agent 必须只接受一次且精确匹配该 agent 的 activation。

初始 RED 命令：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
python3 -m pytest -q backend/tests/test_tenant_url_build_contract.py
```

初始 RED 关键输出：

```text
bash: line 3: verify_source_provenance: command not found
FAILED test_online_git_caller_uses_immutable_cli_branches
assert "verify_source_provenance" in text
```

在实现后进一步加入 reconciliation 追加行注入，确认 parser 的首行截断问题：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
```

关键 RED 输出：

```text
FAIL: command unexpectedly succeeded: run_fake_helper
```

### GREEN

- `scripts/deploy_online_latest_kubesphere.sh`
  - 改为非 shallow clone，并在 clone 后、registry login/build/push 前执行
    `git merge-base --is-ancestor 49a4bef4 <full-sha>`；历史不足或 revision
    不合法立即失败。
  - online selector 默认改为现有 StatefulSet/template 的唯一标签
    `app=${APP_NAME}`，dev 与 prod 不再共享
    `app.kubernetes.io/name=ai-builder` selector。
  - Podman 保持 wrapper `PUSH=0`，随后一次
    `podman push --digestfile`；Docker 在 wrapper 前同时验证
    `buildx version` 与 `buildx imagetools inspect --help`，不可用时不 build/push。
  - 新增无 image 的 `--online-prebuild` 输入/工具/provenance/context preflight；
    digest 产生后 `--online-preflight` 对既有 workload 执行严格 topology/image
    检查，对 fresh namespace 仅允许 StatefulSet 缺席，之后才会 apply Kubernetes。
- `scripts/verify_builder_tenant_url_smoke.sh`
  - `--preflight` 保持 CI 严格模式；新增 online 的 prebuild 与允许首次部署模式。
  - StatefulSet template 和每个 Ready Pod 的 backend/dist-init `.image` 必须精确
    等于 digest 形式的 `BUILDER_IMAGE`；所有 selector Pod 还必须由目标
    StatefulSet ownerReference 持有，并继续校验 imageID、controller revision 和
    web SHA。
  - reconciliation 仅接受单行、完整且无重复的六个 `key=value` 字段；严格验证
    数值/list 格式、null list/count、一致性和零值，拒绝缺失、未知、畸形、换行/
    制表符追加输出。
  - password 用 shell 内存比较，不传入 grep/Python argv、输出或临时文件；log
    扫描同时识别 plain/JSON Authorization Bearer、Cookie 与 JWT-like，并在
    browser secret-bearing traffic 前后各扫描一次。命中仅报 category 和 Pod。
- `tests/e2e/builder-tenant-url-release-smoke.spec.mjs` 要求恰好一次新 activation；
  可选 `BUILDER_SMOKE_AGENT_ID` 存在时，path 中 agent 必须精确匹配。
- `tests/release/test_builder_tenant_url_smoke.sh` 增加上述 fake Docker/Podman、
  kubectl 多 Pod、selector collision、fresh/legacy、reconcile 和 secret log
  动态合同；`backend/tests/test_tenant_url_build_contract.py` 将 online caller
  从无条件 `PUSH=1` 公共断言拆为 immutable CLI 分支断言，同时保留 Git archive
  snapshot wrapper 合同。

本波次 GREEN 与规定验证：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
python3 -m pytest -q backend/tests/test_tenant_url_build_contract.py
podman run --rm --entrypoint /bin/sh \
  -v "$PWD:/workspace:ro" \
  -v /mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:/mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:ro \
  -w /workspace \
  om-harbor.dfy.definesys.cn/om-demo/ai-builder:2026.07.20-3f90e08a-runtime-expiry-timezone \
  -lc 'git config --global --add safe.directory /workspace && python -m pytest -q -p no:cacheprovider backend/tests/test_tenant_url_build_contract.py'
bash -n scripts/verify_builder_tenant_url_smoke.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  tests/release/test_builder_tenant_url_smoke.sh
node --check tests/e2e/builder-tenant-url-release-smoke.spec.mjs
ruby -e 'require "yaml"; YAML.load_file(".gitlab-ci.yml"); puts "gitlab yaml parse OK"'
git diff --check
```

关键 GREEN 输出：

```text
ONLINE_BUILD_CLI_BRANCHES=PASS
ONLINE_SOURCE_DOCKER_PREFLIGHT=PASS
ONLINE_SELECTOR_CONTRACT=PASS
FAKE_KUBECTL_RELEASE_CONTRACT=PASS
RELEASE_SPEC_CONTRACT=PASS
28 passed
gitlab yaml parse OK
```

变更文件：

- `scripts/deploy_online_latest_kubesphere.sh`
- `scripts/verify_builder_tenant_url_smoke.sh`
- `tests/release/test_builder_tenant_url_smoke.sh`
- `tests/e2e/builder-tenant-url-release-smoke.spec.mjs`
- `backend/tests/test_tenant_url_build_contract.py`
- `.superpowers/sdd/task-7-report.md`

### 第二修复波次 Concerns

- 严格遵守任务约束：未连接/修改 Kubernetes，未构建或推送镜像，未运行线上账号、
  Edge 或 Code session smoke。
- Builder image 内运行公共合同需要同时只读挂载 linked worktree 与主仓库 `.git`，
  因为该 worktree 的 `.git` 指向主仓库的绝对 gitdir；容器内仅设置临时
  `safe.directory`，未写入宿主仓库。
- GitLab runner 的实际 protected variables、registry、kubeconfig、在线
  Playwright/Edge 与现有 workload topology 仍需在隔离发布 pipeline 中提供真实
  证据；缺失任何输入会按设计 fail closed。

## 最后一轮集中修复

### RED

围绕 review 的 I-1..I-5 先扩展 fake release 合同：

- 健康 StatefulSet 仍为 `D_old`、本轮 `BUILDER_IMAGE=D_new` 时，
  `--preflight` 必须通过；full smoke 的 exact template/Pod/imageID 检查仍必须在
  rollout 后拒绝 `D_new` mismatch。
- fake ingress/service 覆盖 staging origin、错误 backend Service、错误 selector；
  fake RBAC、owner、Ready 和 revision 保持可观察。
- release spec 使用同文件 fake event source，覆盖延迟正确 activation 与 quiet period
  内延迟 duplicate。
- raw compact JWT `eyJhbGciOiJIUzI1NiJ9.e30.<signature>` 必须触发 log gate。
- fake kubectl 覆盖 online smoke fail 后的 existing rollback、rollback rollout 二次
  失败、fresh Ingress-first cleanup，以及从 GitLab YAML 提取的 CI update/browser
  script 捕获 old pair、set new、browser failure 后回滚 old pair。
- `registry:tag` previous image ref 必须拒绝，不能作为 rollback target。

初始动态 RED：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
```

关键输出：

```text
[builder-release-smoke][fail] StatefulSet backend image mismatch
```

这证明旧实现把 `D_old` 当前 template 错误地与本轮 `D_new` 比较，阻塞正常升级。

随后 mutable rollback target 的 RED：

```text
FAIL: command unexpectedly succeeded: bash -c
source "$1/scripts/deploy_online_latest_kubesphere.sh"
capture_previous_workload
```

### GREEN

- `scripts/verify_builder_tenant_url_smoke.sh`
  - preflight 现在只验证输入、origin host、provenance、kubectl context/RBAC、
    StatefulSet container topology、Ingress/Service/selector binding、selector Pod
    owner/Ready 与 currentRevision/updateRevision health；不比较旧 image 与新 digest。
  - full smoke 才检查 StatefulSet template、每个 Pod spec 和 imageID 均为本轮
    `BUILDER_IMAGE`；rollback mode 则以 captured old backend/init digest refs 检查
    template、Pod Ready/owner 和 revision health。
  - 新增 `KUBE_EXPECTED_HOST`、`KUBE_INGRESS`、`KUBE_SERVICE`、
    `KUBE_INGRESS_PATH`。origin hostname 必须匹配 expected host，指定 Ingress 的
    host/path backend 必须指向指定 Service，Service selector 必须精确等于
    `KUBE_LABEL_SELECTOR`。
  - compact JWT 检测改为现实的三段 base64url 下限，短 `{}` payload 也 fail closed。
- `tests/e2e/builder-tenant-url-release-smoke.spec.mjs`
  - 导航前创建 expected activation promise；等待目标 session/optional agent 的 200，
    iframe/src、document ready/body visible 后继续 2 秒 quiet period，再严格断言一次
    activation、无 legacy activation/401。
  - 提供 `RELEASE_SMOKE_ACTIVATION_CONTRACT=1` fake event-source mode，动态证明慢
    正确 response 不 false-fail，quiet period 内 duplicate 不 false-pass。
- `.gitlab-ci.yml`
  - 固定 production resource binding defaults：
    `orcamatrix-demo` / `om-demo.dfy.definesys.cn` / Ingress `ai-builder` /
    Service `ai-builder` / `/ai-builder`，并映射到 preflight/browser helper。
  - `release_and_update_server` 在 set image 前读取 old backend/init exact digest refs，
    拒绝 mutable refs，并追加 `PREVIOUS_*` 到 downstream dotenv artifact。
  - browser smoke 失败时恢复 old pair、等待 rollout、调用 helper rollback verifier；
    rollback 二次失败显式报错，成功 rollback 后仍以原 smoke 非零退出。
- `scripts/deploy_online_latest_kubesphere.sh`
  - 传递 online origin/resource binding；workload mutation 前记录 existing workload
    与 immutable old pair。
  - downstream smoke/rollout 失败时：existing workload restore old pair 并验证；
    fresh workload 先删除 Ingress 停止流量，再删除本轮 StatefulSet/Services 并确认
    资源不存在，不删除 namespace、Secret 或 PVC。
  - `rollout_and_verify` 以显式返回值传播 rollout/smoke failure；最终失败日志仍标识
    本轮 immutable `IMAGE`。

本轮 GREEN 与最终验证命令：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
python3 -m pytest -q backend/tests/test_tenant_url_build_contract.py
podman run --rm --entrypoint /bin/sh \
  -v "$PWD:/workspace:ro" \
  -v /mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:/mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:ro \
  -w /workspace \
  om-harbor.dfy.definesys.cn/om-demo/ai-builder:2026.07.20-3f90e08a-runtime-expiry-timezone \
  -lc 'git config --global --add safe.directory /workspace && python -m pytest -q -p no:cacheprovider backend/tests/test_tenant_url_build_contract.py'
bash -n scripts/verify_builder_tenant_url_smoke.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  tests/release/test_builder_tenant_url_smoke.sh
node --check tests/e2e/builder-tenant-url-release-smoke.spec.mjs
ruby -e 'require "yaml"; YAML.load_file(".gitlab-ci.yml"); puts "gitlab yaml parse OK"'
git diff --check
```

关键 GREEN 输出：

```text
FAKE_KUBECTL_RELEASE_CONTRACT=PASS
ONLINE_ROLLBACK_CONTRACT=PASS
CI_ROLLBACK_CONTRACT=PASS
ACTIVATION_OBSERVER_CONTRACT=PASS
PASS: builder tenant URL release smoke contract
28 passed
```

### 最后一轮 Concerns

- 严格遵守限制：未连接/修改真实 Kubernetes，未 build/push image，未执行线上账号、
  Edge 或 Code session smoke。
- GitLab runner 的实际 kubeconfig/RBAC、Ingress JSONPath/go-template 兼容性、protected
  variables、registry 与真实 browser installation 仍需要隔离 release pipeline
  证据。任一缺失/拓扑不一致会 fail closed。
- rollback 仅恢复 captured immutable backend/init refs；fresh cleanup 有意保留
  namespace、ConfigMap、Secret 和 PVC，避免删除共享或持久化资源。

## 架构收敛修复

### RED

多轮 rollback 修补暴露 shared release state 与 full apply 的架构问题后，先扩展
`tests/release/test_builder_tenant_url_smoke.sh` 的 fake Kubernetes 合同，再修改发布实现。

初始 RED：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
```

关键输出：

```text
FAIL: command unexpectedly succeeded: run_fake_helper --preflight
```

该命令使用 `https://builder.example:443@staging.example`。旧 helper 的手写 authority
拆分错误地接受生产 host 前缀，而标准 URL 解析实际会访问 `staging.example`。

扩展后的动态合同还覆盖：

- `D_old -> D_new` preflight 不比较旧 template image，full smoke 仍拒绝新 digest mismatch；
- CI update job 的 set/rollout failure 在同一 job rollback，artifact 为 `when: always`；
- browser smoke 在 lock owner/target 与 template 仍为本轮 `D_new` 时才可 rollback；
  模拟 B 已切到另一 digest 时，A 被 CAS 拒绝且保留 lock；
- A 持锁期间 B update job 无法写 StatefulSet；
- online 首次安装/StatefulSet 缺失发生在 build/push 前失败；
- online set、rollout、smoke 三种失败都只恢复 captured old image pair；
- online fake command log 无 `apply`、Ingress/Service 删除或 fresh cleanup；
- compact `alg=none` 空签名 JWT 被日志 gate 拒绝；
- activation observer 从导航前开始，覆盖 owner 声明的最大 retry delay 加 safety margin，
  边界内 delayed duplicate 必须失败。

### GREEN

- `scripts/deploy_online_latest_kubesphere.sh` 现在只支持已存在、已绑定正确的
  StatefulSet image update。严格 existing-workload preflight 在 registry mutation
  前执行；缺 StatefulSet 明确提示 bootstrap 流程。删除了 namespace、ConfigMap、
  Secret、PVC、Service、Ingress 与 manifest full apply/fresh cleanup 路径。
- CI 与 online 都使用同 namespace `${STATEFULSET}-release-lock` ConfigMap，记录
  owner、target immutable image、previous backend/init refs 与 acquired timestamp。
  create 是原子获取；已有 lock 保持 fail-closed 并提示人工恢复；成功或 verified rollback
  仅 owner 可删除。
- CI update job 在 set/rollout failure 内完成 lock CAS、old pair rollback、rollout、
  template/Pod health 验证与 lock release；browser job 先验证 lock，再在 smoke failure
  时用 owner+target+template CAS rollback。CAS 不匹配时拒绝覆盖。
- online 所有 StatefulSet image mutation 在 lock guard 内；capture、set、rollout 或
  smoke 失败均走同一 existing-workload recovery。rollback 仍使用 immutable old refs，
  不会更改任何非 image 资源。
- helper 使用 Node `URL` 从环境读取 origin，拒绝 userinfo、path、query、fragment，
  并精确比较 `KUBE_EXPECTED_ORIGIN`；随后继续校验 Ingress path->Service 与 Service
  selector。compact JWT 的第三段允许为空。
- `frontend/src/api/codeRuntime.ts` 导出
  `CODE_RUNTIME_ACTIVATION_RETRY_DELAYS_MS = [] as const`。release smoke 从该 owner
  读取 schedule，而不是使用任意 quiet timeout；未来增加 client retry 时必须同步更新
  owner，release contract 才会继续覆盖最大 retry boundary。
- `backend/tests/test_tenant_url_build_contract.py` 新增 online existing-workload
  image-only 合同，禁止 full apply/bootstrap 资源写入，并验证 prebuild、lock/CAS 与
  two-image mutation 主路径。

本轮 GREEN 与验证：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
python3 -m pytest -q backend/tests/test_tenant_url_build_contract.py
podman run --rm --entrypoint /bin/sh \
  -v "$PWD:/workspace:ro" \
  -v /mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:/mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:ro \
  -w /workspace \
  om-harbor.dfy.definesys.cn/om-demo/ai-builder:2026.07.20-3f90e08a-runtime-expiry-timezone \
  -lc 'git config --global --add safe.directory /workspace && python -m pytest -q -p no:cacheprovider backend/tests/test_tenant_url_build_contract.py'
npm --prefix frontend test -- --run src/api/codeRuntime.proxy.spec.ts --reporter=dot
bash -n scripts/verify_builder_tenant_url_smoke.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  tests/release/test_builder_tenant_url_smoke.sh
node --check tests/e2e/builder-tenant-url-release-smoke.spec.mjs
ruby -e 'require "yaml"; YAML.load_file(".gitlab-ci.yml"); puts "GitLab YAML parse: PASS"'
git diff --check
```

关键输出：

```text
CI_UPDATE_LOCK_CONTRACT=PASS
ONLINE_IMAGE_ONLY_CONTRACT=PASS
ACTIVATION_OBSERVER_CONTRACT=PASS
PASS: builder tenant URL release smoke contract
29 passed
Test Files 1 passed
GitLab YAML parse: PASS
```

### 架构收敛 Concerns

- 本轮严格未连接/修改真实 Kubernetes，未构建或推送镜像，未运行线上受控账号、
  Playwright Edge 或 Code session smoke。
- ConfigMap lock 的实际 RBAC、跨 runner 生命周期和人工 stale-lock 恢复流程仍需在
  隔离 release pipeline 验证；实现不会自动抢占已有 lock。
- 真实 Ingress controller/DNS、registry digest、protected variables 与 Kubernetes
  JSONPath 的环境行为仍需在受控线上演练中提供证据；任一不匹配保持 fail-closed。

## 锁生命周期最终修复

### RED

先扩展 `tests/release/test_builder_tenant_url_smoke.sh` 的 YAML/fake-kubectl 动态合同：

- CI/online 必须先原子创建只含 owner、target、acquired timestamp 的 lock，之后才可
  读取 StatefulSet UID/resourceVersion 与 previous backend/init immutable refs；
- lock patch 必须保存已验证的 UID/resourceVersion/previous pair；set image 前重新读取
  UID/resourceVersion/template pair，任何漂移都只能释放本 owner 的 lock 并失败；
- A 在锁外等待、B 完整 D0->D1 并释放后，A 的失败 D2 只能回滚 D1；
- browser smoke/setup/artifact handoff 失败必须保留 lock，由无 dotenv 输入的
  `when: always` recovery job 从 ConfigMap 读取 baseline 回滚；
- recovery 覆盖 no-lock no-op、foreign lock 不动、成功 browser 释放后 no-op 和
  rollback rollout 二次失败保留 lock。

初始 RED：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
```

关键输出：

```text
key not found: "release_builder_recovery"
```

这证明旧 CI 没有独立 recovery owner。其后 YAML 动态断言还捕获了旧 update path
在 lock 之前读取 previous pair；fake interleave 会把失败 D2 错误地恢复到 D0。

### GREEN

- `scripts/deploy_online_latest_kubesphere.sh`
  - lock 初始创建不再携带 previous refs；成功获取后捕获 StatefulSet UID、
    resourceVersion 和 immutable previous pair，再 patch 回 lock。
  - set image 前按 lock 中 baseline 重读 UID/resourceVersion/template pair；漂移时
    owner-only 释放 lock 并在 mutation 前失败。
  - rollback 从 lock 重新读取 previous pair，并以 owner、target、StatefulSet UID 和
    current target template 作 CAS，避免使用早期 shell 变量。
- `.gitlab-ci.yml`
  - `release_and_update_server` 采用同一 lock-first baseline 协议，set/rollout failure
    仍在原 job 完成 rollback。
  - browser job 不再竞争 rollback；它只验证 owner/target/template、运行 smoke，并在
    成功后释放 lock。
  - 新增固定 `kubectl:1.30.7` 的 `release_builder_recovery` recovery stage/job，
    `when: always` 且不消费 browser dotenv/artifact。它只用 kubeconfig、当前 pipeline
    owner 和 ConfigMap baseline 做 CAS rollback/rollout/health verification；foreign 或
    stale lock 保持 fail-closed。
- `scripts/verify_builder_tenant_url_smoke.sh` preflight 增加 `patch configmaps` 与
  `patch statefulsets` RBAC 检查。
- fake contract 增加 StatefulSet UID/resourceVersion、ConfigMap patch、D0/D1/D2
  interleave、browser setup/artifact failure、foreign lock、successful release/no-op 和
  recovery failure 的可执行覆盖。

本轮 GREEN 与验证：

```bash
bash tests/release/test_builder_tenant_url_smoke.sh
python3 -m pytest -q backend/tests/test_tenant_url_build_contract.py
podman run --rm --entrypoint /bin/sh \
  -v "$PWD:/workspace:ro" \
  -v /mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:/mnt/d/workspaces/d-ai-code/apaas-builder-ai/.git:ro \
  -w /workspace \
  om-harbor.dfy.definesys.cn/om-demo/ai-builder:2026.07.20-3f90e08a-runtime-expiry-timezone \
  -lc 'git config --global --add safe.directory /workspace && python -m pytest -q -p no:cacheprovider backend/tests/test_tenant_url_build_contract.py'
bash -n scripts/verify_builder_tenant_url_smoke.sh \
  scripts/deploy_online_latest_kubesphere.sh \
  tests/release/test_builder_tenant_url_smoke.sh
node --check tests/e2e/builder-tenant-url-release-smoke.spec.mjs
ruby -e 'require "yaml"; YAML.load_file(".gitlab-ci.yml"); puts "GitLab YAML parse: PASS"'
git diff --check
```

关键 GREEN 输出：

```text
CI_RECOVERY_CONTRACT=PASS
CI_UPDATE_LOCK_CONTRACT=PASS
ONLINE_LOCK_BASELINE_INTERLEAVE=PASS
PASS: builder tenant URL release smoke contract
29 passed
GitLab YAML parse: PASS
```

### 最终修复 Concerns

- 按约束未连接/修改真实 Kubernetes、未构建或推送镜像、未运行线上账号、Edge 或 Code
  session smoke。
- runner 进程丢失、取消或 kubeconfig/recovery job 自身无法启动时仍会留下 fail-closed
  lock，必须由人工按 lock 的 owner/target/baseline 信息恢复；实现不会自动抢占 stale
  lock。
- 真实 GitLab stage failure/cancellation、ConfigMap RBAC、StatefulSet
  resourceVersion 行为和跨 runner 资源组调度仍需在隔离 release pipeline 中演练。
