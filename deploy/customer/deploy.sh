#!/usr/bin/env bash
# ============================================================
# apaas-builder 客户单机 Docker Compose 一键部署脚本
# ============================================================
# 复用 deploy/docker/docker-compose.yml（团队已验证的编排），在其之上自动补齐
# 客户部署真正缺的环节：
#   1) 前置依赖与必填配置校验   2) 随机生成全部密钥（绝不用默认值）
#   3) 拉起容器 + 健康检查        4) seed 第一个平台管理员（解「无 aPaaS 无管理员」阻塞）
#
# 用法：
#   首次：  ./deploy.sh            # 生成 backend.env（含随机密钥），提示你填必填项
#   填好后：./deploy.sh            # 校验通过后真正部署
#
# 客户只维护一份配置文件：
#   /data/apaas/backend.env（首次运行由 backend.env.template 生成）
# 脚本会从这份文件读取镜像、端口、workspace、JDK、DB、aPaaS、密钥等配置。
# ------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deploy/docker/docker-compose.yml"
TEMPLATE="$SCRIPT_DIR/backend.env.template"
CREATE_ADMIN="$REPO_ROOT/backend/scripts/create_admin.py"

DATA_DIR="${APAAS_BUILDER_DATA_DIR:-/data/apaas}"
BACKEND_ENV_FILE="$DATA_DIR/backend.env"
WORKSPACES_DIR="$DATA_DIR/workspaces"
COMPOSE_ENV="$DATA_DIR/compose.env"

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_TAR="${IMAGE_TAR:-}"
PORT="${PORT:-8003}"
CONTAINER_NAME="${CONTAINER_NAME:-apaas-builder}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
SERVICE="apaas-builder"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_blu=$'\033[36m'; c_rst=$'\033[0m'
log()  { printf "%s[deploy]%s %s\n" "$c_blu" "$c_rst" "$*"; }
ok()   { printf "%s[ ok ]%s %s\n" "$c_grn" "$c_rst" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$c_yel" "$c_rst" "$*" >&2; }
die()  { printf "%s[fail]%s %s\n" "$c_red" "$c_rst" "$*" >&2; exit 1; }

gen()        { openssl rand -base64 32 | tr -d '\n'; }                 # 通用随机密钥
gen_fernet() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }  # 合法 Fernet key（urlsafe b64，32B）
env_get() {
  local key="$1" file="${2:-$BACKEND_ENV_FILE}"
  [ -f "$file" ] || return 0
  grep -E "^${key}=" "$file" | tail -1 | cut -d= -f2-
}

load_customer_config() {
  local v
  v="$(env_get IMAGE_TAG)";          [ -n "$v" ] && IMAGE_TAG="$v"
  v="$(env_get IMAGE_TAR)";          [ -n "$v" ] && IMAGE_TAR="$v"
  v="$(env_get PORT)";               [ -n "$v" ] && PORT="$v"
  v="$(env_get CODE_SERVER_PORT)";   [ -n "$v" ] && CODE_SERVER_PORT="$v"
  v="$(env_get CONTAINER_NAME)";     [ -n "$v" ] && CONTAINER_NAME="$v"
  v="$(env_get VITE_BASE_URL)";      [ -n "$v" ] && VITE_BASE_URL="$v"
  v="$(env_get WORKSPACES_DIR)";     [ -n "$v" ] && WORKSPACES_DIR="$v"
}

# ── 1. 前置依赖 ──────────────────────────────────────────────
preflight() {
  log "检查前置依赖…"
  command -v docker  >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker。"
  docker compose version >/dev/null 2>&1 || die "未找到 'docker compose'（v2），请升级 Docker。"
  command -v openssl >/dev/null 2>&1 || die "未找到 openssl（用于生成密钥）。"
  command -v curl    >/dev/null 2>&1 || die "未找到 curl（用于健康检查）。"
  docker info >/dev/null 2>&1 || die "Docker daemon 未运行或当前用户无权限。"
  [ -f "$COMPOSE_FILE" ] || die "缺少 compose 文件: $COMPOSE_FILE"
  [ -f "$TEMPLATE" ]     || die "缺少模板: $TEMPLATE"
  ok "依赖就绪"
}

