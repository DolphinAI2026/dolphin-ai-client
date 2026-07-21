#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d -t builder-release-contract.XXXXXX)"
FAKE_BIN="${TMP_DIR}/bin"
REAL_NODE="$(command -v node)"
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

state_file_value() {
  local file="$1" key="$2" line
  line="$(/usr/bin/grep -E "^${key}=" "$file" || true)"
  printf '%s' "${line#*=}"
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

state_value() {
  local key="\$1" line
  [ -n "\${FAKE_KUBE_STATE:-}" ] || return 0
  [ -f "\${FAKE_KUBE_STATE}" ] || return 0
  line="\$(/usr/bin/grep -E "^\${key}=" "\${FAKE_KUBE_STATE}" || true)"
  printf '%s' "\${line#*=}"
}

set_state_value() {
  local key="\$1" value="\$2" tmp
  [ -n "\${FAKE_KUBE_STATE:-}" ] || return 0
  tmp="\${FAKE_KUBE_STATE}.tmp"
  if [ -f "\${FAKE_KUBE_STATE}" ]; then
    /usr/bin/grep -Ev "^\${key}=" "\${FAKE_KUBE_STATE}" >"\${tmp}" || true
  else
    : >"\${tmp}"
  fi
  printf '%s=%s\n' "\${key}" "\${value}" >>"\${tmp}"
  mv "\${tmp}" "\${FAKE_KUBE_STATE}"
}

replace_lock_with_owner_b() {
  set_state_value lock_owner "\${FAKE_REPLACEMENT_OWNER:-owner-b}"
  set_state_value lock_target "\${FAKE_REPLACEMENT_TARGET:-registry.example/ai-builder@sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee}"
  set_state_value lock_state "\${FAKE_REPLACEMENT_LOCK_STATE:-active}"
  set_state_value lock_uid "\${FAKE_REPLACEMENT_LOCK_UID:-lock-uid-b}"
  set_state_value lock_resource_version "\${FAKE_REPLACEMENT_LOCK_RESOURCE_VERSION:-1}"
  set_state_value lock_previous_backend "\${FAKE_REPLACEMENT_PREVIOUS_BACKEND:-}"
  set_state_value lock_previous_init "\${FAKE_REPLACEMENT_PREVIOUS_INIT:-}"
  set_state_value lock_sts_uid "\${FAKE_REPLACEMENT_STS_UID:-}"
  set_state_value lock_sts_resource_version "\${FAKE_REPLACEMENT_STS_RESOURCE_VERSION:-}"
  [ -z "\${FAKE_KUBE_LOG:-}" ] || printf 'lock-replace owner=%s\n' "\$(state_value lock_owner)" >>"\${FAKE_KUBE_LOG}"
}

if [[ " \$* " == *" -X DELETE "* && " \$* " == *"/configmaps/ai-builder-release-lock"* ]]; then
  if [ "\${FAKE_REPLACE_LOCK_ON_DELETE:-0}" = "1" ] \
    && [ "\$(state_value lock_replaced_on_delete)" != "1" ]; then
    set_state_value lock_replaced_on_delete 1
    replace_lock_with_owner_b
  fi
  body=""
  previous=""
  for argument in "\$@"; do
    if [ "\${previous}" = "--data" ] || [ "\${previous}" = "--data-raw" ]; then
      body="\${argument}"
      break
    fi
    previous="\${argument}"
  done
  expected_uid="\$(printf '%s' "\${body}" | /usr/bin/sed -nE 's/.*"uid":"([^"]+)".*/\1/p')"
  expected_rv="\$(printf '%s' "\${body}" | /usr/bin/sed -nE 's/.*"resourceVersion":"([^"]+)".*/\1/p')"
  [ -n "\${expected_uid}" ] && [ -n "\${expected_rv}" ] || exit 64
  [ "\$(state_value lock_uid)" = "\${expected_uid}" ] || exit 1
  [ "\$(state_value lock_resource_version)" = "\${expected_rv}" ] || exit 1
  set_state_value lock_owner ""
  set_state_value lock_target ""
  set_state_value lock_uid ""
  set_state_value lock_resource_version ""
  set_state_value lock_previous_backend ""
  set_state_value lock_previous_init ""
  set_state_value lock_sts_uid ""
  set_state_value lock_sts_resource_version ""
  [ -z "\${FAKE_KUBE_LOG:-}" ] || printf 'lock-delete-cas\n' >>"\${FAKE_KUBE_LOG}"
  exit 0
fi

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
    script="$(cat)"
    if [[ "$script" == *"KUBE_EXPECTED_ORIGIN"* ]]; then
      printf '%s' "$script" | "$FAKE_REAL_NODE" -
    fi
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

state_has_key() {
  local key="$1"
  [ -n "${FAKE_KUBE_STATE:-}" ] && [ -f "${FAKE_KUBE_STATE}" ] \
    && grep -Eq "^${key}=" "${FAKE_KUBE_STATE}"
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

json_patch_rows() {
  /usr/bin/python3 - "$1" <<'PY'
import base64
import json
import sys

for operation in json.loads(sys.argv[1]):
    encoded = base64.b64encode(
        json.dumps(operation.get("value"), separators=(",", ":")).encode()
    ).decode()
    print(f'{operation["op"]}\t{operation["path"]}\t{encoded}')
PY
}

json_patch_value() {
  /usr/bin/python3 - "$1" <<'PY'
import base64
import json
import sys

value = json.loads(base64.b64decode(sys.argv[1]))
if isinstance(value, str):
    print(value, end="")
else:
    print(json.dumps(value, separators=(",", ":")), end="")
PY
}

lock_state_key() {
  case "$1" in
    /metadata/uid) printf 'lock_uid' ;;
    /metadata/resourceVersion) printf 'lock_resource_version' ;;
    /data/owner) printf 'lock_owner' ;;
    /data/target_image) printf 'lock_target' ;;
    /data/state) printf 'lock_state' ;;
    /data/lease_generation) printf 'lock_generation' ;;
    /data/baseline_generation) printf 'lock_baseline_generation' ;;
    /data/validated_statefulset_uid) printf 'lock_sts_uid' ;;
    /data/validated_statefulset_resource_version) printf 'lock_sts_resource_version' ;;
    /data/previous_backend_image) printf 'lock_previous_backend' ;;
    /data/previous_init_image) printf 'lock_previous_init' ;;
    /data/acquired_at) printf 'lock_acquired_at' ;;
    /data/released_by) printf 'lock_released_by' ;;
    *) return 1 ;;
  esac
}

statefulset_uid() {
  local value
  value="$(state_value sts_uid)"
  printf '%s' "${value:-${FAKE_STS_UID:-sts-uid-1}}"
}

statefulset_resource_version() {
  local value
  value="$(state_value sts_resource_version)"
  printf '%s' "${value:-1}"
}

statefulset_annotations_present() {
  if state_has_key sts_annotations_present; then
    [ "$(state_value sts_annotations_present)" = "1" ]
  else
    return 0
  fi
}

statefulset_other_annotation() {
  local value
  if state_has_key sts_other_annotation; then
    value="$(state_value sts_other_annotation)"
  else
    value="keep"
  fi
  printf '%s' "$value"
}

statefulset_fence_present() {
  state_has_key sts_fence_present && [ "$(state_value sts_fence_present)" = "1" ]
}

container_name_at() {
  printf '%s\n' "${FAKE_CONTAINERS:-ai-builder web}" | tr ' ' '\n' | sed -n "$(( $1 + 1 ))p"
}

init_container_name_at() {
  printf '%s\n' "${FAKE_INIT_TOPOLOGY:-copy-frontend-dist}" | tr ' ' '\n' | sed -n "$(( $1 + 1 ))p"
}

statefulset_path_exists() {
  local path="$1" index
  case "$path" in
    /metadata/uid|/metadata/resourceVersion) return 0 ;;
    /metadata/annotations) statefulset_annotations_present ;;
    /metadata/annotations/builder.ai~1release-generation) statefulset_fence_present ;;
    /spec/template/spec/containers/*/name|/spec/template/spec/containers/*/image)
      index="${path#/spec/template/spec/containers/}"
      index="${index%%/*}"
      [ -n "$(container_name_at "$index")" ]
      ;;
    /spec/template/spec/initContainers/*/name|/spec/template/spec/initContainers/*/image)
      index="${path#/spec/template/spec/initContainers/}"
      index="${index%%/*}"
      [ -n "$(init_container_name_at "$index")" ]
      ;;
    *) return 1 ;;
  esac
}

