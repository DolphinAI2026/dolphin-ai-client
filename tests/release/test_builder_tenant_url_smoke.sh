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
if [[ "$1" == "merge-base" && "$2" == "--is-ancestor" && "$3" == "49a4bef4" ]]; then
  exit 0
fi
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
    printf 'RELEASE_BROWSER_SMOKE=PASS\n'
    ;;
  *)
    printf 'unexpected fake node invocation: %s\n' "$*" >&2
    exit 64
    ;;
esac
EOF

  cat >"${FAKE_BIN}/kubectl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

args=" $* "
if [[ "$args" == *" config current-context "* ]]; then
  printf 'fake-context\n'
  exit 0
fi
if [[ "$args" == *" get statefulset ai-builder "* ]]; then
  if [[ "$args" != *" -o "* ]]; then
    printf 'statefulset/ai-builder\n'
  elif [[ "$args" == *"currentRevision"* || "$args" == *"updateRevision"* ]]; then
    printf '%s\n' "${FAKE_STS_REVISIONS:-rev-7 rev-7}"
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
    printf 'pod-a\npod-b\n'
  fi
  exit 0
fi
if [[ "$args" == *" get pod pod-a "* || "$args" == *" get pod pod-b "* ]]; then
  pod="pod-a"
  [[ "$args" == *" get pod pod-b "* ]] && pod="pod-b"
  if [[ "$args" == *"controller-revision-hash"* ]]; then
    printf 'rev-7\n'
  elif [[ "$args" == *"conditions"* ]]; then
    printf 'True\n'
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
  printf '%s\n' "${FAKE_LOG:-release completed without credentials}"
  exit 0
fi
printf 'unexpected fake kubectl command: %s\n' "$*" >&2
exit 64
EOF

  cat >"${FAKE_BIN}/podman" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "push" && "$2" == "--digestfile" ]]; then
  printf '%s\n' "${FAKE_PODMAN_DIGEST:-sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}" >"$3"
  printf 'pushed %s\n' "$4"
  exit 0
fi
printf 'unexpected fake podman command: %s\n' "$*" >&2
exit 64
EOF

  chmod 755 "${FAKE_BIN}/git" "${FAKE_BIN}/curl" "${FAKE_BIN}/node" \
    "${FAKE_BIN}/kubectl" "${FAKE_BIN}/podman"
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
}
[preflight, smoke].each do |job|
  expected.each { |key, value| abort "missing #{key} mapping" unless job.dig("variables", key) == value }
end
abort "wrong default selector" unless config.dig("variables", "BUILDER_K8S_LABEL_SELECTOR") == "app.kubernetes.io/name=ai-builder"
abort "wrong default web container" unless config.dig("variables", "BUILDER_K8S_WEB_CONTAINER") == "web"
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
puts "RELEASE_SPEC_CONTRACT=PASS"
RUBY
}

ci_metadata_script() {
  ruby -ryaml - "${ROOT_DIR}/.gitlab-ci.yml" <<'RUBY'
config = YAML.load_file(ARGV.fetch(0))
puts config.fetch("publish_release_metadata").fetch("script").join("\n")
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

run_fake_helper() {
  PATH="${FAKE_BIN}:$PATH" \
  BUILDER_ORIGIN="https://builder.example" \
  BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
  DEPLOYED_REVISION="$TEST_REVISION" \
  KUBE_NAMESPACE="release-ns" \
  KUBE_STATEFULSET="ai-builder" \
  KUBE_LABEL_SELECTOR="${1:-app.kubernetes.io/name=ai-builder}" \
  KUBE_BACKEND_CONTAINER="ai-builder" \
  KUBE_DIST_INIT_CONTAINER="copy-frontend-dist" \
  KUBE_WEB_CONTAINER="${2:-web}" \
  BUILDER_SMOKE_USERNAME="release-user" \
  BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD" \
  BUILDER_SMOKE_TENANT_NAME="Release Tenant" \
  BUILDER_SMOKE_CODE_SESSION_ID="session-1" \
  BUILDER_SMOKE_AGENT_ID="agent-1" \
  bash "${ROOT_DIR}/scripts/verify_builder_tenant_url_smoke.sh"
}

assert_fake_helper_contract() {
  run_fake_helper >/dev/null

  local output
  output="$(FAKE_STS_REVISIONS="rev-7 rev-8" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "StatefulSet revision mismatch"

  output="$(FAKE_POD_B_BACKEND_DIGEST="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "backend digest mismatch"

  output="$(FAKE_RECONCILE="scanned_count=2 filled_count=0 null_count=1 null_tenant_ids=9 conflict_tenant_ids= invalid_tenant_ids=" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "reconciliation null_count=1"

  output="$(FAKE_LOG="Authorization: Bearer token-canary" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=authorization"
  assert_not_contains "$output" "token-canary"

  output="$(FAKE_LOG="$TEST_PASSWORD" assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=smoke_password"

  output="$(assert_command_fails_without_secret run_fake_helper "wrong=selector")"
  assert_contains "$output" "no Pods found for selector"

  output="$(assert_command_fails_without_secret run_fake_helper "app.kubernetes.io/name=ai-builder" "wrong-web")"
  assert_contains "$output" "web container is not present"

  printf 'FAKE_KUBECTL_RELEASE_CONTRACT=PASS\n'
}

main() {
  write_fake_tools
  assert_ci_metadata_and_mapping
  assert_ci_metadata_flow
  assert_podman_digestfile
  assert_fake_helper_contract
  assert_release_spec_contract
  printf 'PASS: builder tenant URL release smoke contract\n'
}

main "$@"
