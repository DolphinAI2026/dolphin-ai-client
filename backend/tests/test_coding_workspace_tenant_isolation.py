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


def _ext_result(rows):
    """外部注册工作区查询: (await db.execute(...)).scalars().all() 链"""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    r = MagicMock()
    r.scalars.return_value = scalars_mock
    return r


def test_pick_workspace_conversation_prefers_matching_empty_asset_session():
    """打开重命名后的资产工作区时, 空的新资产会话也应优先于旧资产的有消息会话。"""
    from app.routes import coding as coding_routes

    fresh = MagicMock(id=41, title="[迁移] 数字孪生总览")
    old = MagicMock(id=30, title="读一下当前的代码，页面接入的数据是走的mock数据？还是真实的API？")
    old_messages = [MagicMock(role="user", content="读一下当前的代码"), MagicMock(role="assistant", content="项目驾驶舱 mock 数据说明")]

    selected, messages = coding_routes._pick_workspace_conversation(
        [fresh, old],
        {fresh.id: [], old.id: old_messages},
        {"project_name": "form-page-factory-twin-dashboard", "display_name": "数字孪生总览"},
    )

    assert selected is fresh
    assert messages == []


@pytest.mark.asyncio
async def test_create_workspace_accepts_application_id_binding():
    """应用上下文创建自开发工作区时 project_id 传的是 Application.id, 不能按 Project 查 404。"""
    from fastapi import HTTPException
    from app.routes import coding as coding_routes

    ctx = MagicMock()
    ctx.user = MagicMock(id=1)
    ctx.tenant_id = 64

    app_lookup = MagicMock()
    app_lookup.scalar_one_or_none.return_value = 10
    db = MagicMock()
    db.execute = AsyncMock(return_value=app_lookup)

    created = {
        "id": "ws-app",
        "project_id": 10,
        "project_type": "form-page",
        "project_name": "form-page-factory-twin-dashboard",
        "display_name": "数字孪生总览",
        "user_id": 1,
        "tenant_id": 64,
        "status": "ready",
    }

    with (
        patch.object(
            coding_routes,
            "require_project_access",
            AsyncMock(side_effect=HTTPException(status_code=404, detail="项目不存在")),
        ) as mock_require_project_access,
        patch.object(coding_routes.workspace_mgr, "create_workspace", return_value=created) as mock_create,
        patch.object(coding_routes.workspace_mgr, "list_files", return_value=[]),
        patch.object(coding_routes, "_decorate_workspace_access", side_effect=lambda ws, role: {**ws, "access_role": role}),
    ):
        out = await coding_routes.create_workspace(
            coding_routes.CreateWorkspaceRequest(
                project_type="form-page",
                project_name="factory-twin-dashboard",
                display_name="数字孪生总览",
                project_id=10,
            ),
            ctx,
            db,
        )

    mock_require_project_access.assert_not_awaited()
    mock_create.assert_called_once()
    assert out["project_id"] == 10
    assert out["access_role"] == "owner"


@pytest.mark.asyncio
async def test_list_workspaces_drops_other_tenant_legacy_assets():
    from app.routes import coding as coding_routes

    ctx = MagicMock()
    ctx.user = MagicMock(id=1)
    ctx.tenant_id = 1

    # db.execute 调用顺序:① owned projects ② member projects ③ 本租户 applications
    # ④ 会话归属租户 ⑤ 会话绑定应用(所属应用回填) ⑥ external 注册工作区
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _result([]),                       # owned projects
        _result([]),                       # member projects
        _result([]),                       # 本租户 applications
        _result([("ws-t2", 2), ("ws-t1", 1)]),  # 会话归属:ws-t2→租户2, ws-t1→租户1
        _result([]),                       # 会话绑定应用(无)
        _ext_result([]),                   # external 注册工作区(无)
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
        _ext_result([]),            # external 注册工作区(无)
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


@pytest.mark.asyncio
async def test_ensure_workspace_access_app_bound_does_not_404():
    """回归: 绑定应用(project_id=Application.id)后打开工作区不能 404
    (原代码拿应用 id 查 Project 表, 所有工作区端点直接打不开)。"""
    from fastapi import HTTPException
    from app.routes import coding as coding_routes

    ctx = MagicMock()
    ctx.user = MagicMock(id=1)
    ctx.tenant_id = 64

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=4)))

    meta = {"id": "ws-x", "project_id": 4, "user_id": 1, "tenant_id": 64}
    with patch.object(coding_routes.workspace_mgr, "get_workspace_info", return_value=meta), \
         patch.object(coding_routes, "_decorate_workspace_access", side_effect=lambda m, role: {**m, "access_role": role}):
        out = await coding_routes._ensure_workspace_access("ws-x", ctx, db, minimum_project_role="member")
        assert out["access_role"] == "owner"

        # 同租户非创建者: member 可访问, admin 级操作拒绝
        ctx2 = MagicMock(); ctx2.user = MagicMock(id=2); ctx2.tenant_id = 64
        out2 = await coding_routes._ensure_workspace_access("ws-x", ctx2, db, minimum_project_role="member")
        assert out2["access_role"] == "member"
        with pytest.raises(HTTPException) as exc:
            await coding_routes._ensure_workspace_access("ws-x", ctx2, db, minimum_project_role="admin")
        assert exc.value.status_code == 403
