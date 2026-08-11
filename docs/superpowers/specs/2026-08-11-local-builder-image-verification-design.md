---
asset_id: spec.2026-08-11-local-builder-image-verification
asset_kind: spec
knowledge_level: L1
phase_id: 2026-08-11-local-builder-image-verification
revision: 1
status: ready_for_review
change_type: added
source_section_refs:
  - "Builder 本地镜像验证模式设计"
relations: []
---

# Builder 本地镜像验证模式设计

**Spec ID**：`2026-08-11-local-builder-image-verification`  
**日期**：2026-08-11  
**状态**：设计已确认，对抗评审已闭合，待用户评审  
**主仓库**：`apaas-builder-ai`

## 1. 背景与问题

当前仓库已有两个不同职责的入口：

- `scripts/build_builder_image.sh` 从当前 Git `HEAD` 的归档快照构建镜像，并可由
  `PUSH=1` 进入推送路径。
- `scripts/deploy_online_latest_kubesphere.sh` 克隆代码、登录或复用镜像仓库凭据、推送
  镜像、读取并修改 Kubernetes 工作负载、执行发布锁和线上 smoke。

日常开发还需要一个更窄的“B 模式”：只验证当前提交能否在本机构建为镜像，并证明该
镜像存在于本地容器引擎。该模式不能因为调用者环境中残留 `PUSH=1`、镜像仓库凭据、
`KUBECONFIG` 或发布变量而扩大为推送或发布。

## 2. 已确认决策

1. 新增独立入口 `scripts/verify_local_builder_image.sh`，不改变线上发布入口语义。
2. 标准调用方式固定为：

   ```bash
   bash scripts/verify_local_builder_image.sh
   ```

3. 该入口只做本地构建和本地 `image inspect`，保留构建出的本地镜像。
4. 该入口强制使用 `PUSH=0`，调用者不能通过环境变量重新开启推送。
5. 该入口不读取、不调用、不 source `scripts/deploy_online_latest_kubesphere.sh`，也不
   复用其中的 Kubernetes、发布锁、镜像仓库登录、推送或线上 smoke 函数。
6. 本地验证支持 Docker 和 Podman；当前开发机的真实验证使用 `/usr/bin/podman`。

## 3. 目标

1. 用单一命令验证当前 `HEAD` 对应源码能够构建 `linux/amd64` 本地镜像。
2. 构建过程复用现有 `scripts/build_builder_image.sh`，继续从 Git archive 快照构建，
   不复制 Docker 构建参数和上下文准备逻辑。
3. 无论调用者环境如何设置，入口自身都不登录镜像仓库、不推送镜像、不访问 Kubernetes、
   不修改线上发布状态。
4. 构建结果以权限受限、机器可读的 JSON 文件记录，成功与受控失败均可诊断。
5. 检测构建前后的 `HEAD` 变化，避免结果文件声称的源码 SHA 与实际归档来源不一致。
6. 不修改 staged、unstaged、untracked 或 ignored 工作区内容。

## 4. 非目标

- 不发布镜像到任何远程仓库。
- 不登录或验证镜像仓库凭据。
- 不创建、读取、更新或删除任何 Kubernetes 资源。
- 不执行线上预检、线上 smoke、发布锁、工作负载轮询或回滚。
- 不替代 `scripts/deploy_online_latest_kubesphere.sh` 的发布职责。
- 不清理本地镜像，不管理本地镜像保留周期。
- 不保证调用者指定的 Docker/Podman 可执行文件自身没有额外副作用；入口只接受受信任的
  本地容器 CLI，保证脚本不会主动请求登录、推送或 Kubernetes 操作。
- 不构建未提交工作区内容；构建来源仍固定为当前 Git `HEAD`。

## 5. 入口与输入契约

### 5.1 入口参数

入口不新增位置参数。允许以下环境变量：

