#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d -t builder-release-contract.XXXXXX)"
FAKE_BIN="${TMP_DIR}/bin"
TEST_PASSWORD="release-password-canary"
TEST_REVISION="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TEST_DIGEST="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local value="$1" expected="$2"
  [[ "$value" == *"$expected"* ]] || fail "expected ${expected}"
}

assert_not_contains() {
  local value="$1" expected="$2"
  [[ "$value" != *"$expected"* ]] || fail "unexpected ${expected}"
}

assert_command_fails_without_secret() {
  local output status
  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e
  [ "$status" -ne 0 ] || fail "command unexpectedly succeeded: $*"
  assert_not_contains "$output" "$TEST_PASSWORD"
  printf '%s\n' "$output"
}

write_fake_tools() {
  mkdir -p "$FAKE_BIN"

  cat >"${FAKE_BIN}/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "-C" ]]; then
  shift 2
fi
case "${1:-}" in
  merge-base)
    if [[ "${2:-}" == "--is-ancestor" && "${3:-}" == "49a4bef4" ]]; then
      [ "${FAKE_GIT_PROVENANCE_FAIL:-0}" = "1" ] && exit 1
      exit 0
    fi
    ;;
  rev-parse)
    [ "${2:-}" = "HEAD" ] && printf '%s\n' "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" && exit 0
    ;;
esac
printf 'unexpected fake git command\n' >&2
exit 64
EOF

  cat >"${FAKE_BIN}/curl" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '<meta name="builder-build-sha" content="${TEST_REVISION}">'
EOF

  cat >"${FAKE_BIN}/node" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -e)
    printf '1.61.1'
    ;;
  -)
    cat >/dev/null
    ;;
  *builder-tenant-url-release-smoke.spec.mjs)
    [ "${FAKE_BROWSER_FAIL:-0}" != "1" ] || exit 1
    [ -z "${FAKE_BROWSER_MARKER:-}" ] || : >"${FAKE_BROWSER_MARKER}"
    printf 'RELEASE_BROWSER_SMOKE=PASS\n'
    ;;
  *)
    printf 'unexpected fake node invocation: %s\n' "$*" >&2
    exit 64
    ;;
esac
EOF

  cat >"${FAKE_BIN}/grep" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ -n "${FAKE_GREP_LOG:-}" ]; then
  printf '%s\n' "$*" >>"${FAKE_GREP_LOG}"
fi
exec /usr/bin/grep "$@"
EOF

cat >"${FAKE_BIN}/kubectl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

args=" $* "
state_value() {
  local key="$1" line
  [ -n "${FAKE_KUBE_STATE:-}" ] || return 0
  [ -f "${FAKE_KUBE_STATE}" ] || return 0
  line="$(grep -E "^${key}=" "${FAKE_KUBE_STATE}" || true)"
  printf '%s' "${line#*=}"
}

set_state_value() {
  local key="$1" value="$2" tmp
  [ -n "${FAKE_KUBE_STATE:-}" ] || return 0
  tmp="${FAKE_KUBE_STATE}.tmp"
  if [ -f "${FAKE_KUBE_STATE}" ]; then
    grep -Ev "^${key}=" "${FAKE_KUBE_STATE}" >"${tmp}" || true
  else
    : >"${tmp}"
  fi
  printf '%s=%s\n' "$key" "$value" >>"${tmp}"
  mv "${tmp}" "${FAKE_KUBE_STATE}"
}

if [[ "$args" == *" auth can-i "* ]]; then
  printf '%s\n' "${FAKE_RBAC:-yes}"
  exit 0
fi
if [[ "$args" == *" config current-context "* ]]; then
  printf 'fake-context\n'
  exit 0
fi
if [[ "$args" == *" get pods,sts,svc,ingress,pvc "* ]]; then
  printf 'NAME\n'
  exit 0
fi
if [[ "$args" == *" get ingress ai-builder "* ]]; then
  if [ "${FAKE_INGRESS_ABSENT:-0}" = "1" ] || [ "$(state_value ingress_deleted)" = "1" ]; then
    printf 'Error from server (NotFound): ingresses.networking.k8s.io "ai-builder" not found\n' >&2
    exit 1
  fi
  printf '%s\n' "${FAKE_INGRESS_SERVICE:-ai-builder}"
  exit 0
fi
if [[ "$args" == *" get service ai-builder "* ]]; then
  if [ "${FAKE_SERVICE_ABSENT:-0}" = "1" ] || [ "$(state_value service_deleted)" = "1" ]; then
    printf 'Error from server (NotFound): services "ai-builder" not found\n' >&2
    exit 1
  fi
  printf '%s\n' "${FAKE_SERVICE_SELECTOR:-app.kubernetes.io/name=ai-builder}"
  exit 0
