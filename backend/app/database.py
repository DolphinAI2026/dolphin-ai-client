import logging
import re

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
from app.tenant_public_id import TenantPublicIdStrictError, reconcile_tenant_public_ids


class Base(DeclarativeBase):
    pass


_engine_kwargs = dict(echo=False, future=True)
if not settings.database_url.startswith("sqlite"):
    # pool_pre_ping=True：每次从池里取连接前先发 SELECT 1 探活，
    #   避免 MySQL server 侧 wait_timeout 断开后前端还在用僵尸连接
    #   → "Lost connection to MySQL server during query"
    # pool_recycle=1800：自己主动回收 30 分钟以上的连接（比常见 MySQL
    #   wait_timeout=600 更长时，pre_ping 兜底；两者叠加够稳）
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
    )
    if "+aiomysql" not in settings.database_url:
        _engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(settings.database_url, **_engine_kwargs)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def _schema_statement_for_dialect(statement: str, dialect_name: str) -> str:
    if dialect_name != "postgresql":
        return statement

    statement = re.sub(r"\bDATETIME\b", "TIMESTAMP", statement)
    modify_nullable = re.fullmatch(
        r"ALTER TABLE ([A-Za-z0-9_]+) MODIFY COLUMN ([A-Za-z0-9_]+) .+ NULL",
        statement,
    )
    if modify_nullable:
        table_name, column_name = modify_nullable.groups()
        return f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP NOT NULL"
    return statement


def _insert_select_ignore_conflicts_sql(
    *,
    dialect_name: str,
    target_table: str,
    columns: list[str],
    source_table: str,
) -> str:
    columns_sql = ", ".join(columns)
    if dialect_name == "mysql":
        prefix = "INSERT IGNORE"
        suffix = ""
    elif dialect_name == "sqlite":
        prefix = "INSERT OR IGNORE"
        suffix = ""
    else:
        prefix = "INSERT"
        suffix = " ON CONFLICT DO NOTHING" if dialect_name == "postgresql" else ""
    return (
        f"{prefix} INTO {target_table} ({columns_sql}) "
        f"SELECT {columns_sql} FROM {source_table}{suffix}"
    )


async def _execute_best_effort(conn, statement: str) -> None:
    statement = _schema_statement_for_dialect(statement, conn.dialect.name)
    if conn.dialect.name == "postgresql":
        try:
            async with conn.begin_nested():
                await conn.execute(text(statement))
        except Exception:
            return
    else:
        try:
            await conn.execute(text(statement))
        except Exception:
            return


