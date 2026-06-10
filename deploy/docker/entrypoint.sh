#!/usr/bin/env bash
# apaas-builder 容器启动脚本
# 详见 DEPLOY_CONTAINER.md
set -eu

WORKSPACE_ROOT="${APAAS_WORKSPACE_ROOT:-/root/apaas-builder/workspaces}"
# npm-cache 默认就放 workspaces 下，只挂一个 volume 就够了
NPM_CACHE_DIR="${APAAS_NPM_CACHE_DIR:-$WORKSPACE_ROOT/.npm-cache}"
CODE_SERVER_DATA_DIR="${CODE_SERVER_DATA_DIR:-/root/.local/share/code-server}"
export APAAS_NPM_CACHE_DIR="$NPM_CACHE_DIR"
export CODE_SERVER_DATA_DIR

echo "[entrypoint] APAAS_WORKSPACE_ROOT=$WORKSPACE_ROOT"
echo "[entrypoint] APAAS_NPM_CACHE_DIR=$NPM_CACHE_DIR"
echo "[entrypoint] CODE_SERVER_DATA_DIR=$CODE_SERVER_DATA_DIR"

# 保证挂载点 & 缓存目录存在
mkdir -p "$WORKSPACE_ROOT" "$NPM_CACHE_DIR" "$CODE_SERVER_DATA_DIR/User"

# code-server 默认启用 Workspace Trust。线上 IDE 嵌在 AI Builder 抽屉里时，
# 首次信任弹窗会挡住睿鲸 Chat，视觉上表现为白屏。
python - <<'PYEOF'
import json
import os
from pathlib import Path

settings_path = Path(os.environ["CODE_SERVER_DATA_DIR"]) / "User" / "settings.json"
try:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    if not isinstance(settings, dict):
        settings = {}
except Exception:
    settings = {}

settings["security.workspace.trust.enabled"] = False
settings["security.workspace.trust.startupPrompt"] = "never"
settings["security.workspace.trust.untrustedFiles"] = "open"
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
print(f"[entrypoint] code-server workspace trust disabled: {settings_path}")
PYEOF

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