| 变量 | 默认值 | 约束 |
| --- | --- | --- |
| `CONTAINER_CLI` | `docker` | 可执行文件 basename 必须严格等于 `docker` 或 `podman`，且 `command -v` 可解析 |
| `IMAGE` | `apaas-builder-local:<sha12>` | 本地镜像标签；只传给本地 build 与 inspect，不用于登录或推送 |
| `PLATFORM` | `linux/amd64` | 若调用者显式设置为其他值，立即以 `invalid_platform` 失败 |
| `REPO_ROOT` | 脚本目录的父目录 | 规范化后必须是包含当前脚本和 `deploy/docker/Dockerfile` 的 Git worktree |
| `RESULT_FILE` | 见 5.2 | 测试可覆盖；必须位于固定临时根目录内，父目录由入口创建 |

共享构建脚本已有的以下构建定制变量允许继承，语义与共享脚本一致：

```text
VITE_BASE_URL
VITE_ADMIN_BASE
VITE_API_BASE_URL
VITE_MCP_PUBLIC_BASE
NODE_IMAGE
JDK8_IMAGE
JDK17_IMAGE
MAVEN_IMAGE
PYTHON_IMAGE
DOCKER_CLI_IMAGE
NPM_REGISTRY
PIP_INDEX_URL
```

这些变量只改变本地构建参数和只读依赖来源。入口不承诺离线或字节级可重复构建；标准命令
未设置它们时继续使用 `build_builder_image.sh` 的当前默认值。

`DOCKER_USERNAME`、`DOCKER_PASSWORD`、`KUBECONFIG`、`KUBE_CONTEXT`、
`DEPLOY_TARGET`、`NAMESPACE`、`PUSH` 及其他发布变量都不属于本入口输入。即使调用者注入
这些变量，入口也不得基于其值增加动作或把值写入结果文件。

### 5.2 结果路径

默认结果路径为：

```text
/tmp/d-ai-code/apaas-builder-local-verify/<run-id>/result.json
```

`run-id` 由 UTC 时间、当前进程 ID 和安全随机后缀组成，仅用于避免并发运行互相覆盖。
父目录权限为 `0700`，最终文件权限为 `0600`。入口先在同一父目录创建临时文件，完整
写入并 `chmod 0600` 后使用原子 rename 替换目标文件。

当 `RESULT_FILE` 被覆盖时仍使用相同的临时文件、权限和原子替换规则。入口拒绝相对路径，
避免结果位置受调用目录影响。规范化后的目标必须严格位于：

```text
/tmp/d-ai-code/apaas-builder-local-verify/
```

并且不得位于 `REPO_ROOT`。固定根目录、目标父目录到结果文件的任何已存在路径组件不得是
符号链接；目标不得是目录或符号链接。入口创建的 run 目录权限为 `0700`；复用既有父目录
时要求 owner 为当前有效用户，且 group/other 不可写，否则以 `result_write_failed` 失败。

成功或受控失败结果完成原子替换后，入口向 stdout 恰好输出一条机器可解析的 locator：

```text
result_path=<absolute-path>
```

构建日志可以先于该行出现，但 `result_path=` 前缀在单次运行中只能出现一次。结果文件无法
写入时，不输出成功 locator，只向 stderr 输出
`result_write_failed result_path=<absolute-path>`。

## 6. 执行流程

### 6.1 前置校验

入口按以下顺序执行，任何一步失败都不得启动容器构建：

1. 记录 `started_at`，只读解析 `RESULT_FILE` 或生成默认结果路径，不创建目录或文件。
2. 只读解析 `REPO_ROOT`。使用能够解析既有符号链接并规范化缺失尾部组件的路径方法，得到
   比较用绝对路径；该步骤不得要求目标已经是有效 Git worktree。
3. 在首次文件系统写入前，检查结果路径位于固定临时根目录、已存在路径组件不是符号链接，
   且规范化结果路径不等于、也不位于规范化 `REPO_ROOT`。任一检查失败时只向 stderr 报告
   `result_write_failed`，不得创建仓库内目录、临时文件或 JSON。
4. 路径隔离通过后，按 5.2 创建安全结果上下文。这是本入口首次允许的文件系统写入。
5. 验证 `REPO_ROOT` 是 Git worktree，并包含：
   - `scripts/verify_local_builder_image.sh`
   - `scripts/build_builder_image.sh`
   - `deploy/docker/Dockerfile`
