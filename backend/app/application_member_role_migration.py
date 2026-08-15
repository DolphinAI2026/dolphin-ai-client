import re

from sqlalchemy import text


def _migration_statements(dialect_name: str) -> tuple[str, ...]:
    statements = (
        "UPDATE application_members SET role = CASE "
        "WHEN role = 'owner' THEN 'owner' "
        "WHEN role IN ('maintainer', 'admin') THEN 'admin' "
        "WHEN role IN ('contributor', 'viewer', 'member') THEN 'collaborator' "
        "ELSE 'collaborator' END",
    )
    if dialect_name == "mysql":
        return statements + (
            "ALTER TABLE application_members MODIFY COLUMN role "
            "VARCHAR(20) NOT NULL DEFAULT 'collaborator'",
        )
    if dialect_name == "postgresql":
        return statements + (
            "ALTER TABLE application_members ALTER COLUMN role "
            "SET DEFAULT 'collaborator'",
        )
    return statements


async def migrate_application_member_roles(conn) -> None:
    for statement in _migration_statements(conn.dialect.name):
        await conn.execute(text(statement))
    if conn.dialect.name == "sqlite":
        await _rebuild_sqlite_role_default(conn)


async def _rebuild_sqlite_role_default(conn) -> None:
    role_column = next(
        row for row in (await conn.execute(
            text("PRAGMA table_info(application_members)")
        )).mappings()
        if row["name"] == "role"
    )
    if str(role_column.get("dflt_value") or "").strip("()'\"") == "collaborator":
        return

    table_sql = await conn.scalar(text(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'table' AND name = 'application_members'"
    ))
    if not table_sql:
        raise RuntimeError("SQLite application_members schema is unavailable")
    rebuilt_sql, replacements = re.subn(
        r"((?:\"role\"|`role`|\[role\]|\brole\b)\s+[^,\n]*?\bDEFAULT\s+)"
        r"(?:\(\s*)?['\"]contributor['\"](?:\s*\))?",
        r"\1'collaborator'",
        str(table_sql),
        count=1,
        flags=re.IGNORECASE,
    )
    if replacements == 0:
        rebuilt_sql, replacements = re.subn(
            r"((?:\"role\"|`role`|\[role\]|\brole\b)\s+[^,\n]+?)(\s*)(?=,)",
            r"\1 DEFAULT 'collaborator'\2",
            str(table_sql),
            count=1,
            flags=re.IGNORECASE,
        )
    if replacements != 1:
        raise RuntimeError("SQLite application_members role default could not be rewritten")

    index_rows = (await conn.execute(text(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'index' AND tbl_name = 'application_members' AND sql IS NOT NULL"
    ))).mappings().all()
    columns = [
        str(row["name"])
        for row in (await conn.execute(
            text("PRAGMA table_info(application_members)")
        )).mappings()
    ]
    archive_name = "application_members_role_default_legacy"
    suffix = 2
    while await conn.scalar(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"
    ), {"name": archive_name}):
        archive_name = f"application_members_role_default_legacy_{suffix}"
        suffix += 1

    archive_count = await conn.scalar(text("SELECT COUNT(*) FROM application_members"))
    await conn.execute(text(f'ALTER TABLE application_members RENAME TO "{archive_name}"'))
    for row in index_rows:
        await conn.execute(text(f'DROP INDEX IF EXISTS "{row["name"]}"'))
    await conn.execute(text(rebuilt_sql))
    columns_sql = ", ".join(f'"{column}"' for column in columns)
    await conn.execute(text(
        f'INSERT INTO application_members ({columns_sql}) '
        f'SELECT {columns_sql} FROM "{archive_name}"'
    ))
    current_count = await conn.scalar(text("SELECT COUNT(*) FROM application_members"))
    if current_count != archive_count:
        raise RuntimeError("SQLite application_members rebuild copied an unexpected row count")
    await conn.execute(text(f'DROP TABLE "{archive_name}"'))
    for row in index_rows:
        await conn.execute(text(str(row["sql"])))
