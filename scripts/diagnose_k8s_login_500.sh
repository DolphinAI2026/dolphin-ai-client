#!/usr/bin/env bash
# Diagnose apaas-builder login failures in Kubernetes.
#
# Safe for KubeSphere / web kubectl terminals: self-contained and read-only.
# It prints the active pod, loaded env, health endpoints, recent backend logs,
# and auth/login related log lines.

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env}"
SECRET_KEY="${SECRET_KEY:-backend.env}"
CONTAINER="${CONTAINER:-apaas-builder}"
PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"
LOG_LINES="${LOG_LINES:-300}"

log() { printf '[diagnose-login] %s\n' "$*"; }
die() { printf '[diagnose-login][fail] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die 'missing command: kubectl'
command -v base64 >/dev/null 2>&1 || die 'missing command: base64'

jsonpath_key="${SECRET_KEY//./\\.}"

log "namespace: ${NAMESPACE}"
log "statefulset/app: ${APP_NAME}"
log "secret: ${BACKEND_SECRET}:${SECRET_KEY}"

kubectl get namespace "${NAMESPACE}" >/dev/null

log "pods"
kubectl -n "${NAMESPACE}" get pods -l "app=${APP_NAME}" -o wide

pod="$(kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}')"
[ -n "${pod}" ] || die "no pod found for app=${APP_NAME}"
log "selected pod: ${pod}"

log "backend.env selected keys from Secret"
kubectl -n "${NAMESPACE}" get secret "${BACKEND_SECRET}" \
  -o "jsonpath={.data.${jsonpath_key}}" \
  | base64 -d \
  | awk -F= '
      $1=="APAAS_BASE_URL" || $1=="APAAS_TENANT_ID" || $1=="DATABASE_URL" || $1=="LLM_API_KEY" || $1=="JWT_SECRET_KEY" || $1=="ENCRYPTION_KEY" {
        if ($1=="DATABASE_URL" || $1 ~ /(KEY|SECRET|TOKEN|PASSWORD)/) {
          print $1"=<masked>"
        } else {
          print $0
        }
      }
    '

log "runtime settings inside pod"
kubectl -n "${NAMESPACE}" exec "${pod}" -c "${CONTAINER}" -- sh -lc 'cd /app/backend && python - <<'"'"'PY'"'"'
from app.config import settings
from urllib.parse import urlsplit

db = urlsplit(settings.database_url)
print("APAAS_BASE_URL=" + (settings.apaas_base_url or "[empty]"))
print("APAAS_TENANT_ID=" + (settings.apaas_tenant_id or "[empty]"))
print("DATABASE_HOST=" + (db.hostname or "[empty]"))
print("DATABASE_NAME=" + ((db.path or "").lstrip("/") or "[empty]"))
PY'

log "backend local health from inside pod"
kubectl -n "${NAMESPACE}" exec "${pod}" -c "${CONTAINER}" -- sh -lc \
  'curl -sS -o /tmp/health.out -w "health HTTP %{http_code} SIZE %{size_download}\n" http://127.0.0.1:8003/api/health; cat /tmp/health.out; echo'

log "public login health"
if command -v curl >/dev/null 2>&1; then
  curl -k -sS -o /tmp/apaas-builder-login-diagnose.html \
    -w 'public login HTTP %{http_code} SIZE %{size_download}\n' \
    "${PUBLIC_URL}" || true
fi

log "recent backend logs, last ${LOG_LINES} lines"
kubectl -n "${NAMESPACE}" logs "${pod}" -c "${CONTAINER}" --tail="${LOG_LINES}" || true

log "auth/login and traceback snippets"
kubectl -n "${NAMESPACE}" logs "${pod}" -c "${CONTAINER}" --tail=1200 \
  | grep -Ei 'auth/login|aPaaS 登录|Traceback|Exception|ERROR|500|RequestError|IntegrityError|OperationalError|NoSuch|KeyError|TypeError|ValueError' \
  || true

log "done"
