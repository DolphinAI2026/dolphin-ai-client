#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROVENANCE_FLOOR="49a4bef4"
EXPECTED_DIGEST=""
SMOKE_POD=""
ROLLOUT_REVISION=""

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
  local value="$1" digest
  digest="$(printf '%s\n' "$value" | sed -nE 's#.*(@sha256:[0-9a-f]{64}).*#\1#p' | head -n 1)"
  [[ "$digest" =~ ^@sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$digest"
}

extract_build_sha() {
  local html="$1"
  local -a tags=()
  local tag

  mapfile -t tags < <(
    printf '%s' "$html" \
      | grep -oE '<meta[[:space:]]+name="builder-build-sha"[[:space:]]+content="[0-9a-f]{40}"[[:space:]]*/?>' \
      || true
  )
  [ "${#tags[@]}" -eq 1 ] || return 1
  tag="${tags[0]}"
  printf '%s\n' "$tag" \
    | sed -nE 's#.*content="([0-9a-f]{40})".*#\1#p'
}

statefulset_container_exists() {
  local kind="$1" name="$2" names
  case "$kind" in
    container)
      names="$(kubectl -n "$KUBE_NAMESPACE" get statefulset "$KUBE_STATEFULSET" \
        -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{" "}{end}')"
      ;;
    init)
      names="$(kubectl -n "$KUBE_NAMESPACE" get statefulset "$KUBE_STATEFULSET" \
        -o jsonpath='{range .spec.template.spec.initContainers[*]}{.name}{" "}{end}')"
      ;;
    *) die "unknown StatefulSet container kind: ${kind}" ;;
  esac
  [[ " ${names} " == *" ${name} "* ]]
}

verify_playwright_and_edge() {
  local version

  [ -f "${ROOT_DIR}/node_modules/playwright/package.json" ] \
    || die "root Playwright is not installed; run npm ci"
  version="$(node -e 'process.stdout.write(require(process.argv[1]).version)' \
    "${ROOT_DIR}/node_modules/playwright/package.json")"
  [ "$version" = "1.61.1" ] \
    || die "root Playwright must be 1.61.1 (actual: ${version})"
  node - <<'NODE' >/dev/null 2>&1 || die "msedge cannot launch through root Playwright"
const { chromium } = require("./node_modules/playwright");
(async () => {
  const browser = await chromium.launch({ channel: "msedge" });
  await browser.close();
})().catch(() => process.exit(1));
NODE
}

