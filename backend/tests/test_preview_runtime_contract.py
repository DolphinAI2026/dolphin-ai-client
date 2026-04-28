from pathlib import Path

from app.coding.preview_runtime.contracts import (
    PackageManager,
    PreviewRuntimeStatus,
    build_preview_url,
)
from app.coding.preview_runtime.project_detector import detect_preview_project


def _write_package_json(path: Path, scripts: dict[str, str]) -> None:
    import json

    path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text(
        json.dumps({"scripts": scripts}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_detects_root_npm_dev_project(tmp_path):
    _write_package_json(tmp_path, {"dev": "vite --host 0.0.0.0", "build": "vite build"})
    detected = detect_preview_project("oc_demo", tmp_path)

    assert detected.workspace_id == "oc_demo"
    assert detected.supported is True
    assert detected.package_manager == PackageManager.NPM
    assert detected.working_dir == tmp_path
    assert detected.install_command == ["npm", "install"]
    assert detected.start_command == ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "{port}"]
    assert detected.build_command == ["npm", "run", "build"]


def test_detects_pnpm_with_lockfile(tmp_path):
    _write_package_json(tmp_path, {"start": "vite --host 0.0.0.0"})
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    detected = detect_preview_project("oc_pnpm", tmp_path)

    assert detected.package_manager == PackageManager.PNPM
    assert detected.install_command == ["pnpm", "install"]
    assert detected.start_command == ["pnpm", "run", "start", "--", "--host", "0.0.0.0", "--port", "{port}"]


def test_prefers_frontend_subdirectory_when_root_has_no_script(tmp_path):
    _write_package_json(tmp_path, {})
    frontend_dir = tmp_path / "frontend"
    _write_package_json(frontend_dir, {"dev": "vite"})

    detected = detect_preview_project("oc_frontend", tmp_path)

    assert detected.supported is True
    assert detected.working_dir == frontend_dir
    assert detected.start_command == ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "{port}"]


def test_unsupported_when_no_package_json(tmp_path):
    detected = detect_preview_project("oc_empty", tmp_path)

    assert detected.supported is False
    assert detected.status == PreviewRuntimeStatus.UNSUPPORTED
    assert "package.json" in (detected.reason or "")


def test_build_preview_url_normalizes_base_path():
    assert (
        build_preview_url("https://builder.example.com/api", "oc_abc", 31000)
        == "https://builder.example.com/api/online-coding/workspaces/oc_abc/preview/?port=31000"
    )
    assert (
        build_preview_url("https://builder.example.com/api/", "oc_abc", 31000, path="/dashboard")
        == "https://builder.example.com/api/online-coding/workspaces/oc_abc/preview/dashboard?port=31000"
    )
