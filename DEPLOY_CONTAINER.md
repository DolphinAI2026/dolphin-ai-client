# 单节点容器化部署清单

> 配套主机部署版：[DEPLOY.md](DEPLOY.md)。本文档专门描述**单节点容器化**部署（Docker，单容器，应用自身容器化）。如果你要做的是「SSH 到云主机上升级裸跑的 uvicorn」，请看 DEPLOY.md。

配套示例文件目录：[deploy/docker/](deploy/docker/)

---

## 适用场景

- 单台云主机或内网服务器
- 外置 MySQL（线上既有实例或同机另起的 mysql 容器均可）
- TLS 终止 / 域名 / 证书继续由**宿主机 nginx** 处理（不做容器 TLS）
- 目标是让后端 + code-server + 工作区 dev-server 作为一个整体跑在一个容器里，宿主 nginx 做前置反代

**非目标**：多节点、K8s、蓝绿部署、滚动升级、容器里终止 TLS。

---

## 架构

```
┌────────────────────────────────────────────────┐
│  宿主机（单节点）                              │
│                                                │
│  ┌──────────────────────────────────────────┐ │
│  │ 容器 apaas-builder  (--network=host)     │ │
│  │                                          │ │
│  │  supervisord（PID 1）                    │ │
│  │  ├─ uvicorn app.main:app :8003 --workers 1
│  │  ├─ code-server :8080 (auth=none)        │ │
│  │  └─ 工作区 dev-server :8081+ (后端 fork) │ │
│  │                                          │ │
│  │  Volumes:                                │ │
│  │   /data/apaas/workspaces    ← workspaces │ │
│  │   /data/apaas/npm-cache     ← npm 缓存   │ │
│  │   /data/apaas/frontend-dist ← 前端静态   │ │
│  │   /data/apaas/backend.env   ← .env (ro)  │ │
│  │   /data/apaas/logs          ← 日志       │ │
│  └──────────────────────────────────────────┘ │
│                                                │
│  外置 MySQL（127.0.0.1:3306 或独立实例）       │
│                                                │
│  宿主 nginx（TLS + 域名）                      │
│   /ai-builder/assets/ → /data/apaas/frontend-dist/assets/ (静态)
│   /ai-builder/ide/    → 127.0.0.1:8080 (code-srv)
│   /ai-builder/        → 127.0.0.1:8003 (API/SSE)
│   (工作区 dev proxy 由 code-server 内置 /proxy/ 处理)
└────────────────────────────────────────────────┘
```

**为什么用 `--network=host`**：后端会为每个工作区启动一个 `npm run serve` 进程，端口从 `8081` 起动态递增（见 [backend/app/coding/workspace.py:46](backend/app/coding/workspace.py:46)）。用 host 网络后，宿主 nginx 可以直接用 `127.0.0.1:{port}` 转发到对应的工作区 dev-server，不需要在 compose 里 expose 一批端口。同时保持行为与主机部署一致。

---

## 前置条件

| 项 | 要求 |
|---|---|
| Docker | ≥ 24.0（建议 26+），装好 `docker compose` 插件 |
| MySQL | 可达的 MySQL 5.7 / 8.x，提前建好库 `apaas_builder` 和账号 |
| 磁盘 | ≥ 6GB（镜像约 1.5GB：Python + Node + code-server；Chromium 默认不装） |
| 内存 | ≥ 2GB 建议 |
| 宿主 nginx | 已就绪，能签证书、绑定域名 |

---

## 一次性准备

### 1. 建挂载目录

```bash
sudo mkdir -p /data/apaas/{workspaces,npm-cache,logs,frontend-dist}
sudo chown -R 1000:1000 /data/apaas   # 若 Dockerfile 里用非 root 用户
```

> `frontend-dist` 用来接收容器启动时从镜像同步出来的前端构建产物，宿主 nginx 直接 serve（后端 `main.py` 只托管 `/api/static`，不托管 SPA dist）。

### 2. 准备 .env

```bash
cp backend/.env.example /data/apaas/backend.env
chmod 600 /data/apaas/backend.env
vi /data/apaas/backend.env
```

至少填好：