statefulset_path_value() {
  local path="$1" index name
  case "$path" in
    /metadata/uid) statefulset_uid ;;
    /metadata/resourceVersion) statefulset_resource_version ;;
    /metadata/annotations/builder.ai~1release-generation) state_value sts_fence_generation ;;
    /spec/template/spec/containers/*/name)
      index="${path#/spec/template/spec/containers/}"
      container_name_at "${index%%/*}"
      ;;
    /spec/template/spec/containers/*/image)
      index="${path#/spec/template/spec/containers/}"
      name="$(container_name_at "${index%%/*}")"
      case "$name" in
        ai-builder|apaas-builder)
          printf '%s' "$(state_value backend_image)"
          ;;
        *) printf '%s' "${FAKE_WEB_IMAGE:-registry.example/web@sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff}" ;;
      esac
      ;;
    /spec/template/spec/initContainers/*/name)
      index="${path#/spec/template/spec/initContainers/}"
      init_container_name_at "${index%%/*}"
      ;;
    /spec/template/spec/initContainers/*/image)
      index="${path#/spec/template/spec/initContainers/}"
      name="$(init_container_name_at "${index%%/*}")"
      [ "$name" = "copy-frontend-dist" ] || return 1
      printf '%s' "$(state_value init_image)"
      ;;
    *) return 1 ;;
  esac
}

replace_lock_with_owner_b() {
  set_state_value lock_owner "${FAKE_REPLACEMENT_OWNER:-owner-b}"
  set_state_value lock_target "${FAKE_REPLACEMENT_TARGET:-registry.example/ai-builder@sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee}"
  set_state_value lock_state "${FAKE_REPLACEMENT_LOCK_STATE:-active}"
  set_state_value lock_uid "${FAKE_REPLACEMENT_LOCK_UID:-lock-uid-b}"
  set_state_value lock_resource_version "${FAKE_REPLACEMENT_LOCK_RESOURCE_VERSION:-1}"
  set_state_value lock_generation "${FAKE_REPLACEMENT_GENERATION:-generation-b}"
  set_state_value lock_baseline_generation "${FAKE_REPLACEMENT_BASELINE_GENERATION:-}"
  set_state_value lock_previous_backend "${FAKE_REPLACEMENT_PREVIOUS_BACKEND:-}"
  set_state_value lock_previous_init "${FAKE_REPLACEMENT_PREVIOUS_INIT:-}"
  set_state_value lock_sts_uid "${FAKE_REPLACEMENT_STS_UID:-}"
  set_state_value lock_sts_resource_version "${FAKE_REPLACEMENT_STS_RESOURCE_VERSION:-}"
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'lock-replace owner=%s\n' "$(state_value lock_owner)" >>"${FAKE_KUBE_LOG}"
}

replace_lease_and_fence_for_new_executor() {
  local generation lock_resource_version sts_resource_version
  generation="${FAKE_REPLACEMENT_GENERATION:-generation-new}"
  set_state_value lock_owner "${FAKE_REPLACEMENT_OWNER:-$(state_value lock_owner)}"
  set_state_value lock_target "${FAKE_REPLACEMENT_TARGET:-$(state_value lock_target)}"
  set_state_value lock_state active
  set_state_value lock_generation "$generation"
  set_state_value lock_baseline_generation "$generation"
  lock_resource_version="$(state_value lock_resource_version)"
  set_state_value lock_resource_version "$(( ${lock_resource_version:-1} + 1 ))"
  set_state_value sts_annotations_present 1
  set_state_value sts_fence_present 1
  set_state_value sts_fence_generation "$generation"
  sts_resource_version="$(statefulset_resource_version)"
  set_state_value sts_resource_version "$((sts_resource_version + 1))"
  [ -z "${FAKE_KUBE_LOG:-}" ] \
    || printf 'lease-fence-replace generation=%s\n' "$generation" >>"${FAKE_KUBE_LOG}"
}

if [[ "$args" == *" auth can-i "* ]]; then
  printf '%s\n' "${FAKE_RBAC:-yes}"
  exit 0
fi
if [[ "$args" == *" create configmap ai-builder-release-lock "* ]]; then
  [ -z "$(state_value lock_uid)" ] && [ -z "$(state_value lock_state)" ] || exit 1
  if [ "${FAKE_INTERLEAVE_ON_LOCK_CREATE:-0}" = "1" ] \
    && [ "$(state_value interleave_completed)" != "1" ]; then
    set_state_value backend_image "registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    set_state_value init_image "registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    set_state_value sts_resource_version "2"
    set_state_value interleave_completed 1
    [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'interleave-release backend=%s\n' "$(state_value backend_image)" >>"${FAKE_KUBE_LOG}"
  fi
  for argument in "$@"; do
    case "$argument" in
      --from-literal=owner=*) set_state_value lock_owner "${argument#--from-literal=owner=}" ;;
      --from-literal=target_image=*) set_state_value lock_target "${argument#--from-literal=target_image=}" ;;
      --from-literal=state=*) set_state_value lock_state "${argument#--from-literal=state=}" ;;
      --from-literal=lease_generation=*) set_state_value lock_generation "${argument#--from-literal=lease_generation=}" ;;
      --from-literal=baseline_generation=*) set_state_value lock_baseline_generation "${argument#--from-literal=baseline_generation=}" ;;
      --from-literal=validated_statefulset_uid=*) set_state_value lock_sts_uid "${argument#--from-literal=validated_statefulset_uid=}" ;;
      --from-literal=validated_statefulset_resource_version=*) set_state_value lock_sts_resource_version "${argument#--from-literal=validated_statefulset_resource_version=}" ;;
      --from-literal=previous_backend_image=*) set_state_value lock_previous_backend "${argument#--from-literal=previous_backend_image=}" ;;
      --from-literal=previous_init_image=*) set_state_value lock_previous_init "${argument#--from-literal=previous_init_image=}" ;;
      --from-literal=acquired_at=*) set_state_value lock_acquired_at "${argument#--from-literal=acquired_at=}" ;;
    esac
  done
  [ -n "$(state_value lock_owner)" ] && [ -n "$(state_value lock_target)" ] || exit 64
  [ -n "$(state_value lock_state)" ] || set_state_value lock_state active
  state_has_key lock_generation || exit 64
  for key in lock_baseline_generation lock_sts_uid lock_sts_resource_version lock_previous_backend lock_previous_init; do
    state_has_key "$key" || exit 64
  done
  [ -n "$(state_value lock_uid)" ] || set_state_value lock_uid "${FAKE_LOCK_UID_ON_CREATE:-lock-uid-a}"
  [ -n "$(state_value lock_resource_version)" ] || set_state_value lock_resource_version "${FAKE_LOCK_RESOURCE_VERSION_ON_CREATE:-1}"
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'lock-create owner=%s target=%s\n' "$(state_value lock_owner)" "$(state_value lock_target)" >>"${FAKE_KUBE_LOG}"
  if [[ "$args" == *"metadata.uid"* && "$args" == *"metadata.resourceVersion"* ]]; then
    printf '%s %s\n' "$(state_value lock_uid)" "$(state_value lock_resource_version)"
  elif [[ "$args" == *"metadata.resourceVersion"* ]]; then
    printf '%s\n' "$(state_value lock_resource_version)"
  fi
  exit 0
fi
if [[ "$args" == *" patch configmap ai-builder-release-lock "* ]]; then
  [ -n "$(state_value lock_uid)" ] || exit 1
  if [ "${FAKE_REPLACE_LOCK_ON_PATCH:-0}" = "1" ] \
    && [ "$(state_value lock_replaced_on_patch)" != "1" ]; then
    set_state_value lock_replaced_on_patch 1
    replace_lock_with_owner_b
  fi
  patch=""
  previous=""
  for argument in "$@"; do
    if [ "$previous" = "--patch" ]; then
      patch="$argument"
      break
    fi
    previous="$argument"
  done
  [ -n "$patch" ] || exit 64
  rows="$(mktemp)"
  json_patch_rows "$patch" >"$rows"
  while IFS=$'\t' read -r operation path encoded; do
    key="$(lock_state_key "$path")" || { rm -f "$rows"; exit 64; }
    expected="$(json_patch_value "$encoded")"
    case "$operation" in
      test)
        [ "$(state_value "$key")" = "$expected" ] || { rm -f "$rows"; exit 1; }
        ;;
      replace)
        state_has_key "$key" || { rm -f "$rows"; exit 1; }
        ;;
      add) ;;
      *) rm -f "$rows"; exit 64 ;;
    esac
  done <"$rows"
  while IFS=$'\t' read -r operation path encoded; do
    case "$operation" in
      add|replace)
        key="$(lock_state_key "$path")"
        set_state_value "$key" "$(json_patch_value "$encoded")"
        ;;
    esac
  done <"$rows"
  rm -f "$rows"
  set_state_value lock_resource_version "$(( $(state_value lock_resource_version) + 1 ))"
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'lock-patch uid=%s rv=%s\n' \
    "$(state_value lock_sts_uid)" "$(state_value lock_sts_resource_version)" >>"${FAKE_KUBE_LOG}"
  if [[ "$args" == *"metadata.uid"* && "$args" == *"metadata.resourceVersion"* ]]; then
    printf '%s %s\n' "$(state_value lock_uid)" "$(state_value lock_resource_version)"
  elif [[ "$args" == *"metadata.resourceVersion"* ]]; then
    printf '%s\n' "$(state_value lock_resource_version)"
  fi
  exit 0
fi
if [[ "$args" == *" get configmap ai-builder-release-lock "* || "$args" == *" get configmap/ai-builder-release-lock "* ]]; then
  [ "${FAKE_LOCK_GET_TRANSIENT_FAIL:-0}" != "1" ] || exit 1
  if [ -z "$(state_value lock_uid)" ] && [ -z "$(state_value lock_state)" ]; then
    [[ "$args" == *" --ignore-not-found "* ]] && exit 0
    exit 1
  fi
  case "$args" in
    *"metadata.uid"*"data.state"*"data.owner"*)
      printf '%s|%s|%s|%s|%s\n' \
        "$(state_value lock_uid)" "$(state_value lock_resource_version)" \
        "$(state_value lock_state)" "$(state_value lock_owner)" "$(state_value lock_target)"
      ;;
    *"metadata.uid"*"metadata.resourceVersion"*)
      printf '%s %s\n' "$(state_value lock_uid)" "$(state_value lock_resource_version)"
      ;;
    *"metadata.uid"*) printf '%s\n' "$(state_value lock_uid)" ;;
    *"metadata.resourceVersion"*) printf '%s\n' "$(state_value lock_resource_version)" ;;
    *"target_image"*) printf '%s\n' "$(state_value lock_target)" ;;
    *"previous_backend_image"*) printf '%s\n' "$(state_value lock_previous_backend)" ;;
    *"previous_init_image"*) printf '%s\n' "$(state_value lock_previous_init)" ;;
    *"validated_statefulset_uid"*) printf '%s\n' "$(state_value lock_sts_uid)" ;;
    *"validated_statefulset_resource_version"*) printf '%s\n' "$(state_value lock_sts_resource_version)" ;;
    *"baseline_generation"*) printf '%s\n' "$(state_value lock_baseline_generation)" ;;
    *"lease_generation"*) printf '%s\n' "$(state_value lock_generation)" ;;
    *"state"*) printf '%s\n' "$(state_value lock_state)" ;;
    *"owner"*) printf '%s\n' "$(state_value lock_owner)" ;;
    *) printf 'configmap/ai-builder-release-lock\n' ;;
  esac
  exit 0
fi
if [[ "$args" == *" delete configmap ai-builder-release-lock "* ]]; then
  [ -n "$(state_value lock_owner)" ] || exit 1
  if [ "${FAKE_REPLACE_LOCK_ON_DELETE:-0}" = "1" ] \
    && [ "$(state_value lock_replaced_on_delete)" != "1" ]; then
    set_state_value lock_replaced_on_delete 1
    replace_lock_with_owner_b
  fi
  set_state_value lock_owner ""
  set_state_value lock_target ""
  set_state_value lock_state ""
  set_state_value lock_previous_backend ""
  set_state_value lock_previous_init ""
  set_state_value lock_sts_uid ""
  set_state_value lock_sts_resource_version ""
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'lock-delete\n' >>"${FAKE_KUBE_LOG}"
  exit 0
fi
if [[ "$args" == *" proxy "* ]]; then
  printf 'Starting to serve on 127.0.0.1:%s\n' "${RELEASE_LOCK_PROXY_PORT:-18081}" >&2
  while :; do sleep 1; done
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
if [[ "$args" == *" patch statefulset ai-builder "* || "$args" == *" patch statefulset/ai-builder "* ]]; then
  patch=""
  previous=""
  for argument in "$@"; do
    if [ "$previous" = "--patch" ]; then
      patch="$argument"
      break
    fi
    previous="$argument"
  done
  [ -n "$patch" ] || exit 64
  patch_count="$(state_value statefulset_patch_count)"
  patch_count="$(( ${patch_count:-0} + 1 ))"
  set_state_value statefulset_patch_count "$patch_count"
  if [ "${FAKE_REPLACE_LEASE_ON_STS_PATCH:-0}" = "1" ] \
    && [ "$patch_count" = "${FAKE_REPLACE_LEASE_ON_STS_PATCH_NUMBER:-1}" ]; then
    replace_lease_and_fence_for_new_executor
  fi
  if [[ "$patch" == *"/image\""* ]]; then
    if [ "${FAKE_SET_IMAGE_FAIL_ONCE:-0}" = "1" ] \
      && [ "$(state_value set_image_failed_once)" != "1" ]; then
      set_state_value set_image_failed_once 1
      exit 1
    fi
    [ "${FAKE_SET_IMAGE_FAIL:-0}" != "1" ] || exit 1
  fi
  rows="$(mktemp)"
  json_patch_rows "$patch" >"$rows"
  while IFS=$'\t' read -r operation path encoded; do
    expected="$(json_patch_value "$encoded")"
    case "$operation" in
      test)
        statefulset_path_exists "$path" || { rm -f "$rows"; exit 1; }
        [ "$(statefulset_path_value "$path")" = "$expected" ] \
          || { rm -f "$rows"; exit 1; }
        ;;
      replace)
        statefulset_path_exists "$path" || { rm -f "$rows"; exit 1; }
        ;;
      add)
        case "$path" in
          /metadata/annotations) ;;
          /metadata/annotations/builder.ai~1release-generation)
            statefulset_annotations_present || { rm -f "$rows"; exit 1; }
            ;;
          *) statefulset_path_exists "$path" || { rm -f "$rows"; exit 1; } ;;
        esac
        ;;
      *) rm -f "$rows"; exit 64 ;;
    esac
  done <"$rows"
  next_backend=""
  next_init=""
  next_fence=""
  while IFS=$'\t' read -r operation path encoded; do
    case "$operation" in
      add|replace)
        value="$(json_patch_value "$encoded")"
        case "$path" in
          /metadata/annotations)
            next_fence="$(/usr/bin/python3 - "$value" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["builder.ai/release-generation"], end="")
PY
)"
            set_state_value sts_annotations_present 1
            set_state_value sts_other_annotation ""
            set_state_value sts_fence_present 1
            set_state_value sts_fence_generation "$next_fence"
            ;;
          /metadata/annotations/builder.ai~1release-generation)
            next_fence="$value"
            set_state_value sts_fence_present 1
            set_state_value sts_fence_generation "$next_fence"
            ;;
          /spec/template/spec/containers/*/image)
            next_backend="$value"
            set_state_value backend_image "$value"
            ;;
          /spec/template/spec/initContainers/*/image)
            next_init="$value"
            set_state_value init_image "$value"
            ;;
        esac
        ;;
    esac
  done <"$rows"
  rm -f "$rows"
  resource_version="$(statefulset_resource_version)"
  set_state_value sts_resource_version "$((resource_version + 1))"
  if [ -n "$next_backend" ] || [ -n "$next_init" ]; then
    [ -z "${FAKE_KUBE_LOG:-}" ] \
      || printf 'image-patch backend=%s init=%s fence=%s\n' \
        "$(state_value backend_image)" "$(state_value init_image)" \
        "$(state_value sts_fence_generation)" >>"${FAKE_KUBE_LOG}"
  elif [ -n "$next_fence" ]; then
    [ -z "${FAKE_KUBE_LOG:-}" ] \
      || printf 'fence-patch generation=%s other=%s\n' \
        "$next_fence" "$(statefulset_other_annotation)" >>"${FAKE_KUBE_LOG}"
  fi
  if [[ "$args" == *"metadata.uid"* && "$args" == *"metadata.resourceVersion"* ]]; then
    printf '%s %s\n' "$(statefulset_uid)" "$(statefulset_resource_version)"
  elif [[ "$args" == *"metadata.resourceVersion"* ]]; then
    printf '%s\n' "$(statefulset_resource_version)"
  fi
  exit 0
fi
if [[ "$args" == *" get statefulset ai-builder "* || "$args" == *" get statefulset/ai-builder "* ]]; then
  if [ "${FAKE_STS_ABSENT:-0}" = "1" ] || [ "$(state_value sts_deleted)" = "1" ]; then
    printf 'Error from server (NotFound): statefulsets.apps "ai-builder" not found\n' >&2
    exit 1
  fi
  if [[ "$args" != *" -o "* ]]; then
    printf 'statefulset/ai-builder\n'
  elif [[ "$args" == *'index .metadata.annotations "builder.ai/release-generation"'* ]]; then
    statefulset_fence_present && printf '%s' "$(state_value sts_fence_generation)"
  elif [[ "$args" == *".metadata.annotations"* ]]; then
    if statefulset_annotations_present; then
      other_annotation="$(statefulset_other_annotation)"
      [ -z "$other_annotation" ] || printf 'other.example/key=%s\n' "$other_annotation"
      statefulset_fence_present \
        && printf 'builder.ai/release-generation=%s\n' "$(state_value sts_fence_generation)"
    fi
  elif [[ "$args" == *"metadata.uid"* || "$args" == *"metadata.resourceVersion"* ]]; then
    if [[ "$args" == *"metadata.uid"* && "$args" == *"metadata.resourceVersion"* ]]; then
      printf '%s %s\n' "$(statefulset_uid)" "$(statefulset_resource_version)"
    elif [[ "$args" == *"metadata.uid"* ]]; then
      printf '%s\n' "$(statefulset_uid)"
    else
      printf '%s\n' "$(statefulset_resource_version)"
    fi
  elif [[ "$args" == *"currentRevision"* || "$args" == *"updateRevision"* ]]; then
    printf '%s\n' "${FAKE_STS_REVISIONS:-rev-7 rev-7}"
  elif [[ "$args" == *"spec.template.spec.containers"* && "$args" == *"image"* ]]; then
    image="$(state_value backend_image)"
    printf '%s\n' "${image:-${FAKE_STS_BACKEND_IMAGE:-registry.example/ai-builder@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}}"
  elif [[ "$args" == *"spec.template.spec.initContainers"* && "$args" == *"image"* ]]; then
    image="$(state_value init_image)"
    printf '%s\n' "${image:-${FAKE_STS_INIT_IMAGE:-registry.example/ai-builder@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}}"
  elif [[ "$args" == *"containers"* ]]; then
    if [[ "$args" == *'{"\n"}'* ]]; then
      printf '%s\n' "${FAKE_CONTAINERS:-ai-builder web}" | tr ' ' '\n'
    else
      printf '%s ' ${FAKE_CONTAINERS:-ai-builder web}
    fi
  elif [[ "$args" == *"initContainers"* ]]; then
    if [[ "$args" == *'{"\n"}'* ]]; then
      printf '%s\n' "${FAKE_INIT_TOPOLOGY:-copy-frontend-dist}" | tr ' ' '\n'
    else
      printf '%s ' ${FAKE_INIT_TOPOLOGY:-copy-frontend-dist}
    fi
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
  printf 'kubectl set image is forbidden by the release fencing contract\n' >&2
  exit 64
fi
if [[ "$args" == *" rollout status statefulset/ai-builder "* ]]; then
  [ -z "${FAKE_KUBE_LOG:-}" ] || printf 'rollout-status\n' >>"${FAKE_KUBE_LOG}"
  if [ "${FAKE_ROLLOUT_FAIL_ONCE:-0}" = "1" ] && [ "$(state_value rollout_failed_once)" != "1" ]; then
    set_state_value rollout_failed_once 1
    exit 1
  fi
  [ "${FAKE_ROLLOUT_FAIL:-0}" != "1" ] || exit 1
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
recovery = config.fetch("release_builder_recovery")
expected = {
  "KUBE_NAMESPACE" => "$BUILDER_K8S_NAMESPACE",
  "KUBE_STATEFULSET" => "$BUILDER_K8S_STATEFULSET",
  "KUBE_BACKEND_CONTAINER" => "$BUILDER_K8S_BACKEND_CONTAINER",
  "KUBE_DIST_INIT_CONTAINER" => "$BUILDER_K8S_DIST_INIT_CONTAINER",
  "KUBE_LABEL_SELECTOR" => "$BUILDER_K8S_LABEL_SELECTOR",
  "KUBE_WEB_CONTAINER" => "$BUILDER_K8S_WEB_CONTAINER",
  "KUBE_EXPECTED_HOST" => "$BUILDER_K8S_EXPECTED_HOST",
  "KUBE_EXPECTED_ORIGIN" => "$BUILDER_K8S_EXPECTED_ORIGIN",
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
abort "wrong default expected origin" unless config.dig("variables", "BUILDER_K8S_EXPECTED_ORIGIN") == "https://om-demo.dfy.definesys.cn"
abort "release must need preflight" unless config.fetch("release_and_update_server").fetch("needs").any? { |need| need["job"] == "release_builder_preflight" && need["artifacts"] }
abort "smoke must use release spec" unless smoke.fetch("script").join("\n").include?("verify_builder_tenant_url_smoke.sh")
update = config.fetch("release_and_update_server")
abort "update job must persist artifacts after failure" unless update.dig("artifacts", "when") == "always"
abort "release jobs must serialize the workload" unless update["resource_group"] == "$BUILDER_K8S_NAMESPACE/$BUILDER_K8S_STATEFULSET"
update_script = update.fetch("script").join("\n")
abort "update job must own ConfigMap release lock" unless update_script.include?("release_lock_owner")
create_at = update_script.index('if ! identity="$(kubectl -n "${BUILDER_K8S_NAMESPACE}" create configmap')
fence_at = create_at && update_script.index("fence_statefulset_for_generation", create_at)
capture_at = fence_at && update_script.index("read_statefulset_snapshot", fence_at)
patch_at = capture_at && update_script.index('patch_release_lock_cas "${patch}"', capture_at)
set_at = patch_at && update_script.index('if ! patch_statefulset_images_cas', patch_at)
abort "update job must acquire lock before fencing and capture" \
  unless create_at && fence_at && capture_at && create_at < fence_at && fence_at < capture_at
abort "update job must persist baseline before mutation" unless patch_at
abort "update job must mutate images with StatefulSet JSON Patch" unless set_at
abort "update job must validate baseline before mutation" unless patch_at < set_at
abort "update job must export lease generation" unless update_script.include?("LEASE_GENERATION=")
abort "browser job must verify ConfigMap release lock" unless smoke.fetch("script").join("\n").include?("release_lock_owner")
abort "missing recovery stage" unless config.fetch("stages").include?("recovery")
abort "recovery must run after release" unless config.fetch("stages").index("recovery") > config.fetch("stages").index("release")
abort "recovery must use fixed kubectl" unless recovery.dig("image", "name") == "hub-mirror.dfy.definesys.cn/bitnami/kubectl:1.30.7"
abort "recovery must always run" unless recovery.fetch("rules").any? { |rule| rule["when"] == "always" }
abort "recovery must not consume browser artifacts" if recovery.fetch("needs", []).any? { |need| need["artifacts"] }
abort "recovery must explicitly disable previous-stage artifact downloads" unless recovery["dependencies"] == []
recovery_script = recovery.fetch("script").join("\n")
abort "recovery must read lock previous refs" unless recovery_script.include?("previous_backend_image")
abort "recovery must not read browser dotenv" if recovery_script.include?("PREVIOUS_BACKEND_IMAGE")
abort "recovery lock existence check must distinguish NotFound from API failures" \
  unless recovery_script.include?("--ignore-not-found") && recovery_script.include?("-o name")
online_source = File.read(File.join(File.dirname(path), "scripts/deploy_online_latest_kubesphere.sh"))
[update.fetch("script").join("\n"), smoke.fetch("script").join("\n"), recovery_script, online_source].each do |source|
  abort "release lock baseline/release must use JSON Patch CAS" unless source.include?("--type=json")
  %w[/metadata/uid /metadata/resourceVersion /data/owner /data/target_image].each do |path|
    abort "release lock CAS test missing #{path}" unless source.include?(path)
  end
end
[update.fetch("script").join("\n"), recovery_script].each do |source|
  abort "kubectl-only job must not require curl" if source.match?(/\bcurl\b/)
end
[update.fetch("script").join("\n"), smoke.fetch("script").join("\n"), recovery_script, online_source].each do |source|
  %w[lease_generation baseline_generation builder.ai/release-generation].each do |contract|
    abort "missing release generation/fence contract #{contract}" unless source.include?(contract)
  end
end
[update.fetch("script").join("\n"), recovery_script, online_source].each do |source|
  abort "release image mutation must use StatefulSet JSON Patch CAS" if source.include?("set image")
  abort "release image mutation is missing StatefulSet metadata fence tests" unless source.include?("/metadata/annotations/")
  %w[
    /metadata/uid
    /metadata/resourceVersion
    /spec/template/spec/containers/
    /spec/template/spec/initContainers/
    /name
    /image
  ].each do |path|
    abort "StatefulSet image CAS is missing #{path}" unless source.include?(path)
  end
end
abort "update dotenv must include LEASE_GENERATION" \
  unless update.fetch("script").join("\n").include?("LEASE_GENERATION=%s")
abort "browser must consume artifact lease generation" \
  unless smoke.fetch("script").join("\n").include?("${LEASE_GENERATION}")
abort "released reuse must test empty owner and target" \
  unless update_script.include?('"path":"/data/owner","value":""') \
    && update_script.include?('"path":"/data/target_image","value":""')
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
        export FAKE_REPLACE_LOCK_ON_PATCH=1
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
        export FAKE_REPLACE_LOCK_ON_PATCH=1
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

assert_online_root_playwright_dependencies_contract() {
  local expected_calls npm_bin npm_calls npm_log output workdir
  npm_bin="${TMP_DIR}/root-playwright-bin"
  npm_log="${TMP_DIR}/root-playwright-npm.log"
  workdir="${TMP_DIR}/root-playwright-workdir"
  mkdir -p "$npm_bin" "$workdir"
  cat >"${npm_bin}/npm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s\n' "$PWD" "$*" >>"$FAKE_NPM_LOG"
EOF
  chmod 755 "${npm_bin}/npm"

  if ! output="$(
    PATH="${npm_bin}:$PATH" \
    WORKDIR="$workdir" \
    FAKE_NPM_LOG="$npm_log" \
      bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        prepare_root_playwright_dependencies
      ' bash "$ROOT_DIR" 2>&1
  )"; then
    printf '%s\n' "$output" >&2
    fail "online release did not prepare root Playwright dependencies"
  fi
  npm_calls="$(<"$npm_log")"
  expected_calls="$(printf '%s|ci\n%s|exec -- playwright install msedge\n' "$workdir" "$workdir")"
  [ "$npm_calls" = "$expected_calls" ] \
    || fail "online release must install msedge with locked local Playwright after npm ci"

  ruby - "${ROOT_DIR}/scripts/deploy_online_latest_kubesphere.sh" <<'RUBY'
source = File.read(ARGV.fetch(0))
main = source.split("main() {", 2).fetch(1)
clone_at = main.index("\n  clone_latest_code\n")
prepare_at = main.index("\n  prepare_root_playwright_dependencies\n")
prebuild_at = main.index("\n  run_release_builder_prebuild_preflight\n")
abort "root dependency preparation must run after clone and before online prebuild" \
  unless clone_at && prepare_at && prebuild_at && clone_at < prepare_at && prepare_at < prebuild_at
RUBY
  printf 'ONLINE_ROOT_PLAYWRIGHT_DEPENDENCIES=PASS\n'
}

run_fake_helper() {
  local mode="${1:-}"
  shift $(( $# > 0 ? 1 : 0 ))
  PATH="${FAKE_BIN}:$PATH" \
  FAKE_REAL_NODE="${FAKE_REAL_NODE:-$REAL_NODE}" \
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
  KUBE_EXPECTED_ORIGIN="${KUBE_EXPECTED_ORIGIN:-https://builder.example}" \
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

  output="$(FAKE_STS_ABSENT=1 assert_command_fails_without_secret run_fake_helper --online-preflight)"
  if [[ "$output" != *"StatefulSet is not accessible"* ]]; then
    printf 'online missing-workload output: %s\n' "$output" >&2
    fail "expected StatefulSet is not accessible"
  fi

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
  assert_contains "$output" "origin mismatch"

  output="$(
    BUILDER_ORIGIN="https://builder.example:443@staging.example" \
    KUBE_EXPECTED_ORIGIN="https://builder.example" \
      assert_command_fails_without_secret run_fake_helper --preflight
  )"
  assert_contains "$output" "BUILDER_ORIGIN must not contain credentials"

  output="$(FAKE_INGRESS_SERVICE="wrong-service" assert_command_fails_without_secret run_fake_helper --preflight)"
  assert_contains "$output" "Ingress backend service mismatch"

  output="$(FAKE_SERVICE_SELECTOR="app=wrong" assert_command_fails_without_secret run_fake_helper --preflight)"
  assert_contains "$output" "Service selector mismatch"

  output="$(FAKE_LOG='eyJhbGciOiJub25lIn0.e30.' assert_command_fails_without_secret run_fake_helper)"
  assert_contains "$output" "category=jwt_like"

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
    FAKE_ONLINE_REVISION="$TEST_REVISION" \
    FAKE_ONLINE_DIGEST="$TEST_DIGEST" \
    FAKE_BUILD_MARKER="${TMP_DIR}/online-build.called" \
    BUILDER_SMOKE_AGENT_ID="agent-1" \
      node "${ROOT_DIR}/tests/e2e/builder-tenant-url-release-smoke.spec.mjs"
  )"
  assert_contains "$output" "ACTIVATION_OBSERVER_CONTRACT=PASS"
  assert_contains "$output" "ACTIVATION_RETRY_CONTRACT=PASS"
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
  local source
  source="$(<"${ROOT_DIR}/scripts/deploy_online_latest_kubesphere.sh")"
  assert_not_contains "$source" "kubectl apply"
  assert_not_contains "$source" "apply_namespace"
  assert_not_contains "$source" "cleanup_fresh_workload"
  assert_not_contains "$source" "delete ingress"
  printf 'ONLINE_ROLLBACK_CONTRACT=PASS\n'
}

assert_online_generation_fencing_contract() {
  local state_file kube_log output generation mode
  state_file="${TMP_DIR}/online-generation.state"
  kube_log="${TMP_DIR}/online-generation.log"

  for mode in missing-parent nonempty-parent existing-fence; do
    printf '%s\n' \
      "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
      "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
      "sts_resource_version=1" \
      "sts_annotations_present=$([ "$mode" = "missing-parent" ] && printf 0 || printf 1)" \
      "sts_other_annotation=$([ "$mode" = "missing-parent" ] && printf '' || printf keep)" \
      "sts_fence_present=$([ "$mode" = "existing-fence" ] && printf 1 || printf 0)" \
      "sts_fence_generation=$([ "$mode" = "existing-fence" ] && printf generation-old || printf '')" \
      >"$state_file"
    : >"$kube_log"
    if ! output="$(
      PATH="${FAKE_BIN}:$PATH" \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        bash -c '
          source "$1/scripts/deploy_online_latest_kubesphere.sh"
          NAMESPACE="release-ns"
          APP_NAME="ai-builder"
          KUBE_BACKEND_CONTAINER="ai-builder"
          KUBE_DIST_INIT_CONTAINER="copy-frontend-dist"
          RELEASE_LOCK_NAME="ai-builder-release-lock"
          RELEASE_LOCK_OWNER="online-generation"
          IMAGE="registry.example/ai-builder@$2"
          acquire_release_lock
          fence_statefulset_for_generation
          capture_previous_workload
          persist_validated_baseline
        ' bash "$ROOT_DIR" "$TEST_DIGEST" 2>&1
    )"; then
      printf 'online generation mode=%s output:\n%s\nstate:\n%s\nlog:\n%s\n' \
        "$mode" "$output" "$(<"$state_file")" "$(<"$kube_log")" >&2
      fail "online generation setup failed"
    fi
    generation="$(state_file_value "$state_file" lock_generation)"
    [ -n "$generation" ] || fail "online fresh lock did not create a lease generation"
    [ "$(state_file_value "$state_file" lock_baseline_generation)" = "$generation" ] \
      || fail "online baseline generation does not match its lease"
    [ "$(state_file_value "$state_file" sts_fence_generation)" = "$generation" ] \
      || fail "online StatefulSet fence does not match its lease"
    if [ "$mode" != "missing-parent" ]; then
      [ "$(state_file_value "$state_file" sts_other_annotation)" = "keep" ] \
        || fail "online fence patch overwrote another StatefulSet annotation"
    fi
  done

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "sts_resource_version=4" \
    "lock_owner=" \
    "lock_target=" \
    "lock_state=released" \
    "lock_uid=lock-uid-a" \
    "lock_resource_version=7" \
    "lock_generation=generation-old" \
    "lock_baseline_generation=generation-old" \
    "lock_previous_backend=registry.example/ai-builder@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
    "lock_previous_init=registry.example/ai-builder@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
    "lock_sts_uid=sts-uid-old" \
    "lock_sts_resource_version=2" >"$state_file"
  PATH="${FAKE_BIN}:$PATH" \
  FAKE_KUBE_STATE="$state_file" \
    bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      NAMESPACE="release-ns"
      APP_NAME="ai-builder"
      RELEASE_LOCK_NAME="ai-builder-release-lock"
      RELEASE_LOCK_OWNER="online-generation"
      IMAGE="registry.example/ai-builder@$2"
      acquire_release_lock
      [ "$LEASE_GENERATION" != "generation-old" ]
      ! load_validated_baseline_from_lock
    ' bash "$ROOT_DIR" "$TEST_DIGEST"
  generation="$(state_file_value "$state_file" lock_generation)"
  [ -n "$generation" ] && [ "$generation" != "generation-old" ] \
    || fail "released lease reuse did not install a new generation"
  [ -z "$(state_file_value "$state_file" lock_baseline_generation)" ] \
    || fail "released lease reuse retained stale baseline generation"
  [ -z "$(state_file_value "$state_file" lock_previous_backend)" ] \
    && [ -z "$(state_file_value "$state_file" lock_previous_init)" ] \
    || fail "released lease reuse retained stale previous images"

  for mode in owner target; do
    printf '%s\n' \
      "lock_owner=$([ "$mode" = "owner" ] && printf stale-owner || printf '')" \
      "lock_target=$([ "$mode" = "target" ] && printf "registry.example/ai-builder@%s" "$TEST_DIGEST" || printf '')" \
      "lock_state=released" \
      "lock_uid=lock-uid-a" \
      "lock_resource_version=9" \
      "lock_generation=generation-old" \
      "lock_baseline_generation=" \
      "lock_previous_backend=" \
      "lock_previous_init=" \
      "lock_sts_uid=" \
      "lock_sts_resource_version=" >"$state_file"
    output="$(
      PATH="${FAKE_BIN}:$PATH" \
      FAKE_KUBE_STATE="$state_file" \
        assert_command_fails_without_secret bash -c '
          source "$1/scripts/deploy_online_latest_kubesphere.sh"
          NAMESPACE="release-ns"
          APP_NAME="ai-builder"
          RELEASE_LOCK_NAME="ai-builder-release-lock"
          RELEASE_LOCK_OWNER="online-generation"
          IMAGE="registry.example/ai-builder@$2"
          acquire_release_lock
        ' bash "$ROOT_DIR" "$TEST_DIGEST"
    )"
    assert_contains "$output" "manual recovery is required"
    [ "$(state_file_value "$state_file" lock_generation)" = "generation-old" ] \
      || fail "inconsistent released tombstone was mutated"
  done

  for mode in forward rollback recovery; do
    printf '%s\n' \
      "backend_image=$([ "$mode" = "forward" ] && printf "registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" || printf "registry.example/ai-builder@%s" "$TEST_DIGEST")" \
      "init_image=$([ "$mode" = "forward" ] && printf "registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" || printf "registry.example/ai-builder@%s" "$TEST_DIGEST")" \
      "sts_resource_version=12" \
      "sts_annotations_present=1" \
      "sts_other_annotation=keep" \
      "sts_fence_present=1" \
      "sts_fence_generation=generation-new" \
      "lock_owner=online-generation" \
      "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
      "lock_state=active" \
      "lock_uid=lock-uid-a" \
      "lock_resource_version=12" \
      "lock_generation=generation-new" \
      "lock_baseline_generation=generation-new" \
      "lock_previous_backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
      "lock_previous_init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
      "lock_sts_uid=sts-uid-1" \
      "lock_sts_resource_version=10" >"$state_file"
    : >"$kube_log"
    output="$(
      PATH="${FAKE_BIN}:$PATH" \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c '
          source "$1/scripts/deploy_online_latest_kubesphere.sh"
          NAMESPACE="release-ns"
          APP_NAME="ai-builder"
          RELEASE_LOCK_NAME="ai-builder-release-lock"
          RELEASE_LOCK_OWNER="online-generation"
          IMAGE="registry.example/ai-builder@$2"
          LEASE_GENERATION="generation-old"
          RELEASE_LOCK_UID="lock-uid-a"
          RELEASE_LOCK_RESOURCE_VERSION="12"
          LOCK_ACQUIRED=1
          case "$3" in
            forward)
              patch_statefulset_images_cas \
                "registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
                "registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
                "$IMAGE" "$IMAGE"
              ;;
            rollback)
              patch_statefulset_images_cas "$IMAGE" "$IMAGE" \
                "registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
                "registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
              ;;
            recovery) recover_failed_release ;;
          esac
        ' bash "$ROOT_DIR" "$TEST_DIGEST" "$mode"
    )"
    assert_not_contains "$(<"$kube_log")" "image-patch"
  done
  printf 'ONLINE_GENERATION_FENCING=PASS\n'
}

assert_ci_recovery_contract() {
  local job_dir state_file kube_log update_script browser_script recovery_script output generation
  job_dir="${TMP_DIR}/ci-recovery"
  state_file="${TMP_DIR}/ci-recovery.state"
  kube_log="${TMP_DIR}/ci-recovery.log"
  update_script="$(ci_job_script release_and_update_server)"
  browser_script="$(ci_job_script release_builder_browser_smoke)"
  recovery_script="$(ci_job_script release_builder_recovery)"
  mkdir -p "${job_dir}/build"
  ln -s "${ROOT_DIR}/scripts" "${job_dir}/scripts"
  ln -s "${ROOT_DIR}/node_modules" "${job_dir}/node_modules"
  printf '%s\n' \
    "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "sts_resource_version=1" >"$state_file"
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
    BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    CI_PIPELINE_ID="pipeline-a" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      bash -c "$update_script"
  )
  [ "$(state_file_value "$state_file" lock_owner)" = "ci-pipeline-a" ] \
    || fail "CI update did not acquire pipeline-owned release lock"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@${TEST_DIGEST}"
  generation="$(state_file_value "$state_file" lock_generation)"
  [ -n "$generation" ] || fail "CI update did not create a lease generation"
  [ "$(state_file_value "$state_file" lock_baseline_generation)" = "$generation" ] \
    || fail "CI update baseline generation does not match its lease"
  [ "$(state_file_value "$state_file" sts_fence_generation)" = "$generation" ] \
    || fail "CI update StatefulSet fence does not match its lease"
  assert_contains "$(<"${job_dir}/build/release.env")" "LEASE_GENERATION=${generation}"

  output="$(
    (
      local_status=0
      cd "$job_dir"
      set -a
      . build/release.env
      set +a
      export PATH="${FAKE_BIN}:$PATH"
      export APAAS_KUBECONFIG="${job_dir}/kubeconfig"
      export BUILDER_ORIGIN="https://builder.example"
      export KUBE_NAMESPACE="release-ns"
      export KUBE_STATEFULSET="ai-builder"
      export KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder"
      export KUBE_BACKEND_CONTAINER="ai-builder"
      export KUBE_DIST_INIT_CONTAINER="copy-frontend-dist"
      export KUBE_WEB_CONTAINER="web"
      export KUBE_EXPECTED_HOST="builder.example"
      export KUBE_EXPECTED_ORIGIN="https://builder.example"
      export KUBE_INGRESS="ai-builder"
      export KUBE_SERVICE="ai-builder"
      export KUBE_INGRESS_PATH="/ai-builder"
      export BUILDER_SMOKE_USERNAME="release-user"
      export BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD"
      export BUILDER_SMOKE_TENANT_NAME="Release Tenant"
      export BUILDER_SMOKE_CODE_SESSION_ID="session-1"
      export BUILDER_ROLLOUT_TIMEOUT="30s"
      export CI_PIPELINE_ID="pipeline-a"
      export FAKE_BROWSER_FAIL=1
      export FAKE_REAL_NODE="$REAL_NODE"
      export FAKE_KUBE_STATE="$state_file"
      export FAKE_KUBE_LOG="$kube_log"
      set +e
      browser_output="$(bash -e -c "$browser_script" 2>&1)"
      local_status=$?
      set -e
      assert_not_contains "$browser_output" "$TEST_PASSWORD"
      if [ "$local_status" -eq 0 ]; then
        fail "browser script unexpectedly succeeded"
      fi
      printf '%s\n' "$browser_output"
    )
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@${TEST_DIGEST}"
  [ "$(state_file_value "$state_file" lock_owner)" = "ci-pipeline-a" ] \
    || fail "browser failure must leave the release lock for recovery"

  # Model a failing browser before_script or a missing dotenv artifact: recovery sees only lock state.
  rm -f "${job_dir}/build/release.env"
  (
    cd "$job_dir"
    PATH="${FAKE_BIN}:$PATH" \
    APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
    BUILDER_K8S_NAMESPACE="release-ns" \
    BUILDER_K8S_STATEFULSET="ai-builder" \
    BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
    BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
    BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    CI_PIPELINE_ID="pipeline-a" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      bash -c "$recovery_script"
  )
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  assert_contains "$(<"$state_file")" "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  [ -z "$(state_file_value "$state_file" lock_owner)" ] || fail "recovery did not release its lock"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "init_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "sts_resource_version=9" \
    "sts_annotations_present=1" \
    "sts_fence_present=1" \
    "sts_fence_generation=generation-a" \
    "lock_owner=ci-pipeline-a" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_state=active" \
    "lock_generation=generation-a" \
    "lock_baseline_generation=generation-a" \
    "lock_previous_backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "lock_previous_init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "lock_sts_uid=sts-uid-1" \
    "lock_sts_resource_version=1" >"$state_file"
  : >"$kube_log"
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
    BUILDER_K8S_NAMESPACE="release-ns" \
    BUILDER_K8S_STATEFULSET="ai-builder" \
    BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
    BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
    BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    CI_PIPELINE_ID="pipeline-b" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      assert_command_fails_without_secret bash -c "$recovery_script"
  )"
  assert_contains "$output" "different pipeline"
  [ "$(state_file_value "$state_file" lock_owner)" = "ci-pipeline-a" ] \
    || fail "foreign recovery released another owner's lock"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@${TEST_DIGEST}"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "sts_resource_version=1" >"$state_file"
  printf 'BUILDER_IMAGE=registry.example/ai-builder@%s\nDEPLOYED_REVISION=%s\n' \
    "$TEST_DIGEST" "$TEST_REVISION" >"${job_dir}/build/release.env"
  (
    cd "$job_dir"
    PATH="${FAKE_BIN}:$PATH" \
    APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
    BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
    BUILDER_K8S_NAMESPACE="release-ns" \
    BUILDER_K8S_STATEFULSET="ai-builder" \
    BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
    BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
    BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    CI_PIPELINE_ID="pipeline-c" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      bash -c "$update_script"
    set -a
    . build/release.env
    set +a
    export PATH="${FAKE_BIN}:$PATH"
    export APAAS_KUBECONFIG="${job_dir}/kubeconfig"
    export BUILDER_ORIGIN="https://builder.example"
    export KUBE_NAMESPACE="release-ns"
    export KUBE_STATEFULSET="ai-builder"
    export KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder"
    export KUBE_BACKEND_CONTAINER="ai-builder"
    export KUBE_DIST_INIT_CONTAINER="copy-frontend-dist"
    export KUBE_WEB_CONTAINER="web"
    export KUBE_EXPECTED_HOST="builder.example"
    export KUBE_EXPECTED_ORIGIN="https://builder.example"
    export KUBE_INGRESS="ai-builder"
    export KUBE_SERVICE="ai-builder"
    export KUBE_INGRESS_PATH="/ai-builder"
    export BUILDER_SMOKE_USERNAME="release-user"
    export BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD"
    export BUILDER_SMOKE_TENANT_NAME="Release Tenant"
    export BUILDER_SMOKE_CODE_SESSION_ID="session-1"
    export BUILDER_ROLLOUT_TIMEOUT="30s"
    export CI_PIPELINE_ID="pipeline-c"
    export FAKE_REAL_NODE="$REAL_NODE"
    export FAKE_KUBE_STATE="$state_file"
    export FAKE_KUBE_LOG="$kube_log"
    bash -e -c "$browser_script"
  )
  [ -z "$(state_file_value "$state_file" lock_owner)" ] || fail "browser success did not release its lock"
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
    BUILDER_K8S_NAMESPACE="release-ns" \
    BUILDER_K8S_STATEFULSET="ai-builder" \
    BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
    BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
    BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    CI_PIPELINE_ID="pipeline-c" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      bash -c "$recovery_script"
  )"
  assert_contains "$output" "released release lock requires no recovery"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "init_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "sts_resource_version=3" \
    "sts_annotations_present=1" \
    "sts_fence_present=1" \
    "sts_fence_generation=generation-d" \
    "lock_owner=ci-pipeline-d" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_state=active" \
    "lock_generation=generation-d" \
    "lock_baseline_generation=generation-d" \
    "lock_previous_backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "lock_previous_init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "lock_sts_uid=sts-uid-1" \
    "lock_sts_resource_version=1" >"$state_file"
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
    BUILDER_K8S_NAMESPACE="release-ns" \
    BUILDER_K8S_STATEFULSET="ai-builder" \
    BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
    BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
    BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    BUILDER_ROLLOUT_TIMEOUT="30s" \
    CI_PIPELINE_ID="pipeline-d" \
    FAKE_ROLLBACK_ROLLOUT_FAIL=1 \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
      assert_command_fails_without_secret bash -c "$recovery_script"
  )"
  assert_contains "$output" "recovery rollback rollout or health verification failed"
  [ "$(state_file_value "$state_file" lock_owner)" = "ci-pipeline-d" ] \
    || fail "failed recovery released its lock"
  printf 'CI_RECOVERY_CONTRACT=PASS\n'
}

assert_ci_update_failure_and_lock_contract() {
  local job_dir state_file kube_log update_script output
  job_dir="${TMP_DIR}/ci-update-failure"
  state_file="${TMP_DIR}/ci-update-failure.state"
  kube_log="${TMP_DIR}/ci-update-failure.log"
  update_script="$(ci_job_script release_and_update_server)"
  mkdir -p "${job_dir}/build"
  printf 'backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\ninit_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n' >"$state_file"
  printf 'BUILDER_IMAGE=registry.example/ai-builder@%s\nDEPLOYED_REVISION=%s\n' \
    "$TEST_DIGEST" "$TEST_REVISION" >"${job_dir}/build/release.env"
  : >"${job_dir}/kubeconfig"
  : >"$kube_log"

  output="$(
    (
      cd "$job_dir"
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
      BUILDER_K8S_NAMESPACE="release-ns" \
      BUILDER_K8S_STATEFULSET="ai-builder" \
      BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
      BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
      BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      BUILDER_ROLLOUT_TIMEOUT="30s" \
      CI_PIPELINE_ID="pipeline-a" \
      CI_JOB_ID="update-a" \
      FAKE_ROLLOUT_FAIL_ONCE=1 \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c "$update_script"
    )
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  if [[ "$output" != *"rollout failed; rollback completed"* ]]; then
    printf 'CI update rollback output: %s\n' "$output" >&2
    fail "expected rollout failed; rollback completed"
  fi
  assert_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@${TEST_DIGEST}"
  assert_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  [ -z "$(state_file_value "$state_file" lock_owner)" ] || fail "CI update rollback did not release its lock"

  printf '%s\n' \
    "lock_owner=ci-pipeline-a-update-a" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_previous_backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "lock_previous_init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    >>"$state_file"
  : >"$kube_log"
  output="$(
    (
      cd "$job_dir"
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
      BUILDER_K8S_NAMESPACE="release-ns" \
      BUILDER_K8S_STATEFULSET="ai-builder" \
      BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
      BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
      BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      BUILDER_ROLLOUT_TIMEOUT="30s" \
      CI_PIPELINE_ID="pipeline-b" \
      CI_JOB_ID="update-b" \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c "$update_script"
    )
  )"
  assert_contains "$output" "release lock"
  assert_not_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@${TEST_DIGEST}"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "sts_resource_version=1" >"$state_file"
  : >"$kube_log"
  output="$(
    (
      cd "$job_dir"
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
      BUILDER_K8S_NAMESPACE="release-ns" \
      BUILDER_K8S_STATEFULSET="ai-builder" \
      BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
      BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
      BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      BUILDER_ROLLOUT_TIMEOUT="30s" \
      CI_PIPELINE_ID="pipeline-a" \
      FAKE_INTERLEAVE_ON_LOCK_CREATE=1 \
      FAKE_ROLLOUT_FAIL_ONCE=1 \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c "$update_script"
    )
  )"
  assert_contains "$output" "rollout failed; rollback completed"
  assert_contains "$(<"$kube_log")" "interleave-release backend=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  [ -z "$(state_file_value "$state_file" lock_owner)" ] || fail "CI interleave rollback did not release its lock"
  printf 'CI_UPDATE_LOCK_CONTRACT=PASS\n'
}

run_fake_online_main() {
  local state_file="$1" kube_log="$2" mode="$3" marker="$4"
  env \
    PATH="${FAKE_BIN}:$PATH" \
    FAKE_REAL_NODE="$REAL_NODE" \
    WORKDIR="$ROOT_DIR" \
    CONTAINER_CLI=true \
    NAMESPACE="release-ns" \
    APP_NAME="ai-builder" \
    HOST="builder.example" \
    KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
    KUBE_BACKEND_CONTAINER="ai-builder" \
    KUBE_DIST_INIT_CONTAINER="copy-frontend-dist" \
    KUBE_WEB_CONTAINER="web" \
    BUILDER_SMOKE_USERNAME="release-user" \
    BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD" \
    BUILDER_SMOKE_TENANT_NAME="Release Tenant" \
    BUILDER_SMOKE_CODE_SESSION_ID="session-1" \
    FAKE_ONLINE_REVISION="$TEST_REVISION" \
    FAKE_ONLINE_DIGEST="$TEST_DIGEST" \
    FAKE_ONLINE_MODE="$mode" \
    FAKE_BUILD_MARKER="$marker" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
    bash -c '
      source "$1/scripts/deploy_online_latest_kubesphere.sh"
      setup_kubeconfig() { :; }
      clone_latest_code() { GIT_SHA=aaaaaaaa; GIT_FULL_SHA="$FAKE_ONLINE_REVISION"; }
      prepare_root_playwright_dependencies() { :; }
      docker_login_if_requested() { :; }
      build_and_push_image() { : >"$FAKE_BUILD_MARKER"; IMAGE="registry.example/ai-builder@$FAKE_ONLINE_DIGEST"; }
      if [ "$FAKE_ONLINE_MODE" != "missing" ]; then
        run_release_builder_prebuild_preflight() { :; }
        run_release_builder_preflight() { :; }
      fi
      case "$FAKE_ONLINE_MODE" in
        missing) export FAKE_STS_ABSENT=1 ;;
        set) export FAKE_SET_IMAGE_FAIL_ONCE=1; run_release_builder_smoke() { return 0; } ;;
        rollout) export FAKE_ROLLOUT_FAIL_ONCE=1; run_release_builder_smoke() { return 0; } ;;
        smoke) run_release_builder_smoke() { return 1; } ;;
        interleave)
          export FAKE_INTERLEAVE_ON_LOCK_CREATE=1
          export FAKE_ROLLOUT_FAIL_ONCE=1
          run_release_builder_smoke() { return 0; }
          ;;
      esac
      main
    ' bash "$ROOT_DIR"
}

assert_online_image_only_contract() {
  local state_file kube_log marker output mode
  state_file="${TMP_DIR}/online-image-only.state"
  kube_log="${TMP_DIR}/online-image-only.log"
  marker="${TMP_DIR}/online-build.called"

  printf 'backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\ninit_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n' >"$state_file"
  : >"$kube_log"
  output="$(assert_command_fails_without_secret run_fake_online_main "$state_file" "$kube_log" missing "$marker")"
  assert_contains "$output" "StatefulSet is not accessible"
  [ ! -e "$marker" ] || fail "online build ran before existing-workload preflight"

  for mode in set rollout smoke; do
    printf 'backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\ninit_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\n' >"$state_file"
    : >"$kube_log"
    rm -f "$marker"
    output="$(assert_command_fails_without_secret run_fake_online_main "$state_file" "$kube_log" "$mode" "$marker")"
    if [[ "$output" != *"rollback completed"* ]]; then
      printf 'online %s output: %s\n' "$mode" "$output" >&2
      fail "expected rollback completed"
    fi
    if [ "$mode" = "set" ]; then
      assert_not_contains "$(<"$kube_log")" "image-patch"
    else
      assert_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@${TEST_DIGEST}"
      assert_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    fi
    assert_not_contains "$(<"$kube_log")" " apply "
    assert_not_contains "$(<"$kube_log")" " delete "
    [ -z "$(state_file_value "$state_file" lock_owner)" ] || fail "online ${mode} rollback did not release its lock"
  done
  printf 'ONLINE_IMAGE_ONLY_CONTRACT=PASS\n'
}

assert_online_lock_baseline_interleave_contract() {
  local state_file kube_log marker output
  state_file="${TMP_DIR}/online-interleave.state"
  kube_log="${TMP_DIR}/online-interleave.log"
  marker="${TMP_DIR}/online-interleave-build.called"
  printf '%s\n' \
    "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "init_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "sts_resource_version=1" >"$state_file"
  : >"$kube_log"

  output="$(assert_command_fails_without_secret run_fake_online_main "$state_file" "$kube_log" interleave "$marker")"
  assert_contains "$output" "rollback completed"
  assert_contains "$(<"$kube_log")" "interleave-release backend=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  assert_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@${TEST_DIGEST}"
  assert_contains "$(<"$kube_log")" "image-patch backend=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  assert_contains "$(<"$state_file")" "backend_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  [ -z "$(state_file_value "$state_file" lock_owner)" ] || fail "online interleave recovery did not release its lock"
  printf 'ONLINE_LOCK_BASELINE_INTERLEAVE=PASS\n'
}

assert_replacement_lock_cas_contract() {
  local state_file kube_log job_dir update_script browser_script recovery_script output
  state_file="${TMP_DIR}/replacement-lock.state"
  kube_log="${TMP_DIR}/replacement-lock.log"
  job_dir="${TMP_DIR}/replacement-lock-ci"
  update_script="$(ci_job_script release_and_update_server)"
  browser_script="$(ci_job_script release_builder_browser_smoke)"
  recovery_script="$(ci_job_script release_builder_recovery)"
  mkdir -p "${job_dir}/build"
  ln -s "${ROOT_DIR}/scripts" "${job_dir}/scripts"
  ln -s "${ROOT_DIR}/node_modules" "${job_dir}/node_modules"
  : >"${job_dir}/kubeconfig"

  printf '%s\n' \
    "lock_owner=online-a" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_state=active" \
    "lock_uid=lock-uid-a" \
    "lock_resource_version=7" \
    "lock_generation=generation-a" \
    "lock_baseline_generation=" \
    "lock_previous_backend=" \
    "lock_previous_init=" \
    "lock_sts_uid=" \
    "lock_sts_resource_version=" >"$state_file"
  : >"$kube_log"
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
    FAKE_REPLACE_LOCK_ON_PATCH=1 \
      assert_command_fails_without_secret bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        NAMESPACE="release-ns"
        APP_NAME="ai-builder"
        RELEASE_LOCK_NAME="ai-builder-release-lock"
        IMAGE="registry.example/ai-builder@$2"
        RELEASE_LOCK_OWNER="online-a"
        RELEASE_LOCK_UID="lock-uid-a"
        RELEASE_LOCK_RESOURCE_VERSION="7"
        LEASE_GENERATION="generation-a"
        VALIDATED_STATEFULSET_UID="sts-uid-1"
        VALIDATED_STATEFULSET_RESOURCE_VERSION="1"
        PREVIOUS_BACKEND_IMAGE="registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        PREVIOUS_DIST_INIT_IMAGE="registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        persist_validated_baseline
      ' bash "$ROOT_DIR" "$TEST_DIGEST"
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  if [ "$(state_file_value "$state_file" lock_owner)" != "owner-b" ]; then
    printf 'online replacement baseline output: %s\nstate:\n%s\n' "$output" "$(<"$state_file")" >&2
    fail "online stale baseline patch changed replacement lock owner"
  fi
  [ -z "$(state_file_value "$state_file" lock_previous_backend)" ] \
    || fail "online stale baseline patch wrote replacement lock baseline"

  printf '%s\n' \
    "lock_owner=online-a" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_state=active" \
    "lock_uid=lock-uid-a" \
    "lock_resource_version=7" \
    "lock_generation=generation-a" \
    "lock_baseline_generation=" \
    "lock_previous_backend=" \
    "lock_previous_init=" \
    "lock_sts_uid=" \
    "lock_sts_resource_version=" >"$state_file"
  output="$(
    PATH="${FAKE_BIN}:$PATH" \
    FAKE_KUBE_STATE="$state_file" \
    FAKE_KUBE_LOG="$kube_log" \
    FAKE_REPLACE_LOCK_ON_PATCH=1 \
      assert_command_fails_without_secret bash -c '
        source "$1/scripts/deploy_online_latest_kubesphere.sh"
        NAMESPACE="release-ns"
        APP_NAME="ai-builder"
        RELEASE_LOCK_NAME="ai-builder-release-lock"
        IMAGE="registry.example/ai-builder@$2"
        RELEASE_LOCK_OWNER="online-a"
        RELEASE_LOCK_UID="lock-uid-a"
        RELEASE_LOCK_RESOURCE_VERSION="7"
        LEASE_GENERATION="generation-a"
        LOCK_ACQUIRED=1
        release_lock_if_owned
      ' bash "$ROOT_DIR" "$TEST_DIGEST"
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  [ "$(state_file_value "$state_file" lock_owner)" = "owner-b" ] \
    || fail "online stale release deleted replacement lock"
  [ "$(state_file_value "$state_file" lock_uid)" = "lock-uid-b" ] \
    || fail "online stale release changed replacement lock identity"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "init_image=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "sts_resource_version=1" >"$state_file"
  printf 'BUILDER_IMAGE=registry.example/ai-builder@%s\nDEPLOYED_REVISION=%s\n' \
    "$TEST_DIGEST" "$TEST_REVISION" >"${job_dir}/build/release.env"
  output="$(
    (
      cd "$job_dir"
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
      BUILDER_K8S_NAMESPACE="release-ns" \
      BUILDER_K8S_STATEFULSET="ai-builder" \
      BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
      BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
      BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      BUILDER_ROLLOUT_TIMEOUT="30s" \
      CI_PIPELINE_ID="pipeline-a" \
      CI_JOB_ID="update-a" \
      FAKE_REPLACE_LOCK_ON_PATCH=1 \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c "$update_script"
    )
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  [ "$(state_file_value "$state_file" lock_owner)" = "owner-b" ] \
    || fail "CI update stale baseline patch changed replacement lock owner"
  [ -z "$(state_file_value "$state_file" lock_previous_backend)" ] \
    || fail "CI update stale baseline patch wrote replacement lock baseline"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "init_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "sts_resource_version=3" \
    "sts_annotations_present=1" \
    "sts_fence_present=1" \
    "sts_fence_generation=generation-a" \
    "lock_owner=ci-pipeline-a" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_state=active" \
    "lock_uid=lock-uid-a" \
    "lock_resource_version=7" \
    "lock_generation=generation-a" \
    "lock_baseline_generation=generation-a" \
    "lock_previous_backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "lock_previous_init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "lock_sts_uid=sts-uid-1" \
    "lock_sts_resource_version=2" >"$state_file"
  output="$(
    (
      cd "$job_dir"
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_IMAGE="registry.example/ai-builder@${TEST_DIGEST}" \
      DEPLOYED_REVISION="$TEST_REVISION" \
      KUBE_NAMESPACE="release-ns" \
      KUBE_STATEFULSET="ai-builder" \
      KUBE_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      KUBE_BACKEND_CONTAINER="ai-builder" \
      KUBE_DIST_INIT_CONTAINER="copy-frontend-dist" \
      KUBE_WEB_CONTAINER="web" \
      KUBE_EXPECTED_HOST="builder.example" \
      KUBE_EXPECTED_ORIGIN="https://builder.example" \
      KUBE_INGRESS="ai-builder" \
      KUBE_SERVICE="ai-builder" \
      KUBE_INGRESS_PATH="/ai-builder" \
      BUILDER_ORIGIN="https://builder.example" \
      BUILDER_SMOKE_USERNAME="release-user" \
      BUILDER_SMOKE_PASSWORD="$TEST_PASSWORD" \
      BUILDER_SMOKE_TENANT_NAME="Release Tenant" \
      BUILDER_SMOKE_CODE_SESSION_ID="session-1" \
      CI_PIPELINE_ID="pipeline-a" \
      LEASE_GENERATION="generation-a" \
      FAKE_REAL_NODE="$REAL_NODE" \
      FAKE_REPLACE_LOCK_ON_PATCH=1 \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -e -c "$browser_script"
    )
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  [ "$(state_file_value "$state_file" lock_owner)" = "owner-b" ] \
    || fail "CI browser stale release deleted replacement lock"

  printf '%s\n' \
    "backend_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "init_image=registry.example/ai-builder@${TEST_DIGEST}" \
    "sts_resource_version=1" \
    "sts_annotations_present=1" \
    "sts_fence_present=1" \
    "sts_fence_generation=generation-a" \
    "lock_owner=ci-pipeline-a" \
    "lock_target=registry.example/ai-builder@${TEST_DIGEST}" \
    "lock_state=active" \
    "lock_uid=lock-uid-a" \
    "lock_resource_version=7" \
    "lock_generation=generation-a" \
    "lock_baseline_generation=generation-a" \
    "lock_previous_backend=registry.example/ai-builder@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
    "lock_previous_init=registry.example/ai-builder@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
    "lock_sts_uid=sts-uid-1" \
    "lock_sts_resource_version=1" >"$state_file"
  output="$(
    (
      cd "$job_dir"
      PATH="${FAKE_BIN}:$PATH" \
      APAAS_KUBECONFIG="${job_dir}/kubeconfig" \
      BUILDER_K8S_NAMESPACE="release-ns" \
      BUILDER_K8S_STATEFULSET="ai-builder" \
      BUILDER_K8S_BACKEND_CONTAINER="ai-builder" \
      BUILDER_K8S_DIST_INIT_CONTAINER="copy-frontend-dist" \
      BUILDER_K8S_LABEL_SELECTOR="app.kubernetes.io/name=ai-builder" \
      BUILDER_ROLLOUT_TIMEOUT="30s" \
      CI_PIPELINE_ID="pipeline-a" \
      FAKE_REPLACE_LOCK_ON_PATCH=1 \
      FAKE_KUBE_STATE="$state_file" \
      FAKE_KUBE_LOG="$kube_log" \
        assert_command_fails_without_secret bash -c "$recovery_script"
    )
  )"
  assert_not_contains "$output" "$TEST_PASSWORD"
  [ "$(state_file_value "$state_file" lock_owner)" = "owner-b" ] \
    || fail "CI recovery stale release deleted replacement lock"
  printf 'REPLACEMENT_LOCK_CAS_CONTRACT=PASS\n'
}

main() {
  write_fake_tools
  assert_fake_helper_contract
  assert_online_generation_fencing_contract
  assert_ci_metadata_and_mapping
  assert_ci_metadata_flow
  assert_podman_digestfile
  assert_online_build_cli_branches
  assert_online_source_and_docker_preflight
  assert_online_root_playwright_dependencies_contract
  assert_online_selector_contract
  assert_online_rollback_contract
  assert_ci_recovery_contract
  assert_ci_update_failure_and_lock_contract
  assert_online_image_only_contract
  assert_online_lock_baseline_interleave_contract
  assert_replacement_lock_cas_contract
  assert_release_spec_contract
  assert_activation_observer_contract
  printf 'PASS: builder tenant URL release smoke contract\n'
}

main "$@"
