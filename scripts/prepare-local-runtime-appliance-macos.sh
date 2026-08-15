#!/usr/bin/env bash
# 构建 macOS arm64 桌面本地运行时使用的受信任 appliance。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_RUNTIME_REPO="${AGENT_RUNTIME_REPO:-${ROOT}/../agent-runtime}"
AGENTIC_CODING_ROOT="${AGENTIC_CODING_ROOT:-${ROOT}/../agentic-coding}"
AGENTIC_SUPERPOWERS_SOURCE="${AGENTIC_SUPERPOWERS_SOURCE:-${ROOT}/../superpowers}"
PORTABLE_PYTHON_ROOT="${PORTABLE_PYTHON_ROOT:-}"
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
require_directory "${PORTABLE_PYTHON_ROOT}"
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
require_executable "${PORTABLE_PYTHON_ROOT}/bin/python3"

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
  "${PORTABLE_PYTHON_ROOT}" \
  "${APPLIANCE_DIR}/agentic-coding/.venv"
cp -a \
  "${AGENTIC_CODING_ROOT}/bin" \
  "${APPLIANCE_DIR}/agentic-coding/"
cp -a "${AGENTIC_CODING_ROOT}/python" "${APPLIANCE_DIR}/agentic-coding/"
APPLIANCE_PYTHON="${APPLIANCE_DIR}/agentic-coding/.venv/bin/python3"
APPLIANCE_PURELIB="$("${APPLIANCE_PYTHON}" - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
)"
mkdir -p "${APPLIANCE_PURELIB}"
"${APPLIANCE_PYTHON}" -m pip --version >/dev/null 2>&1 || "${APPLIANCE_PYTHON}" -m ensurepip --upgrade
"${APPLIANCE_PYTHON}" -m pip install --no-cache-dir --target "${APPLIANCE_PURELIB}" \
  -r "${AGENTIC_CODING_ROOT}/requirements.txt"

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

printf '[local-runtime-appliance] validate relocated Codex, Python, and pack reconcile\n'
APPLIANCE_PARENT="$(dirname "${APPLIANCE_DIR}")"
RELOCATION_PARENT="$(mktemp -d "${APPLIANCE_PARENT}/.agent-runtime-relocation-XXXXXX")"
RELOCATED_APPLIANCE="${RELOCATION_PARENT}/agent-runtime"
TMP_CODEX_HOME=""
cleanup() {
  local status="$?"
  trap - EXIT
  if [ -d "${RELOCATED_APPLIANCE}" ]; then
    rm -rf "${APPLIANCE_DIR}"
    mv "${RELOCATED_APPLIANCE}" "${APPLIANCE_DIR}"
  fi
  [ -z "${TMP_CODEX_HOME}" ] || rm -rf "${TMP_CODEX_HOME}"
  rm -rf "${RELOCATION_PARENT}"
  exit "${status}"
}
trap cleanup EXIT
mv "${APPLIANCE_DIR}" "${RELOCATED_APPLIANCE}"
"${RELOCATED_APPLIANCE}/codex/bin/codex" --version >/dev/null
test -x "${RELOCATED_APPLIANCE}/agentic-coding/.venv/bin/python3" ||
  fail "agentic-coding Python runtime is unavailable in appliance"
"${RELOCATED_APPLIANCE}/agentic-coding/.venv/bin/python3" - \
  "${RELOCATED_APPLIANCE}/agentic-coding/.venv" \
  "${AGENTIC_CODING_ROOT}" \
  "${PORTABLE_PYTHON_ROOT}" <<'PY'
from pathlib import Path
import sys

expected_root = Path(sys.argv[1]).resolve()
runner_roots = [Path(value).resolve() for value in sys.argv[2:]]
for label, value in (("sys.executable", sys.executable), ("sys.prefix", sys.prefix)):
    resolved = Path(value).resolve()
    if resolved != expected_root and expected_root not in resolved.parents:
        raise SystemExit(f"{label} is outside the relocated appliance: {resolved}")
    if any(resolved == root or root in resolved.parents for root in runner_roots):
        raise SystemExit(f"{label} still references a build runner path: {resolved}")
PY
TMP_CODEX_HOME="$(mktemp -d)"
reconcile_status=0
AGENTIC_ROOT="${RELOCATED_APPLIANCE}/agentic-coding" \
AGENTIC_PACK_PYTHON="${RELOCATED_APPLIANCE}/agentic-coding/.venv/bin/python3" \
  "${RELOCATED_APPLIANCE}/agentic-coding-pack/bin/agentic-pack-reconcile" \
    --codex-home "${TMP_CODEX_HOME}" >/dev/null 2>&1 || reconcile_status="$?"
case "${reconcile_status}" in
  0|10) ;;
  *) fail "offline agentic pack reconcile failed with exit code ${reconcile_status}" ;;
esac
test -f "${TMP_CODEX_HOME}/skills/superpowers/brainstorming/SKILL.md" ||
  fail "reconciled Codex home is missing required skills"

printf '[local-runtime-appliance] complete: %s\n' "${APPLIANCE_DIR}"
