#!/usr/bin/env bash
# Upgrade dev and/or main Kubernetes StatefulSets to the 2026-07-01 image.
#
# Usage:
#   scripts/upgrade_dev_main_20260701.sh dev
#   scripts/upgrade_dev_main_20260701.sh main
#   scripts/upgrade_dev_main_20260701.sh all
#
# Safe to run from KubeSphere / kubectl terminals. It only updates container
# images and rolls the StatefulSet; it does not touch Secrets, PVCs, databases,
# or workspace volumes.

set -euo pipefail

IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
DEV_IMAGE="${DEV_IMAGE:-${IMAGE_REPO}:dev-20260701-final}"
MAIN_IMAGE="${MAIN_IMAGE:-${IMAGE_REPO}:main-20260701-final}"
NAMESPACE="${NAMESPACE:-apaas-builder}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"

log() { printf '[upgrade-20260701] %s\n' "$*"; }
die() { printf '[upgrade-20260701][fail] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die "missing command: kubectl"

rollout_one() {
  local env_name="$1"
  local app_name="$2"
  local image="$3"
  local login_url="$4"
  local admin_url="$5"

  log "env=${env_name}"
  log "namespace=${NAMESPACE}"
  log "statefulset=${app_name}"
  log "image=${image}"

  kubectl get namespace "${NAMESPACE}" >/dev/null
  kubectl -n "${NAMESPACE}" get "statefulset/${app_name}" >/dev/null

  log "set backend image"
  kubectl -n "${NAMESPACE}" set image \
    "statefulset/${app_name}" \
    "${BACKEND_CONTAINER}=${image}"

  log "set frontend dist initContainer image and trigger restart"
  kubectl -n "${NAMESPACE}" patch "statefulset/${app_name}" --type=strategic -p "
spec:
  template:
    metadata:
      annotations:
        upgrade-20260701/restartedAt: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        upgrade-20260701/image: \"${image}\"
    spec:
      initContainers:
        - name: ${DIST_INIT_CONTAINER}
          image: ${image}
"

  log "wait rollout"
  kubectl -n "${NAMESPACE}" rollout status "statefulset/${app_name}" --timeout="${ROLL_TIMEOUT}"

  log "pods"
  kubectl -n "${NAMESPACE}" get pod -l "app=${app_name}" -o wide || true

  if command -v curl >/dev/null 2>&1; then
    log "login route check: ${login_url}"
    curl -k -L -sS -o "/tmp/${app_name}-login.html" \
      -w 'LOGIN_HTTP %{http_code} SIZE %{size_download}\n' \
      "${login_url}" || true

    log "admin route check: ${admin_url}"
    curl -k -L -sS -o "/tmp/${app_name}-platform-admin.html" \
      -w 'ADMIN_HTTP %{http_code} SIZE %{size_download}\n' \
      "${admin_url}" || true
  fi

  log "${env_name} done"
}

upgrade_dev() {
  rollout_one \
    "dev" \
    "${DEV_APP_NAME:-apaas-builder-dev}" \
    "${DEV_IMAGE}" \
    "${DEV_PUBLIC_URL:-https://agent.dfy.definesys.cn/ai-builder/login}" \
    "${DEV_ADMIN_URL:-https://agent.dfy.definesys.cn/ai-builder/platform-admin}"
}

upgrade_main() {
  rollout_one \
    "main" \
    "${MAIN_APP_NAME:-apaas-builder}" \
    "${MAIN_IMAGE}" \
    "${MAIN_PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}" \
    "${MAIN_ADMIN_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/platform-admin}"
}

target="${1:-all}"
case "${target}" in
  dev)
    upgrade_dev
    ;;
  main)
    upgrade_main
    ;;
  all)
    upgrade_dev
    upgrade_main
    ;;
  *)
    die "usage: $0 dev|main|all"
    ;;
esac
