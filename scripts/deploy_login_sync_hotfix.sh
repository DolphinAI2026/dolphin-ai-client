#!/usr/bin/env bash
# Build and deploy the login sync hotfix.
#
# Fix included in this checkout:
#   - aPaaS login no longer syncs every platform tenant.
#   - login no longer syncs builtin LLM configs per tenant.
#   - existing tenant PlatformEnv rows are reused instead of inserting duplicates.
#
# Run from the apaas-builder-ai repo:
#   scripts/deploy_login_sync_hotfix.sh
#
# Useful overrides:
#   APP_NAME=apaas-builder-dev PUBLIC_URL=https://agent.dfy.definesys.cn/ai-builder/login scripts/deploy_login_sync_hotfix.sh
#   SKIP_IMAGE_BUILD=1 IMAGE=hub.dfy.definesys.cn/ai-builder/apaas-builder:<tag> scripts/deploy_login_sync_hotfix.sh

set -euo pipefail

if [ -n "${REPO_ROOT:-}" ]; then
  REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
elif [ -n "${BASH_SOURCE:-}" ] && [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "./deploy/docker/Dockerfile" ]; then
  REPO_ROOT="$(pwd)"
else
  printf "[fail] cannot locate repo root. Run from the apaas-builder-ai repo, or set REPO_ROOT=/path/to/apaas-builder-ai\n" >&2
  exit 1
fi

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE="${IMAGE:-}"
PLATFORM="${PLATFORM:-linux/amd64}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-https://df-aigc.dfy.definesys.cn}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
SKIP_IMAGE_BUILD="${SKIP_IMAGE_BUILD:-0}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"

log() { printf '[login-sync-hotfix] %s\n' "$*"; }
warn() { printf '[login-sync-hotfix][warn] %s\n' "$*" >&2; }
die() { printf '[login-sync-hotfix][fail] %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

need kubectl

resolve_image() {
  if [ "$SKIP_IMAGE_BUILD" = "1" ]; then
    [ -n "$IMAGE" ] || die "SKIP_IMAGE_BUILD=1 requires IMAGE=<repo:tag>"
    return
  fi

  need docker
  local sha dirty_suffix
  sha="nogit"
  if command -v git >/dev/null 2>&1 && [ -d "$REPO_ROOT/.git" ]; then
    sha="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || printf nogit)"
  fi
  dirty_suffix=""
  if command -v git >/dev/null 2>&1 && [ -d "$REPO_ROOT/.git" ] \
    && [ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)" ]; then
    dirty_suffix="-dirty"
    warn "building with local uncommitted changes"
  fi
  if [ -z "$IMAGE_TAG" ]; then
    IMAGE_TAG="hotfix-login-sync-$(date +%Y%m%d-%H%M%S)-${sha}${dirty_suffix}"
  fi
  IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"
}

build_and_push_image() {
  if [ "$SKIP_IMAGE_BUILD" = "1" ]; then
    warn "SKIP_IMAGE_BUILD=1, using existing image: ${IMAGE}"
    return
  fi

  log "build and push image: ${IMAGE}"
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build \
      --platform "$PLATFORM" \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE}" \
      -f "$REPO_ROOT/deploy/docker/Dockerfile" \
      -t "$IMAGE" \
      --push \
      "$REPO_ROOT"
  else
    docker build \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE}" \
      -f "$REPO_ROOT/deploy/docker/Dockerfile" \
      -t "$IMAGE" \
      "$REPO_ROOT"
    docker push "$IMAGE"
  fi
}

rollout_image() {
  log "namespace: ${NAMESPACE}"
  log "statefulset: ${APP_NAME}"
  log "image: ${IMAGE}"

  kubectl get namespace "$NAMESPACE" >/dev/null
  kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" >/dev/null

  log "update backend container image"
  kubectl -n "$NAMESPACE" set image \
    "statefulset/${APP_NAME}" \
    "${BACKEND_CONTAINER}=${IMAGE}"

  log "update frontend dist initContainer image"
  kubectl -n "$NAMESPACE" patch "statefulset/${APP_NAME}" --type=strategic -p \
    "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"login-sync-hotfix/restartedAt\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}},\"spec\":{\"initContainers\":[{\"name\":\"${DIST_INIT_CONTAINER}\",\"image\":\"${IMAGE}\"}]}}}}"

  log "wait for rollout"
  kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLL_TIMEOUT"
}

verify() {
  local pod
  pod="$(kubectl -n "$NAMESPACE" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}')"
  if [ -n "$pod" ]; then
    log "current pod: ${pod}"
    kubectl -n "$NAMESPACE" exec "$pod" -c "$BACKEND_CONTAINER" -- \
      sh -lc 'cd /app/backend && python -m py_compile app/routes/auth.py' || true
  fi

  if command -v curl >/dev/null 2>&1; then
    log "health check: ${PUBLIC_URL}"
    curl -k -sS -o /tmp/apaas-builder-login-sync-hotfix.html \
      -w 'HTTP %{http_code} SIZE %{size_download}\n' \
      "$PUBLIC_URL" || true
  fi
}

resolve_image
build_and_push_image
rollout_image
verify
log "done"