async def init_db():
    import app.models.tenant  # noqa: F401
    # 确保 extension models 被 Base 注册（create_all 会创建新表）
    import app.harness.models  # noqa: F401
    # 智能开发 V2 - agent 架构相关表（agent_messages / brainstorm_sessions / specs / ...）
    import app.models.agent_models  # noqa: F401
    import app.models.collaboration  # noqa: F401
    import app.models.preference  # noqa: F401
    import app.models.system_setting  # noqa: F401
    import app.models.spec  # noqa: F401
    # 部署历史 + 回滚（2026-05-24）— DeployRecord
    import app.models.deploy_history  # noqa: F401
    # 流程定义 JSON 本地存档（design-v4 H2）— ProcessDefinition
    import app.models.process_definition  # noqa: F401
    # SPEC 版本快照 + markdown 缓存（Y SPEC 版本管理）
    import app.models.spec_applied_version  # noqa: F401
    import app.models.spec_document  # noqa: F401
    import app.models.agent_observability  # noqa: F401  — Agent 可观测底座
    # 代码会话 git 远程仓绑定（2026-06-25）— WorkspaceGitRemote
    import app.models.workspace_git  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        tenant_public_id_result = await reconcile_tenant_public_ids(conn)
        if (
            tenant_public_id_result.null_count
            or tenant_public_id_result.conflict_tenant_ids
            or tenant_public_id_result.invalid_tenant_ids
        ):
            raise TenantPublicIdStrictError(tenant_public_id_result)
        await _migrate_legacy_builder_specs(conn, inspect)
        await conn.run_sync(Base.metadata.create_all)
        # 迁移：确保新列存在（兼容 SQLite 和 MySQL）
        for stmt in [
            "ALTER TABLE applications ADD COLUMN generation_state TEXT",
            "ALTER TABLE conversations ADD COLUMN workspace_id VARCHAR(50)",
            "ALTER TABLE conversations ADD COLUMN selected_llm_config_id INTEGER",
            "ALTER TABLE conversations ADD COLUMN project_id INTEGER",
            "ALTER TABLE users ADD COLUMN display_name VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN apaas_base_url VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN apaas_tenant_id VARCHAR(50)",
            "ALTER TABLE users ADD COLUMN coding_user_id VARCHAR(80)",
            "ALTER TABLE users ADD COLUMN coding_tenant_id VARCHAR(80)",
            "ALTER TABLE users ADD COLUMN coding_base_url VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN coding_access_token TEXT",
            "ALTER TABLE users ADD COLUMN coding_refresh_token TEXT",
            "ALTER TABLE users ADD COLUMN remote_builder_access_token TEXT",
            # Tenant quota/contact columns added after early multi-tenant installs.
            "ALTER TABLE tenants ADD COLUMN max_applications INTEGER NOT NULL DEFAULT 10",
            "ALTER TABLE tenants ADD COLUMN max_workspaces INTEGER NOT NULL DEFAULT 20",
            "ALTER TABLE tenants ADD COLUMN max_components INTEGER NOT NULL DEFAULT 50",
            "ALTER TABLE tenants ADD COLUMN contact_name VARCHAR(64)",
            "ALTER TABLE tenants ADD COLUMN contact_email VARCHAR(128)",
            "ALTER TABLE tenants ADD COLUMN apaas_env_id INTEGER",
            "ALTER TABLE tenants ADD COLUMN apaas_tenant_id_str VARCHAR(40)",
            "ALTER TABLE tenants ADD COLUMN control_plane_tenant_id_str VARCHAR(80)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_control_plane_tenant_id ON tenants(control_plane_tenant_id_str)",
            # PlatformEnv columns added after early installs. Existing dev/prod
            # MySQL tables may predate these fields; login now queries them.
            "ALTER TABLE platform_envs ADD COLUMN alias VARCHAR(50)",
            "ALTER TABLE platform_envs ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE platform_envs ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'disconnected'",
            "ALTER TABLE platform_envs ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE platform_envs ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "CREATE UNIQUE INDEX uq_platform_envs_alias ON platform_envs(alias)",
            # Projects table columns (in case table existed before new columns were added)
            "ALTER TABLE projects ADD COLUMN platform_username VARCHAR(100)",
            "ALTER TABLE projects ADD COLUMN platform_app_name VARCHAR(100)",
            # Document-driven incremental development
            "ALTER TABLE applications ADD COLUMN current_doc_version INTEGER",
            # SPEC / collaboration mode metadata
            "ALTER TABLE applications ADD COLUMN canonical_spec_id VARCHAR(40)",
            "ALTER TABLE conversations ADD COLUMN spec_id VARCHAR(40)",
            "ALTER TABLE applications ADD COLUMN default_mode VARCHAR(20)",
            "ALTER TABLE applications ADD COLUMN git_repo_url VARCHAR(500)",
            "ALTER TABLE applications ADD COLUMN git_provider VARCHAR(20)",
            "ALTER TABLE applications ADD COLUMN git_default_branch VARCHAR(100)",
            # App code for app-mode debug
            "ALTER TABLE projects ADD COLUMN platform_app_code VARCHAR(100)",
            "ALTER TABLE projects ADD COLUMN platform_password_enc TEXT",
            # Document version chain support
            "ALTER TABLE document_versions ADD COLUMN parent_version INTEGER",
            # conversation_id for doc versions created before application exists
            "ALTER TABLE document_versions ADD COLUMN conversation_id INTEGER",
            # Application 合并 Project 平台配置 + conversation_id 改可选
            "ALTER TABLE applications ADD COLUMN project_id INTEGER",
            "ALTER TABLE applications ADD COLUMN platform_url VARCHAR(255)",
            "ALTER TABLE applications ADD COLUMN platform_tenant_id VARCHAR(50)",
            "ALTER TABLE applications ADD COLUMN platform_token TEXT",
            "ALTER TABLE applications ADD COLUMN platform_username VARCHAR(100)",
            "ALTER TABLE applications ADD COLUMN platform_password_enc TEXT",
            "ALTER TABLE applications ADD COLUMN platform_env_id INTEGER",
            "ALTER TABLE applications ADD COLUMN icon_svg TEXT",
            # conversation_id 改为可空（MySQL ALTER COLUMN MODIFY）
            "ALTER TABLE applications MODIFY COLUMN conversation_id INTEGER NULL",
            # 需求分析：为 conversations 表添加 doc_result 字段
            "ALTER TABLE conversations ADD COLUMN doc_result JSON",
            # 上下文压缩：对话摘要字段
            "ALTER TABLE conversations ADD COLUMN context_summary TEXT",
            # 对话阶段 + 服务端 config 状态
            "ALTER TABLE conversations ADD COLUMN phase VARCHAR(20)",
            "ALTER TABLE conversations ADD COLUMN current_config JSON",
            # 智能开发 V2 - agent 流水线状态
            "ALTER TABLE conversations ADD COLUMN coding_phase VARCHAR(32)",
            "ALTER TABLE conversations ADD COLUMN coding_active_brainstorm_session_id VARCHAR(64)",
            "ALTER TABLE conversations ADD COLUMN coding_active_coding_session_id VARCHAR(64)",
            # AI Coding「在应用上定制」绑定应用持久化(刷新/侧栏点开仍记得是哪个应用)
            "ALTER TABLE conversations ADD COLUMN coding_app_id INTEGER",
            # 滑动窗口压缩态(messages+summary 的 JSON), coding agent 跨轮 from_snapshot 恢复用
            "ALTER TABLE conversations ADD COLUMN coding_agent_state TEXT",
            # AIChat 工作模式：chat（从零理需求）/ cowork（批量材料整合）
            "ALTER TABLE ai_chat_sessions ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'chat'",
            # Code system assistant entry profile; intentionally independent from mode.
            "ALTER TABLE ai_chat_sessions ADD COLUMN assistant_profile VARCHAR(40) NOT NULL DEFAULT 'entry_agent'",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_assistant_profile ON ai_chat_sessions(assistant_profile)",
            # 兼容旧版公开会话链接；历史数据允许为空，新会话仍使用数字 ID 作为主键。
            "ALTER TABLE ai_chat_sessions ADD COLUMN public_id VARCHAR(36)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_chat_sessions_public_id ON ai_chat_sessions(public_id)",
            # AIChat 工具调用：存 LLM 返回的原始 call id，跨轮 history 重建用
            "ALTER TABLE ai_chat_tool_calls ADD COLUMN provider_call_id VARCHAR(120)",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_tool_calls_provider_call_id ON ai_chat_tool_calls(provider_call_id)",
            # design-v4 I4: ProcessDefinition 真同步到 apaas 后回填 last_deployed_*
            "ALTER TABLE process_definitions ADD COLUMN last_deployed_version INTEGER",
            "ALTER TABLE process_definitions ADD COLUMN last_deployed_at DATETIME",
            # 统一应用类型: low-code (ai-builder/SPEC) | ai-code (vibe-coding)
            "ALTER TABLE applications ADD COLUMN app_type VARCHAR(20) NOT NULL DEFAULT 'low-code'",
            "ALTER TABLE applications ADD COLUMN source_workspace_id VARCHAR(60)",
            # 配置助手统一到 unified：会话级应用上下文常驻锁
            "ALTER TABLE ai_chat_sessions ADD COLUMN app_id INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_app_id ON ai_chat_sessions(app_id)",
            # SP2a: 会话绑定工作区 ws_id，统一引擎据 mode='code' 推导 ws-lock（cutover 建会话时写入）。
            # 桌面/dev 经本启动块加列（create_all 不改既有表），与 scripts/migrate_aichat_workspace_id.sql 等价。
            "ALTER TABLE ai_chat_sessions ADD COLUMN workspace_id VARCHAR(64)",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_workspace_id ON ai_chat_sessions(workspace_id)",
            # Code 模式外部应用锚点：来自 d-ai-code Control Plane，不在本地 applications 建影子项目。
            "ALTER TABLE ai_chat_sessions ADD COLUMN public_id VARCHAR(36)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_chat_sessions_public_id ON ai_chat_sessions(public_id)",
            "ALTER TABLE ai_chat_sessions ADD COLUMN external_application_id VARCHAR(80)",
            "ALTER TABLE ai_chat_sessions ADD COLUMN external_app_name VARCHAR(200)",
            "ALTER TABLE ai_chat_sessions ADD COLUMN external_app_code VARCHAR(120)",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_external_application_id ON ai_chat_sessions(external_application_id)",
            "ALTER TABLE ai_chat_sessions ADD COLUMN control_plane_tenant_id VARCHAR(80)",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_sessions_control_plane_tenant_id ON ai_chat_sessions(control_plane_tenant_id)",
            # 纯 Code 会话没有本地 applications.id，运行时绑定允许 app_id 为空。
            "ALTER TABLE code_runtime_bindings MODIFY COLUMN app_id INTEGER NULL",
            "ALTER TABLE code_runtime_bindings ADD COLUMN control_plane_tenant_id VARCHAR(80)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_control_plane_tenant_id ON code_runtime_bindings(control_plane_tenant_id)",
            # 早期多会话表包含以下必填字段；当前模型已不再写入，旧库必须释放非空约束。
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN conversation_id VARCHAR(160)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN conversation_purpose VARCHAR(32)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN conversation_purpose_revision BIGINT",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN status VARCHAR(32)",
            "ALTER TABLE code_runtime_agent_sessions MODIFY COLUMN conversation_id VARCHAR(160) NULL",
            "ALTER TABLE code_runtime_agent_sessions MODIFY COLUMN conversation_purpose VARCHAR(32) NULL",
            "ALTER TABLE code_runtime_agent_sessions MODIFY COLUMN conversation_purpose_revision BIGINT NULL",
            "ALTER TABLE code_runtime_agent_sessions MODIFY COLUMN status VARCHAR(32) NULL",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN title VARCHAR(300)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN summary TEXT",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN state VARCHAR(40)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN model VARCHAR(120)",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN runtime_created_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN runtime_updated_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN last_active_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN deleted_at DATETIME",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN capability_stale BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN codex_session_resumable BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE code_runtime_agent_sessions ADD COLUMN control_plane_tenant_id VARCHAR(80)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_control_plane_tenant_id ON code_runtime_agent_sessions(control_plane_tenant_id)",
            # 桌面产品账号来源标记(2026-06-16): 'apaas'=aPaaS同步账号 | 'desktop'=桌面账号
            "ALTER TABLE users ADD COLUMN account_source VARCHAR(20) NOT NULL DEFAULT 'apaas'",
            # account-service: username 全局唯一 → 复合 (username, account_source)
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_username_source ON users(username, account_source)",
            "DROP INDEX IF EXISTS ix_users_username",
            "CREATE INDEX IF NOT EXISTS ix_users_username ON users(username)",
            # 桌面 skill 二进制产物(2026-06-17): pptx/docx 落盘 + 可下载
            "ALTER TABLE ai_chat_artifacts ADD COLUMN storage VARCHAR(10) NOT NULL DEFAULT 'text'",
            "ALTER TABLE ai_chat_artifacts ADD COLUMN file_path VARCHAR(1000)",
            "ALTER TABLE ai_chat_artifacts ADD COLUMN size_bytes BIGINT NOT NULL DEFAULT 0",
            # Code runtime browser-session expand (Task 4); token cleanup is deferred.
            "ALTER TABLE code_runtime_bindings ADD COLUMN runtime_service_session_enc TEXT",
            "ALTER TABLE code_runtime_bindings ADD COLUMN auth_generation INTEGER NOT NULL DEFAULT 1",
            # Execution target defaults to Control Plane for existing bindings.
            "ALTER TABLE code_runtime_bindings ADD COLUMN execution_target "
            "VARCHAR(32) NOT NULL DEFAULT 'control_plane'",
            # Desktop runtime tokens must be Fernet-encrypted before persistence.
            "ALTER TABLE code_runtime_bindings ADD COLUMN desktop_agent_runtime_token_enc TEXT",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_browser_sessions_binding_id "
            "ON code_runtime_browser_sessions(binding_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_code_runtime_browser_sessions_binding_browser "
            "ON code_runtime_browser_sessions(binding_id, browser_session_id)",
        ]:
            await _execute_best_effort(conn, stmt)

        await _migrate_code_runtime_binding_app_id_nullable(conn, inspect)

        # 兼容文档增量流程：DocumentVersion 可先仅绑定 conversation，稍后再关联 application
        for stmt in [
            "ALTER TABLE document_versions MODIFY COLUMN application_id INTEGER NULL",
            "ALTER TABLE document_versions MODIFY COLUMN conversation_id INTEGER NULL",
        ]:
            await _execute_best_effort(conn, stmt)

        # project_members 表 — create_all 已处理，此处确保唯一约束
        await _execute_best_effort(
            conn,
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_member ON project_members(project_id, user_id)",
        )

        # 只清理既没有 application_id 也没有 conversation_id 的真正孤立记录。
        # conversation_id 存在的记录可能还要在应用创建后回填 application_id。
        await _execute_best_effort(
            conn,
            "DELETE FROM document_versions WHERE application_id IS NULL AND conversation_id IS NULL",
        )

        # document_versions / change_plans — create_all 已处理，确保索引存在
        for idx_stmt in [
            "CREATE INDEX IF NOT EXISTS ix_document_versions_application_id ON document_versions(application_id)",
            "CREATE INDEX IF NOT EXISTS ix_change_plans_application_id ON change_plans(application_id)",
            "CREATE INDEX IF NOT EXISTS ix_change_plans_conversation_id ON change_plans(conversation_id)",
            "CREATE INDEX IF NOT EXISTS ix_document_versions_conversation_id ON document_versions(conversation_id)",
        ]:
            await _execute_best_effort(conn, idx_stmt)