fi
if [[ "$args" == *" get statefulset ai-builder "* || "$args" == *" get statefulset/ai-builder "* ]]; then
  if [ "${FAKE_STS_ABSENT:-0}" = "1" ] || [ "$(state_value sts_deleted)" = "1" ]; then
    printf 'Error from server (NotFound): statefulsets.apps "ai-builder" not found\n' >&2
    exit 1
  fi
  if [[ "$args" != *" -o "* ]]; then
    printf 'statefulset/ai-builder\n'
  elif [[ "$args" == *"currentRevision"* || "$args" == *"updateRevision"* ]]; then
    printf '%s\n' "${FAKE_STS_REVISIONS:-rev-7 rev-7}"
  elif [[ "$args" == *"spec.template.spec.containers"* && "$args" == *"image"* ]]; then
    image="$(state_value backend_image)"
    printf '%s\n' "${image:-${FAKE_STS_BACKEND_IMAGE:-registry.example/ai-builder@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}}"
  elif [[ "$args" == *"spec.template.spec.initContainers"* && "$args" == *"image"* ]]; then
    image="$(state_value init_image)"
    printf '%s\n' "${image:-${FAKE_STS_INIT_IMAGE:-registry.example/ai-builder@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}}"
  elif [[ "$args" == *"containers"* ]]; then
    printf '%s\n' "${FAKE_CONTAINERS:-ai-builder web}"
  elif [[ "$args" == *"initContainers"* ]]; then
    printf '%s\n' "${FAKE_INIT_TOPOLOGY:-copy-frontend-dist}"
  else
    printf 'unexpected StatefulSet query\n' >&2
    exit 64
  fi
  exit 0
fi
if [[ "$args" == *" get pods "* && "$args" == *" -l "* ]]; then
  if [[ "$args" != *" ${FAKE_EXPECT_SELECTOR:-app.kubernetes.io/name=ai-builder} "* ]]; then
    printf '\n'
  else
    if [ "${FAKE_COLLISION:-0}" = "1" ]; then
      printf 'pod-a\npod-prod\n'
    else
      printf 'pod-a\npod-b\n'
    fi
  fi
  exit 0
fi
if [[ "$args" == *" get pod pod-a "* || "$args" == *" get pod pod-b "* || "$args" == *" get pod pod-prod "* ]]; then
  pod="pod-a"
  [[ "$args" == *" get pod pod-b "* ]] && pod="pod-b"
  [[ "$args" == *" get pod pod-prod "* ]] && pod="pod-prod"
  if [[ "$args" == *"controller-revision-hash"* ]]; then
    printf 'rev-7\n'
  elif [[ "$args" == *"ownerReferences"* ]]; then
    if [[ "$pod" == "pod-prod" ]]; then
      printf 'ai-builder-prod\n'
    else
      printf 'ai-builder\n'
    fi
  elif [[ "$args" == *"conditions"* ]]; then
    printf 'True\n'
  elif [[ "$args" == *"spec.containers"* && "$args" == *"image"* ]]; then
    image="$(state_value backend_image)"
    image="${image:-${FAKE_POD_BACKEND_IMAGE:-registry.example/ai-builder@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}}"
    printf '%s\n' "$image"
  elif [[ "$args" == *"spec.initContainers"* && "$args" == *"image"* ]]; then
    image="$(state_value init_image)"
    image="${image:-${FAKE_POD_INIT_IMAGE:-registry.example/ai-builder@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}}"
    printf '%s\n' "$image"
  elif [[ "$args" == *"containerStatuses"* ]]; then
    digest="${FAKE_BACKEND_DIGEST:-sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}"
    [[ "$pod" == "pod-b" && -n "${FAKE_POD_B_BACKEND_DIGEST:-}" ]] && digest="$FAKE_POD_B_BACKEND_DIGEST"
    printf 'containerd://registry.example/ai-builder@%s\n' "$digest"
  elif [[ "$args" == *"initContainerStatuses"* ]]; then
    digest="${FAKE_INIT_DIGEST:-sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}"
    printf 'containerd://registry.example/ai-builder@%s\n' "$digest"
  else
    printf 'unexpected Pod query\n' >&2
    exit 64
  fi
  exit 0
fi
if [[ "$args" == *" set image statefulset/ai-builder "* ]]; then
  backend_image=""
  init_image=""
  for argument in "$@"; do
    case "$argument" in
      ai-builder=*) backend_image="${argument#ai-builder=}" ;;
      apaas-builder=*) backend_image="${argument#apaas-builder=}" ;;
      copy-frontend-dist=*) init_image="${argument#copy-frontend-dist=}" ;;
    esac
  done
  [ -n "$backend_image" ] && [ -n "$init_image" ] || exit 64
  set_state_value backend_image "$backend_image"
  set_state_value init_image "$init_image"
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'set-image backend=%s init=%s\n' "$backend_image" "$init_image" >>"${FAKE_KUBE_LOG}"
  exit 0
fi
if [[ "$args" == *" rollout status statefulset/ai-builder "* ]]; then
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'rollout-status\n' >>"${FAKE_KUBE_LOG}"
  [ "${FAKE_ROLLBACK_ROLLOUT_FAIL:-0}" = "1" ] && exit 1
  exit 0
fi
if [[ "$args" == *" delete ingress ai-builder "* || "$args" == *" delete statefulset ai-builder "* || "$args" == *" delete service ai-builder "* || "$args" == *" delete service ai-builder-headless "* ]]; then
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'delete %s\n' "$*" >>"${FAKE_KUBE_LOG}"
  case "$args" in
    *" delete ingress ai-builder "*) set_state_value ingress_deleted 1 ;;
    *" delete statefulset ai-builder "*) set_state_value sts_deleted 1 ;;
    *" delete service ai-builder-headless "*) set_state_value headless_deleted 1 ;;
    *" delete service ai-builder "*) set_state_value service_deleted 1 ;;
  esac
  exit 0
