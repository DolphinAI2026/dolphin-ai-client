# 单节点容器化部署清单

> 配套主机部署版：[DEPLOY.md](DEPLOY.md)。本文档描述 Docker 单容器部署：前端构建产物、FastAPI 后端、工作区命令执行能力在同一镜像内交付，数据库和 nginx 仍由外部提供。

配套示例文件目录：[deploy/docker/](deploy/docker/)

## 适用场景

- 单台云主机或内网服务器
- 外置 PostgreSQL
- TLS、域名和证书由宿主机 nginx 处理
- 需要支持 AI Builder、应用资产、自开发资产、代码工作区和工作区命令执行

非目标：多节点、滚动升级、容器内终止 TLS、容器内自带数据库。

## 架构

```text
┌────────────────────────────────────────────────┐
│ 宿主机                                         │
│                                                │
│  ┌──────────────────────────────────────────┐  │
│  │ 容器 apaas-builder (--network=host)       │  │
│  │                                          │  │
│  │  supervisord                             │  │
│  │  └─ uvicorn app.main:app :8003           │  │
│  │                                          │  │
│  │  镜像内置：                              │  │
│  │  - frontend/dist                         │  │
│  │  - admin-spa/dist                        │  │
│  │  - Python 后端依赖                       │  │
│  │  - Node 20 / JDK 8 / JDK 17 / Maven      │  │
│  │  - docker CLI                            │  │
│  │                                          │  │
│  │  Volumes:                                │  │
│  │  - /data/apaas/workspaces                │  │
│  │  - /data/apaas/backend.env               │  │
│  │  - /var/run/docker.sock                  │  │
│  └──────────────────────────────────────────┘  │
│                                                │
│  外置 PostgreSQL                               │
│  宿主 nginx: /ai-builder/ -> 127.0.0.1:8003    │
└────────────────────────────────────────────────┘
```

使用 `--network=host` 的原因：工作区命令、预览和 sandbox 容器需要与宿主机端口、路径保持一致；host 网络能避免动态端口批量映射和路径翻译问题。

## 前置条件

| 项 | 要求 |
|---|---|
| Docker | 24.0+，建议 26+，安装 docker compose 插件 |
| PostgreSQL | PostgreSQL 14+，提前建好库和账号 |
| 磁盘 | 6GB+ 镜像与工作区空间，真实项目建议 50GB+ |
| 内存 | 2GB+，多人自开发建议 4GB+ |
| nginx | 宿主机已配置 TLS 和反向代理 |
| sandbox 镜像 | 若启用自开发沙箱，预先构建 `vibe-sandbox:latest` |

## 一次性准备

### 1. 建挂载目录

```bash
sudo mkdir -p /data/apaas/workspaces
sudo chmod 755 /data/apaas /data/apaas/workspaces
```

### 2. 准备后端环境文件

```bash
cp deploy/docker/compose.env.example deploy/docker/.env
cp backend/.env.example /data/apaas/backend.env
chmod 600 /data/apaas/backend.env
vi /data/apaas/backend.env
```

至少确认：

```dotenv
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@127.0.0.1:5432/apaas_builder
AUTH_PROVIDER=control_plane
DOLPHIN_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn
DOLPHIN_CODE_CONTROL_PLANE_URL=https://<control-plane-host>
JWT_SECRET_KEY=<生产随机长字符串>
ENCRYPTION_KEY=<生产随机长字符串>
LLM_API_KEY=<按实际模型供应商填写>

HOST=0.0.0.0
PORT=8003
APAAS_WORKSPACE_ROOT=/data/apaas/workspaces
APAAS_NPM_CACHE_DIR=/data/apaas/workspaces/.npm-cache
APAAS_BACKEND_JDK_VERSION=17
```

`APAAS_WORKSPACE_ROOT` 必须是宿主机和容器内都能看到的同一路径。后端通过宿主 Docker daemon 启动 sandbox 容器时，会把这个路径直接传给 `docker run -v`。

### 3. PostgreSQL 建库

```sql
CREATE USER apaas WITH PASSWORD '<pass>';
CREATE DATABASE apaas_builder OWNER apaas;
```

后端启动时会自动建表。

Control Plane 部署还需设置：

```dotenv
CONTROL_PLANE_AUTH_FULL_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn
```

