import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.deps import AuthContext
from app.models import User
from app.models.tenant import Tenant
from app.routes.coding import (
    git_status_endpoint, git_branches_endpoint, git_checkout_endpoint,
    GitCheckoutRequest,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def run(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    run("init", "-b", "main")
    run("config", "user.email", "t@t.com"); run("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("hi"); run("add", "a.txt"); run("commit", "-m", "init")
    return tmp_path


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_status_and_branches_and_checkout(db_session, git_repo):
    tenant = Tenant(tenant_name="t", tenant_code="t_git_p1"); db_session.add(tenant); await db_session.flush()
    user = User(username="git_p1", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)
    fake_meta = {"ws_id": "ws-x", "tenant_id": tenant.id, "project_id": None, "user_id": user.id}
    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=git_repo), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_info", return_value=fake_meta), \
         patch("app.coding.workspace_access.workspace_mgr.get_workspace_path", return_value=git_repo):
        s = await git_status_endpoint("ws-x", ctx, db_session)
        assert s["branch"] == "main"
        b = await git_branches_endpoint("ws-x", ctx, db_session)
        assert b["local"] == ["main"]
        out = await git_checkout_endpoint("ws-x", GitCheckoutRequest(name="feat/y", create=True), ctx, db_session)
        assert out["ok"] is True and out["branch"] == "feat/y"
