#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${BUILDER_PYTHON:-}"
if [[ -z "${PYTHON}" ]] && [[ -x "${ROOT_DIR}/backend/venv/bin/python" ]]; then
  PYTHON="${ROOT_DIR}/backend/venv/bin/python"
fi
if [[ -z "${PYTHON}" ]] \
  && [[ -x "/mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python" ]]; then
  PYTHON="/mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend/venv/bin/python"
fi
if [[ -z "${PYTHON}" ]]; then
  PYTHON="$(command -v python3)"
fi
if ! "${PYTHON}" -c 'import sqlalchemy, uvicorn' >/dev/null 2>&1; then
  printf 'backend Python lacks required packages: %s\n' "${PYTHON}" >&2
  exit 2
fi

BROWSER_CHANNEL="${BROWSER_CHANNEL:?BROWSER_CHANNEL must be chromium or msedge}"
if [[ "${BROWSER_CHANNEL}" != "chromium" && "${BROWSER_CHANNEL}" != "msedge" ]]; then
  printf 'unsupported BROWSER_CHANNEL=%s\n' "${BROWSER_CHANNEL}" >&2
  exit 2
fi

for executable in \
  "${ROOT_DIR}/node_modules/.bin/playwright" \
  "${ROOT_DIR}/frontend/node_modules/.bin/vite" \
  "${ROOT_DIR}/frontend/node_modules/.bin/vue-tsc"; do
  if [[ ! -x "${executable}" ]]; then
    printf 'missing dependency executable: %s; run root and frontend npm ci first\n' \
      "${executable}" >&2
    exit 2
  fi
done

