#!/usr/bin/env bash
# apaas-builder 容器启动脚本
# 详见 DEPLOY_CONTAINER.md
set -eu

WORKSPACE_ROOT="${APAAS_WORKSPACE_ROOT:-/root/apaas-builder/workspaces}"
# npm-cache 默认就放 workspaces 下，只挂一个 volume 就够了
NPM_CACHE_DIR="${APAAS_NPM_CACHE_DIR:-$WORKSPACE_ROOT/.npm-cache}"
export APAAS_NPM_CACHE_DIR="$NPM_CACHE_DIR"

echo "[entrypoint] APAAS_WORKSPACE_ROOT=$WORKSPACE_ROOT"
echo "[entrypoint] APAAS_NPM_CACHE_DIR=$NPM_CACHE_DIR"

# 保证挂载点 & 缓存目录存在
mkdir -p "$WORKSPACE_ROOT" "$NPM_CACHE_DIR"

# 可选：等 MySQL 就绪
if [ "${WAIT_FOR_MYSQL:-1}" = "1" ] && [ -n "${DATABASE_URL:-}" ]; then
    case "$DATABASE_URL" in
      mysql*|*aiomysql*)
        echo "[entrypoint] waiting for MySQL..."
        python - <<'PYEOF' || echo "[entrypoint] MySQL probe failed, continuing anyway"
import os, re, socket, time, sys
url = os.environ.get("DATABASE_URL", "")
m = re.search(r"@([^:/]+)(?::(\d+))?/", url)
if not m:
    sys.exit(0)
host = m.group(1)
port = int(m.group(2) or "3306")
deadline = time.time() + 30
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint]   MySQL {host}:{port} reachable")
            sys.exit(0)
    except OSError:
        time.sleep(1)
print(f"[entrypoint]   timeout connecting to MySQL {host}:{port}")
sys.exit(1)
PYEOF
        ;;
    esac
fi

echo "[entrypoint] exec supervisord"
exec supervisord -n -c /etc/supervisor/supervisord.conf
