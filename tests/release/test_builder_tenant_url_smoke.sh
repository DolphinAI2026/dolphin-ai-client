#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local file="$1" expected="$2"
  grep -F -- "$expected" "${ROOT_DIR}/${file}" >/dev/null \
    || fail "${file} is missing: ${expected}"
}

assert_contains '.gitlab-ci.yml' '--metadata-file build/metadata.json'
assert_contains '.gitlab-ci.yml' 'containerimage.digest'
assert_contains '.gitlab-ci.yml' 'BUILDER_IMAGE=%s@%s'
assert_contains '.gitlab-ci.yml' 'DEPLOYED_REVISION=%s'
assert_contains '.gitlab-ci.yml' 'release_builder_browser_smoke:'
assert_contains '.gitlab-ci.yml' 'mcr.microsoft.com/playwright:v1.61.1-noble'
assert_contains '.gitlab-ci.yml' 'v1.30.7/bin/linux/amd64/kubectl'
assert_contains '.gitlab-ci.yml' 'npm exec -- playwright install msedge'

assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'initContainerStatuses'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'containerStatuses'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'builder-build-sha'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'BROWSER_CHANNEL=msedge'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'tenant_public_id reconcile --verify-only-after-write'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' 'BUILDER_CODE_SESSION_REF'
assert_contains 'scripts/verify_builder_tenant_url_smoke.sh' '1.61.1'

assert_contains 'scripts/deploy_online_latest_kubesphere.sh' 'resolve_pushed_image_digest'
assert_contains 'scripts/deploy_online_latest_kubesphere.sh' 'run_release_builder_smoke'
assert_contains 'scripts/deploy_online_latest_kubesphere.sh' 'BUILDER_IMAGE="$IMAGE"'
assert_contains 'scripts/deploy_online_latest_kubesphere.sh' 'DEPLOYED_REVISION="$GIT_FULL_SHA"'

printf 'PASS: builder tenant URL release smoke contract\n'
