# 部署基础设施盘点 + 客户部署缺口分析

> 仓库：`apaas-builder-ai`（得帆云低代码平台 AI 搭建助手）
> 评审类型：**给客户部署前的就绪评审（read-only）**
> 日期：2026-05-30
> 范围：部署产物盘点 / 环境变量全量枚举 / 运行时拓扑 / 外部依赖 / 客户交付缺口

本文是后续「部署脚本」与「前置要求」的权威依据。所有结论均以源码 / 配置文件实证，文末列出佐证文件路径。

---

## 0. 一句话结论

平台 = **单容器多进程**（uvicorn 后端 + code-server Web IDE 由 supervisord 托管）+ **可选 nginx 前置** + **外置 MySQL**。
现成两种部署形态都在：单机 `docker compose`（成熟、文档全）和 `k8s` StatefulSet+sidecar（针对得帆公司 KubeSphere 集群写死了节点标签/私库/域名）。

**给客户干净交付，推荐 `docker compose` 单机形态**（k8s 清单内网耦合太深，详见 §5）。最大阻碍不是脚本，而是：①镜像只在内网私库 `hub.dfy.definesys.cn`；②默认连得帆自家 aPaaS（`apaas-poc.definesys.cn`）和 LLM（`api.minimaxi.com`）；③首个管理员账号靠「登录时镜像 aPaaS 用户」自举，**没有 aPaaS 就没有第一个管理员**。

---

## 1. 现有部署产物盘点

### 1.1 单机容器（`deploy/docker/`）——【主推形态，文档最全】

| 产物 | 作用 | 覆盖形态 |
|---|---|---|
| `Dockerfile` | 5-stage 构建：①Vite 构建前端 → ②构建 code-server 睿鲸扩展 VSIX → ③拉 JDK8/JDK17/Maven 二进制 → ④`python:3.12-slim` 运行时（装 Node20、docker CLI、code-server、后端 pip 依赖、补丁 code-server Chat）。PID1 = supervisord。**前端 dist 打进镜像**，workspaces 走 volume。apt 源换阿里云镜像。 | 单机 compose / k8s 共用同一镜像 |
| `docker-compose.yml` | 单 service `apaas-builder`，**`network_mode: host`**，`restart: unless-stopped`。挂 3 个 volume：workspaces（host 路径=容器内路径，关键）、`/var/run/docker.sock`（DinD 起 vibe-sandbox 子容器）、`.env`（只读）。healthcheck 探 `/api/health` + openapi 含 harness 路由。 | 单机 compose（host 网络） |
| `entrypoint.sh` | 建 workspace/npm-cache 目录 → 可选探活 MySQL（解析 `DATABASE_URL`，30s 超时，失败仅警告不阻断）→ `exec supervisord`。 | 容器启动入口 |
| `supervisord.conf` | 容器内 2 个进程：`uvicorn`（端口 `PORT`，默认 8003，**强制 `--workers 1`**，因 `platform_proxy._proxy_state` 是模块级全局 dict）+ `code-server`（`CODE_SERVER_BIND_HOST:CODE_SERVER_PORT`，默认 127.0.0.1:8080，`--auth none`）。日志全走 stdout/stderr。 | 容器内进程管理 |
| `nginx.conf.example` | **宿主机** nginx 片段示例（容器自身不含 nginx）。演示 `/ai-builder-docker/` 与裸跑 `/ai-builder/` 并存：转发 `/api`→8103、`/ide`→8090、SPA dist。含 WebSocket upgrade map、SSE `proxy_buffering off`。**写死示例域名 `agent.dfy.definesys.cn`**。 | 单机 compose 的反代层（可选） |
| `compose.env.example` | compose 变量样例：场景 A 主机独占（8003/8080，`/ai-builder/`）vs 场景 B 与裸跑并存（8103/8090，`/ai-builder-docker/`）。**注意：这是 compose 编排变量（端口/路径/容器名/卷目录），不是后端业务 env**——后端业务 env 走 `BACKEND_ENV_FILE` 指向的独立文件。 | 单机 compose |
| `cache/` | （构建缓存目录，非交付物） | — |

> ⚠️ **compose 用 host 网络 + 挂 docker.sock**：后端要起 vibe-sandbox 子容器，必须复用宿主 docker daemon，且 workspace 路径两侧一致。这对客户环境是强假设（客户机要有 docker daemon、要允许挂 sock）。若客户不用 Vibe Coding，可去掉 sock 挂载并设 `VIBE_CODING_RUNTIME=host`（§2 说明）。

### 1.2 K8s（`deploy/k8s/`，00→61）——【内网耦合形态，慎用】