fi
if [[ "$args" == *" exec "* ]]; then
  if [[ "$args" == *" wget -qO- http://127.0.0.1/ai-builder/ "* ]]; then
    printf '<meta name="builder-build-sha" content="%s">' "${FAKE_WEB_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}"
  elif [[ "$args" == *"tenant_public_id reconcile --verify-only-after-write"* ]]; then
    printf '%s\n' "${FAKE_RECONCILE:-scanned_count=2 filled_count=0 null_count=0 null_tenant_ids= conflict_tenant_ids= invalid_tenant_ids=}"
  else
    printf 'unexpected exec command\n' >&2
    exit 64
  fi
  exit 0
fi
if [[ "$args" == *" logs "* ]]; then
  if [ -n "${FAKE_BROWSER_MARKER:-}" ] && [ -e "${FAKE_BROWSER_MARKER}" ]; then
    printf '%s\n' "${FAKE_LOG_AFTER:-${FAKE_LOG:-release completed without credentials}}"
  else
    printf '%s\n' "${FAKE_LOG_BEFORE:-${FAKE_LOG:-release completed without credentials}}"
  fi
  exit 0
fi
printf 'unexpected fake kubectl command: %s\n' "$*" >&2
exit 64
EOF

  cat >"${FAKE_BIN}/podman" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "push" && "$2" == "--digestfile" ]]; then
  [ -z "${FAKE_SEQUENCE_LOG:-}" ] || printf 'podman %s\n' "$*" >>"${FAKE_SEQUENCE_LOG}"
  printf '%s\n' "${FAKE_PODMAN_DIGEST:-sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}" >"$3"
  printf 'pushed %s\n' "$4"
  exit 0
fi
printf 'unexpected fake podman command: %s\n' "$*" >&2
exit 64
EOF

cat >"${FAKE_BIN}/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "buildx" && "${2:-}" == "version" ]]; then
  [ -z "${FAKE_SEQUENCE_LOG:-}" ] || printf 'docker %s\n' "$*" >>"${FAKE_SEQUENCE_LOG}"
  [ "${FAKE_DOCKER_IMAGETOOLS:-0}" = "1" ]
  exit
fi
if [[ "${1:-}" == "buildx" && "${2:-}" == "imagetools" && "${3:-}" == "inspect" ]]; then
  [ -z "${FAKE_SEQUENCE_LOG:-}" ] || printf 'docker %s\n' "$*" >>"${FAKE_SEQUENCE_LOG}"
  [ "${FAKE_DOCKER_IMAGETOOLS:-0}" = "1" ] || exit 1
  if [[ "${4:-}" == "--help" ]]; then
    exit 0
  fi
  printf 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  exit 0
fi
printf 'unexpected fake docker command: %s\n' "$*" >&2
exit 64
EOF

  chmod 755 "${FAKE_BIN}/git" "${FAKE_BIN}/curl" "${FAKE_BIN}/node" \
    "${FAKE_BIN}/grep" "${FAKE_BIN}/kubectl" "${FAKE_BIN}/podman" "${FAKE_BIN}/docker"
}

assert_ci_metadata_and_mapping() {
  ruby -ryaml - "${ROOT_DIR}/.gitlab-ci.yml" <<'RUBY'
path = ARGV.fetch(0)
config = YAML.load_file(path)
abort "missing build_release_image" unless config["build_release_image"]
build = config.fetch("build_release_image")
build_script = build.fetch("script").join("\n")
abort "build job parses metadata directly" if build_script.include?("python3") || build_script.include?("jq")
abort "build metadata artifact missing" unless Array(build.dig("artifacts", "paths")).include?("build/metadata.json")

metadata = config.fetch("publish_release_metadata")
abort "metadata job must use configurable Python image" unless metadata.dig("image", "name") == "$BUILDER_METADATA_PYTHON_IMAGE"
abort "metadata job must need build artifact" unless metadata.fetch("needs").any? { |need| need["job"] == "build_release_image" && need["artifacts"] }
metadata_script = metadata.fetch("script").join("\n")
abort "metadata parser is not strict" unless metadata_script.include?("sha256:[0-9a-f]{64}")
abort "metadata dotenv missing deployed revision" unless metadata_script.include?("DEPLOYED_REVISION")

preflight = config.fetch("release_builder_preflight")
smoke = config.fetch("release_builder_browser_smoke")
expected = {
  "KUBE_NAMESPACE" => "$BUILDER_K8S_NAMESPACE",
  "KUBE_STATEFULSET" => "$BUILDER_K8S_STATEFULSET",
  "KUBE_BACKEND_CONTAINER" => "$BUILDER_K8S_BACKEND_CONTAINER",
  "KUBE_DIST_INIT_CONTAINER" => "$BUILDER_K8S_DIST_INIT_CONTAINER",
  "KUBE_LABEL_SELECTOR" => "$BUILDER_K8S_LABEL_SELECTOR",
  "KUBE_WEB_CONTAINER" => "$BUILDER_K8S_WEB_CONTAINER",
  "KUBE_EXPECTED_HOST" => "$BUILDER_K8S_EXPECTED_HOST",
  "KUBE_INGRESS" => "$BUILDER_K8S_INGRESS",
  "KUBE_SERVICE" => "$BUILDER_K8S_SERVICE",
  "KUBE_INGRESS_PATH" => "$BUILDER_K8S_INGRESS_PATH",
}
[preflight, smoke].each do |job|
  expected.each { |key, value| abort "missing #{key} mapping" unless job.dig("variables", key) == value }
end
abort "wrong default selector" unless config.dig("variables", "BUILDER_K8S_LABEL_SELECTOR") == "app.kubernetes.io/name=ai-builder"
abort "wrong default web container" unless config.dig("variables", "BUILDER_K8S_WEB_CONTAINER") == "web"
abort "wrong default expected host" unless config.dig("variables", "BUILDER_K8S_EXPECTED_HOST") == "om-demo.dfy.definesys.cn"
abort "wrong default ingress" unless config.dig("variables", "BUILDER_K8S_INGRESS") == "ai-builder"
abort "wrong default service" unless config.dig("variables", "BUILDER_K8S_SERVICE") == "ai-builder"
abort "wrong default ingress path" unless config.dig("variables", "BUILDER_K8S_INGRESS_PATH") == "/ai-builder"
abort "release must need preflight" unless config.fetch("release_and_update_server").fetch("needs").any? { |need| need["job"] == "release_builder_preflight" && need["artifacts"] }
abort "smoke must use release spec" unless smoke.fetch("script").join("\n").include?("verify_builder_tenant_url_smoke.sh")
puts "CI_METADATA_MAPPING=PASS"
RUBY
}

