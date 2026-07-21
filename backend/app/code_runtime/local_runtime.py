"""Prepare local application runtime requests for the desktop runtime manager."""
from __future__ import annotations

import json
import os
import re
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering_sessions.git_state import GitCommandError, git, git_common_dir
from app.engineering_sessions.service import EngineeringSessionService
from app.models import Application, RegisteredWorkspace


_APPLICATION_COMPONENT = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MANAGER_UNAVAILABLE = "LOCAL_RUNTIME_MANAGER_UNAVAILABLE"
_MANAGER_INVALID_RESPONSE = "LOCAL_RUNTIME_MANAGER_INVALID_RESPONSE"
_INSTANCE_CONFLICT = "LOCAL_RUNTIME_INSTANCE_CONFLICT"
_WORKSPACE_REQUIRED = "LOCAL_APPLICATION_WORKSPACE_REQUIRED"
_WORKSPACE_FORBIDDEN = "LOCAL_APPLICATION_WORKSPACE_FORBIDDEN"
_WORKSPACE_INVALID = "LOCAL_APPLICATION_WORKSPACE_INVALID"
_APPLICATION_INVALID = "LOCAL_APPLICATION_ID_INVALID"


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=f"{code}: {message}")


def _text(value: object) -> str:
    return str(value or "").strip()


def _application_id(session: Any) -> str:
    app_id = _text(getattr(session, "app_id", None))
    application_id = app_id or _text(getattr(session, "external_application_id", None))
    if not application_id:
        raise _error(400, _APPLICATION_INVALID, "Code 会话未绑定应用")
    if not _APPLICATION_COMPONENT.fullmatch(application_id):
        raise _error(400, _APPLICATION_INVALID, "应用标识不安全")
    return application_id


def _allocate_loopback_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        host, port = listener.getsockname()
    return f"{host}:{port}"


def _validate_workspace_path(workspace: RegisteredWorkspace) -> Path:
    configured_path = Path(workspace.abs_path)
    if not configured_path.is_absolute():
        raise _error(409, _WORKSPACE_INVALID, "注册工作区路径必须为绝对路径")
    configured_absolute_path = Path(os.path.abspath(configured_path))
    try:
        repository_path = configured_absolute_path.resolve(strict=True)
    except OSError as exc:
        raise _error(409, _WORKSPACE_INVALID, "注册的本地 Git 工作区不存在") from exc
    if not repository_path.is_dir():
        raise _error(409, _WORKSPACE_INVALID, "注册的本地 Git 工作区不是目录")
    try:
        git_top_level = Path(
            git(
                repository_path,
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
            ).stdout.strip()
        ).resolve()
    except (GitCommandError, OSError) as exc:
        raise _error(409, _WORKSPACE_INVALID, "注册的本地工作区不是 Git 仓库") from exc
    if git_top_level != configured_absolute_path:
        raise _error(409, _WORKSPACE_INVALID, "注册路径必须是 Git 顶层目录")
    return repository_path


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
        raise _error(409, _WORKSPACE_REQUIRED, "应用未绑定本地 Git 工作区")
    if (
        application.tenant_id != int(ctx.tenant_id)
        or application.user_id != int(ctx.user.id)
    ):
        raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问应用的本地 Git 工作区")
    return application