6. 读取完整小写 40 位 `HEAD` 为 `source_sha`。
7. 校验 `CONTAINER_CLI` basename 和可执行性。
8. 校验 `PLATFORM` 严格等于 `linux/amd64`。
9. 若调用者未设置 `IMAGE`，使用
   `apaas-builder-local:${source_sha:0:12}`。
10. 校验 `IMAGE` 非空、不以 `-` 开头且不包含 ASCII 空白或控制字符。

### 6.2 构建调用

入口只允许以下调用关系：

```text
verify_local_builder_image.sh
  -> PUSH=0 EXPECTED_BUILD_SHA=<source_sha> scripts/build_builder_image.sh
  -> <docker|podman> image inspect <image>
```

调用 `scripts/build_builder_image.sh` 时，入口必须显式覆盖并传递：

```text
REPO_ROOT=<normalized repo root>
CONTAINER_CLI=<validated executable>
IMAGE=<resolved local image>
PLATFORM=linux/amd64
PUSH=0
EXPECTED_BUILD_SHA=<captured source_sha>
```

不得用 `env` 透传方式把 `PUSH` 的外部值保留下来，也不得根据 Docker/Podman 类型切换到
`buildx --push`、`push` 或 `imagetools`。

5.1 列出的构建定制变量由入口显式读取并传给共享脚本，使可继承输入集合可审计；其他发布
变量不传入行为判断。新增或删除共享构建脚本输入时，必须同步更新该白名单和契约测试。

### 6.3 构建脚本兼容增强

`scripts/build_builder_image.sh` 新增可选环境变量 `EXPECTED_BUILD_SHA`：

- 未设置时保持当前行为和现有调用方兼容性。
- 设置时必须是完整小写 40 位 Git SHA，否则构建在容器 CLI 调用前失败。
- 脚本读取当前 `HEAD` 后，要求它与 `EXPECTED_BUILD_SHA` 完全一致。
- 不一致时输出不含敏感值的稳定错误前缀，并以专用非零退出码 `42` 结束。
- 通过校验后仍使用该 `HEAD` 执行 `git archive`，不得改为构建工作区目录。

专用退出码使上层入口能够把竞态准确归类为 `head_changed`，而不是依赖解析自然语言日志。
已有未设置 `EXPECTED_BUILD_SHA` 的发布和 CI 调用不改变退出码或行为。

### 6.4 构建后校验

构建命令成功后：

1. 再次读取完整 `HEAD`。
2. 若与 `source_sha` 不一致，以 `head_changed` 失败，不执行 inspect。
3. 执行且只执行一次：

   ```bash
   "$CONTAINER_CLI" image inspect --format '{{.Id}}' "$IMAGE"
   ```

   Docker 与 Podman 均使用 `.Id` 模板。fake CLI 测试必须按参数数组逐项核对，不允许通过
   shell 拼接或 `eval` 执行。
4. inspect 退出码必须为 0，且输出经去除首尾空白后必须严格匹配
   `sha256:[0-9a-f]{64}`，不得包含第二行。
5. 再次读取 `HEAD`；若已变化，以 `head_changed` 失败，不写成功结果。
6. 写入成功结果并返回 0。

inspect 只证明镜像存在于当前本地容器引擎。`platform` 字段记录本次固定构建请求平台，
不把远程 manifest 或 registry 查询作为成功条件。

## 7. 状态、退出与恢复语义

该入口没有持久化任务状态和自动恢复。每次调用都是独立运行：

- 成功：保留本地镜像，写 `status=succeeded`，退出 0。
- 受控失败：不重试、不推送、不清理调用者既有镜像，尽力写 `status=failed`，退出非 0。
- 再次运行：创建新的默认 `run-id`；当调用者复用同一 `RESULT_FILE` 时，原子替换上一份
  完整结果，不追加、不合并。

脚本不删除构建失败时容器引擎可能留下的缓存层；这属于容器引擎本地缓存管理，不属于发布
副作用。

