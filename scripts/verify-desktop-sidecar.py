#!/usr/bin/env python3
"""Start a packaged desktop sidecar and verify its health endpoint."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--sidecar-arg", action="append", default=[])
    parser.add_argument("--verify-import", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=30)
    return parser.parse_args()


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def smoke_root() -> Path:
    if os.name == "nt":
        return Path(tempfile.gettempdir()) / "d-ai-code" / "desktop-sidecar-smoke"
    return Path("/tmp/d-ai-code/desktop-sidecar-smoke")


def sidecar_path(path: Path) -> Path:
    candidate = path.expanduser()
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def wait_for_health(process: subprocess.Popen[bytes], port: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/api/health"
    last_error = "health endpoint did not respond"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"sidecar exited before health check (exit code {return_code})")
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 - loopback smoke check
                payload = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and payload.get("status") == "ok":
                return
            last_error = f"unexpected health response: {payload!r}"
        except Exception as error:  # The next poll may succeed while uvicorn starts.
            last_error = str(error)
        time.sleep(0.2)
    raise RuntimeError(f"sidecar health check timed out: {last_error}")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def verify_lazy_imports(sidecar: Path, args: argparse.Namespace, run_dir: Path, log_path: Path) -> None:
    """Exercise modules that a health endpoint does not import until a chat runs."""
    for module_name in args.verify_import:
        command = [
            str(sidecar),
            *args.sidecar_arg,
            "--data-dir",
            str(run_dir / "import-data"),
            "--applications-root",
            str(run_dir / "import-applications"),
            "--runtime-data-dir",
            str(run_dir / "import-runtime"),
            "--verify-import",
            module_name,
        ]
        with log_path.open("ab") as log_file:
            completed = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT, timeout=args.timeout_seconds)
        if completed.returncode != 0:
            raise RuntimeError(f"sidecar failed lazy import {module_name!r} (exit code {completed.returncode})")
def main() -> int:
    args = parse_args()
    sidecar = sidecar_path(args.sidecar)
    if not sidecar.is_file():
        print(f"ERROR: sidecar executable does not exist: {sidecar}", file=sys.stderr)
        return 2
    if args.timeout_seconds <= 0:
        print("ERROR: --timeout-seconds must be positive", file=sys.stderr)
        return 2

    smoke_root().mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=smoke_root()))
    log_path = run_dir / "sidecar.log"
    port = reserve_port()
    command = [str(sidecar), *args.sidecar_arg]
    command.extend(
        [
            "--port",
            str(port),
            "--data-dir",
            str(run_dir / "data"),
            "--applications-root",
            str(run_dir / "applications"),
            "--runtime-data-dir",
            str(run_dir / "runtime"),
        ]
    )

    process: subprocess.Popen[bytes] | None = None
    succeeded = False
    try:
        with log_path.open("wb") as log_file:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            wait_for_health(process, port, args.timeout_seconds)
        verify_lazy_imports(sidecar, args, run_dir, log_path)
        succeeded = True
        print(f"Desktop sidecar startup smoke check passed: {sidecar.name}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: desktop sidecar startup smoke check failed: {error}", file=sys.stderr)
        if log_path.is_file():
            print(log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
        print(f"Diagnostic directory retained: {run_dir}", file=sys.stderr)
        return 1
    finally:
        if process is not None:
            stop(process)
        if succeeded:
            shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
