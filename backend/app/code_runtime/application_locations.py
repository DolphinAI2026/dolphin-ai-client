"""Stable local application-location primitives shared by later Code flows."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal, TypedDict


CodeExecutionLocation = Literal["local", "remote"]
CodeLocationAvailability = Literal["ready", "missing", "unreadable", "unavailable"]
LocalApplicationDirectoryMode = Literal["new_directory", "existing_directory"]


class LocalApplicationPathError(ValueError):
    """A user-actionable local application directory validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CodeApplicationLocation(TypedDict):
    location: CodeExecutionLocation
    location_id: str
    availability: CodeLocationAvailability
    workspace_id: str | None
    workspace_path: str | None
    environment_name: str | None


def normalize_local_workspace_path(value: str | Path) -> str:
    """Return the canonical absolute path used for local location identity."""

    raw_path = str(value or "").strip()
    if not raw_path:
        raise ValueError("local workspace path is required")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("local workspace path must be absolute")
    normalized = str(path.resolve(strict=False))
    if os.name == "nt":
        if normalized.lower().startswith("\\\\?\\unc\\"):
            return "\\\\" + normalized[8:]
        if normalized.startswith("\\\\?\\"):
            return normalized[4:]
    return normalized


def local_workspace_path_identity(value: str | Path) -> str:
    """Return the canonical path identity used to compare local locations."""

    normalized = normalize_local_workspace_path(value)
    return normalized.casefold() if os.name == "nt" else normalized


def prepare_local_application_workspace(
    value: str | Path,
    *,
    directory_mode: LocalApplicationDirectoryMode,
) -> str:
    """Validate a local workspace and create only a requested new directory."""

    raw_path = str(value or "").strip()
    if not raw_path or not Path(raw_path).expanduser().is_absolute():
        raise LocalApplicationPathError(
            "LOCAL_APPLICATION_PATH_NOT_ABSOLUTE",
            "本地项目目录必须是绝对路径",
        )

    normalized = normalize_local_workspace_path(raw_path)
    path = Path(normalized)
    if directory_mode == "new_directory" and not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=False)
        except PermissionError as exc:
            raise LocalApplicationPathError(
                "LOCAL_APPLICATION_PATH_UNREADABLE",
                "本地项目目录不可读",
            ) from exc
        except OSError as exc:
            raise LocalApplicationPathError(
                "LOCAL_APPLICATION_PATH_NOT_FOUND",
                "无法创建本地项目目录",
            ) from exc

    if not path.exists():
        raise LocalApplicationPathError(
            "LOCAL_APPLICATION_PATH_NOT_FOUND",
            "本地项目目录不存在",
        )
    if not path.is_dir():
        raise LocalApplicationPathError(
            "LOCAL_APPLICATION_PATH_NOT_DIRECTORY",
            "本地项目路径不是目录",
        )
    try:
        if not os.access(path, os.R_OK | os.X_OK):
            raise PermissionError
        with os.scandir(path):
            pass
    except PermissionError as exc:
        raise LocalApplicationPathError(
            "LOCAL_APPLICATION_PATH_UNREADABLE",
            "本地项目目录不可读",
        ) from exc
    except OSError as exc:
        raise LocalApplicationPathError(
            "LOCAL_APPLICATION_PATH_UNREADABLE",
            "本地项目目录不可读",
        ) from exc
    return normalized


def local_location_id(workspace_path: str | Path) -> str:
    """Build a path-stable local location identifier without exposing the path."""

    identity = local_workspace_path_identity(workspace_path)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"local-{digest[:32]}"


def local_workspace_availability(workspace_path: str | Path) -> CodeLocationAvailability:
    """Classify a local workspace without creating or changing it."""

    try:
        path = Path(normalize_local_workspace_path(workspace_path))
        if not path.exists():
            return "missing"
        if not path.is_dir():
            return "unavailable"
        if not os.access(path, os.R_OK | os.X_OK):
            return "unreadable"
        with os.scandir(path):
            pass
    except PermissionError:
        return "unreadable"
    except (OSError, ValueError):
        return "unavailable"
    return "ready"


def build_local_application_location(
    *,
    workspace_id: str | None,
    workspace_path: str | Path,
) -> CodeApplicationLocation:
    """Describe one local application location for the unified application API."""

    normalized_path = normalize_local_workspace_path(workspace_path)
    normalized_workspace_id = str(workspace_id).strip() if workspace_id is not None else ""
    return {
        "location": "local",
        "location_id": local_location_id(normalized_path),
        "availability": local_workspace_availability(normalized_path),
        "workspace_id": normalized_workspace_id or None,
        "workspace_path": normalized_path,
        "environment_name": None,
    }
