#!/usr/bin/env bash
# Build the current online source and update only an existing Builder workload.
#
# First installation and any Service/Ingress/Secret/ConfigMap/PVC/workload-shape
# change belong to the separate bootstrap workflow. This entry point only changes
# the backend and dist initContainer image fields of an already-bound StatefulSet.

set -euo pipefail

GIT_REPO="${GIT_REPO:-https://github.com/Mars-hub404/apaas-builder-ai.git}"
GIT_BRANCH="${GIT_BRANCH:-}"
DEPLOY_TARGET="${DEPLOY_TARGET:-dev}"
NAMESPACE="${NAMESPACE:-apaas-builder}"
IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
CONTAINER_CLI="${CONTAINER_CLI:-docker}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE_TAG="${IMAGE_TAG:-}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PROVENANCE_FLOOR="49a4bef4"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_ADMIN_BASE="${VITE_ADMIN_BASE:-/ai-builder/admin/}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-/ai-builder/api}"
VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-}"
DEV_HOST="${DEV_HOST:-agent.dfy.definesys.cn}"
PROD_HOST="${PROD_HOST:-df-aigc.dfy.definesys.cn}"
TMP_PARENT="${TMP_PARENT:-/tmp}"

if [ "$DEPLOY_TARGET" = "main" ] || [ "$DEPLOY_TARGET" = "prod" ]; then
  GIT_BRANCH="${GIT_BRANCH:-main}"
  APP_NAME="${APP_NAME:-apaas-builder}"
  HOST="${HOST:-$PROD_HOST}"
  IMAGE_TAG_PREFIX="${IMAGE_TAG_PREFIX:-main}"
else
  GIT_BRANCH="${GIT_BRANCH:-dev}"
  APP_NAME="${APP_NAME:-apaas-builder-dev}"
  HOST="${HOST:-$DEV_HOST}"
  IMAGE_TAG_PREFIX="${IMAGE_TAG_PREFIX:-dev}"
fi

KUBE_LABEL_SELECTOR="${KUBE_LABEL_SELECTOR:-app=${APP_NAME}}"
KUBE_INGRESS_PATH="${KUBE_INGRESS_PATH:-/ai-builder}"
WORKDIR="${WORKDIR:-${TMP_PARENT}/apaas-builder-online-${DEPLOY_TARGET}-${GIT_BRANCH}}"
RELEASE_LOCK_NAME="${RELEASE_LOCK_NAME:-${APP_NAME}-release-lock}"
RELEASE_LOCK_OWNER="${RELEASE_LOCK_OWNER:-online-${USER:-unknown}-$$-$(date +%s)}"
PREVIOUS_BACKEND_IMAGE=""
PREVIOUS_DIST_INIT_IMAGE=""
VALIDATED_STATEFULSET_UID=""
VALIDATED_STATEFULSET_RESOURCE_VERSION=""
IMAGE=""
GIT_SHA=""
GIT_FULL_SHA=""
LOCK_ACQUIRED=0

