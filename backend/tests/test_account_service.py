import hashlib
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import User
from app.auth import get_password_hash, verify_password
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def account_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


def test_new_hash_is_bcrypt_and_verifies():
    h = get_password_hash("ruijing2026")
    assert h.startswith("$2")  # bcrypt 前缀
    assert verify_password("ruijing2026", h) is True
    assert verify_password("wrong", h) is False


def test_legacy_sha256_still_verifies():
    # 旧账号库里是裸 sha256 hexdigest
    legacy = hashlib.sha256("oldpw".encode()).hexdigest()
    assert verify_password("oldpw", legacy) is True
    assert verify_password("wrong", legacy) is False


@pytest.mark.asyncio
async def test_same_username_different_source_coexist(account_db):
    account_db.add(User(username="zhangsan", hashed_password="x", account_source="desktop"))
    account_db.add(User(username="zhangsan", hashed_password="y", account_source="apaas"))
    await account_db.flush()  # 复合唯一下不该抛 IntegrityError
    rows = (await account_db.execute(select(User).where(User.username == "zhangsan"))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_apaas_login_does_not_clobber_desktop_user(account_db):
    from app.routes.auth.login import _ensure_apaas_user
    desktop = User(username="li", hashed_password="desk", account_source="desktop", is_platform_admin=True)
    account_db.add(desktop)
    await account_db.flush()
    # aPaaS 登录同名 li → 应新建一行 apaas, 不动 desktop 行
    await _ensure_apaas_user(account_db, "li", "apaaspw", {"id": "999"}, is_platform_admin=False)
    await account_db.flush()
    rows = (await account_db.execute(select(User).where(User.username == "li"))).scalars().all()
    assert len(rows) == 2
    desk = [r for r in rows if r.account_source == "desktop"][0]
    assert desk.hashed_password == "desk"  # 没被覆盖
    assert desk.is_platform_admin is True


@pytest_asyncio.fixture
async def account_client(monkeypatch):
    # 共享内存库 + monkeypatch AsyncSessionLocal, 让路由(get_db)和测试看同一个库
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.config.settings.public_account_base_url", "")  # authority
    from services.account_service.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, Session


@pytest.mark.asyncio
async def test_account_service_login_authority(account_client):
    c, Session = account_client
    from app import desktop_accounts as da
    async with Session() as db:
        await da.provision_desktop_account(db, "mars", "ruijing2026", is_platform_admin=True)
        await db.commit()
    # authority 登录
    r = await c.post("/api/desktop-auth/login", json={"username": "mars", "password": "ruijing2026"})
    assert r.status_code == 200
    assert r.json()["username"] == "mars"
    # 错密码
    r2 = await c.post("/api/desktop-auth/login", json={"username": "mars", "password": "x"})
    assert r2.status_code == 401


# ─── M2: bcrypt 72 字节截断 ──────────────────────────────────────────────────

def test_long_cjk_password_does_not_crash():
    """25 个中文字符 = 75 字节 > bcrypt 72 字节上限, 不应抛 ValueError。"""
    pw = "密" * 25
    h = get_password_hash(pw)          # 不该抛 ValueError
    assert h.startswith("$2")
    assert verify_password(pw, h) is True


# ─── M1: federation 撞名 (apaas 同名行共存) 不 MultipleResultsFound ────────────

@pytest.mark.asyncio
async def test_federation_mirror_with_apaas_namesake_no_crash(account_client):
    """federation 模式: 先有 apaas 同名行, 再 provision_desktop_account → 不应抛 AccountExistsError。
    login authority 模式下 verify_desktop_account 只认 desktop 行 → 正常登录。"""
    c, Session = account_client
    from app import desktop_accounts as da
    async with Session() as db:
        # 先放一个 apaas 同名账号 (模拟 aPaaS 登录同步过来的)
        db.add(User(username="dup", hashed_password="apaas-hash", account_source="apaas", is_active=True))
        await db.flush()
        # provision_desktop_account 应只检查 desktop 行, apaas 同名不应阻止
        await da.provision_desktop_account(db, "dup", "ruijing2026", is_platform_admin=False)
        await db.commit()
    # authority 模式登录 → verify_desktop_account 只认 desktop 行 → 成功
    r = await c.post("/api/desktop-auth/login", json={"username": "dup", "password": "ruijing2026"})
    assert r.status_code == 200
    assert r.json()["username"] == "dup"


# ─── Admin 后台: 列账号 / 改密 / 停用 ─────────────────────────────────────────


async def _provision_admin_and_token(c, Session, username="mars", password="ruijing2026"):
    """provision 一个平台管理员 + authority 登录拿 token。"""
    from app import desktop_accounts as da
    async with Session() as db:
        await da.provision_desktop_account(db, username, password, is_platform_admin=True)
        await db.commit()
    r = await c.post("/api/desktop-auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_list_accounts(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    # 开 2 个普通账号
    for u in ("alice", "bob"):
        r = await c.post("/api/desktop-auth/admin/accounts",
                         json={"username": u, "password": "ruijing2026"}, headers=hdr)
        assert r.status_code == 200, r.text
    # 列账号: mars + alice + bob = 3 项
    r = await c.get("/api/desktop-auth/admin/accounts", headers=hdr)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    by_name = {it["username"]: it for it in items}
    assert {"mars", "alice", "bob"} <= set(by_name)
    # 按 id 排序
    ids = [it["id"] for it in items]
    assert ids == sorted(ids)
    # 字段齐全 + 类型
    mars_item = by_name["mars"]
    assert mars_item["is_platform_admin"] is True
    assert mars_item["is_active"] is True
    assert isinstance(mars_item["tenant_id"], int)
    assert by_name["alice"]["is_platform_admin"] is False


@pytest.mark.asyncio
async def test_admin_list_only_desktop_accounts(account_client):
    """apaas 同名/非 desktop 行不应出现在列表里。"""
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    async with Session() as db:
        db.add(User(username="apaasonly", hashed_password="x", account_source="apaas", is_active=True))
        await db.commit()
    r = await c.get("/api/desktop-auth/admin/accounts", headers=hdr)
    assert r.status_code == 200
    names = {it["username"] for it in r.json()}
    assert "apaasonly" not in names


@pytest.mark.asyncio
async def test_admin_list_requires_platform_admin(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    # 开一个普通(非管理员)账号
    r = await c.post("/api/desktop-auth/admin/accounts",
                     json={"username": "plain", "password": "ruijing2026"}, headers=hdr)
    assert r.status_code == 200, r.text
    plain_token = (await c.post("/api/desktop-auth/login",
                                json={"username": "plain", "password": "ruijing2026"})).json()["access_token"]
    # 非管理员 → 403
    r = await c.get("/api/desktop-auth/admin/accounts",
                    headers={"Authorization": f"Bearer {plain_token}"})
    assert r.status_code == 403
    # 无 token → 401/403
    r = await c.get("/api/desktop-auth/admin/accounts")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_disable_account_blocks_login(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    await c.post("/api/desktop-auth/admin/accounts",
                 json={"username": "carol", "password": "ruijing2026"}, headers=hdr)
    # 停用前能登录
    assert (await c.post("/api/desktop-auth/login",
                         json={"username": "carol", "password": "ruijing2026"})).status_code == 200
    # PATCH disable
    r = await c.patch("/api/desktop-auth/admin/accounts/carol",
                      json={"action": "disable"}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
    assert r.json()["username"] == "carol"
    # 停用后 login 401
    assert (await c.post("/api/desktop-auth/login",
                         json={"username": "carol", "password": "ruijing2026"})).status_code == 401
    # enable 回来
    r = await c.patch("/api/desktop-auth/admin/accounts/carol",
                      json={"action": "enable"}, headers=hdr)
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    assert (await c.post("/api/desktop-auth/login",
                         json={"username": "carol", "password": "ruijing2026"})).status_code == 200


@pytest.mark.asyncio
async def test_admin_reset_password(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    await c.post("/api/desktop-auth/admin/accounts",
                 json={"username": "dave", "password": "oldpassw"}, headers=hdr)
    # 改密
    r = await c.patch("/api/desktop-auth/admin/accounts/dave",
                      json={"action": "reset_password", "password": "newpassw1"}, headers=hdr)
    assert r.status_code == 200, r.text
    # 新密码能登录
    assert (await c.post("/api/desktop-auth/login",
                         json={"username": "dave", "password": "newpassw1"})).status_code == 200
    # 旧密码 401
    assert (await c.post("/api/desktop-auth/login",
                         json={"username": "dave", "password": "oldpassw"})).status_code == 401


@pytest.mark.asyncio
async def test_admin_reset_password_too_short(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    await c.post("/api/desktop-auth/admin/accounts",
                 json={"username": "erin", "password": "ruijing2026"}, headers=hdr)
    r = await c.patch("/api/desktop-auth/admin/accounts/erin",
                      json={"action": "reset_password", "password": "short"}, headers=hdr)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_patch_unknown_user_404(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    r = await c.patch("/api/desktop-auth/admin/accounts/nobody",
                      json={"action": "disable"}, headers=hdr)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_ui_served(account_client):
    """/admin-ui 返回 self-contained HTML 页面。"""
    c, _ = account_client
    r = await c.get("/admin-ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "桌面账号管理" in r.text
    assert "/account-api" in r.text  # API 前缀变量在页内


@pytest.mark.asyncio
async def test_admin_patch_requires_platform_admin(account_client):
    c, Session = account_client
    token = await _provision_admin_and_token(c, Session)
    hdr = {"Authorization": f"Bearer {token}"}
    await c.post("/api/desktop-auth/admin/accounts",
                 json={"username": "frank", "password": "ruijing2026"}, headers=hdr)
    plain_token = (await c.post("/api/desktop-auth/login",
                                json={"username": "frank", "password": "ruijing2026"})).json()["access_token"]
    r = await c.patch("/api/desktop-auth/admin/accounts/frank",
                      json={"action": "disable"},
                      headers={"Authorization": f"Bearer {plain_token}"})
    assert r.status_code == 403
