#!/usr/bin/env bash
# Roll out the prebuilt main/prod image without rebuilding it.
#
# This script intentionally only updates Kubernetes workload image/config and
# waits for rollout. It does not delete databases or PVCs, so application data
# remains in place.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export REPO_ROOT
export SKIP_IMAGE_BUILD="${SKIP_IMAGE_BUILD:-1}"
export IMAGE="${IMAGE:-hub.dfy.definesys.cn/ai-builder/apaas-builder:main-20260607-c9b4c022}"
export NAMESPACE="${NAMESPACE:-apaas-builder}"
export APP_NAME="${APP_NAME:-apaas-builder}"
export NGINX_CM="${NGINX_CM:-apaas-builder-nginx}"
export PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"
export DEV_HOST="${DEV_HOST:-df-aigc.dfy.definesys.cn}"
export VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-https://df-aigc.dfy.definesys.cn}"

exec "$REPO_ROOT/scripts/deploy_platform_proxy_hotfix.sh" "$@"
