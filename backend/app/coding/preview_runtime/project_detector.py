from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.coding.preview_runtime.contracts import (
    DetectedPreviewProject,
    PackageManager,
    PreviewRuntimeStatus,
)

START_SCRIPT_PRIORITY = ("dev", "start", "serve", "preview")
CANDIDATE_DIRS = ("", "frontend", "web", "app", "client")


def detect_preview_project(workspace_id: str, workspace_path: Path) -> DetectedPreviewProject:
    """Detect the first runnable npm-family project in a workspace."""
    root = workspace_path.resolve()
    package_dirs = [root / rel for rel in CANDIDATE_DIRS]

    saw_package_json = False
    for candidate in package_dirs:
        package_json = candidate / "package.json"
        if not package_json.exists():
            continue
        saw_package_json = True

        package_payload = _read_package_json(package_json)
        scripts = package_payload.get("scripts") if isinstance(package_payload.get("scripts"), dict) else {}
        start_script = _choose_start_script(scripts)
        if not start_script:
            continue

        package_manager = _detect_package_manager(candidate, root)
        return DetectedPreviewProject(
            workspace_id=workspace_id,
            workspace_path=root,
            working_dir=candidate,
            supported=True,
            status=PreviewRuntimeStatus.DETECTED,
            package_manager=package_manager,
            install_command=_install_command(package_manager),
            start_command=_run_script_command(package_manager, start_script, host=True),
            build_command=(
                _run_script_command(package_manager, "build")
                if "build" in scripts
                else None
            ),
        )

    reason = (
        "未找到 package.json，当前工作区暂不支持自动预览"
        if not saw_package_json
        else "未找到可用于预览的 npm scripts: dev/start/serve/preview"
    )
    return DetectedPreviewProject(
        workspace_id=workspace_id,
        workspace_path=root,
        working_dir=root,
        supported=False,
        status=PreviewRuntimeStatus.UNSUPPORTED,
        reason=reason,
    )


def _read_package_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _choose_start_script(scripts: dict[str, Any]) -> str | None:
    for script_name in START_SCRIPT_PRIORITY:
        if isinstance(scripts.get(script_name), str) and scripts[script_name].strip():
            return script_name
    return None


def _detect_package_manager(project_dir: Path, workspace_root: Path) -> PackageManager:
    for root in (project_dir, workspace_root):
        if (root / "pnpm-lock.yaml").exists():
            return PackageManager.PNPM
        if (root / "yarn.lock").exists():
            return PackageManager.YARN
        if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            return PackageManager.BUN
        if (root / "package-lock.json").exists():
            return PackageManager.NPM
    return PackageManager.NPM


def _install_command(package_manager: PackageManager) -> list[str]:
    if package_manager == PackageManager.PNPM:
        return ["pnpm", "install"]
    if package_manager == PackageManager.YARN:
        return ["yarn", "install"]
    if package_manager == PackageManager.BUN:
        return ["bun", "install"]
    return ["npm", "install"]


def _run_script_command(
    package_manager: PackageManager,
    script_name: str,
    *,
    host: bool = False,
) -> list[str]:
    if package_manager == PackageManager.YARN:
        command = ["yarn", script_name]
        if host:
            command.extend(["--host", "0.0.0.0", "--port", "{port}"])
        return command

    if package_manager == PackageManager.BUN:
        command = ["bun", "run", script_name]
    elif package_manager == PackageManager.PNPM:
        command = ["pnpm", "run", script_name]
    else:
        command = ["npm", "run", script_name]

    if host:
        command.extend(["--", "--host", "0.0.0.0", "--port", "{port}"])
    return command