| 文件 | 作用 |
|---|---|
| `00-namespace.yaml` | namespace `apaas-builder` + label `apaas.definesys.com/app-tier` |
| `15-configmap-nginx.yaml` | sidecar nginx 配置：`/ai-builder/ide`→8080、`/ai-builder/api`→8003、平台代理路由（`/platform`/`/backend`/`/xdap-`/`/apaas`）、32-hex 插件资源、SPA 兜底 |
| `20-pvc-workspaces.yaml` | PVC `apaas-workspaces`，**`storageClassName: local-path`**，50Gi，RWO |
| `30-statefulset.yaml` | StatefulSet replicas=1。**initContainer** 把镜像内 dist 拷到 emptyDir 给 sidecar serve。**主容器**（uvicorn+code-server）+ **sidecar `nginx:alpine`**。**写死镜像 `hub.dfy.definesys.cn/ai-builder/apaas-builder:20260428-ruijing`**、**nodeAffinity `app-tier`**、**`imagePullSecrets: regcred-hub-dfy`**。backend.env 来自 Secret `apaas-backend-env`。 |
| `40-service.yaml` | ClusterIP `apaas-builder:80` + headless service |
| `50-ingress.yaml` | ingressClass `nginx`，**host 写死 `df-aigc.dfy.definesys.cn`**，TLS 段注释掉（默认 HTTP），路径 `/ai-builder` + `/` |
| `60-vibe-rbac.yaml` | ServiceAccount `vibe-sandbox-manager` + Role/RoleBinding：管 Pod/exec/log、Service、Ingress、PVC（给 `k8s_runtime.py` 起沙箱 Pod 用） |
| `61-vibe-ingress.yaml` | Vibe 沙箱 per-workspace 动态 Ingress 的占位（方案 A `*.vibe-first.cn` 通配撞 nginx "if is evil" 已废，方案 B 动态 Ingress 仍是 TODO 未落地）。只留一个不路由流量的 placeholder Service。 |
| `README.md` | K8s 部署手册：前置（MySQL 在 `mysql` namespace、账号 `apaas:apaas2024`、镜像私库、节点标签、IngressClass）、建 Secret、改域名、apply 顺序、升级/回滚/拆除/排错。**正文写死内网 IP `172.23.39.215/234/237/246`、私库、域名、MySQL 账号明文**。 |

### 1.3 宿主裸跑脚本（根目录）+ 其它

| 产物 | 作用 | 形态 |
|---|---|---|
| `start.sh` | **本地开发/裸跑**一键起：拉起本地 MySQL（`~/mysql`，账号 `apaas:apaas2024`）→ 建/校验后端 venv（Python 3.13）+ 前端 node_modules → 起 code-server → 起后端（`run.py`，8000）→ 起前端（`npm run dev`，5173）。前台守护模式 Ctrl+C 自动 stop。 | 本地/裸机开发 |
| `stop.sh` | 停后端/前端/code-server（launchctl + pid + 端口兜底） | 本地 |
| `test.sh` | 烟雾检查：主文件存在 + 依赖装好 + `.env` 在 | 本地 |
| `backend/run.py` | `uvicorn.run("app.main:app", host=settings.host, port=settings.port)` 单进程入口 | 通用 |
| `scripts/deploy_cloud.py` | **paramiko SSH 推送式部署**到固定云主机（默认 `101.132.123.203` 阿里云 ECS）。打 tar 上传 backend/前端 dist → pip install → 重启 uvicorn（systemd 或 pkill+nohup，8003）→ 本地+公网健康检查（**`agent.dfy.definesys.cn`**）。可选 `--include-ide` 推睿鲸扩展 + patch code-server。 | 内网裸机运维（非客户交付） |
| `.github/workflows/deploy.yml` | GitHub Actions `workflow_dispatch`：构建前端（`VITE_BASE_URL=/ai-builder/`）→ 内联 paramiko 脚本 SSH 到 `secrets.SERVER_HOST` 部署 backend+前端 → 健康检查 + harness 路由探测。 | 内网 CI 运维（非客户交付） |
| `deploy/nginx/vibe-preview.conf.example` | 宿主 nginx：`p<port>.vibe-first.cn` 通配子域反代到 podman 沙箱端口。**写死 `vibe-first.cn`**。 | Vibe 预览（可选） |
| `deploy/nginx/vibe-first-aliyun-ecs.conf` | 阿里云 ECS 反代到 k8s ingress（`172.23.39.x`）的 upstream 配置。**纯内网，全是写死 IP**。 | 内网（非客户交付） |

**结论**：`scripts/deploy_cloud.py`、`.github/workflows/deploy.yml`、`deploy/nginx/vibe-first-aliyun-ecs.conf`、`start.sh` 都是**得帆内网自用运维**，不是客户交付路径，客户部署应忽略。客户交付的候选只有 `deploy/docker/` 和 `deploy/k8s/`。

---

## 2. 环境变量全量枚举

合并来源：`backend/app/config.py`（pydantic `Settings`）+ `backend/.env.example` + `deploy/docker/compose.env.example` + `frontend/.env.production` + 全仓 `os.getenv/os.environ`（`grep` 实证）。

**敏感**=密钥/凭证/密码，绝不可进镜像/进仓库；**必填**=不给就起不来或核心功能不可用。

### 2.1 后端业务 env（写进 `BACKEND_ENV_FILE` / Secret / `.env`）

