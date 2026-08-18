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
NODE_VERSION="v22.19.0"
NODE_ARCHIVE="node-${NODE_VERSION}-darwin-arm64.tar.gz"
NODE_URL="https://nodejs.org/dist/${NODE_VERSION}/${NODE_ARCHIVE}"
NODE_SHA256="c59006db713c770d6ec63ae16cb3edc11f49ee093b5c415d667bb4f436c6526d"
CODEGRAPH_PACKAGE="@colbymchenry/codegraph@0.9.9"
SERENA_PACKAGE="serena-agent==1.5.1"
FRONTEND_LSP_PACKAGES=(
  "@axivo/mcp-lsp@1.0.5"
  "typescript-language-server@5.3.0"
  "typescript@7.0.2"
  "vls@0.8.5"
)
CHROME_DEVTOOLS_PACKAGE="chrome-devtools-mcp@1.0.1"

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
  CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 \
    go build -trimpath -ldflags='-s -w' \
    -o "${APPLIANCE_DIR}/bin/knowledge-mcp-proxy" \
    ./cmd/knowledge-mcp-proxy
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
cp -a "${AGENTIC_CODING_ROOT}/wrappers" "${APPLIANCE_DIR}/agentic-coding/"
# The bundled frontend LSP configuration includes these sample workspaces. Keep
# them in the appliance so its advertised projects always resolve locally.
cp -a "${AGENTIC_CODING_ROOT}/examples" "${APPLIANCE_DIR}/agentic-coding/"

printf '[local-runtime-appliance] install bundled Node and CodeGraph\n'
NODE_TEMP_DIR="$(mktemp -d)"
NODE_ARCHIVE_PATH="${NODE_TEMP_DIR}/${NODE_ARCHIVE}"
curl --fail --location --silent --show-error "${NODE_URL}" --output "${NODE_ARCHIVE_PATH}"
printf '%s  %s\n' "${NODE_SHA256}" "${NODE_ARCHIVE_PATH}" | shasum -a 256 --check --status ||
  fail "bundled Node checksum verification failed"
tar -xzf "${NODE_ARCHIVE_PATH}" -C "${NODE_TEMP_DIR}"
cp -a "${NODE_TEMP_DIR}/node-${NODE_VERSION}-darwin-arm64" "${APPLIANCE_DIR}/node"
rm -rf "${NODE_TEMP_DIR}"
require_executable "${APPLIANCE_DIR}/node/bin/node"
require_executable "${APPLIANCE_DIR}/node/bin/npm"
"${APPLIANCE_DIR}/node/bin/npm" install \
  --prefix "${APPLIANCE_DIR}/agentic-coding/.generated/codegraph" \
  --no-audit \
  --no-fund \
  --ignore-scripts \
  "${CODEGRAPH_PACKAGE}"
CODEGRAPH_BINARY="${APPLIANCE_DIR}/agentic-coding/.generated/codegraph/node_modules/.bin/codegraph"
require_executable "${CODEGRAPH_BINARY}"
ln -s "../.generated/codegraph/node_modules/.bin/codegraph" \
  "${APPLIANCE_DIR}/agentic-coding/bin/codegraph"

"${APPLIANCE_DIR}/agentic-coding/.venv/bin/python3" -m venv \
  "${APPLIANCE_DIR}/agentic-coding/.generated/serena/venv"
"${APPLIANCE_DIR}/agentic-coding/.generated/serena/venv/bin/python" -m pip install \
  --no-cache-dir "${SERENA_PACKAGE}"
mkdir -p "${APPLIANCE_DIR}/agentic-coding/.generated/serena/bin"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"' \
  'SERENA_SITE_PACKAGES="${ROOT}/.generated/serena/venv/lib/python3.11/site-packages"' \
  'export PYTHONPATH="${SERENA_SITE_PACKAGES}${PYTHONPATH:+:${PYTHONPATH}}"' \
  'exec "${ROOT}/.venv/bin/python3" -c '\''from serena.cli import top_level; raise SystemExit(top_level())'\'' "$@"' \
  > "${APPLIANCE_DIR}/agentic-coding/.generated/serena/bin/serena"
