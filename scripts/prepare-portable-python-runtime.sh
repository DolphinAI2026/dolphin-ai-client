#!/usr/bin/env bash
# Download and validate a fixed python-build-standalone runtime for an appliance.
set -euo pipefail

archive=''

fail() {
  printf '[portable-python-runtime] %s\n' "$*" >&2
  exit 1
}

usage() {
  printf 'Usage: %s --platform macos-aarch64|linux-x86_64 --destination DIRECTORY\n' "${0##*/}" >&2
}

select_platform() {
  case "$1" in
    macos-aarch64)
      RUNTIME_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20260814/cpython-3.11.16%2B20260814-aarch64-apple-darwin-install_only.tar.gz'
      RUNTIME_SHA256='fcba9f3f676c83e07225e38116649f0c6eb94cb4fcc166632cf92769462b6e39'
      ;;
    linux-x86_64)
      RUNTIME_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20260814/cpython-3.11.16%2B20260814-x86_64-unknown-linux-gnu-install_only.tar.gz'
      RUNTIME_SHA256='33994fad90145ba559ebbe8a18d69fa7e56653502f7ba14ba07199b52cde3775'
      ;;
    *) fail "unsupported platform: $1" ;;
  esac
}

verify_checksum() {
  case "${PLATFORM}" in
    macos-aarch64)
      printf '%s  %s\n' "${RUNTIME_SHA256}" "$1" | shasum -a 256 --check --status
      ;;
    linux-x86_64)
      printf '%s  %s\n' "${RUNTIME_SHA256}" "$1" | sha256sum --check --status
      ;;
  esac
}

validate_runtime_root() {
  local runtime_root="$1"
  [ -x "${runtime_root}/bin/python3" ] || fail "missing executable python3: ${runtime_root}"
  [ -x "${runtime_root}/bin/python" ] || fail "missing executable python: ${runtime_root}"
  "${runtime_root}/bin/python3" - "${runtime_root}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
for label, value in (("sys.executable", sys.executable), ("sys.prefix", sys.prefix), ("sys.base_prefix", sys.base_prefix)):
    resolved = Path(value).resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"{label} is outside the portable runtime root: {resolved}")
PY
}

self_test() {
  PLATFORM='macos-aarch64'
  select_platform "${PLATFORM}"
  [ "${RUNTIME_SHA256}" = 'fcba9f3f676c83e07225e38116649f0c6eb94cb4fcc166632cf92769462b6e39' ] || fail 'macOS checksum changed'
  PLATFORM='linux-x86_64'
  select_platform "${PLATFORM}"
  [ "${RUNTIME_SHA256}" = '33994fad90145ba559ebbe8a18d69fa7e56653502f7ba14ba07199b52cde3775' ] || fail 'Linux checksum changed'
  if (select_platform unsupported) >/dev/null 2>&1; then fail 'unsupported platform was accepted'; fi
  printf '[portable-python-runtime] self-test passed\n' >&2
}

main() {
  local destination=''
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --platform) PLATFORM="${2:-}"; shift 2 ;;
      --destination) destination="${2:-}"; shift 2 ;;
      --self-test) self_test; return ;;
      --help|-h) usage; return ;;
      *) usage; fail "unknown argument: $1" ;;
    esac
  done
  [ -n "${PLATFORM:-}" ] || fail 'missing --platform'
  [ -n "${destination}" ] || fail 'missing --destination'
  select_platform "${PLATFORM}"
  command -v curl >/dev/null 2>&1 || fail 'curl is required'
  command -v tar >/dev/null 2>&1 || fail 'tar is required'
  mkdir -p "${destination}"
  [ -z "$(find "${destination}" -mindepth 1 -print -quit)" ] || fail "destination must be empty: ${destination}"

  archive="$(mktemp "${TMPDIR:-/tmp}/dolphin-portable-python.XXXXXX")"
  trap 'rm -f "${archive}"' EXIT
  printf '[portable-python-runtime] download %s\n' "${PLATFORM}" >&2
  curl --fail --location --retry 3 --retry-delay 1 --output "${archive}" "${RUNTIME_URL}"
  verify_checksum "${archive}"
  tar -xzf "${archive}" -C "${destination}"

  local portable_python portable_root matches
  portable_python="$(find "${destination}" -path '*/python/bin/python3' -print)"
  matches="$(printf '%s\n' "${portable_python}" | sed '/^$/d' | wc -l | tr -d ' ')"
  [ "${matches}" = 1 ] || fail "archive must contain exactly one python/bin/python3, found ${matches}"
  portable_root="$(cd "$(dirname "${portable_python}")/.." && pwd -P)"
  validate_runtime_root "${portable_root}"
  printf '%s\n' "${portable_root}"
}

main "$@"
