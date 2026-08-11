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
WORKDIR_BASE="${WORKDIR:-${TMP_PARENT}/apaas-builder-online-${DEPLOY_TARGET}-${GIT_BRANCH}}"
WORKDIR="${WORKDIR:-}"
RELEASE_LOCK_NAME="${RELEASE_LOCK_NAME:-${APP_NAME}-release-lock}"
RELEASE_LOCK_OWNER="${RELEASE_LOCK_OWNER:-online-${USER:-unknown}-$$-$(date +%s)}"
PREVIOUS_BACKEND_IMAGE=""
PREVIOUS_DIST_INIT_IMAGE=""
VALIDATED_STATEFULSET_UID=""
VALIDATED_STATEFULSET_RESOURCE_VERSION=""
IMAGE=""
GIT_SHA=""
GIT_FULL_SHA=""
CLONED_GIT_FULL_SHA=""
LOCK_ACQUIRED=0
RELEASE_LOCK_UID=""
RELEASE_LOCK_RESOURCE_VERSION=""
LEASE_GENERATION=""
STATEFULSET_FENCE_KEY="builder.ai/release-generation"
STATEFULSET_FENCE_JSON_POINTER="/metadata/annotations/builder.ai~1release-generation"

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
  [ -n "$WORKDIR_BASE" ] && [ "$WORKDIR_BASE" != "/" ] || die "unsafe WORKDIR base: ${WORKDIR_BASE}"
  mkdir -p "$(dirname "$WORKDIR_BASE")"
  WORKDIR="$(mktemp -d "${WORKDIR_BASE}.XXXXXX")"
  git clone --branch "$GIT_BRANCH" "$GIT_REPO" "$WORKDIR"
  GIT_SHA="$(git -C "$WORKDIR" rev-parse --short HEAD)"
  GIT_FULL_SHA="$(git -C "$WORKDIR" rev-parse HEAD)"
  CLONED_GIT_FULL_SHA="$GIT_FULL_SHA"
  verify_source_provenance "$GIT_FULL_SHA"
  ok "checked out ${GIT_BRANCH}@${GIT_FULL_SHA}"
}

