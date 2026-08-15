from app import database
from app import application_member_role_migration as role_migration
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable


def test_ai_chat_public_id_has_startup_migration():
    import inspect

    from app.models.ai_chat import AIChatSession

    column = AIChatSession.__table__.columns["public_id"]
    assert column.nullable is True
    assert "ALTER TABLE ai_chat_sessions ADD COLUMN public_id" in inspect.getsource(database.init_db)


def test_postgresql_schema_statement_uses_supported_types_and_alter_syntax():
    assert database._schema_statement_for_dialect(
        "ALTER TABLE platform_envs ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "postgresql",
    ) == (
        "ALTER TABLE platform_envs ADD COLUMN created_at "
        "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
    assert database._schema_statement_for_dialect(
        "ALTER TABLE code_runtime_bindings MODIFY COLUMN app_id INTEGER NULL",
        "postgresql",
    ) == "ALTER TABLE code_runtime_bindings ALTER COLUMN app_id DROP NOT NULL"


def test_legacy_code_runtime_agent_session_columns_become_nullable_on_startup():
    import inspect

    source = inspect.getsource(database.init_db)
    legacy_columns = {
        "conversation_id": "VARCHAR(160)",
        "conversation_purpose": "VARCHAR(32)",
        "conversation_purpose_revision": "BIGINT",
        "status": "VARCHAR(32)",
    }

    for column_name, column_type in legacy_columns.items():
        add_statement = (
            "ALTER TABLE code_runtime_agent_sessions "
            f"ADD COLUMN {column_name} {column_type}"
        )
        statement = (
            "ALTER TABLE code_runtime_agent_sessions "
            f"MODIFY COLUMN {column_name} {column_type} NULL"
        )
        assert add_statement in source
        assert source.index(add_statement) < source.index(statement)
        assert database._schema_statement_for_dialect(
            add_statement,
            "postgresql",
        ) == add_statement
        assert statement in source
        assert database._schema_statement_for_dialect(
            statement,
            "postgresql",
        ) == (
            "ALTER TABLE code_runtime_agent_sessions "
            f"ALTER COLUMN {column_name} DROP NOT NULL"
        )


def test_sqlite_agent_session_rebuild_copies_rows_without_ignoring_conflicts():
    import inspect

    source = inspect.getsource(database._migrate_code_runtime_binding_app_id_nullable)
    assert "INSERT OR IGNORE INTO {table_name}" not in source
    assert "archive_row_count" in source
    assert "current_row_count" in source


def test_code_runtime_agent_session_snapshot_has_startup_migrations():
    import inspect

    source = inspect.getsource(database.init_db)
    assert "ALTER TABLE code_runtime_agent_sessions ADD COLUMN title" in source
    assert "ALTER TABLE code_runtime_agent_sessions ADD COLUMN last_active_at" in source
    assert "ALTER TABLE code_runtime_agent_sessions ADD COLUMN codex_session_resumable" in source


def test_postgresql_insert_select_ignores_conflicts_with_on_conflict():
    statement = database._insert_select_ignore_conflicts_sql(
        dialect_name="postgresql",
        target_table="builder_specs",
        columns=["id", "tenant_id"],
        source_table="specs",
    )

    assert statement == (
        "INSERT INTO builder_specs (id, tenant_id) "
        "SELECT id, tenant_id FROM specs ON CONFLICT DO NOTHING"
    )


def test_existing_insert_select_syntax_is_preserved_for_mysql_and_sqlite():
    mysql_statement = database._insert_select_ignore_conflicts_sql(
        dialect_name="mysql",
        target_table="builder_specs",
        columns=["id"],
        source_table="specs",
    )
    sqlite_statement = database._insert_select_ignore_conflicts_sql(
        dialect_name="sqlite",
        target_table="builder_specs",
        columns=["id"],
        source_table="specs",
    )

    assert mysql_statement == (
        "INSERT IGNORE INTO builder_specs (id) SELECT id FROM specs"
    )
    assert sqlite_statement == (
        "INSERT OR IGNORE INTO builder_specs (id) SELECT id FROM specs"
    )


def test_audit_log_schema_compiles_for_supported_database_dialects():
    from app.models.audit_log import AuditLog

    dialects = (sqlite.dialect(), mysql.dialect(), postgresql.dialect())
    for dialect in dialects:
        table_sql = str(CreateTable(AuditLog.__table__).compile(dialect=dialect))
        index_sql = [
            str(CreateIndex(index).compile(dialect=dialect))
            for index in AuditLog.__table__.indexes
        ]

        assert "audit_logs" in table_sql
        assert "tenant_id" in table_sql
        assert "application_id" in table_sql
        assert "before_value" in table_sql
        assert len(index_sql) == 3


def test_standard_audit_log_mysql_migration_normalizes_legacy_member_roles():
    migration = (
        Path(__file__).parents[1] / "scripts" / "migrate_standard_audit_logs.sql"
    ).read_text(encoding="utf-8")

    assert "WHEN role = 'owner' THEN 'owner'" in migration
    assert "WHEN role IN ('maintainer', 'admin') THEN 'admin'" in migration
    assert "WHEN role IN ('contributor', 'viewer', 'member') THEN 'collaborator'" in migration
    assert "MODIFY COLUMN role VARCHAR(20) NOT NULL DEFAULT 'collaborator'" in migration


def test_application_member_role_migration_uses_valid_dialect_defaults():
    mysql_statements = role_migration._migration_statements("mysql")
    postgres_statements = role_migration._migration_statements("postgresql")
    sqlite_statements = role_migration._migration_statements("sqlite")

    assert mysql_statements[-1] == (
        "ALTER TABLE application_members MODIFY COLUMN role "
        "VARCHAR(20) NOT NULL DEFAULT 'collaborator'"
    )
    assert postgres_statements[-1] == (
        "ALTER TABLE application_members ALTER COLUMN role "
        "SET DEFAULT 'collaborator'"
    )
    assert all("ALTER COLUMN" not in statement for statement in sqlite_statements)


@pytest.mark.asyncio
async def test_application_member_role_startup_migration_is_idempotent_on_sqlite():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE application_members ("
                "id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL, "
                "user_id INTEGER NOT NULL, role VARCHAR(20) NOT NULL DEFAULT 'contributor', "
                "invited_by INTEGER NOT NULL, created_at DATETIME, "
                "CONSTRAINT uq_app_member UNIQUE (application_id, user_id), "
                "FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE, "
                "FOREIGN KEY(user_id) REFERENCES users(id), "
                "FOREIGN KEY(invited_by) REFERENCES users(id))"
            ))
            await conn.execute(text(
                "CREATE INDEX idx_app_member_user ON application_members(user_id)"
            ))
            await conn.execute(text(
                "INSERT INTO application_members "
                "(id, application_id, user_id, role, invited_by) VALUES "
                "(1, 1, 1, 'owner', 1), (2, 2, 2, 'maintainer', 2), "
                "(3, 3, 3, 'contributor', 3), (4, 4, 4, 'viewer', 4), "
                "(5, 5, 5, 'member', 5), (6, 6, 6, 'admin', 6), "
                "(7, 7, 7, 'collaborator', 7)"
            ))

            await role_migration.migrate_application_member_roles(conn)
            await role_migration.migrate_application_member_roles(conn)

            roles = list((await conn.execute(text(
                "SELECT role FROM application_members ORDER BY id"
            ))).scalars())
            role_column = next(
                row for row in (await conn.execute(text(
                    "PRAGMA table_info(application_members)"
                ))).mappings() if row["name"] == "role"
            )
            index_rows = list((await conn.execute(text(
                "PRAGMA index_list(application_members)"
            ))).mappings())
            indexes = {row["name"] for row in index_rows}
            foreign_keys = list((await conn.execute(text(
                "PRAGMA foreign_key_list(application_members)"
            ))).mappings())
            await conn.execute(text(
                "INSERT INTO application_members "
                "(id, application_id, user_id, invited_by) VALUES (8, 8, 8, 8)"
            ))
            defaulted_role = await conn.scalar(text(
                "SELECT role FROM application_members WHERE id = 8"
            ))

        assert roles == [
            "owner", "admin", "collaborator", "collaborator",
            "collaborator", "admin", "collaborator",
        ]
        assert role_column["dflt_value"] == "'collaborator'"
        assert defaulted_role == "collaborator"
        assert "idx_app_member_user" in indexes
        assert any(row["origin"] == "u" for row in index_rows)
        assert {row["table"] for row in foreign_keys} == {"applications", "users"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_application_member_role_migration_adds_default_to_legacy_orm_table():
    metadata = MetaData()
    Table("applications", metadata, Column("id", Integer, primary_key=True))
    Table("users", metadata, Column("id", Integer, primary_key=True))
    members = Table(
        "application_members",
        metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "application_id",
            Integer,
            ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
        Column("role", String(20), nullable=False),
        Column("invited_by", Integer, ForeignKey("users.id"), nullable=False),
        UniqueConstraint("application_id", "user_id", name="uq_app_member"),
    )
    Index("idx_app_member_user", members.c.user_id)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.execute(text(
                "INSERT INTO applications (id) VALUES (1), (2)"
            ))
            await conn.execute(text(
                "INSERT INTO users (id) VALUES (1), (2)"
            ))
            await conn.execute(text(
                "INSERT INTO application_members "
                "(id, application_id, user_id, role, invited_by) VALUES "
                "(1, 1, 1, 'owner', 1), (2, 2, 2, 'contributor', 2)"
            ))

            await role_migration.migrate_application_member_roles(conn)
            await role_migration.migrate_application_member_roles(conn)

            role_column = next(
                row for row in (await conn.execute(text(
                    "PRAGMA table_info(application_members)"
                ))).mappings() if row["name"] == "role"
            )
            index_rows = list((await conn.execute(text(
                "PRAGMA index_list(application_members)"
            ))).mappings())
            foreign_keys = list((await conn.execute(text(
                "PRAGMA foreign_key_list(application_members)"
            ))).mappings())
            roles = list((await conn.execute(text(
                "SELECT role FROM application_members ORDER BY id"
            ))).scalars())
            await conn.execute(text(
                "INSERT INTO application_members "
                "(id, application_id, user_id, invited_by) VALUES (3, 1, 2, 1)"
            ))
            defaulted_role = await conn.scalar(text(
                "SELECT role FROM application_members WHERE id = 3"
            ))

        assert roles == ["owner", "collaborator"]
        assert role_column["dflt_value"] == "'collaborator'"
        assert defaulted_role == "collaborator"
        assert "idx_app_member_user" in {row["name"] for row in index_rows}
        assert any(row["origin"] == "u" for row in index_rows)
        assert {row["table"] for row in foreign_keys} == {"applications", "users"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_application_member_role_startup_migration_propagates_failures():
    class FailingConnection:
        class Dialect:
            name = "sqlite"

        dialect = Dialect()

        async def execute(self, _statement):
            raise RuntimeError("role migration failed")

    with pytest.raises(RuntimeError, match="role migration failed"):
        await role_migration.migrate_application_member_roles(FailingConnection())
