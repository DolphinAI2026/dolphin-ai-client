#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTAINER_CLI="${CONTAINER_CLI:-docker}"
IMAGE="${IMAGE:-apaas-builder:${IMAGE_TAG:-latest}}"
PLATFORM="${PLATFORM:-linux/amd64}"
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

assert_clean_build_inputs() {
  (
    cd "$REPO_ROOT"
    build_inputs=(frontend backend admin-spa deploy/docker .dockerignore)
    git diff --quiet --cached -- "${build_inputs[@]}" &&
    git diff --quiet -- "${build_inputs[@]}" &&
    [ -z "$(git ls-files --others --exclude-standard -- "${build_inputs[@]}")" ]
  ) || die "Docker build inputs are dirty; commit them before building"
}

main() {
  local BUILD_SHA
  local -a build_args

  need git
  need "$CONTAINER_CLI"
  assert_clean_build_inputs
  BUILD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
  [[ "$BUILD_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "HEAD is not a full lowercase Git SHA"

  build_args=(
    build
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
    -f "$REPO_ROOT/deploy/docker/Dockerfile"
    -t "$IMAGE"
    "$REPO_ROOT"
  )

  printf '[build-builder-image] image=%s platform=%s sha=%s\n' \
    "$IMAGE" "$PLATFORM" "$BUILD_SHA"
  "$CONTAINER_CLI" "${build_args[@]}"
}

main "$@"