# ── 2. 镜像 ──────────────────────────────────────────────────
ensure_image() {
  if [ -n "$IMAGE_TAR" ]; then
    [ -f "$IMAGE_TAR" ] || die "IMAGE_TAR 指定的文件不存在: $IMAGE_TAR"
    log "从 tar 导入镜像: $IMAGE_TAR"
    docker load -i "$IMAGE_TAR"
  fi
  if ! docker image inspect "apaas-builder:$IMAGE_TAG" >/dev/null 2>&1; then
    die "本机没有镜像 apaas-builder:$IMAGE_TAG。
       客户环境通常拉不到内网私库，请二选一：
         a) 由交付方预构建后 docker save 成 tar，部署时 IMAGE_TAR=/path/xxx.tar ./deploy.sh
         b) 在能联网的机器上构建：
            cd $REPO_ROOT && docker build -t apaas-builder:$IMAGE_TAG -f deploy/docker/Dockerfile ."
  fi
  ok "镜像 apaas-builder:$IMAGE_TAG 已就绪"
}

# ── 3. backend.env（首次生成密钥；不覆盖已有）────────────────────
ensure_backend_env() {
  mkdir -p "$DATA_DIR" "$WORKSPACES_DIR"
  if [ -f "$BACKEND_ENV_FILE" ]; then
    ok "复用已有 backend.env: $BACKEND_ENV_FILE（不重置密钥）"
    return
  fi
  log "首次生成 backend.env（随机化全部密钥）…"
  : > "$BACKEND_ENV_FILE"
  chmod 600 "$BACKEND_ENV_FILE"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      JWT_SECRET_KEY=__GENERATE__*)        echo "JWT_SECRET_KEY=$(gen)" ;;
      ENCRYPTION_KEY=__GENERATE__*)        echo "ENCRYPTION_KEY=$(gen)" ;;
      BUILDER_FERNET_KEY=__GENERATE_FERNET__*) echo "BUILDER_FERNET_KEY=$(gen_fernet)" ;;
      *) echo "$line" ;;
    esac
  done < "$TEMPLATE" >> "$BACKEND_ENV_FILE"
  ok "已生成 $BACKEND_ENV_FILE（密钥随机，权限 600）"
  warn "请编辑该文件，把所有 __SET_ME__ 填成客户真实值（DB / aPaaS），然后重新运行本脚本。"
  exit 0
}