| 变量名 | 必填 | 敏感 | 用途 | 默认 / 示例 |
|---|:--:|:--:|---|---|
| `LLM_API_KEY` | ✅ **是**（pydantic 无默认，缺则启动崩） | 🔑 | LLM 调用密钥 | `REPLACE_WITH_YOUR_API_KEY` |
| `JWT_SECRET_KEY` | ✅ **是**（pydantic 无默认，缺则启动崩） | 🔑 | 签发平台 JWT | `your-secret-key-change-in-production` |
| `DATABASE_URL` | ✅ 生产是（prod 必接 MySQL） | 🔑（含库密码） | 数据库连接串 | dev 默认 `mysql+aiomysql://root:password@localhost:3306/apaas_builder`；支持 `sqlite+aiosqlite:///...`（dev）；prod 例 `mysql+aiomysql://apaas:apaas2024@host:3306/apaas_builder?charset=utf8mb4` |
| `APAAS_BASE_URL` | ✅ 是（核心功能依赖 aPaaS） | 否 | 得帆云 aPaaS 后端地址 | `https://apaas-poc.definesys.cn/backend` |
| `APAAS_TENANT_ID` | ✅ 是 | 否 | aPaaS 默认租户 ID | `743906758237356033`（**得帆 POC 租户，硬编码默认值**） |
| `ENCRYPTION_KEY` | ✅ **强烈建议**（生产必改） | 🔑 | Fernet 派生密钥，加密 aPaaS/平台账号密码存库（`crypto.py` SHA256 派生） | `default-key-change-in-production-32b`（**不安全默认**） |
| `ANTHROPIC_BASE_URL` | 否 | 否 | 运行时实际走的 LLM 网关（OpenAI/Anthropic 兼容） | `https://api.minimaxi.com/anthropic` |
| `ANTHROPIC_API_KEY` | 否（缺则回退 `LLM_API_KEY`） | 🔑 | 同上密钥 | 空 |
| `ANTHROPIC_MODEL` / `LLM_MODEL` / `LLM_DOC_MODEL` / `LLM_VISION_MODEL` | 否 | 否 | 主/文档/视觉模型名 | `MiniMax-M2.7` / `claude-haiku-4-5-...` |
| `LLM_API_BASE` | 否（兼容保留，运行时不再实际参与） | 否 | 历史字段 | `https://api.minimaxi.com/anthropic` |
| `JWT_ALGORITHM` | 否 | 否 | JWT 算法 | `HS256` |
| `JWT_EXPIRE_MINUTES` | 否 | 否 | token 有效期（分钟） | `1440` |
| `HOST` | 否 | 否 | 后端绑定地址 | `0.0.0.0` |
| `PORT` | 否 | 否 | 后端端口（compose/k8s 注入 8003） | `8000`（dev）/`8003`（容器） |
| `ENABLE_CODE_SUFFIX` | 否 | 否 | 资源编码加随机后缀（避冲突）；生产建议 false | `false` |
| `CODE_SERVER_BASE_URL` | 否（空则**禁用** Web IDE 按钮） | 否 | code-server 外部访问 URL | 空；例 `https://<host>/ai-builder/ide/` |
| `CODING_MAX_TURNS` / `VERIFICATION_MAX_TURNS` | 否 | 否 | Agent 轮次上限 | 30 / 20 |
| `CODING_MODEL_{DEEPSEEK,QWEN,GPT54,CODEX,SONNET,OPUS}_{BASE_URL,API_KEY,MODEL}` | 否 | 🔑（API_KEY 项） | IDE 多模型路由上游（前端 model 字段选择） | 全空 |
| `DOLPHIN_BASE_URL` / `DOLPHIN_API_KEY` / `DOLPHIN_MODEL` | 否 | 🔑（KEY 项） | **把 dolphin omnigate 当普通 LLM provider**（OpenAI 兼容 `gpt-5.5`），非业务集成；`seed_data.py` 据此 seed 一条内置 LLM 配置 | 全空 / `gpt-5.5` |
| `VIBE_CODING_RUNTIME` | 否 | 否 | `auto`/`docker`/`host`：沙箱运行时选择（客户不挂 docker.sock 时设 `host`） | `auto` |
| `VIBE_CODING_IDLE_THRESHOLD_SEC` | 否 | 否 | 沙箱空闲回收秒数 | `1800` |
| `AI_BUILDER_CHAT_DEEPLINK_BASE` | 否 | 否 | 给外部 MCP 客户端下发 deeplink 的对外 URL | 空；例 `https://ai-builder.dfy.definesys.cn` |

### 2.2 进程环境变量（只读 `os.environ`，**不走 pydantic，必须在 Pod/compose env 显式注入**）

