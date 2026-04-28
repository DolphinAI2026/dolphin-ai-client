# 在线通用 Vibe Coding 平台架构设计

**Date**: 2026-04-26
**Status**: Draft v0.1
**Context**: 从当前低代码智能搭建 + 低代码二次开发 Vibe Coding，扩展到 Codex / Genspark AI Developer 类的在线通用全代码开发。

---

## 0. 结论

这个方向能做，而且当前仓库已经有一部分可复用基础：`CodingPage` / `WorkspaceShell`、`/api/coding`、`HarnessManager`、`VibeCodingAgent`、code-server / VS Code patch 脚本、工作区创建、SSE 事件流、Git 接入设计。

但它不能只理解为“fork VS Code，再把低代码二开限制去掉”。真正的架构边界要从：

> 单机可信工作区 + 低代码模板生成

升级为：

> 多租户控制面 + 每工作区独立沙箱 + Web IDE + Agent Runtime + Git/预览/部署闭环

核心判断：

- **VS Code fork 是产品入口，不是安全边界**。
- **沙箱是必须项**。只要允许用户跑任意全代码项目，就等于允许用户执行任意命令、安装依赖、访问网络、启动服务。
- 当前 `WorkspaceManager` + 本机目录 + code-server 的模式适合内部 demo / 单租户可信环境，不适合作为公有云多租户底座。
- 低代码二开与全代码开发应该共用一套 `Agent Runtime + Workspace + Git + Preview + Sandbox` 内核，差异放在 `Project Adapter`。

---

## 1. 外部产品参照

Genspark 当前公开定位已经不是单纯搜索或聊天，而是 All-in-One AI Workspace。官网展示了 `Genspark Claw Desktop App`，核心形态是把本地电脑和多个云电脑统一在一个工作区里管理。

Genspark AI Developer 的公开介绍里明确把它定位为类似 Claude Code 的自主编码代理：支持多种前沿 coding 模型、可在浏览器和 App 中工作，并强调从规划、编码、测试到交付的自动化。

OpenAI 对 Genspark Super Agent 的案例也说明了这类平台的底层方向：不是一个模型直接回答，而是多模型、多工具编排，让用户只描述目标，系统执行完整工作流。

参考链接：

- https://www.genspark.ai/
- https://www.genspark.ai/blog/genspark-ai-developer
- https://openai.com/index/genspark/

对我们的启发：

- 在线 Vibe Coding 不是“在线编辑器 + 聊天框”，而是“云工作区 + agent 执行系统”。
- 如果要支持全代码，必须给每个项目一个可执行、可预览、可回滚的云电脑 / 沙箱。
- 浏览器 IDE、聊天、计划、测试、预览、Git、部署应该在一个工作台里闭环。

---

## 2. 产品定位

### 2.1 一句话

面向企业和开发团队的在线 AI 开发工作台：既能继续做得帆低代码应用的智能搭建与二次开发，也能导入任意 Git 仓库或新建全代码项目，让 AI 在隔离云工作区中读代码、改代码、跑命令、启动预览、提交 PR。

### 2.2 三类入口

| 入口 | 用户心智 | Source of Truth | 典型产物 |
| --- | --- | --- | --- |
| 低代码智能搭建 | 描述业务应用，生成 aPaaS 配置 | Application Schema / Canonical SPEC | 对象、表单、流程、权限 |
| 低代码二次开发 | 针对 aPaaS 自开发组件/页面/接口做 Vibe Coding | aPaaS 自开发模板 + 平台发布结果 | 组件包、页面包、后端接口 |
| 通用全代码开发 | 像 Codex / Claude Code 一样处理任意代码库 | Git repo | commit、branch、PR、部署包 |

### 2.3 不做什么

- 不让任意用户代码跑在 Builder 后端宿主机上。
- 不把 Git merge 等同于低代码平台 apply；低代码仍然保留不可逆操作的审批门。
- 不一开始承诺完全替代 Cursor / VS Code Desktop；第一阶段先做浏览器工作台。

---

