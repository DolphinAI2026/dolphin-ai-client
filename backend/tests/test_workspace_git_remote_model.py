import pytest
from app.models.workspace_git import WorkspaceGitRemote


@pytest.mark.asyncio
async def test_workspace_git_remote_persists(db_session):
    r = WorkspaceGitRemote(
        ws_id="1_abc",
        tenant_id=1,
        user_id=2,
        provider="gitlab",
        remote_url="https://git.co/g/p.git",
        default_branch="main",
        git_connection_id=5,
    )
    db_session.add(r)
    await db_session.flush()
    from sqlalchemy import select

    got = (
        await db_session.execute(
            select(WorkspaceGitRemote).where(WorkspaceGitRemote.ws_id == "1_abc")
        )
    ).scalar_one()
    assert got.provider == "gitlab" and got.git_connection_id == 5
