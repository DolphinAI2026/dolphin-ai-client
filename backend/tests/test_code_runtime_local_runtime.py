from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.engineering_sessions.models import EngineeringSession
from app.models import Application, RegisteredWorkspace
from app.models.ai_chat import AIChatSession
from app.code_runtime.local_runtime import (
    LocalRuntimeClient,
    build_runtime_context,
    resolve_registered_workspace,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def ctx():
    return SimpleNamespace(
        tenant_id=7,
        user=SimpleNamespace(id=11, username="dev", display_name="Developer"),
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    return repo


@pytest.fixture
def engineering_session(git_repo: Path) -> EngineeringSession:
    return EngineeringSession(
        id="S-123",
        application_id="local-app-1",
        type="new-app",
        title="Local App",
        repo=git_repo.name,
        repo_path=str(git_repo),
        base_branch="main",
        branch="session/S-123-new-app-local-app",
        worktree_path=str(git_repo),
    )


class FakeEngineeringSessionService:
    def __init__(self, session: EngineeringSession) -> None:
        self.session = session
        self.calls: list[tuple[str, str]] = []

    def ensure_application_session(self, application_id: str, title: str) -> EngineeringSession:
        self.calls.append((application_id, title))
        return self.session


async def _create_workspace(
    db: AsyncSession,
    repo: Path,
    *,
    ws_id: str = "ws-local-1",
    user_id: int = 11,
    tenant_id: int = 7,
    apaas_app_id: str | None = "local-app-1",
) -> RegisteredWorkspace:
    workspace = RegisteredWorkspace(
        ws_id=ws_id,
        abs_path=str(repo),
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_type="external",
        apaas_app_id=apaas_app_id,
        display_name="Local repo",
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def _create_code_session(
    db: AsyncSession,
    *,
    app_id: int | None = None,
    external_application_id: str | None = "local-app-1",
    workspace_id: str | None = None,
    public_id: str = "conversation-1",
) -> AIChatSession:
    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=app_id,
        external_application_id=external_application_id,
        workspace_id=workspace_id,
        public_id=public_id,
        title="Local application",
        mode="code",
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


def _manager_status(
    application_id: str = "local-app-1",
    sandbox_instance_id: str = "local-local-app-1-s-123",
    state: str = "ready",
) -> dict[str, object]:
    return {
        "application_id": application_id,
        "sandbox_instance_id": sandbox_instance_id,
        "state": state,
        "pid": 42,
        "runtime_base_url": "http://127.0.0.1:19090",
        "builder_url": "http://127.0.0.1:19090/builder/",
        "started_at": "2026-07-20T00:00:00Z",
    }


def _client(
    tmp_path: Path,
    engineering_session: EngineeringSession,
    transport: httpx.AsyncBaseTransport,
) -> tuple[LocalRuntimeClient, FakeEngineeringSessionService]:
    service = FakeEngineeringSessionService(engineering_session)
    agent_runtime = tmp_path / "agent-runtime"
    agent_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    client = LocalRuntimeClient(
        "http://127.0.0.1:9988",
        "manager-secret",
        desktop_data_dir=tmp_path / "desktop-data",
        agent_runtime_path=agent_runtime,
        engineering_service_factory=lambda _repo_path: service,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
    )
    return client, service


@pytest.mark.asyncio
async def test_open_rejects_unbound_local_application(db, ctx, engineering_session, tmp_path):
    code_session = await _create_code_session(db, external_application_id="unbound-app")
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 409
    assert "LOCAL_APPLICATION_WORKSPACE_REQUIRED" in str(exc.value.detail)
    assert "本地 Git 工作区" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_open_rejects_workspace_owned_by_another_user(
    db, ctx, git_repo, engineering_session, tmp_path
):
    workspace = await _create_workspace(db, git_repo, user_id=12)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 403
    assert "LOCAL_APPLICATION_WORKSPACE_FORBIDDEN" in str(exc.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_kind", ["not_git", "subdirectory"])
async def test_open_rejects_unmanaged_workspace_paths(
    db, ctx, git_repo, engineering_session, tmp_path, repository_kind
):
    path = tmp_path / "plain-directory"
    if repository_kind == "subdirectory":
        path = git_repo / "nested"
        path.mkdir()
    else:
        path.mkdir()
    workspace = await _create_workspace(db, path)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 409
    assert "LOCAL_APPLICATION_WORKSPACE_INVALID" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_open_rejects_symlinked_repository_alias(
    db, ctx, git_repo, engineering_session, tmp_path
):
    repository_alias = tmp_path / "repository-alias"
    repository_alias.symlink_to(git_repo, target_is_directory=True)
    workspace = await _create_workspace(db, repository_alias)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 409
    assert "LOCAL_APPLICATION_WORKSPACE_INVALID" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_resolve_prefers_session_workspace_then_application_source_workspace(
    db, ctx, git_repo
):
    source_repo = git_repo.parent / "application-source"
    source_repo.mkdir()
    subprocess.run(["git", "init", str(source_repo)], check=True, capture_output=True, text=True)
    source_workspace = await _create_workspace(
        db,
        source_repo,
        ws_id="ws-source",
        apaas_app_id=None,
    )
    preferred_workspace = await _create_workspace(
        db,
        git_repo,
        ws_id="ws-preferred",
        apaas_app_id=None,
    )
    app = Application(
        id=101,
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="Internal app",
        app_code="internal-app",
        app_type="ai-code",
        source_workspace_id=source_workspace.ws_id,
    )
    db.add(app)
    await db.flush()
    code_session = await _create_code_session(
        db,
        app_id=app.id,
        external_application_id="external-ignored",
        workspace_id=preferred_workspace.ws_id,
    )

    resolved = await resolve_registered_workspace(db, code_session, ctx)

    assert resolved.ws_id == preferred_workspace.ws_id


@pytest.mark.asyncio
async def test_open_uses_internal_application_identity_and_source_workspace(
    db, ctx, git_repo, engineering_session, tmp_path, monkeypatch
):
    workspace = await _create_workspace(db, git_repo, ws_id="ws-source", apaas_app_id=None)
    app = Application(
        id=101,
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="Internal app",
        app_code="internal-app",
        app_type="ai-code",
        source_workspace_id=workspace.ws_id,
    )
    db.add(app)
    await db.flush()
    code_session = await _create_code_session(
        db,
        app_id=app.id,
        external_application_id="external-ignored",
    )
    engineering_session.application_id = "101"
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json=_manager_status("101", "local-101-s-123"))

    client, service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    opened = await client.open_application(db, code_session, ctx)

    assert opened["applicationId"] == "101"
    assert service.calls == [("101", "Internal app")]
    assert calls[0].url.path == "/v1/local-runtime/instances/101/local-101-s-123"


def test_from_environment_rejects_missing_required_manager_configuration(monkeypatch):
    for key in (
        "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL",
        "DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN",
        "DOLPHIN_DESKTOP_DATA_DIR",
        "DOLPHIN_AGENT_RUNTIME_PATH",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(HTTPException) as exc:
        LocalRuntimeClient.from_environment()

    assert exc.value.status_code == 503
    assert exc.value.detail == "LOCAL_RUNTIME_MANAGER_UNAVAILABLE: 本地 Runtime manager 未配置"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["ready", "starting"])
async def test_open_reuses_active_application_instance_across_conversations(
    db, ctx, git_repo, engineering_session, tmp_path, state
):
    workspace = await _create_workspace(db, git_repo)
    first = await _create_code_session(db, workspace_id=workspace.ws_id, public_id="conversation-1")
    second = await _create_code_session(db, workspace_id=workspace.ws_id, public_id="conversation-2")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_manager_status(state=state))

    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))

    first_opened = await client.open_application(db, first, ctx)
    second_opened = await client.open_application(db, second, ctx)

    assert first_opened["sandboxInstanceId"] == second_opened["sandboxInstanceId"]
    assert [request.method for request in calls] == ["GET", "GET"]
    assert len({request.url.path for request in calls}) == 1


