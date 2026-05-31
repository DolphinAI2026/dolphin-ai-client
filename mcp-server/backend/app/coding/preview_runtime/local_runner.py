from __future__ import annotations

import asyncio
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from app.coding.preview_runtime.contracts import (
    DetectedPreviewProject,
    PreviewRuntimeState,
    PreviewRuntimeStatus,
    build_preview_url,
)


class LocalPreviewRuntime:
    """Internal MVP runner that executes preview commands as local processes."""

    def __init__(
        self,
        *,
        api_base_url: str,
        runtime_root: Path,
        port_start: int = 31000,
        port_end: int = 39999,
        startup_timeout: int = 90,
        install_timeout: int = 300,
    ) -> None:
        self.api_base_url = api_base_url
        self.runtime_root = runtime_root
        self.port_start = port_start
        self.port_end = port_end
        self.startup_timeout = startup_timeout
        self.install_timeout = install_timeout
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._states: dict[str, PreviewRuntimeState] = {}

    async def start(self, project: DetectedPreviewProject) -> PreviewRuntimeState:
        current = self.status(project.workspace_id)
        if current.status == PreviewRuntimeStatus.RUNNING:
            return current

        if not project.supported or not project.start_command:
            state = self._state(
                project,
                PreviewRuntimeStatus.UNSUPPORTED,
                error=project.reason or "当前工作区不支持自动预览",
            )
            self._states[project.workspace_id] = state
            return state

        port = self._allocate_port()
        log_path = self._log_path(project.workspace_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._materialize_command(project.start_command, port)
        env = self._build_env(port)

        install_error = await self._install_if_needed(project, log_path, env)
        if install_error:
            state = self._state(
                project,
                PreviewRuntimeStatus.ERROR,
                port=port,
                log_path=log_path,
                command=command,
                error=install_error,
            )
            self._states[project.workspace_id] = state
            return state

        with log_path.open("ab") as log_file:
            log_file.write(f"\n[{self._now().isoformat()}] start: {' '.join(command)}\n".encode("utf-8"))
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(project.working_dir),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

        starting = self._state(
            project,
            PreviewRuntimeStatus.STARTING,
            port=port,
            pid=proc.pid,
            log_path=log_path,
            command=command,
        )
        self._processes[project.workspace_id] = proc
        self._states[project.workspace_id] = starting

        started = await self._wait_until_ready(project, proc, port, log_path, command)
        self._states[project.workspace_id] = started
        return started

    def status(self, workspace_id: str) -> PreviewRuntimeState:
        state = self._states.get(workspace_id)
        if not state:
            return PreviewRuntimeState(
                workspace_id=workspace_id,
                status=PreviewRuntimeStatus.STOPPED,
                runner="local",
                working_dir=Path("."),
                updated_at=self._now(),
            )

        proc = self._processes.get(workspace_id)
        if proc and proc.returncode is None:
            return state
        if state.status in {PreviewRuntimeStatus.RUNNING, PreviewRuntimeStatus.STARTING}:
            stopped = PreviewRuntimeState(
                **{
                    **state.__dict__,
                    "status": PreviewRuntimeStatus.STOPPED,
                    "updated_at": self._now(),
                }
            )
            self._states[workspace_id] = stopped
            self._processes.pop(workspace_id, None)
            return stopped
        return state

    async def stop(self, workspace_id: str) -> PreviewRuntimeState:
        state = self.status(workspace_id)
        proc = self._processes.pop(workspace_id, None)
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        stopped = PreviewRuntimeState(
            **{
                **state.__dict__,
                "status": PreviewRuntimeStatus.STOPPED,
                "updated_at": self._now(),
            }
        )
        self._states[workspace_id] = stopped
        return stopped

    def tail_logs(self, workspace_id: str, *, max_bytes: int = 16_000) -> str:
        state = self._states.get(workspace_id)
        if not state or not state.log_path or not state.log_path.exists():
            return ""
        return self._tail_log_path(state.log_path, max_bytes=max_bytes)

    async def _install_if_needed(
        self,
        project: DetectedPreviewProject,
        log_path: Path,
        env: dict[str, str],
    ) -> str | None:
        if not project.install_command or not self._needs_install(project.working_dir):
            return None

        with log_path.open("ab") as log_file:
            log_file.write(
                f"\n[{self._now().isoformat()}] [install] {' '.join(project.install_command)}\n".encode("utf-8")
            )
            proc = await asyncio.create_subprocess_exec(
                *project.install_command,
                cwd=str(project.working_dir),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=self.install_timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"依赖安装超时（{self.install_timeout}s）"

        if proc.returncode != 0:
            return self._tail_log_path(log_path)[-2000:] or "依赖安装失败"
        return None

    async def _wait_until_ready(
        self,
        project: DetectedPreviewProject,
        proc: asyncio.subprocess.Process,
        port: int,
        log_path: Path,
        command: list[str],
    ) -> PreviewRuntimeState:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if proc.returncode is not None:
                return self._state(
                    project,
                    PreviewRuntimeStatus.ERROR,
                    port=port,
                    pid=proc.pid,
                    log_path=log_path,
                    command=command,
                    error=self.tail_logs(project.workspace_id)[-2000:] or "预览进程启动失败",
                )
            if self._is_port_open(port):
                return self._state(
                    project,
                    PreviewRuntimeStatus.RUNNING,
                    port=port,
                    pid=proc.pid,
                    log_path=log_path,
                    command=command,
                    preview_url=build_preview_url(self.api_base_url, project.workspace_id, port),
                )
            await asyncio.sleep(0.2)

        return self._state(
            project,
            PreviewRuntimeStatus.ERROR,
            port=port,
            pid=proc.pid,
            log_path=log_path,
            command=command,
            error=f"预览服务启动超时（{self.startup_timeout}s）",
        )

    def _state(
        self,
        project: DetectedPreviewProject,
        status: PreviewRuntimeStatus,
        *,
        port: int | None = None,
        preview_url: str | None = None,
        pid: int | None = None,
        log_path: Path | None = None,
        command: list[str] | None = None,
        error: str | None = None,
    ) -> PreviewRuntimeState:
        now = self._now()
        return PreviewRuntimeState(
            workspace_id=project.workspace_id,
            status=status,
            runner="local",
            working_dir=project.working_dir,
            port=port,
            preview_url=preview_url,
            pid=pid,
            log_path=log_path,
            command=command,
            error=error,
            started_at=now if status in {PreviewRuntimeStatus.STARTING, PreviewRuntimeStatus.RUNNING} else None,
            updated_at=now,
        )

    def _allocate_port(self) -> int:
        for port in range(self.port_start, self.port_end + 1):
            if not self._is_port_open(port):
                return port
        raise RuntimeError(f"没有可用预览端口：{self.port_start}-{self.port_end}")

    def _log_path(self, workspace_id: str) -> Path:
        return self.runtime_root / workspace_id / "preview.log"

    @staticmethod
    def _tail_log_path(log_path: Path, *, max_bytes: int = 16_000) -> str:
        if not log_path.exists():
            return ""
        raw = log_path.read_bytes()[-max_bytes:]
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _needs_install(working_dir: Path) -> bool:
        return (working_dir / "package.json").exists() and not (working_dir / "node_modules").exists()

    def _build_env(self, port: int) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "PORT": str(port),
            "HOST": "0.0.0.0",
            "BROWSER": "none",
            "CI": "1",
            "FORCE_COLOR": "0",
        })
        return env

    @staticmethod
    def _materialize_command(command: list[str], port: int) -> list[str]:
        return [part.replace("{port}", str(port)) for part in command]

    @staticmethod
    def _is_port_open(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