```dotenv
# 指向外置 MySQL（host network 下 127.0.0.1 即宿主本机）
DATABASE_URL=mysql+aiomysql://<user>:<pass>@127.0.0.1:3306/apaas_builder

LLM_API_KEY=<填写>
JWT_SECRET_KEY=<随机长字符串，生产环境必改>

# 后端监听（与主机部署对齐用 8003）
HOST=0.0.0.0
PORT=8003

# 工作区根目录（容器内绝对路径，和 volume 映射点一致）
APAAS_WORKSPACE_ROOT=/root/apaas-builder/workspaces
APAAS_NPM_CACHE_DIR=/root/.apaas-builder/npm-cache

# Web IDE 外部访问 URL（走宿主 nginx）
CODE_SERVER_BASE_URL=https://<domain>/ai-builder/ide/
```

> `APAAS_WORKSPACE_ROOT` 的值必须是**容器内路径**，不是宿主路径。容器内后端把该路径传给 code-server 的 `folder=` 参数，code-server 和后端在同一容器内所以看到的是同一个路径。

### 3. MySQL 建库

```sql
CREATE DATABASE apaas_builder DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'apaas'@'%' IDENTIFIED BY '<pass>';
GRANT ALL ON apaas_builder.* TO 'apaas'@'%';
FLUSH PRIVILEGES;
```

后端启动时 `init_db()` 会自动建表（见 [backend/app/database.py:31](backend/app/database.py:31)）。

---

## 构建镜像

```bash
cd /path/to/apaas-builder-ai
docker build --platform linux/amd64 \
  -f deploy/docker/Dockerfile \
  --build-arg VITE_BASE_URL=/ai-builder/ \
  -t apaas-builder:latest .
```

镜像构建分三阶段：

1. **stage 1 (`node:20-bookworm-slim`)**：装 `frontend/` 依赖，运行 `VITE_BASE_URL=/ai-builder/ vite build` 产出 `frontend/dist/`
2. **stage 2 (`node:20-bookworm-slim`)**：从 `extensions/ruijing-ai` 构建睿鲸 VS Code 扩展 VSIX
3. **stage 3 (`python:3.12-slim-bookworm`)**：装 `requirements.txt`（含 `playwright` Python 包）、code-server、Node 20（给工作区用），安装睿鲸扩展，执行 `scripts/patch_all.js --code-server-path /opt/code-server`，再 copy stage 1 的 `frontend/dist/`。**默认不下载 Chromium**——前端目前未调用 `/browser/*` 端点，装上纯浪费镜像空间。需要时参考下方「启用浏览器预览」章节

**什么改动会让缓存失效**：
- 改 `frontend/package.json` → stage 1 依赖层失效
- 改 `extensions/ruijing-ai/package.json` → stage 2 扩展依赖层失效
- 改 `extensions/ruijing-ai/src/*` 或 `scripts/patch_*.js` → code-server 扩展/patch 层失效
- 改 `backend/requirements.txt` → stage 3 依赖层失效
- 改业务代码 → 只有 COPY 层失效，依赖层复用

> Apple Silicon 本机默认容易构出 `linux/arm64` 镜像；线上 Linux 节点使用 amd64 时，构建和推送生产镜像必须显式带 `--platform linux/amd64`。

### code-server / 睿鲸 AI 扩展

镜像内置安装 `apaas-builder.ruijing-ai`，并对 code-server 的 `workbench.js` 做 Chat fallback patch：把原生 Chat 对 `GitHub.copilot-chat` 的检查改为 `apaas-builder.ruijing-ai`。否则即使手动安装扩展，Chat 面板也可能仍显示 VS Code 默认 Agent 引导界面。

运行后可验证：

```bash
docker exec apaas-builder code-server --list-extensions --show-versions | grep ruijing

docker exec apaas-builder sh -lc \
  'WB=/opt/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js; grep -q GitHub.copilot-chat "$WB" && echo "patch missing" || echo "patch ok"'
```

---

## 启动容器

### 方式 A：docker compose（推荐）

```bash
cd deploy/docker
docker compose up -d
docker compose logs -f
```

### 方式 B：docker run 等价命令

