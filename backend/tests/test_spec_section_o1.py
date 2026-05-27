"""SpecSection O1 — unit tests.

Coverage:
  test_create_spec_section
  test_read_nonexistent_returns_exists_false
  test_update_increments_draft_version
  test_unique_constraint              (同 app+type+key 第 2 次 INSERT 抛 IntegrityError)
  test_init_from_apaas_form           (mock query_detail_page_config, 验 base_version=1)
  test_init_from_apaas_already_exists (重复 init 返 already_exists=True)
  test_init_from_apaas_not_implemented (process / page 类返 NOT_IMPLEMENTED)
  test_diff_form_fields_logic         (纯函数 _diff_form_fields)
  test_diff_form_fields_via_tool      (mock apaas, 验 add/update/remove)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

# 导入触发 model 注册
import app.models  # noqa: F401
from app.database import Base
from app.models import Application, SpecSection, PlatformEnv
from app.models.tenant import Tenant
from app.mcp_spec_sections import (
    read_spec_section,
    init_spec_section_from_apaas,
    update_spec_section,
    diff_spec_vs_apaas,
    _diff_form_fields,
    _form_apaas_to_spec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Per-test 全新 in-memory SQLite + 完整 schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_app(db: AsyncSession) -> Application:
    """A bare Application row to satisfy spec_sections.application_id FK."""
    tenant = Tenant(
        id=1,
        tenant_code="t1",
        tenant_name="Test Tenant",
        created_at=datetime.utcnow(),
    )
    db.add(tenant)
    await db.commit()
    app = Application(
        user_id=1,
        tenant_id=1,
        created_by=1,
        app_name="Demo",
        app_code="demo",
        apaas_app_id="apaas-1",
        platform_env_id=None,
        status="draft",
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


@pytest_asyncio.fixture
async def seeded_env(db: AsyncSession) -> PlatformEnv:
    """A PlatformEnv row with a non-empty token (used by init/diff)."""
    env = PlatformEnv(
        tenant_id=1,
        env_name="prod",
        base_url="http://apaas.example.com",
        platform_tenant_id="apaas-tenant-1",
        token="fake-token",
        status="connected",
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return env


# ---------------------------------------------------------------------------
# 1. test_create_spec_section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_spec_section(db: AsyncSession, seeded_app: Application):
    """直接创建 ORM 行, 验字段默认值符合 spec."""
    row = SpecSection(
        application_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json='{"type":"form","fields":[]}',
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    assert row.id is not None
    assert row.base_version == 0
    assert row.draft_version == 1
    assert row.last_applied_at is None
    assert row.created_at is not None
    assert row.updated_at is not None


# ---------------------------------------------------------------------------
# 2. test_read_nonexistent_returns_exists_false
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_nonexistent_returns_exists_false(
    db: AsyncSession, seeded_app: Application
):
    result = await read_spec_section(db, seeded_app.id, "form", "missing-form")
    assert result["ok"] is True
    assert result["exists"] is False
    assert "init_spec_section_from_apaas" in result["hint"]


# ---------------------------------------------------------------------------
# 3. test_update_increments_draft_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_increments_draft_version(
    db: AsyncSession, seeded_app: Application
):
    # 先建一条
    row = SpecSection(
        application_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json='{"fields":[]}',
        draft_version=1,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    assert row.draft_version == 1

    new_spec = {"type": "form", "fields": [{"code": "name", "label": "姓名"}]}
    r1 = await update_spec_section(
        db,
        app_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json=new_spec,
        diff_summary="加字段 name",
    )
    assert r1["ok"] is True
    assert r1["section"]["draft_version"] == 2
    assert r1["section"]["spec_json"]["fields"][0]["code"] == "name"

    # 第 2 次 update → 3
    r2 = await update_spec_section(
        db,
        app_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json=new_spec,
    )
    assert r2["section"]["draft_version"] == 3


# ---------------------------------------------------------------------------
# 4. test_unique_constraint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unique_constraint(db: AsyncSession, seeded_app: Application):
    row1 = SpecSection(
        application_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json="{}",
    )
    db.add(row1)
    await db.commit()

    row2 = SpecSection(
        application_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json="{}",
    )
    db.add(row2)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# ---------------------------------------------------------------------------
# 5. test_init_from_apaas_form
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_from_apaas_form(
    db: AsyncSession,
    seeded_app: Application,
    seeded_env: PlatformEnv,
    monkeypatch,
):
    """Mock query_detail_page_config → 验 init 落表 base_version=1."""
    fake_apaas_payload = {
        "detailPage": {
            "formId": "form-1",
            "formName": "客户表单",
            "formComponents": [
                {"componentCode": "name", "componentLabel": "姓名", "componentType": "input", "required": True},
                {"componentCode": "age", "componentLabel": "年龄", "componentType": "number"},
            ],
        }
    }

    async def fake_query_detail_page_config(self, app_id, form_id):
        assert app_id == "apaas-1"
        assert form_id == "form-1"
        return fake_apaas_payload

    monkeypatch.setattr(
        "app.apaas_client.APaaSClient.query_detail_page_config",
        fake_query_detail_page_config,
    )

    result = await init_spec_section_from_apaas(
        db,
        env_id=seeded_env.id,
        apaas_app_id="apaas-1",
        app_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
    )
    assert result["ok"] is True
    assert result["already_exists"] is False
    sec = result["section"]
    assert sec["base_version"] == 1
    assert sec["draft_version"] == 1
    assert sec["spec_json"]["type"] == "form"
    assert sec["spec_json"]["form_name"] == "客户表单"
    codes = [f["code"] for f in sec["spec_json"]["fields"]]
    assert codes == ["name", "age"]
    assert sec["spec_json"]["fields"][0]["required"] is True


# ---------------------------------------------------------------------------
# 6. test_init_from_apaas_already_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_from_apaas_already_exists(
    db: AsyncSession,
    seeded_app: Application,
    seeded_env: PlatformEnv,
    monkeypatch,
):
    # 先 manually 落一条
    row = SpecSection(
        application_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json=json.dumps({"type": "form", "fields": []}),
        base_version=1,
        draft_version=5,
    )
    db.add(row)
    await db.commit()

    # apaas mock 不该被调到（已存在直接返回）
    call_count = {"n": 0}

    async def should_not_be_called(self, app_id, form_id):
        call_count["n"] += 1
        return {}

    monkeypatch.setattr(
        "app.apaas_client.APaaSClient.query_detail_page_config",
        should_not_be_called,
    )

    result = await init_spec_section_from_apaas(
        db,
        env_id=seeded_env.id,
        apaas_app_id="apaas-1",
        app_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
    )
    assert result["ok"] is True
    assert result["already_exists"] is True
    assert result["section"]["draft_version"] == 5
    assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# 7. test_init_from_apaas_not_implemented
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_from_apaas_not_implemented(
    db: AsyncSession, seeded_app: Application, seeded_env: PlatformEnv
):
    for section_type in ("process", "list", "page", "permission"):
        result = await init_spec_section_from_apaas(
            db,
            env_id=seeded_env.id,
            apaas_app_id="apaas-1",
            app_id=seeded_app.id,
            section_type=section_type,
            section_key="x",
        )
        assert result["ok"] is False, section_type
        assert result["error_code"] == "NOT_IMPLEMENTED", section_type


# ---------------------------------------------------------------------------
# 8. test_diff_form_fields_logic (pure function)
# ---------------------------------------------------------------------------


def test_diff_form_fields_logic():
    spec = {
        "fields": [
            {"code": "name", "label": "姓名", "widget": "input", "required": True},
            {"code": "phone", "label": "手机", "widget": "input", "required": False},  # new
            {"code": "age", "label": "年龄", "widget": "number", "required": True},     # label changed
        ]
    }
    apaas = {
        "fields": [
            {"code": "name", "label": "姓名", "widget": "input", "required": True},  # same
            {"code": "age", "label": "Age", "widget": "number", "required": True},   # label diff
            {"code": "address", "label": "地址", "widget": "input", "required": False}, # to remove
        ]
    }
    diff = _diff_form_fields(spec, apaas)
    add_codes = [f["code"] for f in diff["add"]]
    update_codes = [u["code"] for u in diff["update"]]
    remove_codes = [f["code"] for f in diff["remove"]]
    assert add_codes == ["phone"]
    assert update_codes == ["age"]
    assert "label" in diff["update"][0]["changes"]
    assert diff["update"][0]["changes"]["label"]["from"] == "Age"
    assert diff["update"][0]["changes"]["label"]["to"] == "年龄"
    assert remove_codes == ["address"]


# ---------------------------------------------------------------------------
# 9. test_diff_form_fields_via_tool (mock apaas)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_form_fields_via_tool(
    db: AsyncSession,
    seeded_app: Application,
    seeded_env: PlatformEnv,
    monkeypatch,
):
    # 草稿: name + phone
    spec = {
        "type": "form",
        "form_id": "form-1",
        "fields": [
            {"code": "name", "label": "姓名", "widget": "input", "required": True},
            {"code": "phone", "label": "手机", "widget": "input", "required": False},
        ],
    }
    row = SpecSection(
        application_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        spec_json=json.dumps(spec, ensure_ascii=False),
        base_version=1,
        draft_version=2,
    )
    db.add(row)
    await db.commit()

    # apaas 上: name (same) + address (to be removed in spec) — 草稿应该 add phone, remove address
    fake_apaas_payload = {
        "detailPage": {
            "formId": "form-1",
            "formName": "客户表单",
            "formComponents": [
                {"componentCode": "name", "componentLabel": "姓名", "componentType": "input", "required": True},
                {"componentCode": "address", "componentLabel": "地址", "componentType": "input"},
            ],
        }
    }

    async def fake_query(self, app_id, form_id):
        return fake_apaas_payload

    monkeypatch.setattr(
        "app.apaas_client.APaaSClient.query_detail_page_config", fake_query
    )

    result = await diff_spec_vs_apaas(
        db,
        app_id=seeded_app.id,
        section_type="form",
        section_key="form-1",
        env_id=seeded_env.id,
        apaas_app_id="apaas-1",
    )
    assert result["ok"] is True
    diff = result["diff"]
    assert [f["code"] for f in diff["add"]] == ["phone"]
    assert [f["code"] for f in diff["remove"]] == ["address"]
    assert diff["update"] == []  # name 完全一致


# ---------------------------------------------------------------------------
# Edge case: read with invalid section_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_section_type_rejected(
    db: AsyncSession, seeded_app: Application
):
    result = await read_spec_section(db, seeded_app.id, "garbage", "x")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_SECTION_TYPE"