assert_release_spec_contract() {
  ruby - "${ROOT_DIR}/tests/e2e/builder-tenant-url-release-smoke.spec.mjs" <<'RUBY'
source = File.read(ARGV.fetch(0))
%w[
  BUILDER_ORIGIN
  DEPLOYED_REVISION
  BUILDER_IMAGE
  KUBE_NAMESPACE
  KUBE_LABEL_SELECTOR
  KUBE_BACKEND_CONTAINER
  KUBE_DIST_INIT_CONTAINER
  KUBE_WEB_CONTAINER
  BUILDER_SMOKE_USERNAME
  BUILDER_SMOKE_PASSWORD
  BUILDER_SMOKE_TENANT_NAME
  BUILDER_SMOKE_CODE_SESSION_ID
].each { |input| abort "release spec is missing #{input}" unless source.include?(input) }
%w[
  BUILDER_TARGET_TENANT_ID
  BUILDER_TARGET_C_TENANT_ID
  BUILDER_DISABLED_TENANT_UUID
  BUILDER_UNAUTHORIZED_TENANT_UUID
  DELAY_TENANT_ID
].each { |forbidden| abort "release spec uses local fixture input #{forbidden}" if source.include?(forbidden) }
%w[
  /auth/select-tenant
  /auth/switch-tenant
  Authorization
  /api/code/sessions/
  /api/code-runtime/
].each { |contract| abort "release spec is missing #{contract}" unless source.include?(contract) }
%w[
  newActivationAgentId
  newActivations.length, 1
  wrong configured agent
].each { |contract| abort "release spec does not bind activation exactly: #{contract}" unless source.include?(contract) }
puts "RELEASE_SPEC_CONTRACT=PASS"
RUBY
}

ci_metadata_script() {
  ruby -ryaml - "${ROOT_DIR}/.gitlab-ci.yml" <<'RUBY'
config = YAML.load_file(ARGV.fetch(0))
puts config.fetch("publish_release_metadata").fetch("script").join("\n")
RUBY
}

ci_job_script() {
  local job="$1"
  ruby -ryaml - "${ROOT_DIR}/.gitlab-ci.yml" "$job" <<'RUBY'
config = YAML.load_file(ARGV.fetch(0))
puts config.fetch(ARGV.fetch(1)).fetch("script").join("\n")
RUBY
}

assert_ci_metadata_flow() {
  local script metadata_dir output
  script="$(ci_metadata_script)"
  metadata_dir="${TMP_DIR}/metadata"
  mkdir -p "${metadata_dir}/build"
  printf '{"containerimage.digest":"%s"}\n' "$TEST_DIGEST" \
    >"${metadata_dir}/build/metadata.json"
  (
    cd "$metadata_dir"
    BUILDER_IMAGE_REPOSITORY="registry.example/ai-builder" \
    CI_COMMIT_SHA="$TEST_REVISION" \
      bash -c "$script"
  )
  output="$(<"${metadata_dir}/build/release.env")"
  assert_contains "$output" "BUILDER_IMAGE=registry.example/ai-builder@${TEST_DIGEST}"
  assert_contains "$output" "DEPLOYED_REVISION=${TEST_REVISION}"

  printf '{"containerimage.digest":"sha256:invalid"}\n' \
    >"${metadata_dir}/build/metadata.json"
  assert_command_fails_without_secret bash -c "cd '$metadata_dir' && BUILDER_IMAGE_REPOSITORY=registry.example/ai-builder CI_COMMIT_SHA=$TEST_REVISION bash -c \"\$0\"" "$script" \
    >/dev/null
  printf 'CI_METADATA_FLOW=PASS\n'
}

