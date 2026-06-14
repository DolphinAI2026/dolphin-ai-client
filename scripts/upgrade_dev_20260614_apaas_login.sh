#!/usr/bin/env bash
# Upgrade dev environment to the aPaaS login tenant-response fix image.
#
# Usage:
#   scripts/upgrade_dev_20260614_apaas_login.sh
#
# Optional overrides:
#   IMAGE=hub.dfy.definesys.cn/ai-builder/apaas-builder:dev-20260614-5a78b452 \
#   NAMESPACE=apaas-builder APP_NAME=apaas-builder-dev \
#   scripts/upgrade_dev_20260614_apaas_login.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export IMAGE="${IMAGE:-hub.dfy.definesys.cn/ai-builder/apaas-builder:dev-20260614-5a78b452}"
export NAMESPACE="${NAMESPACE:-apaas-builder}"
export APP_NAME="${APP_NAME:-apaas-builder-dev}"
export NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
export BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
export DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
export BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env-dev}"
export DEV_MCP_API_KEYS="${DEV_MCP_API_KEYS:-dev-mcp-api-key-local}"
export ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
export PUBLIC_URL="${PUBLIC_URL:-https://agent.dfy.definesys.cn/ai-builder/login}"
export ADMIN_URL="${ADMIN_URL:-https://agent.dfy.definesys.cn/ai-builder/platform-admin}"
export MCP_URL="${MCP_URL:-https://agent.dfy.definesys.cn/api/mcp/mcp}"

exec "$SCRIPT_DIR/deploy_image_dev.sh"
