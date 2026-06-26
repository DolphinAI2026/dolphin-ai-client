"""CLI 包装：对当前 DATABASE_URL 跑知识库 seed。

用法：
    cd backend
    venv/bin/python scripts/seed_knowledge_docs.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

# 让 import app.* 可用（同其他 backend/scripts/*.py 惯例）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal  # noqa: E402
from app.knowledge_seed import upsert_seed_docs  # noqa: E402


async def _main() -> None:
    async with AsyncSessionLocal() as db:
        n = await upsert_seed_docs(db)
        print(f"seeded/updated {n} knowledge docs")


if __name__ == "__main__":
    asyncio.run(_main())
