# ============================================================
# apaas-builder 单节点容器镜像
# 详见 DEPLOY_CONTAINER.md
# ============================================================

# 2026-05-18: 砍 stage 0a/0b（jdk8-source / maven-source）—— 被 stage 3 的
# jdk8 + jdk17 + maven-bin 替代（XHH e7bcb00 + dcec96c cherry-pick），
# mvn wrapper 按 pom.xml 自动 JDK 8/17 切换。


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
# stage 1b: 构建平台管理前端（admin-spa）
# ------------------------------------------------------------
FROM node:20-bookworm-slim AS admin-builder

ARG VITE_ADMIN_BASE=/ai-builder/admin/
ARG VITE_API_BASE_URL=/ai-builder/api
ARG VITE_MCP_PUBLIC_BASE=

WORKDIR /build/admin-spa

COPY admin-spa/package.json admin-spa/package-lock.json* ./
RUN npm ci --prefer-offline --no-audit --progress=false

COPY admin-spa/ ./
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE}
# 与主前端一样跳过 vue-tsc：管理台当前类型债不应影响镜像发布。
RUN node_modules/.bin/vite build --base="${VITE_ADMIN_BASE}"


# ------------------------------------------------------------
# stage 3: JDK runtimes for backend packaging
#   - aPaaS 4.x: JDK 8 / Java 1.8
#   - aPaaS 5.x: JDK 17
# ------------------------------------------------------------
FROM eclipse-temurin:8-jdk-jammy AS jdk8
FROM eclipse-temurin:17-jdk-jammy AS jdk17
FROM maven:3.9.9-eclipse-temurin-17 AS maven-bin


# ------------------------------------------------------------
# stage 4: 运行时镜像
#   - Python 3.11 + 后端依赖
#   - Node 20（工作区 npm run serve 用）
#   - Playwright Chromium
#   - supervisord 作为 PID 1
# ------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
# 注：后端代码用到了 PEP 701（f-string 可含反斜杠），Python 3.12+ 必需

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_MAJOR=20

# --- 系统依赖 + Node 20 + Maven (XHH e7bcb00 cherry-pick) ----
# 注：未安装 Chromium 运行时依赖。playwright Python 包会装（import 需要），
# 但不下载浏览器二进制。如果将来真的要启用 /api/coding/.../browser 端点，
# 在运行中的容器里执行：
#   docker exec apaas-builder playwright install --with-deps chromium
# 或取消下方 RUN playwright install 那行的注释并重建镜像。
RUN set -eux; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null \
    || sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list; \
    echo 'Acquire::Retries "10";' > /etc/apt/apt.conf.d/80-retries; \
    echo 'Acquire::http::Timeout "60";' >> /etc/apt/apt.conf.d/80-retries; \
    apt_run() { for i in 1 2 3 4 5; do apt-get update && apt-get install -y --no-install-recommends "$@" && return 0; echo "[apt] retry $i in 10s..."; sleep 10; rm -rf /var/lib/apt/lists/*; done; return 1; }; \
    apt_run curl ca-certificates gnupg git procps rsync supervisor build-essential; \
    mkdir -p /etc/apt/keyrings; \
    curl -fsSL --retry 5 --retry-delay 5 https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list; \
    apt_run nodejs; \
    apt-get purge -y --auto-remove build-essential; \
    rm -rf /var/lib/apt/lists/*

# --- docker CLI（仅 client，不带 daemon）—— mars 独有，vibe-coding 沙箱要 ---
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

COPY --from=jdk8 /opt/java/openjdk /opt/jdk8
COPY --from=jdk17 /opt/java/openjdk /opt/jdk17
COPY --from=maven-bin /usr/share/maven /opt/maven

# Default to JDK 17. Set APAAS_BACKEND_JDK_VERSION=8/17/auto per environment.
# auto switches by pom.xml; 8/17 force the environment-level packaging JDK.
ENV JAVA_HOME=/opt/jdk17
ENV APAAS_BACKEND_JDK_VERSION=17
ENV MAVEN_HOME=/opt/maven
ENV PATH="${JAVA_HOME}/bin:${MAVEN_HOME}/bin:${PATH}"

COPY deploy/docker/mvn-wrapper.sh /usr/local/bin/mvn
RUN chmod +x /usr/local/bin/mvn \
    && java -version \
    && /opt/jdk8/bin/java -version \
    && /opt/jdk17/bin/java -version \
    && mvn -version

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
COPY --from=admin-builder /build/admin-spa/dist /app/admin-spa/dist

# --- 挂载点 & 目录 ------------------------------------------
# workspaces 卷由 compose 在运行时挂入（路径由 ${APAAS_WORKSPACE_ROOT} 决定，
# 默认 /data/apaas/workspaces，host 跟容器内路径一致以兼容 vibe-sandbox 子容器）。
# 这里只创建 supervisor 配置目录。
RUN mkdir -p /etc/supervisor/conf.d

# --- supervisord + entrypoint ------------------------------
COPY deploy/docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY deploy/docker/entrypoint.sh    /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 2026-05-18: JDK 8 + Maven 老块迁移到上方 stage 3 + mvn wrapper（XHH cherry-pick）
# 老 ENV JAVA_HOME=/opt/java/openjdk 会覆盖 wrapper 的 JAVA_HOME=/opt/jdk17，删干净

# host 网络下无需 EXPOSE，但保留作为文档说明
# 实际监听端口由 PORT 环境变量控制，默认 8003
EXPOSE 8003

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
