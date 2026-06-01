"""B2: migrate_orphan_workspaces — 孤儿 workspace 迁移测试

验收条件:
1. 有会话指向的 workspace → 不动（跳过）
2. 孤儿 workspace（有 user_id + tenant_id）→ 补建一个 Conversation(agent_type='coding',
   workspace_id=<ws_id>) 并挂上
3. 孤儿 workspace 但 meta 缺 user_id/tenant_id → 打 archived=true 标记, 不删目录
4. 幂等：跑两遍结果相同（不重复建 Conversation，不报错）
5. 无数据丢失：任何 workspace 目录都不被删除
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import select

from app.models import Conversation
from app.models.tenant import Tenant


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_ws_dir(root: Path, ws_id: str, meta: dict) -> Path:
    """在 root 下建一个合法 workspace 目录，写 .workspace.json。"""
    folder_name = f"form-component-custom__{ws_id}"
    ws_path = root / folder_name
    ws_path.mkdir(parents=True, exist_ok=True)
    (ws_path / ".workspace.json").write_text(
        json.dumps({"id": ws_id, **meta}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ws_path


async def _seed_tenant_and_conversation(db, *, tenant_code: str, ws_id: str) -> tuple:
    """建租户 + coding 会话（已指向 ws_id）。"""
    tenant = Tenant(tenant_name=tenant_code, tenant_code=tenant_code)
    db.add(tenant)
    await db.flush()

    conv = Conversation(
        user_id=1,
        tenant_id=tenant.id,
        title="已有会话",
        agent_type="coding",
        workspace_id=ws_id,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(conv)
    return tenant, conv


# ---------------------------------------------------------------------------
# 1. 有主 workspace → 跳过
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_owned_workspace_skipped(db_session, tmp_path, monkeypatch):
    """已有 Conversation 指向的 workspace 不应被修改。"""
    ws_id = "1_aaaaaaaa"
    tenant, conv = await _seed_tenant_and_conversation(
        db_session, tenant_code="t_owned", ws_id=ws_id,
    )

    _make_ws_dir(tmp_path, ws_id, {
        "user_id": 1,
        "tenant_id": tenant.id,
        "project_type": "form-component-dual",
        "display_name": "已有",
    })

    from app.coding import migrate_orphan_workspaces as mod
    monkeypatch.setattr(mod, "WORKSPACE_SEARCH_ROOTS", (tmp_path,))

    result = await mod.migrate_orphan_workspaces(db_session)
    assert result["skipped"] == 1
    assert result["migrated"] == 0
    assert result["archived"] == 0

    # 会话数量不变
    rows = (await db_session.execute(
        select(Conversation).where(Conversation.workspace_id == ws_id)
    )).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 2. 孤儿 workspace（有 owner）→ 补建 Conversation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orphan_workspace_gets_conversation(db_session, tmp_path, monkeypatch):
    """无会话指向的孤儿 workspace 应被补建一个 coding 会话。"""
    tenant = Tenant(tenant_name="t_orphan", tenant_code="t_orphan")
    db_session.add(tenant)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(tenant)

    ws_id = "2_bbbbbbbb"
    _make_ws_dir(tmp_path, ws_id, {
        "user_id": 42,
        "tenant_id": tenant.id,
        "project_type": "form-component-dual",
        "display_name": "孤儿组件",
    })

    from app.coding import migrate_orphan_workspaces as mod
    monkeypatch.setattr(mod, "WORKSPACE_SEARCH_ROOTS", (tmp_path,))

    result = await mod.migrate_orphan_workspaces(db_session)
    assert result["migrated"] == 1
    assert result["skipped"] == 0
    assert result["archived"] == 0

    # DB 里应有新会话
    rows = (await db_session.execute(
        select(Conversation).where(Conversation.workspace_id == ws_id)
    )).scalars().all()
    assert len(rows) == 1
    new_conv = rows[0]
    assert new_conv.agent_type == "coding"
    assert new_conv.user_id == 42
    assert new_conv.tenant_id == tenant.id
    assert new_conv.workspace_id == ws_id


# ---------------------------------------------------------------------------
# 3. 孤儿 workspace，meta 缺 user_id/tenant_id → archived
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orphan_no_owner_gets_archived(db_session, tmp_path, monkeypatch):
    """meta 缺 user_id 或 tenant_id 的孤儿 workspace → 打 archived 标记, 目录仍在。"""
    ws_id = "3_cccccccc"
    ws_path = _make_ws_dir(tmp_path, ws_id, {
        # 故意不写 user_id / tenant_id
        "project_type": "form-component-dual",
        "display_name": "无主",
    })

    from app.coding import migrate_orphan_workspaces as mod
    monkeypatch.setattr(mod, "WORKSPACE_SEARCH_ROOTS", (tmp_path,))

    result = await mod.migrate_orphan_workspaces(db_session)
    assert result["archived"] == 1
    assert result["migrated"] == 0

    # 目录未被删
    assert ws_path.exists()

    # .workspace.json 中有 archived=true
    meta = json.loads((ws_path / ".workspace.json").read_text())
    assert meta.get("archived") is True

    # DB 没有新增会话
    rows = (await db_session.execute(
        select(Conversation).where(Conversation.workspace_id == ws_id)
    )).scalars().all()
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# 4. 幂等：跑两遍，结果不变
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migrate_is_idempotent(db_session, tmp_path, monkeypatch):
    """跑两遍：孤儿只补建一次 Conversation，有主的仍然跳过，归档的不重复归档。"""
    tenant = Tenant(tenant_name="t_idem", tenant_code="t_idem")
    db_session.add(tenant)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(tenant)

    # workspace A：孤儿 + 有 owner
    ws_a = "10_aaaaaaaa"
    _make_ws_dir(tmp_path, ws_a, {
        "user_id": 99,
        "tenant_id": tenant.id,
        "project_type": "form-page",
        "display_name": "幂等测试A",
    })

    # workspace B：已有会话
    ws_b = "10_bbbbbbbb"
    conv_b = Conversation(
        user_id=99, tenant_id=tenant.id,
        title="已有B", agent_type="coding", workspace_id=ws_b,
    )
    db_session.add(conv_b)
    await db_session.commit()
    _make_ws_dir(tmp_path, ws_b, {
        "user_id": 99,
        "tenant_id": tenant.id,
        "project_type": "form-page",
        "display_name": "幂等测试B",
    })

    from app.coding import migrate_orphan_workspaces as mod
    monkeypatch.setattr(mod, "WORKSPACE_SEARCH_ROOTS", (tmp_path,))

    # 第一次
    r1 = await mod.migrate_orphan_workspaces(db_session)
    assert r1["migrated"] == 1
    assert r1["skipped"] == 1

    # 第二次
    r2 = await mod.migrate_orphan_workspaces(db_session)
    assert r2["migrated"] == 0   # 已有会话，跳过
    assert r2["skipped"] == 2    # ws_a 现在也有会话了，ws_b 继续跳过

    # ws_a 只有 1 个会话
    rows_a = (await db_session.execute(
        select(Conversation).where(Conversation.workspace_id == ws_a)
    )).scalars().all()
    assert len(rows_a) == 1


# ---------------------------------------------------------------------------
# 5. 混合场景：有主 + 孤儿 + 无主孤儿
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mixed_scenario(db_session, tmp_path, monkeypatch):
    """混合场景：有主 1 个 + 孤儿(有 owner) 1 个 + 孤儿(无 owner) 1 个。"""
    tenant = Tenant(tenant_name="t_mix", tenant_code="t_mix")
    db_session.add(tenant)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(tenant)

    # ws1: 已有会话
    ws1 = "20_11111111"
    conv1 = Conversation(
        user_id=1, tenant_id=tenant.id,
        title="已有", agent_type="coding", workspace_id=ws1,
    )
    db_session.add(conv1)
    await db_session.commit()
    _make_ws_dir(tmp_path, ws1, {"user_id": 1, "tenant_id": tenant.id, "project_type": "form-page"})

    # ws2: 孤儿，有 owner
    ws2 = "20_22222222"
    _make_ws_dir(tmp_path, ws2, {"user_id": 1, "tenant_id": tenant.id, "project_type": "form-page"})

    # ws3: 孤儿，无 owner
    ws3 = "20_33333333"
    ws3_path = _make_ws_dir(tmp_path, ws3, {"project_type": "form-page"})

    from app.coding import migrate_orphan_workspaces as mod
    monkeypatch.setattr(mod, "WORKSPACE_SEARCH_ROOTS", (tmp_path,))

    result = await mod.migrate_orphan_workspaces(db_session)
    assert result["skipped"] == 1
    assert result["migrated"] == 1
    assert result["archived"] == 1

    # 所有目录仍存在
    for ws_id_val, root_for_check in [(ws1, tmp_path), (ws2, tmp_path), (ws3, tmp_path)]:
        folder = f"form-component-custom__{ws_id_val}"
        assert (tmp_path / folder).exists() or any(
            (tmp_path / d).exists()
            for d in [f"form-component-custom__{ws_id_val}", f"form-page__{ws_id_val}"]
        )
    assert ws3_path.exists()
    meta3 = json.loads((ws3_path / ".workspace.json").read_text())
    assert meta3.get("archived") is True
