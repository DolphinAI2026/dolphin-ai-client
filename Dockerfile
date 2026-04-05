# ============================================================
# apaas-builder-ai — 生产部署镜像
#
# 包含：
#   - Python 3.11（后端 FastAPI 服务）
#   - Node.js 18（前端构建 / npm）
#   - JDK 8 + Maven 3.8（后端自开发接口打包）
# ============================================================

FROM python:3.11-slim

# ── 系统依赖 ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    unzip \
    # JDK 8
    openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

# ── Maven 3.8.8 ───────────────────────────────────────────
ENV MAVEN_VERSION=3.8.8
ENV MAVEN_HOME=/opt/maven
RUN wget -q "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/${MAVEN_VERSION}/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
    -O /tmp/maven.tar.gz \
    && mkdir -p ${MAVEN_HOME} \
    && tar -xzf /tmp/maven.tar.gz -C ${MAVEN_HOME} --strip-components=1 \
    && rm /tmp/maven.tar.gz
ENV PATH="${MAVEN_HOME}/bin:${PATH}"

# ── Node.js 18 ────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Maven 本地仓库（可挂载宿主机目录加速）────────────────
ENV MAVEN_LOCAL_REPO=/root/.m2/repository
RUN mkdir -p ${MAVEN_LOCAL_REPO}

# ── Maven 全局镜像（国内部署时替换为内网 Nexus）──────────
# 如果部署在内网，可以在 CI/CD 中通过环境变量 MAVEN_MIRROR_URL 覆盖
COPY scripts/docker-maven-settings.xml /root/.m2/settings.xml 2>/dev/null || true

# ── Python 依赖 ───────────────────────────────────────────
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# ── 应用代码 ──────────────────────────────────────────────
COPY . .

# ── 前端构建（可选，若已预构建可注释掉）──────────────────
# RUN cd frontend && npm install && npm run build

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
