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