verify_inputs() {
  local name
  local required_envs=(
    BUILDER_ORIGIN
    DEPLOYED_REVISION
    BUILDER_IMAGE
    KUBE_NAMESPACE
    KUBE_STATEFULSET
    KUBE_LABEL_SELECTOR
    KUBE_BACKEND_CONTAINER
    KUBE_DIST_INIT_CONTAINER
    KUBE_WEB_CONTAINER
    BUILDER_SMOKE_USERNAME
    BUILDER_SMOKE_PASSWORD
    BUILDER_SMOKE_TENANT_NAME
    BUILDER_SMOKE_CODE_SESSION_ID
  )

  for name in "${required_envs[@]}"; do
    require_env "$name"
  done
  [[ "$BUILDER_ORIGIN" =~ ^https?://[^[:space:]]+$ ]] \
    || die "BUILDER_ORIGIN must be an http(s) origin"
  [[ "$DEPLOYED_REVISION" =~ ^[0-9a-f]{40}$ ]] \
    || die "DEPLOYED_REVISION must be a full lowercase Git SHA"
  EXPECTED_DIGEST="$(normalize_digest "$BUILDER_IMAGE")" \
    || die "BUILDER_IMAGE must use an immutable sha256 digest"
}

verify_cluster_preflight() {
  local pod_names

  kubectl config current-context >/dev/null 2>&1 \
    || die "kubectl has no configured kubeconfig context"
  kubectl -n "$KUBE_NAMESPACE" get statefulset "$KUBE_STATEFULSET" >/dev/null \
    || die "StatefulSet is not accessible: ${KUBE_STATEFULSET}"
  statefulset_container_exists container "$KUBE_BACKEND_CONTAINER" \
    || die "backend container is not present: ${KUBE_BACKEND_CONTAINER}"
  statefulset_container_exists init "$KUBE_DIST_INIT_CONTAINER" \
    || die "dist init container is not present: ${KUBE_DIST_INIT_CONTAINER}"
  statefulset_container_exists container "$KUBE_WEB_CONTAINER" \
    || die "web container is not present: ${KUBE_WEB_CONTAINER}"
  pod_names="$(kubectl -n "$KUBE_NAMESPACE" get pods -l "$KUBE_LABEL_SELECTOR" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"
  [ -n "$pod_names" ] || die "no Pods found for selector: ${KUBE_LABEL_SELECTOR}"
}

preflight() {
  need curl
  need git
  need grep
  need kubectl
  need node
  need sed
  verify_inputs
  verify_playwright_and_edge
  git -C "$ROOT_DIR" merge-base --is-ancestor "$PROVENANCE_FLOOR" "$DEPLOYED_REVISION" \
    || die "DEPLOYED_REVISION is below provenance floor"
  verify_cluster_preflight
  printf '[builder-release-smoke][ok] release preflight passed\n'
}

verify_public_build_sha() {
  local html build_sha

  html="$(curl -fsS "${BUILDER_ORIGIN%/}/ai-builder/")" \
    || die "unable to read public Builder HTML"
  build_sha="$(extract_build_sha "$html")" \
    || die "public Builder HTML must contain exactly one builder-build-sha"
  [ "$build_sha" = "$DEPLOYED_REVISION" ] \
    || die "public Builder build SHA mismatch"
  printf '[builder-release-smoke][ok] public build_sha=%s\n' "$build_sha"
}

verify_statefulset_revision() {
  local revisions current_revision update_revision

  revisions="$(kubectl -n "$KUBE_NAMESPACE" get statefulset "$KUBE_STATEFULSET" \
    -o jsonpath='{.status.currentRevision}{" "}{.status.updateRevision}')"
  read -r current_revision update_revision <<<"$revisions"
  [ -n "$current_revision" ] && [ -n "$update_revision" ] \
    || die "StatefulSet rollout revisions are empty"
  [ "$current_revision" = "$update_revision" ] \
    || die "StatefulSet revision mismatch"
  ROLLOUT_REVISION="$current_revision"
}

pod_is_ready() {
  local pod="$1" ready
  ready="$(kubectl -n "$KUBE_NAMESPACE" get pod "$pod" \
    -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}')"
  [ "$ready" = "True" ]
}

pod_controller_revision() {
  local pod="$1"
  kubectl -n "$KUBE_NAMESPACE" get pod "$pod" \
    -o jsonpath='{.metadata.labels.controller-revision-hash}'
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

verify_ready_pods() {
  local pod controller_revision backend_image_id init_image_id
  local backend_digest init_digest observed_digest pod_html build_sha
  local -a pods=()

  mapfile -t pods < <(
    kubectl -n "$KUBE_NAMESPACE" get pods -l "$KUBE_LABEL_SELECTOR" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
  [ "${#pods[@]}" -gt 0 ] || die "no Pods found for selector: ${KUBE_LABEL_SELECTOR}"

  for pod in "${pods[@]}"; do
    [ -n "$pod" ] || continue
    pod_is_ready "$pod" || die "Pod is not Ready: ${pod}"
    controller_revision="$(pod_controller_revision "$pod")"
    [ "$controller_revision" = "$ROLLOUT_REVISION" ] \
      || die "Pod controller revision mismatch: ${pod}"

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
    if [ -n "${observed_digest:-}" ] && [ "$backend_digest" != "$observed_digest" ]; then
      die "backend digest differs across Ready Pods: ${pod}"
    fi
    observed_digest="$backend_digest"

    pod_html="$(kubectl -n "$KUBE_NAMESPACE" exec "$pod" -c "$KUBE_WEB_CONTAINER" -- \
      wget -qO- http://127.0.0.1/ai-builder/)" \
      || die "unable to read web sidecar HTML for Pod: ${pod}"
    build_sha="$(extract_build_sha "$pod_html")" \
      || die "expected exactly one builder-build-sha meta tag for Pod: ${pod}"
    [ "$build_sha" = "$DEPLOYED_REVISION" ] \
      || die "web build SHA mismatch for Pod: ${pod}"

    printf '[builder-release-smoke][ok] pod=%s digest=%s build_sha=%s\n' \
      "$pod" "$backend_digest" "$build_sha"
  done

  SMOKE_POD="${pods[0]}"
}

verify_reconciliation_output() {
  local output="$1" part key value
  local scanned_count="" filled_count="" null_count=""
  local null_tenant_ids="" conflict_tenant_ids="" invalid_tenant_ids=""

  for part in $output; do
    key="${part%%=*}"
    value="${part#*=}"
    [ "$key" != "$part" ] || die "invalid reconciliation output"
    case "$key" in
      scanned_count) scanned_count="$value" ;;
      filled_count) filled_count="$value" ;;
      null_count) null_count="$value" ;;
      null_tenant_ids) null_tenant_ids="$value" ;;
      conflict_tenant_ids) conflict_tenant_ids="$value" ;;
      invalid_tenant_ids) invalid_tenant_ids="$value" ;;
      *) die "unexpected reconciliation output key" ;;
    esac
  done

  [[ "$scanned_count" =~ ^[0-9]+$ ]] || die "invalid reconciliation scanned_count"
  [[ "$filled_count" =~ ^[0-9]+$ ]] || die "invalid reconciliation filled_count"
  [[ "$null_count" =~ ^[0-9]+$ ]] || die "invalid reconciliation null_count"
  [ "$null_count" = "0" ] || die "reconciliation null_count=${null_count}"
  [ -z "$null_tenant_ids" ] || die "reconciliation null tenant IDs are present"
  [ -z "$conflict_tenant_ids" ] || die "reconciliation conflict tenant IDs are present"
  [ -z "$invalid_tenant_ids" ] || die "reconciliation invalid tenant IDs are present"
  printf '[builder-release-smoke][ok] reconciliation scanned=%s filled=%s null=0 conflict=0 invalid=0\n' \
    "$scanned_count" "$filled_count"
}

