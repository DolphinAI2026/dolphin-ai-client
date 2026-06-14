#!/usr/bin/env bash
# Read-only audit for config/code/database drift in the K8s deployment.
#
# Safe for KubeSphere / web kubectl terminals: self-contained and read-only.
# It does not patch Secrets, update database rows, restart pods, or deploy images.

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
DEV_APP_NAME="${DEV_APP_NAME:-apaas-builder-dev}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env}"
DEV_BACKEND_SECRET="${DEV_BACKEND_SECRET:-apaas-backend-env-dev}"
SECRET_KEY="${SECRET_KEY:-backend.env}"
CONTAINER="${CONTAINER:-apaas-builder}"
LOG_LINES="${LOG_LINES:-500}"

log() { printf '\n[audit] %s\n' "$*"; }
warn() { printf '[audit][warn] %s\n' "$*" >&2; }
die() { printf '[audit][fail] %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

secret_jsonpath_key="${SECRET_KEY//./\\.}"

need kubectl
need base64

log "target"
echo "NAMESPACE=${NAMESPACE}"
echo "APP_NAME=${APP_NAME}"
echo "BACKEND_SECRET=${BACKEND_SECRET}:${SECRET_KEY}"
echo "DEV_APP_NAME=${DEV_APP_NAME}"
echo "DEV_BACKEND_SECRET=${DEV_BACKEND_SECRET}:${SECRET_KEY}"

kubectl get namespace "${NAMESPACE}" >/dev/null

log "StatefulSet images"
kubectl -n "${NAMESPACE}" get sts "${APP_NAME}" "${DEV_APP_NAME}" \
  -o jsonpath='{range .items[*]}{.metadata.name}{" backend="}{.spec.template.spec.containers[?(@.name=="apaas-builder")].image}{" init="}{.spec.template.spec.initContainers[?(@.name=="copy-frontend-dist")].image}{"\n"}{end}' \
  2>/dev/null || kubectl -n "${NAMESPACE}" get sts "${APP_NAME}" -o wide

log "pods"
kubectl -n "${NAMESPACE}" get pods -l "app=${APP_NAME}" -o wide
if kubectl -n "${NAMESPACE}" get sts "${DEV_APP_NAME}" >/dev/null 2>&1; then
  kubectl -n "${NAMESPACE}" get pods -l "app=${DEV_APP_NAME}" -o wide || true
fi

pod="$(kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}')"
[ -n "${pod}" ] || die "no pod found for app=${APP_NAME}"
echo "selected pod=${pod}"

print_secret_keys() {
  local name="$1"
  if ! kubectl -n "${NAMESPACE}" get secret "${name}" >/dev/null 2>&1; then
    warn "Secret not found: ${name}"
    return
  fi
  echo "-- ${name}"
  kubectl -n "${NAMESPACE}" get secret "${name}" \
    -o "jsonpath={.data.${secret_jsonpath_key}}" \
    | base64 -d \
    | awk -F= '
        $1=="APAAS_BASE_URL" || $1=="APAAS_TENANT_ID" || $1=="DATABASE_URL" || $1=="LLM_API_KEY" || $1=="ANTHROPIC_API_KEY" || $1=="JWT_SECRET_KEY" || $1=="ENCRYPTION_KEY" || $1=="MCP_API_KEYS" {
          if ($1=="DATABASE_URL" || $1 ~ /(KEY|SECRET|TOKEN|PASSWORD)/) print $1"=<masked>";
          else print $0;
        }
      '
}

log "Secret backend.env selected keys"
print_secret_keys "${BACKEND_SECRET}"
print_secret_keys "${DEV_BACKEND_SECRET}"

log "runtime settings in selected production pod"
kubectl -n "${NAMESPACE}" exec "${pod}" -c "${CONTAINER}" -- sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
from app.config import settings
from urllib.parse import urlsplit

db = urlsplit(settings.database_url)
print("APAAS_BASE_URL=" + (settings.apaas_base_url or "[empty]"))
print("APAAS_TENANT_ID=" + (settings.apaas_tenant_id or "[empty]"))
print("DATABASE_HOST=" + (db.hostname or "[empty]"))
print("DATABASE_NAME=" + ((db.path or "").lstrip("/") or "[empty]"))
PY'

log "deployed auth.py behavior check"
kubectl -n "${NAMESPACE}" exec "${pod}" -c "${CONTAINER}" -- sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
from pathlib import Path

text = Path("app/routes/auth.py").read_text(encoding="utf-8")
checks = {
    "login_calls_all_tenants": "all_tenants = await _apaas_all_tenants" in text,
    "login_syncs_builtin_llm": "sync_builtin_llm_configs(db, tenant_ids=[tenant.id]" in text,
    "ensure_env_reuses_any_tenant_env": ".where(PlatformEnv.tenant_id == tenant.id)" in text and ".order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())" in text,
}
for key, value in checks.items():
    print(f"{key}={value}")
PY'

log "database binding audit"
kubectl -n "${NAMESPACE}" exec "${pod}" -c "${CONTAINER}" -- sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
import asyncio
from collections import Counter
from sqlalchemy import select, text

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Application, PlatformEnv
from app.models.tenant import Tenant

async def main():
    expected_base = (settings.apaas_base_url or "").rstrip("/")
    async with AsyncSessionLocal() as db:
        print("schema/indexes platform_envs:")
        try:
            rows = (await db.execute(text("SHOW INDEX FROM platform_envs"))).mappings().all()
            for r in rows:
                key = r.get("Key_name")
                col = r.get("Column_name")
                non_unique = r.get("Non_unique")
                if key and key != "PRIMARY":
                    print(f"  {key} col={col} unique={non_unique == 0}")
        except Exception as exc:
            print(f"  index check skipped: {type(exc).__name__}: {exc}")

        tenants = (await db.execute(select(Tenant).order_by(Tenant.id.asc()))).scalars().all()
        envs = (await db.execute(select(PlatformEnv).order_by(PlatformEnv.id.asc()))).scalars().all()
        apps = (await db.execute(select(Application).order_by(Application.id.desc()).limit(50))).scalars().all()

        env_by_id = {e.id: e for e in envs}
        env_count_by_tenant = Counter(e.tenant_id for e in envs)
        tenant_by_id = {t.id: t for t in tenants}

        print(f"counts tenants={len(tenants)} platform_envs={len(envs)} sample_apps={len(apps)}")

        issues = []
        for t in tenants:
            if t.apaas_env_id and t.apaas_env_id not in env_by_id:
                issues.append(f"TENANT_DANGLING_ENV tenant_id={t.id} apaas_env_id={t.apaas_env_id}")
            if env_count_by_tenant[t.id] > 1:
                issues.append(f"TENANT_MULTI_ENV tenant_id={t.id} env_count={env_count_by_tenant[t.id]}")

        for e in envs:
            t = tenant_by_id.get(e.tenant_id)
            if not t:
                issues.append(f"ENV_DANGLING_TENANT env_id={e.id} tenant_id={e.tenant_id}")
                continue
            if expected_base and (e.base_url or "").rstrip("/") != expected_base:
                issues.append(f"ENV_BASE_MISMATCH env_id={e.id} tenant_id={e.tenant_id} env_base={e.base_url} expected={expected_base}")
            if t.apaas_tenant_id_str and e.platform_tenant_id != t.apaas_tenant_id_str:
                issues.append(f"ENV_TENANT_ID_MISMATCH env_id={e.id} tenant_id={e.tenant_id} env_platform_tid={e.platform_tenant_id} tenant_apaas_tid={t.apaas_tenant_id_str}")
            if t.apaas_env_id and t.apaas_env_id != e.id and env_count_by_tenant[e.tenant_id] == 1:
                issues.append(f"TENANT_ENV_POINTER_MISMATCH tenant_id={t.id} tenant_apaas_env_id={t.apaas_env_id} actual_env_id={e.id}")

        for app in apps:
            if app.platform_env_id and app.platform_env_id not in env_by_id:
                issues.append(f"APP_DANGLING_ENV app_id={app.id} app_name={app.app_name} platform_env_id={app.platform_env_id}")

        print("platform_envs:")
        for e in envs[:80]:
            t = tenant_by_id.get(e.tenant_id)
            print(
                f"  env_id={e.id} tenant_id={e.tenant_id} tenant_code={(t.tenant_code if t else None)} "
                f"tenant_apaas_tid={(t.apaas_tenant_id_str if t else None)} env_platform_tid={e.platform_tenant_id} "
                f"base={e.base_url} default={e.is_default} status={e.status} alias={e.alias}"
            )
        if len(envs) > 80:
            print(f"  ... {len(envs) - 80} more envs omitted")

        print("issues:")
        if issues:
            for issue in issues[:200]:
                print("  " + issue)
            if len(issues) > 200:
                print(f"  ... {len(issues) - 200} more issues omitted")
        else:
            print("  none")

asyncio.run(main())
PY'

log "recent login errors"
kubectl -n "${NAMESPACE}" logs "${pod}" -c "${CONTAINER}" --tail="${LOG_LINES}" \
  | grep -Ei 'POST /api/auth/login|Duplicate entry|platform_envs|PendingRollback|Traceback|IntegrityError|ERROR|500|parameters' \
  | tail -160 || true

log "done (read-only)"
