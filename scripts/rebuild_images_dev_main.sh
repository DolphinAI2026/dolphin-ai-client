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
CONTAINER_CLI="${CONTAINER_CLI:-docker}"
PLATFORM="${PLATFORM:-linux/amd64}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_ADMIN_BASE="${VITE_ADMIN_BASE:-/ai-builder/admin/}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-/ai-builder/api}"
DEV_MCP_PUBLIC_BASE="${DEV_MCP_PUBLIC_BASE:-https://agent.dfy.definesys.cn/ai-builder}"
MAIN_MCP_PUBLIC_BASE="${MAIN_MCP_PUBLIC_BASE:-https://df-aigc.dfy.definesys.cn/ai-builder}"

DATE_TAG="${DATE_TAG:-$(date +%Y%m%d)}"
GIT_SHA="${GIT_SHA:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
DEV_TAG="${DEV_TAG:-dev-${DATE_TAG}-${GIT_SHA}}"
MAIN_TAG="${MAIN_TAG:-main-${DATE_TAG}-${GIT_SHA}}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing command: $1" >&2; exit 1; }
}

build_image() {
  local tag="$1"
  local mcp_public="$2"
  local image="${IMAGE_REPO}:${tag}"

  echo "[build] ${image}"
  REPO_ROOT="$REPO_ROOT" \
  CONTAINER_CLI="$CONTAINER_CLI" \
  IMAGE="$image" \
  PLATFORM="$PLATFORM" \
  VITE_BASE_URL="$VITE_BASE_URL" \
  VITE_ADMIN_BASE="$VITE_ADMIN_BASE" \
  VITE_API_BASE_URL="$VITE_API_BASE_URL" \
  VITE_MCP_PUBLIC_BASE="$mcp_public" \
  PUSH=1 \
    "$REPO_ROOT/scripts/build_builder_image.sh"

  echo "[push] ${image}"
}

main() {
  need "$CONTAINER_CLI"
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