## 3. 总体架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Browser                                                             │
│ ┌────────────────────┐ ┌──────────────────────────────────────────┐ │
│ │ Builder Workspace  │ │ VS Code Web / Forked IDE iframe          │ │
│ │ Chat / Plan / Diff │ │ Files / Terminal / Extension / Preview   │ │
│ └────────────────────┘ └──────────────────────────────────────────┘ │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│ Control Plane                                                       │
│ API Gateway / Auth / Tenant / Project / Workspace / Billing         │
│ Agent Orchestrator / Git Service / Secret Service / Audit / Policy  │
└──────────────┬───────────────────────┬──────────────────────────────┘
               │                       │
               │                       │
┌──────────────▼─────────────┐ ┌───────▼──────────────────────────────┐
│ Model Gateway              │ │ Sandbox Control Plane                │
│ OpenAI-compatible routing  │ │ Provision / Snapshot / Quota / Kill  │
│ prompt cache / rate limit  │ │ Network policy / Port proxy          │
└────────────────────────────┘ └───────┬──────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────┐
│ Per-workspace Sandbox                                                │
│ ┌────────────┐ ┌──────────────┐ ┌──────────────┐ ┌───────────────┐ │
│ │ VS Code Web│ │ Agent Daemon │ │ Dev Runtime  │ │ Project Files │ │
│ │ code-server│ │ tool server  │ │ node/python… │ │ repo + volume │ │
│ └────────────┘ └──────────────┘ └──────────────┘ └───────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 核心模块

### 4.1 Control Plane

负责平台级状态，不直接执行用户代码。

职责：

- 租户、用户、项目、工作区、角色权限。
- Agent thread / turn / event 持久化与 SSE 回放。
- 工作区生命周期：创建、恢复、暂停、销毁、快照。
- Git 绑定、分支、commit、PR / MR。
- Secret 管理、审计日志、模型路由、用量计费。

当前可复用：

- `backend/app/harness/*` 的 thread / turn / event 模型。
- `/api/coding` 的 SSE 流程和 conversation 绑定。
- `WorkspaceShell` 的三栏工作台方向。
- Git integration 的 Project / Application / repo / proposal 设计。

### 4.2 Sandbox Control Plane

负责把用户工作区调度到隔离运行环境。

职责：

- 根据项目类型选择基础镜像。
- 创建 Pod / microVM / container。
- 挂载持久化 volume 或恢复 snapshot。
- 下发资源限制：CPU、内存、磁盘、最长运行时间。
- 注入只读配置和临时 secret。
- 绑定 IDE URL、preview URL、port proxy。
- 空闲回收、异常 kill、快照保存。

### 4.3 Per-workspace Sandbox

每个用户工作区独立运行。所有危险操作只发生在这里。

内容：

- VS Code Web / OpenVSCode Server / code-server。
- 自研 VS Code extension。
- Agent Daemon：接收 Control Plane 的 tool call，在沙箱内执行。
- Dev Runtime：Node / Python / Java / Go / Rust / Maven / pnpm 等。
- Project Files：Git repo、模板工程、用户文件。
- Local services：用户 `npm run dev` / `pytest` / `mvn test` 启动的进程。

关键约束：

- 不挂载宿主机敏感目录。
- 不暴露 Docker socket。
- 不使用 privileged container。
- 默认非 root 用户。
- 网络出站走 egress proxy。
- 所有命令、文件 diff、端口暴露都进审计日志。

### 4.4 Agent Runtime

把现在的 `VibeCodingAgent` 升级成通用 coding harness。

职责：

- 读 repo map / 文件 / 搜索结果 / LSP 诊断。
- 生成 plan。
- 执行工具：read、write、edit、run command、test、preview、browser check。
- 根据测试结果迭代。
- 输出 diff、commit message、PR 描述。
- 对高风险命令请求用户确认。

关键变化：

- 工具不再直接操作 Builder 后端本机文件系统。
- 所有 tool call 通过 `Agent Daemon` 在 sandbox 内执行。
- `run_command` 必须有 policy engine：区分安全命令、需确认命令、禁止命令。

### 4.5 IDE Gateway