BUILD_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
if [[ ! "${BUILD_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'git HEAD is not a full lowercase SHA: %s\n' "${BUILD_SHA}" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d -t builder-tenant-url.XXXXXX)"
DB_PATH="${TMP_DIR}/builder.db"
BUILD_LOG="${TMP_DIR}/build.log"
BACKEND_LOG="${TMP_DIR}/backend.log"
FRONTEND_LOG="${TMP_DIR}/frontend.log"
RUNTIME_LOG="${TMP_DIR}/runtime.log"
PLAYWRIGHT_LOG="${TMP_DIR}/playwright.log"
SEED_LOG="${TMP_DIR}/seed.log"
backend_pid=""
frontend_pid=""
runtime_pid=""
E2E_PASSWORD="Task6-local-password"
E2E_USERNAME="task6-tenant-user"

redacted_tail() {
  local log="$1"
  [[ -f "${log}" ]] || return 0
  tail -160 "${log}" \
    | sed -E \
      -e "s/${E2E_PASSWORD}/[REDACTED_PASSWORD]/g" \
      -e 's/(Bearer )[A-Za-z0-9._-]+/\1[REDACTED_TOKEN]/g' \
      -e 's/[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/[REDACTED_JWT]/g'
}

dump_logs() {
  local status=$?
  if [[ "${status}" -ne 0 ]]; then
    for log in \
      "${BUILD_LOG}" \
      "${RUNTIME_LOG}" \
      "${BACKEND_LOG}" \
      "${SEED_LOG}" \
      "${TMP_DIR}/fixture.json" \
      "${FRONTEND_LOG}" \
      "${PLAYWRIGHT_LOG}"; do
      printf '\n===== %s =====\n' "${log}" >&2
      redacted_tail "${log}" >&2 || true
    done
  fi
  return "${status}"
}

cleanup() {
  for pid in "${frontend_pid}" "${backend_pid}" "${runtime_pid}"; do
    if [[ -n "${pid}" ]]; then
      kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  rm -rf "${TMP_DIR}"
}

trap dump_logs ERR
trap cleanup EXIT INT TERM

free_port() {
  "${PYTHON}" - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

wait_http() {
  local url="$1" log="$2"
  for _ in $(seq 1 300); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  printf 'HTTP readiness timeout: %s\n' "${url}" >&2
  redacted_tail "${log}" >&2 || true
  return 1
}

printf 'BUILD_SHA=%s\n' "${BUILD_SHA}"
(
  cd "${ROOT_DIR}"
  VITE_BUILD_SHA="${BUILD_SHA}" npm --prefix frontend run build
) >"${BUILD_LOG}" 2>&1

DIST_INDEX="${ROOT_DIR}/frontend/dist/index.html"
if [[ ! -f "${DIST_INDEX}" ]]; then
  printf 'frontend build did not produce %s\n' "${DIST_INDEX}" >&2
  exit 1
fi
META_SHA="$("${PYTHON}" - "${DIST_INDEX}" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
matches = re.findall(
    r'<meta\s+name="builder-build-sha"\s+content="([0-9a-f]{40})"\s*/?>',
    text,
)
if len(matches) != 1:
    raise SystemExit(f"expected one builder-build-sha meta, got {matches!r}")
print(matches[0])
PY
)"
if [[ "${META_SHA}" != "${BUILD_SHA}" ]]; then
  printf 'build SHA meta mismatch: expected=%s actual=%s\n' "${BUILD_SHA}" "${META_SHA}" >&2
  exit 1
fi

runtime_port="$(free_port)"
backend_port="$(free_port)"
frontend_port="$(free_port)"
runtime_base_url="http://127.0.0.1:${runtime_port}"
backend_base_url="http://127.0.0.1:${backend_port}"
builder_base_url="http://127.0.0.1:${frontend_port}"

cat >"${TMP_DIR}/fake_runtime.py" <<'PY'
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def _write(self, status, body, content_type):
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlsplit(self.path)
        print(f"runtime_request method=GET path={parsed.path} query={parsed.query}", flush=True)
        if parsed.path in {"/healthz", "/builder", "/builder/"}:
            if parsed.path == "/healthz":
                self._write(200, "ok", "text/plain")
                return
            self._write(
                200,
                (
                    "<!doctype html><html><body><main id=\"runtime-ready\">"
                    "Task 6 Runtime</main></body></html>"
                ),
                "text/html; charset=utf-8",
            )
            return
        if parsed.path == "/api/agent/sessions":
            self._write(
                200,
                json.dumps({"sessions": []}, separators=(",", ":")),
                "application/json",
            )
            return
        self._write(404, "not found", "text/plain")

    def do_POST(self):
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or "0")
        if length:
            self.rfile.read(length)
        print(f"runtime_request method=POST path={parsed.path} query={parsed.query}", flush=True)
        prefix = "/api/agent/sessions/"
        if parsed.path.startswith(prefix) and parsed.path.endswith("/activate"):
            runtime_id = parsed.path[len(prefix) : -len("/activate")].strip("/")
            self._write(
                200,
                json.dumps(
                    {
                        "runtimeSessionId": runtime_id,
                        "title": "Task 6 Agent",
                        "state": "waiting_input",
                    },
                    separators=(",", ":"),
                ),
                "application/json",
            )
            return
        self._write(404, "not found", "text/plain")


server = ThreadingHTTPServer(("127.0.0.1", int(os.environ["RUNTIME_PORT"])), Handler)
server.serve_forever()
PY

RUNTIME_PORT="${runtime_port}" "${PYTHON}" "${TMP_DIR}/fake_runtime.py" \
  >"${RUNTIME_LOG}" 2>&1 &
runtime_pid=$!
wait_http "${runtime_base_url}/healthz" "${RUNTIME_LOG}"

export DATABASE_URL="sqlite+aiosqlite:///${DB_PATH}"
export JWT_SECRET_KEY="task6-builder-jwt-secret"
export LLM_API_KEY="task6-builder-llm-key"
export APAAS_ENCRYPTION_KEY="task6-builder-encryption-key-32b"
export ALLOW_DEFAULT_ENCRYPTION_KEY=1
export AUTH_PROVIDER=local
export BUILDER_AUTH_DEFAULT_LOGIN_PROVIDER=local
export ACCEPTED_TOKEN_ISSUERS=ai-builder
export DOLPHIN_CODE_BUILDER_URL="${runtime_base_url}/builder/"
export DOLPHIN_CODE_ALLOW_COOKIELESS_LOOPBACK_RUNTIME=1

(
  cd "${ROOT_DIR}/backend"
  exec "${PYTHON}" -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "${backend_port}" \
    --no-access-log
) >"${BACKEND_LOG}" 2>&1 &
backend_pid=$!
wait_http "${backend_base_url}/api/health" "${BACKEND_LOG}"

if ! (
  cd "${ROOT_DIR}/backend"
  BUILDER_E2E_USERNAME="${E2E_USERNAME}" \
  BUILDER_E2E_PASSWORD="${E2E_PASSWORD}" \
  "${PYTHON}" - <<'PY'
import asyncio
import json
import os
from uuid import uuid4

from app.auth import get_password_hash
from app.database import AsyncSessionLocal
from app.models import User
from app.models.ai_chat import AIChatSession, CodeRuntimeAgentSession
from app.models.tenant import Role, Tenant, UserTenant


async def main():
    async with AsyncSessionLocal() as db:
        tenants = [
            Tenant(
                public_id=str(uuid4()),
                tenant_name="Task 6 Current",
                tenant_code="task6-current",
                status=1,
            ),
            Tenant(
                public_id=str(uuid4()),
                tenant_name="Task 6 Target",
                tenant_code="task6-target",
                status=1,
            ),
            Tenant(
                public_id=str(uuid4()),
                tenant_name="Task 6 Disabled",
                tenant_code="task6-disabled",
                status=0,
            ),
            Tenant(
                public_id=str(uuid4()),
                tenant_name="Task 6 Unauthorized",
                tenant_code="task6-unauthorized",
                status=1,
            ),
        ]
        db.add_all(tenants)
        await db.flush()

        roles = []
        for tenant in tenants:
            role = Role(
                tenant_id=tenant.id,
                role_name="Task 6 Admin",
                role_code="R_tenant_admin",
                permissions={},
                is_system=True,
            )
            roles.append(role)
            db.add(role)
        await db.flush()

        user = User(
            username=os.environ["BUILDER_E2E_USERNAME"],
            display_name="Task 6 Tenant User",
            hashed_password=get_password_hash(os.environ["BUILDER_E2E_PASSWORD"]),
            account_source="apaas",
            is_platform_admin=False,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        db.add_all(
            [
                UserTenant(
                    user_id=user.id,
                    tenant_id=tenants[0].id,
                    role_id=roles[0].id,
                    is_default=True,
                    status=1,
                ),
                UserTenant(
                    user_id=user.id,
                    tenant_id=tenants[1].id,
                    role_id=roles[1].id,
                    is_default=False,
                    status=1,
                ),
                UserTenant(
                    user_id=user.id,
                    tenant_id=tenants[2].id,
                    role_id=roles[2].id,
                    is_default=False,
                    status=1,
                ),
            ]
        )
        session = AIChatSession(
            tenant_id=tenants[0].id,
            user_id=user.id,
            title="Task 6 Code",
            mode="code",
            status="active",
            external_application_id="local-task6-tenant-url",
            external_app_name="Task 6 Code",
            external_app_code="task6-code",
        )
        db.add(session)
        await db.flush()
        agent_session_id = "task6-agent-session"
        db.add(
            CodeRuntimeAgentSession(
                tenant_id=tenants[0].id,
                user_id=user.id,
                session_id=session.id,
                external_application_id=session.external_application_id,
                runtime_session_id=agent_session_id,
                title="Task 6 Agent",
                state="waiting_input",
            )
        )
        await db.commit()
        print(
            json.dumps(
                {
                    "current_tenant_uuid": tenants[0].public_id,
                    "target_tenant_uuid": tenants[1].public_id,
                    "disabled_tenant_uuid": tenants[2].public_id,
                    "unauthorized_tenant_uuid": tenants[3].public_id,
                    "code_session_ref": session.public_id,
                    "agent_session_id": agent_session_id,
                },
                separators=(",", ":"),
            )
        )


asyncio.run(main())
PY
) >"${TMP_DIR}/fixture.json" 2>"${SEED_LOG}"; then
  printf 'failed to seed tenant URL fixture data\n' >&2
  exit 1
fi

fixture_json="$(<"${TMP_DIR}/fixture.json")"
if [[ -z "${fixture_json}" ]]; then
  printf 'tenant URL fixture seed returned empty JSON\n' >&2
  exit 1
fi
printf 'FIXTURE_PHASE=seeded\n'

json_value() {
  "${PYTHON}" -c \
    'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' \
    "${fixture_json}" "$1"
}

current_tenant_uuid="$(json_value current_tenant_uuid)"
target_tenant_uuid="$(json_value target_tenant_uuid)"
disabled_tenant_uuid="$(json_value disabled_tenant_uuid)"
unauthorized_tenant_uuid="$(json_value unauthorized_tenant_uuid)"
code_session_ref="$(json_value code_session_ref)"
agent_session_id="$(json_value agent_session_id)"
printf 'FIXTURE_PHASE=parsed\n'

cat >"${TMP_DIR}/frontend_server.py" <<'PY'
from __future__ import annotations

import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

DIST = Path(os.environ["DIST_DIR"]).resolve()
BACKEND = os.environ["BACKEND_ORIGIN"].rstrip("/")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def _proxy(self):
        parsed = urlsplit(self.path)
        suffix = parsed.path[len("/ai-builder/api") :]
        target = f"{BACKEND}/api{suffix}"
        if parsed.query:
            target += f"?{parsed.query}"
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        headers["X-Forwarded-Prefix"] = "/ai-builder"
        headers["X-Forwarded-Proto"] = "http"
        request = Request(target, data=body, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=65)
        except HTTPError as exc:
            response = exc
        payload = response.read()
        self.send_response(response.status)
        for key, value in response.headers.items():
            if key.lower() not in {
                "connection",
                "content-length",
                "transfer-encoding",
                "content-encoding",
            }:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)
        print(
            f"frontend_proxy method={self.command} path={parsed.path} status={response.status}",
            flush=True,
        )

    def _static(self):
        parsed = urlsplit(self.path)
        if parsed.path in {"/ai-builder", "/ai-builder/"}:
            relative = "index.html"
        elif parsed.path.startswith("/ai-builder/"):
            relative = unquote(parsed.path[len("/ai-builder/") :])
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        candidate = (DIST / relative).resolve()
        if DIST not in candidate.parents and candidate != DIST:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not candidate.is_file():
            candidate = DIST / "index.html"
        payload = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if candidate.name == "index.html":
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _dispatch(self):
        if urlsplit(self.path).path.startswith("/ai-builder/api/"):
            self._proxy()
        else:
            self._static()

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch


server = ThreadingHTTPServer(("0.0.0.0", int(os.environ["FRONTEND_PORT"])), Handler)
server.serve_forever()
PY

DIST_DIR="${ROOT_DIR}/frontend/dist" \
BACKEND_ORIGIN="${backend_base_url}" \
FRONTEND_PORT="${frontend_port}" \
"${PYTHON}" "${TMP_DIR}/frontend_server.py" >"${FRONTEND_LOG}" 2>&1 &
frontend_pid=$!
printf 'FIXTURE_PHASE=frontend-started\n'
wait_http "${builder_base_url}/ai-builder/" "${FRONTEND_LOG}"

served_meta="$(
  curl -fsS "${builder_base_url}/ai-builder/" \
    | "${PYTHON}" -c '
import re,sys
text=sys.stdin.read()
matches=re.findall(r"<meta\s+name=\"builder-build-sha\"\s+content=\"([0-9a-f]{40})\"\s*/?>", text)
if len(matches) != 1:
    raise SystemExit(1)
print(matches[0])
'
)"
if [[ "${served_meta}" != "${BUILD_SHA}" ]]; then
  printf 'served build SHA mismatch: expected=%s actual=%s\n' "${BUILD_SHA}" "${served_meta}" >&2
  exit 1