| 变量名 | 必填 | 敏感 | 用途 | 默认 / 示例 | 实证 |
|---|:--:|:--:|---|---|---|
| `APAAS_WORKSPACE_ROOT` | ✅ 容器必注 | 否 | workspace 根目录；**仅写 .env 不生效，后端直接读进程 env**，缺则回退镜像内 `/app/workspaces`（与 code-server/PVC 不一致） | `/data/apaas/workspaces`（compose）/`/root/apaas-builder/workspaces`（k8s） | `coding/workspace.py:34` |
| `APAAS_NPM_CACHE_DIR` | 否 | 否 | npm 缓存目录 | 默认 `$WORKSPACE_ROOT/.npm-cache` | `coding/tools.py:30` |
| `CODE_SERVER_BIND_HOST` | 否 | 否 | code-server 绑定地址（k8s sidecar 同 Pod 用 127.0.0.1） | `127.0.0.1` | `supervisord.conf:54` |
| `CODE_SERVER_PORT` | 否 | 否 | code-server 端口 | `8080` | `supervisord.conf:54` |
| `WAIT_FOR_MYSQL` | 否 | 否 | entrypoint 是否探活 MySQL | `1` | `entrypoint.sh:18` |
| `MCP_API_KEYS` | 否（不设则 MCP `/api/mcp` 端点拒绝外部调用） | 🔑 | 逗号分隔的 MCP 客户端鉴权 key（dolphin/外部 agent 调工具用） | 空 | `mcp_server.py:54` |
| `MCP_ALLOWED_HOSTS` | 否 | 否 | MCP TrustedHost 白名单 | 空 | `mcp_server.py:283` |
| `MCP_INTERNAL_BASE` / `MCP_BRIDGE_BASE_URL` / `MCP_BRIDGE_AUTH_KEY` | 否 | 🔑（auth key） | ai-chat 内置 agent 走 MCP 的 loopback 地址/鉴权 | 空 | `ai_chat/mcp_bridge.py:48` |
| `MCP_V2_INTERNAL_BASE` / `MCP_V2_HOST` | 否 | 否 | admin/builder MCP 页面**代理到内网 mcp-server-v2** 的地址/Host 头 | `http://apaas-builder-mcp-server:8004` / **`agent.dfy.definesys.cn`** | `routes/admin_mcp.py:42,51` |
| `APAAS_BUILDER_PUBLIC_URL` | 否（空走相对路径） | 否 | MCP 工具返回应用查看链接的公网前缀 | 空 | `mcp_server.py:96` |
| `BUILDER_FERNET_KEY` | 否（用 git OAuth 才需；缺则 dev fallback **不安全**） | 🔑 | **第二把** Fernet key，加密 git 连接 token（与 `ENCRYPTION_KEY` 是两套独立密钥） | dev dummy `dGVzdC1mYWxsYmFjay1rZXktMzItYnl0ZXMtZGV2PT0=` | `git/connection.py:18` |
| `BUILDER_PUBLIC_URL` | 否 | 否 | git OAuth 回调拼接的对外地址 | `http://localhost:5173` | `routes/git_connection.py:309` |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` / `GITHUB_OAUTH_SCOPE` | 否（仅 GitHub 集成） | 🔑 | GitHub OAuth | 无 | `routes/git_connection.py:339+` |
| `GITLAB_CLIENT_ID` / `GITLAB_CLIENT_SECRET` / `GITLAB_HOST` / `GITLAB_OAUTH_SCOPE` | 否（仅 GitLab 集成） | 🔑 | GitLab OAuth | `https://gitlab.com` | `routes/git_connection.py:351+` |
| `APAAS_NPM_REGISTRY` / `NPM_CONFIG_REGISTRY` | 否 | 否 | 沙箱/工作区 npm 私有源 | 代码内默认指向 `registry.dfy.definesys.cn`（见 §5） | `coding/tools.py:393` |
| `CHROME_DEVTOOLS_BROWSER_URL` | 否（浏览器工具才用） | 否 | Playwright/CDP 地址 | `http://127.0.0.1:9222` | `browser_mcp_bridge.py:31` |
| `SPEC_CHAT_USE_REAL_LLM` | 否 | 否 | spec-chat 是否走真 LLM（测试开关） | 空 | `routes/applications/spec_chat.py:84` |

### 2.3 前端 env（build 时注入，固化进 dist）

| 变量名 | 必填 | 用途 | 默认 / 示例 |
|---|:--:|---|---|
| `VITE_BASE_URL` | ✅（决定部署路径前缀） | 路由/资源前缀 + 运行时 API base（前端用 `import.meta.env.BASE_URL + 'api'` 拼相对地址，**不写死域名**，可移植性好） | `/ai-builder/`（默认 build arg）/`/`（dev） |
| `VITE_SANDBOX_PREVIEW_BASE` | 否（Vibe 预览才用） | Vibe 沙箱预览子域后缀 | **`.vibe-first.cn`**（`frontend/.env.production`，写死得帆域名） |

> 前端 API 寻址：`frontend/src/utils/request.ts` —— dev 固定 `/api`（Vite 代理到 8000），prod 走 `${BASE_URL}api` 相对路径。**前端不含写死的后端域名**（除 Vibe 预览后缀 + 一处 ProcessNodePropsPanel 的展示性占位 `agent.dfy...`），换域名只需改 nginx host，不必重打前端（除非改路径前缀 `VITE_BASE_URL`）。

### 2.4 部署运维 env（不进运行时，给脚本用）

`scripts/deploy_cloud.py` 读：`APAAS_DEPLOY_HOST/USER/PORT/PASSWORD/KEY_FILE`、`SERVER_HOST/USER/PASSWORD/KEY_FILE`、`APAAS_REMOTE_BASE`、`APAAS_CODE_SERVER_DATA_DIR/SERVICE`。
`.github/workflows/deploy.yml` 读 GitHub Secrets：`SERVER_HOST/USER/PASSWORD`。
→ **客户交付不涉及这些**（内网 SSH 运维专用）。

---

## 3. 运行时组件与拓扑

### 3.1 单容器内部（supervisord 托管 2 进程）