负责把 VS Code Web 安全暴露给浏览器。

职责：

- 每个 workspace 独立 IDE URL。
- IDE token 短期有效，绑定 user / tenant / workspace。
- 反向代理 WebSocket。
- 注入 Builder extension 配置。
- 禁止跨工作区访问。
- 支持文件树、终端、源代码搜索、Git 面板、Chat 面板。

当前 `build_ide_url`、`.vscode/ruijing-ai.json`、code-server patch 脚本可以作为第一版基础，但长期建议把它们收敛进标准 runtime image。

### 4.6 Preview / Port Proxy

通用全代码开发必须有实时预览。

职责：

- 监听 sandbox 内进程打开的端口。
- 映射到公网/内网 HTTPS URL：`https://<workspace>-3000.dev.example.com`。
- 只允许已登录且有权限用户访问。
- 支持 WebSocket / HMR。
- 阻断 SSRF：preview 代理不能访问控制面内网接口、云厂商 metadata、其他租户工作区。
- 支持多端口：frontend、backend、storybook、docs。

### 4.7 Git / Artifact / Deployment

职责：

- GitHub / GitLab OAuth 或 PAT 绑定。
- 导入 repo、创建 branch、提交 commit、打开 PR。
- 保存 workspace snapshot。
- 保存构建产物、测试日志、预览链接。
- 对低代码二开提供 upload-to-platform / publish。
- 对全代码提供 Vercel / Cloudflare / Docker image / 企业内部部署插件。

---

## 5. 数据模型草案

```python
class CodingProject:
    id: str
    tenant_id: int
    owner_id: int
    name: str
    kind: str  # apaas_schema | apaas_custom_dev | full_code
    repo_url: str | None
    default_branch: str | None
    adapter: str  # apaas | fullstack | frontend | backend | unknown
    created_at: datetime


class CodingWorkspace:
    id: str
    project_id: str
    tenant_id: int
    user_id: int
    source_type: str  # template | git_import | branch | snapshot
    branch_name: str | None
    sandbox_id: str | None
    status: str  # creating | ready | sleeping | running | failed | deleted
    last_snapshot_id: str | None
    resource_profile: str  # small | medium | large
    created_at: datetime
    last_active_at: datetime


class SandboxSession:
    id: str
    workspace_id: str
    runtime: str  # docker | k8s_gvisor | kata | firecracker
    image: str
    pod_name: str | None
    vm_id: str | None
    cpu_limit: str
    memory_limit: str
    disk_limit_gb: int
    status: str  # provisioning | running | stopping | stopped | failed
    ide_url: str | None
    created_at: datetime
    expires_at: datetime | None


class AgentThread:
    id: str
    workspace_id: str
    profile: str  # coding | review | fix_test | lowcode_spec
    model: str
    status: str  # idle | running | waiting_approval | completed | failed
    current_plan: dict | None
    created_at: datetime


class ToolCall:
    id: str
    thread_id: str
    sandbox_id: str
    tool_name: str
    arguments_json: dict
    risk_level: str  # low | medium | high | blocked
    status: str  # pending | approved | running | succeeded | failed | denied
    stdout_ref: str | None
    stderr_ref: str | None
    diff_ref: str | None
    started_at: datetime | None
    completed_at: datetime | None


class PortForward:
    id: str
    workspace_id: str
    sandbox_port: int
    public_url: str
    protocol: str  # http | websocket | tcp
    status: str
    created_at: datetime


class WorkspaceSnapshot:
    id: str
    workspace_id: str
    base_git_sha: str | None
    volume_snapshot_ref: str
    description: str
    created_by: str  # user | system | agent
    created_at: datetime
```

---

## 6. 沙箱选型

| 方案 | 安全性 | 成本 | 启动速度 | 适用阶段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 本机目录 + 本机 code-server | 低 | 低 | 快 | 本地 demo | 只能内部可信使用 |
| Docker container | 中低 | 低 | 快 | 单租户/私有化 MVP | 不能作为公有云强隔离 |
| Kubernetes Pod + gVisor | 中高 | 中 | 中 | SaaS Beta | 推荐 v1 |
| Kubernetes Pod + Kata Containers | 高 | 中高 | 中 | 企业多租户 | 推荐 v1/v2 |
| Firecracker microVM | 高 | 高 | 中慢 | 公有云规模化 | 推荐长期目标 |

