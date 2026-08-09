# aPaaS Builder AI

得帆云低代码平台的智能搭建与 Dolphin Code 集成工作台。这个仓库同时承载低代码应用搭建、全代码 Code 应用入口、后端编排服务、平台管理端、桌面交付端和部署交付材料。

## 核心能力

- 对话式生成和改造低代码应用。
- Builder / Code 双模式应用入口，低代码应用与全代码应用按 `app_type` 隔离。
- 应用目录、项目概览、需求/SPEC、配置预览、部署、租户日志和能力中心。
- Dolphin Code runtime 嵌入、会话绑定、左侧 rail 历史、runtime 反向代理和 token/cookie 隔离。
- FastAPI 后端统一承载认证、租户、应用、Agent、MCP、知识库、技能库、Git、工作区和运行态代理。
- Tauri 桌面端使用本地 sidecar、单 URL Discovery、远程认证和本地 AI 补充能力；不启用本地账号登录。
- 自开发页面、表单组件、前端插件模板和客户交付部署包。

## 快速开始

### 一键启动

```bash
./start.sh
```

`start.sh` 会准备后端虚拟环境、安装前端依赖、构建管理端静态资源，并启动后端和主前端。

### 手动启动

后端：

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

主前端：

```bash
cd frontend
npm install
npm run dev
```

平台管理端：

```bash
cd admin-spa
npm install
npm run dev
```

## 本地访问

- 主前端：http://localhost:5173/ai-builder/
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs
- 平台管理端：本地开发由 `admin-spa` 的 Vite 服务提供；容器/K8s 部署时通常挂在 `/ai-builder/admin/`

## 工程会话与 Worktree

本地可用 `backend/scripts/agentic_session.py` 管理工程会话。默认会把可写任务放到独立 Git branch + worktree 中；默认 worktree 父目录为 `<control-repo-parent>/worktrees/<repo-id>/`，registry 默认写入 `~/.codex/.agentic-coding/workspaces/<repo-id>/sessions/`。两者分别可用 `--worktree-parent`、`--registry-root` 覆盖。

以下示例从主仓库根目录开始执行，每段先进入 `backend/`；`--repo ..` 因而指向当前 Git worktree。服务会通过 Git common-dir 统一解析主工作树，因此也可以从主工作区或 linked worktree 的根目录、子目录调用。

