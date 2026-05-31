from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote, urlencode


class PackageManager(StrEnum):
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"
    UNKNOWN = "unknown"


class PreviewRuntimeStatus(StrEnum):
    UNSUPPORTED = "unsupported"
    DETECTED = "detected"
    INSTALLING = "installing"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True)
class DetectedPreviewProject:
    workspace_id: str
    workspace_path: Path
    working_dir: Path
    supported: bool
    status: PreviewRuntimeStatus
    package_manager: PackageManager = PackageManager.UNKNOWN
    install_command: list[str] | None = None
    start_command: list[str] | None = None
    build_command: list[str] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PreviewRuntimeState:
    workspace_id: str
    status: PreviewRuntimeStatus
    runner: str
    working_dir: Path
    port: int | None = None
    preview_url: str | None = None
    pid: int | None = None
    log_path: Path | None = None
    command: list[str] | None = None
    error: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None


def build_preview_url(
    api_base_url: str,
    workspace_id: str,
    port: int,
    *,
    path: str = "/",
) -> str:
    """Build the public preview URL for an online Vibe Coding workspace."""
    base = (api_base_url or "").rstrip("/")
    clean_path = "/" + (path or "/").lstrip("/")
    encoded_workspace_id = quote(workspace_id, safe="")
    query = urlencode({"port": str(port)})
    return (
        f"{base}/online-coding/workspaces/{encoded_workspace_id}"
        f"/preview{clean_path}?{query}"
    )
