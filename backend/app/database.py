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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 迁移：确保新列存在（兼容 SQLite 和 MySQL）
        for stmt in [
            "ALTER TABLE applications ADD COLUMN generation_state TEXT",
            "ALTER TABLE conversations ADD COLUMN workspace_id VARCHAR(50)",
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
            # conversation_id 改为可空（MySQL ALTER COLUMN MODIFY）
            "ALTER TABLE applications MODIFY COLUMN conversation_id INTEGER NULL",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # 列已存在

        # project_members 表 — create_all 已处理，此处确保唯一约束
        try:
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_member ON project_members(project_id, user_id)"
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