创建功能会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. create --type feature --title "新增会话"
```

省略 `--base-branch` 时优先使用 `origin/HEAD` 指向的默认分支。仓库配置了 `origin` 时，每次创建都会在 fetch 后刷新并校验该引用，远端默认分支变更不会继续沿用本地陈旧值；无法确定时直接报错，不会静默落到错误基线。没有 `origin` 时依次尝试 `main`、`master`，最后才使用非 `session/*` 的控制工作区当前分支。基线 commit 优先取 fetch 后的 `origin/<base>`，因此不会从落后的本地默认分支创建一个立即 stale 的会话。release、集成分支或其他非默认基线必须显式传入 `--base-branch`。

`create` 会扫描现存 `session/S-*` branch 和 `refs/agentic/sessions/S-*` 隐藏身份引用，并通过 Git ref compare-and-swap 原子预留 session ID。所有 registry 根目录共享 Git common-dir 下的仓库级变更锁；即使并发创建，或创建的是没有 worktree 的 review/deploy 会话，也会自动重试到不同 ID。标准 SHA-1 与 SHA-256 Git 仓库都使用各自对象格式对应的零 OID 完成 compare-and-swap。权限、磁盘或 ref lock 等基础设施错误会直接返回真实 Git 错误，不会伪装成 ID 冲突重试。Git 命令在已生效后超时时会回读 ref/worktree：可以确认成功时继续创建，无法确认时保留现场。每个 worktree branch 还会写入指向 registry owner 的 symbolic claim，避免不同 registry 同时认领同一 orphan。registry 丢失或切换后，不会把旧 branch/worktree 静默接管为新任务；已有对象由原 owner 的 `reconcile` 恢复为 `orphan_session`。只要 branch 已完成预留，后续 worktree 创建或 registry 保存失败都会保留 branch、identity ref 和 claim，已创建的 worktree 也会一并保留，并在原异常中提示运行 `reconcile` 恢复；系统不会在回滚中删除可能已被外部 Git 推进的分支。

查看并同步会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. list --sync
```

读取、同步并恢复单个会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. resume S-001
```

`resume` 会刷新 registry 和 Git 状态；合法的无 worktree 只读会话，或 worktree 存在且 branch 匹配的会话，会重新进入 `running`。缺失的 worktree 会被标记但不会自动重建，branch mismatch 也不会被强制恢复。

为会话创建 checkpoint：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. checkpoint S-001 --message "checkpoint: S-001 async conversation create"
```

`checkpoint` 使用独立临时 Git index 执行 `git add -A`，然后通过 `git write-tree`、`git commit-tree` 和带旧 HEAD 校验的 `git update-ref` 创建 checkpoint。提交明确更新 registry 中的目标 `session/*` branch，不依赖命令执行瞬间的当前分支；发布 live index 时同时持有目标 branch 的 Git ref lock 和 `index.lock`，并重新校验 branch 名称、目标 HEAD 与 index 内容，保留原 index 权限并持久化 rename 所在目录。外部 reset、暂存、checkout 或现有 lock 抢先发生时不会被覆盖；如果 branch 已提交但 live index 发布被拒绝，会刷新 registry 并返回“部分成功”错误，不会错误输出成功。`update-ref` 已生效后的 index 或 registry 刷新失败同样按部分成功状态重新同步 registry，恢复和提交前临时文件清理错误只作为主异常的附加诊断；durable publish 完成后的临时文件清理失败只记录 warning，不会把成功 checkpoint 误报为失败。输出 `created: false` 仅表示 clean no-op、missing worktree、branch mismatch、重复 worktree 或 Git 操作进行中等提交前拒绝状态；实际提交失败或提交后的 index 发布失败会刷新 registry 后返回非零退出码。

归档会话但保留 worktree：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. archive S-001
```

`archive` 默认先尝试 checkpoint。missing worktree、branch mismatch、重复 worktree 或 Git 操作进行中仍按不可写状态保留会话；`blocked_retained` 不会被 archive 覆盖成可清理状态。实际提交失败会传播为非零退出码，不会伪装为归档成功。`--no-checkpoint` 会跳过尝试：仅 dirty worktree 标记 `dirty_uncheckpointed`，clean worktree 直接归档为对应 retained 状态。

对齐真实 worktree 并回写 registry：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. reconcile
```

`reconcile` 会同步已登记会话，并为未登记的 `session/*` worktree 建立 `orphan_session`，不是只读扫描。创建失败后只剩 branch、identity 和 claim、尚无 worktree 的现场也会登记为 `missing_worktree`，保留 `orphan_session` 生命周期供后续恢复。创建期间已写入但尚未落 registry 的同 owner claim 会按原 session ID 恢复；其他 registry 已 claim 的对象会跳过并输出 warning。branch ID 或 claim ID 对应损坏、不兼容的 registry YAML 时会 fail-closed：保留原文件和身份并输出 warning，不会覆盖损坏记录或另分配新 ID。

如果同一个 branch 被强制挂载到多个 worktree，会话进入 `ambiguous_worktree`，设置 `git_state.worktree_ambiguous=true`，并阻止 resume 激活、checkpoint、archive 和清理提示；系统不会通过路径排序静默选择其中一个 worktree。

约束：

- `new-app` 和 `spec-change` 不允许使用 `--no-worktree`。
- 不记录文件锁、路径锁或模块锁，冲突由 Git merge/rebase 暴露。
- registry 根目录包含原子发布的 `.repository.yaml` 所有权标记，禁止不同仓库通过相同 `--registry-root` 相互覆盖。旧 registry 必须至少有一条可验证且所有者一致的记录才能补建 owner；只有损坏记录或出现冲突 owner 时会拒绝认领。单条损坏或不兼容的 session YAML 会被 `list/reconcile` 跳过，并以 stderr JSON `warnings` 返回；其他健康会话仍可读取和修复。
- registry 使用临时文件、原子替换、文件与目录 `fsync`；未知 YAML 字段会在旧版本 load/save 后保留。临时文件清理失败不会遮蔽正在传播的主异常。进程锁同时支持 POSIX `fcntl` 和原生 Windows `msvcrt`；Windows 锁竞争使用有截止时间的非阻塞重试，超时会返回明确错误。
- base ref 不可用时会设置 `git_state.base_missing`，保留原生命周期状态，但阻止 resume 激活、checkpoint 和 archive 状态转换，并暂停清理提示。
- 无 worktree 的 review/deploy 会话会比较 `base_commit` 与当前 base ref；base 前进或发生分叉时同样标记 `stale` 并计算 ahead/behind。
- merge、rebase、cherry-pick、revert、bisect、sequencer 或未解决 index 冲突进行中时，checkpoint 不会执行 `git add -A` 或提交。
- `fetch origin` 在 registry 事务锁外执行，慢网络不会阻塞同仓库的本地 `list`。CLI `create` 仍会等待 fetch 和 worktree 创建完成后返回，产品层的“先展示会话、后台初始化”由后续 Engineering Manager/API 接入负责。
- CLI 参数错误和运行错误统一写入 stderr JSON，格式为 `{"error":{"code":"...","message":"..."}}`，不输出 Python traceback。
- 标准 Git 仓库及常规 linked worktree 共享同一个控制工作区。`--separate-git-dir` 从主工作树调用受支持；其 linked worktree 无法从 Git 元数据可靠反查原始工作树时会明确拒绝，不会误认 metadata 目录。
- 已合并且 clean 的 worktree 只提示清理，不自动删除。
- 本 CLI 不执行部署；发布门禁由人工或调用方负责。目标 worktree 必须 clean（`git status --porcelain` 无输出），目标 commit 必须已合入默认分支或明确的 release ref，可用 `git merge-base --is-ancestor <commit> <default-or-release-ref>` 检查：退出码 0 表示已合入，1 表示未合入，其他值表示命令错误。禁止从 dirty 或 unmerged worktree 发布。

## 应用/子系统一览

| 应用/子系统 | 目录 | 主要职责 | 常用入口 |
|---|---|---|---|
| AI Builder 主前端 | `frontend/` | 面向用户的主工作台。包含登录、租户选择、AI 对话搭建、应用目录、项目概览、需求/SPEC、配置预览、低代码应用部署、知识/技能/AI 网关能力中心、平台环境配置、租户日志和桌面引导。 | `cd frontend && npm run dev` |
| Dolphin Code 模式 | `frontend/src/views/CodeShellLayout.vue`、`frontend/src/views/CodeConversationPage.vue` | 全代码应用入口。提供 `/code/apps`、`/code/new`、`/code/:id` 路由，创建 `app_type=ai-code` 应用，打开独立 Code 会话，并把 Dolphin Code runtime 以 iframe 嵌入主工作台。 | 前端访问 `/ai-builder/code` |
| Builder 后端 API | `backend/` | FastAPI 主服务。负责认证、租户、用户、应用、对话/SSE、需求解析、配置生成、aPaaS 调用、应用成员、Git 连接、知识库、技能库、LLM 配置、MCP 工具、运行态代理和桌面适配。 | `cd backend && python run.py` |
| Code Runtime Bridge | `backend/app/code_runtime/`、`backend/app/routes/code_runtime.py` | Dolphin Code 集成层。负责 Code 应用列表/创建、Code 会话创建、runtime workspace 打开、embed token、proxy cookie、runtime session rail 历史、agent session 激活/删除，以及 `/api/code-runtime/{sessionId}` 反向代理。 | 后端 `/api/code/*`、`/api/code-runtime/*` |
| 平台管理 SPA | `admin-spa/` | 平台管理员控制台。管理系统状态、MCP 服务和测试器、平台租户/用户、平台环境、LLM 配置、助手配置、沙箱监控、调用日志和设计预览。主前端 `/platform-admin` 会嵌入它。 | `cd admin-spa && npm run dev` |
| Tauri 桌面端 | `src-tauri/`、`backend/desktop_sidecar.py` | Dolphin Code 桌面壳。首次只输入一个远程服务 URL，由 Discovery 决定 Control Plane/aPaaS 认证和 Builder/Code 入口；远程负责用户、租户、应用、会话，桌面 SQLite 仅保存本地模型、MCP、Skill、知识库及诊断数据。支持 Windows、Linux、macOS。 | Linux/macOS: `bash scripts/build-desktop.sh`；Windows: `scripts/build-desktop-windows.ps1` |
| 桌面账号服务 | `backend/services/account_service/` | 旧版公网账号兼容服务，仅供历史 Web 部署或更新托管使用。桌面 sidecar 已禁用 `/api/desktop-auth/login`，不会再建立本地桌面身份。 | `cd backend && python -m services.account_service` |
| 低代码自开发资产示例 | `custom-pages/` | 得帆云自开发资产示例。`frontend-plugin-ai-builder-entry` 是前端插件入口示例，`form-component-supplier-network` 是表单组件示例。 | `npm run debug` 或 `df-apaas-cli build` |
| 代码生成模板 | `backend/templates/cli-generated/` | 后端生成自开发资产时使用的模板库，覆盖菜单页、列表视图、页面布局、前端插件、Web/移动双端表单组件等模板类型。 | 后端生成流程内部使用 |
| Vibe/Coding 沙箱镜像 | `docker/vibe-sandbox/` | 代码工作区运行/调试用的隔离容器基础镜像，配合后端通过 Docker socket 或 K8s 运行 dev server、构建和验证命令。 | `docker build -t vibe-sandbox:latest docker/vibe-sandbox/` |
| 部署交付包 | `deploy/` | Docker、K8s、客户单机 Docker Compose、Rancher 单节点、nginx 等部署材料。 | 见各目录 README |
| 测试与基线 | `backend/tests/`、`tests/` | 后端单元/集成测试、路由库存、生成器基线、Code runtime、Agent、Spec、Coding 流程测试和 prompt 快照。 | `pytest` / `./test.sh` |

## 目录结构

```text
apaas-builder-ai/
├── frontend/                    # Vue 3 主前端，承载 Builder 和 Code 两种模式
│   └── src/views/Code*.vue       # Dolphin Code shell 和会话页
├── backend/                     # FastAPI 主后端、Agent、MCP、aPaaS 客户端和模板生成
│   ├── app/routes/              # API 路由
│   ├── app/code_runtime/        # Dolphin Code runtime 集成服务
│   ├── app/agents/              # 搭建/编码 Agent
│   ├── app/coding/              # 代码工作区、运行、部署和自开发资产生成
│   ├── app/mcp_tools/           # 内置 MCP 工具
│   ├── services/account_service/ # 桌面账号服务
│   ├── templates/               # 业务需求模板和自开发资产模板
│   └── tests/                   # 后端测试
├── admin-spa/                   # 平台管理端 SPA
├── src-tauri/                   # Tauri 桌面端壳工程
├── custom-pages/                # 自定义页面/表单组件/前端插件示例
├── deploy/                      # Docker、K8s、客户交付、Rancher、nginx 部署材料
├── docker/vibe-sandbox/         # 编码沙箱基础镜像
├── docs/                        # 架构、交付、需求、调研、交接和帮助文档
├── scripts/                     # 构建、部署、桌面发版、巡检和升级脚本
├── tests/                       # 跨模块测试与基线
├── start.sh                     # 本地一键启动
├── stop.sh                      # 停止本地启动的服务
└── test.sh                      # 基础检查和关键后端测试
```

## 技术栈

| 层级 | 技术 |
|---|---|
| 主前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router + Less |
| Code runtime 嵌入 | iframe + shell config + backend proxy + JWT embed token + scoped cookie |
| 管理端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia |
| 后端 | FastAPI + SQLAlchemy 2.0 async + Pydantic v2 + httpx + SSE |
| 桌面端 | Tauri 2 + Rust + Python sidecar + PyInstaller |
| 自开发资产模板 | Vue 2.7 + df-apaas-cli + Element UI/Vant/ECharts |
| 数据库 | SQLite/aiosqlite（本地、桌面）+ PostgreSQL/asyncpg（部署） |
| 认证 | Builder JWT + Dolphin/Control Plane 登录 + aPaaS 登录 |
| LLM | OpenAI/Anthropic 兼容 API，经后端和平台配置统一封装 |
| 部署 | Docker Compose、Kubernetes、Rancher 单节点、nginx、supervisord |

## 关键配置

环境变量请在本地 `backend/.env` 配置，仓库只保留占位示例：

```env
# Authentication
AUTH_PROVIDER=control_plane
DOLPHIN_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn
DOLPHIN_CODE_CONTROL_PLANE_URL=https://your-control-plane.example.com

# LLM Configuration
LLM_API_BASE=https://your-llm-gateway.example.com/openai
LLM_API_KEY=<your-llm-api-key>
LLM_MODEL=<your-model-name>

# Database (server)
DATABASE_URL=postgresql+asyncpg://apaas:<password>@postgres:5432/apaas_builder

# JWT
JWT_SECRET_KEY=<generate-a-long-random-secret>

# Dolphin Code integration
DOLPHIN_CODE_CONTROL_PLANE_TOKEN=<optional-control-plane-token>
DOLPHIN_CODE_BUILDER_URL=http://127.0.0.1:5173/builder/ # 可选，本地 runtime fallback
DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID=<seed-project-id>
```

每个客户实例只配置一种登录模式，登录页和管理端不提供运行时切换入口：

- `AUTH_PROVIDER=control_plane`：默认模式，使用 Control Plane 账号登录。
- `AUTH_PROVIDER=apaas`：使用 aPaaS 账号登录，并需要配置对应的 `APAAS_BASE_URL`。

修改 `AUTH_PROVIDER` 后需要重启后端 Pod、容器或进程，后续登录请求才会使用新的认证源；已经签发的 Builder 会话不会立即失效。Control Plane 模式下，用户仍可单独绑定 aPaaS 账号访问租户、应用和低代码能力，该绑定不会增加第二个登录入口，也不会改变 `AUTH_PROVIDER`。

Control Plane 服务端还必须配置
`CONTROL_PLANE_AUTH_FULL_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn`，
否则它无法校验 Builder 转发的 Dolphin 用户 Token。

`DOLPHIN_CODE_BUILDER_URL` 是可选项，只适合本地开发 fallback。仅 loopback 地址会在 seed 不存在时创建本地 Code 应用；生产应通过 `DOLPHIN_CODE_CONTROL_PLANE_URL` 打开真实隔离 workspace，避免所有 Code 应用共用同一个本地 builder。

## 常用流程

1. 低代码应用：进入 `/ai-builder/` 或 `/ai-builder/apps`，创建/打开 Builder 应用，通过对话生成需求、配置和部署变更。
2. 全代码应用：进入 `/ai-builder/code`，在 Code 应用列表或 `/code/new` 创建 `ai-code` 应用，打开 Dolphin Code runtime 继续开发。
3. 平台配置：进入平台环境、LLM 配置、能力中心或管理端，维护租户环境、模型、MCP、知识和技能。
4. 桌面交付：Linux 使用 `bash scripts/build-desktop.sh` 产出 AppImage/deb；macOS 使用同一脚本产出 app/dmg，Apple Silicon 构建 Intel 包时使用 `bash scripts/build-desktop-x86.sh`；Windows 在原生 Windows PowerShell 执行 `scripts/build-desktop-windows.ps1 -Bundle portable`（或 `nsis`/`msi`）。每次脚本都会清理 PyInstaller sidecar 构建，避免复用旧二进制。
5. 客户部署：按 `deploy/customer/`、`deploy/docker/`、`deploy/k8s/` 或 `deploy/rancher-single-node/` 的 README 交付。

## 相关文档

- [DEVELOPMENT.md](DEVELOPMENT.md)：开发说明。
- [DEPLOY_CONTAINER.md](DEPLOY_CONTAINER.md)：容器部署说明。
- [docs/dolphin-code-integration-issues.md](docs/dolphin-code-integration-issues.md)：Dolphin Code runtime 集成契约和已验证事项。
- [docs/dolphin-code-real-app-demo-content.md](docs/dolphin-code-real-app-demo-content.md)：Dolphin Code 演示内容包。
- [docs/account-service-deploy.md](docs/account-service-deploy.md)：桌面账号服务部署和接线。
- [frontend/README.md](frontend/README.md)：前端工程约定。
- [backend/BACKEND_FRAMEWORK_GUIDE_CODEX.md](backend/BACKEND_FRAMEWORK_GUIDE_CODEX.md)：后端开发指南。

## MCP 服务

独立 MCP 服务在单独仓库 [`apaas-builder-mcp-server`](https://github.com/Mars-hub404/apaas-builder-mcp-server) 维护并部署。主后端通过 bridge 调用它；未启动时应优雅降级，Builder 核心工具不受影响。需要本地联调时，克隆该仓库按其 README 启动，或用 `MCP_V2_INTERNAL_BASE` 指向已有 MCP 服务。

## License

MIT
