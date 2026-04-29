#!/usr/bin/env python3
"""Deploy the local aPaaS Builder AI checkout to the cloud host.

The script intentionally lives in the repo so deployment behavior is reviewable
and repeatable. Secrets are read from environment variables or an interactive
password prompt; do not commit credentials here.
"""

from __future__ import annotations

import argparse
import getpass
import io
import os
import shlex
import subprocess
import sys
import tarfile
import time
from pathlib import Path

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - local operator guidance
    raise SystemExit("Missing dependency: pip install paramiko") from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
RUIJING_EXTENSION_DIR = REPO_ROOT / "extensions" / "ruijing-ai"
SCRIPTS_DIR = REPO_ROOT / "scripts"

DEFAULT_HOST = "101.132.123.203"
DEFAULT_USER = "root"
DEFAULT_PORT = 22
DEFAULT_REMOTE_BASE = "/root/apaas-builder"
DEFAULT_PUBLIC_HEALTH = "https://agent.dfy.definesys.cn/ai-builder/api/health"
DEFAULT_CODE_SERVER_DATA_DIR = "/root/.local/share/code-server"
DEFAULT_CODE_SERVER_SERVICE = "apaas-code-server.service"
RUIJING_EXTENSION_NAME = "apaas-builder.ruijing-ai-0.1.0"
REMOTE_RUIJING_EXTENSION_TAR = "/tmp/apaas_ruijing_ai_extension.tar.gz"
REMOTE_IDE_PATCH_TAR = "/tmp/apaas_ruijing_ide_patch.tar.gz"
REMOTE_IDE_PATCH_DIR = "/tmp/apaas_ruijing_ide_patch"

BACKEND_EXCLUDES = {
    ".DS_Store",
    ".env",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
}

EXTENSION_EXCLUDES = {
    ".DS_Store",
    "node_modules",
    ".npm",
    ".vscode-test",
}

IDE_PATCH_FILES = {
    "patch_vscode_branding.js",
    "patch_vscode_chat_fallback.js",
    "patch_vscode_chat_fallback.template.txt",
    "lib/codeServerResolver.js",
}


def log(message: str) -> None:
    print(message, flush=True)


