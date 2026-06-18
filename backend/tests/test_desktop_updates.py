"""桌面更新托管端点测试。GET 不鉴权; 文件名白名单防穿越; POST 需平台管理员。"""
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

import app.config as config_mod


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    # 把更新目录指到临时目录
    monkeypatch.setattr(config_mod.settings, "desktop_updates_dir", str(tmp_path))
    from app.routes import desktop_updates
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(desktop_updates.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path


@pytest.mark.asyncio
async def test_latest_json_404_when_absent(client):
    c, _ = client
    resp = await c.get("/desktop-updates/latest.json")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_latest_json_served_when_present(client):
    c, tmp = client
    (tmp / "latest.json").write_text(json.dumps({"version": "0.2.0", "platforms": {}}), encoding="utf-8")
    resp = await c.get("/desktop-updates/latest.json")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.2.0"


@pytest.mark.asyncio
async def test_package_served(client):
    c, tmp = client
    (tmp / "ruijing-0.2.0-aarch64.app.tar.gz").write_bytes(b"PKGDATA")
    resp = await c.get("/desktop-updates/ruijing-0.2.0-aarch64.app.tar.gz")
    assert resp.status_code == 200
    assert resp.content == b"PKGDATA"


@pytest.mark.asyncio
async def test_package_path_traversal_rejected(client):
    c, _ = client
    resp = await c.get("/desktop-updates/..%2f..%2fetc%2fpasswd")
    assert resp.status_code in (400, 404)


@pytest.mark.asyncio
async def test_package_bad_name_rejected(client):
    c, tmp = client
    (tmp / "evil.sh").write_text("x", encoding="utf-8")
    resp = await c.get("/desktop-updates/evil.sh")
    assert resp.status_code == 400


# ── 发版上传(平台管理员) ──────────────────────────────────────
import app.database as database  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from app.auth import create_access_token, get_password_hash  # noqa: E402
from app.models import User  # noqa: E402


@pytest_asyncio.fixture
async def admin_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "desktop_updates_dir", str(tmp_path))
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    async with Session() as s:
        admin = User(
            username="pubadmin", display_name="A",
            hashed_password=get_password_hash("adminpass123"),
            is_active=True, is_platform_admin=True, account_source="desktop",
        )
        s.add(admin)
        await s.flush()
        aid = admin.id
        await s.commit()
    token = create_access_token(aid, tenant_id=None)

    from app.routes import desktop_updates
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(desktop_updates.router)

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_publish_requires_platform_admin(client):
    c, _ = client  # 无 token 的普通 client
    resp = await c.post(
        "/desktop-updates/admin/publish",
        data={"manifest": json.dumps({"version": "0.2.0", "platforms": {}})},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_publish_writes_manifest_and_packages(admin_client):
    c, tmp = admin_client
    manifest = json.dumps({"version": "0.2.0", "platforms": {"darwin-aarch64": {"signature": "s", "url": "u"}}})
    files = [("packages", ("ruijing-0.2.0-aarch64.app.tar.gz", b"PKG", "application/gzip"))]
    resp = await c.post("/desktop-updates/admin/publish", data={"manifest": manifest}, files=files)
    assert resp.status_code == 200, resp.text
    assert (tmp / "latest.json").is_file()
    assert (tmp / "ruijing-0.2.0-aarch64.app.tar.gz").read_bytes() == b"PKG"


@pytest.mark.asyncio
async def test_publish_rejects_bad_manifest(admin_client):
    c, _ = admin_client
    resp = await c.post("/desktop-updates/admin/publish", data={"manifest": "{not json"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_publish_rejects_bad_package_name(admin_client):
    c, _ = admin_client
    manifest = json.dumps({"version": "0.2.0", "platforms": {}})
    files = [("packages", ("evil.sh", b"x", "text/plain"))]
    resp = await c.post("/desktop-updates/admin/publish", data={"manifest": manifest}, files=files)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_history_requires_platform_admin(client):
    c, _ = client
    resp = await c.get("/desktop-updates/admin/history")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_history_records_published_version_with_notes(admin_client):
    c, _ = admin_client
    manifest = json.dumps({"version": "0.3.0", "notes": "新功能", "pub_date": "2026-06-17T00:00:00Z",
                           "platforms": {"darwin-aarch64": {"signature": "s", "url": "u"}}})
    files = [("packages", ("ruijing-0.3.0-aarch64.app.tar.gz", b"PKG", "application/gzip"))]
    await c.post("/desktop-updates/admin/publish", data={"manifest": manifest}, files=files)
    resp = await c.get("/desktop-updates/admin/history")
    assert resp.status_code == 200
    rows = resp.json()
    row = next(r for r in rows if r["version"] == "0.3.0")
    assert row["notes"] == "新功能"
    assert row["is_latest"] is True
    assert row["packages"]["aarch64"] == "ruijing-0.3.0-aarch64.app.tar.gz"


@pytest.mark.asyncio
async def test_history_backfills_versions_from_package_files(admin_client):
    c, tmp = admin_client
    # 直接放一个没有 history 记录的旧版本包文件
    (tmp / "ruijing-0.1.9-x86_64.app.tar.gz").write_bytes(b"OLD")
    resp = await c.get("/desktop-updates/admin/history")
    rows = resp.json()
    vers = [r["version"] for r in rows]
    assert "0.1.9" in vers


@pytest.mark.asyncio
async def test_history_sorted_newest_first(admin_client):
    c, tmp = admin_client
    for v in ["0.2.9", "0.2.10", "0.2.1"]:
        (tmp / f"ruijing-{v}-aarch64.app.tar.gz").write_bytes(b"X")
    rows = (await c.get("/desktop-updates/admin/history")).json()
    vers = [r["version"] for r in rows]
    # 0.2.10 应排在 0.2.9 之前(语义化, 非字符串排序)
    assert vers.index("0.2.10") < vers.index("0.2.9")