@pytest.mark.asyncio
async def test_manager_non_json_response_is_stable_and_redacted(
    db, ctx, git_repo, engineering_session, tmp_path
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)

    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(
            lambda _request: httpx.Response(200, text="manager-secret malformed")
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 502
    assert exc.value.detail == (
        "LOCAL_RUNTIME_MANAGER_INVALID_RESPONSE: 本地 Runtime manager 返回了无效响应"
    )


@pytest.mark.asyncio
async def test_open_starts_missing_instance_with_runtime_context_path_and_environment_contract(
    db, ctx, git_repo, engineering_session, tmp_path, monkeypatch
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    calls: list[tuple[httpx.Request, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request, payload))
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json=_manager_status())

    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    opened = await client.open_application(db, code_session, ctx)

    assert opened["workspaceId"] == workspace.ws_id
    assert opened["specReviewUrl"] == "http://127.0.0.1:19090/builder/"
    status_request, _ = calls[0]
    start_request, start_payload = calls[1]
    assert status_request.url.path == "/v1/local-runtime/instances/local-app-1/local-local-app-1-s-123"
    assert start_request.method == "POST"
    assert start_request.url.path == "/v1/local-runtime/instances/start"
    assert start_request.headers["Authorization"] == "Bearer manager-secret"
    assert start_payload is not None
    assert start_payload["application_id"] == "local-app-1"
    assert start_payload["sandbox_instance_id"] == "local-local-app-1-s-123"
    assert start_payload["managed_worktree"] == str(git_repo)
    assert start_payload["git_common_dir"] == str(git_repo / ".git")
    assert start_payload["agent_runtime_path"] == str(tmp_path / "agent-runtime")
    assert start_payload["runtime_address"] == "127.0.0.1:19090"
    assert start_payload["environment"] == {
        "APAAS_RUNTIME_CONTEXT_PATH": start_payload["runtime_context_path"],
        "APAAS_WORKSPACE_INIT_MODE": "local_fixture",
        "APAAS_CI_HANDOFF_MODE": "local_ci_provider",
        "APAAS_REPO_WORKSPACE_PATH": str(git_repo),
        "APAAS_WORKSPACE_PATH": str(git_repo),
        "APAAS_RUNTIME_WORKSPACE_PATH": start_payload["runtime_dir"],
        "APAAS_CODEX_HOME": start_payload["codex_home"],
        "APAAS_RUNTIME_ADDR": "127.0.0.1:19090",
        "APAAS_AUTH_MODE": "disabled",
    }
    context_path = Path(str(start_payload["runtime_context_path"]))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context == build_runtime_context(
        tenant_id=7,
        application_id="local-app-1",
        workspace_id=workspace.ws_id,
        sandbox_instance_id="local-local-app-1-s-123",
        conversation_id="conversation-1",
        repo_path=git_repo,
        default_branch="main",
        user_id=11,
        display_name="Developer",
        codex_home=Path(str(start_payload["codex_home"])),
        runtime_dir=Path(str(start_payload["runtime_dir"])),
    )
    assert context_path.parent == Path(str(start_payload["runtime_dir"]))
    assert Path(str(start_payload["codex_home"])).parent == (
        tmp_path / "desktop-data" / "local-runtimes" / "local-app-1"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 409, 500])
async def test_manager_errors_are_stable_and_redacted(
    db, ctx, git_repo, engineering_session, tmp_path, status_code
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="manager-secret should never escape")

    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    expected_status = 409 if status_code == 409 else 503
    assert exc.value.status_code == expected_status
    assert "manager-secret" not in str(exc.value.detail)
    assert str(exc.value.detail).startswith(
        "LOCAL_RUNTIME_INSTANCE_CONFLICT"
        if status_code == 409
        else "LOCAL_RUNTIME_MANAGER_UNAVAILABLE"
    )