异步信号和宿主进程强制终止不属于受控失败合同。入口不承诺在 `SIGINT`、`SIGTERM`、
`SIGKILL`、终端关闭或宿主崩溃后生成结果 JSON，也不实现独立的进程组终止器。此时容器 CLI
按其自身信号语义退出；后续重新运行会创建新的 run。实现不得在结果中宣称已终止容器引擎
的所有后代进程。

## 8. 结果 JSON 契约

### 8.1 写入方式

结果必须由 Python 标准库 `json` 序列化，不允许用 shell 字符串拼接 JSON。时间使用 UTC
RFC 3339 格式，精确到秒并以 `Z` 结尾。所有字段固定存在，未知值使用空字符串，不使用
`null`。

```json
{
  "schema_version": "apaas-builder-local-image-verification/v1",
  "status": "succeeded",
  "source_sha": "0123456789abcdef0123456789abcdef01234567",
  "image": "apaas-builder-local:0123456789ab",
  "image_id": "sha256:example",
  "platform": "linux/amd64",
  "container_cli": "podman",
  "push_permitted": false,
  "kubernetes_access_permitted": false,
  "started_at": "2026-08-11T08:00:00Z",
  "finished_at": "2026-08-11T08:01:00Z",
  "error_code": "",
  "result_path": "/tmp/d-ai-code/apaas-builder-local-verify/example/result.json"
}
```

`container_cli` 只记录校验后的 basename，不记录可能包含本机目录信息的完整路径。

### 8.2 稳定错误码

| 错误码 | 触发条件 |
| --- | --- |
| `invalid_container_cli` | CLI basename 非 `docker`/`podman`，或命令不可执行 |
| `invalid_platform` | `PLATFORM` 不是 `linux/amd64` |
| `invalid_repo_root` | 仓库路径、Git worktree 或必需文件校验失败 |
| `invalid_head_sha` | `HEAD` 不是完整小写 40 位 SHA |
| `invalid_image` | `IMAGE` 为空、以 `-` 开头或包含 ASCII 空白/控制字符 |
| `head_changed` | 捕获后、构建脚本读取时、构建完成后或 inspect 完成后发现 `HEAD` 改变 |
| `build_failed` | 共享构建脚本除专用 SHA 竞态外返回非零 |
| `image_inspect_failed` | 本地 inspect 失败或未得到非空单行 image ID |
| `result_write_failed` | 结果目录、临时文件、权限设置、序列化或原子替换失败 |

若失败发生在 `source_sha`、`image` 或 `image_id` 形成前，对应字段写空字符串。若无法创建
任何结果文件，stderr 必须包含 `result_write_failed` 和预期结果路径，但不得打印环境变量
或凭据值。

### 8.3 失败字段矩阵

除 `result_write_failed` 外，所有受控失败都必须生成 JSON、输出一次 locator，并遵循下表。
`valid` 表示写入已经通过校验的实际值，空字符串表示固定写 `""`，不得记录非法原始输入。

| `error_code` | `source_sha` | `image` | `image_id` | `platform` | `container_cli` |
| --- | --- | --- | --- | --- | --- |
| `invalid_repo_root` | `""` | `""` | `""` | `""` | `""` |
| `invalid_head_sha` | `""` | `""` | `""` | `""` | `""` |
| `invalid_container_cli` | valid | `""` | `""` | `""` | `""` |
| `invalid_platform` | valid | `""` | `""` | `""` | valid |
| `invalid_image` | valid | `""` | `""` | valid | valid |
| `head_changed` | valid | valid | `""` | valid | valid |
| `build_failed` | valid | valid | `""` | valid | valid |
| `image_inspect_failed` | valid | valid | `""` | valid | valid |

所有失败行还必须固定：`status="failed"`、`push_permitted=false`、
`kubernetes_access_permitted=false`、`finished_at` 为实际完成时间、`result_path` 为当前安全
目标路径。`result_write_failed` 是唯一允许没有 JSON 和 locator 的稳定错误；它只使用 5.2
规定的 stderr 诊断。

### 8.4 禁止字段与敏感信息

结果 JSON 不得包含以下键，也不得嵌入对应值：

