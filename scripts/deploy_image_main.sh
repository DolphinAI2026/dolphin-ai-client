#!/usr/bin/env bash
# Roll out the prebuilt main/prod image.
#
# Safe for KubeSphere / web kubectl terminals: this script is self-contained and
# does not need the repository files to exist on the target machine. It only
# updates StatefulSet images and waits for rollout. It does not delete databases,
# Secrets, PVCs, or workspace volumes, so data remains in place.

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
IMAGE="${IMAGE:-hub.dfy.definesys.cn/ai-builder/apaas-builder:main-202606080026-support-triage-mcp}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"

log() { printf '[deploy-main-image] %s\n' "$*"; }
die() { printf '[deploy-main-image][fail] %s\n' "$*" >&2; exit 1; }

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

log "update frontend dist initContainer image"
kubectl -n "${NAMESPACE}" patch "statefulset/${APP_NAME}" --type=strategic -p \
  "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"deploy-image/restartedAt\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}},\"spec\":{\"initContainers\":[{\"name\":\"${DIST_INIT_CONTAINER}\",\"image\":\"${IMAGE}\"}]}}}}"

log "wait for rollout"
kubectl -n "${NAMESPACE}" rollout status "statefulset/${APP_NAME}" --timeout="${ROLL_TIMEOUT}"

pod="$(kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}')"
if [ -n "${pod}" ]; then
  log "current pod: ${pod}"
fi

if command -v curl >/dev/null 2>&1; then
  log "health check: ${PUBLIC_URL}"
  curl -k -sS -o /tmp/apaas-builder-main-login.html \
    -w 'HTTP %{http_code} SIZE %{size_download}\n' \
    "${PUBLIC_URL}" || true
fi

log "done"