assert_podman_digestfile() {
  local digest
  digest="$(
    PATH="${FAKE_BIN}:$PATH" \
    CONTAINER_CLI="${FAKE_BIN}/podman" \
      bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        push_podman_image_and_capture_digest "registry.example/ai-builder:test"
      ' bash "$ROOT_DIR"
  )"
  [ "$digest" = "$TEST_DIGEST" ] || fail "Podman digestfile result mismatch"
  printf 'PODMAN_DIGESTFILE=PASS\n'
}

assert_online_build_cli_branches() {
  local workdir sequence wrapper_log output
  workdir="${TMP_DIR}/online-workdir"
  sequence="${TMP_DIR}/online-sequence.log"
  wrapper_log="${TMP_DIR}/online-wrapper.log"
  mkdir -p "${workdir}/scripts"
  cat >"${workdir}/scripts/build_builder_image.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'wrapper PUSH=%s\n' "$PUSH" >>"${FAKE_SEQUENCE_LOG}"
printf '%s\n' "$PUSH" >>"${FAKE_BUILD_WRAPPER_LOG}"
EOF
  chmod 755 "${workdir}/scripts/build_builder_image.sh"

  PATH="${FAKE_BIN}:$PATH" \
  WORKDIR="$workdir" \
  CONTAINER_CLI="${FAKE_BIN}/podman" \
  IMAGE_REPO="registry.example/ai-builder" \
  IMAGE_TAG="contract" \
  FAKE_SEQUENCE_LOG="$sequence" \
  FAKE_BUILD_WRAPPER_LOG="$wrapper_log" \
    bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      build_and_push_image
    ' bash "$ROOT_DIR" >/dev/null
  [ "$(<"$wrapper_log")" = "0" ] || fail "Podman wrapper did not use PUSH=0"
  [ "$(grep -c '^podman push --digestfile ' "$sequence")" = "1" ] \
    || fail "Podman did not perform exactly one digestfile push"
  grep -q '^wrapper PUSH=0$' "$sequence" || fail "Podman wrapper sequence is missing"

  : >"$sequence"
  : >"$wrapper_log"
  PATH="${FAKE_BIN}:$PATH" \
  WORKDIR="$workdir" \
  CONTAINER_CLI="${FAKE_BIN}/docker" \
  IMAGE_REPO="registry.example/ai-builder" \
  IMAGE_TAG="contract" \
  FAKE_DOCKER_IMAGETOOLS=1 \
  FAKE_SEQUENCE_LOG="$sequence" \
  FAKE_BUILD_WRAPPER_LOG="$wrapper_log" \
    bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      build_and_push_image
    ' bash "$ROOT_DIR" >/dev/null
  [ "$(<"$wrapper_log")" = "1" ] || fail "Docker wrapper did not use PUSH=1"
  [ "$(grep -n '^docker buildx version$' "$sequence" | cut -d: -f1)" \
    -lt "$(grep -n '^wrapper PUSH=1$' "$sequence" | cut -d: -f1)" ] \
    || fail "Docker capability was not checked before the wrapper build"

  : >"$sequence"
  : >"$wrapper_log"
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    WORKDIR="$workdir" \
    CONTAINER_CLI="${FAKE_BIN}/docker" \
    IMAGE_REPO="registry.example/ai-builder" \
    IMAGE_TAG="contract" \
    FAKE_DOCKER_IMAGETOOLS=0 \
    FAKE_SEQUENCE_LOG="$sequence" \
    FAKE_BUILD_WRAPPER_LOG="$wrapper_log" \
      assert_command_fails_without_secret bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        build_and_push_image
      ' bash "$ROOT_DIR"
  )"
  assert_contains "$output" "Docker buildx imagetools is required"
  [ ! -s "$wrapper_log" ] || fail "Docker wrapper ran without immutable digest capability"
  printf 'ONLINE_BUILD_CLI_BRANCHES=PASS\n'
}

assert_online_source_and_docker_preflight() {
  PATH="${FAKE_BIN}:$PATH" \
  FAKE_DOCKER_IMAGETOOLS=1 \
  CONTAINER_CLI="${FAKE_BIN}/docker" \
    bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      verify_source_provenance "$2"
      verify_docker_digest_capability
    ' bash "$ROOT_DIR" "$TEST_REVISION"

  local output
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    FAKE_DOCKER_IMAGETOOLS=0 \
    CONTAINER_CLI="${FAKE_BIN}/docker" \
      assert_command_fails_without_secret bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        verify_docker_digest_capability
      ' bash "$ROOT_DIR"
  )"
  assert_contains "$output" "Docker buildx imagetools is required"

  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    FAKE_GIT_PROVENANCE_FAIL=1 \
      assert_command_fails_without_secret bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        verify_source_provenance "$2"
      ' bash "$ROOT_DIR" "$TEST_REVISION"
  )"
  assert_contains "$output" "below provenance floor"
  printf 'ONLINE_SOURCE_DOCKER_PREFLIGHT=PASS\n'
}

