#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_REPO="${AGENT_RUNTIME_REPO:?AGENT_RUNTIME_REPO is required}"
PYTHON="${BUILDER_PYTHON:-${ROOT_DIR}/backend/venv/bin/python}"
if [[ ! -x "${PYTHON}" ]] && [[ -x /mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python ]]; then
  PYTHON=/mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python
fi
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3)"
fi
PLAYWRIGHT_PATH="${PLAYWRIGHT_BROWSERS_PATH:?PLAYWRIGHT_BROWSERS_PATH is required}"
TMP_DIR="$(mktemp -d -t builder-auth-renewal.XXXXXX)"
RUNTIME_LOG="${TMP_DIR}/runtime.log"
CP_LOG="${TMP_DIR}/control-plane.log"
BUILDER_LOG="${TMP_DIR}/builder.log"
RUNTIME_READY="${TMP_DIR}/runtime.json"
DB_PATH="${TMP_DIR}/builder.db"
BROWSER_SECRET_EVIDENCE="${TMP_DIR}/browser-secrets.json"
runtime_pid=""
cp_pid=""
builder_pid=""

dump_logs() {
  local status=$?
  if [[ "${status}" -ne 0 ]]; then
    for log in "${RUNTIME_LOG}" "${CP_LOG}" "${BUILDER_LOG}"; do
      printf '\n===== %s =====\n' "${log}" >&2
      "${PYTHON}" - "${log}" "${RUNTIME_READY}" "${BROWSER_SECRET_EVIDENCE}" <<'PY' >&2 || true
import json
import re
import sys

log_path, runtime_ready, browser_evidence = sys.argv[1:]
secrets = []
for path, key in (
    (runtime_ready, "initial_launch_token"),
    (runtime_ready, "clock_nonce"),
    (runtime_ready, "internal_token"),
):
    try:
        with open(path, encoding="utf-8") as handle:
            value = str(json.load(handle).get(key) or "")
        if value:
            secrets.append(value)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
try:
    with open(browser_evidence, encoding="utf-8") as handle:
        secrets.extend(str(value) for value in json.load(handle).get("runtime_cookies", []))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass

with open(log_path, encoding="utf-8", errors="replace") as handle:
    text = "".join(handle.readlines()[-120:])
for value in secrets:
    text = text.replace(value, "[REDACTED]")
text = re.sub(r"(AUTH_RENEWAL_FIXTURE=).*", r"\1[REDACTED]", text)
text = re.sub(
    r"(\?\s*token\s*=\s*)(?:[A-Za-z0-9_-]\s*){20,}",
    r"\1[REDACTED]",
    text,
)
sys.stderr.write(text)
PY
    done
  fi
  return "${status}"
}

cleanup() {
  for pid in "${builder_pid}" "${cp_pid}" "${runtime_pid}"; do
    if [[ -n "${pid}" ]]; then
      kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  rm -rf "${TMP_DIR}"
}
trap dump_logs ERR
trap cleanup EXIT INT TERM

wait_line() {
  local file="$1" prefix="$2"
  for _ in $(seq 1 150); do
    if grep -q "^${prefix}" "${file}" 2>/dev/null; then
      grep "^${prefix}" "${file}" | tail -1 | sed "s/^${prefix}//"
      return 0
    fi
    sleep 0.1
  done
  printf 'readiness timeout: %s\n' "${file}" >&2
  tail -80 "${file}" >&2 || true
  return 1
}

wait_http() {
  local url="$1" log="$2"
  for _ in $(seq 1 150); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  printf 'HTTP readiness timeout: %s\n' "${url}" >&2
  tail -80 "${log}" >&2 || true
  return 1
}

(
  cd "${RUNTIME_REPO}"
  go run ./tests/e2e/authrenewalfixture
) >"${RUNTIME_LOG}" 2>&1 &
runtime_pid=$!
runtime_json="$(wait_line "${RUNTIME_LOG}" "AUTH_RENEWAL_FIXTURE=")"
printf '%s\n' "${runtime_json}" >"${RUNTIME_READY}"
sed -i 's/^AUTH_RENEWAL_FIXTURE=.*/AUTH_RENEWAL_FIXTURE=[REDACTED]/' "${RUNTIME_LOG}"

"${PYTHON}" "${ROOT_DIR}/tests/e2e/fixtures/fake_control_plane.py" \
  --runtime-readiness "${RUNTIME_READY}" >"${CP_LOG}" 2>&1 &
cp_pid=$!
cp_json="$(wait_line "${CP_LOG}" "FAKE_CONTROL_PLANE=")"
cp_base_url="$(printf '%s' "${cp_json}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["base_url"])')"
wait_http "${cp_base_url}/healthz" "${CP_LOG}"

builder_port="$("${PYTHON}" - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
builder_base_url="http://localhost:${builder_port}"
export DATABASE_URL="sqlite+aiosqlite:///${DB_PATH}"
export JWT_SECRET_KEY="builder-e2e-jwt-secret"
export LLM_API_KEY="builder-e2e-llm-key"
export APAAS_ENCRYPTION_KEY="builder-e2e-encryption-key-32byte"
export ALLOW_DEFAULT_ENCRYPTION_KEY=1
export AUTH_PROVIDER=control_plane
export BUILDER_AUTH_DEFAULT_LOGIN_PROVIDER=control_plane
export DOLPHIN_WORKSPACE_BASE_URL="${cp_base_url}"
export DOLPHIN_CODE_CONTROL_PLANE_URL="${cp_base_url}"
export ACCEPTED_TOKEN_ISSUERS=ai-builder