async def _workspace_for_id(
    db: AsyncSession,
    ws_id: str,
    ctx: Any,
) -> RegisteredWorkspace:
    owned = (
        await db.execute(
            select(RegisteredWorkspace).where(
                RegisteredWorkspace.ws_id == ws_id,
                RegisteredWorkspace.tenant_id == int(ctx.tenant_id),
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
        raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问该本地 Git 工作区")
    raise _error(409, _WORKSPACE_REQUIRED, "应用必须先绑定本地 Git 工作区")


async def resolve_registered_workspace(
    db: AsyncSession,
    session: Any,
    ctx: Any,
) -> RegisteredWorkspace:
    """Resolve one owned registered workspace without falling back to local paths."""
    session_tenant_id = getattr(session, "tenant_id", None)
    session_user_id = getattr(session, "user_id", None)
    if (
        session_tenant_id is not None
        and int(session_tenant_id) != int(ctx.tenant_id)
    ) or (
        session_user_id is not None
        and int(session_user_id) != int(ctx.user.id)
    ):
        raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问该 Code 会话的本地 Git 工作区")

    workspace_id = _text(getattr(session, "workspace_id", None))
    application = await _application_for_session(db, session, ctx)
    if not workspace_id and application is not None:
        workspace_id = _text(application.source_workspace_id)

    if not workspace_id and application is None:
        external_application_id = _text(getattr(session, "external_application_id", None))
        if external_application_id:
            owned = (
                await db.execute(
                    select(RegisteredWorkspace).where(
                        RegisteredWorkspace.apaas_app_id == external_application_id,
                        RegisteredWorkspace.tenant_id == int(ctx.tenant_id),
                        RegisteredWorkspace.user_id == int(ctx.user.id),
                    )
                )
            ).scalar_one_or_none()
            if owned is not None:
                workspace_id = owned.ws_id
            else:
                foreign = (
                    await db.execute(
                        select(RegisteredWorkspace).where(
                            RegisteredWorkspace.apaas_app_id == external_application_id
                        )
                    )
                ).scalar_one_or_none()
                if foreign is not None:
                    raise _error(403, _WORKSPACE_FORBIDDEN, "无权访问该本地 Git 工作区")

    if not workspace_id:
        raise _error(409, _WORKSPACE_REQUIRED, "应用必须先绑定本地 Git 工作区")
    workspace = await _workspace_for_id(db, workspace_id, ctx)
    _validate_workspace_path(workspace)
    return workspace


def build_runtime_context(
    *,
    tenant_id: int,
    application_id: str,
    workspace_id: str,
    sandbox_instance_id: str,
    conversation_id: str,
    repo_path: Path,
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
        "repoUrl": str(repo_path),
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


def _write_runtime_context(runtime_dir: Path, context: dict[str, Any]) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target = runtime_dir / "runtime-context.json"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=runtime_dir,
            prefix=".runtime-context.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(context, temporary, ensure_ascii=False, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
        return target
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


class LocalRuntimeClient:
    """Translate a Code session into one deterministic local runtime instance."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        desktop_data_dir: str | Path | None = None,
        agent_runtime_path: str | Path | None = None,
        engineering_service_factory: Callable[[Path], EngineeringSessionService] = EngineeringSessionService,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.url = _text(url).rstrip("/")
        self.token = _text(token)
        self.desktop_data_dir = (
            Path(desktop_data_dir).expanduser() if desktop_data_dir is not None else None
        )
        self.agent_runtime_path = (
            Path(agent_runtime_path).expanduser() if agent_runtime_path is not None else None
        )
        self.engineering_service_factory = engineering_service_factory
        self.http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10)
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
            raise _error(
                503,
                _MANAGER_UNAVAILABLE,
                "本地 Runtime manager 未配置",
            )
        return cls(
            str(required["DOLPHIN_LOCAL_RUNTIME_MANAGER_URL"]),
            str(required["DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN"]),
            desktop_data_dir=str(required["DOLPHIN_DESKTOP_DATA_DIR"]),
            agent_runtime_path=str(required["DOLPHIN_AGENT_RUNTIME_PATH"]),
        )

    def _runtime_paths(self, application_id: str, sandbox_instance_id: str) -> tuple[Path, Path, Path]:
        if self.desktop_data_dir is None or self.agent_runtime_path is None:
            raise _error(
                503,
                _MANAGER_UNAVAILABLE,
                "本地 Runtime manager 未配置",
            )
        data_dir = self.desktop_data_dir.resolve()
        application_dir = data_dir / "local-runtimes" / application_id
        codex_home = application_dir / "codex-home"
        runtime_dir = application_dir / "instances" / sandbox_instance_id
        codex_home.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return codex_home, runtime_dir, self.agent_runtime_path.resolve()

    async def _manager_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if not self.url or not self.token:
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 未配置")
        try:
            async with self.http_client_factory() as client:
                return await client.request(
                    method,
                    f"{self.url}{path}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 不可用") from exc

    @staticmethod
    def _manager_error(response: httpx.Response) -> HTTPException:
        if response.status_code == 409:
            return _error(409, _INSTANCE_CONFLICT, "本地应用已有冲突的 Runtime 实例")
        return _error(503, _MANAGER_UNAVAILABLE, "本地 Runtime manager 不可用")

    @staticmethod
    def _manager_status(
        response: httpx.Response,
        application_id: str,
        sandbox_instance_id: str,
    ) -> dict[str, Any]:
        if response.status_code >= 400:
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
            raise _error(
                502,
                _MANAGER_INVALID_RESPONSE,
                "本地 Runtime manager 返回了无效响应",
            )
        if (
            _text(payload.get("application_id")) != application_id
            or _text(payload.get("sandbox_instance_id")) != sandbox_instance_id
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
        return {
            "applicationId": application_id,
            "workspaceId": workspace_id,
            "sandboxInstanceId": sandbox_instance_id,
            "conversationId": conversation_id,
            "state": _text(manager_status.get("state")),
            "runtimeBaseUrl": _text(manager_status.get("runtime_base_url")),
            "specReviewUrl": _text(manager_status.get("builder_url")),
        }

    async def open_application(
        self,
        db: AsyncSession,
        session: Any,
        ctx: Any,
    ) -> dict[str, Any]:
        application_id = _application_id(session)
        workspace = await resolve_registered_workspace(db, session, ctx)
        repository_path = _validate_workspace_path(workspace)
        application = await _application_for_session(db, session, ctx)
        title = (
            _text(getattr(application, "app_name", None))
            or _text(getattr(session, "external_app_name", None))
            or application_id
        )
        try:
            engineering_session = self.engineering_service_factory(
                repository_path
            ).ensure_application_session(application_id, title)
        except HTTPException:
            raise
        except Exception as exc:
            raise _error(
                503,
                _MANAGER_UNAVAILABLE,
                "无法准备本地应用 Runtime 工作区",
            ) from exc

        managed_worktree = _text(getattr(engineering_session, "worktree_path", None))
        if not managed_worktree:
            raise _error(409, _WORKSPACE_INVALID, "应用工程会话未提供受管工作区")
        managed_worktree_path = Path(managed_worktree).resolve()
        try:
            managed_git_common_dir = git_common_dir(managed_worktree_path)
        except (GitCommandError, OSError) as exc:
            raise _error(409, _WORKSPACE_INVALID, "应用工程会话工作区不是 Git 仓库") from exc

        engineering_session_id = _text(getattr(engineering_session, "id", None)).lower()
        if not engineering_session_id:
            raise _error(503, _MANAGER_UNAVAILABLE, "应用工程会话缺少稳定身份")
        sandbox_instance_id = f"local-{application_id}-{engineering_session_id}"
        codex_home, runtime_dir, agent_runtime_path = self._runtime_paths(
            application_id,
            sandbox_instance_id,
        )
        runtime_address = _allocate_loopback_address()
        conversation_id = _text(getattr(session, "public_id", None)) or _text(
            getattr(session, "id", None)
        )
        display_name = _text(getattr(ctx.user, "display_name", None)) or _text(
            getattr(ctx.user, "username", None)
        )
        context = build_runtime_context(
            tenant_id=int(ctx.tenant_id),
            application_id=application_id,
            workspace_id=workspace.ws_id,
            sandbox_instance_id=sandbox_instance_id,
            conversation_id=conversation_id,
            repo_path=repository_path,
            default_branch=_text(getattr(engineering_session, "base_branch", None)) or "main",
            user_id=int(ctx.user.id),
            display_name=display_name,
            codex_home=codex_home,
            runtime_dir=runtime_dir,
        )
        context_path = _write_runtime_context(runtime_dir, context)
        environment = {
            "APAAS_RUNTIME_CONTEXT_PATH": str(context_path),
            "APAAS_WORKSPACE_INIT_MODE": "local_fixture",
            "APAAS_CI_HANDOFF_MODE": "local_ci_provider",
            "APAAS_REPO_WORKSPACE_PATH": str(managed_worktree_path),
            "APAAS_WORKSPACE_PATH": str(managed_worktree_path),
            "APAAS_RUNTIME_WORKSPACE_PATH": str(runtime_dir),
            "APAAS_CODEX_HOME": str(codex_home),
            "APAAS_RUNTIME_ADDR": runtime_address,
            "APAAS_AUTH_MODE": "disabled",
        }
        status_path = (
            f"/v1/local-runtime/instances/{application_id}/{sandbox_instance_id}"
        )
        status_response = await self._manager_request("GET", status_path)
        if status_response.status_code == 404:
            start_payload = {
                "application_id": application_id,
                "sandbox_instance_id": sandbox_instance_id,
                "managed_worktree": str(managed_worktree_path),
                "git_common_dir": str(managed_git_common_dir),
                "codex_home": str(codex_home),
                "runtime_dir": str(runtime_dir),
                "runtime_context_path": str(context_path),
                "agent_runtime_path": str(agent_runtime_path),
                "runtime_address": runtime_address,
                "environment": environment,
            }
            manager_status = self._manager_status(
                await self._manager_request(
                    "POST",
                    "/v1/local-runtime/instances/start",
                    payload=start_payload,
                ),
                application_id,
                sandbox_instance_id,
            )
        else:
            manager_status = self._manager_status(
                status_response,
                application_id,
                sandbox_instance_id,
            )
            if _text(manager_status.get("state")) not in {"ready", "starting"}:
                raise _error(
                    409,
                    _INSTANCE_CONFLICT,
                    "本地应用已有不可复用的 Runtime 实例",
                )

        return self._opened(
            manager_status,
            application_id=application_id,
            workspace_id=workspace.ws_id,
            sandbox_instance_id=sandbox_instance_id,
            conversation_id=conversation_id,
        )
