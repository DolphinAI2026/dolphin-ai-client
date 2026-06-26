#!/usr/bin/env bash
# apaas-builder 容器启动脚本
# 详见 DEPLOY_CONTAINER.md
set -eu

WORKSPACE_ROOT="${APAAS_WORKSPACE_ROOT:-/root/apaas-builder/workspaces}"
# npm-cache 默认就放 workspaces 下，只挂一个 volume 就够了
NPM_CACHE_DIR="${APAAS_NPM_CACHE_DIR:-$WORKSPACE_ROOT/.npm-cache}"
export APAAS_NPM_CACHE_DIR="$NPM_CACHE_DIR"

MAVEN_SETTINGS_PATH="${MAVEN_SETTINGS_PATH:-/root/.m2/settings.xml}"
APAAS_MAVEN_REPO_ID="${APAAS_MAVEN_REPO_ID:-dcloud-public}"
APAAS_MAVEN_REPO_USERNAME="${APAAS_MAVEN_REPO_USERNAME:-dcloud-public}"
APAAS_MAVEN_REPO_PASSWORD="${APAAS_MAVEN_REPO_PASSWORD:-dcloud-public}"

echo "[entrypoint] APAAS_WORKSPACE_ROOT=$WORKSPACE_ROOT"
echo "[entrypoint] APAAS_NPM_CACHE_DIR=$NPM_CACHE_DIR"

# 保证挂载点 & 缓存目录存在
mkdir -p "$WORKSPACE_ROOT" "$NPM_CACHE_DIR"

# 后端自开发打包会拉取 com.xdap 私有 Maven 依赖。线上容器没有宿主机
# ~/.m2/settings.xml，因此默认生成 Nexus 认证；若运维已挂载 Secret 则不覆盖。
if [ ! -f "$MAVEN_SETTINGS_PATH" ]; then
    echo "[entrypoint] create Maven settings: $MAVEN_SETTINGS_PATH"
    export MAVEN_SETTINGS_PATH APAAS_MAVEN_REPO_ID APAAS_MAVEN_REPO_USERNAME APAAS_MAVEN_REPO_PASSWORD
    PYTHON_BIN="$(command -v python || command -v python3)"
    "$PYTHON_BIN" - <<'PYEOF'
import os
from pathlib import Path
from xml.sax.saxutils import escape

path = Path(os.environ["MAVEN_SETTINGS_PATH"])
path.parent.mkdir(parents=True, exist_ok=True)

repo_id = escape(os.environ.get("APAAS_MAVEN_REPO_ID", "dcloud-public"))
username = escape(os.environ.get("APAAS_MAVEN_REPO_USERNAME", "dcloud-public"))
password = escape(os.environ.get("APAAS_MAVEN_REPO_PASSWORD", "dcloud-public"))

path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
  <servers>
    <server>
      <id>{repo_id}</id>
      <username>{username}</username>
      <password>{password}</password>
    </server>
  </servers>
  <mirrors>
    <mirror>
      <id>{repo_id}</id>
      <mirrorOf>external:http:*</mirrorOf>
      <url>https://registry.dfy.definesys.cn/repository/maven-public/</url>
    </mirror>
  </mirrors>
</settings>
""", encoding="utf-8")
path.chmod(0o600)
PYEOF
else
    echo "[entrypoint] Maven settings exists: $MAVEN_SETTINGS_PATH"
fi

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
