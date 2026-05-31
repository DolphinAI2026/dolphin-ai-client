"""Database migration script for multi-tenant support (MySQL compatible)."""
import asyncio

from sqlalchemy import text
from app.database import engine


async def _column_exists(conn, table: str, column: str) -> bool:
    """检查 MySQL 表中是否存在指定列"""
    result = await conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


async def _table_exists(conn, table: str) -> bool:
    """检查 MySQL 数据库中是否存在指定表"""
    result = await conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
    ), {"table": table})
    return result.scalar() > 0


async def _add_column_if_not_exists(conn, table: str, column: str, col_def: str):
    """如果列不存在则添加"""
    if not await _column_exists(conn, table, column):
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
        print(f"  {table} 表已添加 {column} 字段")


async def migrate_to_multi_tenant():
    """迁移现有数据库到多租户架构"""
    async with engine.begin() as conn:
        # 1. 检查是否已经迁移过
        if await _table_exists(conn, "tenants"):
            print("多租户表已存在，跳过迁移")
            return

        print("开始迁移到多租户架构...")

        # 2. 创建默认租户
        print("创建默认租户...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                tenant_name VARCHAR(128) NOT NULL,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                plan_type VARCHAR(32) NOT NULL DEFAULT 'free',
                max_applications INTEGER NOT NULL DEFAULT 10,
                status INTEGER NOT NULL DEFAULT 1,
                contact_name VARCHAR(64),
                contact_email VARCHAR(128),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """))

        await conn.execute(text("""
            INSERT INTO tenants (tenant_name, tenant_code, plan_type, max_applications, status)
            VALUES ('Default Tenant', 'default', 'free', 100, 1)
        """))

        result = await conn.execute(text("SELECT LAST_INSERT_ID()"))
        default_tenant_id = result.scalar()
        print(f"默认租户已创建，ID: {default_tenant_id}")

        # 3. 修改 users 表 — 添加 is_platform_admin
        print("修改 users 表...")
        await _add_column_if_not_exists(conn, "users", "is_platform_admin", "BOOLEAN NOT NULL DEFAULT 0")

        # 4. 修改 conversations 表 — 添加 tenant_id
        print("修改 conversations 表...")
        await _add_column_if_not_exists(
            conn, "conversations", "tenant_id",
            f"INTEGER NOT NULL DEFAULT {default_tenant_id}"
        )
        try:
            await conn.execute(text(
                "CREATE INDEX ix_conversations_tenant_id ON conversations(tenant_id)"
            ))
        except Exception:
            pass

        # 5. 修改 applications 表 — 添加 tenant_id, team_id, created_by
        print("修改 applications 表...")
        await _add_column_if_not_exists(
            conn, "applications", "tenant_id",
            f"INTEGER NOT NULL DEFAULT {default_tenant_id}"
        )
        try:
            await conn.execute(text(
                "CREATE INDEX ix_applications_tenant_id ON applications(tenant_id)"
            ))
        except Exception:
            pass

        await _add_column_if_not_exists(conn, "applications", "team_id", "INTEGER")
        try:
            await conn.execute(text(
                "CREATE INDEX ix_applications_team_id ON applications(team_id)"
            ))
        except Exception:
            pass

        await _add_column_if_not_exists(conn, "applications", "created_by", "INTEGER NOT NULL DEFAULT 0")
        try:
            await conn.execute(text(
                "UPDATE applications SET created_by = user_id WHERE created_by = 0"
            ))
            await conn.execute(text(
                "CREATE INDEX ix_applications_created_by ON applications(created_by)"
            ))
        except Exception:
            pass

        print("✅ 数据库迁移完成")


if __name__ == "__main__":
    asyncio.run(migrate_to_multi_tenant())