chmod 755 "${APPLIANCE_DIR}/agentic-coding/.generated/serena/bin/serena"
require_executable "${APPLIANCE_DIR}/agentic-coding/.generated/serena/bin/serena"

"${APPLIANCE_DIR}/node/bin/npm" install \
  --prefix "${APPLIANCE_DIR}/agentic-coding/.generated/frontend-lsp" \
  --no-audit \
  --no-fund \
  --ignore-scripts \
  "${FRONTEND_LSP_PACKAGES[@]}"
FRONTEND_LSP_ROOT="${APPLIANCE_DIR}/agentic-coding/.generated/frontend-lsp"
test -f "${FRONTEND_LSP_ROOT}/node_modules/@axivo/mcp-lsp/dist/index.js" ||
  fail "bundled frontend LSP MCP entrypoint is unavailable"
require_executable "${FRONTEND_LSP_ROOT}/node_modules/.bin/typescript-language-server"
require_executable "${FRONTEND_LSP_ROOT}/node_modules/.bin/vls"
mkdir -p "${APPLIANCE_DIR}/agentic-coding/.generated/lsp"
sed "s|__ROOT__|${APPLIANCE_DIR}/agentic-coding|g" \
  "${AGENTIC_CODING_ROOT}/templates/lsp/frontend-lsp.json.tpl" \
  > "${APPLIANCE_DIR}/agentic-coding/.generated/lsp/frontend-lsp.json"

"${APPLIANCE_DIR}/node/bin/npm" install \
  --prefix "${APPLIANCE_DIR}/agentic-coding/.generated/chrome-devtools" \
  --no-audit \
  --no-fund \
  --ignore-scripts \
  "${CHROME_DEVTOOLS_PACKAGE}"
require_executable "${APPLIANCE_DIR}/agentic-coding/.generated/chrome-devtools/node_modules/.bin/chrome-devtools-mcp"
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
    sed -i '' "s|${RELOCATED_APPLIANCE}/agentic-coding|${APPLIANCE_DIR}/agentic-coding|g" \
      "${RELOCATED_APPLIANCE}/agentic-coding/.generated/lsp/frontend-lsp.json"
    rm -rf "${APPLIANCE_DIR}"
    mv "${RELOCATED_APPLIANCE}" "${APPLIANCE_DIR}"
  fi
  [ -z "${TMP_CODEX_HOME}" ] || rm -rf "${TMP_CODEX_HOME}"
  rm -rf "${RELOCATION_PARENT}"
  exit "${status}"
}
trap cleanup EXIT
mv "${APPLIANCE_DIR}" "${RELOCATED_APPLIANCE}"
sed -i '' "s|${APPLIANCE_DIR}/agentic-coding|${RELOCATED_APPLIANCE}/agentic-coding|g" \
  "${RELOCATED_APPLIANCE}/agentic-coding/.generated/lsp/frontend-lsp.json"
"${RELOCATED_APPLIANCE}/codex/bin/codex" --version >/dev/null
test -x "${RELOCATED_APPLIANCE}/agentic-coding/.venv/bin/python3" ||
  fail "agentic-coding Python runtime is unavailable in appliance"
test -x "${RELOCATED_APPLIANCE}/node/bin/node" ||
  fail "bundled Node runtime is unavailable in appliance"
test -x "${RELOCATED_APPLIANCE}/bin/knowledge-mcp-proxy" ||
  fail "bundled knowledge MCP proxy is unavailable in appliance"
test -x "${RELOCATED_APPLIANCE}/agentic-coding/wrappers/semantic/mcp-codegraph" ||
  fail "CodeGraph MCP wrapper is unavailable in appliance"
