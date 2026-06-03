#!/usr/bin/env bash
# Deploy the platform-proxy iframe routing hotfix.
#
# What it does:
#   1. Builds and pushes the current checkout as a new image.
#   2. Applies deploy/k8s/15-configmap-nginx.yaml as the target nginx ConfigMap.
#   3. Updates the StatefulSet image for both the backend container and dist-copy initContainer.
#   4. Waits for rollout and verifies nginx config inside the running sidecar.
#
# Typical dev use:
#   scripts/deploy_platform_proxy_hotfix.sh
#
# Useful overrides:
#   IMAGE_TAG=hotfix-platform-proxy-001 scripts/deploy_platform_proxy_hotfix.sh
#   SKIP_IMAGE_BUILD=1 IMAGE=hub.dfy.definesys.cn/ai-builder/apaas-builder:<tag> scripts/deploy_platform_proxy_hotfix.sh
#   APP_NAME=apaas-builder NGINX_CM=apaas-builder-nginx PUBLIC_URL=https://df-aigc.dfy.definesys.cn/ai-builder/login scripts/deploy_platform_proxy_hotfix.sh

set -euo pipefail

if [ -n "${REPO_ROOT:-}" ]; then
  REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
elif [ -n "${BASH_SOURCE:-}" ] && [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "./deploy/k8s/15-configmap-nginx.yaml" ] && [ -f "./deploy/docker/Dockerfile" ]; then
  REPO_ROOT="$(pwd)"
else
  printf "[fail] cannot locate repo root. Run from the apaas-builder-ai repo, or set REPO_ROOT=/path/to/apaas-builder-ai\n" >&2
  exit 1
fi
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$REPO_ROOT/deploy/k8s/dev.env}"

if [ -f "$DEPLOY_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$DEPLOY_ENV_FILE"
  set +a
fi

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder-dev}"
NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"

IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE="${IMAGE:-}"
PLATFORM="${PLATFORM:-linux/amd64}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
DEV_HOST="${DEV_HOST:-agent.dfy.definesys.cn}"
VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-https://${DEV_HOST}}"
PUBLIC_URL="${PUBLIC_URL:-https://${DEV_HOST}/ai-builder/login}"

BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
SKIP_IMAGE_BUILD="${SKIP_IMAGE_BUILD:-0}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"

c_red=$'\033[31m'
c_grn=$'\033[32m'
c_yel=$'\033[33m'
c_blu=$'\033[36m'
c_rst=$'\033[0m'

