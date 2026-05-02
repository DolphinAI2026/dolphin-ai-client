# ============================================================
# apaas-builder 单节点容器镜像
# 详见 DEPLOY_CONTAINER.md
# ============================================================

# ------------------------------------------------------------
# stage 1: 构建前端（Vite）
# ------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend-builder

# URL 前缀：
#   主机独占部署 → /ai-builder/
#   与主机裸跑并存 → /ai-builder-docker/
# 用法：docker build --build-arg VITE_BASE_URL=/ai-builder-docker/ ...
ARG VITE_BASE_URL=/ai-builder/

WORKDIR /build/frontend

# 先拷 package 清单，利用 Docker 层缓存
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline --no-audit --progress=false

# 再拷源码构建
COPY frontend/ ./
ENV VITE_BASE_URL=${VITE_BASE_URL}
# 与 DEPLOY.md 第 37 行的线上构建命令一致：直接 vite build，
# 跳过 vue-tsc 类型检查（项目代码有遗留 TS 错误，主机部署流程也跳过）
RUN node_modules/.bin/vite build


# ------------------------------------------------------------
# stage 2: 构建 code-server 睿鲸扩展
# ------------------------------------------------------------
FROM node:20-bookworm-slim AS ruijing-extension-builder

WORKDIR /build/extensions/ruijing-ai

COPY extensions/ruijing-ai/package.json extensions/ruijing-ai/package-lock.json ./
RUN npm ci --prefer-offline --no-audit --progress=false

COPY extensions/ruijing-ai/ ./
RUN npm run build \
    && npx @vscode/vsce package --no-dependencies


# ------------------------------------------------------------
# stage 3: 运行时镜像
#   - Python 3.11 + 后端依赖
#   - Node 20（工作区 npm run serve 用）
#   - Playwright Chromium
#   - code-server
#   - supervisord 作为 PID 1
# ------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
# 注：后端代码用到了 PEP 701（f-string 可含反斜杠），Python 3.12+ 必需

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_MAJOR=20 \
    CODE_SERVER_VERSION=4.112.0

# --- 系统依赖 + Node 20 ------------------------------------
# 注：未安装 Chromium 运行时依赖。playwright Python 包会装（import 需要），
# 但不下载浏览器二进制。如果将来真的要启用 /api/coding/.../browser 端点，
# 在运行中的容器里执行：
#   docker exec apaas-builder playwright install --with-deps chromium
# 或取消下方 RUN playwright install 那行的注释并重建镜像。
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg git procps rsync \
        supervisor \
        build-essential \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- docker CLI（仅 client，不带 daemon）---------------------
# 后端要起 vibe-coding 沙箱容器（vibe-sandbox:latest），通过挂载
# host /var/run/docker.sock 复用 host docker daemon。从官方静态二进制
# 装最稳，跟 apt 源/dockerd 都解耦。
ARG DOCKER_CLI_VERSION=24.0.7
RUN set -eux; \
    arch=$(dpkg --print-architecture); \
    case "$arch" in \
      amd64) docker_arch=x86_64 ;; \
      arm64) docker_arch=aarch64 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz; \
    tar -xzC /tmp -f /tmp/docker.tgz; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker /tmp/docker.tgz; \
    docker --version

# --- code-server --------------------------------------------
# 用官方 release tarball 装，比 install.sh 可靠（install.sh 在最小化镜像里
# 会静默失败，且 exit code 为 0 会骗过 Docker 缓存）
RUN set -eux; \
    arch=$(dpkg --print-architecture); \
    case "$arch" in \
      amd64) cs_arch=amd64 ;; \
      arm64) cs_arch=arm64 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-${cs_arch}.tar.gz"; \
    mkdir -p /opt/code-server; \
    curl -fsSL "$url" -o /tmp/cs.tgz; \
    tar -xzf /tmp/cs.tgz -C /opt/code-server --strip-components=1; \
    ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server; \
    rm /tmp/cs.tgz; \
    code-server --version

# --- code-server 睿鲸扩展 + Chat fallback patch -------------
# 主机部署依赖 workbench.js patch 将原生 Chat 的 GitHub Copilot 检查
# 切到 apaas-builder.ruijing-ai；容器镜像必须内置同样处理，避免手动安装扩展
# 后仍显示 VS Code 默认 Agent 界面。
COPY --from=ruijing-extension-builder /build/extensions/ruijing-ai/ruijing-ai-*.vsix /tmp/ruijing-ai.vsix
COPY scripts/ /app/scripts/
RUN set -eux; \
    code-server --install-extension /tmp/ruijing-ai.vsix --force; \
    node /app/scripts/patch_all.js --code-server-path /opt/code-server; \
    rm -f /tmp/ruijing-ai.vsix

# --- 后端 Python 依赖 ---------------------------------------
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Playwright 浏览器（默认不装，按需启用）-----------------
# 目前 /api/coding/workspace/{ws_id}/browser/* 端点前端未调用，跳过 Chromium
# 下载以节省 ~500MB 镜像体积。需要时取消下一行注释重建，或在运行容器中临时装：
#   docker exec apaas-builder playwright install --with-deps chromium
# RUN playwright install --with-deps chromium

# --- 拷后端代码 ---------------------------------------------
COPY backend/ /app/backend/
# 镜像内不要带 .env / venv / sqlite db，交给 volume 挂载
RUN rm -rf /app/backend/.env /app/backend/.venv /app/backend/venv \
           /app/backend/apaas_builder.db /app/backend/__pycache__ || true

# --- 拷前端构建产物（直接落在镜像内，不再 VOLUME 挂出）---------
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# --- 挂载点 & 目录 ------------------------------------------
# workspaces 卷由 compose 在运行时挂入（路径由 ${APAAS_WORKSPACE_ROOT} 决定，
# 默认 /data/apaas/workspaces，host 跟容器内路径一致以兼容 vibe-sandbox 子容器）。
# 这里只创建 supervisor 配置目录。
RUN mkdir -p /etc/supervisor/conf.d

# --- supervisord + entrypoint ------------------------------
COPY deploy/docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY deploy/docker/entrypoint.sh    /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# host 网络下无需 EXPOSE，但保留作为文档说明
# 实际监听端口由 PORT / CODE_SERVER_PORT 环境变量控制，默认 8003/8080
EXPOSE 8003 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
