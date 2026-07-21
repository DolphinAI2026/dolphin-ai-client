#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() {
  printf '[builder-release-smoke][fail] %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

require_env() {
  local name="$1"
  [ -n "${!name:-}" ] || die "missing required environment: ${name}"
}

normalize_digest() {
  local value digest
  value="$1"
  digest="$(printf '%s\n' "$value" | sed -nE 's#.*(@sha256:[0-9a-f]{64}).*#\1#p' | head -n 1)"
  [[ "$digest" =~ ^@sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$digest"
}

pod_is_ready() {
  local pod="$1" ready
  ready="$(kubectl -n "$KUBE_NAMESPACE" get pod "$pod" \
    -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}')"
  [ "$ready" = "True" ]
}

pod_status_image_id() {
  local pod="$1"
  kubectl -n "$KUBE_NAMESPACE" get pod "$pod" \
    -o jsonpath="{range .status.containerStatuses[?(@.name==\"${KUBE_BACKEND_CONTAINER}\")]}{.imageID}{end}"
}

pod_init_status_image_id() {
  local pod="$1"
  kubectl -n "$KUBE_NAMESPACE" get pod "$pod" \
    -o jsonpath="{range .status.initContainerStatuses[?(@.name==\"${KUBE_DIST_INIT_CONTAINER}\")]}{.imageID}{end}"
}

extract_build_sha() {
  node -e '
const html = require("fs").readFileSync(0, "utf8");
const matches = [...html.matchAll(
  /<meta\s+name=["\x27]builder-build-sha["\x27]\s+content=["\x27]([0-9a-f]{40})["\x27]\s*\/?>/g,
)].map((match) => match[1]);
if (matches.length !== 1) process.exit(1);
process.stdout.write(matches[0]);
'
}

verify_playwright_version() {
  local version
  [ -f "${ROOT_DIR}/node_modules/playwright/package.json" ] \
    || die "root Playwright is not installed; run npm ci"
  version="$(node -e 'process.stdout.write(require(process.argv[1]).version)' \
    "${ROOT_DIR}/node_modules/playwright/package.json")"
  [ "$version" = "1.61.1" ] \
    || die "root Playwright must be 1.61.1 (actual: ${version})"
}

verify_ready_pods() {
  local pod backend_image_id init_image_id backend_digest init_digest pod_html build_sha
  local -a pods

  mapfile -t pods < <(
    kubectl -n "$KUBE_NAMESPACE" get pods -l "$KUBE_POD_SELECTOR" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
  [ "${#pods[@]}" -gt 0 ] || die "no Pods found for selector: ${KUBE_POD_SELECTOR}"

  for pod in "${pods[@]}"; do
    [ -n "$pod" ] || continue
    pod_is_ready "$pod" || die "Pod is not Ready: ${pod}"

    backend_image_id="$(pod_status_image_id "$pod")"
    init_image_id="$(pod_init_status_image_id "$pod")"
    backend_digest="$(normalize_digest "$backend_image_id")" \
      || die "backend imageID has no digest for Pod: ${pod}"
    init_digest="$(normalize_digest "$init_image_id")" \
      || die "initContainer imageID has no digest for Pod: ${pod}"
    [ "$backend_digest" = "$EXPECTED_DIGEST" ] \
      || die "backend digest mismatch for Pod: ${pod}"
    [ "$init_digest" = "$EXPECTED_DIGEST" ] \
      || die "initContainer digest mismatch for Pod: ${pod}"

    pod_html="$(kubectl -n "$KUBE_NAMESPACE" exec "$pod" -c "$KUBE_WEB_CONTAINER" -- \
      wget -qO- http://127.0.0.1/ai-builder/)" \
      || die "unable to read web sidecar HTML for Pod: ${pod}"
    build_sha="$(printf '%s' "$pod_html" | extract_build_sha)" \
      || die "expected exactly one builder-build-sha meta tag for Pod: ${pod}"
    [ "$build_sha" = "$DEPLOYED_REVISION" ] \
      || die "web build SHA mismatch for Pod: ${pod}"

    printf '[builder-release-smoke][ok] pod=%s digest=%s build_sha=%s\n' \
      "$pod" "$EXPECTED_DIGEST" "$build_sha"
  done

  SMOKE_POD="${pods[0]}"
}

run_reconciliation() {
  kubectl -n "$KUBE_NAMESPACE" exec "$SMOKE_POD" -c "$KUBE_BACKEND_CONTAINER" -- \
    sh -lc 'cd /app/backend && python -m app.tenant_public_id reconcile --verify-only-after-write' \
    >/dev/null \
    || die "tenant public ID reconciliation failed"
  printf '[builder-release-smoke][ok] tenant public ID reconciliation verified\n'
}

run_browser_smoke() {
  (
    cd "$ROOT_DIR"
    BROWSER_CHANNEL=msedge \
    BUILDER_BASE_URL="$BUILDER_BASE_URL" \
    BUILDER_BUILD_SHA="$DEPLOYED_REVISION" \
    BUILDER_CURRENT_TENANT_UUID="$BUILDER_CURRENT_TENANT_UUID" \
    BUILDER_TARGET_TENANT_UUID="$BUILDER_TARGET_TENANT_UUID" \
    BUILDER_TARGET_TENANT_ID="$BUILDER_TARGET_TENANT_ID" \
    BUILDER_TARGET_C_TENANT_UUID="$BUILDER_TARGET_C_TENANT_UUID" \
    BUILDER_TARGET_C_TENANT_ID="$BUILDER_TARGET_C_TENANT_ID" \
    BUILDER_DISABLED_TENANT_UUID="$BUILDER_DISABLED_TENANT_UUID" \
    BUILDER_UNAUTHORIZED_TENANT_UUID="$BUILDER_UNAUTHORIZED_TENANT_UUID" \
    BUILDER_E2E_USERNAME="$BUILDER_E2E_USERNAME" \
    BUILDER_E2E_PASSWORD="$BUILDER_E2E_PASSWORD" \
    BUILDER_CODE_SESSION_REF="$BUILDER_CODE_SESSION_REF" \
    BUILDER_AGENT_SESSION_ID="$BUILDER_AGENT_SESSION_ID" \
    node tests/e2e/builder-tenant-url-public-uuid.spec.mjs
  ) || die "Edge tenant URL browser smoke failed"
}

main() {
  local name
  local required_envs=(
    BUILDER_IMAGE
    DEPLOYED_REVISION
    KUBE_NAMESPACE
    KUBE_POD_SELECTOR
    KUBE_BACKEND_CONTAINER
    KUBE_DIST_INIT_CONTAINER
    KUBE_WEB_CONTAINER
    BUILDER_BASE_URL
    BUILDER_CURRENT_TENANT_UUID
    BUILDER_TARGET_TENANT_UUID
    BUILDER_TARGET_TENANT_ID
    BUILDER_TARGET_C_TENANT_UUID
    BUILDER_TARGET_C_TENANT_ID
    BUILDER_DISABLED_TENANT_UUID
    BUILDER_UNAUTHORIZED_TENANT_UUID
    BUILDER_E2E_USERNAME
    BUILDER_E2E_PASSWORD
    BUILDER_CODE_SESSION_REF
    BUILDER_AGENT_SESSION_ID
  )

  need kubectl
  need node
  need sed
  for name in "${required_envs[@]}"; do
    require_env "$name"
  done
  [[ "$DEPLOYED_REVISION" =~ ^[0-9a-f]{40}$ ]] \
    || die "DEPLOYED_REVISION must be a full lowercase Git SHA"
  EXPECTED_DIGEST="$(normalize_digest "$BUILDER_IMAGE")" \
    || die "BUILDER_IMAGE must use an immutable sha256 digest"
  kubectl config current-context >/dev/null 2>&1 \
    || die "kubectl has no configured kubeconfig context"
  verify_playwright_version
  verify_ready_pods
  run_reconciliation
  run_browser_smoke
  printf '[builder-release-smoke][ok] release tenant URL smoke passed\n'
}

main "$@"
