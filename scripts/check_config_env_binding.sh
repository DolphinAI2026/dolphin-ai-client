#!/usr/bin/env bash
# Check that the running AI Builder backend is bound to the aPaaS environment
# from backend.env / Secret, and show stale application platform_env_id values.
#
# Usage:
#   scripts/check_config_env_binding.sh
#   APP_ID=123 scripts/check_config_env_binding.sh
#   APP_NAME_LIKE='场景QMS' scripts/check_config_env_binding.sh
#
# Common overrides:
#   NAMESPACE=apaas-builder
#   APP_NAME=apaas-builder-dev
#   BACKEND_SECRET=apaas-backend-env-dev
#   CONTAINER=apaas-builder

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder-dev}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env-dev}"
CONTAINER="${CONTAINER:-apaas-builder}"
APP_ID="${APP_ID:-}"
APP_NAME_LIKE="${APP_NAME_LIKE:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

need kubectl

echo "[1/4] backend Secret: ${NAMESPACE}/${BACKEND_SECRET}"
secret_env="$(
  kubectl -n "$NAMESPACE" get secret "$BACKEND_SECRET" -o jsonpath='{.data.backend\.env}' \
    | base64 -d
)"

printf '%s\n' "$secret_env" \
  | awk -F= '
      $1=="APAAS_BASE_URL" || $1=="APAAS_TENANT_ID" || $1=="DATABASE_URL" {
        if ($1=="DATABASE_URL") {
          print $1"=<masked>"
        } else {
          print $0
        }
      }
    '

echo
echo "[2/4] running pod for app=${APP_NAME}"
pod="$(
  kubectl -n "$NAMESPACE" get pod -l "app=${APP_NAME}" \
    -o jsonpath='{.items[0].metadata.name}'
)"
if [ -z "$pod" ]; then
  echo "no pod found for app=${APP_NAME} in namespace ${NAMESPACE}" >&2
  exit 1
fi
echo "pod=${pod}"

echo
echo "[3/4] backend settings loaded inside pod"
kubectl -n "$NAMESPACE" exec "$pod" -c "$CONTAINER" -- \
  sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
from app.config import settings
from urllib.parse import urlsplit

db = urlsplit(settings.database_url)
print(f"APAAS_BASE_URL={settings.apaas_base_url}")
print(f"APAAS_TENANT_ID={settings.apaas_tenant_id}")
print(f"DATABASE_HOST={db.hostname or ''}")
print(f"DATABASE_NAME={(db.path or '').lstrip('/')}")
PY'

echo
echo "[4/4] application bindings in database"
kubectl -n "$NAMESPACE" exec "$pod" -c "$CONTAINER" -- \
  env APP_ID="$APP_ID" APP_NAME_LIKE="$APP_NAME_LIKE" \
  sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
import asyncio
import os
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Application, PlatformEnv

app_id = (os.getenv("APP_ID") or "").strip()
name_like = (os.getenv("APP_NAME_LIKE") or "").strip()

async def main():
    async with AsyncSessionLocal() as db:
        stmt = select(Application).order_by(Application.id.desc()).limit(20)
        if app_id:
            stmt = select(Application).where(Application.id == int(app_id))
        elif name_like:
            stmt = (
                select(Application)
                .where(Application.app_name.like(f"%{name_like}%"))
                .order_by(Application.id.desc())
                .limit(20)
            )

        apps = (await db.execute(stmt)).scalars().all()
        if not apps:
            print("no applications matched")
            return

        env_ids = sorted({a.platform_env_id for a in apps if a.platform_env_id})
        env_map = {}
        if env_ids:
            rows = (await db.execute(select(PlatformEnv).where(PlatformEnv.id.in_(env_ids)))).scalars().all()
            env_map = {e.id: e for e in rows}

        print("id\tname\tapp_code\tapaas_app_id\tstale_platform_env_id\tenv_exists")
        for app in apps:
            env_exists = "yes" if app.platform_env_id in env_map else "no"
            print(
                f"{app.id}\t{app.app_name}\t{app.app_code}\t"
                f"{app.apaas_app_id or ''}\t{app.platform_env_id or ''}\t{env_exists}"
            )

asyncio.run(main())
PY'

echo
echo "Done. Runtime menu loading should use APAAS_BASE_URL/APAAS_TENANT_ID above; stale_platform_env_id is diagnostic only."