run_fake_helper() {
  local mode="${1:-}"
  shift $(( $# > 0 ? 1 : 0 ))
  PATH="${FAKE_BIN}:$PATH" \
  BUILDER_ORIGIN="${BUILDER_ORIGIN:-https://builder.example}" \
  BUILDER_IMAGE="${BUILDER_IMAGE:-registry.example/ai-builder@${TEST_DIGEST}}" \
  DEPLOYED_REVISION="${DEPLOYED_REVISION:-$TEST_REVISION}" \
  KUBE_NAMESPACE="${KUBE_NAMESPACE:-release-ns}" \
  KUBE_STATEFULSET="${KUBE_STATEFULSET:-ai-builder}" \
  KUBE_LABEL_SELECTOR="${KUBE_LABEL_SELECTOR:-app.kubernetes.io/name=ai-builder}" \
  KUBE_BACKEND_CONTAINER="${KUBE_BACKEND_CONTAINER:-ai-builder}" \
  KUBE_DIST_INIT_CONTAINER="${KUBE_DIST_INIT_CONTAINER:-copy-frontend-dist}" \
  KUBE_WEB_CONTAINER="${KUBE_WEB_CONTAINER:-web}" \
  KUBE_EXPECTED_HOST="${KUBE_EXPECTED_HOST:-builder.example}" \
  KUBE_INGRESS="${KUBE_INGRESS:-ai-builder}" \
  KUBE_SERVICE="${KUBE_SERVICE:-ai-builder}" \
  KUBE_INGRESS_PATH="${KUBE_INGRESS_PATH:-/ai-builder}" \
  BUILDER_SMOKE_USERNAME="${BUILDER_SMOKE_USERNAME:-release-user}" \
  BUILDER_SMOKE_PASSWORD="${BUILDER_SMOKE_PASSWORD:-$TEST_PASSWORD}" \
  BUILDER_SMOKE_TENANT_NAME="${BUILDER_SMOKE_TENANT_NAME:-Release Tenant}" \
  BUILDER_SMOKE_CODE_SESSION_ID="${BUILDER_SMOKE_CODE_SESSION_ID:-session-1}" \
  BUILDER_SMOKE_AGENT_ID="${BUILDER_SMOKE_AGENT_ID:-agent-1}" \
  bash "${ROOT_DIR}/scripts/verify_builder_tenant_url_smoke.sh" "$mode"
}

assert_fake_helper_contract() {
  run_fake_helper >/dev/null

  local output
  FAKE_STS_BACKEND_IMAGE="registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
  FAKE_STS_INIT_IMAGE="registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    run_fake_helper --preflight >/dev/null

  output="$(FAKE_STS_REVISIONS="rev-7 rev-8" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "StatefulSet revision mismatch"

  output="$(FAKE_POD_B_BACKEND_DIGEST="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "backend digest mismatch"

  output="$(FAKE_STS_BACKEND_IMAGE="registry.example/ai-builder:mutable" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "StatefulSet backend image mismatch"

  output="$(FAKE_POD_BACKEND_IMAGE="registry.example/ai-builder:mutable" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "backend spec image mismatch"

  output="$(FAKE_COLLISION=1 assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "Pod is not owned by StatefulSet"

  output="$(FAKE_RECONCILE="scanned_count=2 filled_count=0 null_count=1 null_tenant_ids=9 conflict_tenant_ids= invalid_tenant_ids=" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "reconciliation null_count=1"

  output="$(FAKE_RECONCILE="scanned_count=2 filled_count=0 null_count=0 null_tenant_ids= conflict_tenant_ids=" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "missing reconciliation output key"

  output="$(FAKE_RECONCILE="scanned_count=2 filled_count=0 null_count=0 null_count=0 null_tenant_ids= conflict_tenant_ids= invalid_tenant_ids=" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "duplicate reconciliation output key"

  output="$(FAKE_RECONCILE=$'scanned_count=2 filled_count=0 null_count=0 null_tenant_ids= conflict_tenant_ids= invalid_tenant_ids=\ntrailing=1' assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "invalid reconciliation output"

  output="$(FAKE_LOG='{"Authorization":"Bearer token-canary"}' assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=authorization"
  assert_not_contains "$output" "token-canary"

  output="$(FAKE_LOG='{"Cookie":"session=canary"}' assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=cookie"

  output="$(FAKE_LOG='eyJhbGciOiJIUzI1NiJ9.e30.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO' assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=jwt_like"

  output="$(FAKE_LOG="$TEST_PASSWORD" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=smoke_password"

  output="$(KUBE_LABEL_SELECTOR="wrong=selector" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "Service selector mismatch"

  output="$(KUBE_WEB_CONTAINER="wrong-web" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "web container is not present"

  output="$(FAKE_STS_ABSENT=1 assert_command_fails_without_secret run_fake_helper --preflight)"
  assert_contains "$output" "StatefulSet is not accessible"

  FAKE_STS_ABSENT=1 run_fake_helper --online-preflight >/dev/null

  local grep_log
  grep_log="${TMP_DIR}/grep-argv.log"
  FAKE_GREP_LOG="$grep_log" run_fake_helper >/dev/null
  assert_not_contains "$(<"$grep_log")" "$TEST_PASSWORD"

  output="$(
    FAKE_BROWSER_MARKER="${TMP_DIR}/browser-done" \
    FAKE_LOG_AFTER='{"Authorization":"Bearer post-browser-canary"}' \
      assert_command_fails_without_secret run_fake_helper
  )"
  assert_contains "$output" "category=authorization"
  assert_not_contains "$output" "post-browser-canary"

  output="$(BUILDER_ORIGIN="https://staging.example" assert_command_fails_without_secret run_fake_helper --preflight)"
  assert_contains "$output" "origin host mismatch"

  output="$(FAKE_INGRESS_SERVICE="wrong-service" assert_command_fails_without_secret run_fake_helper --preflight)"
  assert_contains "$output" "Ingress backend service mismatch"

  output="$(FAKE_SERVICE_SELECTOR="app=wrong" assert_command_fails_without_secret run_fake_helper --preflight)"
  assert_contains "$output" "Service selector mismatch"

  printf 'FAKE_KUBECTL_RELEASE_CONTRACT=PASS\n'
}

assert_activation_observer_contract() {
  local output
  output="$(
    RELEASE_SMOKE_ACTIVATION_CONTRACT=1 \
    BUILDER_ORIGIN="https://builder.example" \
    DEPLOYED_REVISION="$TEST_REVISION" \
    BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
    KUBE_NAMESPACE="release-ns" \
    KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    KUBE_BACKEND_CONTAINER="ai-builder" \
    KUBE_DIST_INIT_CONTAINER="copy-frontend-dist" \
    KUBE_WEB_CONTAINER="web" \
    BUILDER_SMOKE_USERNAME="release-user" \
    BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD" \
    BUILDER_SMOKE_TENANT_NAME="Release Tenant" \
    BUILDER_SMOKE_CODE_SESSION_ID="session-1" \
    BUILDER_SMOKE_AGENT_ID="agent-1" \
      node "${ROOT_DIR}/tests/e2e/builder-tenant-url-release-smoke.spec.mjs"
  )"
  assert_contains "$output" "ACTIVATION_OBSERVER_CONTRACT=PASS"
  printf 'ACTIVATION_OBSERVER_CONTRACT=PASS\n'
}