```bash
docker run -d --name apaas-builder \
  --network=host \
  --restart unless-stopped \
  -v /data/apaas/workspaces:/root/apaas-builder/workspaces \
  -v /data/apaas/npm-cache:/root/.apaas-builder/npm-cache \
  -v /data/apaas/frontend-dist:/srv/frontend/dist \
  -v /data/apaas/backend.env:/app/backend/.env:ro \
  -v /data/apaas/logs:/var/log/apaas \
  apaas-builder:latest
```

---

## 验证（对齐 [DEPLOY.md:60](DEPLOY.md:60)）

```bash
# 1. 后端健康检查
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8003/api/health
# 期望：200

# 2. 真实路由探测（防历史 bug：老进程占端口骗过健康检查）
curl -s http://127.0.0.1:8003/openapi.json | grep -c '/harness/coding/pipeline'
# 期望：≥1

# 3. code-server 自身健康
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/healthz
# 期望：200

# 4. 端到端
# 浏览器打开 https://<domain>/ai-builder/
# 登录 → 创建工作区 → 终端里 npm run serve
# 终端应打印 https://<domain>/ai-builder/ide/proxy/{port}/，点开能看到页面
```

---

## 升级流程

### 代码升级

```bash
git pull
cd deploy/docker
docker compose build
docker compose up -d          # 自动滚动替换
docker compose logs -f        # 观察 uvicorn / code-server 起来
```

`.env` 和数据库通过 volume / 外置 MySQL，**不会被覆盖**。

### 只改 .env

```bash
vi /data/apaas/backend.env
docker compose restart
```

### 数据库 schema 变化

后端启动时会自动 `init_db()`（[backend/app/database.py:31](backend/app/database.py:31)），新表/新列自动建。如果有破坏性迁移（列改类型、删表），需要先人工改 MySQL，再升级容器。

---

## 宿主 nginx 配置

完整片段见 [deploy/docker/nginx.conf.example](deploy/docker/nginx.conf.example)。三条核心 location：

```nginx
# 1) 前端静态资源：nginx 直接 serve，不回源
location ^~ /ai-builder/assets/ {
    alias /data/apaas/frontend-dist/assets/;
    expires 7d;
    add_header Cache-Control "public, immutable";
}

# 2) code-server（Web IDE + WebSocket）— 优先级高于 /ai-builder/
location ^~ /ai-builder/ide/ {
    proxy_pass http://127.0.0.1:8080/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;   # http{} 段里用 map 定义
    proxy_set_header Host $host;
    proxy_read_timeout 86400s;
}

# 3) 后端 API + SSE
location /ai-builder/ {
    proxy_pass http://127.0.0.1:8003/;
    proxy_http_version 1.1;
    proxy_buffering off;             # SSE 流式响应必须关
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
}
```

**为什么前端静态单独拉出来**：后端 `main.py` 只 mount 了 `/api/static`（见 [backend/app/main.py:122](backend/app/main.py:122)），没有托管 SPA dist。容器启动时 entrypoint 把 `/app/frontend/dist` 同步到共享卷 `/data/apaas/frontend-dist`，nginx 直接 serve 性能最好。

**工作区 `npm run serve` 的动态端口**：走 code-server 自带的 `/proxy/{port}/` 路由，**不需要宿主 nginx 额外配置**——code-server 会代理到容器内 `127.0.0.1:{port}`（host 网络下即宿主的 127.0.0.1）。

改完 nginx：`nginx -t && nginx -s reload`。

---

## 注意事项