prepare_root_playwright_dependencies() {
  need npm
  log "install root Playwright dependencies from package-lock"
  (cd "$WORKDIR" && npm ci)
  (cd "$WORKDIR" && npm exec -- playwright install msedge)
  ok "root Playwright dependencies and msedge installed"
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
  [ -z "$CLONED_GIT_FULL_SHA" ] || [ "$GIT_FULL_SHA" = "$CLONED_GIT_FULL_SHA" ] \
    || die "source worktree changed after clone"
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
  log "verify target image frontend base and source revision"
  CONTAINER_CLI="$CONTAINER_CLI" \
    BUILDER_IMAGE="$IMAGE" \
    EXPECTED_BASE_URL="$VITE_BASE_URL" \
    EXPECTED_BUILD_SHA="$GIT_FULL_SHA" \
    bash "$WORKDIR/scripts/verify_builder_image_frontend_base.sh"
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

refresh_release_lock_identity() {
  local identity current_uid current_resource_version
  identity="$(kubectl -n "$NAMESPACE" get "configmap/${RELEASE_LOCK_NAME}" \
    -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" || return 1
  read -r current_uid current_resource_version <<<"$identity"
  [[ "$current_uid" =~ ^[A-Za-z0-9.-]+$ ]] \
    && [[ "$current_resource_version" =~ ^[0-9]+$ ]] \
    || { warn "release lock identity is invalid"; return 1; }
  if [ -n "$RELEASE_LOCK_UID" ] && [ "$current_uid" != "$RELEASE_LOCK_UID" ]; then
    warn "release lock identity changed; refusing mutation"
    return 1
  fi
  RELEASE_LOCK_UID="$current_uid"
  RELEASE_LOCK_RESOURCE_VERSION="$current_resource_version"
}

verify_release_lock() {
  refresh_release_lock_identity || return 1
  [ "$(lock_value owner)" = "$RELEASE_LOCK_OWNER" ] \
    || { warn "release lock owner changed; refusing mutation"; return 1; }
  [ "$(lock_value target_image)" = "$IMAGE" ] \
    || { warn "release lock target changed; refusing mutation"; return 1; }
  [ "$(lock_value state)" = "active" ] \
    || { warn "release lock is not active; refusing mutation"; return 1; }
}

update_release_lock_identity() {
  local identity="$1" patched_uid patched_resource_version
  read -r patched_uid patched_resource_version <<<"$identity"
  [ "$patched_uid" = "$RELEASE_LOCK_UID" ] \
    && [[ "$patched_resource_version" =~ ^[0-9]+$ ]] \
    || { warn "release lock patch returned unexpected identity"; return 1; }
  RELEASE_LOCK_RESOURCE_VERSION="$patched_resource_version"
}

acquire_release_lock() {
  local identity patch observed_uid observed_resource_version observed_state observed_owner observed_target
  LEASE_GENERATION="${RELEASE_LOCK_OWNER}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  if identity="$(kubectl -n "$NAMESPACE" create configmap "$RELEASE_LOCK_NAME" \
    --from-literal="owner=${RELEASE_LOCK_OWNER}" \
    --from-literal="target_image=${IMAGE}" \
    --from-literal="state=active" \
    --from-literal="lease_generation=${LEASE_GENERATION}" \
    --from-literal="baseline_generation=" \
    --from-literal="validated_statefulset_uid=" \
    --from-literal="validated_statefulset_resource_version=" \
    --from-literal="previous_backend_image=" \
    --from-literal="previous_init_image=" \
    --from-literal="acquired_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')"; then
    read -r RELEASE_LOCK_UID RELEASE_LOCK_RESOURCE_VERSION <<<"$identity"
    [[ "$RELEASE_LOCK_UID" =~ ^[A-Za-z0-9.-]+$ ]] \
      && [[ "$RELEASE_LOCK_RESOURCE_VERSION" =~ ^[0-9]+$ ]] \
      || die "release lock create did not return UID/resourceVersion"
    LOCK_ACQUIRED=1
    return 0
  fi
  identity="$(kubectl -n "$NAMESPACE" get "configmap/${RELEASE_LOCK_NAME}" \
    -o jsonpath='{.metadata.uid}{"|"}{.metadata.resourceVersion}{"|"}{.data.state}{"|"}{.data.owner}{"|"}{.data.target_image}')" \
    || die "unable to acquire release lock: ${RELEASE_LOCK_NAME}"
  IFS='|' read -r observed_uid observed_resource_version observed_state observed_owner observed_target <<<"$identity"
  [[ "$observed_uid" =~ ^[A-Za-z0-9.-]+$ ]] \
    && [[ "$observed_resource_version" =~ ^[0-9]+$ ]] \
    || die "release lock identity is invalid"
  [ "$observed_state" = "released" ] && [ -z "$observed_owner" ] && [ -z "$observed_target" ] \
    || die "release lock exists (${RELEASE_LOCK_NAME}); manual recovery is required"
  RELEASE_LOCK_UID="$observed_uid"
  RELEASE_LOCK_RESOURCE_VERSION="$observed_resource_version"
  patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"test","path":"/data/state","value":"released"},{"op":"test","path":"/data/owner","value":""},{"op":"test","path":"/data/target_image","value":""},{"op":"replace","path":"/data/owner","value":"%s"},{"op":"replace","path":"/data/target_image","value":"%s"},{"op":"replace","path":"/data/state","value":"active"},{"op":"replace","path":"/data/lease_generation","value":"%s"},{"op":"replace","path":"/data/baseline_generation","value":""},{"op":"replace","path":"/data/validated_statefulset_uid","value":""},{"op":"replace","path":"/data/validated_statefulset_resource_version","value":""},{"op":"replace","path":"/data/previous_backend_image","value":""},{"op":"replace","path":"/data/previous_init_image","value":""},{"op":"add","path":"/data/acquired_at","value":"%s"}]' \
    "$RELEASE_LOCK_UID" "$RELEASE_LOCK_RESOURCE_VERSION" "$RELEASE_LOCK_OWNER" "$IMAGE" "$LEASE_GENERATION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  identity="$(kubectl -n "$NAMESPACE" patch configmap "$RELEASE_LOCK_NAME" \
    --type=json --patch "$patch" -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" \
    || die "release lock changed before released lease reuse"
  update_release_lock_identity "$identity" || die "release lock reuse returned unexpected identity"
  LOCK_ACQUIRED=1
}