```
容器 apaas-builder (PID1 = supervisord)
 ├─ uvicorn  app.main:app   :8003 (--workers 1, 必须单 worker)
 │    ├─ FastAPI 业务 API（/api/*）
 │    ├─ 平台代理 platform_proxy（透传 aPaaS /backend /xdap-* /platform，模块级全局状态 → 故单 worker）
 │    ├─ 内嵌 MCP server（mount /api/mcp/mcp + /api/mcp-legacy/sse，受 MCP_API_KEYS 鉴权）
 │    └─ 启动钩子 lifespan: init_db() → seed_initial_data() → seed_industry/marketplace → 启动恢复 sweep
 └─ code-server :8080 (--auth none, 服务 workspace 目录, Web IDE)
内置但默认不跑：JDK8/JDK17/Maven（后端打 aPaaS Java 包用）、docker CLI（起 vibe-sandbox 子容器）、Playwright（浏览器二进制默认不装）
```

前端 dist **打进镜像**（`/app/frontend/dist`），由前置 nginx（compose 宿主 / k8s sidecar）serve。

### 3.2 整体拓扑

```
                       浏览器 (HTTPS)
                          │
                  ┌───────┴────────┐
   compose 形态：  宿主 nginx        k8s 形态：Ingress(nginx) → Service:80
   (nginx.conf.example)               → Pod sidecar nginx:alpine (15-configmap-nginx)
                          │
        ┌─────────────────┼──────────────────────┐
        ▼ /ai-builder/    ▼ /ai-builder/api/      ▼ /ai-builder/ide/
   静态 dist(前端)     uvicorn :8003          code-server :8080
                          │
                          ▼ (出站)
        ┌────────────┬─────────────┬───────────────┐
   外置 MySQL   aPaaS 平台      LLM 网关         (可选) dolphin/git/npm私源
   (业务库)    (apaas_base_url) (anthropic_base) (omnigate / github / registry.dfy)

   旁路：uvicorn ──DinD(docker.sock)/k8s API──▶ vibe-sandbox 子容器/Pod（Vibe Coding 沙箱）
```

### 3.3 端口

| 端口 | 进程 | 暴露 |
|---|---|---|
| 8003（容器）/8000（dev） | uvicorn 后端 | 经 nginx |
| 8080 | code-server | 经 nginx `/ide` |
| 80 | k8s sidecar nginx | Service/Ingress |
| 5173 | Vite dev | 仅本地开发 |
| 8082+ / 30000-65999 | 工作区 dev-server / vibe 沙箱端口 | Vibe 预览（可选） |

### 3.4 数据卷与持久化

| 卷 | 内容 | compose | k8s |
|---|---|---|---|
| workspaces | 用户工作区代码 + `.npm-cache` | host bind（路径两侧一致，默认 `/data/apaas/workspaces`） | PVC `apaas-workspaces`（local-path 50Gi RWO，绑定固定节点） |
| 数据库 | 全部业务数据（应用/对话/SPEC/用户/凭证…） | **外置 MySQL，不在容器内** | 同，外置 `mysql` namespace |
| 前端 dist | 静态资源 | 打进镜像 | initContainer 拷到 emptyDir |
| backend.env | 业务 env | host 只读 bind | Secret `apaas-backend-env` |

**关键**：MySQL 在容器/Pod 外。客户必须自备一个可达的 MySQL（5.7+/8.0），库 + 账号预建。容器**不自带数据库**。

### 3.5 数据库初始化（无 Alembic）

`init_db()`（`database.py`）= `Base.metadata.create_all` **自动建表** + 一长串幂等 `ALTER TABLE ... ADD COLUMN`（try/except 吞「列已存在」）+ 一次性 legacy `specs`→`builder_specs` 迁移。**没有 Alembic / 迁移版本管理**，靠「create_all + 手写 ALTER」演进 schema。
`seed_initial_data()` 建：默认租户（`tenant_code=default`）+ 三个角色（`R_tenant_admin`/`R_developer`/`R_viewer`）+ 据 env 同步内置 LLM 配置。**不 seed 任何用户**。

→ 客户侧只需建空库 + 授权账号，首次启动自动建表 + seed 租户/角色。**但「第一个登录用户」靠 aPaaS 自举**（见 §5）。

---

## 4. 外部依赖与网络出口

| 外部服务 | 默认地址 | 部署必须连通？ | 说明 |
|---|---|:--:|---|
| **外置 MySQL** | `DATABASE_URL` | ✅ **必须**（不连起不来） | 业务数据库；客户自备，库+账号预建 |
| **aPaaS 平台** | `apaas-poc.definesys.cn/backend` | ✅ **核心功能必须** | 生成的低代码应用真正落地的平台；登录自举、应用上线、平台代理全靠它。**不连=产品没价值** |
| **LLM 网关** | `api.minimaxi.com/anthropic` | ✅ **核心功能必须** | AI 搭建/对话/生成全靠它。可换任意 OpenAI/Anthropic 兼容网关 |
| 镜像私库 | `hub.dfy.definesys.cn` | ⚠️ 部署期必须（拉镜像） | 客户拉不到内网私库 → **必须改用客户能访问的 registry 或离线导入**（§5 头号缺口） |
| 公网 apt/npm/github（构建期） | aliyun mirror / nodesource / deb.nodesource / github releases (code-server) / download.docker.com | ⚠️ **构建镜像时必须**（运行时不需要） | Dockerfile 构建拉 Node/code-server/docker CLI。客户若离线，应由交付方**预构建镜像**后导入，不让客户现场 build |
| 得帆私有 npm 源 | `registry.dfy.definesys.cn/repository/apaas-npm-group/`、maven `registry.dfy.definesys.cn/.../maven-public/` | ⚠️ 仅 Vibe/打包用 | 沙箱装依赖、Maven 打 aPaaS 包时拉私有源（代码内写死，见 §5）。客户环境若用此功能需替换 registry |
| dolphin omnigate | `DOLPHIN_BASE_URL`（空） | ❌ 可选 | 仅当作 LLM provider；不配不影响主链路 |
| GitHub/GitLab | `gitlab.com` / `GITLAB_HOST` | ❌ 可选 | 仅 git 连接/OAuth 功能用，不配则该功能不可用 |
| mcp-server-v2 内网服务 | `apaas-builder-mcp-server:8004` | ❌ 可选 | admin/builder「MCP」页面代理目标；客户环境无此服务则该页面空，**不影响核心** |

