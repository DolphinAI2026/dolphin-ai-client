# Vibe Coding 沙箱镜像
# 给 agent 跑用户代码用的容器：node + python + git + 常用 CLI
#
# 设计原则：
# - 不预装具体框架（next/vite/express），让 agent 按需 npm install
# - 容器以 PID 1 长驻（tail -f /dev/null），通过 docker exec 跑命令
# - workspace 通过 -v 挂载到 /workspace，跟主后端工作区路径共享
# - 监听端口段 6100-6999，host 端用 -p 动态映射
#
# Build: docker build -t vibe-sandbox:latest docker/vibe-sandbox/
#        docker build --build-arg NODE_BASE_IMAGE=node:20-bookworm-slim -t vibe-sandbox:latest docker/vibe-sandbox/
# Size : ~1.2 GB（多阶段构建后）

# Docker Desktop / BuildKit 解析 FROM 元数据时不一定稳定命中 daemon registry-mirrors，
# 这里直接把国内镜像作为默认基础镜像，避免访问 registry-1.docker.io 超时。
ARG NODE_BASE_IMAGE=docker.1ms.run/library/node:20-bookworm-slim
FROM ${NODE_BASE_IMAGE}

LABEL org.opencontainers.image.title="Vibe Coding Sandbox"
LABEL org.opencontainers.image.description="Runtime for Vibe Coding agent — Node 20 + Python 3.11 + pnpm + uv + git"

ARG APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    NPM_CONFIG_REGISTRY=${NPM_REGISTRY} \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false \
    COREPACK_NPM_REGISTRY=${NPM_REGISTRY} \
    FORCE_COLOR=0 \
    LANG=C.UTF-8

# ─────────────────────────── 基础工具 ───────────────────────────
# - python3.11（bookworm 自带，足够跑大多数脚本）
# - git / curl / unzip / vim / tini / sqlite3 / build-essential（部分 npm 包要 native build）
# - pnpm + uv（python 包管理快）
RUN if [ -n "${APT_MIRROR}" ]; then \
      if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
          -e "s#http://deb.debian.org/debian#${APT_MIRROR}#g" \
          -e "s#https://deb.debian.org/debian#${APT_MIRROR}#g" \
          -e "s#http://security.debian.org/debian-security#${APT_MIRROR}-security#g" \
          -e "s#https://security.debian.org/debian-security#${APT_MIRROR}-security#g" \
          /etc/apt/sources.list.d/debian.sources; \
      fi; \
      if [ -f /etc/apt/sources.list ]; then \
        sed -i \
          -e "s#http://deb.debian.org/debian#${APT_MIRROR}#g" \
          -e "s#https://deb.debian.org/debian#${APT_MIRROR}#g" \
          -e "s#http://security.debian.org/debian-security#${APT_MIRROR}-security#g" \
          -e "s#https://security.debian.org/debian-security#${APT_MIRROR}-security#g" \
          /etc/apt/sources.list; \
      fi; \
    fi \
 && apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    unzip \
    ca-certificates \
    procps \
    tini \
    sqlite3 \
    vim-tiny \
    less \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# pnpm（更快的 npm 替代，agent 倾向用它）
RUN corepack enable && corepack prepare pnpm@latest --activate

# uv（Astral 出的 python 包管理，比 pip 快 10x）
# 注：astral.sh 在 build 环境可能被墙，走 PyPI 国内镜像稳定（已配 PIP_INDEX_URL=tsinghua）。
# 装到系统 python，命令在 /usr/local/bin/uv（pip 的 entry_points 行为）。
RUN pip3 install --no-cache-dir --break-system-packages uv \
    && uv --version

# 国内镜像加速兜底（agent 装包失败时有 fallback）
RUN npm config set registry "${NPM_REGISTRY}" --location=global \
 && pip config set global.index-url "${PIP_INDEX_URL}"

# ─────────────────────────── 工作区 ───────────────────────────
WORKDIR /workspace

# 用 tini 做 PID 1（避免僵尸进程）
ENTRYPOINT ["/usr/bin/tini", "--"]

# 默认长驻；run_command 通过 docker exec 进来跑实际命令
CMD ["tail", "-f", "/dev/null"]

# 暴露 vibe-coding 专用端口段（实际用哪个由 agent 决定，host 用 -p 动态映射）
EXPOSE 6100-6999