persist_validated_baseline() {
  local patch identity
  verify_release_lock || return 1
  patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"test","path":"/data/owner","value":"%s"},{"op":"test","path":"/data/target_image","value":"%s"},{"op":"test","path":"/data/state","value":"active"},{"op":"test","path":"/data/lease_generation","value":"%s"},{"op":"replace","path":"/data/validated_statefulset_uid","value":"%s"},{"op":"replace","path":"/data/validated_statefulset_resource_version","value":"%s"},{"op":"replace","path":"/data/previous_backend_image","value":"%s"},{"op":"replace","path":"/data/previous_init_image","value":"%s"},{"op":"replace","path":"/data/baseline_generation","value":"%s"}]' \
    "$RELEASE_LOCK_UID" "$RELEASE_LOCK_RESOURCE_VERSION" "$RELEASE_LOCK_OWNER" "$IMAGE" \
    "$LEASE_GENERATION" \
    "$VALIDATED_STATEFULSET_UID" "$VALIDATED_STATEFULSET_RESOURCE_VERSION" \
    "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE" "$LEASE_GENERATION")"
  identity="$(kubectl -n "$NAMESPACE" patch configmap "$RELEASE_LOCK_NAME" \
    --type=json --patch "$patch" -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" \
    || return 1
  update_release_lock_identity "$identity"
}

load_validated_baseline_from_lock() {
  PREVIOUS_BACKEND_IMAGE="$(lock_value previous_backend_image)"
  PREVIOUS_DIST_INIT_IMAGE="$(lock_value previous_init_image)"
  VALIDATED_STATEFULSET_UID="$(lock_value validated_statefulset_uid)"
  VALIDATED_STATEFULSET_RESOURCE_VERSION="$(lock_value validated_statefulset_resource_version)"
  [ "$(lock_value baseline_generation)" = "$(lock_value lease_generation)" ] \
    && [ -n "$(lock_value baseline_generation)" ] \
    && [ "$(lock_value lease_generation)" = "$LEASE_GENERATION" ] \
    || return 1
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
  local patch identity
  verify_release_lock || return 1
  patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"test","path":"/data/owner","value":"%s"},{"op":"test","path":"/data/target_image","value":"%s"},{"op":"test","path":"/data/state","value":"active"},{"op":"test","path":"/data/lease_generation","value":"%s"},{"op":"replace","path":"/data/owner","value":""},{"op":"replace","path":"/data/target_image","value":""},{"op":"replace","path":"/data/state","value":"released"},{"op":"replace","path":"/data/baseline_generation","value":""},{"op":"replace","path":"/data/validated_statefulset_uid","value":""},{"op":"replace","path":"/data/validated_statefulset_resource_version","value":""},{"op":"replace","path":"/data/previous_backend_image","value":""},{"op":"replace","path":"/data/previous_init_image","value":""},{"op":"add","path":"/data/released_by","value":"%s"}]' \
    "$RELEASE_LOCK_UID" "$RELEASE_LOCK_RESOURCE_VERSION" "$RELEASE_LOCK_OWNER" "$IMAGE" "$LEASE_GENERATION" "$RELEASE_LOCK_OWNER")"
  identity="$(kubectl -n "$NAMESPACE" patch configmap "$RELEASE_LOCK_NAME" \
    --type=json --patch "$patch" -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" \
    || return 1
  update_release_lock_identity "$identity" || return 1
  LOCK_ACQUIRED=0
}

set_release_images() {
  patch_statefulset_images_cas "$1" "$2" "$3" "$4"
}