def run_local(cmd: list[str], cwd: Path) -> None:
    log(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def should_exclude_backend(rel: str) -> bool:
    parts = Path(rel).parts
    for part in parts:
        if part in BACKEND_EXCLUDES:
            return True
        if part.startswith("._"):
            return True
        if part.endswith((".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3")):
            return True
    return False


def should_exclude_extension(rel: str) -> bool:
    parts = Path(rel).parts
    for part in parts:
        if part in EXTENSION_EXCLUDES:
            return True
        if part.startswith("._"):
            return True
    return False


def should_exclude_ide_patch(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    return normalized not in IDE_PATCH_FILES


def make_tar(base_dir: Path, exclude_fn=None) -> bytes:
    if not base_dir.exists():
        raise FileNotFoundError(str(base_dir))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in base_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(base_dir))
            if exclude_fn and exclude_fn(rel):
                continue
            tar.add(str(path), arcname=rel)
    buf.seek(0)
    return buf.read()


def shq(value: str | Path) -> str:
    return shlex.quote(str(value))


def connect(
    host: str,
    user: str,
    password: str | None,
    port: int,
    key_file: str | None = None,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 30,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if key_file:
        kwargs["key_filename"] = os.path.expanduser(key_file)
    else:
        kwargs["password"] = password
    client.connect(**kwargs)
    return client


def remote_run(client: paramiko.SSHClient, cmd: str, *, check: bool = True, timeout: int = 300) -> str:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    stdin.close()
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        log(out)
    if err:
        log(err)
    if check and exit_code != 0:
        raise RuntimeError(f"Remote command failed ({exit_code}): {cmd}")
    return out


def remote_start_backend(client: paramiko.SSHClient, remote_backend: str) -> None:
    # Open a short-lived channel and close it after dispatching the background
    # process. Redirecting stdin is required; otherwise nohup can keep the SSH
    # channel open on some hosts.
    command = (
        f"cd {remote_backend} && "
        "nohup .venv/bin/python -m uvicorn app.main:app "
        "--host 0.0.0.0 --port 8003 --workers 1 "
        ">> ../backend.log 2>&1 < /dev/null &"
    )
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport is not available")
    channel = transport.open_session()
    channel.exec_command(command)
    time.sleep(0.5)
    channel.close()


def remote_has_service(client: paramiko.SSHClient, service_name: str) -> bool:
    result = remote_run(
        client,
        f"systemctl list-unit-files {service_name} --no-legend | "
        f"grep -q '^{service_name}' && echo yes || echo no",
        check=False,
        timeout=60,
    )
    return result.strip() == "yes"


def upload_tar(sftp: paramiko.SFTPClient, remote_path: str, data: bytes) -> None:
    with sftp.open(remote_path, "wb") as handle:
        handle.write(data)


def remote_node_command(script_path: str) -> str:
    quoted_script = shq(script_path)
    return (
        "set -e; "
        "NODE_BIN=$(command -v node || true); "
        "if [ -z \"$NODE_BIN\" ]; then "
        "CODE_ROOT=$(find /root/.local/lib /usr/lib /usr/local/lib -maxdepth 2 "
        "\\( -name 'code-server-*' -o -name 'code-server' \\) 2>/dev/null | sort -V | tail -n 1); "
        "if [ -n \"$CODE_ROOT\" ] && [ -x \"$CODE_ROOT/lib/node\" ]; then NODE_BIN=\"$CODE_ROOT/lib/node\"; fi; "
        "fi; "
        "if [ -z \"$NODE_BIN\" ]; then echo 'node not found for code-server patch'; exit 1; fi; "
        "\"$NODE_BIN\" "
        f"{quoted_script}"
    )


def deploy_ruijing_ide(
    client: paramiko.SSHClient,
    sftp: paramiko.SFTPClient,
    *,
    code_server_data_dir: str,
    code_server_service: str,
    restart: bool,
) -> None:
    log("=== Upload Web IDE ruijing-ai extension ===")
    extension_tar = make_tar(RUIJING_EXTENSION_DIR, should_exclude_extension)
    patch_tar = make_tar(SCRIPTS_DIR, should_exclude_ide_patch)
    log(f"ruijing extension archive: {len(extension_tar) // 1024} KB")
    upload_tar(sftp, REMOTE_RUIJING_EXTENSION_TAR, extension_tar)
    upload_tar(sftp, REMOTE_IDE_PATCH_TAR, patch_tar)

    remote_extensions_dir = f"{code_server_data_dir.rstrip('/')}/extensions"
    remote_extension_dir = f"{remote_extensions_dir}/{RUIJING_EXTENSION_NAME}"
    remote_run(
        client,
        "set -e; "
        f"rm -rf {shq(remote_extension_dir)} {shq(REMOTE_IDE_PATCH_DIR)}; "
        f"mkdir -p {shq(remote_extension_dir)} {shq(REMOTE_IDE_PATCH_DIR)}; "
        f"tar -xzf {shq(REMOTE_RUIJING_EXTENSION_TAR)} -C {shq(remote_extension_dir)}; "
        f"tar -xzf {shq(REMOTE_IDE_PATCH_TAR)} -C {shq(REMOTE_IDE_PATCH_DIR)}; "
        f"rm -f {shq(REMOTE_RUIJING_EXTENSION_TAR)} {shq(REMOTE_IDE_PATCH_TAR)}",
        timeout=120,
    )

    log("=== Patch Web IDE default chat agent ===")
    remote_run(client, remote_node_command(f"{REMOTE_IDE_PATCH_DIR}/patch_vscode_branding.js"), timeout=120)
    remote_run(client, remote_node_command(f"{REMOTE_IDE_PATCH_DIR}/patch_vscode_chat_fallback.js"), timeout=120)

    if restart:
        log("=== Restart Web IDE service ===")
        remote_run(client, f"systemctl restart {shq(code_server_service)}", timeout=90)
        state = remote_run(client, f"systemctl is-active {shq(code_server_service)} || true", check=False, timeout=30)
        if state.strip() != "active":
            raise RuntimeError(f"Code-server service is not active after restart: {state.strip()}")

    log("=== Validate Web IDE ruijing-ai wiring ===")
    validation_cmd = (
        "set -e; "
        f"EXT_DIR={shq(remote_extension_dir)}; "
        "test -f \"$EXT_DIR/package.json\"; "
        "CODE_ROOT=$(find /root/.local/lib /usr/lib /usr/local/lib -maxdepth 2 "
        "\\( -name 'code-server-*' -o -name 'code-server' \\) 2>/dev/null | sort -V | tail -n 1); "
        "test -n \"$CODE_ROOT\"; "
        "PRODUCT=\"$CODE_ROOT/lib/vscode/product.json\"; "
        "WORKBENCH=\"$CODE_ROOT/lib/vscode/out/vs/code/browser/workbench/workbench.js\"; "
        "grep -q 'apaas-builder.ruijing-ai' \"$PRODUCT\"; "
        "grep -q 'ruijing-ai.chat' \"$PRODUCT\"; "
        "grep -q 'apaas-builder.ruijing-ai' \"$WORKBENCH\"; "
        "grep -q 'patched:skip-signin' \"$WORKBENCH\"; "
        "if ! grep -q 'patched:delegate-setup-to-minimax' \"$WORKBENCH\" "
        "&& ! grep -q 'patched:delegate-to-minimax' \"$WORKBENCH\"; then "
        "echo 'missing minimax delegate patch'; exit 1; fi; "
        "if grep -q 'GitHub.copilot-chat' \"$WORKBENCH\"; then "
        "echo 'GitHub.copilot-chat references remain'; exit 1; fi; "
        "if ! grep -q 'patched:always-show-native-chat-view' \"$WORKBENCH\"; then "
        "echo 'warning: native chat visibility marker not found; this is expected on older code-server builds'; fi; "
        "if ! grep -q 'patched:apaas-open-native-chat-on-vibe' \"$WORKBENCH\"; then "
        "echo 'warning: native chat auto-open marker not found; this is expected on older code-server builds'; fi; "
        f"MINIMAX_PKG=$(find {shq(remote_extensions_dir)} -maxdepth 2 -path '*/apaas-builder.minimax-chat-provider-*/package.json' 2>/dev/null | head -n 1); "
        "if [ -n \"$MINIMAX_PKG\" ]; then grep -q '__neutralizedByApaasBuilderAI' \"$MINIMAX_PKG\"; fi; "
        "echo \"ruijing extension: $EXT_DIR\"; "
        "echo \"code-server root: $CODE_ROOT\""
    )
    remote_run(client, validation_cmd, timeout=60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy aPaaS Builder AI to the cloud host")
    parser.add_argument("--host", default=os.getenv("APAAS_DEPLOY_HOST") or os.getenv("SERVER_HOST") or DEFAULT_HOST)
    parser.add_argument("--user", default=os.getenv("APAAS_DEPLOY_USER") or os.getenv("SERVER_USER") or DEFAULT_USER)
    parser.add_argument("--port", type=int, default=int(os.getenv("APAAS_DEPLOY_PORT") or DEFAULT_PORT))
    parser.add_argument("--remote-base", default=os.getenv("APAAS_REMOTE_BASE") or DEFAULT_REMOTE_BASE)
    parser.add_argument("--key-file", default=os.getenv("APAAS_DEPLOY_KEY_FILE") or os.getenv("SERVER_KEY_FILE"))
    parser.add_argument("--skip-build", action="store_true", help="Use existing frontend/dist")
    parser.add_argument("--backend-only", action="store_true", help="Only deploy backend files and restart backend")
    parser.add_argument("--frontend-only", action="store_true", help="Only deploy frontend/dist")
    parser.add_argument("--include-ide", action="store_true", help="Also deploy ruijing-ai Web IDE extension and code-server patches")
    parser.add_argument("--ide-only", action="store_true", help="Only repair/deploy the Web IDE ruijing-ai extension and patches")
    parser.add_argument(
        "--code-server-data-dir",
        default=os.getenv("APAAS_CODE_SERVER_DATA_DIR") or DEFAULT_CODE_SERVER_DATA_DIR,
        help="Remote code-server data dir containing the extensions directory",
    )
    parser.add_argument(
        "--code-server-service",
        default=os.getenv("APAAS_CODE_SERVER_SERVICE") or DEFAULT_CODE_SERVER_SERVICE,
        help="Remote systemd service name for code-server",
    )
    parser.add_argument("--no-ide-restart", action="store_true", help="Deploy IDE files without restarting code-server")
    parser.add_argument("--no-public-check", action="store_true", help="Skip public HTTPS health check")
    parser.add_argument("--wait", type=int, default=6, help="Seconds to wait after backend restart")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.backend_only and args.frontend_only:
        raise SystemExit("--backend-only and --frontend-only cannot be used together")
    if args.ide_only and (args.backend_only or args.frontend_only):
        raise SystemExit("--ide-only cannot be combined with --backend-only or --frontend-only")

    password = os.getenv("APAAS_DEPLOY_PASSWORD") or os.getenv("SERVER_PASSWORD")
    if not password and not args.key_file:
        password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")

    remote_backend = f"{args.remote_base.rstrip('/')}/backend"
    remote_frontend = f"{args.remote_base.rstrip('/')}/frontend/dist"

    deploy_app = not args.ide_only
    deploy_backend = deploy_app and not args.frontend_only
    deploy_frontend = deploy_app and not args.backend_only
    deploy_ide = args.ide_only or args.include_ide

    if not args.skip_build and deploy_frontend:
        log("=== Build frontend ===")
        run_local(["npm", "run", "build:nocheck"], FRONTEND_DIR)

    if not args.skip_build and deploy_ide:
        log("=== Build ruijing-ai extension ===")
        run_local(["npm", "run", "build"], RUIJING_EXTENSION_DIR)

    if deploy_frontend and not (FRONTEND_DIST / "index.html").exists():
        raise SystemExit("frontend/dist is missing. Run without --skip-build or build frontend first.")

    client = None
    try:
        log("=== Connect ===")
        client = connect(args.host, args.user, password, args.port, args.key_file)
        sftp = client.open_sftp()

        if deploy_app:
            remote_run(client, f"mkdir -p {remote_backend} {remote_frontend}", timeout=60)

        if deploy_backend:
            log("=== Upload backend ===")
            backend_tar = make_tar(BACKEND_DIR, should_exclude_backend)
            log(f"backend archive: {len(backend_tar) // 1024} KB")
            upload_tar(sftp, "/tmp/apaas_backend_deploy.tar.gz", backend_tar)
            remote_run(
                client,
                f"tar -xzf /tmp/apaas_backend_deploy.tar.gz -C {remote_backend}/ "
                "&& rm -f /tmp/apaas_backend_deploy.tar.gz",
            )

        if deploy_frontend:
            log("=== Upload frontend ===")
            frontend_tar = make_tar(FRONTEND_DIST)
            log(f"frontend archive: {len(frontend_tar) // 1024} KB")
            upload_tar(sftp, "/tmp/apaas_frontend_deploy.tar.gz", frontend_tar)
            remote_run(client, f"rm -rf {remote_frontend} && mkdir -p {remote_frontend}", timeout=60)
            remote_run(
                client,
                f"tar -xzf /tmp/apaas_frontend_deploy.tar.gz -C {remote_frontend}/ "
                "&& rm -f /tmp/apaas_frontend_deploy.tar.gz",
            )

        if deploy_backend:
            log("=== Install backend dependencies ===")
            remote_run(client, f"cd {remote_backend} && .venv/bin/pip install -q -r requirements.txt", timeout=600)

            log("=== Restart backend ===")
            if remote_has_service(client, "apaas-builder-backend.service"):
                remote_run(client, "systemctl restart apaas-builder-backend.service", timeout=120)
            else:
                remote_run(client, "pkill -9 -f 'uvicorn.*:app.*8003' || true", check=False, timeout=60)
                remote_run(client, "fuser -k 8003/tcp || true", check=False, timeout=60)
                time.sleep(2)
                remote_start_backend(client, remote_backend)
            time.sleep(max(args.wait, 1))

            log("=== Remote health check ===")
            code = remote_run(
                client,
                "curl -s -o /dev/null -w '%{http_code}' http://localhost:8003/api/health",
                timeout=60,
            ).strip()
            log(f"remote /api/health: {code}")
            if code != "200":
                remote_run(client, "tail -80 /root/apaas-builder/backend.log", check=False, timeout=60)
                raise RuntimeError("Remote health check failed")

            for route in (
                "/api/chat/send",
                "/api/applications/upload-doc-with-conversation",
            ):
                hit = remote_run(
                    client,
                    f"curl -s http://localhost:8003/openapi.json | grep -c '{route}' || true",
                    check=False,
                    timeout=60,
                ).strip()
                log(f"openapi route {route}: {hit}")
                if hit == "0":
                    raise RuntimeError(f"Route not registered: {route}")

        if deploy_ide:
            deploy_ruijing_ide(
                client,
                sftp,
                code_server_data_dir=args.code_server_data_dir,
                code_server_service=args.code_server_service,
                restart=not args.no_ide_restart,
            )

        sftp.close()
        client.close()
        client = None

        if deploy_app and not args.no_public_check:
            log("=== Public health check ===")
            result = subprocess.check_output(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", DEFAULT_PUBLIC_HEALTH],
                text=True,
            ).strip()
            log(f"public /api/health: {result}")
            if result != "200":
                raise RuntimeError("Public health check failed")

        log("=== Deploy succeeded ===")
        return 0
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
