"""Webhook 接收端点：POST /api/webhooks/git/{provider}

入口设计：
- URL path 含 provider（github/gitlab）
- header 带签名 / token，body 是 JSON
- 找匹配的 GitConnection（通过 repo_full_path → host → 找用此 host 的 connection 之一）
- 验签 → 通过 → 异步 dispatch event handler
- 失败：返 401（验签失败）或 404（无匹配 connection）
"""
from __future__ import annotations
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.collaboration import GitConnection
from app.git.connection import decrypt_token
from app.git.webhook import (
    verify_signature_github, verify_signature_gitlab, parse_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/git", tags=["git-webhook"])


@router.post("/{provider}")
async def receive_webhook(
    provider: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if provider not in ("github", "gitlab"):
        raise HTTPException(400, f"unsupported provider: {provider}")

    payload_bytes = await request.body()
    try:
        payload = (await request.json())
    except Exception:
        raise HTTPException(400, "invalid JSON payload")

    # 找 repo_full_path → 找 GitConnection
    headers = {k.lower(): v for k, v in request.headers.items()}
    event = parse_event(provider, headers, payload)
    repo = event.repo_full_path
    if not repo:
        raise HTTPException(400, "cannot extract repo from payload")

    # 找 connection：在所有 GitConnection 里找 webhook_secret_enc 配过的且 provider/host 匹配
    # （简化版：repo path 含 group/org 名，跟 GitConnection.group_id_or_org 前缀匹配）
    repo_owner = repo.split("/")[0]
    conn = (await db.execute(
        select(GitConnection).where(
            GitConnection.provider == provider,
            GitConnection.group_id_or_org == repo_owner,
        )
    )).scalar_one_or_none()
    if not conn or not conn.webhook_secret_enc:
        raise HTTPException(404, f"no connection or webhook secret for {repo}")

    secret = decrypt_token(conn.webhook_secret_enc)
    if provider == "github":
        sig = headers.get("x-hub-signature-256", "")
        if not verify_signature_github(payload_bytes, sig, secret):
            raise HTTPException(401, "signature verification failed")
    else:  # gitlab
        token = headers.get("x-gitlab-token", "")
        if not verify_signature_gitlab(payload_bytes, token, secret):
            raise HTTPException(401, "signature verification failed")

    # dispatch（Phase D 后续 task 加 handler）
    from app.git.inbound import dispatch_webhook_event
    try:
        await dispatch_webhook_event(db, conn=conn, event=event)
    except Exception as e:
        logger.exception(f"webhook dispatch failed for {repo}: {e}")
        # 不 raise — 返 200 让 git 平台不重投
    return {"status": "ok", "event_type": event.event_type}
