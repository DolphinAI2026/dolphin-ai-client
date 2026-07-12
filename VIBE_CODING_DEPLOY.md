# Vibe Coding 阿里云 Docker 部署指南

> Vibe Coding 模块需要在后端容器内调 host docker 起 sandbox 子容器（DinD），
> 这是有别于普通服务的特殊约束。本文给出**完整 checklist**，按顺序做即可。
> 通用部署流程仍参考 `DEPLOY_CONTAINER.md`，本文是 Vibe Coding 增量补充。

## 0. 环境前提

- 阿里云 ECS（推荐 4C8G 起步；vibe-sandbox 镜像 ~1.2GB，每个 workspace `node_modules` 1-3GB，磁盘 100GB+）
- ECS 已装 docker 24+ 和 docker compose v2
- 域名 + SSL 证书（**HTTPS 必须**，否则浏览器拒绝麦克风/语音输入）
- 外置 PostgreSQL（`DATABASE_URL` 走 `.env`）

## 1. 构建 vibe-sandbox 镜像（关键！）

后端容器自检如果发现 host docker 里没有 `vibe-sandbox:latest`，Vibe Coding 整个特性会自动 fallback 到 host 模式（只能跑单用户，且不安全）。**必须在 ECS 上预先构建**：

```bash
cd /path/to/apaas-builder-ai
docker build -t vibe-sandbox:latest docker/vibe-sandbox/
docker images | grep vibe-sandbox  # 验证
```

构建过程 ~2 分钟，1.2GB。**升级仓库后**如果 `docker/vibe-sandbox/Dockerfile` 改了，要手动 `docker build` 一次。

## 2. 准备宿主机目录

```bash
# workspaces 数据卷（持久化用户代码 + node_modules）
mkdir -p /data/apaas/workspaces

# backend.env 文件
cp deploy/docker/compose.env.example /data/apaas/backend.env
vim /data/apaas/backend.env
```

**关键**：`backend.env` 必须包含一行（让后端代码内的 `WORKSPACE_ROOT` 跟 host docker 看到的路径一致）：

```bash
APAAS_WORKSPACE_ROOT=/data/apaas/workspaces
```

> ⚠️ 这条很关键。后端 docker_runtime 起 sandbox 时会把这个路径作为 `-v <host>:/workspace` 传给 host docker。如果它跟 host 实际路径不一致，sandbox 容器看到空目录、agent 找不到用户文件。

完整 backend.env 还要含：DATABASE_URL、SECRET_KEY、各 LLM 凭证等（参考 `DEPLOY_CONTAINER.md`）。

## 3. 启动后端容器

```bash
cd /path/to/apaas-builder-ai/deploy/docker
cp compose.env.example .env
vim .env  # 设 WORKSPACES_DIR / VITE_BASE_URL 等

docker compose build  # 第一次或 Dockerfile 改后跑
docker compose up -d
docker compose logs -f
```

**自检**（跟之前不同）：

```bash
# 1) 后端容器里能不能调 host docker
docker exec apaas-builder docker version
# 期望：Client + Server 都能列出（Server 是 host docker daemon）

# 2) 后端能不能看到 vibe-sandbox 镜像
docker exec apaas-builder docker image inspect vibe-sandbox:latest --format '{{.Id}}'
# 期望：返回镜像 ID，不报错

# 3) 健康检查
curl http://127.0.0.1:8003/api/health
```

## 4. nginx HTTPS 反代

参考 `deploy/docker/nginx.conf.example`。**关键路径**：

```nginx
location /ai-builder/ {
    proxy_pass http://127.0.0.1:8003/ai-builder/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;  # SSE 流式不要被切
    proxy_buffering off;       # SSE 必须关
}
```

证书路径配好后 `nginx -s reload`，访问 `https://your-domain/ai-builder/` 应能打开。

## 5. ECS 安全组

- 入方向：80/443 (nginx)，22 (ssh) 放行
- **不需要**开放 6100-6999 端口段。Vibe Coding 的 dev server 预览走的是后端容器内 iframe 嵌入，host 端口由 docker 自动分配（55xxx），用户从 nginx 反代/iframe URL 访问，不直接访问 ECS 公网端口。

## 6. 验证 Vibe Coding 能用

1. 访问 `https://your-domain/ai-builder/vibe-coding`
2. 点 "+ 新建工作区" → 自动创建空 workspace
3. 在对话框说 "做一个 todo app"
4. 后端会调 host docker 起一个 `vibe-{workspace_id}` 容器，agent 在里面跑 npm create vite + 写代码
5. 说"启动 dev server" → agent 起 vite，预览面板自动显示链接

**故障排查**：

| 症状 | 原因 | 排查 |
|---|---|---|
| 对话能聊但 agent 不调 tool | 后端 docker.sock 没挂上 / docker CLI 没装 | `docker exec apaas-builder docker version` 报错 |
| sandbox 容器起来了但里面是空目录 | workspace 路径不一致 | `docker inspect vibe-{ws} --format '{{json .Mounts}}'`，看 Source 是不是 host 上能找到的路径 |
| dev server 起来但浏览器访问空白 | 服务监听 127.0.0.1 不是 0.0.0.0 | 在对话里让 agent 改成 0.0.0.0（prompts.py 里也明确写了，这是 LLM 偶尔忘） |
| 预览页前端报"连接中…"接不上后端 | 前端写死 `localhost:6300` 了 | 让 AI 改 vite proxy 用相对路径（prompts.py 已加约束，新会话 OK） |
| 语音输入按钮点了没反应 | HTTP 站点 / 麦克风权限拒绝 | F12 console 看 `[VoiceInputButton]` 报什么；HTTPS 是必须的 |
| 语音识别 404 错误 | LLM 直连原厂不支持 Whisper 协议 | 切到 OneAPI / FastGPT 等 OpenAI 兼容网关，或单独配 STT 用模型 |

## 7. 资源 / 清理建议

- vibe-sandbox 子容器**一个 workspace 一个**，30 分钟无活跃自动 stop（保留容器以复用 node_modules）
- 删 workspace 时后端会调 `docker rm -f vibe-{id}`
- 残留容器手动清：`docker ps -a --filter label=vibe-coding=1 -q | xargs docker rm -f`
- workspace 数据清：`rm -rf /data/apaas/workspaces/_online_coding/oc_xxx`
- 监控：磁盘占用是大头，建议加 cron 定期 `docker system prune -af --filter "until=24h"` 清未使用镜像层

## 8. 升级流程

```bash
git pull
cd deploy/docker
docker compose build       # 重建后端镜像
docker compose up -d       # 滚动重启

# 如果 vibe-sandbox/Dockerfile 改了
docker build -t vibe-sandbox:latest ../../docker/vibe-sandbox/
# 现有 sandbox 容器需手动重启才用新镜像（或在对话里说"重启沙箱"，agent 走 docker rm + 下次自动重建）
```

---

**文件清单**（这次改动）：
- `deploy/docker/Dockerfile` — 装 docker CLI 二进制
- `deploy/docker/docker-compose.yml` — 挂 docker.sock + workspace 路径双向一致 + APAAS_WORKSPACE_ROOT
- `deploy/docker/supervisord.conf` — 后端 uvicorn 进程由 supervisor 托管
- `deploy/docker/compose.env.example` — 注释提示 Vibe Coding 前置项