template_matches() {
  [ "$(statefulset_image backend "${KUBE_BACKEND_CONTAINER:-apaas-builder}")" = "$1" ] \
    && [ "$(statefulset_image init "${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}")" = "$2" ]
}

find_container_index() {
  local kind="$1" name="$2" names index=0 found=""
  case "$kind" in
    backend) names="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"\n"}{end}')" ;;
    init) names="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" -o jsonpath='{range .spec.template.spec.initContainers[*]}{.name}{"\n"}{end}')" ;;
    *) return 1 ;;
  esac
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    if [ "$candidate" = "$name" ]; then
      [ -z "$found" ] || return 1
      found="$index"
    fi
    index=$((index + 1))
  done <<<"$names"
  [ -n "$found" ] || return 1
  printf '%s\n' "$found"
}

read_statefulset_fence_snapshot() {
  local backend_name="${KUBE_BACKEND_CONTAINER:-apaas-builder}" init_name="${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}"
  local identity annotation
  identity="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" || return 1
  read -r VALIDATED_STATEFULSET_UID VALIDATED_STATEFULSET_RESOURCE_VERSION <<<"$identity"
  [[ "$VALIDATED_STATEFULSET_UID" =~ ^[A-Za-z0-9.-]+$ ]] \
    && [[ "$VALIDATED_STATEFULSET_RESOURCE_VERSION" =~ ^[0-9]+$ ]] \
    || return 1
  BACKEND_INDEX="$(find_container_index backend "$backend_name")" || return 1
  INIT_INDEX="$(find_container_index init "$init_name")" || return 1
  STATEFULSET_ANNOTATIONS="$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" \
    -o go-template='{{if .metadata.annotations}}{{range $key, $value := .metadata.annotations}}{{$key}}={{$value}}{{"\n"}}{{end}}{{end}}')" || return 1
  STATEFULSET_FENCE_PRESENT=0
  STATEFULSET_FENCE_GENERATION=""
  while IFS= read -r annotation; do
    case "$annotation" in
      "${STATEFULSET_FENCE_KEY}="*)
        STATEFULSET_FENCE_PRESENT=1
        STATEFULSET_FENCE_GENERATION="${annotation#*=}"
        ;;
    esac
  done <<<"$STATEFULSET_ANNOTATIONS"
  SNAPSHOT_BACKEND_IMAGE="$(statefulset_image backend "$backend_name")"
  SNAPSHOT_INIT_IMAGE="$(statefulset_image init "$init_name")"
  [ -n "$SNAPSHOT_BACKEND_IMAGE" ] && [ -n "$SNAPSHOT_INIT_IMAGE" ]
}

fence_statefulset_for_generation() {
  local patch identity
  read_statefulset_fence_snapshot || return 1
  if [ "$STATEFULSET_FENCE_PRESENT" = "1" ]; then
    patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"test","path":"%s","value":"%s"},{"op":"replace","path":"%s","value":"%s"}]' "$VALIDATED_STATEFULSET_UID" "$VALIDATED_STATEFULSET_RESOURCE_VERSION" "$STATEFULSET_FENCE_JSON_POINTER" "$STATEFULSET_FENCE_GENERATION" "$STATEFULSET_FENCE_JSON_POINTER" "$LEASE_GENERATION")"
  elif [ -z "$STATEFULSET_ANNOTATIONS" ]; then
    patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"add","path":"/metadata/annotations","value":{"builder.ai/release-generation":"%s"}}]' "$VALIDATED_STATEFULSET_UID" "$VALIDATED_STATEFULSET_RESOURCE_VERSION" "$LEASE_GENERATION")"
  else
    patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"add","path":"%s","value":"%s"}]' "$VALIDATED_STATEFULSET_UID" "$VALIDATED_STATEFULSET_RESOURCE_VERSION" "$STATEFULSET_FENCE_JSON_POINTER" "$LEASE_GENERATION")"
  fi
  identity="$(kubectl -n "$NAMESPACE" patch "statefulset/${APP_NAME}" --type=json --patch "$patch" -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" || return 1
  read -r VALIDATED_STATEFULSET_UID VALIDATED_STATEFULSET_RESOURCE_VERSION <<<"$identity"
  STATEFULSET_FENCE_GENERATION="$LEASE_GENERATION"
}

