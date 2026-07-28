#!/usr/bin/env bash
# 构建 Linux 桌面本地运行时使用的受信任 appliance。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_RUNTIME_REPO="${AGENT_RUNTIME_REPO:-${ROOT}/../agent-runtime}"
AGENTIC_CODING_ROOT="${AGENTIC_CODING_ROOT:-${ROOT}/../agentic-coding}"
APPLIANCE_DIR="${LOCAL_RUNTIME_APPLIANCE_DIR:-${ROOT}/src-tauri/resources/agent-runtime}"
CODEX_NATIVE_ROOT="${CODEX_NATIVE_ROOT:-}"

fail() {
  printf '[local-runtime-appliance] %s\n' "$*" >&2
  exit 1
}

require_directory() {
  [ -d "$1" ] || fail "missing directory: $1"
}

require_executable() {
  [ -x "$1" ] || fail "missing executable: $1"
}

resolve_codex_native_root() {
  if [ -n "${CODEX_NATIVE_ROOT}" ]; then
    printf '%s\n' "${CODEX_NATIVE_ROOT}"
    return
  fi
  local pnpm_home="${PNPM_HOME:-${HOME}/.local/share/pnpm}"
  local package_root="${pnpm_home}/global/5/.pnpm"
  local candidate=""
  [ -d "${package_root}" ] || fail "set CODEX_NATIVE_ROOT to the installed @openai/codex Linux package"
  candidate="$(find "${package_root}" -maxdepth 1 -type d -name '@openai+codex@*-linux-x64' -print | sort | tail -n 1)"
  [ -n "${candidate}" ] || fail "set CODEX_NATIVE_ROOT to the installed @openai/codex Linux package"
  printf '%s/node_modules/@openai/codex\n' "${candidate}"
}

require_directory "${AGENT_RUNTIME_REPO}"
require_directory "${AGENTIC_CODING_ROOT}"
require_executable "${AGENTIC_CODING_ROOT}/bin/agentic-pack"
require_executable "${AGENTIC_CODING_ROOT}/.venv/bin/python"

CODEX_NATIVE_ROOT="$(resolve_codex_native_root)"
CODEX_VENDOR="${CODEX_NATIVE_ROOT}/vendor/x86_64-unknown-linux-musl"
require_executable "${CODEX_VENDOR}/bin/codex"

PACK_PYTHON="$(readlink -f "${AGENTIC_CODING_ROOT}/.venv/bin/python")"
require_executable "${PACK_PYTHON}"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) ;;
  *) fail "this appliance builder only supports Linux x86_64" ;;
esac

rm -rf "${APPLIANCE_DIR}"
mkdir -p "${APPLIANCE_DIR}/bin"

printf '[local-runtime-appliance] build agent-runtime\n'
(
  cd "${AGENT_RUNTIME_REPO}"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags='-s -w' \
    -o "${APPLIANCE_DIR}/bin/agent-runtime" \
    ./cmd/sandbox-runtime
)

printf '[local-runtime-appliance] copy native Codex\n'
cp -a "${CODEX_VENDOR}" "${APPLIANCE_DIR}/codex"

printf '[local-runtime-appliance] copy agentic-coding runtime\n'
mkdir -p "${APPLIANCE_DIR}/agentic-coding"
cp -a \
  "${AGENTIC_CODING_ROOT}/.venv" \
  "${AGENTIC_CODING_ROOT}/bin" \
  "${AGENTIC_CODING_ROOT}/python" \
  "${APPLIANCE_DIR}/agentic-coding/"

printf '[local-runtime-appliance] build offline agentic pack\n'
"${AGENTIC_CODING_ROOT}/bin/agentic-pack" build \
  --profile sandbox-container \
  --output "${APPLIANCE_DIR}/agentic-coding-pack" \
  "${AGENTIC_CODING_ROOT}"

printf '[local-runtime-appliance] validate Codex and pack reconcile\n'
"${APPLIANCE_DIR}/codex/bin/codex" --version >/dev/null
test -x "${APPLIANCE_DIR}/agentic-coding/.venv/bin/python" ||
  fail "agentic-coding Python runtime is unavailable in appliance"
TMP_CODEX_HOME="$(mktemp -d)"
trap 'rm -rf "${TMP_CODEX_HOME}"' EXIT
reconcile_status=0
AGENTIC_ROOT="${APPLIANCE_DIR}/agentic-coding" \
AGENTIC_PACK_PYTHON="${APPLIANCE_DIR}/agentic-coding/.venv/bin/python" \
  "${APPLIANCE_DIR}/agentic-coding-pack/bin/agentic-pack-reconcile" \
    --codex-home "${TMP_CODEX_HOME}" >/dev/null 2>&1 || reconcile_status="$?"
case "${reconcile_status}" in
  0|10) ;;
  *) fail "offline agentic pack reconcile failed with exit code ${reconcile_status}" ;;
esac
test -f "${TMP_CODEX_HOME}/skills/superpowers/brainstorming/SKILL.md" ||
  fail "reconciled Codex home is missing required skills"

printf '[local-runtime-appliance] complete: %s\n' "${APPLIANCE_DIR}"
