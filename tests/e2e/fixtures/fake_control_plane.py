#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class State:
    def __init__(self, runtime: dict[str, str]) -> None:
        self.runtime = runtime
        self.lock = threading.Lock()
        self.mode = "ok"
        self.open_count = 0
        self.refresh_count = 0
        self.rotate_count = 0
        self.accepted_access_tokens = {"access-initial"}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "mode": self.mode,
                "open_count": self.open_count,
                "refresh_count": self.refresh_count,
                "rotate_count": self.rotate_count,
            }

    def set_mode(self, mode: str) -> None:
        with self.lock:
            self.mode = mode

    def next_open(self) -> int:
        with self.lock:
            self.open_count += 1
            return self.open_count

    def next_refresh(self) -> tuple[int, str]:
        with self.lock:
            self.refresh_count += 1
            token = f"access-refreshed-{self.refresh_count}"
            self.accepted_access_tokens.add(token)
            return self.refresh_count, token

    def access_allowed(self, token: str) -> bool:
        with self.lock:
            if self.mode == "refresh_invalid":
                return False
            if self.mode == "access_expired":
                return token != "access-initial" and token in self.accepted_access_tokens
            return token in self.accepted_access_tokens


def json_request(url: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


class Handler(BaseHTTPRequestHandler):
    server: "Server"

    def log_message(self, _format: str, *_args: object) -> None:
        print("fake-control-plane request [REDACTED]", flush=True)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        value = json.loads(self.rfile.read(length))
        return value if isinstance(value, dict) else {}

    def _bearer(self) -> str:
        value = self.headers.get("Authorization", "")
        return value[7:].strip() if value.startswith("Bearer ") else ""

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"ok": True})
            return
        if self.path == "/__control/state":
            self._json(200, self.server.state.snapshot())
            return
        self._json(404, {"detail": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/__control/mode":
            mode = str(self._body().get("mode") or "ok")
            self.server.state.set_mode(mode)
            self._json(200, {"mode": mode})
            return
        if self.path == "/api/auth/refresh":
            self._refresh()
            return
        if self.path.startswith("/api/applications/") and self.path.endswith("/workspace/open"):
            self._workspace_open()
            return
        self._json(404, {"detail": "not_found"})

    def _refresh(self) -> None:
        state = self.server.state
        body = self._body()
        if state.mode in {"refresh_invalid", "account_disabled"}:
            state.next_refresh()
            self._json(401, {"detail": state.mode})
            return
        if body.get("refresh_token") != "refresh-initial":
            state.next_refresh()
            self._json(401, {"detail": "refresh_invalid"})
            return
        _, token = state.next_refresh()
        self._json(
            200,
            {
                "access_token": token,
                "refresh_token": "refresh-initial",
                "tenant_id": "tenant-e2e",
            },
        )

    def _workspace_open(self) -> None:
        state = self.server.state
        open_number = state.next_open()
        mode = state.mode
        if mode == "account_disabled":
            self._json(403, {"detail": "account_disabled"})
            return
        if mode == "tenant_unbound":
            self._json(403, {"detail": "tenant_unbound"})
            return
        if not state.access_allowed(self._bearer()):
            self._json(401, {"detail": "access_expired"})
            return

        launch_token = secrets.token_urlsafe(32)
        expected_hash = "sha256:" + hashlib.sha256(launch_token.encode()).hexdigest()
        try:
            json_request(
                state.runtime["rotate_url"],
                {
                    "token": launch_token,
                    "expectedTokenHash": expected_hash,
                    "expiresInSeconds": 300,
                    "preserveSessions": True,
                },
                state.runtime["internal_token"],
            )
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self._json(503, {"detail": f"runtime_rotate_failed:{type(exc).__name__}"})
            return
        with state.lock:
            state.rotate_count += 1
        runtime_url = state.runtime["runtime_base_url"]
        self._json(
            200,
            {
                "applicationId": "app-e2e",
                "workspaceId": "workspace-e2e",
                "sandboxInstanceId": "sandbox-e2e",
                "runtimeSessionId": "runtime-e2e",
                "specReviewUrl": f"{runtime_url}/builder/?token={launch_token}",
            },
        )


class Server(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], state: State) -> None:
        super().__init__(address, Handler)
        self.state = state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-readiness", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with open(args.runtime_readiness, encoding="utf-8") as handle:
        runtime = json.load(handle)
    server = Server(("127.0.0.1", args.port), State(runtime))
    print(
        "FAKE_CONTROL_PLANE="
        + json.dumps({"base_url": f"http://127.0.0.1:{server.server_port}"}),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