(
  cd "${ROOT_DIR}/backend"
  exec "${PYTHON}" -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "${builder_port}" \
    --no-access-log
) >"${BUILDER_LOG}" 2>&1 &
builder_pid=$!
wait_http "${builder_base_url}/api/code/internal/sandbox-auth-state" "${BUILDER_LOG}"

fixture_json="$(
  cd "${ROOT_DIR}/backend"
  "${PYTHON}" - <<'PY'
import asyncio
import json
from sqlalchemy import select
from app.auth import create_access_token
from app.code_runtime.service import code_session_route_id
from app.code_runtime.auth import store_control_plane_credentials
from app.database import AsyncSessionLocal
from app.models import User
from app.models.ai_chat import AIChatSession
from app.models.tenant import Tenant, UserTenant

async def main():
    async with AsyncSessionLocal() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.tenant_code == "workspace-tenant-e2e"))).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(tenant_name="E2E Tenant", tenant_code="workspace-tenant-e2e")
            db.add(tenant)
            await db.flush()
        user = User(
            username="same-account-e2e",
            display_name="Same Account E2E",
            hashed_password="!",
            account_source="control_plane",
            coding_user_id="user-e2e",
            coding_tenant_id="tenant-e2e",
            is_platform_admin=True,
        )
        store_control_plane_credentials(user, "access-initial", "refresh-initial")
        db.add(user)
        await db.flush()
        db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
        session = AIChatSession(
            tenant_id=tenant.id,
            control_plane_tenant_id="tenant-e2e",
            user_id=user.id,
            title="Auth renewal E2E",
            status="active",
            mode="code",
            external_application_id="app-e2e",
            external_app_name="Auth renewal E2E",
        )
        db.add(session)
        await db.commit()
        print(json.dumps({
            "access_token": create_access_token(user, tenant_id=tenant.id),
            "session_ref": code_session_route_id(session.id),
        }))

asyncio.run(main())
PY
)"

clock_url="$(printf '%s' "${runtime_json}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["clock_control_url"])')"
clock_nonce="$(printf '%s' "${runtime_json}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["clock_nonce"])')"
access_token="$(printf '%s' "${fixture_json}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
session_ref="$(printf '%s' "${fixture_json}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["session_ref"])')"

PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_PATH}" \
BUILDER_BASE_URL="${builder_base_url}" \
CONTROL_PLANE_BASE_URL="${cp_base_url}" \
CLOCK_CONTROL_URL="${clock_url}" \
CLOCK_NONCE="${clock_nonce}" \
BUILDER_ACCESS_TOKEN="${access_token}" \
BUILDER_SESSION_REF="${session_ref}" \
BUILDER_DATABASE_PATH="${DB_PATH}" \
BROWSER_SECRET_EVIDENCE_PATH="${BROWSER_SECRET_EVIDENCE}" \
npm exec -- node "${ROOT_DIR}/tests/e2e/builder-sandbox-auth-renewal.spec.mjs"

initial_launch_token="$(printf '%s' "${runtime_json}" \
  | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["initial_launch_token"])')"
printf '{"database_path":"%s","launch_tokens":["%s"]}' \
  "${DB_PATH}" "${initial_launch_token}" \
  | "${PYTHON}" "${ROOT_DIR}/tests/e2e/fixtures/verify_sandbox_auth_db.py"
unset initial_launch_token

"${PYTHON}" -c '
import json
import re
import sys

runtime_ready, browser_evidence, *logs = sys.argv[1:]
with open(runtime_ready, encoding="utf-8") as handle:
    launch_token = str(json.load(handle)["initial_launch_token"])
with open(browser_evidence, encoding="utf-8") as handle:
    runtime_cookies = [str(value) for value in json.load(handle)["runtime_cookies"]]
if not runtime_cookies:
    raise SystemExit("runtime cookie evidence is empty")

literal_canaries = [
    "access-initial",
    "refresh-initial",
    "clock_nonce",
    "initial_launch_token",
    "internal_token",
    "local-auth-disabled",
]
secret_canaries = [launch_token, *runtime_cookies]
url_canary = re.compile(r"\?\s*token\s*=\s*(?:[A-Za-z0-9_-]\s*){20,}")
for log_path in logs:
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    compact_text = re.sub(r"\s+", "", text)
    if (
        any(value and value in text for value in literal_canaries)
        or any(value and (value in text or value in compact_text) for value in secret_canaries)
        or url_canary.search(text)
    ):
        raise SystemExit(f"credential canary found in service log: {log_path}")
' "${RUNTIME_READY}" "${BROWSER_SECRET_EVIDENCE}" \
  "${RUNTIME_LOG}" "${CP_LOG}" "${BUILDER_LOG}"

echo "L3_SANDBOX_AUTH_RENEWAL=PASS"