log() { printf '[online-deploy] %s\n' "$*"; }
ok() { printf '[online-deploy][ok] %s\n' "$*"; }
warn() { printf '[online-deploy][warn] %s\n' "$*" >&2; }
die() { printf '[online-deploy][fail] %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

is_immutable_image_ref() {
  [[ "$1" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]
}

setup_kubeconfig() {
  if [ -n "${KUBE_CONTEXT:-}" ]; then
    kubectl config use-context "$KUBE_CONTEXT" >/dev/null
  fi
  kubectl cluster-info >/dev/null
  ok "kubectl connected: $(kubectl config current-context 2>/dev/null || printf default)"
}

clone_latest_code() {
  log "clone latest online code: ${GIT_REPO} branch=${GIT_BRANCH}"
  [ -n "$WORKDIR" ] && [ "$WORKDIR" != "/" ] || die "unsafe WORKDIR: ${WORKDIR}"
  rm -rf "$WORKDIR"
  git clone --branch "$GIT_BRANCH" "$GIT_REPO" "$WORKDIR"
  GIT_SHA="$(git -C "$WORKDIR" rev-parse --short HEAD)"
  GIT_FULL_SHA="$(git -C "$WORKDIR" rev-parse HEAD)"
  verify_source_provenance "$GIT_FULL_SHA"
  ok "checked out ${GIT_BRANCH}@${GIT_FULL_SHA}"
}

verify_source_provenance() {
  local revision="${1:-${GIT_FULL_SHA:-}}"
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] \
    || die "source revision is not a full lowercase Git SHA"
  git -C "$WORKDIR" merge-base --is-ancestor "$PROVENANCE_FLOOR" "$revision" \
    || die "source revision is below provenance floor or clone history is incomplete"
}

verify_docker_digest_capability() {
  "$CONTAINER_CLI" buildx version >/dev/null 2>&1 \
    && "$CONTAINER_CLI" buildx imagetools inspect --help >/dev/null 2>&1 \
    || die "Docker buildx imagetools is required to resolve the pushed image digest"
}

docker_login_if_requested() {
  if [ -n "${DOCKER_USERNAME:-}" ] && [ -n "${DOCKER_PASSWORD:-}" ]; then
    local registry="${IMAGE_REPO%%/*}"
    log "docker login: ${registry}"
    printf '%s' "$DOCKER_PASSWORD" \
      | "$CONTAINER_CLI" login "$registry" -u "$DOCKER_USERNAME" --password-stdin
  else
    warn "DOCKER_USERNAME/DOCKER_PASSWORD not set; assuming container CLI is already logged in"
  fi
}

push_podman_image_and_capture_digest() {
  local image_tag_ref="$1" digest_file digest
  digest_file="$(mktemp "${TMP_PARENT}/apaas-builder-push-digest.XXXXXX")"
  if ! "$CONTAINER_CLI" push --digestfile "$digest_file" "$image_tag_ref" >/dev/null; then
    rm -f "$digest_file"
    die "podman push failed: ${image_tag_ref}"
  fi
  digest="$(tr -d '[:space:]' <"$digest_file")"
  rm -f "$digest_file"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die "invalid Podman push digest"
  printf '%s\n' "$digest"
}

resolve_docker_pushed_image_digest() {
  local image_tag_ref="$1" digest
  digest="$("$CONTAINER_CLI" buildx imagetools inspect "$image_tag_ref" \
    --format '{{.Manifest.Digest}}')" \
    || die "unable to resolve pushed image digest: ${image_tag_ref}"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die "invalid pushed image digest"
  printf '%s\n' "$digest"
}

build_and_push_image() {
  local image_tag_ref image_digest cli_name build_push
  GIT_FULL_SHA="$(git -C "$WORKDIR" rev-parse HEAD)"
  [[ "$GIT_FULL_SHA" =~ ^[0-9a-f]{40}$ ]] || die "HEAD is not a full lowercase Git SHA"
  [ -n "$IMAGE_TAG" ] || IMAGE_TAG="${IMAGE_TAG_PREFIX}-$(date +%Y%m%d-%H%M%S)-${GIT_SHA}"
  IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"
  cli_name="$(basename "$CONTAINER_CLI")"
  case "$cli_name" in
    podman) build_push=0 ;;
    docker)
      verify_docker_digest_capability
      build_push=1
      ;;
    *) die "unsupported CONTAINER_CLI for immutable digest release: ${CONTAINER_CLI}" ;;
  esac
  REPO_ROOT="$WORKDIR" CONTAINER_CLI="$CONTAINER_CLI" IMAGE="$IMAGE" PLATFORM="$PLATFORM" \
    VITE_BASE_URL="$VITE_BASE_URL" VITE_ADMIN_BASE="$VITE_ADMIN_BASE" \
    VITE_API_BASE_URL="$VITE_API_BASE_URL" \
    VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-https://${HOST}/ai-builder}" PUSH="$build_push" \
    "$WORKDIR/scripts/build_builder_image.sh"
  image_tag_ref="$IMAGE"
  case "$cli_name" in
    podman) image_digest="$(push_podman_image_and_capture_digest "$image_tag_ref")" ;;
    docker) image_digest="$(resolve_docker_pushed_image_digest "$image_tag_ref")" ;;
  esac
  IMAGE="${IMAGE_REPO}@${image_digest}"
  ok "image pushed: ${IMAGE}"
}

