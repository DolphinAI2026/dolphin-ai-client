# aPaaS Builder AI

得帆云低代码平台的智能搭建与 Dolphin Code 集成工作台。这个仓库同时承载低代码应用搭建、全代码 Code 应用入口、后端编排服务、平台管理端、桌面交付端和部署交付材料。

## 核心能力

- 对话式生成和改造低代码应用。
- Builder / Code 双模式应用入口，低代码应用与全代码应用按 `app_type` 隔离。
- 应用目录、项目概览、需求/SPEC、配置预览、部署、租户日志和能力中心。
- Dolphin Code runtime 嵌入、会话绑定、左侧 rail 历史、runtime 反向代理和 token/cookie 隔离。
- FastAPI 后端统一承载认证、租户、应用、Agent、MCP、知识库、技能库、Git、工作区和运行态代理。
- Tauri 桌面端使用本地 sidecar、桌面账号 federation、自动更新和本机工作区能力。
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

本地可用 `backend/scripts/agentic_session.py` 管理工程会话。默认会把可写任务放到独立 Git branch + worktree 中；registry 默认写入 `~/.codex/.agentic-coding/workspaces/<repo-id>/sessions/`，也可用 `--registry-root` 覆盖。

以下示例从主仓库根目录开始执行，每段先进入 `backend/`；`--repo ..` 因而指向主仓库根目录，不能在 session worktree 内照抄。

创建功能会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. create --type feature --title "新增会话先返回再异步加载"
```

省略 `--base-branch` 时使用 `--repo` 指向仓库的当前本地分支；要固定默认分支或 release 基线，请显式传入 `--base-branch`。

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

`checkpoint` 会在对应 worktree 中执行 `git add -A`，使用内置本地身份并通过 `git commit --no-verify` 提交全部当前改动。输出 `created: false` 可能是 clean no-op、missing worktree、branch mismatch 或 `git commit` 失败；若 `git add -A` 已执行，失败后可能留下 staged 改动，调用方需检查 JSON、`git status` 和 `HEAD`。

归档会话但保留 worktree：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. archive S-001
```

`archive` 默认先尝试 checkpoint。遇到 missing worktree、branch mismatch 或提交失败时，CLI 仍返回 0 和会话 JSON；调用方必须检查 `status`、`git_state` 和 `HEAD` 判断 checkpoint 是否成功。`--no-checkpoint` 会跳过尝试：仅 dirty worktree 标记 `dirty_uncheckpointed`，clean worktree 直接归档为对应 retained 状态。

对齐真实 worktree 并回写 registry：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. reconcile
```

`reconcile` 会同步已登记会话，并为未登记的 `session/*` worktree 建立 `orphan_session`，不是只读扫描。

约束：

- `new-app` 和 `spec-change` 不允许使用 `--no-worktree`。
- 不记录文件锁、路径锁或模块锁，冲突由 Git merge/rebase 暴露。
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
| Tauri 桌面端 | `src-tauri/`、`backend/desktop_sidecar.py` | Dolphin Code 桌面壳。打包 `frontend/dist-desktop`，启动本地 Python sidecar，使用本地 SQLite、稳定本地端口、每安装实例密钥、桌面账号 federation、桌面自动更新和本机 workspace 能力。 | `bash scripts/build-desktop.sh` |
| 桌面账号服务 | `backend/services/account_service/` | 独立公网账号权威。只挂桌面登录/开号路由和桌面更新包托管，提供自包含 `/admin-ui`，供桌面 sidecar 通过 `PUBLIC_ACCOUNT_BASE_URL` federation 登录。 | `cd backend && python -m services.account_service` |
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
| 数据库 | SQLite/aiosqlite（本地、桌面）+ MySQL/aiomysql（部署） |
| 认证 | JWT + aPaaS 登录 + 桌面账号 federation |
| LLM | OpenAI/Anthropic 兼容 API，经后端和平台配置统一封装 |
| 部署 | Docker Compose、Kubernetes、Rancher 单节点、nginx、supervisord |

## 关键配置

环境变量请在本地 `backend/.env` 配置，仓库只保留占位示例：

```env
# aPaaS Platform
APAAS_BASE_URL=https://your-apaas.example.com/backend
# 本地初始化 default 租户时用于绑定 aPaaS 平台租户
APAAS_TENANT_ID=<your-apaas-tenant-id>

# LLM Configuration
LLM_API_BASE=https://your-llm-gateway.example.com/openai
LLM_API_KEY=<your-llm-api-key>
LLM_MODEL=<your-model-name>

# Database
DATABASE_URL=sqlite+aiosqlite:///./apaas_builder.db

# JWT
JWT_SECRET_KEY=<generate-a-long-random-secret>

# Dolphin Code integration
DOLPHIN_CODE_CONTROL_PLANE_URL=http://127.0.0.1:8080
DOLPHIN_CODE_CONTROL_PLANE_TOKEN=<optional-control-plane-token>
DOLPHIN_CODE_BUILDER_URL=http://127.0.0.1:5173/builder/
DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID=<seed-project-id>
```

`DOLPHIN_CODE_BUILDER_URL` 只适合本地开发 fallback。生产应通过 `DOLPHIN_CODE_CONTROL_PLANE_URL` 打开真实隔离 workspace，避免所有 Code 应用共用同一个本地 builder。

## 常用流程

1. 低代码应用：进入 `/ai-builder/` 或 `/ai-builder/apps`，创建/打开 Builder 应用，通过对话生成需求、配置和部署变更。
2. 全代码应用：进入 `/ai-builder/code`，在 Code 应用列表或 `/code/new` 创建 `ai-code` 应用，打开 Dolphin Code runtime 继续开发。
3. 平台配置：进入平台环境、LLM 配置、能力中心或管理端，维护租户环境、模型、MCP、知识和技能。
4. 桌面交付：使用 `frontend` 的 `build:desktop` 和 `scripts/build-desktop.sh` 打包 Tauri 桌面端，桌面 sidecar 本地承载后端。
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
