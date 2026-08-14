from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, text, update
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Application
from app.models.ai_chat import AIChatSession


@pytest.fixture(autouse=True)
def _stub_service_runtime_bootstrap(monkeypatch):
    from app.code_runtime import service
    from app.code_runtime.sandbox_auth import RuntimeBootstrap, split_entry_token

    async def fake_bootstrap(
        builder_url: str,
        *,
        runtime_base_url: str | None = None,
    ):
        clean_builder_url, _entry_token = split_entry_token(builder_url)
        return RuntimeBootstrap(
            clean_builder_url=clean_builder_url,
            runtime_base_url=(
                runtime_base_url
                or service.derive_runtime_base_url(clean_builder_url)
            ),
            runtime_cookie="test-runtime-cookie",
            runtime_cookie_hash="c" * 64,
            expires_at=None,
        )

    monkeypatch.setattr(service, "bootstrap_runtime_session", fake_bootstrap)


def test_code_runtime_binding_model_is_registered():
    from app.models.ai_chat import AIChatSession, CodeRuntimeAgentSession, CodeRuntimeBinding

    cols = {c.name for c in sa_inspect(CodeRuntimeBinding).columns}
    assert {
        "session_id",
        "app_id",
        "external_application_id",
        "runtime_base_url",
        "builder_url",
        "workspace_id",
        "sandbox_instance_id",
        "runtime_session_id",
        "runtime_service_session_enc",
        "auth_generation",
        "execution_target",
        "desktop_agent_runtime_token_enc",
        "control_plane_tenant_id",
    }.issubset(cols)
    assert "control_plane_tenant_id" in {
        c.name for c in sa_inspect(AIChatSession).columns
    }
    assert "control_plane_tenant_id" in {
        c.name for c in sa_inspect(CodeRuntimeAgentSession).columns
    }
    assert sa_inspect(CodeRuntimeBinding).columns.app_id.nullable is True
    assert sa_inspect(CodeRuntimeBinding).columns.execution_target.default.arg == "control_plane"
    assert sa_inspect(CodeRuntimeBinding).columns.execution_target.server_default.arg == "control_plane"


def test_runtime_binding_rejects_plaintext_token_on_construction_and_assignment():
    from app.models.ai_chat import CodeRuntimeBinding

    with pytest.raises(ValueError, match="desktop runtime token must be encrypted"):
        CodeRuntimeBinding(desktop_agent_runtime_token_enc="plaintext-token")

    binding = CodeRuntimeBinding()
    with pytest.raises(ValueError, match="desktop runtime token must be encrypted"):
        binding.desktop_agent_runtime_token_enc = "plaintext-token"


def test_execution_target_classifies_desktop_runtime_and_legacy_values():
    from app.code_runtime.execution_target import (
        ExecutionTarget,
        is_desktop_agent_runtime_target,
        resolve_execution_target,
    )

    assert resolve_execution_target(None) is ExecutionTarget.CONTROL_PLANE
    assert resolve_execution_target("") is ExecutionTarget.CONTROL_PLANE
    assert resolve_execution_target("desktop_agent_runtime") is ExecutionTarget.DESKTOP_AGENT_RUNTIME
    assert is_desktop_agent_runtime_target(ExecutionTarget.DESKTOP_AGENT_RUNTIME)
    assert not is_desktop_agent_runtime_target(ExecutionTarget.CONTROL_PLANE)


@pytest.mark.asyncio
async def test_execution_target_rejects_invalid_bind_values_and_normalizes_legacy_empty_rows(db_session):
    from app.code_runtime.execution_target import ExecutionTarget
    from app.models.ai_chat import CodeRuntimeBinding

    with pytest.raises(StatementError, match="unsupported execution target"):
        await db_session.execute(
            update(CodeRuntimeBinding).values(execution_target="unsupported-target")
        )

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-legacy-target",
        title="Legacy target",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()
    binding = CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-legacy-target",
        runtime_base_url="https://sandbox.example.com/workspaces/ws-legacy-target",
        builder_url="https://sandbox.example.com/workspaces/ws-legacy-target/builder",
        execution_target=ExecutionTarget.LOCAL_FIXTURE.value,
    )
    db_session.add(binding)
    await db_session.flush()
    binding_id = binding.id
    await db_session.commit()

    await db_session.execute(
        text("UPDATE code_runtime_bindings SET execution_target = '' WHERE id = :id"),
        {"id": binding_id},
    )
    await db_session.commit()
    db_session.expire_all()

    legacy_binding = await db_session.get(CodeRuntimeBinding, binding_id)
    assert legacy_binding.execution_target == ExecutionTarget.CONTROL_PLANE.value


@pytest.mark.asyncio
async def test_runtime_binding_token_type_rejects_plaintext_bulk_update(db_session):
    from app.code_runtime.sandbox_auth import encrypt_runtime_cookie
    from app.models.ai_chat import CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-token",
        title="Token binding",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()
    binding = CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-token",
        runtime_base_url="https://sandbox.example.com/workspaces/ws-token",
        builder_url="https://sandbox.example.com/workspaces/ws-token/builder",
    )
    db_session.add(binding)
    await db_session.flush()
    binding_id = binding.id
    await db_session.commit()

    with pytest.raises(StatementError, match="desktop runtime token must be encrypted"):
        await db_session.execute(
            update(CodeRuntimeBinding)
            .where(CodeRuntimeBinding.id == binding_id)
            .values(desktop_agent_runtime_token_enc="plaintext-token")
        )

    encrypted_token = encrypt_runtime_cookie("desktop-runtime-token")
    await db_session.execute(
        update(CodeRuntimeBinding)
        .where(CodeRuntimeBinding.id == binding_id)
        .values(desktop_agent_runtime_token_enc=encrypted_token)
    )
    await db_session.commit()
    db_session.expire_all()

    saved_binding = await db_session.get(CodeRuntimeBinding, binding_id)
    assert saved_binding.desktop_agent_runtime_token_enc == encrypted_token


def test_code_runtime_agent_session_model_has_rail_snapshot_columns():
    from app.models.ai_chat import CodeRuntimeAgentSession

    columns = {column.name for column in sa_inspect(CodeRuntimeAgentSession).columns}
    assert {
        "title",
        "summary",
        "state",
        "model",
        "runtime_created_at",
        "runtime_updated_at",
        "last_active_at",
        "deleted_at",
        "capability_stale",
        "codex_session_resumable",
    }.issubset(columns)


def test_code_runtime_browser_session_model_has_isolated_identity_and_unique_binding_key():
    from app.models.ai_chat import CodeRuntimeBrowserSession

    columns = {column.name: column for column in sa_inspect(CodeRuntimeBrowserSession).columns}
    assert {
        "id",
        "binding_id",
        "browser_session_id",
        "runtime_session_cookie_enc",
        "runtime_session_hash",
        "runtime_session_expires_at",
        "generation",
        "created_at",
        "updated_at",
    }.issubset(columns)
    assert columns["binding_id"].index is True
    assert columns["browser_session_id"].nullable is False
    assert columns["runtime_session_cookie_enc"].nullable is False
    assert columns["runtime_session_hash"].nullable is False
    assert columns["generation"].nullable is False
    assert columns["generation"].default.arg == 1
    assert {
        constraint.name
        for constraint in CodeRuntimeBrowserSession.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    } == {"uq_code_runtime_browser_sessions_binding_browser"}