fi

e2e_builder_base_url="${builder_base_url}"
e2e_node=(node)
e2e_spec="${ROOT_DIR}/tests/e2e/builder-tenant-url-public-uuid.spec.mjs"
e2e_playwright_module=""
e2e_wslenv="${WSLENV:-}"

if [[ "${BROWSER_CHANNEL}" == "msedge" ]]; then
  WINDOWS_NODE="${WINDOWS_NODE:-$(command -v node.exe || true)}"
  if [[ -n "${WINDOWS_NODE}" ]]; then
    windows_spec="$(wslpath -w "${e2e_spec}")"
    windows_root="$(wslpath -w "${ROOT_DIR}")"
    e2e_playwright_module="${windows_root}\\node_modules\\playwright"
    e2e_node=("${WINDOWS_NODE}")
    e2e_spec="${windows_spec}"
    e2e_wslenv="${e2e_wslenv:+${e2e_wslenv}:}BUILDER_BASE_URL"
    e2e_wslenv="${e2e_wslenv}:BUILDER_BUILD_SHA:BUILDER_CURRENT_TENANT_UUID"
    e2e_wslenv="${e2e_wslenv}:BUILDER_TARGET_TENANT_UUID:BUILDER_DISABLED_TENANT_UUID"
    e2e_wslenv="${e2e_wslenv}:BUILDER_UNAUTHORIZED_TENANT_UUID:BUILDER_E2E_USERNAME"
    e2e_wslenv="${e2e_wslenv}:BUILDER_E2E_PASSWORD:BUILDER_CODE_SESSION_REF"
    e2e_wslenv="${e2e_wslenv}:BUILDER_AGENT_SESSION_ID:BUILDER_PLAYWRIGHT_MODULE"
    e2e_wslenv="${e2e_wslenv}:BROWSER_CHANNEL"

    if ! "${WINDOWS_NODE}" -e \
      'fetch(process.argv[1], {signal: AbortSignal.timeout(5000)}).then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))' \
      "${builder_base_url}/ai-builder/" </dev/null >/dev/null 2>&1; then
      wsl_ip="$(hostname -I | awk '{ print $1 }')"
      if [[ -z "${wsl_ip}" ]]; then
        printf 'unable to determine a Windows-accessible WSL address\n' >&2
        exit 1
      fi
      e2e_builder_base_url="http://${wsl_ip}:${frontend_port}"
      if ! "${WINDOWS_NODE}" -e \
        'fetch(process.argv[1], {signal: AbortSignal.timeout(5000)}).then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))' \
        "${e2e_builder_base_url}/ai-builder/" </dev/null >/dev/null 2>&1; then
        printf 'Windows Node cannot reach WSL static service via localhost or %s\n' \
          "${e2e_builder_base_url}" >&2
        exit 1
      fi
    fi
  fi