patch_statefulset_images_cas() {
  local expected_backend="$1" expected_init="$2" next_backend="$3" next_init="$4" patch identity
  read_statefulset_fence_snapshot || return 1
  [ "$STATEFULSET_FENCE_GENERATION" = "$LEASE_GENERATION" ] \
    && [ "$SNAPSHOT_BACKEND_IMAGE" = "$expected_backend" ] \
    && [ "$SNAPSHOT_INIT_IMAGE" = "$expected_init" ] || return 1
  patch="$(printf '[{"op":"test","path":"/metadata/uid","value":"%s"},{"op":"test","path":"/metadata/resourceVersion","value":"%s"},{"op":"test","path":"%s","value":"%s"},{"op":"test","path":"/spec/template/spec/containers/%s/name","value":"%s"},{"op":"test","path":"/spec/template/spec/containers/%s/image","value":"%s"},{"op":"test","path":"/spec/template/spec/initContainers/%s/name","value":"%s"},{"op":"test","path":"/spec/template/spec/initContainers/%s/image","value":"%s"},{"op":"replace","path":"/spec/template/spec/containers/%s/image","value":"%s"},{"op":"replace","path":"/spec/template/spec/initContainers/%s/image","value":"%s"}]' "$VALIDATED_STATEFULSET_UID" "$VALIDATED_STATEFULSET_RESOURCE_VERSION" "$STATEFULSET_FENCE_JSON_POINTER" "$LEASE_GENERATION" "$BACKEND_INDEX" "${KUBE_BACKEND_CONTAINER:-apaas-builder}" "$BACKEND_INDEX" "$expected_backend" "$INIT_INDEX" "${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}" "$INIT_INDEX" "$expected_init" "$BACKEND_INDEX" "$next_backend" "$INIT_INDEX" "$next_init")"
  identity="$(kubectl -n "$NAMESPACE" patch "statefulset/${APP_NAME}" --type=json --patch "$patch" -o jsonpath='{.metadata.uid}{" "}{.metadata.resourceVersion}')" || return 1
  read -r VALIDATED_STATEFULSET_UID VALIDATED_STATEFULSET_RESOURCE_VERSION <<<"$identity"
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
  [ "$(kubectl -n "$NAMESPACE" get "statefulset/${APP_NAME}" \
    -o go-template='{{index .metadata.annotations "builder.ai/release-generation"}}')" = "$LEASE_GENERATION" ] \
    || { warn "rollback CAS rejected because StatefulSet release fence changed"; return 1; }
  if template_matches "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE"; then
    ok "release already uses the captured previous immutable images"
  elif template_matches "$IMAGE" "$IMAGE"; then
    if ! set_release_images "$IMAGE" "$IMAGE" "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE"; then
      warn "rollback image CAS patch failed"
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
  prepare_root_playwright_dependencies
  # This strict existing-workload check happens before login/build/push.
  run_release_builder_prebuild_preflight
  docker_login_if_requested
  build_and_push_image
  run_release_builder_preflight
  acquire_release_lock
  if ! fence_statefulset_for_generation; then
    fail_before_mutation "unable to fence StatefulSet for this lease generation"
  fi
  if ! capture_previous_workload; then
    fail_before_mutation "unable to capture existing workload baseline"
  fi
  if ! persist_validated_baseline; then
    fail_before_mutation "unable to persist release lock baseline"
  fi
  if ! validated_baseline_matches_current_workload; then
    fail_before_mutation "StatefulSet changed after release lock acquisition; refusing image mutation"
  fi
  if ! set_release_images "$PREVIOUS_BACKEND_IMAGE" "$PREVIOUS_DIST_INIT_IMAGE" "$IMAGE" "$IMAGE"; then
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
