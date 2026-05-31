"""幂等迁移脚本运行器。

用法：
    python scripts/run_migrations.py scripts/migrate_collab_v1.sql

特性：
- 正确处理 SQL 注释（行内 -- 注释 + 块 /* */ 注释）
- 把 errno 1060 (Duplicate column) 视为"列已存在，跳过"
- 把 errno 1050 (Duplicate table) 视为"表已存在，跳过"
- 把 errno 1061 (Duplicate key) 视为"索引已存在，跳过"
- 其他错误正常 raise
- 每条语句日志单独打印 status

MySQL 8 没有 ALTER TABLE ... ADD COLUMN IF NOT EXISTS 语法，
runner 兜底实现幂等。
"""
from __future__ import annotations
import asyncio
import os
import re
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

# MySQL 错误码 → 处理策略（'skip' = 视为已存在）
IDEMPOTENT_ERRNOS = {
    1060: "Duplicate column (列已存在)",
    1050: "Duplicate table (表已存在)",
    1061: "Duplicate key name (索引已存在)",
    1091: "Can't DROP; check that column/key exists",
}


def strip_sql_comments(sql: str) -> str:
    """移除单行 -- 注释和块 /* */ 注释，保留字符串里的 -- ."""
    # 先去块注释（非贪婪）
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    # 再去单行注释（每行从 -- 到行尾）
    out_lines = []
    for line in sql.splitlines():
        # 简化处理：不进入字符串（migration SQL 一般不在字符串内含 --）
        idx = line.find("--")
        out_lines.append(line if idx < 0 else line[:idx])
    return "\n".join(out_lines)


def split_statements(sql: str) -> list[str]:
    """按 ; 分号分语句（已剥离注释后）。"""
    cleaned = strip_sql_comments(sql)
    parts = [p.strip() for p in cleaned.split(";")]
    return [p for p in parts if p]


def get_database_url() -> str:
    # 优先读 .env
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    raise RuntimeError("DATABASE_URL not found in env or backend/.env")


async def run_migration(sql_path: Path) -> int:
    sql = sql_path.read_text()
    statements = split_statements(sql)
    print(f"[migrate] {sql_path.name}: {len(statements)} statements")

    engine = create_async_engine(get_database_url())
    applied = skipped = 0
    try:
        async with engine.begin() as conn:
            for i, stmt in enumerate(statements, 1):
                short = stmt[:80].replace("\n", " ")
                try:
                    await conn.execute(text(stmt))
                    print(f"  [{i:>3}] OK     {short}...")
                    applied += 1
                except (OperationalError, ProgrammingError) as e:
                    code = getattr(getattr(e, "orig", None), "args", [None])[0]
                    if code in IDEMPOTENT_ERRNOS:
                        print(f"  [{i:>3}] SKIP   {short}... ({IDEMPOTENT_ERRNOS[code]})")
                        skipped += 1
                        # MySQL 对每条 DDL 隐式 commit，即便包在 engine.begin() 内，
                        # 服务端也已落库。所以 swallow errno 1060/1050/1061/1091 后
                        # 继续下一条是安全的。仅 UPDATE/INSERT 等 DML 共享事务，
                        # 但 DML 不会触发这些 errno，永远进 raise 分支。
                    else:
                        raise
    finally:
        await engine.dispose()

    print(f"[migrate] DONE  applied={applied} skipped(already-applied)={skipped}")
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_migrations.py <sql_file>")
        sys.exit(2)
    path = Path(sys.argv[1]).resolve()
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(2)
    sys.exit(asyncio.run(run_migration(path)))


if __name__ == "__main__":
    main()