assert_online_selector_contract() {
  local dev_selector prod_selector
  dev_selector="$(
    DEPLOY_TARGET=dev bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      printf "%s" "$KUBE_LABEL_SELECTOR"
    ' bash "$ROOT_DIR"
  )"
  prod_selector="$(
    DEPLOY_TARGET=prod bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      printf "%s" "$KUBE_LABEL_SELECTOR"
    ' bash "$ROOT_DIR"
  )"
  [ "$dev_selector" = "app=apaas-builder-dev" ] || fail "dev selector is not workload-specific"
  [ "$prod_selector" = "app=apaas-builder" ] || fail "prod selector is not workload-specific"
  [ "$dev_selector" != "$prod_selector" ] || fail "dev and prod selectors collide"
  printf 'ONLINE_SELECTOR_CONTRACT=PASS\n'
}

run_fake_online_recovery() {
  local state_file="$1" kube_log="$2" workload_exists="$3"
  PATH="${FAKE_BIN}:$PATH" \
  WORKDIR="${ROOT_DIR}" \
  NAMESPACE="release-ns" \
  APP_NAME="ai-builder" \
  HOST="builder.example" \
  BUILDER_ORIGIN="https://builder.example" \
  BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
  DEPLOYED_REVISION="$TEST_REVISION" \
  KUBE_NAMESPACE="release-ns" \
  KUBE_STATEFULSET="ai-builder" \
  KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
  KUBE_BACKEND_CONTAINER="ai-builder" \
  KUBE_DIST_INIT_CONTAINER="copy-frontend-dist" \
  KUBE_WEB_CONTAINER="web" \
  KUBE_EXPECTED_HOST="builder.example" \
  KUBE_INGRESS="ai-builder" \
  KUBE_SERVICE="ai-builder" \
  KUBE_INGRESS_PATH="/ai-builder" \
  BUILDER_SMOKE_USERNAME="release-user" \
  BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD" \
  BUILDER_SMOKE_TENANT_NAME="Release Tenant" \
  BUILDER_SMOKE_CODE_SESSION_ID="session-1" \
  RECOVERY_WORKLOAD_EXISTS="$workload_exists" \
  RECOVERY_BACKEND_IMAGE="registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
  RECOVERY_DIST_INIT_IMAGE="registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
  FAKE_KUBE_STATE="$state_file" \
  FAKE_KUBE_LOG="$kube_log" \
  FAKE_CONTAINERS="ai-builder apaas-builder web" \
    bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      PREVIOUS_WORKLOAD_EXISTS="${RECOVERY_WORKLOAD_EXISTS}"
      PREVIOUS_BACKEND_IMAGE="${RECOVERY_BACKEND_IMAGE}"
      PREVIOUS_DIST_INIT_IMAGE="${RECOVERY_DIST_INIT_IMAGE}"
      run_release_builder_smoke() { return 1; }
      if rollout_and_verify; then
        exit 99
      fi
      recover_failed_release
    ' bash "$ROOT_DIR"
}

