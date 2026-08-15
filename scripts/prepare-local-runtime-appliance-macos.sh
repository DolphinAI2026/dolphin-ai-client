#!/usr/bin/env bash
# 构建 macOS arm64 桌面本地运行时使用的受信任 appliance。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_RUNTIME_REPO="${AGENT_RUNTIME_REPO:-${ROOT}/../agent-runtime}"
AGENTIC_CODING_ROOT="${AGENTIC_CODING_ROOT:-${ROOT}/../agentic-coding}"
AGENTIC_SUPERPOWERS_SOURCE="${AGENTIC_SUPERPOWERS_SOURCE:-${ROOT}/../superpowers}"
APPLIANCE_DIR="${LOCAL_RUNTIME_APPLIANCE_DIR:-${ROOT}/src-tauri/resources/agent-runtime}"
CODEX_NATIVE_ROOT="${CODEX_NATIVE_ROOT:-}"
BUILDER_DIST="${AGENT_RUNTIME_REPO}/web/builder/dist"

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

require_directory "${AGENT_RUNTIME_REPO}"
require_directory "${AGENTIC_CODING_ROOT}"
require_directory "${AGENTIC_SUPERPOWERS_SOURCE}"
require_directory "${BUILDER_DIST}"
[ -f "${AGENTIC_SUPERPOWERS_SOURCE}/.codex-plugin/plugin.json" ] ||
  fail "missing Superpowers plugin manifest: ${AGENTIC_SUPERPOWERS_SOURCE}"
find "${AGENTIC_SUPERPOWERS_SOURCE}/skills" -mindepth 2 -maxdepth 2 -name SKILL.md -type f -print -quit | grep -q . ||
  fail "Superpowers source has no skills: ${AGENTIC_SUPERPOWERS_SOURCE}"
[ -f "${BUILDER_DIST}/index.html" ] || fail "missing Builder entrypoint: ${BUILDER_DIST}/index.html"
grep -q 'type="module"' "${BUILDER_DIST}/index.html" ||
  fail "Builder entrypoint does not reference a module bundle: ${BUILDER_DIST}/index.html"
require_executable "${AGENTIC_CODING_ROOT}/bin/agentic-pack"
require_executable "${AGENTIC_CODING_ROOT}/.venv/bin/python"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64|Darwin-aarch64) ;;
  *) fail "this appliance builder only supports macOS arm64" ;;
esac

[ -n "${CODEX_NATIVE_ROOT}" ] || fail "set CODEX_NATIVE_ROOT to the installed @openai/codex macOS package"
CODEX_VENDOR="${CODEX_NATIVE_ROOT}/vendor/aarch64-apple-darwin"
require_executable "${CODEX_VENDOR}/bin/codex"

PACK_PYTHON="${AGENTIC_CODING_ROOT}/.venv/bin/python"
require_executable "${PACK_PYTHON}"

rm -rf "${APPLIANCE_DIR}"
mkdir -p "${APPLIANCE_DIR}/bin"

printf '[local-runtime-appliance] build agent-runtime\n'
(
  cd "${AGENT_RUNTIME_REPO}"
  CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 \
    go build -trimpath -ldflags='-s -w' \
    -o "${APPLIANCE_DIR}/bin/agent-runtime" \
    ./cmd/sandbox-runtime
)

printf '[local-runtime-appliance] copy native Codex\n'
cp -a "${CODEX_VENDOR}" "${APPLIANCE_DIR}/codex"

printf '[local-runtime-appliance] copy Builder workbench\n'
mkdir -p "${APPLIANCE_DIR}/web/builder"
cp -a "${BUILDER_DIST}" "${APPLIANCE_DIR}/web/builder/"
[ -f "${APPLIANCE_DIR}/web/builder/dist/index.html" ] ||
  fail "Builder entrypoint was not copied into appliance"
grep -q 'type="module"' "${APPLIANCE_DIR}/web/builder/dist/index.html" ||
  fail "appliance Builder entrypoint does not reference a module bundle"

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
  --superpowers-source "${AGENTIC_SUPERPOWERS_SOURCE}" \
  "${AGENTIC_CODING_ROOT}"

find "${APPLIANCE_DIR}/agentic-coding-pack" \( -type d -o -type f \) -name .git \
  -prune -exec rm -rf {} +

PYTHONPATH="${AGENTIC_CODING_ROOT}/python" "${PACK_PYTHON}" - "${APPLIANCE_DIR}/agentic-coding-pack" <<'PY'
from pathlib import Path
import sys

from agentic_core.pack.checksums import compute_pack_digest

pack_dir = Path(sys.argv[1])
manifest_path = pack_dir / "manifest.yaml"
digest = compute_pack_digest(pack_dir)
lines = manifest_path.read_text(encoding="utf-8").splitlines(keepends=True)
in_pack = False
for index, line in enumerate(lines):
    if line.strip() == "pack:":
        in_pack = True
        continue
    if in_pack and line.startswith("  digest:"):
        newline = "\n" if line.endswith("\n") else ""
        lines[index] = f"  digest: {digest}{newline}"
        break
    if in_pack and line and not line.startswith(" "):
        raise SystemExit("pack digest field is missing from manifest")
else:
    raise SystemExit("pack digest field is missing from manifest")
manifest_path.write_text("".join(lines), encoding="utf-8")
PY

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