推荐路线：

1. **内部 MVP**：Docker / K8s Pod 均可，但必须明确“非公有云安全边界”。
2. **企业 Beta**：K8s + gVisor 或 Kata Containers，每 workspace 一个 Pod。
3. **公有云规模化**：Firecracker microVM 或等价 microVM，配合 snapshot 加速启动。

---

## 7. 安全设计

### 7.1 文件系统

- 每 workspace 独立 volume。
- base image 只读，项目目录可写。
- 禁止挂载宿主机 `/var/run/docker.sock`、`~/.ssh`、云厂商凭证目录。
- snapshot 前后记录文件 diff。
- 删除/覆盖大范围文件需要用户确认。

### 7.2 进程与系统调用

- 非 root 用户。
- drop Linux capabilities。
- seccomp / AppArmor / gVisor / Kata 隔离。
- 限制 fork bomb、后台守护进程、长时间 CPU 占用。
- idle timeout + hard timeout。

### 7.3 网络

- 默认允许访问公网包管理源和 Git provider。
- 默认阻断：
  - 云 metadata IP：`169.254.169.254`
  - 内网网段：`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`
  - Builder Control Plane 内部服务地址
  - 其他租户 workspace 地址
- 企业私有化可配置 allowlist。
- 所有出站请求经 egress proxy 记录域名、目标 IP、字节数。

### 7.4 Secret

- Secret 存 Vault / KMS，不落工作区文件。
- 运行时以临时 env 或临时文件注入。
- 日志、SSE、tool result 做 secret redaction。
- Agent 不能默认读取全部 secret，必须按项目授权。

### 7.5 Tool Policy

| 风险级别 | 例子 | 行为 |
| --- | --- | --- |
| low | `ls`, `rg`, `npm test`, `pytest` | 自动执行 |
| medium | `npm install`, `pip install`, `git commit` | 可配置自动执行，审计 |
| high | `rm -rf`, `curl \| sh`, `npm publish`, `deploy` | 用户确认 |
| blocked | 访问宿主机、扫描内网、读系统凭证 | 直接拒绝 |

### 7.6 审计

必须记录：

- 用户输入。
- Agent plan。
- tool call 参数。
- 命令 stdout/stderr 摘要。
- 文件 diff。
- 网络出站摘要。
- secret 使用事件。
- Git commit / PR / deploy 事件。

---

## 8. 端到端流程

### 8.1 新建全代码项目

1. 用户选择“新建全代码项目”或“导入 Git 仓库”。
2. Control Plane 创建 `CodingProject`。
3. Sandbox Control Plane 创建 `CodingWorkspace` 和 `SandboxSession`。
4. 沙箱 clone repo 或套模板。
5. IDE Gateway 返回 VS Code Web URL。
6. Agent Runtime 扫描 repo，生成 repo map。
7. 用户在 Chat 中描述任务。
8. Agent 生成 plan，必要时请求确认。
9. Agent 在 sandbox 内读写文件、跑测试、启动预览。
10. Preview Proxy 暴露服务 URL。
11. 用户看 diff，选择 commit / PR / deploy。
12. 系统保存 snapshot 和审计日志。

### 8.2 导入现有 Git 仓库

1. OAuth 绑定 GitHub / GitLab。
2. 选择 repo + branch。
3. 创建 workspace branch：`agent/<task-slug>`。
4. 沙箱 clone branch。
5. Agent 修改后提交到 branch。
6. 打开 PR / MR。
7. PR 描述包含：
   - 用户需求
   - Agent plan
   - 文件变更摘要
   - 测试命令与结果
   - 预览链接

### 8.3 低代码二开