helper_env() {
  BUILDER_ORIGIN="${BUILDER_ORIGIN:-https://${HOST}}" \
  DEPLOYED_REVISION="$GIT_FULL_SHA" \
  KUBE_NAMESPACE="$NAMESPACE" \
  KUBE_STATEFULSET="$APP_NAME" \
  KUBE_LABEL_SELECTOR="$KUBE_LABEL_SELECTOR" \
  KUBE_BACKEND_CONTAINER="${KUBE_BACKEND_CONTAINER:-apaas-builder}" \
  KUBE_DIST_INIT_CONTAINER="${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}" \
  KUBE_WEB_CONTAINER="${KUBE_WEB_CONTAINER:-web}" \
  KUBE_EXPECTED_HOST="$HOST" \
  KUBE_EXPECTED_ORIGIN="${KUBE_EXPECTED_ORIGIN:-https://${HOST}}" \
  KUBE_INGRESS="${KUBE_INGRESS:-$APP_NAME}" \
  KUBE_SERVICE="${KUBE_SERVICE:-$APP_NAME}" \
  KUBE_INGRESS_PATH="$KUBE_INGRESS_PATH" \
  "$@"
}

run_release_builder_prebuild_preflight() {
  log "verify existing workload before registry mutation"
  helper_env bash "$WORKDIR/scripts/verify_builder_tenant_url_smoke.sh" --online-prebuild
}

run_release_builder_preflight() {
  log "verify immutable image release preflight"
  helper_env env BUILDER_IMAGE="$IMAGE" \
    bash "$WORKDIR/scripts/verify_builder_tenant_url_smoke.sh" --online-preflight
}

run_release_builder_smoke() {
  log "run immutable digest and tenant URL release smoke"
  helper_env env BUILDER_IMAGE="$IMAGE" \
    bash "$WORKDIR/scripts/verify_builder_tenant_url_smoke.sh"
}

