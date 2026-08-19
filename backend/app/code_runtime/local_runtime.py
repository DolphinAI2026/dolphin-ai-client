"""Prepare local application runtime requests for the desktop runtime manager."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import ntpath
import os
import re
import secrets
import socket
import stat
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime
from app.code_runtime.application_locations import (
    LocalApplicationDirectoryMode,
    LocalApplicationPathError,
    local_workspace_path_identity,
    local_workspace_path_digest,
    prepare_local_application_workspace,
)
from app.engineering_sessions.service import EngineeringSessionService
from app.models import Application, RegisteredWorkspace
from app.models.workspace_git import WorkspaceGitRemote
from app.code_runtime.model_provider import (
    provider_catalog_identity,
    provider_document as resolve_provider_document,
    provider_identity_from_document,
)

_APPLICATION_COMPONENT = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_INSTANCE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_INSTANCE_ID_LENGTH = 160
_MANAGER_UNAVAILABLE = "LOCAL_RUNTIME_MANAGER_UNAVAILABLE"
_MANAGER_TIMEOUT = "LOCAL_RUNTIME_MANAGER_TIMEOUT"
_MANAGER_INVALID_RESPONSE = "LOCAL_RUNTIME_MANAGER_INVALID_RESPONSE"
_INSTANCE_CONFLICT = "LOCAL_RUNTIME_INSTANCE_CONFLICT"
_INSTANCE_INVALID = "LOCAL_RUNTIME_INSTANCE_ID_INVALID"
_PREPARATION_FAILED = "LOCAL_RUNTIME_PREPARATION_FAILED"
_START_FAILED = "LOCAL_RUNTIME_START_FAILED"
_MODEL_CONFLICT = "LOCAL_RUNTIME_MODEL_PROVIDER_CONFLICT"
_WORKSPACE_REQUIRED = "LOCAL_APPLICATION_WORKSPACE_REQUIRED"
_WORKSPACE_FORBIDDEN = "LOCAL_APPLICATION_WORKSPACE_FORBIDDEN"
_WORKSPACE_INVALID = "LOCAL_APPLICATION_WORKSPACE_INVALID"
_APPLICATION_INVALID = "LOCAL_APPLICATION_ID_INVALID"
_PATH_ALREADY_BOUND = "LOCAL_APPLICATION_PATH_ALREADY_BOUND"
_INSTANCE_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}
_STARTING_TIMEOUT_SECONDS = 120
_STARTING_POLL_SECONDS = 0.2
_SANDBOX_TOKEN_FILE = "sandbox-token"
_MANAGER_DIAGNOSTIC_LIMIT = 600
_MANAGER_ERROR_CODES = frozenset(
    {
        "UnsupportedPlatform",
        "ProbeFailed",
        "InvalidRequest",
        "InstanceConflict",
        "SpawnFailed",
        "ReadinessFailed",
        "StopFailed",
        "JournalFailed",
        "ReconcileIdentityMismatch",
    }
)
_MANAGER_AUTHORIZATION = re.compile(
    r"(?i)(\bauthorization\s*:\s*(?:bearer|basic)\s+)[^\s,;]+"
)
_MANAGER_INLINE_SECRET = re.compile(
    r"(?i)(\b(?:token|password|secret|api[_-]?key)\s*=\s*)[^\s,;]+"
)
_MANAGER_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/\s@]+@")
logger = logging.getLogger(__name__)

def local_workspace_scope_tenant_id(ctx: Any) -> int:
    """Use a device-local scope for desktop workspaces, not a remote tenant."""
    return 0 if runtime.is_desktop() else int(ctx.tenant_id)


def _is_local_session(session: Any) -> bool:
    return _text(getattr(session, "external_application_id", None)).startswith("local-")



def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=f"{code}: {message}")


def _text(value: object) -> str:
    return str(value or "").strip()


def local_workspace_path_text(value: str | Path) -> str:
    path = str(value)
    if os.name != "nt":
        return path
    if path.lower().startswith("\\\\?\\unc\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _workspace_path_identity(
    value: str | Path,
    *,
    windows: bool | None = None,
) -> str:
    if windows is None:
        windows = os.name == "nt"
    path = str(value)
    if not windows:
        return os.path.normcase(os.path.normpath(path))
    if path.lower().startswith("\\\\?\\unc\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return ntpath.normcase(ntpath.normpath(path))


def _manager_diagnostic(response: httpx.Response) -> tuple[str, str] | None:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    code = _text(payload.get("error"))
    raw_message = _text(payload.get("message"))
    if code not in _MANAGER_ERROR_CODES or not raw_message:
        return None
    printable_message = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in raw_message
    )
    message = " ".join(printable_message.split())
    message = _MANAGER_AUTHORIZATION.sub(r"\1<redacted>", message)
    message = _MANAGER_INLINE_SECRET.sub(r"\1<redacted>", message)
    message = _MANAGER_URL_CREDENTIALS.sub(r"\1<redacted>@", message)
    if not message:
        return None
    return code, message[:_MANAGER_DIAGNOSTIC_LIMIT]


def _application_id(session: Any) -> str:
    app_id = _text(getattr(session, "app_id", None))
    application_id = app_id or _text(getattr(session, "external_application_id", None))
    if not application_id:
        raise _error(400, _APPLICATION_INVALID, "Code 会话未绑定应用")
    if not _APPLICATION_COMPONENT.fullmatch(application_id):
        raise _error(400, _APPLICATION_INVALID, "应用标识不安全")
    return application_id


def _runtime_scope_id(ctx: Any, application_id: str) -> str:
    material = f"{int(ctx.tenant_id)}:{int(ctx.user.id)}:{application_id}".encode("utf-8")
    return f"scope-{hashlib.sha256(material).hexdigest()[:32]}"


def _manager_url(value: str) -> str:
    try:
        parsed = urlsplit(_text(value))
        port = parsed.port
    except ValueError as exc:
        raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 地址无效") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 地址无效")
    return f"http://127.0.0.1:{port}"


def _allocate_loopback_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        host, port = listener.getsockname()
    return f"{host}:{port}"


def _validate_workspace_directory(raw_path: str) -> Path:
    """Validate an owned local project directory without requiring Git.

    Local Code opens arbitrary existing directories.  Git remains available to
    an agent when a project has it, but selecting/opening a project must never
    initialize or reject a directory merely because it has no `.git` metadata.
    """
    if (
        not raw_path
        or not os.path.isabs(raw_path)
        or os.path.abspath(raw_path) != raw_path
        or os.path.normpath(raw_path) != raw_path
    ):
        raise _error(409, _WORKSPACE_INVALID, "注册工作区路径必须是规范绝对路径")
    try:
        repository_path = Path(raw_path).resolve(strict=True)
    except OSError as exc:
        raise _error(409, _WORKSPACE_INVALID, "注册的本地项目目录不存在") from exc
    if _workspace_path_identity(repository_path) != _workspace_path_identity(raw_path):
        raise _error(409, _WORKSPACE_INVALID, "注册工作区路径不能是别名或符号链接")
    if not repository_path.is_dir():
        raise _error(409, _WORKSPACE_INVALID, "注册的本地项目目录不是目录")
    return Path(local_workspace_path_text(repository_path))


def _validate_workspace_path(workspace: RegisteredWorkspace) -> Path:
    return _validate_workspace_directory(str(workspace.abs_path or ""))


async def _application_for_session(
    db: AsyncSession,
    session: Any,
    ctx: Any,
) -> Application | None:
    raw_app_id = _text(getattr(session, "app_id", None))
    if not raw_app_id:
        return None
    try:
        application_pk = int(raw_app_id)
    except ValueError as exc:
        raise _error(400, _APPLICATION_INVALID, "内部应用标识无效") from exc
    application = (
        await db.execute(select(Application).where(Application.id == application_pk))
    ).scalar_one_or_none()
    if application is None:
        raise _error(409, _WORKSPACE_REQUIRED, "应用未绑定本地项目目录")
    # Desktop local applications and their workspaces are owned by this device
    # (tenant 0), not by the Control Plane tenant carried by the signed-in user.
    # Keep the user check: a different local account must still never open it.
    workspace_tenant_id = (
        local_workspace_scope_tenant_id(ctx)
        if _is_local_session(session)
        else int(ctx.tenant_id)
    )
    if (
        application.tenant_id != workspace_tenant_id
        or application.user_id != int(ctx.user.id)
    ):
        raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问应用的本地项目目录")
    return application


async def _workspace_for_id(
    db: AsyncSession,
    ws_id: str,
    ctx: Any,
) -> RegisteredWorkspace:
    workspace_tenant_id = local_workspace_scope_tenant_id(ctx)
    owned = (
        await db.execute(
            select(RegisteredWorkspace).where(
                RegisteredWorkspace.ws_id == ws_id,
                RegisteredWorkspace.tenant_id == workspace_tenant_id,
                RegisteredWorkspace.user_id == int(ctx.user.id),
            )
        )
    ).scalar_one_or_none()
    if owned is not None:
        return owned
    foreign = (
        await db.execute(
            select(RegisteredWorkspace).where(RegisteredWorkspace.ws_id == ws_id)
        )
    ).scalar_one_or_none()
    if foreign is not None:
        raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问该本地项目目录")
    raise _error(409, _WORKSPACE_REQUIRED, "应用必须先绑定本地项目目录")


async def resolve_registered_workspace(
    db: AsyncSession,
    session: Any,
    ctx: Any,
    *,
    validate_git: bool = True,
) -> RegisteredWorkspace:
    """Resolve one owned registered workspace without falling back to local paths."""
    session_tenant_id = getattr(session, "tenant_id", None)
    session_user_id = getattr(session, "user_id", None)
    workspace_tenant_id = local_workspace_scope_tenant_id(ctx)
    expected_session_tenant_id = (
        workspace_tenant_id if _is_local_session(session) else int(ctx.tenant_id)
    )
    if (
        session_tenant_id is not None
        and int(session_tenant_id) != expected_session_tenant_id
    ) or (
        session_user_id is not None
        and int(session_user_id) != int(ctx.user.id)
    ):
        raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问该 Code 会话的本地项目目录")

    workspace_id = _text(getattr(session, "workspace_id", None))
    application = await _application_for_session(db, session, ctx)
    if not workspace_id and application is not None:
        workspace_id = _text(application.source_workspace_id)

    if not workspace_id and application is None:
        external_application_id = _text(getattr(session, "external_application_id", None))
        if external_application_id:
            owned = (
                await db.execute(
                    select(RegisteredWorkspace)
                    .where(
                        RegisteredWorkspace.apaas_app_id == external_application_id,
                        RegisteredWorkspace.tenant_id == workspace_tenant_id,
                        RegisteredWorkspace.user_id == int(ctx.user.id),
                    )
                    .limit(2)
                )
            ).scalars().all()
            if len(owned) == 1:
                workspace_id = owned[0].ws_id
            elif len(owned) > 1:
                raise _error(409, _WORKSPACE_REQUIRED, "应用绑定了多个本地项目目录")
            else:
                foreign = (
                    await db.execute(
                        select(RegisteredWorkspace)
                        .where(
                            RegisteredWorkspace.apaas_app_id == external_application_id
                        )
                        .limit(1)
                    )
                ).scalars().all()
                if foreign:
                    raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问该本地项目目录")

    if not workspace_id:
        raise _error(409, _WORKSPACE_REQUIRED, "应用必须先绑定本地项目目录")
    workspace = await _workspace_for_id(db, workspace_id, ctx)
    if validate_git:
        _validate_workspace_path(workspace)
    return workspace


def _safe_workspace_component(value: object) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", _text(value))[:60].strip(".-_")
    return safe_name or "local-app"


def default_local_workspace_root() -> Path:
    configured_root = _text(os.environ.get("APAAS_WORKSPACE_ROOT"))
    if configured_root:
        return Path(configured_root).expanduser()
    data_dir = _text(os.environ.get("DOLPHIN_DESKTOP_DATA_DIR"))
    if data_dir:
        return Path(data_dir) / "workspaces"
    return Path.home() / ".ruijing-builder" / "workspaces"


def default_local_workspace_path(app_code: str) -> Path:
    return default_local_workspace_root() / _safe_workspace_component(app_code)


def _local_application_path_error(exc: LocalApplicationPathError) -> HTTPException:
    status_code = 400 if exc.code == "LOCAL_APPLICATION_PATH_NOT_ABSOLUTE" else 409
    return _error(status_code, exc.code, str(exc))


def _optional_remote_identifier(value: object) -> str | None:
    identifier = _text(value)
    return identifier[:120] or None


def _default_logical_application_id(application_id: str) -> str:
    return f"local:{application_id}"[:160]


async def ensure_registered_local_workspace(
    db: AsyncSession,
    ctx: Any,
    *,
    application_id: str,
    display_name: str,
    workspace_path: str | Path | None = None,
    directory_mode: LocalApplicationDirectoryMode = "new_directory",
    logical_application_id: str | None = None,
    linked_remote_application_id: str | None = None,
    linked_remote_deployment_id: str | None = None,
) -> RegisteredWorkspace:
    external_app_id = _text(application_id)
    if not external_app_id or not _APPLICATION_COMPONENT.fullmatch(external_app_id):
        raise _error(400, _APPLICATION_INVALID, "应用标识不安全")

    requested_path = workspace_path or default_local_workspace_path(external_app_id)
    try:
        resolved_abs = prepare_local_application_workspace(
            requested_path,
            directory_mode=directory_mode,
        )
    except LocalApplicationPathError as exc:
        raise _local_application_path_error(exc) from exc
    remote_application_id = _optional_remote_identifier(linked_remote_application_id)
    remote_deployment_id = _optional_remote_identifier(linked_remote_deployment_id)
    path_digest = local_workspace_path_digest(resolved_abs)

    candidates = (await db.execute(select(RegisteredWorkspace))).scalars().all()
    matching = [
        candidate
        for candidate in candidates
        if candidate.path_identity_digest == path_digest
        or local_workspace_path_identity(candidate.abs_path)
        == local_workspace_path_identity(resolved_abs)
    ]
    if len(matching) > 1:
        raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录存在重复历史绑定")
    existing = matching[0] if matching else None
    if existing is not None:
        if existing.tenant_id != int(ctx.tenant_id):
            raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录已绑定到其他应用")
        if existing.user_id != int(ctx.user.id):
            raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录已绑定给其他用户")
        bound_application = _text(existing.apaas_app_id)
        if (
            remote_application_id
            and _text(existing.linked_remote_application_id)
            and remote_application_id != _text(existing.linked_remote_application_id)
        ) or (
            remote_deployment_id
            and _text(existing.linked_remote_deployment_id)
            and remote_deployment_id != _text(existing.linked_remote_deployment_id)
        ):
            raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录已绑定到其他远程应用")
        if not bound_application:
            existing.apaas_app_id = external_app_id
            bound_application = external_app_id
            existing.display_name = _text(display_name)[:200] or _safe_workspace_component(external_app_id)
        if not _text(existing.logical_application_id):
            existing.logical_application_id = (
                _text(logical_application_id)[:160]
                or _default_logical_application_id(bound_application)
            )
        if remote_application_id and not _text(existing.linked_remote_application_id):
            existing.linked_remote_application_id = remote_application_id
        if remote_deployment_id and not _text(existing.linked_remote_deployment_id):
            existing.linked_remote_deployment_id = remote_deployment_id
        existing.workspace_type = "code-local-application"
        existing.path_identity_digest = path_digest
        existing.last_opened_at = datetime.utcnow()
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录已绑定到其他应用")
        await db.refresh(existing)
        return existing

    workspace = RegisteredWorkspace(
        ws_id=f"{int(ctx.user.id)}_{uuid.uuid4().hex[:8]}",
        abs_path=local_workspace_path_text(resolved_abs),
        path_identity_digest=path_digest,
        user_id=int(ctx.user.id),
        tenant_id=int(ctx.tenant_id),
        workspace_type="code-local-application",
        apaas_app_id=external_app_id,
        logical_application_id=(
            _text(logical_application_id)[:160]
            or _default_logical_application_id(external_app_id)
        ),
        linked_remote_application_id=remote_application_id,
        linked_remote_deployment_id=remote_deployment_id,
        display_name=_text(display_name)[:200] or _safe_workspace_component(external_app_id),
    )
    db.add(workspace)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        concurrent_rows = (
            await db.execute(select(RegisteredWorkspace))
        ).scalars().all()
        concurrent = [
            candidate
            for candidate in concurrent_rows
            if candidate.path_identity_digest == path_digest
            or local_workspace_path_identity(candidate.abs_path)
            == local_workspace_path_identity(resolved_abs)
        ]
        if not concurrent:
            raise
        if len(concurrent) > 1:
            raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录存在重复历史绑定")
        return await ensure_registered_local_workspace(
            db,
            ctx,
            application_id=external_app_id,
            display_name=display_name,
            workspace_path=resolved_abs,
            directory_mode=directory_mode,
            logical_application_id=logical_application_id,
            linked_remote_application_id=remote_application_id,
            linked_remote_deployment_id=remote_deployment_id,
        )
    await db.refresh(workspace)
    return workspace


async def rebind_registered_local_workspace(
    db: AsyncSession,
    session: Any,
    ctx: Any,
    *,
    workspace_path: str | Path,
) -> RegisteredWorkspace:
    workspace = await resolve_registered_workspace(
        db,
        session,
        ctx,
        validate_git=False,
    )
    try:
        resolved_abs = prepare_local_application_workspace(
            workspace_path,
            directory_mode="existing_directory",
        )
    except LocalApplicationPathError as exc:
        raise _local_application_path_error(exc) from exc
    path_digest = local_workspace_path_digest(resolved_abs)
    candidates = (
        await db.execute(
            select(RegisteredWorkspace).where(RegisteredWorkspace.id != workspace.id)
        )
    ).scalars().all()
    occupied = next(
        (
            candidate
            for candidate in candidates
            if local_workspace_path_identity(candidate.abs_path)
            == local_workspace_path_identity(resolved_abs)
        ),
        None,
    )
    if occupied is not None:
        raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录已绑定给其他应用")

    workspace.abs_path = local_workspace_path_text(resolved_abs)
    workspace.path_identity_digest = path_digest
    workspace.last_opened_at = datetime.utcnow()
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        conflicts = (
            await db.execute(
                select(RegisteredWorkspace).where(
                    RegisteredWorkspace.path_identity_digest == path_digest,
                    RegisteredWorkspace.id != workspace.id,
                )
            )
        ).scalars().all()
        if conflicts:
            raise _error(409, _PATH_ALREADY_BOUND, "本地项目目录已绑定给其他应用")
        raise
    await db.refresh(workspace)
    return workspace


def build_runtime_context(
    *,
    tenant_id: int,
    application_id: str,
    workspace_id: str,
    sandbox_instance_id: str,
    conversation_id: str,
    repo_url: str,
    default_branch: str,
    user_id: int,
    display_name: str,
    codex_home: Path,
    runtime_dir: Path,
) -> dict[str, Any]:
    return {
        "tenantId": str(tenant_id),
        "appId": application_id,
        "workspaceId": workspace_id,
        "sandboxInstanceId": sandbox_instance_id,
        "conversationId": conversation_id,
        "repoUrl": repo_url,
        "defaultBranch": default_branch,
        "seedTemplateRef": "local-existing-worktree",
        "user": {
            "userId": str(user_id),
            "displayName": display_name,
        },
        "storage": {
            "userCodexHome": str(codex_home),
            "appWorkspaceContext": str(runtime_dir),
        },
    }


def _open_directory_at(parent_fd: int, component: str, *, create: bool) -> int:
    if not _APPLICATION_COMPONENT.fullmatch(component):
        raise ValueError("unsafe runtime path component")
    if create:
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(component, flags, dir_fd=parent_fd)
    os.fchmod(directory_fd, 0o700)
    return directory_fd


def _runtime_root_path(data_dir: Path) -> Path:
    raw_path = str(data_dir)
    if (
        not raw_path
        or not os.path.isabs(raw_path)
        or os.path.abspath(raw_path) != raw_path
        or os.path.normpath(raw_path) != raw_path
    ):
        raise ValueError("desktop data directory must be a canonical absolute path")
    os.lstat(raw_path)
    resolved = Path(raw_path).resolve(strict=True)
    if str(resolved) != raw_path:
        raise ValueError("desktop data directory must not be an alias")
    return resolved


def _runtime_root_fd(data_dir: Path) -> tuple[Path, int]:
    resolved = _runtime_root_path(data_dir)
    raw_path = str(resolved)
    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in Path(raw_path).parts[1:]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return resolved, current_fd
    except Exception:
        os.close(current_fd)
        raise


@contextlib.contextmanager
def _scope_directory_fds(
    data_dir: Path,
    runtime_scope_id: str,
):
    if os.name == "nt":
        root_path = _runtime_root_path(data_dir)
        local_runtimes_path = _open_runtime_directory(
            root_path,
            "local-runtimes",
            create=True,
        )
        scope_path = _open_runtime_directory(
            local_runtimes_path,
            runtime_scope_id,
            create=True,
        )
        yield {
            "root_path": root_path,
            "scope_path": scope_path,
            "scope_fd": scope_path,
        }
        return

    root_path, root_fd = _runtime_root_fd(data_dir)
    descriptors = [root_fd]
    try:
        local_runtimes_fd = _open_directory_at(root_fd, "local-runtimes", create=True)
        descriptors.append(local_runtimes_fd)
        scope_fd = _open_directory_at(local_runtimes_fd, runtime_scope_id, create=True)
        descriptors.append(scope_fd)
        yield {
            "root_path": root_path,
            "scope_path": root_path / "local-runtimes" / runtime_scope_id,
            "scope_fd": scope_fd,
        }
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextlib.contextmanager
def _runtime_directory_fds(
    data_dir: Path,
    runtime_scope_id: str,
    sandbox_instance_id: str,
    *,
    create_instance: bool,
):
    with _scope_directory_fds(data_dir, runtime_scope_id) as scope:
        if os.name == "nt":
            codex_home = _open_runtime_directory(
                scope["scope_path"],
                "codex-home",
                create=True,
            )
            instances_path = _open_runtime_directory(
                scope["scope_path"],
                "instances",
                create=True,
            )
            runtime_dir = _open_runtime_directory(
                instances_path,
                sandbox_instance_id,
                create=create_instance,
            )
            yield {
                **scope,
                "codex_home": codex_home,
                "runtime_dir": runtime_dir,
                "runtime_fd": runtime_dir,
            }
            return

        descriptors: list[int] = []
        try:
            codex_home_fd = _open_directory_at(scope["scope_fd"], "codex-home", create=True)
            descriptors.append(codex_home_fd)
            instances_fd = _open_directory_at(scope["scope_fd"], "instances", create=True)
            descriptors.append(instances_fd)
            runtime_fd = _open_directory_at(
                instances_fd,
                sandbox_instance_id,
                create=create_instance,
            )
            descriptors.append(runtime_fd)
            yield {
                **scope,
                "codex_home": scope["scope_path"] / "codex-home",
                "runtime_dir": scope["scope_path"] / "instances" / sandbox_instance_id,
                "runtime_fd": runtime_fd,
            }
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


def _open_runtime_directory(parent: Path, component: str, *, create: bool) -> Path:
    if not _APPLICATION_COMPONENT.fullmatch(component):
        raise ValueError("unsafe runtime path component")
    target = parent / component
    if create:
        target.mkdir(mode=0o700, exist_ok=True)
    resolved = target.resolve(strict=True)
    if resolved != target or target.is_symlink() or not target.is_dir():
        raise ValueError("runtime directory is unsafe")
    return resolved


def _runtime_file_path(parent: int | Path, name: str) -> Path | None:
    if not _APPLICATION_COMPONENT.fullmatch(name):
        raise ValueError("unsafe runtime file name")
    if isinstance(parent, Path):
        return parent / name
    return None


def _atomic_write_json_at(parent_fd: int | Path, name: str, payload: dict[str, Any]) -> None:
    if not _APPLICATION_COMPONENT.fullmatch(name):
        raise ValueError("unsafe runtime file name")
    temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
    parent_path = _runtime_file_path(parent_fd, name)
    if parent_path is not None:
        temporary_path = parent_path.parent / temporary_name
        serialized = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        with temporary_path.open("xb") as file:
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, parent_path)
        return

    file_fd = -1
    try:
        file_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        serialized = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        offset = 0
        while offset < len(serialized):
            offset += os.write(file_fd, serialized[offset:])
        os.fsync(file_fd)
        os.close(file_fd)
        file_fd = -1
        os.replace(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _atomic_write_secret_at(parent_fd: int | Path, name: str, value: str) -> None:
    if not _APPLICATION_COMPONENT.fullmatch(name):
        raise ValueError("unsafe runtime file name")
    if not value or "\x00" in value:
        raise ValueError("runtime secret is invalid")
    temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
    parent_path = _runtime_file_path(parent_fd, name)
    if parent_path is not None:
        temporary_path = parent_path.parent / temporary_name
        with temporary_path.open("xb") as file:
            file.write(value.encode("ascii"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, parent_path)
        return

    file_fd = -1
    try:
        file_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        encoded = value.encode("ascii")
        offset = 0
        while offset < len(encoded):
            offset += os.write(file_fd, encoded[offset:])
        os.fsync(file_fd)
        os.close(file_fd)
        file_fd = -1
        os.replace(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _read_json_at(parent_fd: int | Path, name: str) -> dict[str, Any]:
    parent_path = _runtime_file_path(parent_fd, name)
    if parent_path is not None:
        if parent_path.is_symlink():
            raise ValueError("runtime JSON file is unsafe")
        value = json.loads(parent_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("runtime JSON must be an object")
        return value

    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        content = b""
        while chunk := os.read(file_fd, 65536):
            content += chunk
        value = json.loads(content.decode("utf-8"))
    finally:
        os.close(file_fd)
    if not isinstance(value, dict):
        raise ValueError("runtime JSON must be an object")
    return value


def _read_secret_at(parent_fd: int | Path, name: str) -> str:
    parent_path = _runtime_file_path(parent_fd, name)
    if parent_path is not None:
        if parent_path.is_symlink() or not parent_path.is_file():
            raise ValueError("runtime secret file is unsafe")
        content = parent_path.read_bytes()
    else:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ValueError("runtime secret file is unsafe")
            content = b""
            while chunk := os.read(file_fd, 65536):
                content += chunk
        finally:
            os.close(file_fd)
    try:
        value = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("runtime secret is invalid") from exc
    if not value or "\x00" in value or any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise ValueError("runtime secret is invalid")
    return value


def _new_instance_id() -> str:
    sandbox_instance_id = f"local-{uuid.uuid4().hex}"
    if len(sandbox_instance_id) > _MAX_INSTANCE_ID_LENGTH or not _INSTANCE_COMPONENT.fullmatch(
        sandbox_instance_id
    ):
        raise _error(409, _INSTANCE_INVALID, "本地 Runtime 实例标识无效")
    return sandbox_instance_id


def _runtime_url(value: object) -> tuple[str, tuple[str, str, int]]:
    raw = _text(value)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise _error(
            502,
            _MANAGER_INVALID_RESPONSE,
            "本地 Runtime manager 返回了无效 Runtime URL",
        ) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _error(
            502,
            _MANAGER_INVALID_RESPONSE,
            "本地 Runtime manager 返回了无效 Runtime URL",
        )
    return raw, (parsed.scheme, parsed.hostname, port)


def _normalized_builder_path(value: str) -> str:
    decoded = unquote(value)
    if (
        "\\" in decoded
        or any(ord(character) < 32 for character in decoded)
        or any(segment in {".", ".."} for segment in decoded.split("/"))
    ):
        raise _error(
            502,
            _MANAGER_INVALID_RESPONSE,
            "本地 Runtime manager 返回了无效 Runtime URL",
        )
    if not decoded.startswith("/builder/"):
        raise _error(
            502,
            _MANAGER_INVALID_RESPONSE,
            "本地 Runtime manager 返回了无效 Runtime URL",
        )
    return decoded


def _validated_manager_urls(payload: dict[str, Any]) -> tuple[str, str]:
    runtime_base_url, runtime_origin = _runtime_url(payload.get("runtime_base_url"))
    builder_url, builder_origin = _runtime_url(payload.get("builder_url"))
    runtime_path = urlsplit(runtime_base_url).path
    _normalized_builder_path(urlsplit(builder_url).path)
    if builder_origin != runtime_origin or runtime_path not in {"", "/"}:
        raise _error(
            502,
            _MANAGER_INVALID_RESPONSE,
            "本地 Runtime manager 返回了无效 Runtime URL",
        )
    return runtime_base_url, builder_url


async def _repo_metadata(
    db: AsyncSession,
    workspace: RegisteredWorkspace,
    application_id: str,
    ctx: Any,
    repository_path: Path,
) -> tuple[str, str]:
    remote = (
        await db.execute(
            select(WorkspaceGitRemote).where(
                WorkspaceGitRemote.ws_id == workspace.ws_id,
                WorkspaceGitRemote.tenant_id == int(ctx.tenant_id),
                WorkspaceGitRemote.user_id == int(ctx.user.id),
            )
        )
    ).scalar_one_or_none()
    default_branch = _text(getattr(remote, "default_branch", None)) or "main"
    if remote is not None:
        raw = _text(remote.remote_url)
        parsed = urlsplit(raw)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        ):
            return raw, default_branch
    return f"https://local.invalid/{quote(application_id, safe='')}.git", default_branch


async def _provider_document(
    db: AsyncSession,
    ctx: Any,
    selected_config_id: int | None,
    **kwargs: Any,
) -> tuple[dict[str, Any], tuple[str, str, str]]:
    try:
        return await resolve_provider_document(
            db, ctx, selected_config_id, **kwargs
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(503, _PREPARATION_FAILED, "无法解析本地 Runtime 模型配置") from exc


def _provider_identity_from_document(document: dict[str, Any]) -> tuple[str, str, str]:
    return provider_identity_from_document(document)


class LocalRuntimeClient:
    """Translate a Code session into one deterministic local runtime instance."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        desktop_data_dir: str | Path | None = None,
        runtime_data_dir: str | Path | None = None,
        agent_runtime_path: str | Path | None = None,
        engineering_service_factory: Callable[[Path], EngineeringSessionService] = EngineeringSessionService,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.url = _manager_url(url)
        self.token = _text(token)
        self.desktop_data_dir = (
            Path(desktop_data_dir).expanduser() if desktop_data_dir is not None else None
        )
        self.runtime_data_dir = (
            Path(runtime_data_dir).expanduser()
            if runtime_data_dir is not None
            else self.desktop_data_dir
        )
        self.agent_runtime_path = (
            Path(agent_runtime_path).expanduser() if agent_runtime_path is not None else None
        )
        self.engineering_service_factory = engineering_service_factory
        self.http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5, read=140, write=10, pool=10)
            )
        )

    @classmethod
    def from_environment(cls) -> LocalRuntimeClient:
        required = {
            "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL": os.getenv(
                "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL"
            ),
            "DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN": os.getenv(
                "DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN"
            ),
            "DOLPHIN_DESKTOP_DATA_DIR": os.getenv("DOLPHIN_DESKTOP_DATA_DIR"),
            "DOLPHIN_AGENT_RUNTIME_PATH": os.getenv("DOLPHIN_AGENT_RUNTIME_PATH"),
        }
        if any(not _text(value) for value in required.values()):
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
        runtime_data_dir = os.getenv("DOLPHIN_LOCAL_RUNTIME_DATA_DIR")
        if not _text(runtime_data_dir):
            runtime_data_dir = str(
                Path(str(required["DOLPHIN_DESKTOP_DATA_DIR"])) / "runtime"
            )
        return cls(
            str(required["DOLPHIN_LOCAL_RUNTIME_MANAGER_URL"]),
            str(required["DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN"]),
            desktop_data_dir=str(required["DOLPHIN_DESKTOP_DATA_DIR"]),
            runtime_data_dir=runtime_data_dir,
            agent_runtime_path=str(required["DOLPHIN_AGENT_RUNTIME_PATH"]),
        )

    async def _manager_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if not self.token:
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
        started_at = time.monotonic()
        try:
            async with self.http_client_factory() as client:
                return await client.request(
                    method,
                    f"{self.url}{path}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=payload,
                )
        except httpx.RequestError as exc:
            elapsed_ms = round((time.monotonic() - started_at) * 1000)
            logger.warning(
                "local Runtime manager request failed method=%s path=%s elapsed_ms=%s error_type=%s",
                method,
                path,
                elapsed_ms,
                type(exc).__name__,
            )
            if isinstance(exc, httpx.ConnectTimeout):
                raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 连接超时") from exc
            if isinstance(exc, httpx.ConnectError):
                raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 无法连接") from exc
            if isinstance(
                exc,
                (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout),
            ):
                message = (
                    "本地 Runtime manager 启动请求超时"
                    if method.upper() == "POST" and path.endswith("/instances/start")
                    else "本地 Runtime manager 请求超时"
                )
                raise _error(503, _MANAGER_TIMEOUT, message) from exc
            if isinstance(exc, httpx.RemoteProtocolError):
                raise _error(
                    502,
                    _MANAGER_INVALID_RESPONSE,
                    "本地 Runtime manager 连接异常中断",
                ) from exc
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 不可用") from exc

    @staticmethod
    def _manager_error(response: httpx.Response) -> HTTPException:
        if response.status_code == 409:
            return _error(409, _INSTANCE_CONFLICT, "本地应用已有冲突的 Runtime 实例")
        if diagnostic := _manager_diagnostic(response):
            code, message = diagnostic
            return _error(503, _START_FAILED, f"{code}: {message}")
        return _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 不可用")

    @staticmethod
    def _manager_status(
        response: httpx.Response,
        runtime_scope_id: str,
        application_id: str,
        sandbox_instance_id: str | None = None,
    ) -> dict[str, Any]:
        if response.status_code != 200:
            raise LocalRuntimeClient._manager_error(response)
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise _error(
                502,
                _MANAGER_INVALID_RESPONSE,
                "本地 Runtime manager 返回了无效响应",
            ) from exc
        if not isinstance(payload, dict):
            raise _error(502, _MANAGER_INVALID_RESPONSE, "本地 Runtime manager 返回了无效响应")
        if (
            _text(payload.get("runtime_scope_id")) != runtime_scope_id
            or
            _text(payload.get("application_id")) != application_id
            or (
                sandbox_instance_id is not None
                and _text(payload.get("sandbox_instance_id")) != sandbox_instance_id
            )
        ):
            raise _error(
                502,
                _MANAGER_INVALID_RESPONSE,
                "本地 Runtime manager 返回了不匹配的实例",
            )
        return payload

    @staticmethod
    def _opened(
        manager_status: dict[str, Any],
        *,
        application_id: str,
        workspace_id: str,
        sandbox_instance_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        runtime_base_url, builder_url = _validated_manager_urls(manager_status)
        return {
            "applicationId": application_id,
            "workspaceId": workspace_id,
            "sandboxInstanceId": sandbox_instance_id,
            "conversationId": conversation_id,
            "state": _text(manager_status.get("state")),
            "runtimeBaseUrl": runtime_base_url,
            "specReviewUrl": builder_url,
        }

    @staticmethod
    def _lock(runtime_scope_id: str) -> asyncio.Lock:
        key = (id(asyncio.get_running_loop()), runtime_scope_id)
        return _INSTANCE_LOCKS.setdefault(key, asyncio.Lock())

    async def _existing_status(
        self,
        status_path: str,
        runtime_scope_id: str,
        application_id: str,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + _STARTING_TIMEOUT_SECONDS
        while True:
            response = await self._manager_request("GET", status_path)
            if response.status_code == 404:
                return None
            status = self._manager_status(response, runtime_scope_id, application_id)
            state = _text(status.get("state"))
            if state == "ready":
                _validated_manager_urls(status)
                return status
            if state != "starting":
                raise _error(409, _INSTANCE_CONFLICT, "本地应用已有不可复用的 Runtime 实例")
            if time.monotonic() >= deadline:
                raise _error(503, _MANAGER_TIMEOUT, "本地 Runtime 启动状态等待超时")
            await asyncio.sleep(_STARTING_POLL_SECONDS)

    async def application_open_status(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
    ) -> dict[str, Any]:
        application_id = _application_id(session)
        runtime_scope_id = _runtime_scope_id(ctx, application_id)
        workspace = await resolve_registered_workspace(
            db,
            session,
            ctx,
            validate_git=False,
        )
        _validate_workspace_path(workspace)
        response = await self._manager_request(
            "GET",
            f"/v1/local-runtime/instances/{runtime_scope_id}",
        )
        if response.status_code == 404:
            return {
                "phase": "checking_project",
                "runtime_state": "missing",
                "runtime_scope_id": runtime_scope_id,
            }
        status = self._manager_status(response, runtime_scope_id, application_id)
        state = _text(status.get("state"))
        if state == "starting":
            phase = "starting_runtime"
        elif state == "ready":
            _validated_manager_urls(status)
            phase = "opening_workbench"
        else:
            raise _error(409, _INSTANCE_CONFLICT, "本地应用已有不可复用的 Runtime 实例")
        return {
            "phase": phase,
            "runtime_state": state,
            "runtime_scope_id": runtime_scope_id,
            "sandbox_instance_id": _text(status.get("sandbox_instance_id")) or None,
        }

    async def restart_application(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
        *,
        validate_workspace: bool = True,
    ) -> dict[str, Any]:
        application_id = _application_id(session)
        runtime_scope_id = _runtime_scope_id(ctx, application_id)
        if validate_workspace:
            workspace = await resolve_registered_workspace(
                db,
                session,
                ctx,
                validate_git=False,
            )
            _validate_workspace_path(workspace)
        status_path = f"/v1/local-runtime/instances/{runtime_scope_id}"
        response = await self._manager_request("GET", status_path)
        if response.status_code == 404:
            return {
                "runtime_state": "missing",
                "runtime_scope_id": runtime_scope_id,
                "stopped": True,
            }
        status = self._manager_status(response, runtime_scope_id, application_id)
        sandbox_instance_id = _text(status.get("sandbox_instance_id"))
        if not sandbox_instance_id:
            raise _error(502, _MANAGER_INVALID_RESPONSE, "本地 Runtime manager 返回了无效响应")
        stopped = self._manager_status(
            await self._manager_request(
                "DELETE",
                f"{status_path}/{sandbox_instance_id}",
            ),
            runtime_scope_id,
            application_id,
            sandbox_instance_id,
        )
        if _text(stopped.get("state")) != "stopped":
            raise _error(502, _MANAGER_INVALID_RESPONSE, "本地 Runtime manager 未停止实例")
        return {
            "runtime_state": "stopped",
            "runtime_scope_id": runtime_scope_id,
            "sandbox_instance_id": sandbox_instance_id,
            "stopped": True,
        }

    async def _assert_reused_provider(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
        runtime_scope_id: str,
        sandbox_instance_id: str,
        provider_options: dict[str, Any] | None = None,
    ) -> None:
        if self.runtime_data_dir is None:
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
        selected_document, selected_identity = await _provider_document(
            db,
            ctx,
            getattr(session, "selected_llm_config_id", None),
            **(provider_options or {}),
        )
        try:
            with _runtime_directory_fds(
                self.runtime_data_dir,
                runtime_scope_id,
                sandbox_instance_id,
                create_instance=False,
            ) as paths:
                stored = _read_json_at(paths["runtime_fd"], "model-provider.json")
                if (
                    _provider_identity_from_document(stored) != selected_identity
                    or provider_catalog_identity(stored)
                    != provider_catalog_identity(selected_document)
                ):
                    raise _error(
                        409,
                        _MODEL_CONFLICT,
                        "当前会话选择的 Coding 模型与应用 Runtime 不兼容",
                    )
        except HTTPException:
            raise
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            raise _error(503, _PREPARATION_FAILED, "无法读取本地 Runtime 模型配置") from exc

    def _entry_token(
        self,
        runtime_scope_id: str,
        sandbox_instance_id: str,
    ) -> str:
        if self.runtime_data_dir is None:
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
        try:
            with _runtime_directory_fds(
                self.runtime_data_dir,
                runtime_scope_id,
                sandbox_instance_id,
                create_instance=False,
            ) as paths:
                return _read_secret_at(paths["runtime_fd"], _SANDBOX_TOKEN_FILE)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _error(503, _START_FAILED, "无法读取本地 Runtime entry token") from exc

    async def _start(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
        workspace: RegisteredWorkspace,
        repository_path: Path,
        runtime_scope_id: str,
        application_id: str,
        sandbox_instance_id: str,
        conversation_id: str,
        provider_document: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            managed_worktree_path = repository_path.resolve(strict=True)
            if self.runtime_data_dir is None or self.agent_runtime_path is None:
                raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
            agent_runtime_path = self.agent_runtime_path.resolve(strict=True)
            if not agent_runtime_path.is_file() or agent_runtime_path.is_symlink():
                raise ValueError("agent runtime executable is invalid")
            runtime_address = _allocate_loopback_address()
            repo_url, default_branch = await _repo_metadata(
                db,
                workspace,
                application_id,
                ctx,
                repository_path,
            )
            display_name = _text(getattr(ctx.user, "display_name", None)) or _text(
                getattr(ctx.user, "username", None)
            )
            with _runtime_directory_fds(
                self.runtime_data_dir,
                runtime_scope_id,
                sandbox_instance_id,
                create_instance=True,
            ) as paths:
                codex_home = paths["codex_home"]
                runtime_dir = paths["runtime_dir"]
                context = build_runtime_context(
                    tenant_id=int(ctx.tenant_id),
                    application_id=application_id,
                    workspace_id=workspace.ws_id,
                    sandbox_instance_id=sandbox_instance_id,
                    conversation_id=conversation_id,
                    repo_url=repo_url,
                    default_branch=default_branch,
                    user_id=int(ctx.user.id),
                    display_name=display_name,
                    codex_home=codex_home,
                    runtime_dir=runtime_dir,
                )
                _atomic_write_json_at(paths["runtime_fd"], "runtime-context.json", context)
                _atomic_write_json_at(paths["runtime_fd"], "model-provider.json", provider_document)
                _atomic_write_secret_at(
                    paths["runtime_fd"],
                    _SANDBOX_TOKEN_FILE,
                    secrets.token_urlsafe(32),
                )
                context_path = runtime_dir / "runtime-context.json"
                model_path = runtime_dir / "model-provider.json"
                token_path = runtime_dir / _SANDBOX_TOKEN_FILE
        except HTTPException:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise _error(503, _PREPARATION_FAILED, "无法准备本地 Runtime 配置") from exc

        environment = {
            "APAAS_RUNTIME_CONTEXT_PATH": str(context_path),
            "APAAS_MODEL_PROVIDER_PATH": str(model_path),
            "APAAS_WORKSPACE_INIT_MODE": "desktop_existing_workspace",
            "APAAS_CI_HANDOFF_MODE": "disabled",
            "APAAS_CODEX_SESSION_MODE": "codex",
            "APAAS_REPO_WORKSPACE_PATH": str(managed_worktree_path),
            "APAAS_WORKSPACE_PATH": str(managed_worktree_path),
            "APAAS_RUNTIME_WORKSPACE_PATH": str(runtime_dir),
            "APAAS_CODEX_HOME": str(codex_home),
            "APAAS_RUNTIME_ADDR": runtime_address,
            "APAAS_AUTH_MODE": "disabled_local",
            "APAAS_SANDBOX_TOKEN_PATH": str(token_path),
        }
        start_payload = {
            "runtime_scope_id": runtime_scope_id,
            "application_id": application_id,
            "sandbox_instance_id": sandbox_instance_id,
            "workspace_id": workspace.ws_id,
            "worktree_path": str(managed_worktree_path),
            "codex_home": str(codex_home),
            "runtime_dir": str(runtime_dir),
            "runtime_context_path": str(context_path),
            "agent_runtime_path": str(agent_runtime_path),
            "runtime_addr": runtime_address,
            "environment": environment,
        }
        manager_status = self._manager_status(
            await self._manager_request(
                "POST",
                "/v1/local-runtime/instances/start",
                payload=start_payload,
            ),
            runtime_scope_id,
            application_id,
            sandbox_instance_id,
        )
        if _text(manager_status.get("state")) != "ready":
            raise _error(502, _START_FAILED, "本地 Runtime manager 未返回 ready 实例")
        _validated_manager_urls(manager_status)
        return manager_status

    async def open_application_with_entry_token(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
        *,
        on_phase: Callable[[str], None] | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        application_id = _application_id(session)
        runtime_scope_id = _runtime_scope_id(ctx, application_id)
        workspace = await resolve_registered_workspace(
            db,
            session,
            ctx,
            validate_git=False,
        )
        repository_path = _validate_workspace_path(workspace)
        if on_phase is not None:
            on_phase("starting_runtime")

        # The Runtime is shared by an application scope. Agent-runtime derives
        # the sidecar conversation ID from each runtime agent session when this
        # context field is empty, so it must not capture the first shell session.
        conversation_id = ""
        status_path = f"/v1/local-runtime/instances/{runtime_scope_id}"
        manager_status = await self._existing_status(
            status_path,
            runtime_scope_id,
            application_id,
        )
        if manager_status is not None:
            sandbox_instance_id = _text(manager_status.get("sandbox_instance_id"))
            await self._assert_reused_provider(
                db,
                session,
                ctx,
                runtime_scope_id,
                sandbox_instance_id,
                provider_options,
            )
        if manager_status is None:
            async with self._lock(runtime_scope_id):
                if self.runtime_data_dir is None:
                    raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
                manager_status = await self._existing_status(
                    status_path,
                    runtime_scope_id,
                    application_id,
                )
                if manager_status is not None:
                    sandbox_instance_id = _text(manager_status.get("sandbox_instance_id"))
                    await self._assert_reused_provider(
                        db,
                        session,
                        ctx,
                        runtime_scope_id,
                        sandbox_instance_id,
                        provider_options,
                    )
                else:
                    sandbox_instance_id = _new_instance_id()
                    provider_document, _identity = await _provider_document(
                        db,
                        ctx,
                        getattr(session, "selected_llm_config_id", None),
                        **(provider_options or {}),
                    )
                    manager_status = await self._start(
                        db,
                        session,
                        ctx,
                        workspace,
                        repository_path,
                        runtime_scope_id,
                        application_id,
                        sandbox_instance_id,
                        conversation_id,
                        provider_document,
                    )

        opened = self._opened(
            manager_status,
            application_id=application_id,
            workspace_id=workspace.ws_id,
            sandbox_instance_id=sandbox_instance_id,
            conversation_id=conversation_id,
        )
        return opened, self._entry_token(runtime_scope_id, sandbox_instance_id)

    async def open_application(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
    ) -> dict[str, Any]:
        opened, _entry_token = await self.open_application_with_entry_token(db, session, ctx)
        return opened