```text
environment
docker_config
username
password
token
kubeconfig
command_stdout
command_stderr
```

入口不得把完整环境、容器登录配置、命令标准输出或标准错误收集进结果文件。容器构建日志
保持原样输出到当前终端，由调用者自行决定是否留存。

## 9. 无副作用边界

### 9.1 远程系统

入口及其直接调用链中不得出现或执行：

- `login`
- `push`
- `buildx build --push`
- `buildx imagetools`
- `kubectl`
- Kubernetes API、release lock 或线上 smoke helper

静态检查用于证明独立入口没有引用发布脚本和上述操作；动态 fake CLI 用于证明成功、构建
失败和 inspect 失败路径都没有记录这些调用。

本模式禁止镜像仓库认证、推送和其他远程写操作，但不承诺离线构建。冷缓存时 Dockerfile
可以只读拉取基础镜像，并通过 npm、pip、apt、curl 等读取依赖；这些读取受当前共享构建脚本
和调用者网络配置约束。若后续需要完全离线验证，应另立 Spec 定义镜像缓存、依赖镜像、网络
隔离和离线失败码，不得把本模式的“无推送”解释为“无网络读取”。

### 9.2 Git 工作区

入口只能执行只读 Git 操作：`rev-parse` 和由共享构建脚本执行的 `git archive`。它不得执行
`add`、`commit`、`checkout`、`switch`、`reset`、`clean`、`stash`、`rebase` 或修改文件。

测试必须在运行前后比较：

- `git status --porcelain=v1 -z` 的完整字节序列。
- staged 与 unstaged 文件内容 checksum。
- untracked 与 ignored 哨兵文件内容 checksum。

任何差异都视为测试失败。

## 10. 文件责任与兼容边界

实现只允许修改或新增：

```text
scripts/verify_local_builder_image.sh
scripts/build_builder_image.sh
backend/tests/test_local_builder_image_verification.py
```

不得修改线上发布脚本。新测试文件独立创建，因为
`backend/tests/test_tenant_url_build_contract.py` 已超过 500 行，不再承载新职责。

`scripts/build_builder_image.sh` 的兼容性要求：

- 未设置 `EXPECTED_BUILD_SHA` 时，现有默认镜像、平台、`PUSH=0/1` 和调用方式保持不变。
- 线上发布脚本、CI、文档中的既有调用不需要增加新变量。
- 新增逻辑只在容器 CLI 调用前增加可选 SHA 断言，不改变 Dockerfile、构建参数或归档内容。

## 11. 测试设计

新增 `backend/tests/test_local_builder_image_verification.py`，使用临时 Git 仓库和 fake CLI，
不依赖真实镜像仓库或 Kubernetes。

### 11.1 成功路径

1. fake Docker：只允许一次 `build` 和一次 `image inspect`，结果为成功 JSON。
2. fake Podman：同样只允许一次 `build` 和一次 `image inspect`。
3. `PUSH=1` 注入：调用日志仍不得包含 `push`、`--push` 或 `imagetools`。
4. 注入凭据哨兵：`DOCKER_USERNAME`、`DOCKER_PASSWORD` 不触发 login，结果文件不包含哨兵值。
5. PATH 中提供 fake `kubectl`：其调用日志保持空文件或不存在。
6. 默认 image 标签使用捕获 SHA 的前 12 位，平台严格为 `linux/amd64`。
7. 5.1 的构建定制变量按白名单逐项传递；未列出的发布变量不改变调用动作。
8. 成功报告可由 Python `json` 解析，权限严格为 `0600`，stdout 只有一个
   `result_path=` locator。

### 11.2 失败路径

1. CLI basename 非法或不可执行，返回 `invalid_container_cli`，没有 build 调用。
2. 平台非法，返回 `invalid_platform`，没有 build 调用。
3. 仓库根或 HEAD 非法，分别返回 `invalid_repo_root`、`invalid_head_sha`。
4. 共享构建脚本返回普通非零，返回 `build_failed`，不执行 inspect。
5. inspect 返回非零、空输出或多行输出，返回 `image_inspect_failed`。
6. 在入口捕获 SHA 后、共享脚本校验前改变 `HEAD`，共享脚本退出 42，入口返回
   `head_changed`。测试通过 PATH 前置 fake `git`，把非目标调用委托给真实 Git，并按
   `rev-parse HEAD` 调用序号创建一次新 commit，禁止用 sleep 碰撞竞态窗口。
