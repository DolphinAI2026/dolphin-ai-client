"""为遗留 Application 自动创建 Project + ProjectMember(owner) 关联。

迁移逻辑（幂等）：
- 找出所有 Application.project_id IS NULL
- 为每个建一个 Project（name=Application.app_name，user_id=created_by, tenant_id=同 application）
- 加 ProjectMember(role='owner', user_id=created_by)
- 把 Application.project_id 指过去

跑法：
    cd backend && source venv/bin/activate
    python scripts/seed_default_projects.py [--dry-run]
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

# 让 import app.* 可用
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models import Application, Project, ProjectMember


def get_database_url() -> str:
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
    raise RuntimeError("DATABASE_URL not found")


async def run(dry_run: bool = False):
    engine = create_async_engine(get_database_url())
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        result = await db.execute(
            select(Application).where(Application.project_id.is_(None))
        )
        orphans = result.scalars().all()
        print(f"Found {len(orphans)} orphan applications without project_id")

        created = 0
        for app in orphans:
            print(f"  - app id={app.id} name='{app.app_name}' tenant={app.tenant_id} created_by={app.created_by}")
            if dry_run:
                continue

            project = Project(
                name=f"{app.app_name}",
                description=f"自动创建（来自应用 {app.app_name} 迁移）",
                user_id=app.created_by,
                tenant_id=app.tenant_id,
            )
            db.add(project)
            await db.flush()

            existing_mem = (await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == app.created_by,
                )
            )).scalar_one_or_none()
            if not existing_mem:
                db.add(ProjectMember(
                    project_id=project.id,
                    user_id=app.created_by,
                    role="owner",
                ))

            await db.execute(
                update(Application)
                .where(Application.id == app.id)
                .values(project_id=project.id)
            )
            created += 1

        if not dry_run:
            await db.commit()
        print(f"{'[DRY-RUN]' if dry_run else '[DONE]'} created {created} projects")

    await engine.dispose()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    asyncio.run(run(dry_run=dry))
