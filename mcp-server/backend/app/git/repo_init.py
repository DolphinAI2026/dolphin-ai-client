"""为 application 在 git 平台上初始化 repo + 推第一版 canonical SPEC"""
from __future__ import annotations
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application
from app.models.collaboration import GitConnection
from app.git.connection import make_provider
from app.git.provider.base import GitFile

logger = logging.getLogger(__name__)


async def init_repo_for_application(
    db: AsyncSession,
    *,
    application: Application,
    git_connection: GitConnection,
) -> str:
    """创建 repo（如不存在）+ 推 .builder/manifest.json + spec/canonical.{md,json} + README

    返回 repo full path（如 'myorg/app_code'），同时写回 application 的:
      - git_repo_url
      - git_provider
      - git_default_branch
    """
    provider = make_provider(git_connection)
    repo_name = application.app_code or f"app-{application.id}"
    full_path = f"{git_connection.group_id_or_org}/{repo_name}"

    # 检查 repo 是否已存在
    existing = await provider.get_repo(full_path)
    if not existing:
        full_path = await provider.create_repo(
            group_or_org=git_connection.group_id_or_org,
            name=repo_name,
            description=f"aPaaS Builder app: {application.app_name}",
        )
        logger.info("init_repo: created %s/%s -> %s", git_connection.provider, repo_name, full_path)
    else:
        logger.info("init_repo: repo %s already exists, skipping create", full_path)

    # 准备初始文件
    files = [
        GitFile(path=".builder/manifest.json", content=_manifest_json(application)),
        GitFile(path="README.md", content=_readme(application)),
    ]

    # 如果应用已有 canonical SPEC，把 SPEC 也推上去
    if application.canonical_spec_id:
        try:
            from app.builder_spec.persistence import load_spec
            from app.builder_spec.converter import spec_to_config

            canonical = await load_spec(db, application.canonical_spec_id, tenant_id=application.tenant_id)
            if canonical:
                spec_dict = canonical.model_dump(mode="json")
                config_dict = spec_to_config(canonical)
                files.append(GitFile(
                    path="spec/canonical.json",
                    content=json.dumps(spec_dict, indent=2, ensure_ascii=False),
                ))
                title = (canonical.goal.title if canonical.goal else None) or application.app_name
                files.append(GitFile(
                    path="spec/canonical.md",
                    content=(
                        f"# {title}\n\n"
                        f"应用 SPEC（自动从结构化生成）\n\n"
                        f"```json\n{json.dumps(config_dict, indent=2, ensure_ascii=False)}\n```\n"
                    ),
                ))
        except Exception as e:
            logger.warning("init_repo: failed to load canonical SPEC %s: %s", application.canonical_spec_id, e)

    await provider.commit_files(
        repo_full_path=full_path,
        branch="main",
        message="chore: initialize aPaaS Builder repo",
        files=files,
    )

    # 写回 application 字段
    application.git_repo_url = f"{git_connection.host.rstrip('/')}/{full_path}"
    application.git_provider = git_connection.provider
    application.git_default_branch = "main"
    await db.commit()
    return full_path


def _manifest_json(app: Application) -> str:
    return json.dumps({
        "app_id": app.id,
        "app_code": app.app_code,
        "app_name": app.app_name,
        "builder_version": "phase-c-v1",
        "canonical_spec_id": app.canonical_spec_id,
    }, indent=2, ensure_ascii=False)


def _readme(app: Application) -> str:
    desc = app.description or ""
    return (
        f"# {app.app_name}\n\n"
        f"{desc}\n\n"
        f"---\n"
        f"*由 aPaaS Builder 自动维护。请通过 Builder 平台编辑 SPEC，"
        f"避免直接修改 git 上的文件（Phase D 起将拦截直连 merge）。*\n"
    )