validate_backend_env() {
  if grep -q '__SET_ME__' "$BACKEND_ENV_FILE"; then
    grep -n '__SET_ME__' "$BACKEND_ENV_FILE" | sed 's/^/    未填: /' >&2
    die "backend.env still有未填的 __SET_ME__，请补全后重跑。"
  fi
  grep -q '__GENERATE__' "$BACKEND_ENV_FILE" && die "backend.env 残留 __GENERATE__ 占位，疑似生成异常，请删除 $BACKEND_ENV_FILE 重跑。"
  local missing=()
  for k in DATABASE_URL APAAS_BASE_URL JWT_SECRET_KEY ENCRYPTION_KEY; do
    local v; v="$(env_get "$k")"
    [ -n "$v" ] || missing+=("$k")
  done
  [ ${#missing[@]} -eq 0 ] || die "backend.env 缺必填项: ${missing[*]}"
  ok "backend.env 校验通过"
}

# ── 4. MySQL 可达性（仅告警，不阻断；entrypoint 也会等）──────────
probe_mysql() {
  local url host port
  url="$(env_get DATABASE_URL)"
  if [[ "$url" =~ @([^:/]+)(:([0-9]+))?/ ]]; then
    host="${BASH_REMATCH[1]}"; port="${BASH_REMATCH[3]:-3306}"
    if (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
      ok "MySQL $host:$port 可达"; exec 3>&- || true
    else
      warn "MySQL $host:$port 暂不可达 —— 请确认客户 MySQL 已起、库与账号已建、网络可通。"
    fi
  fi
}

# ── 5. 启动 ──────────────────────────────────────────────────
compose_up() {
  local apaas_workspace_root
  apaas_workspace_root="$(env_get APAAS_WORKSPACE_ROOT)"
  [ -n "$apaas_workspace_root" ] || apaas_workspace_root="$WORKSPACES_DIR"
  cat > "$COMPOSE_ENV" <<EOF
IMAGE_TAG=$IMAGE_TAG
CONTAINER_NAME=$CONTAINER_NAME
PORT=$PORT
WORKSPACES_DIR=$WORKSPACES_DIR
APAAS_WORKSPACE_ROOT=$apaas_workspace_root
BACKEND_ENV_FILE=$BACKEND_ENV_FILE
VITE_BASE_URL=$VITE_BASE_URL
EOF
  log "docker compose up -d …"
  docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" up -d
  ok "容器已启动"
}

wait_health() {
  log "等待后端健康检查 http://127.0.0.1:$PORT/api/health …"
  if curl --retry 30 --retry-delay 2 --retry-connrefused --retry-all-errors \
          --connect-timeout 3 -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    ok "后端健康 (/api/health = ok)"
  else
    warn "后端在超时内未就绪。查看日志: docker logs $CONTAINER_NAME --tail 80"
    die "部署未确认成功。"
  fi
}

# ── 6. seed 第一个平台管理员 ─────────────────────────────────
seed_admin() {
  if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$(openssl rand -base64 12 | tr -d '/+=\n')A1!"
    log "未指定 ADMIN_PASSWORD，已随机生成（见末尾汇总）。"
  fi
  # 容器镜像可能早于本脚本，先把 create_admin.py 拷进去再执行
  if [ -f "$CREATE_ADMIN" ]; then
    docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" \
      cp "$CREATE_ADMIN" "$SERVICE:/app/backend/scripts/create_admin.py" 2>/dev/null || true
  fi
  log "创建平台管理员 $ADMIN_USERNAME …"
  if docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" exec -T \
       -e ADMIN_PASSWORD="$ADMIN_PASSWORD" "$SERVICE" \
       bash -lc 'cd /app/backend && python scripts/create_admin.py --username "'"$ADMIN_USERNAME"'" --password "$ADMIN_PASSWORD"'; then
    ok "平台管理员已就绪"
  else
    warn "自动 seed 管理员失败（可手动: docker exec -it $CONTAINER_NAME bash -lc 'cd /app/backend && python scripts/create_admin.py --username admin --password <PW>'）"
  fi
}

summary() {
  cat <<EOF

${c_grn}========================================================${c_rst}
${c_grn} apaas-builder 部署完成${c_rst}
${c_grn}========================================================${c_rst}
  后端 API     : http://127.0.0.1:$PORT/api/health
  API 文档     : http://127.0.0.1:$PORT/docs
  前端访问     : 需在前置 nginx 配置 ${VITE_BASE_URL}（serve 前端 dist + 反代 /api → :$PORT）
                 参考 deploy/docker/nginx.conf.example
  管理员账号   : $ADMIN_USERNAME
  管理员口令   : $ADMIN_PASSWORD
  backend.env  : $BACKEND_ENV_FILE  (权限 600，勿外泄/勿入库)
  数据目录     : $DATA_DIR
  停止         : docker compose --env-file $COMPOSE_ENV -f $COMPOSE_FILE down

${c_yel}⚠ 上生产前仍需人工加固（脚本改不了的代码/编排层，详见安全报告 §6）：${c_rst}
  1. ${c_yel}平台代理鉴权${c_rst}（C-1，最高优先）：platform_proxy 路由加鉴权、废弃全局 _proxy_state 单例。
  2. ${c_yel}容器降权${c_rst}（H-4）：当前 compose 用 host 网络 + 挂 docker.sock；
     ${c_yel}生产需在编排层删掉 docker.sock 挂载并给 Dockerfile 加非 root USER${c_yel}。${c_rst}
  3. ${c_yel}前置 nginx${c_rst}：补 HSTS/X-Frame-Options/CSP/nosniff 安全头（M-5）。
  4. 确认 JWT_SECRET_KEY 不是 README 泄漏的那枚；轮换历史泄漏密钥（C-3）。
EOF
}

main() {
  log "apaas-builder 客户部署 — 数据目录 $DATA_DIR"
  preflight
  ensure_backend_env      # 首次会在此 exit 0，提示填必填项
  load_customer_config
  validate_backend_env
  ensure_image
  probe_mysql
  compose_up
  wait_health
  seed_admin
  summary
}

main "$@"