run_reconciliation() {
  local output
  output="$(kubectl -n "$KUBE_NAMESPACE" exec "$SMOKE_POD" -c "$KUBE_BACKEND_CONTAINER" -- \
    sh -lc 'cd /app/backend && python -m app.tenant_public_id reconcile --verify-only-after-write')" \
    || die "tenant public ID reconciliation failed"
  verify_reconciliation_output "$output"
}

scan_rollout_logs() {
  local pod logs category
  local -a pods=()

  mapfile -t pods < <(
    kubectl -n "$KUBE_NAMESPACE" get pods -l "$KUBE_LABEL_SELECTOR" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
  for pod in "${pods[@]}"; do
    [ -n "$pod" ] || continue
    logs="$(kubectl -n "$KUBE_NAMESPACE" logs "$pod" -c "$KUBE_BACKEND_CONTAINER" \
      --since="${KUBE_ROLLOUT_LOG_SINCE:-10m}")" \
      || die "unable to sample backend logs for Pod: ${pod}"
    category=""
    if printf '%s' "$logs" | grep -Fq -- "$BUILDER_SMOKE_PASSWORD"; then
      category="smoke_password"
    elif printf '%s' "$logs" | grep -Eiq 'authorization:[[:space:]]*(bearer|basic|token)'; then
      category="authorization"
    elif printf '%s' "$logs" | grep -Eq '[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'; then
      category="jwt_like"
    elif printf '%s' "$logs" | grep -Eiq '(^|[^A-Za-z])(cookie|set-cookie)[[:space:]]*:'; then
      category="cookie"
    fi
    [ -z "$category" ] || die "sensitive backend log category=${category} pod=${pod}"
  done
  printf '[builder-release-smoke][ok] backend log canary passed\n'
}

run_browser_smoke() {
  (
    cd "$ROOT_DIR"
    BROWSER_CHANNEL=msedge \
    BUILDER_ORIGIN="$BUILDER_ORIGIN" \
    DEPLOYED_REVISION="$DEPLOYED_REVISION" \
    BUILDER_IMAGE="$BUILDER_IMAGE" \
    KUBE_NAMESPACE="$KUBE_NAMESPACE" \
    KUBE_LABEL_SELECTOR="$KUBE_LABEL_SELECTOR" \
    KUBE_BACKEND_CONTAINER="$KUBE_BACKEND_CONTAINER" \
    KUBE_DIST_INIT_CONTAINER="$KUBE_DIST_INIT_CONTAINER" \
    KUBE_WEB_CONTAINER="$KUBE_WEB_CONTAINER" \
    BUILDER_SMOKE_USERNAME="$BUILDER_SMOKE_USERNAME" \
    BUILDER_SMOKE_PASSWORD="$BUILDER_SMOKE_PASSWORD" \
    BUILDER_SMOKE_TENANT_NAME="$BUILDER_SMOKE_TENANT_NAME" \
    BUILDER_SMOKE_CODE_SESSION_ID="$BUILDER_SMOKE_CODE_SESSION_ID" \
    BUILDER_SMOKE_AGENT_ID="${BUILDER_SMOKE_AGENT_ID:-}" \
    node tests/e2e/builder-tenant-url-release-smoke.spec.mjs
  ) || die "Edge tenant URL browser smoke failed"
}

main() {
  case "${1:-}" in
    --preflight)
      [ "$#" -eq 1 ] || die "usage: $0 [--preflight]"
      preflight
      ;;
    "")
      preflight
      verify_public_build_sha
      verify_statefulset_revision
      verify_ready_pods
      run_reconciliation
      scan_rollout_logs
      run_browser_smoke
      printf '[builder-release-smoke][ok] release tenant URL smoke passed\n'
      ;;
    *)
      die "usage: $0 [--preflight]"
      ;;
  esac
}

main "$@"