---

## 5. 客户部署缺口分析（关键）

按阻塞程度排序。每条给出**实证位置**与**处置建议**。

### 🔴 P0 — 硬阻塞「干净交付」

1. **镜像只在内网私库 `hub.dfy.definesys.cn`**
   - 实证：`deploy/k8s/30-statefulset.yaml:31,48`（写死 `hub.dfy.definesys.cn/ai-builder/apaas-builder:20260428-ruijing` + `imagePullSecrets: regcred-hub-dfy`）、README 升级章节、compose 走本地 `build` 但 tag 仍 `apaas-builder:latest`。
   - 处置：交付方**预构建镜像**（`docker build`）→ 导出 `docker save` tar 或推到**客户可达 registry**；compose 形态客户现场 `build` 需公网（拉 Node/code-server/docker CLI/apt），离线必须改预构建+导入。

2. **首个管理员账号靠「登录时镜像 aPaaS 用户」自举，无独立注册**
   - 实证：`routes/auth.py:833 login` → `_try_apaas_login_flow` → `_ensure_apaas_user`（`:582`，据 aPaaS `user_info` 建本地 User 并设 `is_platform_admin`）。`seed_data.py` **只 seed 租户+角色，不 seed 用户**。本地 `tenant-users/invite`（`:2262`）创建用户又要求调用者已是 tenant admin（鸡生蛋）。
   - 缺口：**没有 aPaaS 连通就没有第一个能登录的管理员**；纯离线/不接 aPaaS 的客户无法自举登录。
   - 处置：要么保证客户接得帆 aPaaS（用 aPaaS 账号登录自举），要么交付方提供「初始化管理员」脚本/一次性 seed（当前仓库**缺这个**）。

3. **默认连得帆自家 aPaaS + LLM，默认值写死在 `config.py`**
   - 实证：`config.py:26-27`（`apaas-poc.definesys.cn` + 租户 `743906758237356033`）、`:31,36`（`api.minimaxi.com`）。
   - 处置：客户部署**必须**在 backend.env 覆盖 `APAAS_BASE_URL`/`APAAS_TENANT_ID`/`ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`/`LLM_API_KEY` 为客户自己的 aPaaS 与 LLM 凭据。

### 🟠 P1 — 需改配置/文档才能交付

4. **不安全密钥默认值（生产必改，否则数据可被解密/JWT 可伪造）**
   - 实证：`ENCRYPTION_KEY=default-key-change-in-production-32b`（`config.py:53`，加密落库的 aPaaS/平台密码）；`JWT_SECRET_KEY=your-secret-key-change-in-production`（`.env.example`）；`BUILDER_FERNET_KEY` dev dummy（`git/connection.py:21`，加密 git token）。
   - 处置：部署脚本应**强制生成随机值**并写入 Secret（两把 Fernet key 是独立的，都要换）。

5. **K8s 清单深度耦合得帆 KubeSphere 集群**（不可直接给客户 apply）
   - 实证：nodeAffinity `apaas.definesys.com/app-tier`（`30-statefulset.yaml:25`，README 说「集群里目前只有 `i8vbj7weas0dx1id3v9wa` 有这标签」）、`storageClassName: local-path`（`20-pvc:9`）、ingress host `df-aigc.dfy.definesys.cn`（`50-ingress.yaml:21`）、内网 IP `172.23.39.215/234/237/246`（README:99 + `vibe-first-aliyun-ecs.conf`）、MySQL DNS `mysql.mysql.svc.cluster.local` + 明文账号 `apaas:apaas2024`（README:55）。
   - 处置：客户若用 k8s，需逐项替换 storageClass/节点标签/host/registry/MySQL。**工作量大于 compose**，故推荐 compose。

6. **管理后台「MCP」页面代理到内网 mcp-server-v2，默认 Host 头写死 `agent.dfy.definesys.cn`**
   - 实证：`routes/admin_mcp.py:42,51` + `routes/builder_mcp.py:38,42`（`MCP_V2_INTERNAL_BASE=http://apaas-builder-mcp-server:8004`，`MCP_V2_HOST=agent.dfy.definesys.cn`）。
   - 处置：客户环境无此服务 → 该后台页面取数失败（**不影响核心搭建链路**）。如客户不需要该页面可忽略；需要则部署 mcp-server-v2 并改这两个 env。

