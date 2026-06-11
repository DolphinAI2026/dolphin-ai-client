"""自开发资产库 租户隔离 —— 回归测试

线上 bug:自开发资产库(/workspace-catalog → GET /coding/workspaces)没按租户隔离,
admin 切租户后数据没变。根因:list_accessible_workspaces 对「缺 tenant_id 的老 workspace」
按 user_id 兜底放行,admin 在每个租户 user_id 相同 → 老资产在所有租户都冒出来。

修复:list_workspaces 路由用 workspace 关联会话的 tenant_id 推断真实归属:
别租户的剔除、本租户的回填 .workspace.json(自愈)。无会话的孤儿维持 user_id 归属。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _result(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


@pytest.mark.asyncio
async def test_list_workspaces_drops_other_tenant_legacy_assets():
    from app.routes import coding as coding_routes

    ctx = MagicMock()
    ctx.user = MagicMock(id=1)
    ctx.tenant_id = 1

    # db.execute 调用顺序:① owned projects ② member projects ③ 本租户 applications
    # ④ 会话归属租户 ⑤ 会话绑定应用(所属应用回填)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _result([]),                       # owned projects
        _result([]),                       # member projects
        _result([]),                       # 本租户 applications
        _result([("ws-t2", 2), ("ws-t1", 1)]),  # 会话归属:ws-t2→租户2, ws-t1→租户1
        _result([]),                       # 会话绑定应用(无)
    ])

    ws_list = [
        {"id": "ws-cur", "tenant_id": 1, "project_id": None},    # 已带租户1 → 保留
        {"id": "ws-t2", "tenant_id": None, "project_id": None},  # 老,会话属租户2 → 剔除
        {"id": "ws-t1", "tenant_id": None, "project_id": None},  # 老,会话属租户1 → 保留+回填
        {"id": "ws-orphan", "tenant_id": None, "project_id": None},  # 老,无会话 → 保留(本人)
    ]

    with (
        patch.object(coding_routes.workspace_mgr, "list_accessible_workspaces", return_value=ws_list),
        patch.object(coding_routes.workspace_mgr, "stamp_tenant_id", return_value=True) as mock_stamp,
        patch.object(coding_routes, "_decorate_workspace_access", side_effect=lambda ws, role: {**ws, "access_role": role}),
    ):
        out = await coding_routes.list_workspaces(ctx, db)

    ids = {w["id"] for w in out}
    assert "ws-t2" not in ids, f"别租户的老资产应被隔离剔除;得到 {ids}"
    assert ids == {"ws-cur", "ws-t1", "ws-orphan"}, f"应保留本租户 + 孤儿;得到 {ids}"
    # ws-t1 命中本租户 → 回填 tenant_id
    mock_stamp.assert_called_once_with("ws-t1", 1)


@pytest.mark.asyncio
async def test_stamp_tenant_id_backfills_only_when_missing(tmp_path):
    import json
    from app.coding.workspace import WorkspaceManager

    mgr = WorkspaceManager()
    ws_path = tmp_path / "ws-legacy"
    ws_path.mkdir()
    (ws_path / ".workspace.json").write_text(json.dumps({"id": "ws-legacy", "user_id": 1}))

    with patch.object(mgr, "get_workspace_path", return_value=ws_path):
        # 缺 tenant_id → 回填成功
        assert mgr.stamp_tenant_id("ws-legacy", 7) is True
        assert json.loads((ws_path / ".workspace.json").read_text())["tenant_id"] == 7
        # 已有 tenant_id → 幂等不动
        assert mgr.stamp_tenant_id("ws-legacy", 9) is False
        assert json.loads((ws_path / ".workspace.json").read_text())["tenant_id"] == 7


@pytest.mark.asyncio
async def test_app_bound_workspace_visible_and_backfilled():
    """所属应用链路: project_id=Application.id 的工作区可见(owner 角色, 不查 Project 表);
    project_id 缺失但会话带 coding_app_id 的工作区被自愈回填。"""
    from app.routes import coding as coding_routes

    ctx = MagicMock()
    ctx.user = MagicMock(id=1)
    ctx.tenant_id = 1

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _result([]),                # owned projects
        _result([]),                # member projects
        _result([(7,), (8,)]),      # 本租户 applications: 7/8
        _result([("ws-unbound", 7)]),  # 会话绑定应用: ws-unbound → app 7
    ])

    ws_list = [
        {"id": "ws-bound", "tenant_id": 1, "project_id": 8},      # 应用绑定 → 直接可见
        {"id": "ws-unbound", "tenant_id": 1, "project_id": None},  # 待回填
    ]

    with (
        patch.object(coding_routes.workspace_mgr, "list_accessible_workspaces", return_value=ws_list),
        patch.object(coding_routes.workspace_mgr, "stamp_project_id", return_value=True) as mock_stamp,
        patch.object(coding_routes, "_decorate_workspace_access", side_effect=lambda ws, role: {**ws, "access_role": role}),
    ):
        out = await coding_routes.list_workspaces(ctx, db)

    by_id = {w["id"]: w for w in out}
    assert by_id["ws-bound"]["access_role"] == "owner", "应用绑定工作区应可见且为 owner(不查 Project 表)"
    assert by_id["ws-unbound"]["project_id"] == 7, "应从会话 coding_app_id 回填所属应用"
    mock_stamp.assert_called_once_with("ws-unbound", 7)


def test_stamp_project_id_backfills_only_when_missing(tmp_path):
    import json as _json
    from app.coding.workspace import WorkspaceManager

    ws_dir = tmp_path / "ws1"
    ws_dir.mkdir()
    (ws_dir / ".workspace.json").write_text(_json.dumps({"id": "ws1", "project_id": None}))
    mgr = WorkspaceManager()
    with patch.object(mgr, "get_workspace_path", return_value=ws_dir):
        assert mgr.stamp_project_id("ws1", 7) is True
        assert _json.loads((ws_dir / ".workspace.json").read_text())["project_id"] == 7
        # 已有值不覆盖
        assert mgr.stamp_project_id("ws1", 9) is False
        assert _json.loads((ws_dir / ".workspace.json").read_text())["project_id"] == 7