statefulset_image() {
  local kind="$1" container="$2"
  case "$kind" in
    backend)
      kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" \
        -o jsonpath="{range .spec.template.spec.containers[?(@.name==\"${container}\")]}{.image}{end}"
      ;;
    init)
      kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" \
        -o jsonpath="{range .spec.template.spec.initContainers[?(@.name==\"${container}\")]}{.image}{end}"
      ;;
    *) die "unknown image field" ;;
  esac
}

capture_previous_workload() {
  local identity

  if ! kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" >/dev/null; then
    warn "StatefulSet is not accessible: ${APP_NAME}; first installation requires bootstrap"
    return 1
  fi
  identity="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" \
    -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" || return 1
  read -r VALIDATED_STATEFULSET_UID VALIDATED_STATEFULSET_RESOURCE_VERSION <<<"$identity"
  [[ "$VALIDATED_STATEFULSET_UID" =~ ^[A-Za-z0-9.-]+$ ]] \
    && [[ "$VALIDATED_STATEFULSET_RESOURCE_VERSION" =~ ^[0-9]+$ ]] \
    || { warn "unable to capture StatefulSet UID/resourceVersion"; return 1; }
  PREVIOUS_BACKEND_IMAGE="$(statefulset_image backend "${KUBE_BACKEND_CONTAINER:-apaas-builder}")"
  PREVIOUS_DIST_INIT_IMAGE="$(statefulset_image init "${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}")"
  [ -n "$PREVIOUS_BACKEND_IMAGE" ] && [ -n "$PREVIOUS_DIST_INIT_IMAGE" ] \
    || { warn "unable to capture previous StatefulSet image refs"; return 1; }
  is_immutable_image_ref "$PREVIOUS_BACKEND_IMAGE" && is_immutable_image_ref "$PREVIOUS_DIST_INIT_IMAGE" \
    || { warn "previous StatefulSet image refs must be immutable digest references"; return 1; }
}

lock_value() {
  local field="$1"
  kubectl -n "$NAMESPACE" get "configmap/${RELEASE_LOCK_NAME}" -o "jsonpath={.data.${field}}"
}

verify_release_lock() {
  [ "$(lock_value owner)" = "$RELEASE_LOCK_OWNER" ] \
    || { warn "release lock owner changed; refusing mutation"; return 1; }
  [ "$(lock_value target_image)" = "$IMAGE" ] \
    || { warn "release lock target changed; refusing mutation"; return 1; }
}

acquire_release_lock() {
  if kubectl -n "$NAMESPACE" create configmap "$RELEASE_LOCK_NAME" \
    --from-literal="owner=${RELEASE_LOCK_OWNER}" \
    --from-literal="target_image=${IMAGE}" \
    --from-literal="acquired_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null; then
    LOCK_ACQUIRED=1
    return 0
  fi
  if kubectl -n "$NAMESPACE" get "configmap/${RELEASE_LOCK_NAME}" >/dev/null 2>&1; then
    die "release lock exists (${RELEASE_LOCK_NAME}); manual recovery is required"
  fi
  die "unable to acquire release lock: ${RELEASE_LOCK_NAME}"
}

persist_validated_baseline() {
  local patch

  verify_release_lock || return 1
  patch="$(printf '{"data":{"validated_statefulset_uid":"%s","validated_statefulset_resource_version":"%s","previous_backend_image":"%s","previous_init_image":"%s"}}' \
    "$VALIDATED_STATEFULSET_UID" "$VALIDATED_STATEFULSET_RESOURCE_VERSION" \
    "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE")"
  kubectl -n "$NAMESPACE" patch configmap "$RELEASE_LOCK_NAME" --type=merge --patch "$patch" >/dev/null
}

load_validated_baseline_from_lock() {
  PREVIOUS_BACKEND_IMAGE="$(lock_value previous_backend_image)"
  PREVIOUS_DIST_INIT_IMAGE="$(lock_value previous_init_image)"
  VALIDATED_STATEFULSET_UID="$(lock_value validated_statefulset_uid)"
  VALIDATED_STATEFULSET_RESOURCE_VERSION="$(lock_value validated_statefulset_resource_version)"
  is_immutable_image_ref "$PREVIOUS_BACKEND_IMAGE" \
    && is_immutable_image_ref "$PREVIOUS_DIST_INIT_IMAGE" \
    && [[ "$VALIDATED_STATEFULSET_UID" =~ ^[A-Za-z0-9.-]+$ ]] \
    && [[ "$VALIDATED_STATEFULSET_RESOURCE_VERSION" =~ ^[0-9]+$ ]]
}

validated_baseline_matches_current_workload() {
  local identity current_uid current_resource_version

  verify_release_lock || return 1
  load_validated_baseline_from_lock || return 1
  identity="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" \
    -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" || return 1
  read -r current_uid current_resource_version <<<"$identity"
  [ "$current_uid" = "$VALIDATED_STATEFULSET_UID" ] \
    && [ "$current_resource_version" = "$VALIDATED_STATEFULSET_RESOURCE_VERSION" ] \
    && template_matches "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE"
}

release_lock_if_owned() {
  verify_release_lock || return 1
  kubectl -n "$NAMESPACE" delete configmap "$RELEASE_LOCK_NAME" >/dev/null \
    || return 1
  LOCK_ACQUIRED=0
}

set_release_images() {
  kubectl -n "$NAMESPACE" set image "statefulset/${APP_NAME}" \
    "${KUBE_BACKEND_CONTAINER:-apaas-builder}=${1}" \
    "${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}=${2}"
}

template_matches() {
  [ "$(statefulset_image backend "${KUBE_BACKEND_CONTAINER:-apaas-builder}")" = "$1" ] \
    && [ "$(statefulset_image init "${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}")" = "$2" ]
}

verify_online_rollback() {
  local previous_backend_image="$1" previous_init_image="$2"
  ROLLBACK_BACKEND_IMAGE="$previous_backend_image" \
  ROLLBACK_DIST_INIT_IMAGE="$previous_init_image" \
  KUBE_NAMESPACE="$NAMESPACE" KUBE_STATEFULSET="$APP_NAME" KUBE_LABEL_SELECTOR="$KUBE_LABEL_SELECTOR" \
  KUBE_BACKEND_CONTAINER="${KUBE_BACKEND_CONTAINER:-apaas-builder}" \
  KUBE_DIST_INIT_CONTAINER="${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}" \
  bash "$WORKDIR/scripts/verify_builder_tenant_url_smoke.sh" --verify-rollback
}

recover_failed_release() {
  [ "$LOCK_ACQUIRED" = "1" ] || return 0
  verify_release_lock || return 1
  load_validated_baseline_from_lock || { warn "release lock baseline is invalid"; return 1; }
  local identity current_uid
  identity="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" -o jsonpath='{.metadata.uid}')" \
    || return 1
  current_uid="$identity"
  [ "$current_uid" = "$VALIDATED_STATEFULSET_UID" ] \
    || { warn "rollback CAS rejected because StatefulSet UID changed"; return 1; }
  if template_matches "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE"; then
    ok "release already uses the captured previous immutable images"
  elif template_matches "$IMAGE" "$IMAGE"; then
    if ! set_release_images "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE"; then
      warn "rollback set image failed"
      return 1
    fi
    if ! kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLL_TIMEOUT"; then
      warn "rollback rollout failed"
      return 1
    fi
    if ! verify_online_rollback "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE"; then
      warn "rollback workload verification failed"
      return 1
    fi
  else
    warn "rollback CAS rejected because StatefulSet no longer uses this release image"
    return 1
  fi
  release_lock_if_owned || { warn "rollback succeeded but lock release failed"; return 1; }
  ok "rolled back existing workload to previous immutable image refs"
}

fail_before_mutation() {
  local reason="$1"
  if ! release_lock_if_owned; then
    die "${reason}; release lock cleanup failed"
  fi
  die "$reason"
}

fail_with_recovery() {
  local reason="$1"
  if ! recover_failed_release; then
    die "${reason}; rollback also failed or CAS rejected"
  fi
  die "${reason}; rollback completed"
}

main() {
  need git
  need "$CONTAINER_CLI"
  need kubectl
  need mktemp
  setup_kubeconfig
  clone_latest_code
  # This strict existing-workload check happens before login/build/push.
  run_release_builder_prebuild_preflight
  docker_login_if_requested
  build_and_push_image
  run_release_builder_preflight
  acquire_release_lock
  if ! capture_previous_workload; then
    fail_before_mutation "unable to capture existing workload baseline"
  fi
  if ! persist_validated_baseline; then
    fail_before_mutation "unable to persist release lock baseline"
  fi
  if ! validated_baseline_matches_current_workload; then
    fail_before_mutation "StatefulSet changed after release lock acquisition; refusing image mutation"
  fi
  if ! set_release_images "$IMAGE" "$IMAGE"; then
    fail_with_recovery "image update failed for immutable image ${IMAGE}"
  fi
  if ! kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLL_TIMEOUT"; then
    fail_with_recovery "rollout failed for immutable image ${IMAGE}"
  fi
  if ! run_release_builder_smoke; then
    fail_with_recovery "release smoke failed for immutable image ${IMAGE}"
  fi
  release_lock_if_owned || die "release succeeded but lock release failed"
  ok "deployed existing StatefulSet ${APP_NAME}"
  ok "source ${GIT_BRANCH}@${GIT_FULL_SHA}"
  ok "image ${IMAGE}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
