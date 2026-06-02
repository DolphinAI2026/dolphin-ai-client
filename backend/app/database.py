from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


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


async def init_db():
    # 确保 extension models 被 Base 注册（create_all 会创建新表）
    import app.harness.models  # noqa: F401
    # 智能开发 V2 - agent 架构相关表（agent_messages / brainstorm_sessions / specs / ...）
    import app.models.agent_models  # noqa: F401
    import app.models.collaboration  # noqa: F401
    import app.models.preference  # noqa: F401
    import app.models.spec  # noqa: F401
    # ConfigChat 会话持久化（2026-05-24）— config_chat_sessions / config_chat_messages
    import app.models.config_chat  # noqa: F401
    # 部署历史 + 回滚（2026-05-24）— DeployRecord
    import app.models.deploy_history  # noqa: F401
    # 流程定义 JSON 本地存档（design-v4 H2）— ProcessDefinition
    import app.models.process_definition  # noqa: F401
    # SPEC 版本快照 + markdown 缓存（Y SPEC 版本管理）
    import app.models.spec_applied_version  # noqa: F401
    import app.models.spec_document  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_legacy_builder_specs(conn, inspect)
        await conn.run_sync(Base.metadata.create_all)
        # 迁移：确保新列存在（兼容 SQLite 和 MySQL）
        for stmt in [
            "ALTER TABLE applications ADD COLUMN generation_state TEXT",
            "ALTER TABLE conversations ADD COLUMN workspace_id VARCHAR(50)",
            "ALTER TABLE conversations ADD COLUMN selected_llm_config_id INTEGER",
            "ALTER TABLE conversations ADD COLUMN project_id INTEGER",
            "ALTER TABLE users ADD COLUMN apaas_base_url VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN apaas_tenant_id VARCHAR(50)",
            # Tenant quota/contact columns added after early multi-tenant installs.
            "ALTER TABLE tenants ADD COLUMN max_applications INTEGER NOT NULL DEFAULT 10",
            "ALTER TABLE tenants ADD COLUMN max_workspaces INTEGER NOT NULL DEFAULT 20",
            "ALTER TABLE tenants ADD COLUMN max_components INTEGER NOT NULL DEFAULT 50",
            "ALTER TABLE tenants ADD COLUMN contact_name VARCHAR(64)",
            "ALTER TABLE tenants ADD COLUMN contact_email VARCHAR(128)",
            "ALTER TABLE tenants ADD COLUMN apaas_env_id INTEGER",
            "ALTER TABLE tenants ADD COLUMN apaas_tenant_id_str VARCHAR(40)",
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
            # AIChat 工作模式：chat（从零理需求）/ cowork（批量材料整合）
            "ALTER TABLE ai_chat_sessions ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'chat'",
            # AIChat 工具调用：存 LLM 返回的原始 call id，跨轮 history 重建用
            "ALTER TABLE ai_chat_tool_calls ADD COLUMN provider_call_id VARCHAR(120)",
            "CREATE INDEX IF NOT EXISTS ix_ai_chat_tool_calls_provider_call_id ON ai_chat_tool_calls(provider_call_id)",
            # design-v4 I4: ProcessDefinition 真同步到 apaas 后回填 last_deployed_*
            "ALTER TABLE process_definitions ADD COLUMN last_deployed_version INTEGER",
            "ALTER TABLE process_definitions ADD COLUMN last_deployed_at DATETIME",
            # 统一应用类型: low-code (ai-builder/SPEC) | ai-code (vibe-coding)
            "ALTER TABLE applications ADD COLUMN app_type VARCHAR(20) NOT NULL DEFAULT 'low-code'",
            "ALTER TABLE applications ADD COLUMN source_workspace_id VARCHAR(60)",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # 列已存在

        # 兼容文档增量流程：DocumentVersion 可先仅绑定 conversation，稍后再关联 application
        for stmt in [
            "ALTER TABLE document_versions MODIFY COLUMN application_id INTEGER NULL",
            "ALTER TABLE document_versions MODIFY COLUMN conversation_id INTEGER NULL",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass

        # project_members 表 — create_all 已处理，此处确保唯一约束
        try:
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_member ON project_members(project_id, user_id)"
            ))
        except Exception:
            pass

        # 只清理既没有 application_id 也没有 conversation_id 的真正孤立记录。
        # conversation_id 存在的记录可能还要在应用创建后回填 application_id。
        try:
            await conn.execute(text(
                "DELETE FROM document_versions WHERE application_id IS NULL AND conversation_id IS NULL"
            ))
        except Exception:
            pass

        # document_versions / change_plans — create_all 已处理，确保索引存在
        for idx_stmt in [
            "CREATE INDEX IF NOT EXISTS ix_document_versions_application_id ON document_versions(application_id)",
            "CREATE INDEX IF NOT EXISTS ix_change_plans_application_id ON change_plans(application_id)",
            "CREATE INDEX IF NOT EXISTS ix_change_plans_conversation_id ON change_plans(conversation_id)",
            "CREATE INDEX IF NOT EXISTS ix_document_versions_conversation_id ON document_versions(conversation_id)",
        ]:
            try:
                await conn.execute(text(idx_stmt))
            except Exception:
                pass


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
        insert_keyword = "INSERT IGNORE" if conn.dialect.name == "mysql" else "INSERT OR IGNORE"
        columns_sql = ", ".join(copy_cols)
        await conn.execute(text(
            f"{insert_keyword} INTO builder_specs ({columns_sql}) "
            f"SELECT {columns_sql} FROM specs"
        ))

    archive_name = "legacy_builder_specs"
    if await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(archive_name)):
        archive_name = "legacy_builder_specs_archived"
        suffix = 2
        while await conn.run_sync(lambda sync_conn: inspect_fn(sync_conn).has_table(archive_name)):
            archive_name = f"legacy_builder_specs_archived_{suffix}"
            suffix += 1
    await conn.execute(text(f"ALTER TABLE specs RENAME TO {archive_name}"))
