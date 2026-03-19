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
            "ALTER TABLE users ADD COLUMN apaas_base_url VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN apaas_tenant_id VARCHAR(50)",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # 列已存在
