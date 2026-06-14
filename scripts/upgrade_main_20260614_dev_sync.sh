#!/usr/bin/env bash
# Self-contained main/prod upgrade script after syncing dev into main.
# Safe to paste into a KubeSphere / kubectl web terminal or run as a file.

set -euo pipefail

IMAGE="${IMAGE:-hub.dfy.definesys.cn/ai-builder/apaas-builder:main-20260614-58e0603f}"
NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"
ADMIN_URL="${ADMIN_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/platform-admin}"

log() { printf '[upgrade-main] %s\n' "$*"; }
die() { printf '[upgrade-main][fail] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die 'missing command: kubectl'

log "namespace: ${NAMESPACE}"
log "statefulset: ${APP_NAME}"
log "image: ${IMAGE}"

kubectl get namespace "${NAMESPACE}" >/dev/null
kubectl -n "${NAMESPACE}" get "statefulset/${APP_NAME}" >/dev/null

log "update backend image"
kubectl -n "${NAMESPACE}" set image \
  "statefulset/${APP_NAME}" \
  "${BACKEND_CONTAINER}=${IMAGE}"

log "update dist initContainer image and restart"
PATCH_FILE="$(mktemp /tmp/apaas-builder-main-upgrade.XXXXXX.yaml)"
trap 'rm -f "${PATCH_FILE}"' EXIT
cat > "${PATCH_FILE}" <<EOF
spec:
  template:
    metadata:
      annotations:
        upgrade-main/restartedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        upgrade-main/image: "${IMAGE}"
    spec:
      initContainers:
        - name: ${DIST_INIT_CONTAINER}
          image: ${IMAGE}
EOF

kubectl -n "${NAMESPACE}" patch "statefulset/${APP_NAME}" \
  --type=strategic \
  --patch-file "${PATCH_FILE}"

log "wait rollout"
kubectl -n "${NAMESPACE}" rollout status "statefulset/${APP_NAME}" --timeout="${ROLL_TIMEOUT}"

log "pod"
kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o wide || true

if command -v curl >/dev/null 2>&1; then
  log "login route check: ${PUBLIC_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-main-login.html \
    -w 'LOGIN_HTTP %{http_code} SIZE %{size_download}\n' \
    "${PUBLIC_URL}" || true

  log "admin route check: ${ADMIN_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-main-platform-admin.html \
    -w 'ADMIN_HTTP %{http_code} SIZE %{size_download}\n' \
    "${ADMIN_URL}" || true
fi

log "done"