PATH="${RELOCATED_APPLIANCE}/agentic-coding/bin:${RELOCATED_APPLIANCE}/node/bin:${PATH}" \
  codegraph --version >/dev/null || fail "bundled CodeGraph CLI is unavailable in appliance"
"${RELOCATED_APPLIANCE}/agentic-coding/.generated/serena/bin/serena" --help >/dev/null ||
  fail "bundled Serena MCP runtime is unavailable in appliance"
test -f "${RELOCATED_APPLIANCE}/agentic-coding/.generated/frontend-lsp/node_modules/@axivo/mcp-lsp/dist/index.js" ||
  fail "bundled frontend LSP MCP runtime is unavailable in appliance"
test -x "${RELOCATED_APPLIANCE}/agentic-coding/.generated/chrome-devtools/node_modules/.bin/chrome-devtools-mcp" ||
  fail "bundled Chrome DevTools MCP runtime is unavailable in appliance"
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
DOLPHIN_CODE_AGENTIC_PACK_DIR="${RELOCATED_APPLIANCE}/agentic-coding-pack" \
DOLPHIN_CODE_KNOWLEDGE_MCP_PROXY_PATH="${RELOCATED_APPLIANCE}/bin/knowledge-mcp-proxy" \
  "${RELOCATED_APPLIANCE}/agentic-coding-pack/bin/agentic-pack-reconcile" \
    --codex-home "${TMP_CODEX_HOME}" >/dev/null 2>&1 || reconcile_status="$?"
case "${reconcile_status}" in
  0|10) ;;
  *) fail "offline agentic pack reconcile failed with exit code ${reconcile_status}" ;;
esac
test -f "${TMP_CODEX_HOME}/skills/superpowers/brainstorming/SKILL.md" ||
  fail "reconciled Codex home is missing required skills"
"${RELOCATED_APPLIANCE}/agentic-coding/.venv/bin/python3" - \
  "${TMP_CODEX_HOME}/config.toml" \
  "${RELOCATED_APPLIANCE}/agentic-coding/.generated/lsp/frontend-lsp.json" \
  "${AGENTIC_CODING_ROOT}" \
  "${PORTABLE_PYTHON_ROOT}" <<'PY'
from pathlib import Path
import os
import sys
import tomllib

config_path = Path(sys.argv[1])
config = tomllib.loads(config_path.read_text(encoding="utf-8"))
servers = config.get("mcp_servers", {})
required = {
    "serena",
    "codegraph",
    "frontend-lsp",
    "chrome-devtools",
    "control-plane-application-templates",
    "control-plane-application-environments",
    "control-plane-application-capabilities",
    "knowledge-server",
}
missing = required - set(servers)
if missing:
    raise SystemExit(f"reconciled desktop MCP configuration is missing: {sorted(missing)}")
unrunnable = []
for name, server in servers.items():
    if not isinstance(server, dict) or not isinstance(server.get("command"), str):
        unrunnable.append(f"{name}: missing command")
        continue
    command = Path(server["command"])
    if not command.is_file() or not os.access(command, os.X_OK):
        unrunnable.append(f"{name}: {command}")
if unrunnable:
    raise SystemExit("reconciled desktop MCP commands are not runnable: " + "; ".join(unrunnable))

lsp_config = Path(sys.argv[2])
lsp_payload = __import__("json").loads(lsp_config.read_text(encoding="utf-8"))
runner_roots = [Path(value).resolve() for value in sys.argv[3:]]
for server in lsp_payload.get("servers", {}).values():
    for project in server.get("projects", []):
        project_path = Path(project["path"]).resolve()
        if not project_path.is_dir():
            raise SystemExit(f"bundled frontend LSP project is missing: {project_path}")
        if any(project_path == root or root in project_path.parents for root in runner_roots):
            raise SystemExit(f"bundled frontend LSP project still references a build runner: {project_path}")
PY

printf '[local-runtime-appliance] complete: %s\n' "${APPLIANCE_DIR}"
