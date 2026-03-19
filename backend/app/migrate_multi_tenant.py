"""Database migration script for multi-tenant support."""
import asyncio
import sqlite3
from pathlib import Path


async def migrate_to_multi_tenant():
    """迁移现有数据库到多租户架构"""
    db_path = Path(__file__).parent.parent / "apaas_builder.db"

    if not db_path.exists():
        print("数据库文件不存在，跳过迁移")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # 1. 检查是否已经迁移过
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tenants'")
        if cursor.fetchone():
            print("多租户表已存在，跳过迁移")
            return

        print("开始迁移到多租户架构...")

        # 2. 创建默认租户
        print("创建默认租户...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_name VARCHAR(128) NOT NULL,
                tenant_code VARCHAR(64) NOT NULL UNIQUE,
                plan_type VARCHAR(32) NOT NULL DEFAULT 'free',
                max_applications INTEGER NOT NULL DEFAULT 10,
                status INTEGER NOT NULL DEFAULT 1,
                contact_name VARCHAR(64),
                contact_email VARCHAR(128),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            INSERT INTO tenants (tenant_name, tenant_code, plan_type, max_applications, status)
            VALUES ('Default Tenant', 'default', 'free', 100, 1)
        """)
        default_tenant_id = cursor.lastrowid
        print(f"默认租户已创建，ID: {default_tenant_id}")

        # 3. 修改 users 表 — 添加 is_platform_admin
        print("修改 users 表...")
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'is_platform_admin' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_platform_admin BOOLEAN NOT NULL DEFAULT 0")
            print("users 表已添加 is_platform_admin 字段")

        # 4. 修改 conversations 表 — 添加 tenant_id
        print("修改 conversations 表...")
        cursor.execute("PRAGMA table_info(conversations)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'tenant_id' not in columns:
            cursor.execute(f"ALTER TABLE conversations ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT {default_tenant_id}")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_conversations_tenant_id ON conversations(tenant_id)")
            print("conversations 表已添加 tenant_id 字段")

        # 5. 修改 applications 表 — 添加 tenant_id, team_id, created_by
        print("修改 applications 表...")
        cursor.execute("PRAGMA table_info(applications)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'tenant_id' not in columns:
            cursor.execute(f"ALTER TABLE applications ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT {default_tenant_id}")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_applications_tenant_id ON applications(tenant_id)")
            print("applications 表已添加 tenant_id 字段")

        if 'team_id' not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN team_id INTEGER")
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_applications_team_id ON applications(team_id)")
            print("applications 表已添加 team_id 字段")

        if 'created_by' not in columns:
            # 将 created_by 设为 user_id（现有应用的创建者就是 user_id）
            cursor.execute("ALTER TABLE applications ADD COLUMN created_by INTEGER NOT NULL DEFAULT 0")
            cursor.execute("UPDATE applications SET created_by = user_id WHERE created_by = 0")
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_applications_created_by ON applications(created_by)")
            print("applications 表已添加 created_by 字段")

        conn.commit()
        print("✅ 数据库迁移完成")

    except Exception as e:
        conn.rollback()
        print(f"❌ 迁移失败: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(migrate_to_multi_tenant())