7. 构建成功后或 inspect 完成后改变 `HEAD`，入口返回 `head_changed`，不得写成功状态。
   fake CLI 使用 marker 文件和 release FIFO/文件作为确定性屏障：测试看到 marker 后改变
   HEAD，再释放 build 或 inspect 返回。
8. 所有可生成 JSON 的稳定错误码使用参数化失败矩阵，逐项断言：非零退出、精确键集合、
   字段类型、无 `null`、`status=failed`、权限 `0600`、禁止键和凭据哨兵不存在、registry /
   Kubernetes / release-lock 日志为空，并逐项匹配 8.3 的字段值。
9. 结果路径位于仓库、目标或父目录为符号链接、父目录 owner/权限不安全时，以
   `result_write_failed` 失败，工作区内容不变。
   仓库内尚不存在的父目录也必须覆盖，断言路径包含关系检查发生在任何 `mkdir` 或临时文件
   写入之前。
10. 用固定根目录下“父路径是普通文件”的 fixture 确定性制造 `ENOTDIR`，断言 stderr 包含
    稳定错误码和目标路径、无敏感值、无残留临时文件。

### 11.3 静态边界

1. 独立入口不引用 `deploy_online_latest_kubesphere.sh`、发布锁或线上 smoke helper。
2. 独立入口源码不包含 `kubectl` 调用、容器 login、push、`--push` 或 `imagetools` 调用。
3. 共享构建脚本仅在 `PUSH=1` 的既有分支包含推送能力；独立入口测试必须证明传入值固定为 0。
4. fake registry、fake Kubernetes 和 fake release-lock 日志在所有场景均为空。
5. 运行前后 staged、unstaged、untracked、ignored 内容和状态完全不变。
6. `RESULT_FILE` 位于仓库内或通过符号链接逃逸固定临时根目录的测试必须失败且不修改目标。

### 11.4 聚焦验证命令

```bash
python -m pytest -q backend/tests/test_local_builder_image_verification.py
python -m pytest -q backend/tests/test_tenant_url_build_contract.py
RESULT_FILE=/tmp/d-ai-code/apaas-builder-local-verify/manual/result.json \
  CONTAINER_CLI=/usr/bin/podman bash scripts/verify_local_builder_image.sh
python -c 'import json; p="/tmp/d-ai-code/apaas-builder-local-verify/manual/result.json"; d=json.load(open(p, encoding="utf-8")); assert d["status"] == "succeeded"; assert d["container_cli"] == "podman"; assert d["platform"] == "linux/amd64"'
python -c 'import json, subprocess; p="/tmp/d-ai-code/apaas-builder-local-verify/manual/result.json"; d=json.load(open(p, encoding="utf-8")); got=subprocess.run(["/usr/bin/podman", "image", "inspect", "--format", "{{.Id}}", d["image"]], check=True, capture_output=True, text=True).stdout.strip(); assert got == d["image_id"]'
```

真实 Podman 验证只在聚焦自动化测试通过后执行。验证成功必须读取并解析结果 JSON，再用
上述参数数组形式的 Podman inspect 交叉核对 `image_id` 完全相等；
不得把命令退出 0 单独作为验收证据。

## 12. 实现操作矩阵