7. **沙箱/打包私有源写死 `registry.dfy.definesys.cn`**
   - 实证：`coding/prompts.py:33`、`dev_scene_workflow.py:27`、`coding/workspace.py:735`、`apaas_backend_templates.py:98`、`mcp_server.py:6987+`（npm/maven 私有源）。`apaas-dev8.dfy.definesys.cn`、`apaas-qa.dfy.definesys.cn` 作平台 URL fallback（`coding/pipeline.py:1823`、`routes/coding.py:2901`）。
   - 处置：Vibe Coding / aPaaS Java 打包功能在客户环境需用 `APAAS_NPM_REGISTRY` 覆盖 + 替换 maven 私有源（部分硬编码在 prompt/模板里，**env 覆盖不全**，可能需改代码）。不用这些功能则无影响。

### 🟡 P2 — 提示项（不阻塞但需告知）

8. **Vibe Coding 沙箱依赖强（docker.sock / k8s RBAC + 私库镜像 `vibe-sandbox:latest`）**：compose 要挂宿主 docker.sock 并预构建 `vibe-sandbox:latest`；k8s 要 RBAC + 动态 Ingress（后者**仍是 TODO 未落地**，`61-vibe-ingress.yaml`）。客户不用 Vibe → 设 `VIBE_CODING_RUNTIME=host`、去 sock 挂载。
9. **`--workers 1` 硬约束**：`platform_proxy` 模块级全局状态决定后端**不能多 worker 横向扩**（单 Pod/单进程）。高并发需另设计。
10. **无 Alembic**：schema 靠 `create_all`+手写 `ALTER`，升级时新列靠 try/except 兜底；跨大版本迁移无回滚机制。
11. **构建期换了阿里云 apt 镜像**（`Dockerfile:86`）：海外/特定网络客户现场 build 可能更慢/失败，强化「预构建交付」结论。

---

## 6. 全部硬编码内部域名 / IP 清单（佐证）

| 值 | 类型 | 出现位置（代表） | 性质 |
|---|---|---|---|
| `apaas-poc.definesys.cn` | aPaaS 默认 | `config.py:26`、`.env.example:2`、`routes/applications/_helpers.py:830` | env 可覆盖 |
| `apaas-trial.definesys.cn` | aPaaS 示例 | `mcp_server.py:357`（工具示例） | 文案 |
| `apaas-dev8.dfy.definesys.cn` | 平台 URL fallback | `coding/pipeline.py:1823`、`coding/workspace.py:2184`、`routes/coding.py:2901-2913` | 代码写死 fallback |
| `apaas-qa.dfy.definesys.cn` | 平台 URL | （平台代理相关） | 代码写死 |
| `api.minimaxi.com` | LLM 默认 | `config.py:31,36`、`.env.example` | env 可覆盖 |
| `agent.dfy.definesys.cn` | 公网入口/Host头 | `routes/admin_mcp.py:51`、`routes/builder_mcp.py:42`、`mcp_server.py:91`、`scripts/deploy_cloud.py:39`、`nginx.conf.example:25` | 部分 env 可覆盖（MCP_V2_HOST），部分写死 |
| `df-aigc.dfy.definesys.cn` | k8s ingress host | `50-ingress.yaml:21`、`15-configmap` 注释、README | k8s 写死 |
| `hub.dfy.definesys.cn` | 镜像私库 | `30-statefulset.yaml:31,48`、README | k8s 写死（**P0**） |
| `registry.dfy.definesys.cn` | npm/maven 私有源 | `coding/prompts.py:33`、`dev_scene_workflow.py:27`、`coding/workspace.py:735`、`apaas_backend_templates.py:98`、`mcp_server.py:6987+` | 代码写死（**P1**） |
| `ai-agent.dfy.definesys.cn/omnigate/0` | dolphin 网关示例 | `routes/llm_configs.py:30` | 示例/默认 |
| `ai-builder.dfy.definesys.cn` | deeplink 示例 | `config.py:106` 注释 | 文案 |
| `vibe-first.cn` / `p38451.vibe-first.cn` / `.vibe-first.cn` | Vibe 预览子域 | `frontend/.env.production:6`、`deploy/nginx/vibe-preview.conf.example`、`deploy/nginx/vibe-first-aliyun-ecs.conf` | 前端 build + nginx 写死 |
| `101.132.123.203` | 阿里云 ECS（部署目标） | `scripts/deploy_cloud.py:35` | 运维脚本（非交付） |
| `39.103.201.110` | 阿里云 ECS 公网入口 | `deploy/nginx/vibe-first-aliyun-ecs.conf:2` | 运维（非交付） |
| `172.23.39.215/234/237/246` | k8s ingress 节点内网 IP | `deploy/k8s/README.md:99`、`deploy/nginx/vibe-first-aliyun-ecs.conf:15-18` | 内网（非交付） |
| `mysql.mysql.svc.cluster.local` + `apaas:apaas2024` | k8s 集群内 MySQL + 明文账号 | `deploy/k8s/README.md:32,55` | k8s 文档明文（**P1 安全**） |
| `743906758237356033` | aPaaS 默认租户 ID | `config.py:27`、README:45 | env 可覆盖 |
| `apaas2024` | MySQL 密码 | `start.sh:23`、README | 本地/文档（生产必改） |

> 源码内**未发现**生产级密钥/token 硬编码（dolphin-prod token、mcp api key 等只出现在 MEMORY/handoff 文档，不在 `backend/app` / `frontend/src` 源码）。落库密码用 Fernet 加密。

