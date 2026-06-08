#!/usr/bin/env bash
# Rollout dev image (Image tag fixed by IMAGE/DEV_TAG).

set -euo pipefail

SCRIPT_PATH="$0"
if [ -n "${BASH_SOURCE:-}" ]; then
  SCRIPT_PATH="${BASH_SOURCE[0]}"
fi
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
DEV_TAG="${DEV_TAG:-}"
IMAGE="${IMAGE:-${IMAGE_REPO}${DEV_TAG:+:${DEV_TAG}}}"

if [ -z "$IMAGE" ] && [ -z "${DEV_TAG:-}" ]; then
  echo "need IMAGE or DEV_TAG, e.g. IMAGE=$IMAGE_REPO:dev-20260608-xxx or DEV_TAG=dev-..." >&2
  exit 1
fi

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder-dev}"
NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env-dev}"
DEV_MCP_API_KEYS="${DEV_MCP_API_KEYS:-dev-mcp-api-key-local}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://agent.dfy.definesys.cn/ai-builder/login}"
ADMIN_URL="${ADMIN_URL:-https://agent.dfy.definesys.cn/ai-builder/platform-admin}"
MCP_URL="${MCP_URL:-https://agent.dfy.definesys.cn/api/mcp/mcp}"

export NAMESPACE APP_NAME NGINX_CM IMAGE BACKEND_CONTAINER DIST_INIT_CONTAINER BACKEND_SECRET DEV_MCP_API_KEYS
export ROLL_TIMEOUT PUBLIC_URL ADMIN_URL MCP_URL

TARGET_SCRIPT="$SCRIPT_DIR/deploy_image_dev.sh"
if [ ! -r "$TARGET_SCRIPT" ]; then
  echo "target script not found or not executable: $TARGET_SCRIPT" >&2
  exit 1
fi

exec "$TARGET_SCRIPT"