该配置属于 Control Plane 运行环境，不需要修改 Control Plane 源码。

### 4. 可选：构建自开发 sandbox 镜像

```bash
docker build -t vibe-sandbox:latest docker/vibe-sandbox/
docker image inspect vibe-sandbox:latest --format '{{.Id}}'
```

启用代码工作区的命令执行和项目预览时建议提前完成。仓库里的 `docker/vibe-sandbox/Dockerfile` 改动后也需要重新构建。

## 构建镜像

```bash
docker build --platform linux/amd64 \
  -f deploy/docker/Dockerfile \
  --build-arg VITE_BASE_URL=/ai-builder/ \
  -t apaas-builder:latest .
```

构建阶段：

1. `frontend-builder`：构建主前端 `frontend/dist/`。
2. `admin-builder`：构建平台管理前端 `admin-spa/dist/`。
3. `jdk8` / `jdk17` / `maven-bin`：准备后端打包运行所需 JDK 与 Maven。
4. `runtime`：安装 Python 依赖、Node 20、docker CLI、后端代码和前端产物。

Apple Silicon 本机给线上 amd64 机器构建时必须显式传 `--platform linux/amd64`。

## 启动容器

```bash
cd deploy/docker
docker compose up -d
docker compose logs -f
```

等价 `docker run`：

```bash
docker run -d --name apaas-builder \
  --network=host \
  --restart unless-stopped \
  --env-file /data/apaas/backend.env \
  -e PORT=8003 \
  -e APAAS_WORKSPACE_ROOT=/data/apaas/workspaces \
  -v /data/apaas/workspaces:/data/apaas/workspaces \
  -v /data/apaas/backend.env:/app/backend/.env:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  apaas-builder:latest
```

## nginx 反代

参考 [deploy/docker/nginx.conf.example](deploy/docker/nginx.conf.example)。核心要求：

- `/ai-builder/` 转发到 `127.0.0.1:8003`
- SSE 关闭 proxy buffering
- 长任务请求设置足够长的 read/send timeout
- 静态资源可由后端托管，也可按示例交给 nginx serve

最小可用片段：

```nginx
location /ai-builder/ {
    proxy_pass http://127.0.0.1:8003/;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /ai-builder;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
}

location = /ai-builder {
    return 301 /ai-builder/;
}
```

## 验证

```bash
# 后端健康
curl -fsS http://127.0.0.1:8003/api/health

# 路由探测，避免旧进程占端口误判
curl -fsS http://127.0.0.1:8003/openapi.json | grep -q '/api/ai-chat'

# 容器是否能访问宿主 Docker
docker exec apaas-builder docker version

# sandbox 镜像是否可见
docker exec apaas-builder docker image inspect vibe-sandbox:latest --format '{{.Id}}'
```

浏览器验证：

1. 打开 `https://<domain>/ai-builder/`。
2. 登录后进入 AI Builder。
3. 创建或打开一个自开发资产。
4. 进入代码工作区，确认文件树、源码、diff、命令执行和构建日志正常。

## 升级

```bash
git pull
cd deploy/docker
docker compose build
docker compose up -d
docker compose logs -f
```

如果 `docker/vibe-sandbox/Dockerfile` 有变化：

```bash
docker build -t vibe-sandbox:latest ../../docker/vibe-sandbox/
```

已有 sandbox 容器需要重启后才会使用新镜像。

## 常见问题

| 症状 | 常见原因 | 排查 |
|---|---|---|
| 健康检查成功但页面打不开 | nginx base path 或 `VITE_BASE_URL` 不一致 | 检查构建参数和 nginx location |
| 代码工作区里命令执行失败 | 容器访问不到宿主 Docker 或 workspace 路径不一致 | `docker exec apaas-builder docker version`，检查 `APAAS_WORKSPACE_ROOT` |
| sandbox 里看不到文件 | host 路径和容器路径不一致 | 检查 compose 的 `WORKSPACES_DIR` 和后端 env |
| 构建 Java 后端失败 | JDK 版本不匹配 | 设置 `APAAS_BACKEND_JDK_VERSION=8/17/auto` |
| SSE 中途断开 | nginx buffering 或 timeout 不合适 | 关闭 proxy buffering，增加 timeout |
