import sys

import pytest

from app.coding.preview_runtime.contracts import (
    DetectedPreviewProject,
    PackageManager,
    PreviewRuntimeStatus,
)
from app.coding.preview_runtime.local_runner import LocalPreviewRuntime


def _server_command() -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import os, http.server, socketserver;"
            "port=int(os.environ['PORT']);"
            "handler=http.server.SimpleHTTPRequestHandler;"
            "server=socketserver.TCPServer(('127.0.0.1', port), handler);"
            "print('ready', port, flush=True);"
            "server.serve_forever()"
        ),
    ]


def _detected_project(tmp_path, workspace_id="oc_runner") -> DetectedPreviewProject:
    return DetectedPreviewProject(
        workspace_id=workspace_id,
        workspace_path=tmp_path,
        working_dir=tmp_path,
        supported=True,
        status=PreviewRuntimeStatus.DETECTED,
        package_manager=PackageManager.NPM,
        install_command=["npm", "install"],
        start_command=_server_command(),
    )


def _detected_project_with_fake_install(tmp_path, workspace_id="oc_install") -> DetectedPreviewProject:
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite"}}', encoding="utf-8")
    return DetectedPreviewProject(
        workspace_id=workspace_id,
        workspace_path=tmp_path,
        working_dir=tmp_path,
        supported=True,
        status=PreviewRuntimeStatus.DETECTED,
        package_manager=PackageManager.NPM,
        install_command=[sys.executable, "-c", "print('install-ok')"],
        start_command=_server_command(),
    )


@pytest.mark.asyncio
async def test_local_runner_starts_reports_and_stops(tmp_path):
    runner = LocalPreviewRuntime(
        api_base_url="http://builder.example/api",
        runtime_root=tmp_path / ".runtime",
        port_start=43100,
        port_end=43120,
        startup_timeout=5,
    )

    state = await runner.start(_detected_project(tmp_path))
    try:
        assert state.status == PreviewRuntimeStatus.RUNNING
        assert state.port is not None
        assert state.pid is not None
        assert state.preview_url == (
            f"http://builder.example/api/online-coding/workspaces/oc_runner/preview/?port={state.port}"
        )
        assert state.log_path and state.log_path.exists()

        status = runner.status("oc_runner")
        assert status.status == PreviewRuntimeStatus.RUNNING
        assert status.port == state.port

        logs = runner.tail_logs("oc_runner")
        assert "ready" in logs
    finally:
        stopped = await runner.stop("oc_runner")

    assert stopped.status == PreviewRuntimeStatus.STOPPED
    assert runner.status("oc_runner").status == PreviewRuntimeStatus.STOPPED


@pytest.mark.asyncio
async def test_local_runner_reuses_running_workspace(tmp_path):
    runner = LocalPreviewRuntime(
        api_base_url="http://builder.example/api",
        runtime_root=tmp_path / ".runtime",
        port_start=43130,
        port_end=43150,
        startup_timeout=5,
    )

    first = await runner.start(_detected_project(tmp_path, "oc_reuse"))
    try:
        second = await runner.start(_detected_project(tmp_path, "oc_reuse"))
        assert second.status == PreviewRuntimeStatus.RUNNING
        assert second.port == first.port
        assert second.pid == first.pid
    finally:
        await runner.stop("oc_reuse")


@pytest.mark.asyncio
async def test_local_runner_rejects_unsupported_project(tmp_path):
    runner = LocalPreviewRuntime(
        api_base_url="http://builder.example/api",
        runtime_root=tmp_path / ".runtime",
    )
    unsupported = DetectedPreviewProject(
        workspace_id="oc_bad",
        workspace_path=tmp_path,
        working_dir=tmp_path,
        supported=False,
        status=PreviewRuntimeStatus.UNSUPPORTED,
        reason="missing package.json",
    )

    state = await runner.start(unsupported)

    assert state.status == PreviewRuntimeStatus.UNSUPPORTED
    assert state.error == "missing package.json"


@pytest.mark.asyncio
async def test_local_runner_installs_before_first_start(tmp_path):
    runner = LocalPreviewRuntime(
        api_base_url="http://builder.example/api",
        runtime_root=tmp_path / ".runtime",
        port_start=43160,
        port_end=43180,
        startup_timeout=5,
        install_timeout=5,
    )

    state = await runner.start(_detected_project_with_fake_install(tmp_path))
    try:
        assert state.status == PreviewRuntimeStatus.RUNNING
        logs = runner.tail_logs("oc_install")
        assert "[install]" in logs
        assert "install-ok" in logs
    finally:
        await runner.stop("oc_install")