fi

env \
  WSLENV="${e2e_wslenv}" \
  PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-${HOME}/.cache/ms-playwright}" \
  BUILDER_BASE_URL="${e2e_builder_base_url}" \
  BUILDER_BUILD_SHA="${BUILD_SHA}" \
  BUILDER_CURRENT_TENANT_UUID="${current_tenant_uuid}" \
  BUILDER_TARGET_TENANT_UUID="${target_tenant_uuid}" \
  BUILDER_DISABLED_TENANT_UUID="${disabled_tenant_uuid}" \
  BUILDER_UNAUTHORIZED_TENANT_UUID="${unauthorized_tenant_uuid}" \
  BUILDER_E2E_USERNAME="${E2E_USERNAME}" \
  BUILDER_E2E_PASSWORD="${E2E_PASSWORD}" \
  BUILDER_CODE_SESSION_REF="${code_session_ref}" \
  BUILDER_AGENT_SESSION_ID="${agent_session_id}" \
  BUILDER_PLAYWRIGHT_MODULE="${e2e_playwright_module}" \
  BROWSER_CHANNEL="${BROWSER_CHANNEL}" \
  "${e2e_node[@]}" "${e2e_spec}" >"${PLAYWRIGHT_LOG}" 2>&1

cat "${PLAYWRIGHT_LOG}"

if rg -n -F "${E2E_PASSWORD}" \
  "${BUILD_LOG}" "${RUNTIME_LOG}" "${BACKEND_LOG}" "${FRONTEND_LOG}" "${PLAYWRIGHT_LOG}"; then
  echo "credential canary found in Task 6 logs" >&2
  exit 1
fi

if rg -n 'tenantId=' "${RUNTIME_LOG}"; then
  echo "outer tenantId leaked into Runtime upstream" >&2
  exit 1
fi

if rg -n \
  'Authorization:|Cookie:|Bearer [A-Za-z0-9._-]+|[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' \
  "${RUNTIME_LOG}" "${BACKEND_LOG}" "${FRONTEND_LOG}" "${PLAYWRIGHT_LOG}"; then
  echo "credential-shaped content found in Task 6 logs" >&2
  exit 1
fi

echo "TENANT_URL_FIXTURE=PASS channel=${BROWSER_CHANNEL} build_sha=${BUILD_SHA}"
