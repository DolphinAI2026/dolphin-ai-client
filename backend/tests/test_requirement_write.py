from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.vibe_coding.tools import execute_requirement_write


async def test_requirement_write_sets_baseline():
    thread = SimpleNamespace(requirement_baseline=None)
    db = AsyncMock()
    out = await execute_requirement_write(
        {
            "roles": ["管理员 — 管理用户", "员工 — 提交报销"],
            "features": ["报销提交", "审批"],
            "flows": ["提交→审批→打款"],
            "acceptance": ["提交后主管能看到待审"],
        },
        thread,
        db,
    )
    assert thread.requirement_baseline["roles"] == ["管理员 — 管理用户", "员工 — 提交报销"]
    assert thread.requirement_baseline["features"] == ["报销提交", "审批"]
    # 缺省字段补空数组
    assert thread.requirement_baseline["external"] == []
    assert thread.requirement_baseline["ai_points"] == []
    db.commit.assert_awaited_once()
    assert "需求基线" in out


async def test_requirement_write_rejects_non_list():
    thread = SimpleNamespace(requirement_baseline=None)
    db = AsyncMock()
    out = await execute_requirement_write({"roles": "管理员"}, thread, db)
    assert "数组" in out  # _err 返回
    db.commit.assert_not_awaited()
