"""Harness coding pipeline access guard tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import User
from app.routes.harness import CodingPipelineRequest, coding_pipeline


def _ctx() -> AuthContext:
    return AuthContext(
        user=User(id=1, username="harness_user", hashed_password="x"),
        tenant_id=10,
        tenant_role="member",
        org_permissions={},
    )


def _request():
    req = MagicMock()
    req.headers = {}
    req.url.scheme = "http"
    req.url.netloc = "testserver"
    return req


@pytest.mark.asyncio
async def test_harness_coding_pipeline_rejects_inaccessible_workspace_before_starting():
    req = CodingPipelineRequest(message="读一下代码", workspace_id="ws-other", conversation_id=123)
    db = MagicMock()

    with (
        patch("app.routes.harness._ensure_workspace_access", new=AsyncMock(side_effect=HTTPException(status_code=403, detail="无权访问该工作区"))),
        patch("app.routes.harness._start_coding_turn_sse", new=AsyncMock()) as start_turn,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await coding_pipeline(req, _request(), _ctx(), db)

    assert exc_info.value.status_code == 403
    start_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_harness_coding_pipeline_checks_project_access_before_starting():
    req = CodingPipelineRequest(message="做个页面", project_id=55)
    db = MagicMock()

    with (
        patch("app.routes.harness._ensure_workspace_access", new=AsyncMock()) as ensure_ws,
        patch("app.routes.harness.require_project_access", new=AsyncMock(side_effect=HTTPException(status_code=403, detail="无权访问项目"))),
        patch("app.routes.harness._start_coding_turn_sse", new=AsyncMock()) as start_turn,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await coding_pipeline(req, _request(), _ctx(), db)

    assert exc_info.value.status_code == 403
    ensure_ws.assert_not_awaited()
    start_turn.assert_not_awaited()