log() { printf "%s[platform-proxy-hotfix]%s %s\n" "$c_blu" "$c_rst" "$*"; }
ok() { printf "%s[ ok ]%s %s\n" "$c_grn" "$c_rst" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$c_yel" "$c_rst" "$*" >&2; }
die() { printf "%s[fail]%s %s\n" "$c_red" "$c_rst" "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Deploy platform-proxy iframe routing hotfix.

Run from the apaas-builder-ai repo:
  scripts/deploy_platform_proxy_hotfix.sh

Use an existing image and only apply config + rollout:
  SKIP_IMAGE_BUILD=1 IMAGE=hub.dfy.definesys.cn/ai-builder/apaas-builder:<tag> scripts/deploy_platform_proxy_hotfix.sh

If the script is copied or piped into bash, set REPO_ROOT:
  REPO_ROOT=/path/to/apaas-builder-ai scripts/deploy_platform_proxy_hotfix.sh

Common overrides:
  NAMESPACE=apaas-builder
  APP_NAME=apaas-builder-dev
  NGINX_CM=apaas-builder-dev-nginx
  PUBLIC_URL=https://agent.dfy.definesys.cn/ai-builder/login
USAGE
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

setup_kubeconfig() {
  if [ -n "${KUBECONFIG:-}" ]; then
    export KUBECONFIG
  elif [ -n "${HOME:-}" ] && [ -f "$HOME/.kube/dfy-host.yaml" ]; then
    export KUBECONFIG="$HOME/.kube/dfy-host.yaml"
  elif kubectl config current-context >/dev/null 2>&1; then
    :
  else
    die "kubectl has no context. Export KUBECONFIG or save it to ~/.kube/dfy-host.yaml"
  fi

  if [ -n "${KUBE_CONTEXT:-}" ]; then
    kubectl config use-context "$KUBE_CONTEXT" >/dev/null
  fi
  kubectl cluster-info >/dev/null
  ok "kubectl connected: $(kubectl config current-context 2>/dev/null || printf default)"
}

resolve_image() {
  if [ "$SKIP_IMAGE_BUILD" = "1" ]; then
    [ -n "$IMAGE" ] || die "SKIP_IMAGE_BUILD=1 requires IMAGE=<repo:tag>"
    return
  fi

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
    IMAGE_TAG="hotfix-platform-proxy-$(date +%Y%m%d-%H%M%S)-${sha}${dirty_suffix}"
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
  ok "image pushed: ${IMAGE}"
}

apply_nginx_config() {
  local tmp_conf
  tmp_conf="$(mktemp /tmp/apaas-builder-nginx-default.XXXXXX.conf)"
  sed '1,/default.conf: |/d; s/^    //' "$REPO_ROOT/deploy/k8s/15-configmap-nginx.yaml" > "$tmp_conf"

  log "apply nginx ConfigMap ${NAMESPACE}/${NGINX_CM}"
  kubectl -n "$NAMESPACE" create configmap "$NGINX_CM" \
    --from-file=default.conf="$tmp_conf" \
    --dry-run=client -o yaml | kubectl apply -f -
  rm -f "$tmp_conf"
}

patch_statefulset_image() {
  log "patch StatefulSet ${NAMESPACE}/${APP_NAME} image -> ${IMAGE}"
  local restarted_at patch
  restarted_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  patch="$(cat <<PATCH
{"spec":{"template":{"metadata":{"annotations":{"platform-proxy-hotfix/restartedAt":"${restarted_at}"}},"spec":{"initContainers":[{"name":"${DIST_INIT_CONTAINER}","image":"${IMAGE}"}],"containers":[{"name":"${BACKEND_CONTAINER}","image":"${IMAGE}"}]}}}}
PATCH
)"
  kubectl -n "$NAMESPACE" patch "statefulset/${APP_NAME}" --type=strategic -p "$patch"
}

rollout_and_verify() {
  log "wait for rollout"
  kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLL_TIMEOUT"

  local pod
  pod="$(kubectl -n "$NAMESPACE" get pod -l "app=${APP_NAME}" \
    -o jsonpath='{.items[0].metadata.name}')"
  [ -n "$pod" ] || die "no pod found for app=${APP_NAME}"

  log "verify nginx config in pod ${pod}"
  kubectl -n "$NAMESPACE" exec "$pod" -c web -- nginx -t

  log "verify public URL: ${PUBLIC_URL}"
  curl -k -sS -o /tmp/apaas-builder-hotfix-login.html \
    -w "HTTP %{http_code}\nURL %{url_effective}\nTYPE %{content_type}\nSIZE %{size_download}\n" \
    "$PUBLIC_URL"
}

main() {
  if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
  fi

  cd "$REPO_ROOT"
  need kubectl
  need curl
  if [ "$SKIP_IMAGE_BUILD" != "1" ]; then
    need docker
  fi

  setup_kubeconfig
  kubectl get namespace "$NAMESPACE" >/dev/null
  kubectl -n "$NAMESPACE" get statefulset "$APP_NAME" >/dev/null

  resolve_image
  build_and_push_image
  apply_nginx_config
  patch_statefulset_image
  rollout_and_verify

  ok "platform proxy hotfix deployed"
  printf "IMAGE=%s\n" "$IMAGE"
}

main "$@"