1. 用户从 aPaaS 应用进入“自开发”。
2. Project Adapter 选择 aPaaS 模板。
3. 沙箱创建工作区，注入 `.cursor/rules` / 平台 SDK / 发布配置。
4. Agent 开发组件、页面、后端接口。
5. 在沙箱内 build。
6. 上传到平台前做二次确认。
7. 发布结果绑定回 aPaaS 应用。

---

## 9. Project Adapter 设计

统一内核，不同项目类型用 adapter 处理差异。

```python
class ProjectAdapter:
    name: str

    async def detect(self, repo_path: Path) -> DetectionResult:
        ...

    async def bootstrap(self, workspace: CodingWorkspace) -> None:
        ...

    async def build_context(self, workspace: CodingWorkspace) -> dict:
        ...

    async def default_commands(self) -> list[str]:
        ...

    async def publish(self, workspace: CodingWorkspace, target: dict) -> PublishResult:
        ...
```

第一批 adapter：

| Adapter | 适用 | 特殊能力 |
| --- | --- | --- |
| `apaas_spec` | 低代码智能搭建 | SPEC / Schema / 平台 apply |
| `apaas_custom_dev` | 得帆二开组件/页面/接口 | 模板、SDK、build、upload-to-platform |
| `node_web` | React/Vue/Next/Vite | npm/pnpm/yarn、dev preview |
| `python_backend` | FastAPI/Django/Flask | venv、pytest、uvicorn |
| `java_backend` | Spring Boot/Maven | mvn test、端口预览 |
| `generic` | 未识别 repo | 基础文件读写 + 命令建议 |

---

## 10. VS Code Fork 策略

### 10.1 第一阶段

不建议一开始深 fork VS Code Desktop。第一阶段用浏览器 IDE：

- OpenVSCode Server / code-server 作为基础。
- 自研 extension 提供 Chat、Plan、Diff、Preview、模型选择。
- 外层 Builder WorkspaceShell 提供项目、审计、审批、Git、部署。

原因：

- 在线平台最难的是 sandbox 和 runtime，不是编辑器 UI。
- 深 fork VS Code 会带来持续合并上游、Marketplace、扩展兼容、Remote Extension Host 的维护成本。
- 当前仓库已经有 code-server patch 和 VS Code extension，可以先复用。

### 10.2 第二阶段

当在线工作区稳定后，再考虑：

- 品牌化 VS Code Web。
- 桌面客户端，统一管理本地电脑和云工作区。
- 类似 Genspark Claw 的“本地 + 多云电脑”工作台。

---

## 11. 与当前仓库的演进关系

当前已有能力可以这样迁移：

| 当前模块 | 目标演进 |
| --- | --- |
| `WorkspaceManager` | 拆成 Control Plane 的 workspace 元数据 + Sandbox 内文件操作 |
| `VibeCodingAgent` | 升级为通用 CodingProfile，tool call 通过 sandbox daemon 执行 |
| `/api/coding/auto-pipeline` | 保留为 aPaaS adapter 的一条任务流 |
| `HarnessManager` | 成为所有 agent thread / event / replay 的统一内核 |
| `useIdeManager` | 继续管理 IDE iframe，但 URL 来源改成 SandboxSession |
| `WorkspaceShell` | 扩展成通用项目工作台 |
| Git integration 设计 | 复用为 full-code repo 的 branch / PR / drift 管理 |
| aPaaS upload/publish | 只作为 `apaas_custom_dev` adapter 的 publish target |

需要新增：

- `sandbox` 服务：provision / stop / snapshot / port proxy。
- `agent-daemon`：运行在沙箱内的 tool server。
- `secret` 服务。
- `policy` 服务。
- `preview gateway`。
- `workspace snapshot` 存储。
- `repo index` 服务。

---

## 12. 分阶段路线

### Phase 0：架构拆分验证

目标：不改变产品体验，先把危险边界拆开。

- 抽象 `ToolExecutor` 接口。
- 当前本机执行器命名为 `LocalTrustedExecutor`。
- 新增 `SandboxExecutor` 接口和 mock。
- `VibeCodingAgent` 不再直接拿本机路径执行命令。
- 现有低代码二开流程保持可跑。

