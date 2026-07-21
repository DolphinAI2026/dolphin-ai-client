#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-${SCRIPT_DIR}/..}"

CONTAINER_CLI="${CONTAINER_CLI:-docker}"
IMAGE="${IMAGE:-apaas-builder:${IMAGE_TAG:-latest}}"
PLATFORM="${PLATFORM:-linux/amd64}"
PUSH="${PUSH:-0}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_ADMIN_BASE="${VITE_ADMIN_BASE:-/ai-builder/admin/}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-/ai-builder/api}"
VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-}"

NODE_IMAGE="${NODE_IMAGE:-node:20-bookworm-slim}"
JDK8_IMAGE="${JDK8_IMAGE:-eclipse-temurin:8-jdk-jammy}"
JDK17_IMAGE="${JDK17_IMAGE:-eclipse-temurin:17-jdk-jammy}"
MAVEN_IMAGE="${MAVEN_IMAGE:-maven:3.9.9-eclipse-temurin-17}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-slim-bookworm}"
DOCKER_CLI_IMAGE="${DOCKER_CLI_IMAGE:-docker:24.0.7-cli}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"

die() {
  printf '[build-builder-image][fail] %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

SNAPSHOT_DIR=""

cleanup() {
  if [ -n "$SNAPSHOT_DIR" ] && [ -d "$SNAPSHOT_DIR" ]; then
    rm -rf "$SNAPSHOT_DIR"
  fi
}

main() {
  local BUILD_SHA
  local -a build_args

  need git
  need tar
  need mktemp
  need "$CONTAINER_CLI"
  REPO_ROOT="$(cd "$REPO_ROOT" && pwd -P)" \
    || die "invalid REPO_ROOT: $REPO_ROOT"
  git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "REPO_ROOT is not a Git worktree: $REPO_ROOT"
  BUILD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
  [[ "$BUILD_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "HEAD is not a full lowercase Git SHA"
  case "$PUSH" in
    0|1) ;;
    *) die "PUSH must be 0 or 1" ;;
  esac

  SNAPSHOT_DIR="$(mktemp -d /tmp/apaas-builder-image.XXXXXX)"
  trap cleanup EXIT
  git -C "$REPO_ROOT" archive --format=tar "$BUILD_SHA" \
    | tar -xf - -C "$SNAPSHOT_DIR"
  [ -f "$SNAPSHOT_DIR/deploy/docker/Dockerfile" ] \
    || die "snapshot is missing deploy/docker/Dockerfile"

  build_args=(
    --platform "$PLATFORM"
    --build-arg "VITE_BASE_URL=${VITE_BASE_URL}"
    --build-arg "VITE_BUILD_SHA=${BUILD_SHA}"
    --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}"
    --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}"
    --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE}"
    --build-arg "NODE_IMAGE=${NODE_IMAGE}"
    --build-arg "JDK8_IMAGE=${JDK8_IMAGE}"
    --build-arg "JDK17_IMAGE=${JDK17_IMAGE}"
    --build-arg "MAVEN_IMAGE=${MAVEN_IMAGE}"
    --build-arg "PYTHON_IMAGE=${PYTHON_IMAGE}"
    --build-arg "DOCKER_CLI_IMAGE=${DOCKER_CLI_IMAGE}"
    --build-arg "NPM_REGISTRY=${NPM_REGISTRY}"
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}"
    -f "$SNAPSHOT_DIR/deploy/docker/Dockerfile"
    -t "$IMAGE"
  )

  printf '[build-builder-image] image=%s platform=%s sha=%s\n' \
    "$IMAGE" "$PLATFORM" "$BUILD_SHA"
  if [ "$PUSH" = "1" ] \
    && "$CONTAINER_CLI" buildx version >/dev/null 2>&1; then
    "$CONTAINER_CLI" buildx build \
      "${build_args[@]}" --push "$SNAPSHOT_DIR"
  else
    "$CONTAINER_CLI" build "${build_args[@]}" "$SNAPSHOT_DIR"
    if [ "$PUSH" = "1" ]; then
      "$CONTAINER_CLI" push "$IMAGE"
    fi
  fi
}

main "$@"
