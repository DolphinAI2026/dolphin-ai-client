from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
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
from app.harness.llm_resolver import ResolvedLLMConfig
from app.models import Application, RegisteredWorkspace
from app.models.ai_chat import AIChatSession
from app.models.workspace_git import WorkspaceGitRemote
from app.code_runtime.local_runtime import (
    LocalRuntimeClient,
    _runtime_scope_id,
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


@pytest.fixture(autouse=True)
def local_runtime_llm_config(monkeypatch):
    async def fake_resolve_llm_config(
        _db,
        tenant_id,
        *,
        purpose,
        selected_config_id=None,
    ):
        assert tenant_id == 7
        assert purpose == "coding"
        return ResolvedLLMConfig(
            model="gpt-local-test",
            base_url="https://models.example.invalid/v1",
            api_key="unit-test-model-token",
            config_id=selected_config_id or 91,
            config_name="Local test model",
            provider="openai",
        )

    monkeypatch.setattr(
        "app.harness.llm_resolver.resolve_llm_config",
        fake_resolve_llm_config,
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
    repo: Path | str,
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
    selected_llm_config_id: int | None = None,
) -> AIChatSession:
    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=app_id,
        external_application_id=external_application_id,
        workspace_id=workspace_id,
        public_id=public_id,
        selected_llm_config_id=selected_llm_config_id,
        title="Local application",
        mode="code",
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


def _manager_status(
    application_id: str = "local-app-1",
    sandbox_instance_id: str = "local-instance-1",
    state: str = "ready",
    runtime_scope_id: str | None = None,
) -> dict[str, object]:
    scope = runtime_scope_id or _runtime_scope_id(
        SimpleNamespace(tenant_id=7, user=SimpleNamespace(id=11)),
        application_id,
    )
    return {
        "runtime_scope_id": scope,
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
    desktop_data = tmp_path / "desktop-data"
    if not os.path.lexists(desktop_data):
        desktop_data.mkdir(mode=0o700)
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


def _manager_status_for_start(request: httpx.Request, *, state: str = "ready") -> dict[str, object]:
    payload = json.loads(request.content)
    return _manager_status(
        str(payload["application_id"]),
        str(payload["sandbox_instance_id"]),
        state,
        str(payload["runtime_scope_id"]),
    )


async def _runtime_case(
    db: AsyncSession,
    git_repo: Path,
    engineering_session: EngineeringSession,
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    **session_values,
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        **session_values,
    )
    client, service = _client(tmp_path, engineering_session, transport)
    return client, service, workspace, code_session


class ConcurrentStartTransport(httpx.AsyncBaseTransport):
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.initial_get_count = 0
        self.get_count = 0
        self.post_payloads: list[dict[str, object]] = []
        self.context_at_start: bytes | None = None
        self.ready = False
        self._initial_gets_complete = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.get_count += 1
            if self.ready:
                return httpx.Response(
                    200,
                    json=_manager_status_for_start(
                        httpx.Request("POST", "http://manager/start", content=json.dumps(self.post_payloads[0]))
                    ),
                )
            if self.initial_get_count < 2:
                self.initial_get_count += 1
                if self.initial_get_count == 2:
                    self._initial_gets_complete.set()
                await self._initial_gets_complete.wait()
                return httpx.Response(404)
            return httpx.Response(404)

        payload = json.loads(request.content)
        self.post_payloads.append(payload)
        self.runtime_dir = Path(str(payload["runtime_dir"]))
        self.context_at_start = (self.runtime_dir / "runtime-context.json").read_bytes()
        self.ready = True
        return httpx.Response(200, json=_manager_status_for_start(request))


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
@pytest.mark.parametrize(
    "repository_kind",
    [
        "not_git",
        "subdirectory",
        "symlink",
        "dotdot",
        "duplicate_separator",
        "trailing_separator",
    ],
)
async def test_open_rejects_unmanaged_workspace_paths(
    db, ctx, git_repo, engineering_session, tmp_path, repository_kind
):
    path: Path | str = tmp_path / "plain-directory"
    if repository_kind == "subdirectory":
        path = git_repo / "nested"
        path.mkdir()
    elif repository_kind == "not_git":
        path.mkdir()
    elif repository_kind == "symlink":
        path = tmp_path / "repository-alias"
        path.symlink_to(git_repo, target_is_directory=True)
    elif repository_kind == "dotdot":
        path = f"{git_repo}/../{git_repo.name}"
    elif repository_kind == "duplicate_separator":
        path = f"{git_repo.parent}//{git_repo.name}"
    else:
        path = f"{git_repo}/"
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
@pytest.mark.parametrize(
    ("owned", "expected_status", "expected_code"),
    [
        (True, 409, "LOCAL_APPLICATION_WORKSPACE_REQUIRED"),
        (False, 403, "LOCAL_APPLICATION_WORKSPACE_FORBIDDEN"),
    ],
)
async def test_external_application_rejects_ambiguous_or_foreign_bindings(
    db, ctx, tmp_path, engineering_session, owned, expected_status, expected_code
):
    for index in range(2):
        repo = tmp_path / f"binding-repo-{index}"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
        await _create_workspace(
            db,
            repo,
            ws_id=f"ws-binding-{index}",
            user_id=11 if owned else 20 + index,
            apaas_app_id="bound-app",
        )
    code_session = await _create_code_session(
        db,
        external_application_id="bound-app",
    )
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == expected_status
    assert expected_code in str(exc.value.detail)


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
        return httpx.Response(200, json=_manager_status_for_start(request))

    client, service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    opened = await client.open_application(db, code_session, ctx)

    assert opened["applicationId"] == "101"
    assert service.calls == [("101", "Internal app")]
    assert calls[0].url.path == (
        f"/v1/local-runtime/instances/{_runtime_scope_id(ctx, '101')}"
    )


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


@pytest.mark.parametrize(
    "manager_url",
    [
        "https://127.0.0.1:9988",
        "http://localhost:9988",
        "http://192.0.2.10:9988",
        "http://user:password@127.0.0.1:9988",
        "http://127.0.0.1:9988/path",
        "http://127.0.0.1:9988?token=query-secret",
        "http://127.0.0.1:9988#fragment",
        "http://127.0.0.1",
    ],
)
def test_constructor_rejects_non_loopback_manager_urls(manager_url, tmp_path):
    with pytest.raises(HTTPException) as exc:
        LocalRuntimeClient(
            manager_url,
            "manager-secret",
            desktop_data_dir=tmp_path / "desktop-data",
            agent_runtime_path=tmp_path / "agent-runtime",
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == (
        "LOCAL_RUNTIME_MANAGER_UNAVAILABLE: 本地 Runtime manager 地址无效"
    )
    assert "manager-secret" not in str(exc.value.detail)
    assert "password" not in str(exc.value.detail)
    assert "query-secret" not in str(exc.value.detail)


def test_from_environment_rejects_external_manager_url(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL",
        "http://manager.example.com:9988",
    )
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN", "manager-secret")
    monkeypatch.setenv("DOLPHIN_DESKTOP_DATA_DIR", str(tmp_path / "desktop-data"))
    monkeypatch.setenv("DOLPHIN_AGENT_RUNTIME_PATH", str(tmp_path / "agent-runtime"))

    with pytest.raises(HTTPException) as exc:
        LocalRuntimeClient.from_environment()

    assert exc.value.status_code == 503
    assert "LOCAL_RUNTIME_MANAGER_UNAVAILABLE" in str(exc.value.detail)
    assert "manager-secret" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_open_generates_instance_independently_from_engineering_session_id(
    db, ctx, git_repo, tmp_path, monkeypatch
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    engineering_session = SimpleNamespace(
        id="../not-an-instance-id",
        base_branch="main",
        worktree_path=str(git_repo),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json=_manager_status_for_start(request))

    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    opened = await client.open_application(db, code_session, ctx)
    assert opened["sandboxInstanceId"].startswith("local-")
    assert "../" not in opened["sandboxInstanceId"]


@pytest.mark.asyncio
async def test_open_reuses_active_application_instance_across_conversations(
    db, ctx, git_repo, engineering_session, tmp_path, monkeypatch
):
    workspace = await _create_workspace(db, git_repo)
    first = await _create_code_session(db, workspace_id=workspace.ws_id, public_id="conversation-1")
    second = await _create_code_session(db, workspace_id=workspace.ws_id, public_id="conversation-2")
    runtime_dir = (
        tmp_path
        / "desktop-data"
        / "local-runtimes"
        / _runtime_scope_id(ctx, "local-app-1")
        / "instances"
        / "local-instance-1"
    )
    runtime_dir.mkdir(parents=True)
    context_path = runtime_dir / "runtime-context.json"
    context_path.write_bytes(b'{"conversationId":"original"}\n')
    (runtime_dir / "model-provider.json").write_text(
        json.dumps(
            {
                "defaultProviderId": "local.test",
                "providers": [
                    {
                        "providerId": "local.test",
                        "providerType": "openai-compatible",
                        "apiBaseUrl": "https://models.example.invalid/v1",
                        "token": "unit-test-model-token",
                        "defaultModel": "gpt-local-test",
                        "models": [{"id": "gpt-local-test", "displayName": "gpt-local-test"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    token_path = runtime_dir / "sandbox-token"
    token_path.write_text("reused-entry-token", encoding="ascii")
    token_path.chmod(0o600)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_manager_status())
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: (_ for _ in ()).throw(AssertionError("active reuse allocated a port")),
    )
    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))

    first_opened = await client.open_application(db, first, ctx)
    second_opened = await client.open_application(db, second, ctx)

    assert first_opened["sandboxInstanceId"] == second_opened["sandboxInstanceId"]
    assert [request.method for request in calls] == ["GET", "GET"]
    assert len({request.url.path for request in calls}) == 1
    assert context_path.read_bytes() == b'{"conversationId":"original"}\n'
    assert (runtime_dir / "model-provider.json").exists()
    assert not (runtime_dir / "ci-provider.json").exists()


@pytest.mark.asyncio
async def test_concurrent_conversations_share_one_start_context(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
    monkeypatch,
):
    workspace = await _create_workspace(db, git_repo)
    first = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        public_id="conversation-1",
    )
    second = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        public_id="conversation-2",
    )
    transport = ConcurrentStartTransport(tmp_path)
    client, _service = _client(tmp_path, engineering_session, transport)
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    opened = await asyncio.gather(
        client.open_application(db, first, ctx),
        client.open_application(db, second, ctx),
    )

    assert len(transport.post_payloads) == 1
    assert transport.get_count == 4
    assert opened[0]["sandboxInstanceId"] == opened[1]["sandboxInstanceId"]
    assert transport.context_at_start is not None
    assert transport.runtime_dir is not None
    assert (transport.runtime_dir / "runtime-context.json").read_bytes() == transport.context_at_start


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
    db.add(
        WorkspaceGitRemote(
            ws_id=workspace.ws_id,
            tenant_id=7,
            user_id=11,
            provider="gitlab",
            remote_url="https://git.example.invalid/team/local-app.git",
            default_branch="main",
            git_connection_id=501,
        )
    )
    code_session = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        selected_llm_config_id=77,
    )
    await db.flush()
    calls: list[tuple[httpx.Request, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request, payload))
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json=_manager_status_for_start(request))

    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    opened = await client.open_application(db, code_session, ctx)

    assert opened["workspaceId"] == workspace.ws_id
    assert opened["specReviewUrl"] == "http://127.0.0.1:19090/builder/"
    status_request, _ = calls[0]
    recheck_request, _ = calls[1]
    start_request, start_payload = calls[2]
    assert status_request.url.path == (
        f"/v1/local-runtime/instances/{_runtime_scope_id(ctx, 'local-app-1')}"
    )
    assert recheck_request.url.path == status_request.url.path
    assert start_request.method == "POST"
    assert start_request.url.path == "/v1/local-runtime/instances/start"
    assert start_request.headers["Authorization"] == "Bearer manager-secret"
    assert start_payload is not None
    assert set(start_payload) == {
        "runtime_scope_id",
        "application_id",
        "sandbox_instance_id",
        "workspace_id",
        "worktree_path",
        "git_common_dir",
        "codex_home",
        "runtime_dir",
        "runtime_context_path",
        "agent_runtime_path",
        "runtime_addr",
        "environment",
    }
    assert start_payload["runtime_scope_id"] == _runtime_scope_id(ctx, "local-app-1")
    assert start_payload["application_id"] == "local-app-1"
    assert str(start_payload["sandbox_instance_id"]).startswith("local-")
    assert start_payload["workspace_id"] == workspace.ws_id
    assert start_payload["worktree_path"] == str(git_repo)
    assert start_payload["git_common_dir"] == str(git_repo / ".git")
    assert start_payload["agent_runtime_path"] == str(tmp_path / "agent-runtime")
    assert start_payload["runtime_addr"] == "127.0.0.1:19090"
    assert start_payload["environment"] == {
        "APAAS_RUNTIME_CONTEXT_PATH": start_payload["runtime_context_path"],
        "APAAS_MODEL_PROVIDER_PATH": str(
            Path(str(start_payload["runtime_dir"])) / "model-provider.json"
        ),
        "APAAS_WORKSPACE_INIT_MODE": "desktop_existing_workspace",
        "APAAS_CI_HANDOFF_MODE": "disabled",
        "APAAS_CODEX_SESSION_MODE": "codex",
        "APAAS_REPO_WORKSPACE_PATH": str(git_repo),
        "APAAS_WORKSPACE_PATH": str(git_repo),
        "APAAS_RUNTIME_WORKSPACE_PATH": start_payload["runtime_dir"],
        "APAAS_CODEX_HOME": start_payload["codex_home"],
        "APAAS_RUNTIME_ADDR": "127.0.0.1:19090",
        "APAAS_AUTH_MODE": "token",
        "APAAS_SANDBOX_TOKEN_PATH": str(
            Path(str(start_payload["runtime_dir"])) / "sandbox-token"
        ),
    }
    context_path = Path(str(start_payload["runtime_context_path"]))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context == build_runtime_context(
        tenant_id=7,
        application_id="local-app-1",
        workspace_id=workspace.ws_id,
        sandbox_instance_id=str(start_payload["sandbox_instance_id"]),
        conversation_id="conversation-1",
        repo_url="https://git.example.invalid/team/local-app.git",
        default_branch="main",
        user_id=11,
        display_name="Developer",
        codex_home=Path(str(start_payload["codex_home"])),
        runtime_dir=Path(str(start_payload["runtime_dir"])),
    )
    assert context_path.parent == Path(str(start_payload["runtime_dir"]))
    assert Path(str(start_payload["codex_home"])).parent == (
        tmp_path
        / "desktop-data"
        / "local-runtimes"
        / _runtime_scope_id(ctx, "local-app-1")
    )
    assert str(git_repo) not in context["repoUrl"]

    model_provider_path = Path(
        str(start_payload["environment"]["APAAS_MODEL_PROVIDER_PATH"])
    )
    assert json.loads(model_provider_path.read_text(encoding="utf-8")) == {
        "defaultProviderId": json.loads(model_provider_path.read_text(encoding="utf-8"))[
            "defaultProviderId"
        ],
        "providers": [
            {
                "providerId": json.loads(model_provider_path.read_text(encoding="utf-8"))[
                    "defaultProviderId"
                ],
                "providerType": "openai-compatible",
                "runtimeProviderKind": "openai",
                "apiBaseUrl": "https://models.example.invalid/v1",
                "token": "unit-test-model-token",
                "defaultModel": "gpt-local-test",
                "models": [
                    {
                        "id": "gpt-local-test",
                        "displayName": "gpt-local-test",
                    }
                ],
            }
        ],
    }
    token_path = Path(str(start_payload["environment"]["APAAS_SANDBOX_TOKEN_PATH"]))
    entry_token = token_path.read_text(encoding="utf-8")
    assert entry_token
    assert "\x00" not in entry_token
    assert "sandbox-token" not in json.dumps(opened)
    if entry_token in json.dumps(start_payload) or entry_token in json.dumps(opened):
        pytest.fail("sandbox entry token leaked into a public payload")
    assert not (token_path.parent / "ci-provider.json").exists()
    for config_path in (context_path, model_provider_path, token_path):
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    for directory in (
        tmp_path / "desktop-data",
        tmp_path / "desktop-data" / "local-runtimes",
        tmp_path
        / "desktop-data"
        / "local-runtimes"
        / _runtime_scope_id(ctx, "local-app-1"),
        Path(str(start_payload["codex_home"])),
        Path(str(start_payload["runtime_dir"])).parent,
        Path(str(start_payload["runtime_dir"])),
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert "unit-test-model-token" not in json.dumps(start_payload)


@pytest.mark.asyncio
async def test_repeated_open_reuses_the_same_private_entry_token(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
    monkeypatch,
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    start_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and start_payloads:
            return httpx.Response(
                200,
                json=_manager_status(
                    sandbox_instance_id=str(start_payloads[0]["sandbox_instance_id"])
                ),
            )
        if request.method == "GET":
            return httpx.Response(404)
        payload = json.loads(request.content)
        start_payloads.append(payload)
        return httpx.Response(200, json=_manager_status_for_start(request))

    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    first, first_token = await client.open_application_with_entry_token(db, code_session, ctx)
    second, second_token = await client.open_application_with_entry_token(db, code_session, ctx)

    assert first["sandboxInstanceId"] == second["sandboxInstanceId"]
    assert hashlib.sha256(first_token.encode("ascii")).digest() == hashlib.sha256(
        second_token.encode("ascii")
    ).digest()
    if first_token in first.values() or second_token in second.values():
        pytest.fail("sandbox entry token leaked into an opened application response")
    assert len(start_payloads) == 1


@pytest.mark.asyncio
async def test_reused_runtime_without_entry_token_returns_503(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    runtime_dir = (
        tmp_path
        / "desktop-data"
        / "local-runtimes"
        / _runtime_scope_id(ctx, "local-app-1")
        / "instances"
        / "local-instance-1"
    )
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "model-provider.json").write_text(
        json.dumps(
            {
                "defaultProviderId": "local.test",
                "providers": [
                    {
                        "providerId": "local.test",
                        "providerType": "openai-compatible",
                        "runtimeProviderKind": "openai",
                        "apiBaseUrl": "https://models.example.invalid/v1",
                        "token": "unit-test-model-token",
                        "defaultModel": "gpt-local-test",
                        "models": [{"id": "gpt-local-test", "displayName": "gpt-local-test"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(lambda _request: httpx.Response(200, json=_manager_status())),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 503
    assert exc.value.detail == "LOCAL_RUNTIME_START_FAILED: 无法读取本地 Runtime entry token"


@pytest.mark.asyncio
async def test_runtime_context_uses_stable_https_placeholder_without_remote_binding(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
    monkeypatch,
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(db, workspace_id=workspace.ws_id)
    start_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        start_payloads.append(json.loads(request.content))
        return httpx.Response(200, json=_manager_status_for_start(request))

    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    await client.open_application(db, code_session, ctx)

    context_path = Path(str(start_payloads[0]["runtime_context_path"]))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["repoUrl"] == "https://local.invalid/local-app-1.git"
    assert str(git_repo) not in context["repoUrl"]


@pytest.mark.asyncio
async def test_open_requires_model_provider_before_first_start(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
    monkeypatch,
):
    workspace = await _create_workspace(db, git_repo)
    code_session = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        selected_llm_config_id=404,
    )
    requests: list[httpx.Request] = []

    async def no_model(*_args, **_kwargs):
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404)

    monkeypatch.setattr(
        "app.harness.llm_resolver.resolve_llm_config",
        no_model,
    )
    client, _service = _client(
        tmp_path,
        engineering_session,
        httpx.MockTransport(handler),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "LOCAL_RUNTIME_MODEL_PROVIDER_REQUIRED: 请先配置可用的 Coding 模型"
    )
    assert [request.method for request in requests] == ["GET", "GET"]
    assert not list(
        (tmp_path / "desktop-data" / "local-runtimes").rglob("model-provider.json")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_changes", "expected_detail"),
    [
        (
            {"state": state},
            "LOCAL_RUNTIME_START_FAILED: 本地 Runtime manager 未返回 ready 实例",
        )
        for state in ("failed", "blocked", "starting", "")
    ]
    + [
        (
            changes,
            "LOCAL_RUNTIME_MANAGER_INVALID_RESPONSE: "
            "本地 Runtime manager 返回了无效 Runtime URL",
        )
        for changes in (
            {"runtime_base_url": ""},
            {"builder_url": ""},
            {"runtime_base_url": "http://127.0.0.1:0"},
            {"builder_url": "http://127.0.0.1:0/builder/"},
            {"runtime_base_url": "https://127.0.0.1:19090"},
            {"runtime_base_url": "http://runtime.example.com:19090"},
            {"builder_url": "http://builder.example.com:19090/builder/"},
            {"builder_url": "http://127.0.0.1:19090/not-builder/"},
            {"runtime_base_url": "http://127.0.0.1:19090/not-root"},
            {"builder_url": "http://127.0.0.1:19090/builder/../admin"},
            {"builder_url": "http://127.0.0.1:19090/builder/%2e%2e/admin"},
            {"builder_url": "http://127.0.0.1:19090/builder\\admin"},
        )
    ],
)
async def test_start_rejects_invalid_manager_result(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
    monkeypatch,
    response_changes,
    expected_detail,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        response_payload = _manager_status_for_start(request)
        response_payload.update(response_changes)
        return httpx.Response(200, json=response_payload)

    client, _service, _workspace, code_session = await _runtime_case(
        db,
        git_repo,
        engineering_session,
        tmp_path,
        httpx.MockTransport(handler),
    )
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 502
    assert exc.value.detail == expected_detail


@pytest.mark.asyncio
async def test_open_rejects_manager_redirect_response(
    db, ctx, git_repo, engineering_session, tmp_path
):
    client, _service, _workspace, code_session = await _runtime_case(
        db,
        git_repo,
        engineering_session,
        tmp_path,
        httpx.MockTransport(
            lambda _request: httpx.Response(
                302,
                json=_manager_status(),
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 503
    assert exc.value.detail == (
        "LOCAL_RUNTIME_MANAGER_UNAVAILABLE: 本地 Runtime manager 不可用"
    )


@pytest.mark.asyncio
async def test_existing_starting_instance_is_polled_until_ready(
    db, ctx, git_repo, engineering_session, tmp_path, monkeypatch
):
    responses = iter(
        [
            httpx.Response(200, json=_manager_status(state="starting")),
            httpx.Response(200, json=_manager_status(state="ready")),
        ]
    )
    client, _service, _workspace, _code_session = await _runtime_case(
        db,
        git_repo,
        engineering_session,
        tmp_path,
        httpx.MockTransport(lambda _request: next(responses)),
    )
    monkeypatch.setattr("app.code_runtime.local_runtime._STARTING_POLL_SECONDS", 0)

    opened = await client._existing_status(
        f"/v1/local-runtime/instances/{_runtime_scope_id(ctx, 'local-app-1')}",
        _runtime_scope_id(ctx, "local-app-1"),
        "local-app-1",
    )

    assert opened is not None
    assert opened["state"] == "ready"


@pytest.mark.asyncio
async def test_runtime_scope_rejects_existing_symlink_before_model_token_write(
    db, ctx, git_repo, engineering_session, tmp_path
):
    attacker_directory = tmp_path / "attacker-controlled"
    attacker_directory.mkdir()
    (tmp_path / "desktop-data").mkdir()
    (tmp_path / "desktop-data" / "local-runtimes").symlink_to(
        attacker_directory,
        target_is_directory=True,
    )
    client, _service, _workspace, code_session = await _runtime_case(
        db,
        git_repo,
        engineering_session,
        tmp_path,
        httpx.MockTransport(lambda _request: httpx.Response(404)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 503
    assert exc.value.detail == (
        "LOCAL_RUNTIME_PREPARATION_FAILED: 无法准备本地 Runtime 配置"
    )
    assert not list(attacker_directory.rglob("model-provider.json"))
    assert not list(attacker_directory.rglob("unit-test-model-token"))


@pytest.mark.asyncio
async def test_same_application_is_scoped_per_user(
    db, ctx, git_repo, engineering_session, tmp_path, monkeypatch
):
    first_workspace = await _create_workspace(db, git_repo, ws_id="ws-user-11")
    other_repo = tmp_path / "source-repo-user-12"
    other_repo.mkdir()
    subprocess.run(["git", "init", str(other_repo)], check=True, capture_output=True, text=True)
    second_workspace = await _create_workspace(
        db,
        other_repo,
        ws_id="ws-user-12",
        user_id=12,
    )
    first = await _create_code_session(db, workspace_id=first_workspace.ws_id)
    second = await _create_code_session(
        db,
        workspace_id=second_workspace.ws_id,
        public_id="conversation-user-12",
    )
    second.user_id = 12
    await db.flush()
    other_ctx = SimpleNamespace(
        tenant_id=7,
        user=SimpleNamespace(id=12, username="other", display_name="Other"),
    )
    starts: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        payload = json.loads(request.content)
        starts.append(payload)
        return httpx.Response(200, json=_manager_status_for_start(request))

    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )

    await client.open_application(db, first, ctx)
    await client.open_application(db, second, other_ctx)

    assert len(starts) == 2
    assert starts[0]["runtime_scope_id"] != starts[1]["runtime_scope_id"]
    assert starts[0]["runtime_dir"] != starts[1]["runtime_dir"]


@pytest.mark.asyncio
async def test_reused_runtime_rejects_conversation_with_incompatible_provider(
    db, ctx, git_repo, engineering_session, tmp_path, monkeypatch
):
    workspace = await _create_workspace(db, git_repo)
    first = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        selected_llm_config_id=1,
    )
    second = await _create_code_session(
        db,
        workspace_id=workspace.ws_id,
        public_id="conversation-2",
        selected_llm_config_id=2,
    )
    state: dict[str, dict[str, object] | None] = {"started": None}

    async def resolve_model(_db, _tenant_id, *, purpose, selected_config_id=None):
        assert purpose == "coding"
        token = "provider-a" if selected_config_id == 1 else "provider-b"
        return ResolvedLLMConfig(
            model=f"model-{selected_config_id}",
            base_url="https://models.example.invalid/v1",
            api_key=token,
            config_id=selected_config_id,
            config_name="test",
            provider="openai",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if state["started"] is None:
                return httpx.Response(404)
            return httpx.Response(200, json=state["started"])
        state["started"] = _manager_status_for_start(request)
        return httpx.Response(200, json=state["started"])

    monkeypatch.setattr("app.harness.llm_resolver.resolve_llm_config", resolve_model)
    monkeypatch.setattr(
        "app.code_runtime.local_runtime._allocate_loopback_address",
        lambda: "127.0.0.1:19090",
    )
    client, _service = _client(tmp_path, engineering_session, httpx.MockTransport(handler))

    await client.open_application(db, first, ctx)
    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, second, ctx)

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "LOCAL_RUNTIME_MODEL_PROVIDER_CONFLICT: 当前会话选择的 Coding 模型与应用 Runtime 不兼容"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_kind", "secret", "message"),
    [
        ("directory", "mkdir-secret", "无法准备本地 Runtime 配置"),
        ("resolve", "desktop-data", "无法准备本地 Runtime 配置"),
        ("socket", "socket-secret", "无法准备本地 Runtime 配置"),
        ("write", "write-secret", "无法准备本地 Runtime 配置"),
        ("model", "unit-test-model-token", "无法解析本地 Runtime 模型配置"),
    ],
)
async def test_preparation_errors_are_stable_and_redacted(
    db,
    ctx,
    git_repo,
    engineering_session,
    tmp_path,
    monkeypatch,
    failure_kind,
    secret,
    message,
):
    if failure_kind == "model":
        async def fail(*_args, **_kwargs):
            raise RuntimeError(secret)

        monkeypatch.setattr("app.harness.llm_resolver.resolve_llm_config", fail)
    elif failure_kind == "write":
        monkeypatch.setattr(
            "app.code_runtime.local_runtime.os.replace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(secret)),
        )
    elif failure_kind == "directory":
        monkeypatch.setattr(
            "app.code_runtime.local_runtime._open_directory_at",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(secret)),
        )
    elif failure_kind == "resolve":
        (tmp_path / "desktop-data").symlink_to(
            "desktop-data",
            target_is_directory=True,
        )
    else:
        monkeypatch.setattr(
            "app.code_runtime.local_runtime._allocate_loopback_address",
            lambda: (_ for _ in ()).throw(OSError(secret)),
        )
    client, _service, _workspace, code_session = await _runtime_case(
        db,
        git_repo,
        engineering_session,
        tmp_path,
        httpx.MockTransport(lambda _request: httpx.Response(404)),
    )

    with pytest.raises(HTTPException) as exc:
        await client.open_application(db, code_session, ctx)

    assert exc.value.status_code == 503
    assert exc.value.detail == f"LOCAL_RUNTIME_PREPARATION_FAILED: {message}"
    assert secret not in str(exc.value.detail)


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
