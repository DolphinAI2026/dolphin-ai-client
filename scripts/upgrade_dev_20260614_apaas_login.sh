#!/usr/bin/env bash
# Self-contained dev upgrade script for the aPaaS login tenant-response fix.
# Safe to paste into a KubeSphere / kubectl web terminal or run as a file.

set -euo pipefail

IMAGE="${IMAGE:-hub.dfy.definesys.cn/ai-builder/apaas-builder:dev-20260614-5a78b452}"
NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder-dev}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://agent.dfy.definesys.cn/ai-builder/login}"
ADMIN_URL="${ADMIN_URL:-https://agent.dfy.definesys.cn/ai-builder/platform-admin}"

log() { printf '[upgrade-dev] %s\n' "$*"; }
die() { printf '[upgrade-dev][fail] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die 'missing command: kubectl'

log "namespace: ${NAMESPACE}"
log "statefulset: ${APP_NAME}"
log "image: ${IMAGE}"

kubectl get namespace "${NAMESPACE}" >/dev/null
kubectl -n "${NAMESPACE}" get "statefulset/${APP_NAME}" >/dev/null

log "update backend container image"
kubectl -n "${NAMESPACE}" set image \
  "statefulset/${APP_NAME}" \
  "${BACKEND_CONTAINER}=${IMAGE}"

log "update frontend dist initContainer image and trigger restart"
kubectl -n "${NAMESPACE}" patch "statefulset/${APP_NAME}" --type=strategic -p "
spec:
  template:
    metadata:
      annotations:
        upgrade-dev/restartedAt: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        upgrade-dev/image: \"${IMAGE}\"
    spec:
      initContainers:
        - name: ${DIST_INIT_CONTAINER}
          image: ${IMAGE}
"

log "wait for rollout"
kubectl -n "${NAMESPACE}" rollout status "statefulset/${APP_NAME}" --timeout="${ROLL_TIMEOUT}"

POD="$(kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [ -n "${POD}" ]; then
  log "current pod: ${POD}"
  kubectl -n "${NAMESPACE}" get pod "${POD}" -o wide || true
fi

if command -v curl >/dev/null 2>&1; then
  log "login route check: ${PUBLIC_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-dev-login.html \
    -w 'LOGIN_HTTP %{http_code} SIZE %{size_download}\n' \
    "${PUBLIC_URL}" || true

  log "admin route check: ${ADMIN_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-dev-platform-admin.html \
    -w 'ADMIN_HTTP %{http_code} SIZE %{size_download}\n' \
    "${ADMIN_URL}" || true
fi

log "done"
