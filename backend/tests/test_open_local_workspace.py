import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

import app.database as database
from app.database import Base


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    from app.main import app
    from app.database import get_db
    from app.deps import get_auth_context, AuthContext
    async def _get_db():
        async with Session() as s:
            yield s
    async def _ctx():
        from app.models import User
        # AuthContext fields: user, tenant_id, tenant_role, org_permissions, apaas_user_id (opt), apaas_tenant_id (opt)
        # User model has no tenant_id column — tenant_id lives on AuthContext, not User
        return AuthContext(
            user=User(id=1, username="t"),
            tenant_id=1,
            tenant_role="tenant_admin",
            org_permissions={"*": True},
        )
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_context] = _ctx
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_open_local_creates_and_dedups(client, tmp_path, monkeypatch):
    # tmp_path on macOS resolves under /private/var (blocked by sensitive-root check);
    # patch _is_sensitive_dir so this test focuses on the DB create+dedup logic.
    import app.routes.coding as coding_mod
    monkeypatch.setattr(coding_mod, "_is_sensitive_dir", lambda p: False)
    r1 = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r1.status_code == 200
    ws_id = r1.json()["ws_id"]
    r2 = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r2.status_code == 200 and r2.json()["ws_id"] == ws_id


@pytest.mark.asyncio
async def test_open_local_rejects_sensitive(client):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(Path.home())})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_missing(client, tmp_path):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path / "nope")})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_symlinked_system_dir(client):
    # /etc resolves to /private/etc on macOS — must still be blocked via ancestry check
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": "/etc"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_users_root(client):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": "/Users"})
    assert r.status_code == 400


def test_sensitive_path_policy():
    from pathlib import Path
    from app.routes.coding import _is_sensitive_path
    # 合法: 家目录下的真实项目路径 — 绝不能被拦(这是 /Users 祖先误拦回归点)
    assert _is_sensitive_path(Path("/Users/alice/projects/myapp")) is False
    assert _is_sensitive_path(Path("/Users/alice/dev/x")) is False
    # 拦: 裸 /Users / 文件系统根 / 系统目录(含 macOS 符号链接 resolve 后形态)
    assert _is_sensitive_path(Path("/Users")) is True
    assert _is_sensitive_path(Path("/")) is True
    assert _is_sensitive_path(Path("/private/etc")) is True
    assert _is_sensitive_path(Path("/private/var/folders/xx/T")) is True
    assert _is_sensitive_path(Path("/System/Library")) is True
    assert _is_sensitive_path(Path("/usr/local")) is True


@pytest.mark.asyncio
async def test_list_includes_external(client, tmp_path, monkeypatch):
    # tmp_path 在 macOS 上 resolve 到 /private/var/... 会被敏感目录拦; 注册时放行以测列表合并
    import app.routes.coding as coding_mod
    monkeypatch.setattr(coding_mod, "_is_sensitive_dir", lambda p: False)
    await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    r = await client.get("/api/coding/workspaces")
    assert r.status_code == 200
    items = r.json()
    ext = [w for w in items if w.get("workspace_type") == "external"]
    assert len(ext) == 1 and ext[0]["disk_path"] == str(tmp_path.resolve())
    assert ext[0]["status"] == "local"
    assert ext[0]["project_name"] == tmp_path.name


@pytest.mark.asyncio
async def test_open_local_then_get_info_and_files(client, tmp_path, monkeypatch):
    """端到端: 打开本地文件夹后, 真正打开工作区(info/files)必须 200(回归: 曾因无 .workspace.json 404)。"""
    import app.routes.coding as coding_mod
    monkeypatch.setattr(coding_mod, "_is_sensitive_dir", lambda p: False)
    (tmp_path / "hello.txt").write_text("hi")
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r.status_code == 200
    ws_id = r.json()["ws_id"]
    info = await client.get(f"/api/coding/workspace/{ws_id}")
    assert info.status_code == 200, info.text
    files = await client.get(f"/api/coding/workspace/{ws_id}/files")
    assert files.status_code == 200, files.text
