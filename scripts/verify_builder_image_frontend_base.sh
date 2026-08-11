#!/usr/bin/env bash
set -euo pipefail

CONTAINER_CLI="${CONTAINER_CLI:-docker}"
BUILDER_IMAGE="${BUILDER_IMAGE:?BUILDER_IMAGE is required}"
EXPECTED_BASE_URL="${EXPECTED_BASE_URL:?EXPECTED_BASE_URL is required}"
EXPECTED_BUILD_SHA="${EXPECTED_BUILD_SHA:?EXPECTED_BUILD_SHA is required}"

fail() {
  printf '[builder-image-contract][fail] %s\n' "$*" >&2
  exit 1
}

case "$EXPECTED_BASE_URL" in
  /*/) ;;
  *) fail "EXPECTED_BASE_URL must be an absolute path ending with /" ;;
esac

[[ "$EXPECTED_BUILD_SHA" =~ ^[0-9a-f]{40}$ ]] \
  || fail "EXPECTED_BUILD_SHA must be a full lowercase Git SHA"

command -v "$CONTAINER_CLI" >/dev/null 2>&1 \
  || fail "container CLI is unavailable: ${CONTAINER_CLI}"

"$CONTAINER_CLI" pull "$BUILDER_IMAGE" >/dev/null 2>&1 \
  || fail "unable to pull frontend image: ${BUILDER_IMAGE}"
index_html="$(
  "$CONTAINER_CLI" run --rm --entrypoint cat "$BUILDER_IMAGE" \
    /app/frontend/dist/index.html
)"

expected_asset_prefix="${EXPECTED_BASE_URL}assets/"
grep -Fq "src=\"${expected_asset_prefix}" <<<"$index_html" \
  || fail "frontend entry asset does not use ${expected_asset_prefix}"

unexpected_asset_refs="$(
  grep -oE '(src|href)="/[^\"]*/assets/' <<<"$index_html" \
    | grep -vF "\"${expected_asset_prefix}" \
    || true
)"
[ -z "$unexpected_asset_refs" ] \
  || fail "frontend image contains asset paths outside ${expected_asset_prefix}"

grep -Fq "name=\"builder-build-sha\" content=\"${EXPECTED_BUILD_SHA}\"" \
  <<<"$index_html" \
  || fail "frontend build SHA does not match ${EXPECTED_BUILD_SHA}"

printf '[builder-image-contract][ok] image=%s base=%s sha=%s\n' \
  "$BUILDER_IMAGE" "$EXPECTED_BASE_URL" "$EXPECTED_BUILD_SHA"