assert_online_rollback_contract() {
  local state_file kube_log output
  state_file="${TMP_DIR}/online-recovery.state"
  kube_log="${TMP_DIR}/online-recovery.log"
  : >"$state_file"
  : >"$kube_log"

  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    NAMESPACE="release-ns" \
    APP_NAME="ai-builder" \
    FAKE_STS_BACKEND_IMAGE="registry.example/ai-builder:mutable" \
      assert_command_fails_without_secret bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        capture_previous_workload
      ' bash "$ROOT_DIR"
  )"
  assert_contains "$output" "previous StatefulSet image refs must be immutable"

  run_fake_online_recovery "$state_file" "$kube_log" 1
  assert_contains "$(<"$kube_log")" "set-image backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  assert_contains "$(<"$kube_log")" "rollout-status"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  assert_contains "$(<"$state_file")" "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"

  : >"$state_file"
  : >"$kube_log"
  output="$(
    FAKE_ROLLBACK_ROLLOUT_FAIL=1 \
      assert_command_fails_without_secret run_fake_online_recovery "$state_file" "$kube_log" 1
  )"
  assert_contains "$output" "rollback rollout failed"

  : >"$state_file"
  : >"$kube_log"
  run_fake_online_recovery "$state_file" "$kube_log" 0
  assert_contains "$(<"$kube_log")" "delete -n release-ns delete ingress ai-builder"
  assert_contains "$(<"$kube_log")" "delete -n release-ns delete statefulset ai-builder"
  assert_contains "$(<"$kube_log")" "delete -n release-ns delete service ai-builder"
  assert_contains "$(<"$state_file")" "ingress_deleted=1"
  assert_contains "$(<"$state_file")" "sts_deleted=1"
  assert_contains "$(<"$state_file")" "service_deleted=1"
  printf 'ONLINE_ROLLBACK_CONTRACT=PASS\n'
}

assert_ci_rollback_contract() {
  local job_dir state_file kube_log update_script browser_script output
  job_dir="${TMP_DIR}/ci-rollback"
  state_file="${TMP_DIR}/ci-rollback.state"
  kube_log="${TMP_DIR}/ci-rollback.log"
  update_script="$(ci_job_script release_and_update_server)"
  browser_script="$(ci_job_script release_builder_browser_smoke)"
  mkdir -p "${job_dir}/build"
  ln -s "${ROOT_DIR}/scripts" "${job_dir}/scripts"
  ln -s "${ROOT_DIR}/node_modules" "${job_dir}/node_modules"
  printf 'backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\ninit_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n' >"$state_file"
  : >"$kube_log"
  printf 'BUILDER_IMAGE=registry.example/ai-builder@%s\nDEPLOYED_REVISION=%s\n' \
    "$TEST_DIGEST" "$TEST_REVISION" >"${job_dir}/build/release.env"
  : >"${job_dir}/kubeconfig"

  (
    cd "$job_dir"
    PATH="${FAKE_BIN}:$PATH" \
    APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
    BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
    BUILDER_K8S_NAMESPACE="release-ns" \
    BUILDER_K8S_STATEFULSET="ai-builder" \
    BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
    BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      bash -c "$update_script"
  )
  assert_contains "$(<"${job_dir}/build/release.env")" "PREVIOUS_BACKEND_IMAGE=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  assert_contains "$(<"${job_dir}/build/release.env")" "PREVIOUS_DIST_INIT_IMAGE=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@${TEST_DIGEST}"

  output="$(
    (
      cd "$job_dir"
      set -a
      . build/release.env
      set +a
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_ORIGIN="https://builder.example" \
      KUBE_NAMESPACE="release-ns" \
      KUBE_STATEFULSET="ai-builder" \
      KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      KUBE_BACKEND_CONTAINER="ai-builder" \
      KUBE_DIST_INIT_CONTAINER="copy-frontend-dist" \
      KUBE_WEB_CONTAINER="web" \
      KUBE_EXPECTED_HOST="builder.example" \
      KUBE_INGRESS="ai-builder" \
      KUBE_SERVICE="ai-builder" \
      KUBE_INGRESS_PATH="/ai-builder" \
      BUILDER_SMOKE_USERNAME="release-user" \
      BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD" \
      BUILDER_SMOKE_TENANT_NAME="Release Tenant" \
      BUILDER_SMOKE_CODE_SESSION_ID="session-1" \
      BUILDER_ROLLOUT_TIMEOUT="30s" \
      FAKE_BROWSER_FAIL=1 \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c "$browser_script"
    )
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  assert_contains "$(<"$state_file")" "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  assert_contains "$(<"$kube_log")" "set-image backend=registry.example/ai-builder@${TEST_DIGEST}"
  assert_contains "$(<"$kube_log")" "set-image backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  printf 'CI_ROLLBACK_CONTRACT=PASS\n'
}

main() {
  write_fake_tools
  assert_fake_helper_contract
  assert_ci_metadata_and_mapping
  assert_ci_metadata_flow
  assert_podman_digestfile
  assert_online_build_cli_branches
  assert_online_source_and_docker_preflight
  assert_online_selector_contract
  assert_online_rollback_contract
  assert_ci_rollback_contract
  assert_release_spec_contract
  assert_activation_observer_contract
  printf 'PASS: builder tenant URL release smoke contract\n'
}

main "$@"
