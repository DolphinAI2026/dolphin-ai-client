from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


class Base(DeclarativeBase):
    pass


_engine_kwargs = dict(echo=False, future=True)
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs.update(pool_size=10, max_overflow=20, pool_recycle=3600)

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
    from sqlalchemy import text
    # 确保 harness models 被 Base 注册（create_all 会创建新表）
    import app.harness.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 迁移：确保新列存在（兼容 SQLite 和 MySQL）
        for stmt in [
            "ALTER TABLE applications ADD COLUMN generation_state TEXT",
            "ALTER TABLE conversations ADD COLUMN workspace_id VARCHAR(50)",
            "ALTER TABLE conversations ADD COLUMN selected_llm_config_id INTEGER",
            "ALTER TABLE conversations ADD COLUMN project_id INTEGER",
            "ALTER TABLE users ADD COLUMN apaas_base_url VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN apaas_tenant_id VARCHAR(50)",
            # Projects table columns (in case table existed before new columns were added)
            "ALTER TABLE projects ADD COLUMN platform_username VARCHAR(100)",
            "ALTER TABLE projects ADD COLUMN platform_app_name VARCHAR(100)",
            # Document-driven incremental development
            "ALTER TABLE applications ADD COLUMN current_doc_version INTEGER",
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