---

## 7. 「客户部署前置要求」草稿要点

交付前请客户准备 / 交付方确认：

**基础设施**
1. 一台 Linux 主机（推荐 ≥4C8G），装 **Docker + docker compose**；如需 Vibe Coding，允许容器挂 `/var/run/docker.sock` 并预置 `vibe-sandbox:latest` 镜像。
2. 一个可达的 **MySQL 5.7+/8.0**，预建空库（如 `apaas_builder`，`utf8mb4`）+ 授权账号。容器不自带 DB，首启自动建表。
3. （HTTPS）一个域名 + TLS 证书，前置 nginx 终止 TLS（麦克风/Vibe 预览需 HTTPS）。

**镜像与网络**
4. **由交付方预构建镜像**并提供（`docker save` tar 或推到客户可达 registry）——客户环境通常拉不到 `hub.dfy.definesys.cn`，也不应现场 build（构建期需公网拉 Node/code-server/docker CLI）。
5. 客户主机需出站可达：**客户自己的 aPaaS 平台** + **LLM 网关**（二者是核心，不通则产品无价值）。其余（dolphin/github/私有 npm 源）按需。

**必填配置（backend.env，由部署脚本生成 Secret）**
6. `LLM_API_KEY`、`JWT_SECRET_KEY`（缺这两个**启动直接崩**）。
7. `DATABASE_URL` 指向客户 MySQL。
8. `APAAS_BASE_URL` + `APAAS_TENANT_ID` 指向**客户自己的 aPaaS 租户**（覆盖得帆 POC 默认值）。
9. `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`（+ 模型名）指向客户 LLM。
10. **随机生成并固化**：`ENCRYPTION_KEY`（落库密码加密）、`JWT_SECRET_KEY`，用 git 功能再加 `BUILDER_FERNET_KEY`。绝不用默认值。
11. 进程 env 显式注入：`APAAS_WORKSPACE_ROOT`（= 卷挂载路径）、`PORT`、`CODE_SERVER_BIND_HOST`；要 Web IDE 则设 `CODE_SERVER_BASE_URL=https://<host>/ai-builder/ide/`。
12. 前端路径前缀：若非 `/ai-builder/` 需用 `VITE_BASE_URL=<前缀>` 重新构建镜像 + 同步改 nginx location。

**首个管理员（重要前置决策）**
13. 当前**第一个登录用户依赖 aPaaS 自举**（用 aPaaS 账号登录后自动镜像为本地管理员）。若客户接了自己的 aPaaS → 用 aPaaS 管理员账号首登即可。**若客户不接 aPaaS**，当前仓库**缺独立初始化管理员的手段**，需交付方补一个 seed 脚本/接口（待开发）。

**可选关闭项（客户不用就省依赖）**
14. 不用 Vibe Coding：`VIBE_CODING_RUNTIME=host` + 去掉 docker.sock 挂载。
15. 不用 git 集成 / dolphin / 后台 MCP 页面：相关 env 留空即可，不影响核心搭建链路。

---

## 8. 推荐交付形态

**首选：单机 `docker compose`（`deploy/docker/`）**
- 理由：文档最全、改动面最小（只需 backend.env + 预构建镜像 + 外置 MySQL）、不假定 k8s 集群。
- 必做改造：①预构建镜像并导入/换 registry；②backend.env 全量覆盖 aPaaS/LLM/DB/密钥；③（可选）去 docker.sock + `VIBE_CODING_RUNTIME=host` 若不用 Vibe；④前置 nginx + TLS。

**次选：`k8s`（`deploy/k8s/`）** —— 仅当客户本就跑 k8s 且能逐项替换 storageClass/节点标签/ingress host/registry/MySQL；否则改造成本高于 compose。

**不交付**：`scripts/deploy_cloud.py`、`.github/workflows/deploy.yml`、`deploy/nginx/vibe-first-aliyun-ecs.conf`、`start.sh`（均为得帆内网自用运维）。

---

## 附：关键佐证文件路径

- 部署产物：`deploy/docker/{Dockerfile,docker-compose.yml,entrypoint.sh,supervisord.conf,nginx.conf.example,compose.env.example}`、`deploy/k8s/{00..61,README.md}`、`deploy/nginx/*`、`scripts/deploy_cloud.py`、`.github/workflows/deploy.yml`、`start.sh`/`stop.sh`/`test.sh`、`backend/run.py`
- 配置/env：`backend/app/config.py`、`backend/.env.example`、`frontend/.env.production`、`frontend/vite.config.ts`、`frontend/src/utils/request.ts`、`backend/app/agents/{brainstorm,verification}/config.py`
- 运行时/DB：`backend/app/main.py`（lifespan/mount）、`backend/app/database.py`（init_db/create_all）、`backend/app/seed_data.py`（租户/角色/LLM seed）、`backend/app/routes/auth.py`（登录自举 `_ensure_apaas_user`）、`backend/app/crypto.py` + `backend/app/git/connection.py`（两把 Fernet key）
- 内网耦合实证：`backend/app/routes/{admin_mcp,builder_mcp,coding,llm_configs}.py`、`backend/app/coding/{prompts,workspace,pipeline}.py`、`backend/app/{mcp_server,apaas_backend_templates,dev_scene_workflow}.py`