async def _migrate_code_runtime_binding_app_id_nullable(conn, inspect_fn) -> None:
    """Rebuild SQLite Code runtime tables that need nullability compatibility.

    MySQL is handled by the regular ALTER statements above. SQLite cannot alter
    column nullability in place, so older Code runtime bindings and agent
    sessions need a small table rebuild.
    """

    if conn.dialect.name != "sqlite":
        return

    from app.models.ai_chat import (
        CodeRuntimeAgentSession,
        CodeRuntimeBinding,
        CodeRuntimeBrowserSession,
    )

    async def table_exists(table_name: str) -> bool:
        return await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(table_name))

    async def table_info(table_name: str):
        return (await conn.execute(text(f"PRAGMA table_info({table_name})"))).mappings().all()

    async def archive_tables() -> list[str]:
        rows = (await conn.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE 'code_runtime_bindings_app_id_notnull%'"
        ))).mappings().all()
        return [str(row["name"]) for row in rows]

    async def drop_non_auto_indexes(table_name: str) -> None:
        index_rows = (await conn.execute(text(f"PRAGMA index_list({table_name})"))).mappings().all()
        for row in index_rows:
            name = str(row.get("name") or "")
            if name and not name.startswith("sqlite_autoindex"):
                await conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))

    async def ensure_current_agent_session_indexes() -> None:
        for stmt in [
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_tenant_id ON code_runtime_agent_sessions(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_control_plane_tenant_id ON code_runtime_agent_sessions(control_plane_tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_user_id ON code_runtime_agent_sessions(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_app_id ON code_runtime_agent_sessions(app_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_session_id ON code_runtime_agent_sessions(session_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_external_application_id ON code_runtime_agent_sessions(external_application_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_workspace_id ON code_runtime_agent_sessions(workspace_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_sandbox_instance_id ON code_runtime_agent_sessions(sandbox_instance_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_agent_sessions_runtime_session_id ON code_runtime_agent_sessions(runtime_session_id)",
        ]:
            await conn.execute(text(stmt))

    async def ensure_agent_session_schema() -> None:
        table_name = CodeRuntimeAgentSession.__tablename__
        table = CodeRuntimeAgentSession.__table__
        if not await table_exists(table_name):
            await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
            await ensure_current_agent_session_indexes()
            return

        rows = await table_info(table_name)
        old_columns = {row.get("name") for row in rows}
        nullable_legacy_columns = {
            "conversation_id",
            "conversation_purpose",
            "conversation_purpose_revision",
            "status",
        }
        needs_rebuild = (
            any(column.name not in old_columns for column in table.columns)
            or any(
                int(next(
                    row.get("notnull") or 0
                    for row in rows
                    if row.get("name") == column_name
                ))
                for column_name in nullable_legacy_columns
                if column_name in old_columns
            )
        )
        if not needs_rebuild:
            await ensure_current_agent_session_indexes()
            return

        archive_name = "code_runtime_agent_sessions_legacy_schema"
        if await table_exists(archive_name):
            suffix = 2
            while await table_exists(f"{archive_name}_{suffix}"):
                suffix += 1
            archive_name = f"{archive_name}_{suffix}"

        await conn.execute(text(f"ALTER TABLE {table_name} RENAME TO {archive_name}"))
        await drop_non_auto_indexes(archive_name)
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))

        common_columns = [column.name for column in table.columns if column.name in old_columns]
        archive_row_count = await conn.scalar(
            text(f"SELECT COUNT(*) FROM {archive_name}")
        )
        if common_columns:
            columns_sql = ", ".join(common_columns)
            await conn.execute(text(
                f"INSERT INTO {table_name} ({columns_sql}) "
                f"SELECT {columns_sql} FROM {archive_name}"
            ))
        current_row_count = await conn.scalar(
            text(f"SELECT COUNT(*) FROM {table_name}")
        )
        if current_row_count != archive_row_count:
            raise RuntimeError(
                "SQLite code runtime agent session rebuild copied an unexpected row count"
            )
        await conn.execute(text(f"DROP TABLE {archive_name}"))
        await ensure_current_agent_session_indexes()

    async def ensure_current_indexes() -> None:
        for stmt in [
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_tenant_id ON code_runtime_bindings(tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_control_plane_tenant_id ON code_runtime_bindings(control_plane_tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_user_id ON code_runtime_bindings(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_app_id ON code_runtime_bindings(app_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_session_id ON code_runtime_bindings(session_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_external_application_id ON code_runtime_bindings(external_application_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_workspace_id ON code_runtime_bindings(workspace_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_sandbox_instance_id ON code_runtime_bindings(sandbox_instance_id)",
            "CREATE INDEX IF NOT EXISTS ix_code_runtime_bindings_runtime_session_id ON code_runtime_bindings(runtime_session_id)",
        ]:
            await conn.execute(text(stmt))

    async def copy_from_archive(archive_name: str, archive_rows) -> None:
        old_columns = {row.get("name") for row in archive_rows}
        new_columns = [col.name for col in CodeRuntimeBinding.__table__.columns]
        common_columns = [name for name in new_columns if name in old_columns]
        if not common_columns:
            return
        columns_sql = ", ".join(common_columns)
        await conn.execute(text(
            f"INSERT OR IGNORE INTO code_runtime_bindings ({columns_sql}) "
            f"SELECT {columns_sql} FROM {archive_name}"
        ))

    async def ensure_browser_session_foreign_key() -> None:
        browser_table = CodeRuntimeBrowserSession.__table__
        if not await table_exists(browser_table.name):
            await conn.run_sync(lambda sync_conn: browser_table.create(sync_conn, checkfirst=True))
            return

        foreign_keys = (await conn.execute(
            text("PRAGMA foreign_key_list(code_runtime_browser_sessions)")
        )).mappings().all()
        if {row.get("table") for row in foreign_keys} == {"code_runtime_bindings"}:
            return

        archive_name = "code_runtime_browser_sessions_fk_archive"
        if await table_exists(archive_name):
            suffix = 2
            while await table_exists(f"{archive_name}_{suffix}"):
                suffix += 1
            archive_name = f"{archive_name}_{suffix}"

        await conn.execute(text(
            f"ALTER TABLE code_runtime_browser_sessions RENAME TO {archive_name}"
        ))
        await drop_non_auto_indexes(archive_name)
        await conn.run_sync(lambda sync_conn: browser_table.create(sync_conn, checkfirst=True))

        archive_rows = await table_info(archive_name)
        old_columns = {row.get("name") for row in archive_rows}
        new_columns = [column.name for column in browser_table.columns]
        common_columns = [name for name in new_columns if name in old_columns]
        if common_columns:
            columns_sql = ", ".join(common_columns)
            await conn.execute(text(
                f"INSERT OR IGNORE INTO code_runtime_browser_sessions ({columns_sql}) "
                f"SELECT {columns_sql} FROM {archive_name}"
            ))
        await conn.execute(text(f"DROP TABLE {archive_name}"))

    await ensure_agent_session_schema()

    has_table = await table_exists("code_runtime_bindings")
    if not has_table:
        await conn.run_sync(lambda sync_conn: CodeRuntimeBinding.__table__.create(sync_conn, checkfirst=True))
        has_table = True

    rows = await table_info("code_runtime_bindings")
    app_col = next((row for row in rows if row.get("name") == "app_id"), None)
    if not app_col:
        await ensure_browser_session_foreign_key()
        return

    if int(app_col.get("notnull") or 0) == 0:
        for archive_name in await archive_tables():
            archive_rows = await table_info(archive_name)
            await drop_non_auto_indexes(archive_name)
            await copy_from_archive(archive_name, archive_rows)
        await ensure_current_indexes()
        await ensure_browser_session_foreign_key()
        return

    archive_name = "code_runtime_bindings_app_id_notnull"
    if await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(archive_name)):
        suffix = 2
        while await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(f"{archive_name}_{suffix}")):
            suffix += 1
        archive_name = f"{archive_name}_{suffix}"

    await conn.execute(text(f"ALTER TABLE code_runtime_bindings RENAME TO {archive_name}"))
    await drop_non_auto_indexes(archive_name)
    await conn.run_sync(lambda sync_conn: CodeRuntimeBinding.__table__.create(sync_conn, checkfirst=True))
    await copy_from_archive(archive_name, rows)
    await ensure_current_indexes()
    await ensure_browser_session_foreign_key()


async def _migrate_legacy_builder_specs(conn, inspect_fn) -> None:
    """Move pre-split AI Builder SPEC rows out of the old `specs` table.

    Older local databases used `specs` for AI Builder business SPECs. The
    integrated branch reserves `specs` for Coding V2 and stores AI Builder
    records in `builder_specs`. If a legacy table is left in place, `/api/spec`
    cannot load existing conversations and Coding V2 cannot create its schema.
    """

    def table_columns(sync_conn, table_name: str) -> set[str]:
        inspector = inspect_fn(sync_conn)
        if not inspector.has_table(table_name):
            return set()
        return {col["name"] for col in inspector.get_columns(table_name)}

    specs_cols = await conn.run_sync(table_columns, "specs")
    if not specs_cols:
        return

    is_legacy_builder_table = (
        {"payload", "phase", "completeness_confirmed", "completeness_total"}.issubset(specs_cols)
        and not {"brainstorm_session_id", "content", "scene_type"}.intersection(specs_cols)
    )
    if not is_legacy_builder_table:
        return

    builder_cols = await conn.run_sync(table_columns, "builder_specs")
    copy_cols = [
        "id",
        "application_id",
        "version",
        "kind",
        "commit_sha",
        "parent_spec_id",
        "payload",
        "phase",
        "completeness_confirmed",
        "completeness_total",
        "created_at",
        "updated_at",
        "created_by",
        "tenant_id",
    ]
    if set(copy_cols).issubset(specs_cols) and set(copy_cols).issubset(builder_cols):
        await conn.execute(text(_insert_select_ignore_conflicts_sql(
            dialect_name=conn.dialect.name,
            target_table="builder_specs",
            columns=copy_cols,
            source_table="specs",
        )))

    archive_name = "legacy_builder_specs"
    if await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(archive_name)):
        archive_name = "legacy_builder_specs_archived"
        suffix = 2
        while await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(archive_name)):
            archive_name = f"legacy_builder_specs_archived_{suffix}"
            suffix += 1
    await conn.execute(text(f"ALTER TABLE specs RENAME TO {archive_name}"))
