from __future__ import annotations

import pytest

import app.mcp_server as mcp_server


@pytest.mark.asyncio
async def test_list_dev_workspaces_finds_unbound_candidate_by_query(monkeypatch):
    class FakeWorkspaceManager:
        def list_accessible_workspaces(self, user_id, project_ids, tenant_id=None):
            assert user_id == 1
            assert project_ids == [6]
            assert tenant_id == 64
            return [
                {
                    "id": "1_4aa2694c",
                    "project_id": None,
                    "project_type": "form-page",
                    "project_name": "form-page-portal-showcase-page",
                    "display_name": "门户展示页",
                    "tenant_id": 64,
                    "user_id": 1,
                    "status": "ready",
                    "disk_path": "/tmp/workspaces/form-page-portal-showcase-page__1_4aa2694c",
                },
                {
                    "id": "1_other",
                    "project_id": None,
                    "project_type": "form-page",
                    "project_name": "form-page-project-dashboard",
                    "display_name": "项目驾驶舱",
                    "tenant_id": 64,
                    "user_id": 1,
                    "status": "ready",
                    "disk_path": "/tmp/workspaces/form-page-project-dashboard__1_other",
                },
            ]

    monkeypatch.setattr("app.coding.workspace.WorkspaceManager", FakeWorkspaceManager)

    with mcp_server.trusted_identity(64, 1):
        result = await mcp_server.list_dev_workspaces(
            app_id=6,
            query="form-page-portal-showcase-page.zip",
            tenant_id=64,
            user_id=1,
        )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["workspaces"][0]["ws_id"] == "1_4aa2694c"
    assert result["workspaces"][0]["binding_status"] == "unbound_candidate"
