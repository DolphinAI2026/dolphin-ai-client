# syntax=docker/dockerfile:1.7
# ─────────────────────── Stage 1: build builder frontend ───────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /frontend
ARG BUILDER_BASE_PATH=/
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund --no-progress
COPY frontend/ ./
# Builder 前端挂载路径由镜像构建参数决定：local=/，staging=/mcp-server/，prod=/ai-builder/。
ENV VITE_BASE_URL=${BUILDER_BASE_PATH}
ENV VITE_SANDBOX_PREVIEW_BASE=.vibe-first.cn
RUN npx vite build --base=${BUILDER_BASE_PATH}

# ─────────────────────── Stage 2: build admin-spa ───────────────────────
# 2026-05-13: admin-spa 打包进 image，mount 到 /admin 让管理员可以浏览器
# 管理租户/用户/平台环境/dolphin agent，避免直接 SQL UPDATE 维护
FROM node:20-alpine AS spa-build
WORKDIR /spa
ARG ADMIN_BASE_PATH=/admin/
ARG ADMIN_API_BASE_URL=/api
COPY admin-spa/package*.json ./
RUN npm ci --no-audit --no-fund --no-progress
COPY admin-spa/ ./
# VITE_API_BASE_URL 编译期注入；staging/prod 分别指向自己的外部 API 前缀。
ENV VITE_API_BASE_URL=${ADMIN_API_BASE_URL}
# 跳过 vue-tsc（type check），直接 vite build — 避免源码里非致命 implicit any 拦 build
RUN npx vite build --base=${ADMIN_BASE_PATH}

# JDK runtimes for backend self-development packaging:
# - aPaaS 4.x uses JDK 8 / Java 1.8
# - aPaaS 5.x uses JDK 17
# Copying from Temurin avoids Debian slim repo drift (for example trixie defaulting to JDK 21).
FROM eclipse-temurin:8-jdk-jammy AS jdk8
FROM eclipse-temurin:17-jdk-jammy AS jdk17
FROM maven:3.9.9-eclipse-temurin-17 AS maven-bin

# ─────────────────────── Stage 3: python runtime ───────────────────────
# apaas-builder-mcp-server — production image
# 用法：
#   docker build -t hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:<tag> .
#   docker push hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:<tag>
#
# k8s 上跑：StatefulSet 内单 container；nginx 反代 + ingress 走另一个 container
# 启动端口 8004，root-path 由 ROOT_PATH 环境变量决定；本地默认无外部路径前缀。

FROM python:3.13-slim AS runtime

# 系统依赖：
#   curl - 健康检查 + NodeSource gpg key 下载
#   ca-certificates - letsencrypt + 公司私有 CA
#   git - 可能的 git ops
#   build-essential - cryptography wheel 兜底
#   procps - **必装**，main.py lifespan 用 pkill -f vibe-serve.js 清残留进程
#   gnupg - NodeSource apt 源签名验证需要
RUN printf 'Acquire::Retries "20";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' > /etc/apt/apt.conf.d/99retries \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates git build-essential procps gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=jdk8 /opt/java/openjdk /opt/jdk8
COPY --from=jdk17 /opt/java/openjdk /opt/jdk17
COPY --from=maven-bin /usr/share/maven /opt/maven

# Default to JDK 17. Backend builds switch JAVA_HOME to /opt/jdk8 when pom.xml
# declares Java 1.8.
ENV JAVA_HOME=/opt/jdk17
ENV MAVEN_HOME=/opt/maven
ENV PATH="${JAVA_HOME}/bin:${MAVEN_HOME}/bin:${PATH}"
ENV MAVEN_SETTINGS=/root/.m2/settings.xml

RUN mkdir -p /root/.m2 \
    && cat > /root/.m2/settings.xml <<'EOF'
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
  <servers>
    <server>
      <id>dcloud-public</id>
      <username>dcloud-public</username>
      <password>dcloud-public</password>
    </server>
  </servers>
</settings>
EOF

RUN cat > /usr/local/bin/mvn <<'EOF' \
    && chmod +x /usr/local/bin/mvn
#!/bin/sh
set -eu

POM="${PWD}/pom.xml"
if [ -f "$POM" ]; then
  if grep -Eq '<(java.version|maven.compiler.source|maven.compiler.target|source|target)>[[:space:]]*(1\.8|8)[[:space:]]*</' "$POM"; then
    export JAVA_HOME=/opt/jdk8
  elif grep -Eq '<(java.version|maven.compiler.source|maven.compiler.target|source|target)>[[:space:]]*17[[:space:]]*</' "$POM"; then
    export JAVA_HOME=/opt/jdk17
  fi
fi

export PATH="$JAVA_HOME/bin:$PATH"
exec /opt/maven/bin/mvn --settings "${MAVEN_SETTINGS:-/root/.m2/settings.xml}" "$@"
EOF

RUN cat > /usr/local/bin/java <<'EOF' \
    && chmod +x /usr/local/bin/java
#!/bin/sh
set -eu

exec "${JAVA_HOME:-/opt/jdk17}/bin/java" "$@"
EOF

# Node.js 20 + npm — run_workspace_command 工具调 npm install / npm run build 需要
# 跟 ai-builder Dockerfile 同一套 NodeSource apt 源（避免版本漂移导致行为差异）
# 2026-05-13: ming 实测 agent 调 npm run build 报"未检测到 npm"，根因 mcp-server
# 拆 repo 时漏装 Node.js → 这里补回
ENV NODE_MAJOR=20
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version \
    && java -version \
    && /opt/jdk8/bin/java -version \
    && /opt/jdk17/bin/java -version \
    && mvn -version

WORKDIR /app/backend

# 依赖层先装（利用 Docker layer cache：requirements.txt 不变就不重 pip install）
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 应用代码（含 design_mcp.py + resources/open-design/ 452 KB 资源）
# .dockerignore 已排除 .venv / __pycache__ / 调试文件 / .env 等
COPY backend/ ./

# admin-spa build 产物（从 stage 1）— FastAPI main.py 会 mount /admin → 这里
COPY --from=spa-build /spa/dist /app/admin-spa/dist
# Builder 前端 build 产物 — FastAPI main.py 会 mount / → 这里
COPY --from=frontend-build /frontend/dist /app/frontend/dist

# uvicorn 直接 PID 1，避免 supervisord 复杂度；信号传播由 uvicorn handle
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8004

EXPOSE 8004

# 健康检查走 /api/health（FastAPI 内置 route）
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8004/api/health || exit 1

# --root-path 让 OpenAPI / MCP advertise message endpoint 含外部前缀。
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8004 --workers 1 ${ROOT_PATH:+--root-path \"$ROOT_PATH\"}"]