@pytest.mark.asyncio
async def test_application_sqlite_engine_enables_foreign_keys_and_cascades_browser_sessions():
    from app import database
    from app.models.ai_chat import AIChatSession, CodeRuntimeBinding, CodeRuntimeBrowserSession

    async with database.engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: CodeRuntimeBrowserSession.__table__.drop(
            sync_conn, checkfirst=True
        ))
        await conn.run_sync(lambda sync_conn: CodeRuntimeBinding.__table__.drop(
            sync_conn, checkfirst=True
        ))
        await conn.run_sync(lambda sync_conn: AIChatSession.__table__.drop(
            sync_conn, checkfirst=True
        ))
        await conn.run_sync(lambda sync_conn: AIChatSession.__table__.create(sync_conn))
        await conn.run_sync(lambda sync_conn: CodeRuntimeBinding.__table__.create(sync_conn))
        await conn.run_sync(lambda sync_conn: CodeRuntimeBrowserSession.__table__.create(sync_conn))

        assert await conn.scalar(database.text("PRAGMA foreign_keys")) == 1
        await conn.execute(database.text(
            """
            INSERT INTO ai_chat_sessions (
                id, tenant_id, user_id, title, status, mode, created_at, updated_at
            )
            VALUES (
                901, 7, 11, 'FK test', 'active', 'code', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ))
        await conn.execute(database.text(
            """
            INSERT INTO code_runtime_bindings (
                id, tenant_id, user_id, app_id, session_id, external_application_id,
                runtime_base_url, builder_url, status, created_at, updated_at
            ) VALUES (
                901, 7, 11, NULL, 901, 'code-app-fk',
                'https://sandbox.example.com/workspaces/ws-fk',
                'https://sandbox.example.com/workspaces/ws-fk/builder',
                'ready', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ))
        await conn.execute(database.text(
            """
            INSERT INTO code_runtime_browser_sessions (
                id, binding_id, browser_session_id, runtime_session_cookie_enc,
                runtime_session_hash, created_at, updated_at
            ) VALUES (
                901, 901, 'browser-fk', 'cookie-fk', 'hash-fk',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ))
        await conn.execute(database.text(
            "DELETE FROM code_runtime_bindings WHERE id = 901"
        ))
        assert await conn.scalar(database.text(
            "SELECT COUNT(*) FROM code_runtime_browser_sessions WHERE id = 901"
        )) == 0


@pytest.mark.asyncio
async def test_init_db_expands_old_runtime_binding_schema_without_cleaning_builder_url(tmp_path, monkeypatch):
    from app import database

    db_path = tmp_path / "legacy-runtime.sqlite"
    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    builder_url = (
        "https://sandbox.example.com/workspaces/ws-1/builder"
        "?token=legacy-entry-token&handoffId=legacy-handoff"
    )
    async with legacy_engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE ai_chat_sessions (
                id INTEGER PRIMARY KEY
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE code_runtime_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                app_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                external_application_id VARCHAR(80) NOT NULL,
                runtime_base_url VARCHAR(1000) NOT NULL,
                builder_url VARCHAR(2000) NOT NULL,
                workspace_id VARCHAR(120),
                sandbox_instance_id VARCHAR(160),
                runtime_session_id VARCHAR(160),
                conversation_id VARCHAR(160),
                status VARCHAR(32) NOT NULL,
                last_error TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE code_runtime_browser_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                binding_id INTEGER NOT NULL,
                browser_session_id VARCHAR(64) NOT NULL,
                runtime_session_cookie_enc TEXT NOT NULL,
                runtime_session_hash VARCHAR(64) NOT NULL,
                runtime_session_expires_at DATETIME,
                generation INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_code_runtime_browser_sessions_binding_browser
                    UNIQUE (binding_id, browser_session_id),
                FOREIGN KEY(binding_id) REFERENCES code_runtime_bindings(id) ON DELETE CASCADE
            )
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO code_runtime_bindings (
                tenant_id, user_id, app_id, session_id, external_application_id,
                runtime_base_url, builder_url, status, created_at, updated_at
            ) VALUES (
                7, 11, 42, 1, 'code-app-1',
                'https://sandbox.example.com/workspaces/ws-1',
                ?, 'ready', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (builder_url,),
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO code_runtime_browser_sessions (
                binding_id, browser_session_id, runtime_session_cookie_enc,
                runtime_session_hash, created_at, updated_at
            ) VALUES (
                1, 'legacy-browser', 'legacy-cookie', 'legacy-hash',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    await database.init_db()
    await database.init_db()

    async with legacy_engine.begin() as conn:
        binding_columns = {
            row["name"] for row in (await conn.execute(
                database.text("PRAGMA table_info(code_runtime_bindings)")
            )).mappings()
        }
        assert {
            "runtime_service_session_enc",
            "auth_generation",
            "execution_target",
            "desktop_agent_runtime_token_enc",
        }.issubset(binding_columns)
        binding = (await conn.execute(database.text(
            "SELECT builder_url, auth_generation, execution_target "
            "FROM code_runtime_bindings WHERE id = 1"
        ))).one()
        assert binding.builder_url == builder_url
        assert binding.auth_generation == 1
        assert binding.execution_target == "control_plane"

        browser_fk = (await conn.execute(database.text(
            "PRAGMA foreign_key_list(code_runtime_browser_sessions)"
        ))).mappings().all()
        assert {row["table"] for row in browser_fk} == {"code_runtime_bindings"}
        historical_browser = (await conn.execute(database.text(
            "SELECT runtime_session_cookie_enc FROM code_runtime_browser_sessions "
            "WHERE binding_id = 1 AND browser_session_id = 'legacy-browser'"
        ))).one()
        assert historical_browser.runtime_session_cookie_enc == "legacy-cookie"

        browser_table = await conn.scalar(database.text(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'code_runtime_browser_sessions'"
        ))
        assert browser_table == "code_runtime_browser_sessions"
        index_names = {
            row["name"] for row in (await conn.execute(
                database.text("PRAGMA index_list(code_runtime_browser_sessions)")
            )).mappings()
        }
        assert "uq_code_runtime_browser_sessions_binding_browser" in index_names

        await conn.execute(database.text(
            """
            INSERT INTO ai_chat_sessions (id) VALUES (2)
            """
        ))
        await conn.execute(database.text(
            """
            INSERT INTO code_runtime_bindings (
                tenant_id, user_id, app_id, session_id, external_application_id,
                runtime_base_url, builder_url, status, created_at, updated_at
            ) VALUES (
                7, 11, NULL, 2, 'code-app-2',
                'https://sandbox.example.com/workspaces/ws-2',
                'https://sandbox.example.com/workspaces/ws-2/builder',
                'ready', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ))
        new_binding_id = await conn.scalar(database.text(
            "SELECT id FROM code_runtime_bindings WHERE session_id = 2"
        ))
        await conn.execute(database.text(
            """
            INSERT INTO code_runtime_browser_sessions (
                binding_id, browser_session_id, runtime_session_cookie_enc,
                runtime_session_hash, created_at, updated_at
            ) VALUES (
                :binding_id, 'new-browser', 'new-cookie', 'new-hash',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ), {"binding_id": new_binding_id})
        assert await conn.scalar(database.text(
            "SELECT COUNT(*) FROM code_runtime_browser_sessions "
            "WHERE binding_id = :binding_id"
        ), {"binding_id": new_binding_id}) == 1

        archive_count = await conn.scalar(database.text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
            "AND name LIKE 'code_runtime_bindings_app_id_notnull%'"
        ))
        assert archive_count == 1

    await legacy_engine.dispose()


@pytest.mark.asyncio
async def test_init_db_rebuilds_old_runtime_agent_sessions_with_nullable_legacy_columns(
    tmp_path,
    monkeypatch,
):
    from app import database

    db_path = tmp_path / "legacy-runtime-agent-sessions.sqlite"
    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with legacy_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE ai_chat_sessions (id INTEGER PRIMARY KEY)")
        await conn.exec_driver_sql(
            """
            CREATE TABLE code_runtime_agent_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                app_id INTEGER,
                session_id INTEGER NOT NULL,
                external_application_id VARCHAR(80) NOT NULL,
                workspace_id VARCHAR(120),
                sandbox_instance_id VARCHAR(160),
                runtime_session_id VARCHAR(160) NOT NULL,
                conversation_id VARCHAR(160) NOT NULL,
                conversation_purpose VARCHAR(32) NOT NULL,
                conversation_purpose_revision BIGINT NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_code_runtime_agent_sessions_shell_runtime
                    UNIQUE (session_id, runtime_session_id)
            )
            """
        )
        await conn.exec_driver_sql("INSERT INTO ai_chat_sessions (id) VALUES (1)")
        await conn.exec_driver_sql("INSERT INTO ai_chat_sessions (id) VALUES (2)")
        await conn.exec_driver_sql(
            """
            INSERT INTO code_runtime_agent_sessions (
                tenant_id, user_id, session_id, external_application_id,
                runtime_session_id, conversation_id, conversation_purpose,
                conversation_purpose_revision, status, created_at, updated_at
            ) VALUES (
                7, 11, 1, 'crm', 'runtime-legacy', 'conversation-1', 'code',
                3, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO code_runtime_agent_sessions (
                tenant_id, user_id, session_id, external_application_id,
                runtime_session_id, conversation_id, conversation_purpose,
                conversation_purpose_revision, status, created_at, updated_at
            ) VALUES (
                7, 11, 2, 'crm', 'runtime-legacy-2', 'conversation-2', 'code',
                4, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    await database.init_db()

    async with legacy_engine.begin() as conn:
        columns = {
            row["name"]: row
            for row in (await conn.execute(
                database.text("PRAGMA table_info(code_runtime_agent_sessions)")
            )).mappings()
        }
        for column_name in {
            "conversation_id",
            "conversation_purpose",
            "conversation_purpose_revision",
            "status",
        }:
            assert columns[column_name]["notnull"] == 0

        historical = (await conn.execute(database.text(
            """
            SELECT runtime_session_id, conversation_id, conversation_purpose_revision
            FROM code_runtime_agent_sessions
            WHERE runtime_session_id = 'runtime-legacy'
            """
        ))).one()
        assert historical.runtime_session_id == "runtime-legacy"
        assert historical.conversation_id == "conversation-1"
        assert historical.conversation_purpose_revision == 3
        assert await conn.scalar(database.text(
            "SELECT COUNT(*) FROM code_runtime_agent_sessions"
        )) == 2

        await conn.execute(database.text("INSERT INTO ai_chat_sessions (id) VALUES (3)"))
        await conn.execute(database.text(
            """
            INSERT INTO code_runtime_agent_sessions (
                tenant_id, user_id, session_id, external_application_id,
                runtime_session_id, conversation_id, conversation_purpose,
                conversation_purpose_revision, status, created_at, updated_at
            ) VALUES (
                7, 11, 3, 'crm', 'runtime-null-legacy', NULL, NULL, NULL, NULL,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ))
        assert await conn.scalar(database.text(
            "SELECT COUNT(*) FROM code_runtime_agent_sessions"
        )) == 3

    await legacy_engine.dispose()


def test_ai_chat_session_model_tracks_external_code_application():
    from sqlalchemy import inspect as sa_inspect
    from app.models.ai_chat import AIChatSession

    cols = {c.name for c in sa_inspect(AIChatSession).columns}
    assert {
        "public_id",
        "external_application_id",
        "external_app_name",
        "external_app_code",
    }.issubset(cols)


def test_code_runtime_proxy_prefix_accepts_public_uuid():
    from app.code_runtime.service import code_runtime_proxy_prefix

    public_id = "e9a6aa2a-9043-4bb5-bb5d-6d764c5fbfa3"

    assert code_runtime_proxy_prefix(public_id) == f"/api/code-runtime/{public_id}"


def test_build_embed_url_removes_runtime_entry_token_and_adds_dolphin_token():
    from app.code_runtime.service import build_embed_url

    url = build_embed_url(
        session_id=12,
        builder_url=(
            "https://sandbox.example.com/workspaces/ws-1/builder"
            "?token=entry-token&handoffId=handoff-1&tab=#editor"
        ),
        dolphin_token="embed-token",
    )

    assert url == (
        "/api/code-runtime/12/builder/"
        "?handoffId=handoff-1&tab="
        "&externalSessionRail=1&hideHistory=1&hideNewSession=1&dolphin_token=embed-token"
        "#editor"
    )
    assert "entry-token" not in url


def test_build_embed_url_passes_hide_history_to_embedded_runtime():
    from app.code_runtime.service import build_embed_url

    url = build_embed_url(
        session_id=12,
        builder_url="https://sandbox.example.com/workspaces/ws-1/builder",
        dolphin_token="embed-token",
    )

    assert "externalSessionRail=1" in url
    assert "hideHistory=1" in url
    assert "hideNewSession=1" in url


def test_derive_runtime_base_url_strips_builder_suffix():
    from app.code_runtime.service import derive_runtime_base_url

    assert derive_runtime_base_url(
        "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token"
    ) == "https://sandbox.example.com/workspaces/ws-1"
    assert derive_runtime_base_url("https://sandbox.example.com/builder") == "https://sandbox.example.com"


def test_control_plane_base_url_defaults_to_local_dev_port(monkeypatch):
    from app.code_runtime.service import control_plane_base_url

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_URL", raising=False)

    assert control_plane_base_url() == "http://127.0.0.1:8080"


def test_local_model_proxy_token_is_stable_and_scope_bound(monkeypatch):
    from app.config import settings
    from app.code_runtime.service import create_local_model_proxy_token

    monkeypatch.setattr(settings, "jwt_secret_key", "unit-test-secret", raising=False)

    first = create_local_model_proxy_token(
        application_id="application-a",
        user_id=11,
        tenant_id=0,
        control_plane_tenant_id="tenant-cp",
    )
    second = create_local_model_proxy_token(
        application_id="application-a",
        user_id=11,
        tenant_id=0,
        control_plane_tenant_id="tenant-cp",
    )
    other = create_local_model_proxy_token(
        application_id="application-b",
        user_id=11,
        tenant_id=0,
        control_plane_tenant_id="tenant-cp",
    )

    assert first == second
    assert first != other
    assert len(first) >= 40


def test_control_plane_headers_combine_user_bearer_and_delegated_identity(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "settings-token", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)

    ctx = SimpleNamespace(
        user=SimpleNamespace(
            id=11,
            username="admin",
            display_name="Admin User",
            coding_tenant_id="default",
        ),
        apaas_user_id="apaas-user-1",
        apaas_tenant_id="apaas-tenant-1",
        tenant_id=7,
    )
    headers = service._control_plane_headers(
        "Bearer user-token",
        delegated_context=ctx,
    )

    assert headers["Authorization"] == "Bearer user-token"
    assert "X-Auth-Provider" not in headers
    assert headers["X-Tenant-Id"] == "default"
    assert headers["X-AI-Builder-Delegation-Secret"] == "shared-secret"
    assert headers["X-AI-Builder-Delegated-User-Id"] == "apaas-user-1"
    assert headers["X-AI-Builder-Delegated-Username"] == "ai-builder-admin-11"
    assert headers["X-AI-Builder-Delegated-Display-Name-B64"] == "QWRtaW4gVXNlcg=="


def test_control_plane_headers_omit_delegated_headers_without_context(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)

    headers = service._control_plane_headers("Bearer user-token")

    assert headers == {"Authorization": "Bearer user-token"}


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("admin", "ai-builder-admin-11"),
        ("root", "ai-builder-root-11"),
    ],
)
def test_delegated_identity_headers_map_reserved_usernames(username, expected):
    from app.code_runtime import service

    headers = service._delegated_identity_headers(
        SimpleNamespace(user=SimpleNamespace(id=11, username=username)),
    )

    assert headers["X-AI-Builder-Delegated-Username"] == expected


def test_control_plane_headers_prefer_current_builder_tenant_mapping(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "", raising=False)

    ctx = SimpleNamespace(
        user=SimpleNamespace(coding_tenant_id="new-tenant"),
        control_plane_tenant_id="0",
        tenant_id=3,
    )
    headers = service._control_plane_headers(
        "Bearer user-token",
        delegated_context=ctx,
    )

    assert headers["X-Tenant-Id"] == "0"


def test_control_plane_headers_prefer_active_builder_tenant_mapping(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "", raising=False)

    ctx = SimpleNamespace(
        user=SimpleNamespace(coding_tenant_id="2077284540335579137"),
        control_plane_tenant_id="0",
        tenant_id=3,
    )
    headers = service._control_plane_headers(
        "Bearer user-token",
        delegated_context=ctx,
    )

    assert headers["X-Tenant-Id"] == "0"


def test_control_plane_headers_use_apaas_tenant_without_untrusted_delegation(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)

    ctx = SimpleNamespace(
        user=SimpleNamespace(coding_tenant_id=None),
        control_plane_tenant_id=None,
        apaas_tenant_id="apaas-tenant-1",
        tenant_id=3,
    )
    headers = service._control_plane_headers(
        "Bearer apaas-access-token",
        delegated_context=ctx,
        auth_provider="apaas",
    )

    assert headers["Authorization"] == "Bearer apaas-access-token"
    assert headers["X-Tenant-Id"] == "apaas-tenant-1"
    assert not any(key.startswith("X-AI-Builder-") for key in headers)


@pytest.mark.asyncio
async def test_verify_control_plane_application_access_uses_current_user_and_tenant(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"applicationId": "app-1"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.verify_control_plane_application_access(
        "app-1",
        authorization_header="Bearer user-token",
        delegated_context=SimpleNamespace(
            control_plane_tenant_id="tenant-current",
            user=SimpleNamespace(coding_tenant_id="tenant-stale"),
        ),
    )

    assert calls == [{
        "url": "https://code.example.com/control-plane/api/applications/app-1",
        "headers": {
            "Authorization": "Bearer user-token",
            "X-Tenant-Id": "tenant-current",
        },
    }]


def test_control_plane_headers_include_delegation_secret(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7)
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)

    headers = service._control_plane_headers(delegated_context=ctx)

    assert headers["X-AI-Builder-Delegation-Secret"] == "shared-secret"


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("admin", "ai-builder-admin-11"),
        ("root", "ai-builder-root-11"),
    ],
)
def test_workspace_open_headers_preserve_trusted_delegation_with_coordinator_token(
    monkeypatch,
    username,
    expected,
):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "workspace-token")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            id=11,
            username=username,
            display_name="Admin User",
            coding_tenant_id="tenant-current",
        ),
        apaas_user_id="apaas-user-1",
        apaas_tenant_id="apaas-tenant-1",
        tenant_id=7,
    )

    headers = service._workspace_open_headers(
        "Bearer user-token",
        delegated_context=ctx,
        shell_session_id=42,
    )

    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer workspace-token"
    assert headers["X-Tenant-Id"] == "tenant-current"
    assert headers["X-AI-Builder-Delegation-Secret"] == "shared-secret"
    assert headers["X-AI-Builder-Delegated-User-Id"] == "apaas-user-1"
    assert headers["X-AI-Builder-Delegated-Username"] == expected
    assert headers["X-AI-Builder-Delegated-Display-Name-B64"] == "QWRtaW4gVXNlcg=="


def test_workspace_open_headers_omit_delegated_identity_without_secret(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "workspace-token")
    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_delegation_secret", "", raising=False)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11, username="admin", coding_tenant_id="tenant-current"),
        apaas_user_id="apaas-user-1",
        tenant_id=7,
    )

    headers = service._workspace_open_headers(
        "Bearer user-token",
        delegated_context=ctx,
    )

    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer workspace-token"
    assert not any(key.startswith("X-AI-Builder-") for key in headers)


@pytest.mark.asyncio
async def test_default_workspace_open_reports_control_plane_connection_target(monkeypatch):
    import httpx
    from fastapi import HTTPException
    from app.config import settings
    from app.code_runtime import service

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **_kwargs):
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_url", "")
    monkeypatch.setattr(settings, "dolphin_code_builder_url", "")
    monkeypatch.setattr(service.httpx, "AsyncClient", FailingClient)

    with pytest.raises(HTTPException) as exc:
        await service.default_workspace_open("app-1")

    assert exc.value.status_code == 503
    assert "http://127.0.0.1:8080" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_default_workspace_open_falls_back_to_configured_builder_url(monkeypatch):
    import httpx
    from app.code_runtime import service

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **_kwargs):
            raise httpx.ConnectError("connection refused", request=httpx.Request("POST", url))

    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:5173/builder/")
    monkeypatch.setattr(service.httpx, "AsyncClient", FailingClient)

    opened = await service.default_workspace_open("app-1")

    assert opened["applicationId"] == "app-1"
    assert opened["workspaceId"] == "local-builder-app-1"
    assert opened["sandboxInstanceId"] == "local-builder"
    assert opened["specReviewUrl"] == "http://127.0.0.1:5173/builder/"


@pytest.mark.asyncio
async def test_default_workspace_open_rebases_builder_urls_to_local_builder(monkeypatch):
    from app.code_runtime import service

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "applicationId": "app-1",
                "workspaceId": "ws-1",
                "sandboxInstanceId": "sandbox-1",
                "chatUrl": "https://sandbox.mock/workspaces/ws-1/builder/?token=entry-token",
                "specReviewUrl": "https://sandbox.mock/workspaces/ws-1/builder/?tab=spec&token=entry-token",
                "webideUrl": "https://sandbox.mock/workspaces/ws-1/ide/?token=entry-token",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url: str, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:5173/builder/")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    opened = await service.default_workspace_open("app-1")

    assert opened["chatUrl"] == "http://127.0.0.1:5173/builder/?token=entry-token"
    assert opened["specReviewUrl"] == "http://127.0.0.1:5173/builder/?tab=spec&token=entry-token"
    assert opened["webideUrl"] == "https://sandbox.mock/workspaces/ws-1/ide/?token=entry-token"


@pytest.mark.asyncio
async def test_default_workspace_open_uses_configured_cold_start_timeout(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    timeouts: list[object] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "https://sandbox.example.com/builder"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            timeouts.append(kwargs["timeout"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url: str, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setattr(settings, "dolphin_code_workspace_open_timeout_seconds", 660)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open("app-1")

    assert timeouts[0].read == 660


@pytest.mark.asyncio
async def test_list_code_applications_fetches_and_maps_control_plane_apps(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "items": [
                    {
                        "applicationId": "code-app-1",
                        "appCode": "crm_portal",
                        "appName": "客户门户",
                        "description": "全代码应用",
                        "provisionStatus": "READY",
                        "repository": {"url": "https://git.example.com/acme/crm.git"},
                        "owner": {"userId": "u-1", "displayName": "Admin"},
                        "createdAt": "2026-06-30T10:00:00Z",
                        "updatedAt": "2026-06-30T11:00:00Z",
                    }
                ],
                "page": 2,
                "pageSize": 5,
                "total": 21,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "cp-token")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    result = await service.list_code_applications(keyword="crm", page=2, page_size=5)

    assert calls == [{
        "url": "https://code.example.com/control-plane/api/applications",
        "headers": {"Authorization": "Bearer cp-token"},
        "params": {"page": 2, "pageSize": 5, "keyword": "crm"},
    }]
    assert result["page"] == 2
    assert result["pageSize"] == 5
    assert result["total"] == 21
    assert result["items"][0] == {
        "id": "code-app-1",
        "external_application_id": "code-app-1",
        "app_name": "客户门户",
        "app_code": "crm_portal",
        "description": "全代码应用",
        "source": "d-ai-code",
        "app_type": "ai-code",
        "status": "READY",
        "local_status": "completed",
        "remote_status": "READY",
        "models": 0,
        "forms": 0,
        "roles": 0,
        "dicts": 0,
        "repository": {"url": "https://git.example.com/acme/crm.git"},
        "owner": {"userId": "u-1", "displayName": "Admin"},
        "created_at": "2026-06-30T10:00:00Z",
        "updated_at": "2026-06-30T11:00:00Z",
    }


@pytest.mark.asyncio
async def test_list_code_applications_uses_local_mode_without_control_plane(monkeypatch):
    from app.code_runtime import service

    class UnexpectedClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("control plane should not be called in local mode")

    monkeypatch.setenv("DOLPHIN_CODE_LOCAL_CODE_APPLICATIONS", "true")
    monkeypatch.setattr(service.httpx, "AsyncClient", UnexpectedClient)

    result = await service.list_code_applications(keyword="crm", page=2, page_size=5)

    assert result == {
        "items": [],
        "page": 2,
        "pageSize": 5,
        "total": 0,
        "source": "d-ai-code-local",
    }


@pytest.mark.asyncio
async def test_list_code_applications_restores_local_workspaces(
    db_session,
    tmp_path,
    monkeypatch,
):
    from app.code_runtime import service
    from app.models import RegisteredWorkspace

    class UnexpectedClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("local application list must not call Control Plane")

    local_path = tmp_path / "sales-assistant"
    local_path.mkdir()
    other_path = tmp_path / "other-app"
    other_path.mkdir()
    db_session.add_all([
        RegisteredWorkspace(
            ws_id="11_local",
            abs_path=str(local_path.resolve()),
            user_id=11,
            tenant_id=7,
            workspace_type="code-local-application",
            apaas_app_id="local-sales",
            display_name="销售助手",
        ),
        RegisteredWorkspace(
            ws_id="12_other",
            abs_path=str(other_path.resolve()),
            user_id=12,
            tenant_id=7,
            workspace_type="code-local-application",
            apaas_app_id="local-other",
            display_name="其他应用",
        ),
    ])
    await db_session.commit()
    monkeypatch.setattr(service.httpx, "AsyncClient", UnexpectedClient)
    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7)

    result = await service.list_code_applications(
        source="local",
        keyword="销售",
        db=db_session,
        ctx=ctx,
    )

    assert result["source"] == "desktop-local"
    assert result["total"] == 1
    assert result["items"] == [{
        "id": "local-sales",
        "external_application_id": "local-sales",
        "app_name": "销售助手",
        "app_code": "sales-assistant",
        "description": None,
        "source": "desktop-local",
        "app_type": "ai-code",
        "status": "READY",
        "local_status": "completed",
        "remote_status": None,
        "models": 0,
        "forms": 0,
        "roles": 0,
        "dicts": 0,
        "local_workspace_path": str(local_path.resolve()),
        "workspace_id": "11_local",
        "repository": None,
        "owner": None,
        "created_at": result["items"][0]["created_at"],
        "updated_at": result["items"][0]["updated_at"],
    }]


@pytest.mark.asyncio
async def test_list_code_applications_rejects_non_json_success_response(monkeypatch):
    from app.code_runtime import service

    class FakeResponse:
        status_code = 200
        text = "<html><body>frontend fallback</body></html>"

        def json(self):
            raise ValueError("Expecting value")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException, match="应用列表响应无效") as exc_info:
        await service.list_code_applications()

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_create_code_application_posts_to_control_plane_with_default_seed(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 201
        text = ""

        def json(self):
            return {
                "applicationId": "code-app-new",
                "appCode": "sales-lead-helper",
                "appName": "销售线索评分助手",
                "description": None,
                "provisionStatus": "READY",
                "seedProjectId": "1781233861147",
                "repository": {"repositoryUrl": "https://git.example.com/sales.git"},
                "createdAt": "2026-07-02T07:00:00Z",
                "updatedAt": "2026-07-02T07:00:01Z",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "cp-token")
    monkeypatch.delenv("DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID", raising=False)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    result = await service.create_code_application(
        app_name="销售线索评分助手",
        app_code="sales-lead-helper",
    )

    assert calls == [{
        "url": "https://code.example.com/control-plane/api/applications",
        "headers": {"Authorization": "Bearer cp-token", "Content-Type": "application/json"},
        "json": {
            "appCode": "sales-lead-helper",
            "appName": "销售线索评分助手",
            "seedProjectId": "1781233861147",
        },
    }]
    assert result["external_application_id"] == "code-app-new"
    assert result["app_name"] == "销售线索评分助手"
    assert result["app_code"] == "sales-lead-helper"
    assert result["local_status"] == "completed"


@pytest.mark.asyncio
async def test_create_code_application_uses_local_mode_without_control_plane(monkeypatch):
    from app.code_runtime import service

    class UnexpectedClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("control plane should not be called in local mode")

    monkeypatch.setenv("DOLPHIN_CODE_LOCAL_CODE_APPLICATIONS", "true")
    monkeypatch.setattr(service.httpx, "AsyncClient", UnexpectedClient)

    result = await service.create_code_application(
        app_name="Dolphin Code CRM",
        app_code="dolphin-code-crm",
    )

    assert result["external_application_id"].startswith("local-")
    assert result["app_name"] == "Dolphin Code CRM"
    assert result["app_code"] == "dolphin-code-crm"
    assert result["status"] == "READY"
    assert result["local_status"] == "completed"


@pytest.mark.asyncio
async def test_create_code_application_registers_existing_local_workspace(
    db_session,
    tmp_path,
    monkeypatch,
):
    from sqlalchemy import select

    from app.code_runtime import service
    from app.models import RegisteredWorkspace

    class UnexpectedClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("local application create must not call Control Plane")

    monkeypatch.setattr(service.httpx, "AsyncClient", UnexpectedClient)
    project_path = tmp_path / "sales-local"
    project_path.mkdir()
    (project_path / "README.md").write_text("existing", encoding="utf-8")
    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7)

    result = await service.create_code_application(
        app_name="本地销售助手",
        app_code="sales-local",
        local_application=True,
        local_workspace_path=str(project_path),
        directory_mode="existing_directory",
        initialize_project=True,
        db=db_session,
        ctx=ctx,
    )

    workspace = (
        await db_session.execute(
            select(RegisteredWorkspace).where(
                RegisteredWorkspace.apaas_app_id == result["external_application_id"]
            )
        )
    ).scalar_one()
    assert result["external_application_id"].startswith("local-")
    assert result["local_workspace_path"] == str(project_path.resolve())
    assert result["workspace_id"] == workspace.ws_id
    assert workspace.workspace_type == "code-local-application"
    assert workspace.display_name == "本地销售助手"
    assert workspace.logical_application_id == result["logical_application_id"]
    assert result["availability"] == "ready"
    assert result["already_registered"] is False
    assert (project_path / "README.md").read_text(encoding="utf-8") == "existing"
    assert not (project_path / ".git").exists()

    reused = await service.create_code_application(
        app_name="重复请求",
        app_code="sales-local-again",
        local_application=True,
        local_workspace_path=str(project_path.parent / "." / project_path.name),
        directory_mode="existing_directory",
        db=db_session,
        ctx=ctx,
    )

    assert reused["external_application_id"] == result["external_application_id"]
    assert reused["logical_application_id"] == result["logical_application_id"]
    assert reused["already_registered"] is True


@pytest.mark.asyncio
async def test_list_code_applications_projects_persisted_local_location_contract(
    db_session,
    tmp_path,
):
    from app.code_runtime import service
    from app.models import RegisteredWorkspace

    missing_workspace = tmp_path / "missing-local-workspace"
    db_session.add(RegisteredWorkspace(
        ws_id="workspace-local-sales",
        abs_path=str(missing_workspace),
        user_id=11,
        tenant_id=7,
        workspace_type="code-local-application",
        apaas_app_id="local-sales",
        logical_application_id="logical-sales",
        linked_remote_application_id="remote-sales",
        linked_remote_deployment_id="deployment-sales",
        display_name="本机销售助手",
    ))
    await db_session.commit()

    result = await service.list_code_applications(
        source="local",
        db=db_session,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
    )

    assert result["items"] == [{
        **result["items"][0],
        "logical_application_id": "logical-sales",
        "linked_remote_application_id": "remote-sales",
        "linked_remote_deployment_id": "deployment-sales",
        "local_workspace_path": str(missing_workspace),
        "workspace_id": "workspace-local-sales",
        "availability": "missing",
    }]


@pytest.mark.asyncio
async def test_create_code_application_uses_seed_project_override(monkeypatch):
    from app.code_runtime import service
    from app.config import settings

    calls: list[dict] = []

    class FakeResponse:
        status_code = 201
        text = ""

        def json(self):
            return {
                "applicationId": "code-app-new",
                "appCode": "inventory-copilot",
                "appName": "库存助手",
                "provisionStatus": "PENDING",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_DEFAULT_SEED_PROJECT_ID", "90001")
    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "", raising=False)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.create_code_application(
        app_name="库存助手",
        app_code="inventory-copilot",
        seed_project_id="90002",
        authorization_header="Bearer user-token",
    )

    assert calls[0]["headers"]["Authorization"] == "Bearer user-token"
    assert calls[0]["json"]["seedProjectId"] == "90002"


@pytest.mark.asyncio
async def test_create_code_application_falls_back_to_local_builder_when_seed_is_missing(monkeypatch):
    from app.code_runtime import service

    class FakeResponse:
        status_code = 404
        text = '{"code":"SEED_PROJECT_NOT_FOUND","message":"seed project not found"}'

        def json(self):
            return {
                "code": "SEED_PROJECT_NOT_FOUND",
                "message": "seed project not found",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url: str, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:5175/builder/")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    result = await service.create_code_application(
        app_name="本地 Code 应用",
        app_code="local-code-app",
    )

    assert result["external_application_id"].startswith("local-")
    assert result["app_name"] == "本地 Code 应用"
    assert result["app_code"] == "local-code-app"
    assert result["status"] == "READY"
    assert result["local_status"] == "completed"


@pytest.mark.asyncio
async def test_default_workspace_open_uses_local_builder_for_local_application(monkeypatch):
    from app.code_runtime import service

    class UnexpectedClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("local application must not call Control Plane")

    monkeypatch.setenv("DOLPHIN_CODE_BUILDER_URL", "http://127.0.0.1:5175/builder/")
    monkeypatch.setattr(service.httpx, "AsyncClient", UnexpectedClient)

    opened = await service.default_workspace_open("local-abc123")

    assert opened["applicationId"] == "local-abc123"
    assert opened["workspaceId"] == "local-builder-local-abc123"
    assert opened["specReviewUrl"] == "http://127.0.0.1:5175/builder/"


@pytest.mark.asyncio
async def test_default_workspace_open_forwards_request_authorization_when_no_service_token(monkeypatch):
    from app.config import settings
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "https://sandbox.example.com/builder"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.delenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_control_plane_token", "")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open("code-app-1", authorization_header="Bearer user-token")

    assert calls[0]["headers"]["Authorization"] == "Bearer user-token"


@pytest.mark.asyncio
async def test_default_workspace_open_uses_independent_override_url_and_token(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "http://127.0.0.1:61139/builder/"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setenv(
        "DOLPHIN_CODE_CONTROL_PLANE_URL",
        "https://code.example.com/control-plane",
    )
    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_URL", "http://127.0.0.1:44633")
    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "workspace-token")

    async def allow_application_access(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        service,
        "verify_control_plane_application_access",
        allow_application_access,
    )
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open(
        "code-app-1",
        authorization_header="Bearer user-token",
    )

    assert calls[0]["url"] == "http://127.0.0.1:44633/api/applications/code-app-1/workspace/open"
    assert calls[0]["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer workspace-token",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("workspace_url", "workspace_token"),
    [
        ("", "workspace-token"),
        ("http://127.0.0.1:44633", ""),
    ],
)
async def test_default_workspace_open_requires_override_url_and_token_together(
    monkeypatch,
    workspace_url,
    workspace_token,
):
    from app.code_runtime import service

    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_URL", workspace_url)
    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", workspace_token)
    monkeypatch.setattr(service.settings, "dolphin_code_workspace_open_url", "")
    monkeypatch.setattr(service.settings, "dolphin_code_workspace_open_token", "")

    with pytest.raises(HTTPException) as exc_info:
        await service.default_workspace_open(
            "code-app-1",
            authorization_header="Bearer user-token",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Code workspace coordinator 配置不完整"


@pytest.mark.asyncio
async def test_default_workspace_open_sends_trusted_delegation_with_user_token(monkeypatch):
    from app.code_runtime import service

    calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "https://sandbox.example.com/builder"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse()

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11, username="admin", display_name="张三"),
        tenant_id=7,
        tenant_role="platform_admin",
        apaas_user_id="100169876816012509184",
        apaas_tenant_id="844246516607483905",
    )

    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com/control-plane")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_TOKEN", "cp-token")
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET", "shared-secret")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open(
        "code-app-1",
        authorization_header="Bearer user-token",
        delegated_context=ctx,
        shell_session_id=42,
    )

    headers = calls[0]["headers"]
    assert headers["Authorization"] == "Bearer user-token"
    assert headers["X-AI-Builder-Delegation-Secret"] == "shared-secret"
    assert headers["X-AI-Builder-Delegated-User-Id"] == "100169876816012509184"
    assert headers["X-AI-Builder-Delegated-Username"] == "ai-builder-admin-11"
    assert headers["X-AI-Builder-Delegated-Display-Name-B64"] == "5byg5LiJ"


def test_delegated_identity_keeps_non_reserved_username():
    from app.code_runtime import service

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=12, username="zhangsan", display_name="张三"),
        tenant_id=7,
    )

    headers = service._delegated_identity_headers(ctx)

    assert headers["X-AI-Builder-Delegated-Username"] == "zhangsan"


def test_embed_token_round_trip_is_bound_to_session_and_browser_session():
    from fastapi import HTTPException
    from app.code_runtime.service import (
        create_embed_token,
        create_proxy_cookie_token,
        validate_embed_token,
        validate_proxy_cookie_token,
    )

    token = create_embed_token(
        session_id=12,
        user_id=34,
        tenant_id=56,
        browser_session_id="browser-session-1",
        minutes=1,
    )

    payload = validate_embed_token(
        token,
        session_id=12,
        browser_session_id="browser-session-1",
    )
    assert payload["sid"] == "12"
    assert payload["sub"] == "34"
    assert payload["tid"] == 56
    assert payload["bsid"] == "browser-session-1"

    with pytest.raises(HTTPException):
        validate_embed_token(token, session_id=13, browser_session_id="browser-session-1")
    with pytest.raises(HTTPException):
        validate_embed_token(token, session_id=12, browser_session_id="browser-session-2")

    proxy_token = create_proxy_cookie_token(
        session_id=12,
        user_id=34,
        tenant_id=56,
        browser_session_id="browser-session-1",
        minutes=60,
    )
    assert validate_proxy_cookie_token(
        proxy_token,
        session_id=12,
        browser_session_id="browser-session-1",
    )["type"] == "code_runtime_proxy"

    with pytest.raises(HTTPException):
        validate_proxy_cookie_token(token, session_id=12, browser_session_id="browser-session-1")

    with pytest.raises(ValueError):
        create_embed_token(session_id=12, user_id=34, tenant_id=56, browser_session_id="")
    with pytest.raises(ValueError):
        create_proxy_cookie_token(
            session_id=12,
            user_id=34,
            tenant_id=56,
            browser_session_id="x" * 65,
        )


def test_split_entry_token_removes_only_token_and_never_exposes_sensitive_values():
    from app.code_runtime.sandbox_auth import split_entry_token

    clean_url, entry_token = split_entry_token(
        "https://sandbox.example.com/workspaces/ws-1/builder"
        "?handoffId=h1&token=entry-secret&tab=&token=second-secret#editor"
    )

    assert clean_url == (
        "https://sandbox.example.com/workspaces/ws-1/builder"
        "?handoffId=h1&tab=#editor"
    )
    assert entry_token == "entry-secret"

    with pytest.raises(ValueError) as exc_info:
        split_entry_token("https://sandbox.example.com/builder?handoffId=h1")
    assert "https://" not in str(exc_info.value)
    assert "h1" not in str(exc_info.value)


def test_runtime_cookie_encryption_round_trip_rejects_invalid_ciphertext_without_leaking_value():
    from app.code_runtime.sandbox_auth import (
        RUNTIME_COOKIE_NAME,
        decrypt_runtime_cookie,
        encrypt_runtime_cookie,
    )

    encrypted = encrypt_runtime_cookie("runtime-cookie-secret")

    assert RUNTIME_COOKIE_NAME == "apaas_sandbox_token"
    assert encrypted.startswith("enc:v1:")
    assert "runtime-cookie-secret" not in encrypted
    assert decrypt_runtime_cookie(encrypted) == "runtime-cookie-secret"

    with pytest.raises(ValueError) as exc_info:
        decrypt_runtime_cookie("enc:v1:not-a-valid-fernet-token")
    assert "not-a-valid-fernet-token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_bootstrap_runtime_session_uses_entry_token_only_upstream_and_returns_cookie_metadata():
    import hashlib
    from datetime import datetime, timezone

    import httpx

    from app.code_runtime.sandbox_auth import bootstrap_runtime_session

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://sandbox.example.com/workspaces/ws-1/api/status?token=entry-secret"
        )
        return httpx.Response(
            200,
            headers={
                "set-cookie": (
                    "apaas_sandbox_token=runtime-cookie-secret; Max-Age=120; Path=/; HttpOnly"
                ),
            },
        )

    transport = httpx.MockTransport(handler)
    bootstrap = await bootstrap_runtime_session(
        "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret&handoffId=h1",
        client_factory=lambda: httpx.AsyncClient(transport=transport),
    )

    assert bootstrap.clean_builder_url == (
        "https://sandbox.example.com/workspaces/ws-1/builder?handoffId=h1"
    )
    assert bootstrap.runtime_base_url == "https://sandbox.example.com/workspaces/ws-1"
    assert bootstrap.runtime_cookie == "runtime-cookie-secret"
    assert bootstrap.runtime_cookie_hash == hashlib.sha256(
        b"runtime-cookie-secret"
    ).hexdigest()
    assert bootstrap.expires_at is not None
    assert bootstrap.expires_at > datetime.now(timezone.utc)
    assert "entry-secret" not in repr(bootstrap)
    assert "runtime-cookie-secret" not in repr(bootstrap)


@pytest.mark.asyncio
async def test_bootstrap_runtime_session_uses_control_plane_internal_runtime_url():
    import httpx

    from app.code_runtime.sandbox_auth import bootstrap_runtime_session

    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"set-cookie": "apaas_sandbox_token=runtime-cookie; Path=/"},
        )

    bootstrap = await bootstrap_runtime_session(
        "https://public.example.test/workspaces/ws-1/builder?token=entry-secret",
        runtime_base_url="http://runtime-1.dolphin-code.svc.cluster.local:8080",
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )

    assert requested_urls == [
        "http://runtime-1.dolphin-code.svc.cluster.local:8080/api/status?token=entry-secret"
    ]
    assert bootstrap.clean_builder_url == (
        "https://public.example.test/workspaces/ws-1/builder"
    )
    assert bootstrap.runtime_base_url == (
        "http://runtime-1.dolphin-code.svc.cluster.local:8080"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_runtime_base_url",
    [
        "ftp://runtime.internal:8080",
        "http://user:password@runtime.internal:8080",
        "http://runtime.internal:8080?token=secret",
        "http://runtime.internal:8080#fragment",
    ],
)
async def test_bootstrap_runtime_session_falls_back_from_invalid_internal_url(
    invalid_runtime_base_url,
):
    import httpx

    from app.code_runtime.sandbox_auth import bootstrap_runtime_session

    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"set-cookie": "apaas_sandbox_token=runtime-cookie; Path=/"},
        )

    await bootstrap_runtime_session(
        "https://public.example.test/workspaces/ws-1/builder?token=entry-secret",
        runtime_base_url=invalid_runtime_base_url,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )

    assert requested_urls == [
        "https://public.example.test/workspaces/ws-1/api/status?token=entry-secret"
    ]


@pytest.mark.asyncio
async def test_bootstrap_runtime_session_rejects_success_without_runtime_cookie():
    import httpx
    from fastapi import HTTPException

    from app.code_runtime.sandbox_auth import bootstrap_runtime_session

    request_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with pytest.raises(HTTPException) as exc_info:
        await bootstrap_runtime_session(
            "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret",
            client_factory=lambda: httpx.AsyncClient(transport=transport),
        )

    assert request_urls == [
        "https://sandbox.example.com/workspaces/ws-1/api/status?token=entry-secret",
    ]
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Runtime bootstrap response missing session cookie"


def test_runtime_session_expiry_for_storage_normalizes_aware_datetime_to_naive_utc():
    from datetime import datetime, timedelta, timezone

    from app.code_runtime.sandbox_auth import runtime_session_expiry_for_storage

    expires_at = datetime(
        2026,
        7,
        20,
        17,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert runtime_session_expiry_for_storage(expires_at) == datetime(
        2026,
        7,
        20,
        9,
        30,
    )


def test_runtime_session_expiry_for_storage_preserves_none_and_naive_datetime():
    from datetime import datetime

    from app.code_runtime.sandbox_auth import runtime_session_expiry_for_storage

    expires_at = datetime(2026, 7, 20, 9, 30)

    assert runtime_session_expiry_for_storage(None) is None
    assert runtime_session_expiry_for_storage(expires_at) is expires_at


@pytest.mark.asyncio
async def test_bootstrap_runtime_session_classifies_only_stable_launch_auth_errors_without_secret_leaks():
    import httpx
    from fastapi import HTTPException

    from app.code_runtime.sandbox_auth import bootstrap_runtime_session

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_launch_token_expired"},
        )

    with pytest.raises(HTTPException) as exc_info:
        await bootstrap_runtime_session(
            "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret",
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {
        "X-APAAS-Sandbox-Auth-Error": "sandbox_launch_token_expired"
    }
    assert "entry-secret" not in str(exc_info.value.detail)


def test_legacy_code_session_public_id_is_stable_across_concurrent_loads():
    from app.code_runtime.service import ensure_code_session_public_id

    first = AIChatSession(id=23)
    second = AIChatSession(id=23)

    assert ensure_code_session_public_id(first) == ensure_code_session_public_id(second)


def test_strip_dolphin_token_keeps_runtime_token_query():
    from app.code_runtime.service import strip_dolphin_token_from_url

    assert strip_dolphin_token_from_url(
        "http://test/api/code-runtime/12/builder?token=entry&dolphin_token=embed&handoffId=h1"
    ) == "http://test/api/code-runtime/12/builder?token=entry&handoffId=h1"


@pytest.mark.asyncio
async def test_open_code_session_upserts_runtime_binding(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeBinding

    app = Application(
        id=101,
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="销售应用",
        app_code="sales",
        app_type="ai-code",
        status="completed",
        apaas_app_id="91001",
    )
    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=101,
        title="销售应用 Code",
        mode="code",
        status="active",
    )
    db_session.add_all([app, session])
    await db_session.commit()
    await db_session.refresh(session)

    calls: list[str] = []

    async def fake_open(external_application_id: str, handoff_id: str | None = None):
        calls.append(external_application_id)
        return {
            "applicationId": external_application_id,
            "workspaceId": "93001",
            "sandboxInstanceId": "sandbox-93001",
            "conversationId": "conversation-93001",
            "specReviewUrl": "https://sandbox.example.com/workspaces/93001/builder?token=entry-token",
            "runtimeBaseUrl": "http://om-agent-runtime-93001.dolphin-code.svc.cluster.local:8080",
            "handoff": {"handoffId": handoff_id or "handoff-1", "status": "accepted"},
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    assert calls == ["91001"]
    assert result["session_id"] == session.public_id
    assert result["route_id"] == "s1"
    assert result["external_base_path"] == "/api/code-runtime/s1"
    assert result["embed_url"].startswith("/api/code-runtime/s1/builder/?")
    assert "dolphin_token=dolphin-embed" in result["embed_url"]

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.external_application_id == "91001"
    assert binding.workspace_id == "93001"
    assert binding.sandbox_instance_id == "sandbox-93001"
    assert binding.runtime_base_url == (
        "http://om-agent-runtime-93001.dolphin-code.svc.cluster.local:8080"
    )
    assert "runtimeBaseUrl" not in result
    assert "svc.cluster.local" not in repr(result)
    assert "entry-token" not in repr(result)


@pytest.mark.asyncio
async def test_open_local_code_session_uses_desktop_runtime_without_control_plane(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="local-desktop-app",
        title="Local Desktop Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    manager_calls = 0

    class FakeLocalRuntimeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        async def open_application_with_entry_token(self, _db, _session, _ctx, **_kwargs):
            nonlocal manager_calls
            manager_calls += 1
            return (
                {
                    "applicationId": "local-desktop-app",
                    "workspaceId": "workspace-local",
                    "sandboxInstanceId": "local-instance",
                    "conversationId": "",
                    "runtimeBaseUrl": "http://127.0.0.1:19090",
                    "specReviewUrl": "http://127.0.0.1:19090/builder/",
                },
                "desktop-entry-token",
            )

    async def unexpected_control_plane(*_args, **_kwargs):
        raise AssertionError("local application must not call Control Plane")

    monkeypatch.setattr(service, "LocalRuntimeClient", FakeLocalRuntimeClient)
    monkeypatch.setattr(
        service,
        "verify_control_plane_application_access",
        unexpected_control_plane,
    )

    async def create_runtime_agent_session(*_args):
        return "local-runtime-session"

    monkeypatch.setattr(
        service,
        "_create_desktop_runtime_agent_session",
        create_runtime_agent_session,
    )

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
        workspace_open=unexpected_control_plane,
    )

    assert manager_calls == 1
    assert result["external_application_id"] == "local-desktop-app"
    assert result["runtime_session_id"] == "local-runtime-session"


@pytest.mark.asyncio
async def test_open_code_session_prefers_configured_desktop_runtime_and_keeps_entry_token_private(
    db_session,
    monkeypatch,
):
    from sqlalchemy import select

    from app.code_runtime import service
    from app.code_runtime.sandbox_auth import decrypt_runtime_cookie
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeAgentSession, CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="local-desktop-code-app",
        title="Desktop Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    entry_token = "desktop-entry-token-secret"
    opened_calls = 0
    bootstrap_calls = 0
    provider_options_seen = None

    class FakeLocalRuntimeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        async def open_application_with_entry_token(
            self,
            _db,
            _session,
            _ctx,
            *,
            provider_options=None,
        ):
            nonlocal opened_calls, provider_options_seen
            opened_calls += 1
            provider_options_seen = provider_options
            return (
                {
                    "applicationId": "local-desktop-code-app",
                    "workspaceId": "workspace-desktop",
                    "sandboxInstanceId": "desktop-instance",
                    "conversationId": "",
                    "runtimeBaseUrl": "http://127.0.0.1:19090",
                    "specReviewUrl": "http://127.0.0.1:19090/builder/",
                },
                entry_token,
            )

    async def unexpected_bootstrap(_builder_url: str):
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        raise AssertionError("desktop runtime must not bootstrap a control-plane session")

    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL", "http://127.0.0.1:9988")
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN", "manager-token")
    monkeypatch.setenv("DOLPHIN_DESKTOP_DATA_DIR", "/tmp/desktop-data")
    monkeypatch.setenv("DOLPHIN_AGENT_RUNTIME_PATH", "/tmp/agent-runtime")
    monkeypatch.setattr(service, "LocalRuntimeClient", FakeLocalRuntimeClient)
    monkeypatch.setattr(service, "bootstrap_runtime_session", unexpected_bootstrap)
    async def unexpected_control_plane(*_args, **_kwargs):
        raise AssertionError("local application must not call Control Plane")

    monkeypatch.setattr(
        service,
        "verify_control_plane_application_access",
        unexpected_control_plane,
    )
    created_with: list[tuple[str, str]] = []

    async def fake_create_agent_session(runtime_base_url: str, token: str) -> str:
        created_with.append((runtime_base_url, token))
        return "desktop-runtime-session-1"

    monkeypatch.setattr(
        service,
        "_create_desktop_runtime_agent_session",
        fake_create_agent_session,
    )

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(
            user=SimpleNamespace(id=11),
            tenant_id=7,
            control_plane_tenant_id="tenant-cp",
        ),
        authorization_header="Bearer control-plane-user-token",
        workspace_open=lambda *_args: (_ for _ in ()).throw(
            AssertionError("desktop runtime must not use Control Plane")
        ),
    )
    await db_session.commit()

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert opened_calls == 1
    assert provider_options_seen["control_plane_url"] == service.control_plane_base_url()
    assert provider_options_seen["control_plane_authorization"] == "Bearer control-plane-user-token"
    assert provider_options_seen["control_plane_tenant_id"] == "tenant-cp"
    assert provider_options_seen["local_proxy_url"].endswith(
        "/api/code/model-proxy/local-desktop-code-app/v1"
    )
    assert provider_options_seen["cache_dir"] == "/tmp/desktop-data/model-catalog-cache"
    assert bootstrap_calls == 0
    assert binding.execution_target == "desktop_agent_runtime"
    assert binding.runtime_session_id == "desktop-runtime-session-1"
    assert hashlib.sha256(
        decrypt_runtime_cookie(binding.desktop_agent_runtime_token_enc).encode("ascii")
    ).digest() == hashlib.sha256(entry_token.encode("ascii")).digest()
    assert created_with == [("http://127.0.0.1:19090", entry_token)]
    ownership = (
        await db_session.execute(
            select(CodeRuntimeAgentSession).where(
                CodeRuntimeAgentSession.session_id == session.id,
                CodeRuntimeAgentSession.runtime_session_id == "desktop-runtime-session-1",
            )
        )
    ).scalar_one()
    assert ownership.conversation_id is None
    if entry_token in repr(result):
        pytest.fail("desktop runtime entry token leaked into public response")
    assert "desktop_agent_runtime_token_enc" not in result


@pytest.mark.asyncio
async def test_desktop_runtime_creates_one_agent_session_per_shell_and_reuses_it(
    db_session,
    monkeypatch,
):
    from sqlalchemy import select

    from app.code_runtime import service
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeAgentSession, CodeRuntimeBinding

    first = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="local-desktop-code-app",
        title="Desktop Code 1",
        mode="code",
        status="active",
    )
    second = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="local-desktop-code-app",
        title="Desktop Code 2",
        mode="code",
        status="active",
    )
    db_session.add_all([first, second])
    await db_session.commit()
    provider_options_seen: list[dict[str, object]] = []

    class FakeLocalRuntimeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        async def open_application_with_entry_token(self, _db, _session, _ctx, **kwargs):
            provider_options_seen.append(kwargs["provider_options"])
            return (
                {
                    "applicationId": "local-desktop-code-app",
                    "workspaceId": "workspace-desktop",
                    "sandboxInstanceId": "desktop-instance",
                    "conversationId": "",
                    "runtimeBaseUrl": "http://127.0.0.1:19090",
                    "specReviewUrl": "http://127.0.0.1:19090/builder/",
                },
                "desktop-entry-token",
            )

    created: list[str] = []

    async def fake_create_agent_session(_runtime_base_url: str, _token: str) -> str:
        runtime_session_id = f"desktop-runtime-session-{len(created) + 1}"
        created.append(runtime_session_id)
        return runtime_session_id

    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL", "http://127.0.0.1:9988")
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN", "manager-token")
    monkeypatch.setenv("DOLPHIN_DESKTOP_DATA_DIR", "/tmp/desktop-data")
    monkeypatch.setenv("DOLPHIN_AGENT_RUNTIME_PATH", "/tmp/agent-runtime")
    monkeypatch.setattr(service, "LocalRuntimeClient", FakeLocalRuntimeClient)

    async def unexpected_control_plane(*_args, **_kwargs):
        raise AssertionError("local application must not call Control Plane")

    monkeypatch.setattr(
        service,
        "verify_control_plane_application_access",
        unexpected_control_plane,
    )
    monkeypatch.setattr(
        service,
        "_create_desktop_runtime_agent_session",
        fake_create_agent_session,
    )

    first_open = await open_code_session(
        db=db_session,
        session_id=first.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
    )
    second_open = await open_code_session(
        db=db_session,
        session_id=second.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
    )
    reopened_first = await open_code_session(
        db=db_session,
        session_id=first.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
    )
    await db_session.commit()

    assert created == ["desktop-runtime-session-1", "desktop-runtime-session-2"]
    assert len({options["local_proxy_url"] for options in provider_options_seen}) == 1
    assert len({options["local_proxy_token"] for options in provider_options_seen}) == 1
    assert first_open["runtime_session_id"] == "desktop-runtime-session-1"
    assert second_open["runtime_session_id"] == "desktop-runtime-session-2"
    assert reopened_first["runtime_session_id"] == "desktop-runtime-session-1"
    ownership = (
        await db_session.execute(
            select(CodeRuntimeAgentSession).order_by(CodeRuntimeAgentSession.session_id)
        )
    ).scalars().all()
    assert [(record.session_id, record.runtime_session_id) for record in ownership] == [
        (first.id, "desktop-runtime-session-1"),
        (second.id, "desktop-runtime-session-2"),
    ]
    bindings = (
        await db_session.execute(
            select(CodeRuntimeBinding).order_by(CodeRuntimeBinding.session_id)
        )
    ).scalars().all()
    assert [(binding.session_id, binding.runtime_session_id) for binding in bindings] == [
        (first.id, "desktop-runtime-session-1"),
        (second.id, "desktop-runtime-session-2"),
    ]


@pytest.mark.asyncio
async def test_open_code_session_does_not_fallback_when_configured_desktop_runtime_fails(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="local-desktop-code-app",
        title="Desktop Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    control_plane_calls = 0

    class FailingLocalRuntimeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        async def open_application_with_entry_token(self, _db, _session, _ctx, **_kwargs):
            raise HTTPException(status_code=503, detail="LOCAL_RUNTIME_MANAGER_UNAVAILABLE: unavailable")

    async def unexpected_control_plane(*_args, **_kwargs):
        nonlocal control_plane_calls
        control_plane_calls += 1
        raise AssertionError("desktop failure must not fall back")

    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL", "http://127.0.0.1:9988")
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN", "manager-token")
    monkeypatch.setenv("DOLPHIN_DESKTOP_DATA_DIR", "/tmp/desktop-data")
    monkeypatch.setenv("DOLPHIN_AGENT_RUNTIME_PATH", "/tmp/agent-runtime")
    monkeypatch.setattr(service, "LocalRuntimeClient", FailingLocalRuntimeClient)
    monkeypatch.setattr(service, "default_workspace_open", unexpected_control_plane)

    async def unexpected_application_check(*_args, **_kwargs):
        raise AssertionError("local application must not call Control Plane")

    monkeypatch.setattr(
        service,
        "verify_control_plane_application_access",
        unexpected_application_check,
    )

    with pytest.raises(HTTPException, match="LOCAL_RUNTIME_MANAGER_UNAVAILABLE") as exc:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
        )

    assert exc.value.status_code == 503
    assert control_plane_calls == 0


@pytest.mark.asyncio
async def test_remote_code_session_uses_control_plane_even_when_desktop_runtime_is_configured(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="desktop-code-app",
        title="Desktop Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()

    class UnexpectedLocalRuntimeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        async def open_application_with_entry_token(self, *_args):
            raise AssertionError("local runtime must not start before application authorization")

    async def denied(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Tenant is not accessible")

    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL", "http://127.0.0.1:9988")
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN", "manager-token")
    monkeypatch.setenv("DOLPHIN_DESKTOP_DATA_DIR", "/tmp/desktop-data")
    monkeypatch.setenv("DOLPHIN_AGENT_RUNTIME_PATH", "/tmp/agent-runtime")
    monkeypatch.setattr(service, "LocalRuntimeClient", UnexpectedLocalRuntimeClient)

    with pytest.raises(HTTPException, match="Tenant is not accessible") as exc:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
            authorization_header="Bearer user-token",
            workspace_open=denied,
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_open_code_session_uses_control_plane_when_desktop_manager_is_not_configured(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-1",
        title="Control plane Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    calls = 0

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        nonlocal calls
        calls += 1
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    for key in (
        "DOLPHIN_LOCAL_RUNTIME_MANAGER_URL",
        "DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN",
        "DOLPHIN_DESKTOP_DATA_DIR",
        "DOLPHIN_AGENT_RUNTIME_PATH",
    ):
        monkeypatch.delenv(key, raising=False)

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7),
        workspace_open=fake_open,
    )

    assert calls == 1
    assert result["external_application_id"] == "code-app-1"


@pytest.mark.asyncio
async def test_open_code_session_bootstraps_token_free_binding_and_new_browser_session(
    db_session,
    monkeypatch,
):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.code_runtime import service
    from app.code_runtime.sandbox_auth import (
        RuntimeBootstrap,
        decrypt_runtime_cookie,
        encrypt_runtime_cookie,
    )
    from app.code_runtime.service import open_code_session, validate_embed_token
    from app.models.ai_chat import CodeRuntimeBinding, CodeRuntimeBrowserSession

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-1",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()

    bootstrap_urls: list[str] = []

    async def fake_bootstrap(builder_url: str):
        bootstrap_urls.append(builder_url)
        return RuntimeBootstrap(
            clean_builder_url=(
                "https://sandbox.example.com/workspaces/ws-1/builder?handoffId=h1"
            ),
            runtime_base_url="https://sandbox.example.com/workspaces/ws-1",
            runtime_cookie="runtime-cookie-secret",
            runtime_cookie_hash="a" * 64,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": (
                "https://sandbox.example.com/workspaces/ws-1/builder"
                "?token=entry-secret&handoffId=h1"
            ),
        }

    monkeypatch.setattr(service, "bootstrap_runtime_session", fake_bootstrap)
    ctx = SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member")
    first = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=ctx,
        workspace_open=fake_open,
    )
    await db_session.commit()
    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    binding.desktop_agent_runtime_token_enc = encrypt_runtime_cookie(
        "desktop-agent-runtime-token-secret"
    )
    await db_session.commit()
    second = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=ctx,
        workspace_open=fake_open,
    )
    await db_session.commit()

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    browser_rows = (
        await db_session.execute(
            select(CodeRuntimeBrowserSession)
            .where(CodeRuntimeBrowserSession.binding_id == binding.id)
            .order_by(CodeRuntimeBrowserSession.generation)
        )
    ).scalars().all()

    assert bootstrap_urls == [
        "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret&handoffId=h1",
        "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret&handoffId=h1",
    ]
    assert binding.builder_url == (
        "https://sandbox.example.com/workspaces/ws-1/builder?handoffId=h1"
    )
    assert "entry-secret" not in binding.builder_url
    assert decrypt_runtime_cookie(binding.runtime_service_session_enc) == "runtime-cookie-secret"
    assert decrypt_runtime_cookie(binding.desktop_agent_runtime_token_enc) == (
        "desktop-agent-runtime-token-secret"
    )
    assert binding.auth_generation == 2
    assert len(browser_rows) == 2
    assert len({row.browser_session_id for row in browser_rows}) == 2
    assert all(0 < len(row.browser_session_id) <= 64 for row in browser_rows)
    assert all(
        decrypt_runtime_cookie(row.runtime_session_cookie_enc) == "runtime-cookie-secret"
        for row in browser_rows
    )
    assert [row.runtime_session_hash for row in browser_rows] == ["a" * 64, "a" * 64]
    assert [row.generation for row in browser_rows] == [1, 2]
    assert "entry-secret" not in first["embed_url"]
    assert "runtime-cookie-secret" not in first["embed_url"]
    assert "desktop_agent_runtime_token_enc" not in second
    assert "desktop-agent-runtime-token-secret" not in repr(second)
    first_token = dict(parse_qsl(urlsplit(first["embed_url"]).query))["dolphin_token"]
    validate_embed_token(
        first_token,
        session_id=session.public_id,
        browser_session_id=browser_rows[0].browser_session_id,
    )
    with pytest.raises(HTTPException):
        validate_embed_token(
            first_token,
            session_id=session.public_id,
            browser_session_id=browser_rows[1].browser_session_id,
        )
    assert "entry-secret" not in repr(first)
    assert "runtime-cookie-secret" not in repr(second)


@pytest.mark.asyncio
async def test_open_code_session_reopens_once_after_expired_launch_token(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-1",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    opens = 0
    bootstraps = 0

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        nonlocal opens
        opens += 1
        return {
            "workspaceId": f"ws-{opens}",
            "specReviewUrl": (
                f"https://sandbox.example.com/workspaces/ws-{opens}/builder?token=entry-{opens}"
            ),
        }

    async def fake_bootstrap(builder_url: str):
        from app.code_runtime.sandbox_auth import RuntimeBootstrap

        nonlocal bootstraps
        bootstraps += 1
        if bootstraps == 1:
            raise HTTPException(
                status_code=401,
                detail="Runtime launch authorization expired",
                headers={"X-APAAS-Sandbox-Auth-Error": "sandbox_launch_token_expired"},
            )
        return RuntimeBootstrap(
            clean_builder_url="https://sandbox.example.com/workspaces/ws-2/builder",
            runtime_base_url="https://sandbox.example.com/workspaces/ws-2",
            runtime_cookie="runtime-cookie",
            runtime_cookie_hash="b" * 64,
            expires_at=None,
        )

    monkeypatch.setattr(service, "bootstrap_runtime_session", fake_bootstrap)
    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
    )

    assert opens == 2
    assert bootstraps == 2
    assert "entry-2" not in result["embed_url"]


@pytest.mark.asyncio
async def test_workspace_token_open_verifies_user_application_access_first(monkeypatch):
    from app.code_runtime import service
    events: list[str] = []

    async def verify_access(external_application_id: str, **kwargs):
        assert external_application_id == "code-app-1"
        assert kwargs["authorization_header"] == "Bearer user-token"
        assert kwargs["delegated_context"].tenant_id == 7
        events.append("verify")

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"specReviewUrl": "https://sandbox.example.com/builder?token=entry"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            events.append("open")
            return FakeResponse()

    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_URL", "https://coordinator.example.com")
    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "workspace-token")
    monkeypatch.setattr(service, "verify_control_plane_application_access", verify_access)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    await service.default_workspace_open(
        "code-app-1",
        authorization_header="Bearer user-token",
        delegated_context=SimpleNamespace(tenant_id=7),
    )

    assert events == ["verify", "open"]


@pytest.mark.asyncio
async def test_workspace_token_open_requires_user_bearer(monkeypatch):
    from app.code_runtime import service

    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_URL", "https://coordinator.example.com")
    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "workspace-token")

    with pytest.raises(HTTPException) as exc_info:
        await service.default_workspace_open("code-app-1")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Code workspace 用户鉴权不可用"


@pytest.mark.asyncio
async def test_workspace_token_rejection_is_coordinator_failure(monkeypatch):
    from app.code_runtime import service

    class FakeResponse:
        status_code = 401
        text = "invalid coordinator token"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    async def allow_application_access(*_args, **_kwargs):
        return None

    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_URL", "https://coordinator.example.com")
    monkeypatch.setenv("DOLPHIN_CODE_WORKSPACE_OPEN_TOKEN", "workspace-token")
    monkeypatch.setattr(
        service,
        "verify_control_plane_application_access",
        allow_application_access,
    )
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException) as exc_info:
        await service.default_workspace_open(
            "code-app-1",
            authorization_header="Bearer user-token",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Code workspace coordinator 鉴权失败"


@pytest.mark.asyncio
async def test_open_code_session_does_not_retry_invalid_launch_token(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-1",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    opens = 0
    bootstraps = 0
    canary = "invalid-launch-token-canary"

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        nonlocal opens
        opens += 1
        return {
            "workspaceId": "ws-1",
            "specReviewUrl": (
                f"https://sandbox.example.com/workspaces/ws-1/builder?token={canary}"
            ),
        }

    async def fake_bootstrap(_builder_url: str):
        nonlocal bootstraps
        bootstraps += 1
        raise HTTPException(
            status_code=401,
            detail="Runtime launch authorization invalid",
            headers={
                "X-APAAS-Sandbox-Auth-Error": "sandbox_launch_token_invalid",
            },
        )

    monkeypatch.setattr(service, "bootstrap_runtime_session", fake_bootstrap)

    with pytest.raises(HTTPException) as exc_info:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
            workspace_open=fake_open,
        )

    assert opens == 1
    assert bootstraps == 1
    assert canary not in str(exc_info.value)
    assert canary not in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_open_code_session_uses_external_code_application_without_local_app(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    calls: list[str] = []

    async def fake_open(external_application_id: str, handoff_id: str | None = None):
        calls.append(external_application_id)
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    assert calls == ["code-app-1"]
    assert result["app_id"] is None
    assert result["external_application_id"] == "code-app-1"

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.app_id is None
    assert binding.external_application_id == "code-app-1"


@pytest.mark.asyncio
async def test_open_code_session_preserves_current_runtime_session_when_open_omits_runtime_id(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-1",
        runtime_base_url="https://old.example.com/workspaces/ws-1",
        builder_url="https://old.example.com/workspaces/ws-1/builder",
        runtime_session_id="runtime-current",
        status="ready",
    ))
    await db_session.commit()
    await db_session.refresh(session)

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.runtime_session_id == "runtime-current"
    assert result["runtime_session_id"] == "runtime-current"


@pytest.mark.asyncio
async def test_open_code_session_preserves_scoped_runtime_session_when_open_returns_default(db_session):
    from sqlalchemy import select
    from app.code_runtime.service import open_code_session
    from app.models.ai_chat import CodeRuntimeAgentSession, CodeRuntimeBinding

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()
    db_session.add(CodeRuntimeBinding(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-1",
        runtime_base_url="https://old.example.com/workspaces/ws-1",
        builder_url="https://old.example.com/workspaces/ws-1/builder",
        runtime_session_id="runtime-selected",
        status="ready",
    ))
    db_session.add(CodeRuntimeAgentSession(
        tenant_id=7,
        user_id=11,
        session_id=session.id,
        external_application_id="code-app-1",
        runtime_session_id="runtime-selected",
    ))
    await db_session.commit()
    await db_session.refresh(session)

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "runtimeSessionId": "runtime-default",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    result = await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
        workspace_open=fake_open,
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    binding = (
        await db_session.execute(
            select(CodeRuntimeBinding).where(CodeRuntimeBinding.session_id == session.id)
        )
    ).scalar_one()
    assert binding.runtime_session_id == "runtime-selected"
    assert result["runtime_session_id"] == "runtime-selected"


@pytest.mark.asyncio
async def test_open_code_session_passes_auth_context_to_control_plane_open(db_session, monkeypatch):
    from app.code_runtime import service
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=None,
        external_application_id="code-app-1",
        external_app_name="客户门户",
        external_app_code="crm_portal",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    captured: dict = {}

    async def fake_default_workspace_open(
        external_application_id: str,
        handoff_id: str | None = None,
        *,
        authorization_header: str | None = None,
        delegated_context=None,
        shell_session_id: int | None = None,
        auth_provider: str | None = None,
    ):
        captured.update({
            "external_application_id": external_application_id,
            "handoff_id": handoff_id,
            "authorization_header": authorization_header,
            "delegated_context": delegated_context,
            "shell_session_id": shell_session_id,
            "auth_provider": auth_provider,
        })
        return {
            "workspaceId": "ws-1",
            "sandboxInstanceId": "sandbox-1",
            "specReviewUrl": "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-token",
        }

    monkeypatch.setattr(service, "default_workspace_open", fake_default_workspace_open)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=11, username="admin", display_name="管理员"),
        tenant_id=7,
        tenant_role="platform_admin",
        apaas_user_id="100169876816012509184",
        apaas_tenant_id="844246516607483905",
    )

    await open_code_session(
        db=db_session,
        session_id=session.id,
        ctx=ctx,
        authorization_header="Bearer user-token",
        embed_token_factory=lambda **_: "dolphin-embed",
    )

    assert captured["external_application_id"] == "code-app-1"
    assert captured["authorization_header"] == "Bearer user-token"
    assert captured["delegated_context"] is ctx
    assert captured["shell_session_id"] == session.id
    assert captured["auth_provider"] is None


@pytest.mark.asyncio
async def test_open_code_session_rejects_low_code_app(db_session):
    from fastapi import HTTPException
    from app.code_runtime.service import open_code_session

    app = Application(
        id=101,
        tenant_id=7,
        user_id=11,
        created_by=11,
        app_name="低代码应用",
        app_code="lowcode",
        app_type="low-code",
        status="completed",
    )
    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        app_id=101,
        title="低代码应用 Code",
        mode="code",
        status="active",
    )
    db_session.add_all([app, session])
    await db_session.commit()
    await db_session.refresh(session)

    with pytest.raises(HTTPException) as exc:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
            workspace_open=lambda *_args, **_kwargs: None,
        )

    assert exc.value.status_code == 400
    assert "Code" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_open_code_session_rejects_non_code_session(db_session):
    from fastapi import HTTPException
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        title="Builder",
        mode="chat",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    with pytest.raises(HTTPException) as exc:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(user=SimpleNamespace(id=11), tenant_id=7, tenant_role="member"),
            workspace_open=lambda *_args, **_kwargs: None,
        )

    assert exc.value.status_code == 400
@pytest.mark.parametrize(
    ("session_id", "route_id"),
    [(1, "s1"), (35, "sz"), (36, "s10"), (123, "s3f")],
)
def test_code_session_route_id_round_trips(session_id, route_id):
    from app.code_runtime.service import code_session_route_id, decode_code_session_route_id

    assert code_session_route_id(session_id) == route_id
    assert decode_code_session_route_id(route_id) == session_id


@pytest.mark.parametrize("route_id", ["", "s", "s0", "s01", "S3F", "s-1", "s2147483648"])
def test_code_session_route_id_rejects_noncanonical_values(route_id):
    from app.code_runtime.service import decode_code_session_route_id

    assert decode_code_session_route_id(route_id) is None


@pytest.mark.asyncio
async def test_short_code_route_rejects_another_control_plane_tenant(db_session):
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=0,
        control_plane_tenant_id="cp-tenant-a",
        user_id=11,
        title="Tenant A Code",
        mode="code",
        status="active",
        external_application_id="crm",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    ctx = SimpleNamespace(
        tenant_id=0,
        control_plane_tenant_id="cp-tenant-b",
        user=SimpleNamespace(id=11, account_source="control_plane"),
    )
    with pytest.raises(HTTPException, match="Code 会话不存在"):
        await open_code_session(
            db=db_session,
            session_id="s1",
            ctx=ctx,
            workspace_open=lambda *_args: pytest.fail("must not open another tenant workspace"),
        )


def test_local_application_location_normalizes_identity_and_availability(tmp_path):
    from app.code_runtime.application_locations import (
        build_local_application_location,
        local_location_id,
        local_workspace_availability,
        normalize_local_workspace_path,
    )

    workspace = tmp_path / "sales" / "workspace"
    workspace.mkdir(parents=True)
    alternate_path = workspace.parent / "." / workspace.name
    missing_path = tmp_path / "sales" / "missing"

    normalized = str(workspace.resolve())
    assert normalize_local_workspace_path(alternate_path) == normalized
    assert local_location_id(alternate_path) == local_location_id(workspace)
    assert local_workspace_availability(workspace) == "ready"
    assert local_workspace_availability(missing_path) == "missing"
    assert build_local_application_location(
        workspace_id="workspace-7",
        workspace_path=alternate_path,
    ) == {
        "location": "local",
        "location_id": local_location_id(workspace),
        "availability": "ready",
        "workspace_id": "workspace-7",
        "workspace_path": normalized,
        "environment_name": None,
    }


@pytest.mark.asyncio
async def test_legacy_code_session_derives_location_and_backfills_on_write(db_session):
    from app.code_runtime.session_location import (
        backfill_session_location,
        derive_session_location,
    )

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="local-sales",
        title="Legacy local session",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()

    assert derive_session_location(session) == {
        "execution_location": "local",
        "logical_application_id": "legacy:local-sales",
    }
    assert backfill_session_location(session) == {
        "execution_location": "local",
        "logical_application_id": "legacy:local-sales",
    }
    assert session.execution_location == "local"
    assert session.logical_application_id == "legacy:local-sales"

    session_id = session.id
    await db_session.commit()
    db_session.expire_all()
    stored = await db_session.get(AIChatSession, session_id)
    assert stored is not None
    assert stored.execution_location == "local"
    assert stored.logical_application_id == "legacy:local-sales"