| operation_id | 触发 | 文件责任 | CLI 契约 | 测试证据 | 审计/失败 | 回退 |
| --- | --- | --- | --- | --- | --- | --- |
| `local-verify.validate-input` | 独立入口启动 | `verify_local_builder_image.sh` | 5.1、5.2、6.1 | 参数化非法输入与路径安全测试 | 8.2 稳定错误码、结果 locator | 删除独立入口 |
| `local-verify.build-head` | 输入校验通过 | 两个脚本 | `PUSH=0 EXPECTED_BUILD_SHA=<sha>` 调用共享构建脚本 | Docker/Podman、hostile env、HEAD 屏障测试 | `build_failed` / `head_changed` | 删除可选 SHA 断言 |
| `local-verify.inspect-image` | build 成功且 HEAD 未变 | 独立入口 | 6.4 的精确 argv 和 ID regex | 精确参数、空/多行/非法 ID 测试 | `image_inspect_failed` | 删除独立入口 |
| `local-verify.write-result` | 成功或受控失败 | 独立入口 | Python json、0600、同目录原子 rename、单一 locator | 全错误码 schema、权限、路径逃逸、并发测试 | `result_write_failed` | 删除结果文件功能 |
| `local-verify.preserve-worktree` | 整次运行 | 独立入口与共享脚本 | 只读 Git 命令 | status 字节与四类文件 checksum | 任一差异即测试失败 | 删除独立入口 |

本任务没有页面、表单、用户业务流、数据库表、API、通知、审批或归档写回；这些 CodegenPlan
维度均为明确不适用。为适配 Builder 当前只在 `business-flow.operations` 中承载 typed
operation contract 的 schema，投影可生成一个“CLI 运行验证流程”资产，仅作为上表五个操作的
结构化容器，不增加用户业务语义、页面或发布职责。实现计划只需消费上表五个 CLI 操作，不得
扩展为发布操作。

## 13. 回退策略

该变更不涉及数据库、API、线上配置或部署迁移。回退时：

1. 删除独立入口和独立测试文件。
2. 删除 `build_builder_image.sh` 中可选 `EXPECTED_BUILD_SHA` 校验。
3. 现有构建和线上发布入口恢复到变更前行为。

回退不需要清理已构建的本地镜像，也不需要访问远程系统。

## 14. Builder 投影要求

Spec 对抗评审闭合后、进入实现计划前，必须通过 `agentic-coding-spec` 和
`agentic-spec-to-knowledge-derivation` 完成最低 Builder 投影：

1. 在 roadmap、phase metadata、asset index 和 derivation manifest 登记本 phase 与当前
   Spec hash。
2. source Spec 作为 `asset_kind: spec` 正式资产，`source_section_refs` 使用标题文本。
3. source coverage 覆盖入口、构建、inspect、结果写入、工作区保持和回退章节；页面、表单和
   用户业务流以 CLI-only 不适用理由闭合。允许派生一个
   `business-flow.local-builder-image-verification` typed asset，唯一用途是按现有 Builder schema
   承载第 12 节五项 CLI operation contract，不得增加新的业务事实或可视 Surface。
4. derivation diagnostics 使用 map 形状，messages 为对象列表。
5. `agentic-prototype-trigger` 以 docs/CLI-only 证据判定 `not_applicable`。
6. `agentic-spec doctor --workspace /mnt/d/workspaces/d-ai-code/apaas-builder-ai` 返回通过后，
   才允许进入 `superpowers:writing-plans`。

## 15. 验收标准

1. 标准命令可在 Docker 或 Podman 上构建当前 `HEAD` 的本地镜像并生成成功 JSON。
2. 外部 `PUSH=1`、镜像仓库凭据和 Kubernetes 配置不会触发 login、push、kubectl、线上
   smoke 或发布锁动作。
3. 入口与共享构建脚本通过 `EXPECTED_BUILD_SHA` 和前后 `HEAD` 检查关闭可观测竞态。
4. 成功与受控失败结果符合 `apaas-builder-local-image-verification/v1`，权限为 `0600`，
   不包含凭据、环境和命令输出。
5. 运行前后的 Git 工作区状态与内容完全一致。
6. 现有未设置 `EXPECTED_BUILD_SHA` 的构建、CI 和线上发布调用保持兼容。
7. 所有聚焦自动化测试通过，当前机器使用 Podman 完成一次真实本地构建与 inspect 验证。
8. 实施和验证期间未认证或写入镜像仓库，未调用 Kubernetes 或线上发布入口；构建所需的
   基础镜像和依赖只读下载不在禁止范围内。
