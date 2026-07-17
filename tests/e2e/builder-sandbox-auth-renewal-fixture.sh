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
runtime_pid=""
cp_pid=""
builder_pid=""

dump_logs() {
  local status=$?
  if [[ "${status}" -ne 0 ]]; then
    for log in "${RUNTIME_LOG}" "${CP_LOG}" "${BUILDER_LOG}"; do
      printf '\n===== %s =====\n' "${log}" >&2
      tail -120 "${log}" >&2 || true
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
cp_base_url="$("${PYTHON}" -c 'import json,sys; print(json.loads(sys.argv[1])["base_url"])' "${cp_json}")"
wait_http "${cp_base_url}/healthz" "${CP_LOG}"

builder_port="$("${PYTHON}" - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
builder_base_url="http://127.0.0.1:${builder_port}"
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
from app.code_runtime.auth import store_control_plane_credentials
from app.database import AsyncSessionLocal
from app.models import User
from app.models.ai_chat import AIChatSession
from app.models.tenant import Tenant

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
        session = AIChatSession(
            tenant_id=tenant.id,
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
            "session_ref": session.public_id,
        }))

asyncio.run(main())
PY
)"

clock_url="$("${PYTHON}" -c 'import json,sys; print(json.loads(sys.argv[1])["clock_control_url"])' "${runtime_json}")"
clock_nonce="$("${PYTHON}" -c 'import json,sys; print(json.loads(sys.argv[1])["clock_nonce"])' "${runtime_json}")"
access_token="$("${PYTHON}" -c 'import json,sys; print(json.loads(sys.argv[1])["access_token"])' "${fixture_json}")"
session_ref="$("${PYTHON}" -c 'import json,sys; print(json.loads(sys.argv[1])["session_ref"])' "${fixture_json}")"

PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_PATH}" \
BUILDER_BASE_URL="${builder_base_url}" \
CONTROL_PLANE_BASE_URL="${cp_base_url}" \
CLOCK_CONTROL_URL="${clock_url}" \
CLOCK_NONCE="${clock_nonce}" \
BUILDER_ACCESS_TOKEN="${access_token}" \
BUILDER_SESSION_REF="${session_ref}" \
BUILDER_DATABASE_PATH="${DB_PATH}" \
npm exec -- node "${ROOT_DIR}/tests/e2e/builder-sandbox-auth-renewal.spec.mjs"

"${PYTHON}" - "${DB_PATH}" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as db:
    rows = db.execute(
        "select browser_session_id, generation, runtime_session_hash "
        "from code_runtime_browser_sessions order by id"
    ).fetchall()
if len(rows) < 2:
    raise SystemExit(f"expected at least 2 browser session rows, got {len(rows)}")
if len({row[0] for row in rows}) != len(rows) or len({row[2] for row in rows}) != len(rows):
    raise SystemExit("browser session rows are not isolated")
if max(row[1] for row in rows) < 3:
    raise SystemExit(f"browser generations did not advance: {rows!r}")
print("L3_DATABASE_ISOLATION=PASS")
PY

if rg -n \
  'access-initial|refresh-initial|clock_nonce|initial_launch_token|internal_token|token=[A-Za-z0-9_-]{20,}' \
  "${RUNTIME_LOG}" "${CP_LOG}" "${BUILDER_LOG}"; then
  echo "credential canary found in service logs" >&2
  exit 1
fi

echo "L3_SANDBOX_AUTH_RENEWAL=PASS"