| 事项 | 说明 |
|------|------|
| `--workers 1` | 必须单 worker。[DEPLOY.md:162](DEPLOY.md:162) 有历史事故：`platform_proxy._proxy_state` 是模块级 dict，多 worker 下 iframe 后续请求打到空状态 worker，表现为"智能体不存在" |
| 数据库外置 | 容器无状态，数据库通过 `DATABASE_URL` 连外部 MySQL。host 网络下用 `127.0.0.1:3306` |
| 前端 dist 共享卷 | 后端不托管 SPA，entrypoint 启动时同步到 `/srv/frontend/dist`（挂到宿主 `/data/apaas/frontend-dist`）。升级镜像后会 `rsync --delete` 清掉旧文件，无需宿主手动清理 |
| workspace volume 必挂 | 不挂的话容器重建会丢所有工作区 |
| workspace 路径对齐 | `APAAS_WORKSPACE_ROOT` 必须与容器内挂载点一致（默认 `/root/apaas-builder/workspaces`）。code-server 和后端在同一容器，所以天然对齐 |
| `.env` 挂载 ro | 防止容器内误写；敏感信息只在宿主 |
| Chromium 默认不装 | [backend/app/coding/browser_service.py](backend/app/coding/browser_service.py) 是 headless Chromium 远程操作服务，但前端未调用 `/browser/*` 端点，镜像默认跳过 Chromium 下载。Python 包 `playwright` 仍装（`import` 需要），惰性启动逻辑保证未用就不启浏览器。需要启用见下节 |
| Node 20 必需 | 工作区 `npm run serve` 在容器里跑，镜像要预装 Node 20。工作区模板 `package.json` 需要 Node ≥ 16 |
| host network 的代价 | 容器端口和宿主端口共用命名空间。启动前确认宿主没别的进程占 8003 / 8080 |
| host network 限 Linux | 只在 Linux 上生效，macOS / Windows 的 Docker Desktop 不是真 host 模式。生产都是 Linux，不是问题 |
| pkill 残留 | [backend/app/main.py:16](backend/app/main.py:16) 启动时 `pkill -f vibe-serve.js`，容器第一次启动没残留，supervisor 管进程后 [DEPLOY.md:190](DEPLOY.md:190) 的历史坑（老进程占端口骗过健康检查）自然消除 |
| 工作区模板改动 | 改 `backend/templates/` 后已存在的工作区不会自动更新，需重建工作区 |
| 镜像大小 | 约 2-3GB，主要是 Chromium（~500MB）+ Node（~150MB）+ Python 依赖。构建慢时把 `playwright install` 单独提前 COPY |
| npm-cache volume | 强烈建议挂载，否则每次新建工作区都要重新下载依赖 |

---

## 启用浏览器预览（Playwright / Chromium）

> 默认**未启用**。仅当要调用 `/api/coding/workspace/{ws_id}/browser/*` 相关端点（前端目前未使用）时才需要。

**临时启用**（进已跑的容器装一次，容器重建后失效）：

```bash
docker exec apaas-builder playwright install --with-deps chromium
```

**永久启用**（改 Dockerfile 重建镜像）：

```dockerfile
# 取消 deploy/docker/Dockerfile 里这一行的注释
RUN playwright install --with-deps chromium
```

重建后镜像约大 500MB，并会拉入 `libnss3`、`libatk1.0-0`、`libxcomposite1`、`fonts-noto-cjk` 等系统库。

**自检**：

```bash
docker exec apaas-builder python -c \
  "import asyncio; from playwright.async_api import async_playwright; \
   async def m():\
     async with async_playwright() as p:\
       b = await p.chromium.launch(); await b.close(); print('ok')\
   ; asyncio.run(m())"
# 期望输出：ok
```

---

## 与主机裸跑并存部署（线上过渡方案）

> 适用场景：线上主机裸跑版（`/ai-builder/`, 8003/8080）继续对外服务，**同一台机器**上再起一套容器版走不同 URL 前缀 `/ai-builder-docker/`，用于验证。两者共享同一台 MySQL，但使用不同库。

### 端口与路径对照

| 组件 | 主机裸跑（保留）| 容器版（新增）|
|---|---|---|
| 后端 uvicorn | `127.0.0.1:8003` | `127.0.0.1:8103` |
| code-server | `127.0.0.1:8080` | `127.0.0.1:8090` |
| 工作区 dev-server 起点 | 8080 起（已占 8081）| 8080 起但自动跳过主机占用端口（[workspace.py:1640](backend/app/coding/workspace.py:1640) 有端口占用自动 +1 逻辑）|
| URL 前缀 | `/ai-builder/` | `/ai-builder-docker/` |
| MySQL 库 | `apaas_builder` | `apaas_builder_docker`（同一 MySQL 实例，不同库）|
| 工作区数据目录 | `/root/apaas-builder/workspaces/` | `/data/apaas-docker/workspaces/`（完全独立，不 rsync）|
| 前端 dist 路径 | `/root/apaas-builder/frontend/dist/` | `/data/apaas-docker/frontend-dist/`（容器同步）|

