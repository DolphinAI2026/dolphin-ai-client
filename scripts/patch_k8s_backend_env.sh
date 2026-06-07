#!/usr/bin/env bash
# Patch backend.env stored in a Kubernetes Secret and restart apaas-builder.
#
# Production example:
#   NAMESPACE=apaas-builder \
#   APP_NAME=apaas-builder \
#   BACKEND_SECRET=apaas-backend-env \
#   APAAS_BASE_URL=https://your-apaas.example.com/backend \
#   scripts/patch_k8s_backend_env.sh
#
# Dev example:
#   NAMESPACE=apaas-builder APP_NAME=apaas-builder-dev BACKEND_SECRET=apaas-backend-env-dev \
#   APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend \
#   scripts/patch_k8s_backend_env.sh

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env}"
SECRET_KEY="${SECRET_KEY:-backend.env}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-300s}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

require_env() {
  local key="$1"
  if [ -z "${!key:-}" ]; then
    echo "missing required env: ${key}" >&2
    exit 1
  fi
}

mask_value() {
  local key="$1"
  local value="$2"
  case "$key" in
    *PASSWORD*|*SECRET*|*TOKEN*|*KEY*|DATABASE_URL|MCP_API_KEYS)
      printf '<masked>'
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
}

upsert_env() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp="${file}.tmp"

  if grep -q "^${key}=" "$file"; then
    awk -v k="$key" -v v="$value" '
      BEGIN { replaced = 0 }
      $0 ~ "^" k "=" && replaced == 0 {
        print k "=" v
        replaced = 1
        next
      }
      $0 ~ "^" k "=" { next }
      { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    {
      printf '\n'
      printf '%s=%s\n' "$key" "$value"
    } >> "$file"
  fi
}

delete_env() {
  local file="$1"
  local key="$2"
  local tmp="${file}.tmp"

  awk -v k="$key" '$0 !~ "^" k "=" { print }' "$file" > "$tmp"
  mv "$tmp" "$file"
}

need kubectl
require_env APAAS_BASE_URL

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
env_file="$tmpdir/backend.env"

echo "[1/4] read Secret ${NAMESPACE}/${BACKEND_SECRET}:${SECRET_KEY}"
kubectl -n "$NAMESPACE" get secret "$BACKEND_SECRET" \
  -o "jsonpath={.data.${SECRET_KEY//./\\.}}" \
  | base64 -d > "$env_file"

echo "[2/4] patch backend env"
upsert_env "$env_file" APAAS_BASE_URL "$APAAS_BASE_URL"
delete_env "$env_file" APAAS_TENANT_ID

# Optional public URL values. Set them only when provided by the caller.
if [ -n "${AI_BUILDER_CHAT_DEEPLINK_BASE:-}" ]; then
  upsert_env "$env_file" AI_BUILDER_CHAT_DEEPLINK_BASE "$AI_BUILDER_CHAT_DEEPLINK_BASE"
fi
if [ -n "${APAAS_BUILDER_PUBLIC_URL:-}" ]; then
  upsert_env "$env_file" APAAS_BUILDER_PUBLIC_URL "$APAAS_BUILDER_PUBLIC_URL"
fi
if [ -n "${BUILDER_PUBLIC_URL:-}" ]; then
  upsert_env "$env_file" BUILDER_PUBLIC_URL "$BUILDER_PUBLIC_URL"
fi

echo "patched keys:"
for key in APAAS_BASE_URL AI_BUILDER_CHAT_DEEPLINK_BASE APAAS_BUILDER_PUBLIC_URL BUILDER_PUBLIC_URL; do
  if grep -q "^${key}=" "$env_file"; then
    value="$(grep "^${key}=" "$env_file" | tail -1 | cut -d= -f2-)"
    printf '  %s=%s\n' "$key" "$(mask_value "$key" "$value")"
  fi
done
echo "removed keys:"
echo "  APAAS_TENANT_ID"

echo "[3/4] apply Secret ${NAMESPACE}/${BACKEND_SECRET}"
kubectl -n "$NAMESPACE" create secret generic "$BACKEND_SECRET" \
  --from-file="${SECRET_KEY}=${env_file}" \
  --dry-run=client -o yaml \
  | kubectl apply -f -

echo "[4/4] restart StatefulSet ${NAMESPACE}/${APP_NAME}"
kubectl -n "$NAMESPACE" rollout restart "statefulset/${APP_NAME}"
kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLLOUT_TIMEOUT"

echo "done"
