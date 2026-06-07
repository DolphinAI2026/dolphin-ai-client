#!/usr/bin/env bash
# Patch the production K8s backend.env to use the aPaaS trial base URL.
#
# Safe for KubeSphere / web kubectl terminals: this script is self-contained and
# does not need the repository files to exist on the target machine. It only
# updates the backend.env Secret, removes stale APAAS_TENANT_ID, restarts the
# StatefulSet, and performs a light login-page health check.
#
# Defaults target production:
#   namespace:   apaas-builder
#   statefulset: apaas-builder
#   secret:      apaas-backend-env
#
# Useful overrides:
#   APP_NAME=apaas-builder-dev BACKEND_SECRET=apaas-backend-env-dev PUBLIC_URL=https://agent.dfy.definesys.cn/ai-builder/login bash patch_trial_k8s_backend_env.sh

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env}"
SECRET_KEY="${SECRET_KEY:-backend.env}"
APAAS_BASE_URL="${APAAS_BASE_URL:-https://apaas-trial.definesys.cn/backend}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"

log() { printf '[patch-trial-env] %s\n' "$*"; }
die() { printf '[patch-trial-env][fail] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die 'missing command: kubectl'
command -v base64 >/dev/null 2>&1 || die 'missing command: base64'

jsonpath_key="${SECRET_KEY//./\\.}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
env_file="${tmpdir}/backend.env"
patched_file="${tmpdir}/backend.env.patched"
backup_file="/tmp/${BACKEND_SECRET}-${SECRET_KEY}-$(date +%Y%m%d-%H%M%S).bak"

log "namespace: ${NAMESPACE}"
log "statefulset: ${APP_NAME}"
log "secret: ${BACKEND_SECRET}:${SECRET_KEY}"
log "APAAS_BASE_URL: ${APAAS_BASE_URL}"

kubectl get namespace "${NAMESPACE}" >/dev/null
kubectl -n "${NAMESPACE}" get "statefulset/${APP_NAME}" >/dev/null
kubectl -n "${NAMESPACE}" get secret "${BACKEND_SECRET}" >/dev/null

log "read current backend.env"
kubectl -n "${NAMESPACE}" get secret "${BACKEND_SECRET}" \
  -o "jsonpath={.data.${jsonpath_key}}" \
  | base64 -d > "${env_file}"

cp "${env_file}" "${backup_file}"
log "backup saved: ${backup_file}"

log "patch APAAS_BASE_URL and remove stale APAAS_TENANT_ID"
awk -v base_url="${APAAS_BASE_URL}" '
  BEGIN { wrote_base = 0 }
  /^APAAS_TENANT_ID=/ { next }
  /^APAAS_BASE_URL=/ {
    if (wrote_base == 0) {
      print "APAAS_BASE_URL=" base_url
      wrote_base = 1
    }
    next
  }
  { print }
  END {
    if (wrote_base == 0) {
      print ""
      print "APAAS_BASE_URL=" base_url
    }
  }
' "${env_file}" > "${patched_file}"

log "patched values"
grep -E '^(APAAS_BASE_URL|APAAS_TENANT_ID)=' "${patched_file}" || true
if grep -q '^APAAS_TENANT_ID=' "${patched_file}"; then
  die 'APAAS_TENANT_ID still exists after patch'
fi

log "apply Secret"
kubectl -n "${NAMESPACE}" create secret generic "${BACKEND_SECRET}" \
  --from-file="${SECRET_KEY}=${patched_file}" \
  --dry-run=client -o yaml \
  | kubectl apply -f -

log "restart StatefulSet"
kubectl -n "${NAMESPACE}" rollout restart "statefulset/${APP_NAME}"
kubectl -n "${NAMESPACE}" rollout status "statefulset/${APP_NAME}" --timeout="${ROLL_TIMEOUT}"

pod="$(kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}')"
if [ -n "${pod}" ]; then
  log "current pod: ${pod}"
  log "runtime settings loaded inside pod"
  kubectl -n "${NAMESPACE}" exec "${pod}" -c apaas-builder -- \
    sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
from app.config import settings
print(f"APAAS_BASE_URL={settings.apaas_base_url}")
print("APAAS_TENANT_ID=" + (settings.apaas_tenant_id or "[empty]"))
PY' || true
fi

if command -v curl >/dev/null 2>&1; then
  log "health check: ${PUBLIC_URL}"
  curl -k -sS -o /tmp/apaas-builder-trial-login.html \
    -w 'HTTP %{http_code} SIZE %{size_download}\n' \
    "${PUBLIC_URL}" || true
fi

log "done"
