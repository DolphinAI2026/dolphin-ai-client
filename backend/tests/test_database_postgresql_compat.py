from app import database


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
        statement = (
            "ALTER TABLE code_runtime_agent_sessions "
            f"MODIFY COLUMN {column_name} {column_type} NULL"
        )
        assert statement in source
        assert database._schema_statement_for_dialect(
            statement,
            "postgresql",
        ) == (
            "ALTER TABLE code_runtime_agent_sessions "
            f"ALTER COLUMN {column_name} DROP NOT NULL"
        )


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