验收：

- 现有 CodingPage 仍可创建工作区、生成代码、打开 IDE。
- 所有 tool call 都能记录 executor 类型。

### Phase 1：内部全代码 MVP

目标：能在内部环境跑任意 Node/Python 项目。

- 新增 full-code project。
- 支持导入 Git repo。
- 每 workspace 一个容器 / Pod。
- 浏览器 IDE 打开 sandbox 文件。
- Agent 可在 sandbox 内读写文件、跑命令。
- 支持 port preview。
- 支持 commit 到 branch。

验收：

- 导入一个 Vite 项目，AI 修改页面，`npm test/build` 通过，预览可访问，能提交 PR。
- 导入一个 FastAPI 项目，AI 修改接口，`pytest` 通过，预览可访问。

### Phase 2：企业 Beta

目标：达到企业多租户可用。

- K8s + gVisor / Kata。
- Secret Vault。
- Egress policy。
- Tool policy + 用户确认。
- Workspace snapshot / rollback。
- 审计后台。
- 资源配额、闲置回收、用量统计。

验收：

- 不同租户 workspace 互相不可访问。
- Agent 不能访问 control plane 内网。
- 高风险命令必须确认。
- secret 不出现在日志和 SSE 中。

### Phase 3：Agentic Developer

目标：更接近 Codex / Genspark AI Developer。

- 异步长任务队列。
- 多 agent：开发、测试、代码审查、文档。
- 自动修测试。
- 自动 PR review 响应。
- 部署目标插件。
- 团队协作、任务看板。

验收：

- 用户提交一个 issue，系统自动开 workspace、改代码、跑测试、开 PR、附预览。

---

## 13. 推荐技术栈

| 层 | 推荐 |
| --- | --- |
| Control Plane | 继续 FastAPI + SQLAlchemy，后续迁移 PostgreSQL |
| Event / Queue | Redis Streams / NATS / Temporal |
| Sandbox Orchestration | Kubernetes |
| Sandbox Runtime | Beta 用 gVisor / Kata，长期 Firecracker |
| IDE | OpenVSCode Server / code-server + 自研 extension |
| Port Proxy | Traefik / Envoy / NGINX Ingress + wildcard domain |
| Artifact | S3 / MinIO |
| Secret | Vault / 云 KMS |
| Repo Index | ripgrep + tree-sitter + LSP + optional vector index |
| Model Gateway | OpenAI-compatible router + per-tenant model policy |

---

## 14. 最大风险

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 沙箱安全低估 | 任意代码执行是高风险能力 | 不上公有云前必须完成强隔离 |
| 成本失控 | 每 workspace 都是云电脑 | idle 回收、资源档位、snapshot 冷启动 |
| VS Code fork 维护成本 | 深 fork 会吞团队资源 | 先 extension + Web IDE，晚点再深 fork |
| Agent 乱改代码 | 全代码项目上下文复杂 | plan/diff/test/approval 四道门 |
| 网络与 secret 泄露 | 用户代码可主动外连 | egress proxy + secret redaction + policy |
| 低代码与全代码语义混淆 | 低代码 apply 不可逆，全代码 git 可回滚 | 用 adapter 隔离发布语义 |

---

## 15. 最小可行结论

如果现在要立项，我建议主线是：

1. **不要另起一套产品内核**，在现有 Builder AI 上扩展 `Workspace + Harness + Git`。
2. **先做在线通用 Vibe Coding 的内部 MVP**，但明确只适合可信用户。
3. **并行设计沙箱控制面**，在进入企业 Beta 前切到 K8s + gVisor/Kata。
4. **保留低代码优势**：低代码场景继续用 SPEC / Schema / 平台 apply；全代码场景用 Git repo / branch / PR。
5. **VS Code 只作为前端工作界面**，核心护城河在 agent runtime、项目 adapter、沙箱和企业治理。

一句话架构原则：

> Chat 是入口，VS Code 是工作台，Git 是交付物，Sandbox 是安全边界，Harness 是智能执行内核，Adapter 决定是低代码还是全代码。
