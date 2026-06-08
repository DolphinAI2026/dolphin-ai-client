#!/usr/bin/env bash
# Rebuild and push both dev + main images.
#
# Examples:
#   scripts/rebuild_images_dev_main.sh
#   DEV_TAG=dev-20260608-mcp-hotfix MAIN_TAG=main-20260608-mcp-hotfix \
#     IMAGE_REPO=hub.dfy.definesys.cn/ai-builder/apaas-builder scripts/rebuild_images_dev_main.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
PLATFORM="${PLATFORM:-linux/amd64}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_ADMIN_BASE="${VITE_ADMIN_BASE:-/admin/}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-/ai-builder/api}"
DEV_MCP_PUBLIC_BASE="${DEV_MCP_PUBLIC_BASE:-https://agent.dfy.definesys.cn}"
MAIN_MCP_PUBLIC_BASE="${MAIN_MCP_PUBLIC_BASE:-https://df-aigc.dfy.definesys.cn}"

DATE_TAG="${DATE_TAG:-$(date +%Y%m%d)}"
GIT_SHA="${GIT_SHA:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
DEV_TAG="${DEV_TAG:-dev-${DATE_TAG}-${GIT_SHA}}"
MAIN_TAG="${MAIN_TAG:-main-${DATE_TAG}-${GIT_SHA}}"

CAN_BUILDX=0
if command -v docker >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
  CAN_BUILDX=1
fi

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing command: $1" >&2; exit 1; }
}

build_image() {
  local tag="$1"
  local mcp_public="$2"
  local image="${IMAGE_REPO}:${tag}"

  echo "[build] ${image}"

  if [ "$CAN_BUILDX" = "1" ]; then
    docker buildx build \
      --platform "$PLATFORM" \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}" \
      --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${mcp_public}" \
      -f "$REPO_ROOT/deploy/docker/Dockerfile" \
      -t "$image" \
      --push \
      "$REPO_ROOT"
  else
    docker build \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}" \
      --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${mcp_public}" \
      -f "$REPO_ROOT/deploy/docker/Dockerfile" \
      -t "$image" \
      "$REPO_ROOT"
    docker push "$image"
  fi

  echo "[push] ${image}"
}

main() {
  need docker
  need git

  echo "repository: $REPO_ROOT"
  echo "platform: $PLATFORM"
  echo "dev image: ${IMAGE_REPO}:${DEV_TAG}"
  echo "main image: ${IMAGE_REPO}:${MAIN_TAG}"

  build_image "$DEV_TAG" "$DEV_MCP_PUBLIC_BASE"
  build_image "$MAIN_TAG" "$MAIN_MCP_PUBLIC_BASE"

  echo "done"
  echo "dev:  ${IMAGE_REPO}:${DEV_TAG}"
  echo "main: ${IMAGE_REPO}:${MAIN_TAG}"
}

main "$@"