### 操作步骤

**1. 服务器上 MySQL 建新库**（用 apaas 账号）：

```bash
mysql -u apaas -p apaas_builder -e "CREATE DATABASE apaas_builder_docker DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

**2. 建独立数据目录**：

```bash
sudo mkdir -p /data/apaas-docker/{workspaces,npm-cache,logs,frontend-dist}
```

**3. 写容器版 `.env`** （`/data/apaas-docker/backend.env`）：

拷主机 `/root/apaas-builder/backend/.env` 的密钥项（`LLM_API_KEY`、`JWT_SECRET_KEY`、`APAAS_*`），然后替换：

```dotenv
DATABASE_URL=mysql+aiomysql://apaas:apaas2024@127.0.0.1:3306/apaas_builder_docker?charset=utf8mb4
PORT=8103
HOST=0.0.0.0
APAAS_WORKSPACE_ROOT=/root/apaas-builder/workspaces
APAAS_NPM_CACHE_DIR=/root/.apaas-builder/npm-cache
CODE_SERVER_BASE_URL=https://agent.dfy.definesys.cn/ai-builder-docker/ide/
```

**4. 用 compose.env 文件切到并存模式**：

```bash
cd /root/apaas-builder/deploy/docker           # 假设代码已 rsync 上来
cp compose.env.example .env                    # 默认就是场景 B（并存）
```

**5. 构建镜像 + 起容器**（podman-compose）：

```bash
podman-compose --env-file .env build
podman-compose --env-file .env up -d
podman-compose logs -f
```

**6. 主机 nginx 加 `/ai-builder-docker/` 段**：

把 [deploy/docker/nginx.conf.example](deploy/docker/nginx.conf.example) 里 `server { ... }` 块内的 `/ai-builder-docker/*` 三段 location 复制到 `/etc/nginx/apaas-builder.conf`（和现有 `/ai-builder/*` 规则并列），然后：

```bash
nginx -t && nginx -s reload
```

**7. 验证**：

```bash
# 容器内 8103 能响应
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8103/api/health         # 200
curl -s http://127.0.0.1:8103/openapi.json | grep -c /harness/coding/pipeline      # ≥1

# 主机仍在正常服务
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8003/api/health         # 200（未动）

# 公网两套路径都通
curl -s -o /dev/null -w "%{http_code}\n" https://agent.dfy.definesys.cn/ai-builder/
curl -s -o /dev/null -w "%{http_code}\n" https://agent.dfy.definesys.cn/ai-builder-docker/
```

### 并存时的注意点

| 事项 | 说明 |
|---|---|
| MySQL 库必须隔离 | 两套用同一库会互相写坏。容器版**必须**用独立库 `apaas_builder_docker`，init_db 会自动建表 |
| 工作区数据不共享 | 容器有自己的 `/data/apaas-docker/workspaces`，和主机的 `/root/apaas-builder/workspaces` **完全分开**。在容器版创建的工作区，主机看不到；反之亦然 |
| `pkill vibe-serve.js` 会波及主机 | [backend/app/main.py:16](backend/app/main.py:16) 容器启动时 `pkill -f vibe-serve.js` 会在 host 网络下**杀掉主机上的工作区 dev server**——切换时会让主机上正在预览的用户断开。建议在低峰期起容器，或暂时注释掉这行再启容器 |
| 端口自动跳过 | 容器里工作区启动时 `socket.connect_ex` 会检测到主机的 8080/8081 被占，自动 +1 到空闲端口。但主机如果继续开新工作区会抢占 8082+，容器启动时会再跳——正常 |
| 镜像构建时间 | 5-10 分钟（主要是 `npm ci` + code-server 下载）。服务器在国内，如慢可设 npm registry 镜像 |
| 磁盘 | 镜像约 1.5GB + workspaces 独立 5GB+，剩余磁盘要够 |

### 并存方案的最终形态

验证稳定后，把主机裸跑下线可分两步：

```bash
# 1. 停主机 systemd 服务
systemctl stop apaas-code-server
pkill -9 -f 'uvicorn.*app.main:app.*8003'
systemctl disable apaas-code-server

# 2. 容器从并存模式切回主机独占模式
#    （改用主机独占端口 8003/8080 和主 URL /ai-builder/，重建镜像）
# 参考 deploy/docker/compose.env.example 里「场景 A」
```

---

## 从主机部署迁移到容器部署

一次性切换步骤（假设已按上文准备好镜像和挂载目录）：

```bash
# 0. 备份
ssh root@<host> "tar -czf /root/apaas-builder-backup-$(date +%F).tar.gz /root/apaas-builder/workspaces"
mysqldump -u apaas -p apaas_builder > apaas_builder-$(date +%F).sql

# 1. 停主机上的 uvicorn
ssh root@<host> "pkill -9 -f 'uvicorn.*:app.*8003'"

# 2. 搬工作区数据
ssh root@<host> "rsync -a /root/apaas-builder/workspaces/ /data/apaas/workspaces/"

# 3. 改宿主 nginx（如果之前 upstream 写的是进程，现在改成 127.0.0.1:8003 依旧能对上——基本无需改动）
nginx -t && nginx -s reload

# 4. 起容器
cd deploy/docker && docker compose up -d

# 5. 验证
curl http://127.0.0.1:8003/api/health          # 200
curl -s http://127.0.0.1:8003/openapi.json | grep -c /harness/coding/pipeline
```

切换完成后旧的 `/root/apaas-builder/.venv` 和裸跑的 uvicorn 残留可以保留一段时间观察，确认稳定后再删。

---

## 排查

```bash
# 实时日志
docker compose logs -f apaas-builder

# 进容器
docker exec -it apaas-builder bash

# 容器内 - 看进程
supervisorctl status

# 容器内 - 看后端日志
tail -f /var/log/apaas/backend.log

# 容器内 - 手动重启某个 program
supervisorctl restart uvicorn
supervisorctl restart code-server

# MySQL 连通性
docker exec apaas-builder python -c \
  "import asyncio, aiomysql, os, urllib.parse as u; \
   url=os.environ['DATABASE_URL']; print('DB URL loaded:', url[:40]+'...')"
```

常见失败：

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `/api/health` 200 但 `/openapi.json` 不含 `/harness/coding/pipeline` | 镜像构建时未 COPY 到最新后端代码 | 重新 `docker compose build --no-cache` |
| 创建工作区卡住 | npm-cache volume 没挂，首次下载慢；或容器内 Node 路径不对 | 看 `backend.log`，查 `[backend/app/coding/runtime_env.py](backend/app/coding/runtime_env.py)` 的探测日志 |
| IDE 打开空白 | `CODE_SERVER_BASE_URL` 没配，或宿主 nginx `/ai-builder/ide/` 转发缺 WebSocket upgrade | 检查 `.env` 和 nginx 片段 |
| 工作区预览截图 500 / `Executable doesn't exist at ...` | Chromium 未装（默认镜像不带）| 见「启用浏览器预览」章节 |
| 重启后工作区消失 | `/data/apaas/workspaces` 没挂载到 `/root/apaas-builder/workspaces` | 检查 compose volumes 映射 |

---

## 线上目录结构（容器内）

```
/app/                                   ← 镜像内代码（只读）
├── backend/
│   ├── app/
│   ├── requirements.txt
│   └── .env                           ← 宿主 /data/apaas/backend.env 挂载进来 (ro)
└── frontend/dist/                      ← 构建期产物

/root/apaas-builder/
└── workspaces/                         ← 宿主 /data/apaas/workspaces 挂载 (rw)

/root/.apaas-builder/
└── npm-cache/                          ← 宿主 /data/apaas/npm-cache 挂载 (rw)

/srv/frontend/dist/                     ← 宿主 /data/apaas/frontend-dist 挂载 (rw)
                                          entrypoint 启动时 rsync 产物进来

/var/log/apaas/                         ← 宿主 /data/apaas/logs 挂载 (rw)
├── backend.log
├── supervisord.log
├── uvicorn.stdout.log / .stderr.log
└── code-server.stdout.log / .stderr.log
```
