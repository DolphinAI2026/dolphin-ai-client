# 桌面版近场硬伤加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清掉桌面版三件 P0 近场硬伤——撤加密旁路、引导式 onboarding、本地签票信任边界——让桌面壳「可对外、不被审计毙、装上即能用」。

**Architecture:** 三个独立工作块。Part 1/3 纯后端（加密密钥持久化 + JWT issuer 隔离 + 开号权限结构性强制），Part 2 前端为主（首次启动向导复用现成 platform_envs/llm_configs 接口 + 桌面功能边界用路由 meta 收敛）。建议实现顺序 Part 1 → Part 3 → Part 2。

**Tech Stack:** FastAPI / SQLAlchemy(async) / pydantic-settings / jose(JWT) / cryptography(Fernet) / pytest(+pytest-asyncio, StaticPool 内存库) ；Vue 3 `<script setup>` / vue-router / Element Plus / Pinia / Vitest。

**关联 spec:** `docs/superpowers/specs/2026-06-17-desktop-nearfield-hardening-design.md`

**分支:** `feat/desktop-login-mvp`（有未并 dev 的桌面工作；只动本计划相关文件，不扫入无关未提交改动）。

**测试命令约定:**
- 后端: `cd backend && .venv/bin/python -m pytest tests/<file>::<test> -v`（.venv 是 py3.13）
- 前端: `cd frontend && npx vitest run src/<path>.spec.ts`
- 桌面真机验证: 重打包 `scripts/build-desktop.sh`（~85s，先 `pkill -f "Builder.app/Contents/MacOS"`），或对 dev sidecar 端口用 chrome-devtools/playwright MCP 连 `http://127.0.0.1:<port>/` 渲染验证。

---

## File Structure

**Part 1（加密）**
- Modify: `backend/desktop_sidecar.py` — 加 `ensure_encryption_key`，build_env 删 `ALLOW_DEFAULT_ENCRYPTION_KEY`、加 `ENCRYPTION_KEY`
- Create: `backend/tests/test_desktop_sidecar.py`

**Part 3（信任边界）**
- Modify: `backend/app/config.py` — 加 `accepted_token_issuers` 字段 + `accepted_issuers_set` property
- Modify: `backend/app/auth.py` — 加 `_DESKTOP_ISSUER`、`create_access_token` 加 `issuer` 参、`decode_token` 校验 issuer、加 `assert_shared_backend_issuer_safety()`
- Modify: `backend/app/routes/desktop_auth.py` — `_federation_login` 签发传 desktop issuer
- Modify: `backend/desktop_sidecar.py` — build_env 设 `ACCEPTED_TOKEN_ISSUERS`
- Modify: `backend/app/main.py` — lifespan 调启动断言
- Modify: `backend/services/account_service/main.py` — lifespan 调启动断言
- Modify: `backend/app/desktop_accounts.py` — `provision_desktop_account` 去掉 `is_platform_admin` 参（恒 False），加 `provision_local_admin_account`
- Modify: `backend/scripts/seed_desktop_account.py` — 改调 `provision_local_admin_account`
- Create: `backend/tests/test_token_issuer.py`
- Modify: `backend/tests/test_desktop_accounts.py` — 补 provision 拆分断言

**Part 2（onboarding + 边界）**
- Create: `frontend/src/composables/useOnboardingState.ts` + `.spec.ts`
- Create: `frontend/src/views/DesktopSetupWizard.vue`
- Create: `frontend/src/views/DesktopUnavailable.vue`
- Modify: `frontend/src/router/index.ts` — 加 wizard/unavailable 路由 + `meta.desktop` + beforeEach 首启/边界守卫
- Modify: `frontend/src/components/v2/RailSidebar.vue` — 导航项读 `meta.desktop` 隐藏不可用项
- Create: `frontend/src/router/desktopGuard.ts` + `.spec.ts` — 抽出可测的守卫纯逻辑

---

## Part 1 — 撤加密旁路 + 持久化加密密钥

### Task 1: ensure_encryption_key + 撤旁路

**Files:**
- Modify: `backend/desktop_sidecar.py`
- Test: `backend/tests/test_desktop_sidecar.py`

**背景:** `crypto.py:10` 把 `settings.encryption_key` 做 `hashlib.sha256(...).digest()` 派生 Fernet key，所以 key 只需是高熵字符串（不是裸 Fernet key）。`main.py:59` 的安全门 `_insecure_keys = {"", "default-key-change-in-production-32b", "__GENERATE__"}`，`token_urlsafe(48)` 不在其中即合法放行。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_desktop_sidecar.py`:

```python
import desktop_sidecar


def test_ensure_encryption_key_persists_and_reuses(tmp_path):
    k1 = desktop_sidecar.ensure_encryption_key(tmp_path)
    assert k1 and k1 not in {"", "default-key-change-in-production-32b", "__GENERATE__"}
    # 0o600 权限
    mode = (tmp_path / "encryption_key").stat().st_mode & 0o777
    assert mode == 0o600
    # 二次调用复用同值
    assert desktop_sidecar.ensure_encryption_key(tmp_path) == k1


def test_build_env_sets_real_key_and_no_bypass(tmp_path):
    env = desktop_sidecar.build_env(data_dir=tmp_path, port=9999)
    assert "ALLOW_DEFAULT_ENCRYPTION_KEY" not in env
    assert env["ENCRYPTION_KEY"] and env["ENCRYPTION_KEY"] != "default-key-change-in-production-32b"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_sidecar.py -v`
Expected: FAIL（`ensure_encryption_key` 不存在 / build_env 仍含 ALLOW_DEFAULT）

- [ ] **Step 3: 实现 ensure_encryption_key + 改 build_env**

在 `backend/desktop_sidecar.py` 的 `ensure_jwt_secret` 之后加：

```python
def ensure_encryption_key(data_dir: Path) -> str:
    """每安装实例持久化一个加密主密钥 (Fernet key 由 crypto.py 对它 sha256 派生)。

    替掉 Phase 0 的 ALLOW_DEFAULT_ENCRYPTION_KEY 旁路: 用真实高熵 key, 让 main.py
    的加密安全门合法放行, 而非被绕过。
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "encryption_key"
    if f.is_file():
        existing = f.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    val = secrets.token_urlsafe(48)
    f.write_text(val, encoding="utf-8")
    f.chmod(0o600)
    return val
```

在 `build_env` 的 `written` 字典里，**删除**这一行：

```python
        # Phase 0 spike: 允许默认加密 key。Phase 1 改为每实例生成持久化 ENCRYPTION_KEY。
        "ALLOW_DEFAULT_ENCRYPTION_KEY": "1",
```

替换为：

```python
        # 每实例持久化的加密主密钥 (crypto.py 对它 sha256 派生 Fernet key)。
        "ENCRYPTION_KEY": ensure_encryption_key(data_dir),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_sidecar.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/desktop_sidecar.py backend/tests/test_desktop_sidecar.py
git commit -m "fix(desktop): 撤加密旁路 — 每实例持久化 ENCRYPTION_KEY 替掉 ALLOW_DEFAULT

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**迁移说明（执行者知会即可，不写代码）:** 既有 dogfood 实例旧凭据用默认 key 加密，换 key 后 test/login 解密失败→由 Part 2 向导/配置页重填一次（既定共识：当前凭据为 throwaway）。`platform_envs`/`llm_configs` 的 list 不解密，列表不会 500；解密只发生在 test/use，失败表现为「测试失败」可读提示。

---

## Part 2 — 信任边界（后端，对应 spec Part 3）

> 注: 实现顺序上这部分先于 onboarding（同属后端、且守安全单点）。

### Task 2: accepted_token_issuers 配置 + decode_token 校验 issuer

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/auth.py:81`（`decode_token`）
- Test: `backend/tests/test_token_issuer.py`

**背景:** 当前 authority 票与本地 federation 票共用 `iss="ai-builder"`，共享后端分不出本地票。设计 = 本地票打独立 issuer `desktop-sidecar`，共享后端只认自身 issuer。本任务先建「接受 issuer 白名单 + decode 校验」，默认只认 `ai-builder`。用 CSV 字符串字段 + property 拆分，避开 pydantic list-from-env 解析坑。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_token_issuer.py`:

```python
import pytest
from jose import JWTError

from app import auth


def _token(monkeypatch, issuer):
    monkeypatch.setattr("app.config.settings.jwt_secret_key", "test-secret-xyz")
    return auth.create_access_token(1, tenant_id=1, issuer=issuer)


def test_decode_accepts_default_issuer(monkeypatch):
    monkeypatch.setattr("app.config.settings.jwt_secret_key", "test-secret-xyz")
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    tok = auth.create_access_token(1, tenant_id=1)  # 默认 iss=ai-builder
    payload = auth.decode_token(tok)
    assert payload["iss"] == "ai-builder"


def test_decode_rejects_desktop_issuer_on_shared_backend(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    tok = _token(monkeypatch, "desktop-sidecar")
    with pytest.raises(JWTError):
        auth.decode_token(tok)


def test_decode_accepts_desktop_issuer_when_whitelisted(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,desktop-sidecar")
    tok = _token(monkeypatch, "desktop-sidecar")
    payload = auth.decode_token(tok)
    assert payload["iss"] == "desktop-sidecar"
```

（`create_access_token` 的 `issuer` 参在 Task 3 加；本任务先让 decode 校验逻辑就位。为让本任务测试可独立跑，先在 Step 3 同时加 `issuer` 参的最小版——见下。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_token_issuer.py -v`
Expected: FAIL（`accepted_token_issuers` 不存在 / `create_access_token` 不收 issuer / decode 不校验）

- [ ] **Step 3: 加配置字段 + decode 校验 + create_access_token issuer 参**

在 `backend/app/config.py` 的 Settings 里，`jwt_expire_minutes` 附近加：

```python
    # 接受的 JWT issuer 白名单 (CSV)。共享后端默认只认 ai-builder; 桌面 sidecar
    # 经 env ACCEPTED_TOKEN_ISSUERS 设为 "ai-builder,desktop-sidecar"。
    accepted_token_issuers: str = "ai-builder"
```

在 Settings 类体内加 property：

```python
    @property
    def accepted_issuers_set(self) -> set[str]:
        return {s.strip() for s in self.accepted_token_issuers.split(",") if s.strip()}
```

在 `backend/app/auth.py` 改 `decode_token`：

```python
def decode_token(token: str) -> dict:
    """解 ai-builder JWT。验签 + exp + issuer 白名单，但不验 aud（旧 JWT 没 aud）。

    issuer 不在 settings.accepted_issuers_set 内 → 抛 JWTError (共享后端拒收本地签票)。
    抛 JWTError 由调用方接住转 401。
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )
    iss = payload.get("iss")
    if iss not in settings.accepted_issuers_set:
        raise JWTError(f"issuer not accepted: {iss}")
    return payload
```

在 `backend/app/auth.py` 顶部常量区加（Task 3 会用到，先放）：

```python
_DESKTOP_ISSUER = "desktop-sidecar"
```

给 `create_access_token` 加 `issuer` 参数：签名行加 `issuer: str = _ISSUER`（放在 `username` 参之后），payload 里 `"iss": _ISSUER` 改成 `"iss": issuer`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_token_issuer.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 回归——全量 auth 相关测试不被 issuer 校验误伤**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_federation.py tests/test_account_service.py tests/test_account_service_federation.py tests/test_auth_context_from_token_permissions.py -v`
Expected: PASS（这些票都是 `ai-builder` issuer，默认白名单含它，不受影响）。若有失败，多半是测试里 monkeypatch 了 settings 但漏 `accepted_token_issuers`——按现象修测试，不放宽校验。

- [ ] **Step 6: 提交**

```bash
git add backend/app/config.py backend/app/auth.py backend/tests/test_token_issuer.py
git commit -m "feat(desktop): JWT issuer 白名单 — decode_token 校验 iss, 默认只认 ai-builder

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 3: 本地 federation 票打 desktop-sidecar issuer + sidecar 接受白名单

**Files:**
- Modify: `backend/app/routes/desktop_auth.py:71`（`_federation_login`）
- Modify: `backend/desktop_sidecar.py`（build_env 设 `ACCEPTED_TOKEN_ISSUERS`）
- Test: `backend/tests/test_desktop_auth_federation.py`（补 1 个）、`backend/tests/test_desktop_sidecar.py`（补 1 个）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_desktop_auth_federation.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_federation_token_has_desktop_issuer(client, monkeypatch):
    """联邦本地签的票 issuer=desktop-sidecar, 不与 authority 共用 ai-builder。"""
    from app.auth import decode_token

    async def fake_remote(base_url, username, password):
        return {"username": username}
    monkeypatch.setattr("app.routes.desktop_auth._remote_authenticate", fake_remote)
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,desktop-sidecar")

    r = await client.post("/api/desktop-auth/login", json={"username": "iris", "password": "x"})
    assert r.status_code == 200
    payload = decode_token(r.json()["access_token"])
    assert payload["iss"] == "desktop-sidecar"
```

在 `backend/tests/test_desktop_sidecar.py` 追加：

```python
def test_build_env_sets_accepted_issuers(tmp_path):
    env = desktop_sidecar.build_env(data_dir=tmp_path, port=9999)
    assert env["ACCEPTED_TOKEN_ISSUERS"] == "ai-builder,desktop-sidecar"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_federation.py::test_federation_token_has_desktop_issuer tests/test_desktop_sidecar.py::test_build_env_sets_accepted_issuers -v`
Expected: FAIL（issuer 仍是 ai-builder / env 无 ACCEPTED_TOKEN_ISSUERS）

- [ ] **Step 3: 实现**

`backend/app/routes/desktop_auth.py` 顶部 import 加 `_DESKTOP_ISSUER`：

```python
from app.auth import create_access_token, get_password_hash, _DESKTOP_ISSUER
```

`_federation_login` 里的签发行（`desktop_auth.py:71`）改为：

```python
    token = create_access_token(user, tenant_id=tenant_id, issuer=_DESKTOP_ISSUER)
```

（`_authority_login` 不改——authority 在公网 account-service 跑，签 `ai-builder`。）

`backend/desktop_sidecar.py` 的 `build_env` `written` 字典加：

```python
        # 桌面 sidecar 接受 ai-builder(内部短票)+ desktop-sidecar(联邦会话票)。
        "ACCEPTED_TOKEN_ISSUERS": "ai-builder,desktop-sidecar",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_federation.py tests/test_desktop_sidecar.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/routes/desktop_auth.py backend/desktop_sidecar.py backend/tests/test_desktop_auth_federation.py backend/tests/test_desktop_sidecar.py
git commit -m "feat(desktop): 联邦本地票打 desktop-sidecar issuer + sidecar 接受白名单

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 4: 共享后端启动断言（铁律代码化）

**Files:**
- Modify: `backend/app/auth.py`（加 `assert_shared_backend_issuer_safety`）
- Modify: `backend/app/main.py`（lifespan 调用）
- Modify: `backend/services/account_service/main.py`（lifespan 调用）
- Test: `backend/tests/test_token_issuer.py`（补 2 个）

**背景:** 铁律——共享后端（在线主后端 / account-service）绝不可接受本地 `desktop-sidecar` 票。用启动断言把它从约定变成 fail-fast。account-service 走自己的 `main.py`（非 app.main），故断言放共享 helper 两边调。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_token_issuer.py` 追加：

```python
def test_assert_rejects_desktop_issuer_on_shared_backend(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,desktop-sidecar")
    with pytest.raises(RuntimeError):
        auth.assert_shared_backend_issuer_safety()


def test_assert_passes_when_shared_backend_excludes_desktop(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    auth.assert_shared_backend_issuer_safety()  # 不抛
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_token_issuer.py -k assert -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现断言 + 两处 lifespan 接线**

`backend/app/auth.py` 末尾加：

```python
def assert_shared_backend_issuer_safety() -> None:
    """共享后端(在线主后端 / account-service)绝不可接受本地 sidecar 签的票。

    本地 sidecar 是单机信任域, 谁控进程谁能签票自提权。一旦共享后端接受
    desktop-sidecar issuer = 本地票可跨实例提权 = 毁掉整个信任边界。启动 fail-fast。
    """
    if _DESKTOP_ISSUER in settings.accepted_issuers_set:
        raise RuntimeError(
            f"共享后端拒绝启动: accepted_token_issuers 含 {_DESKTOP_ISSUER!r}, "
            "本地 sidecar 签的票绝不可被共享后端接受 (信任边界铁律)。"
        )
```

`backend/app/main.py` lifespan 里，在加密门之后加一行（仅非 DESKTOP_MODE 时断言）：

```python
    # 信任边界铁律: 非桌面 sidecar 的部署 = 共享后端, 绝不接受本地签票。
    if os.environ.get("DESKTOP_MODE") != "1":
        from app.auth import assert_shared_backend_issuer_safety
        assert_shared_backend_issuer_safety()
```

`backend/services/account_service/main.py` 的 lifespan/startup 处（`create_app` 内，挂 router 前后均可）加：

```python
    from app.auth import assert_shared_backend_issuer_safety
    assert_shared_backend_issuer_safety()
```

（account-service 永远是 authority/共享后端，无条件断言。若 main.py 用 `lifespan` 函数则放进去；若无 lifespan，放 `create_app()` 体内启动时执行。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_token_issuer.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 冒烟——account-service 能正常起（默认白名单不含 desktop）**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v`
Expected: PASS（默认 `accepted_token_issuers="ai-builder"`，断言不抛）

- [ ] **Step 6: 提交**

```bash
git add backend/app/auth.py backend/app/main.py backend/services/account_service/main.py backend/tests/test_token_issuer.py
git commit -m "feat(desktop): 共享后端启动断言 — 拒绝接受本地 sidecar 票(信任边界铁律)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 5: 开号权限结构性强制（去 is_platform_admin 提权通道）

**Files:**
- Modify: `backend/app/desktop_accounts.py`
- Modify: `backend/scripts/seed_desktop_account.py`
- Test: `backend/tests/test_desktop_accounts.py`（改/补）

**背景:** 现 `provision_desktop_account` 带 `is_platform_admin` 参，federation/公网开号靠「不传=默认 False」约定。改成结构性不可能：federation/公网用的函数根本不接受该参（恒 False），本机管理员单独走 `provision_local_admin_account`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_desktop_accounts.py` 追加：

```python
@pytest.mark.asyncio
async def test_provision_desktop_account_cannot_elevate(session):
    """federation/公网开号路径用的函数结构上不接受 is_platform_admin。"""
    import inspect
    sig = inspect.signature(da.provision_desktop_account)
    assert "is_platform_admin" not in sig.parameters
    user = await da.provision_desktop_account(session, "zoe", "pw123456")
    await session.commit()
    assert user.is_platform_admin is False


@pytest.mark.asyncio
async def test_provision_local_admin_sets_platform_admin(session):
    user = await da.provision_local_admin_account(session, "root", "pw123456")
    await session.commit()
    assert user.is_platform_admin is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_accounts.py -k "elevate or local_admin" -v`
Expected: FAIL（参数仍在 / `provision_local_admin_account` 不存在）

- [ ] **Step 3: 重构 desktop_accounts.py**

把 `provision_desktop_account` 改成内部委托一个带标志的私有实现，对外两个函数：

```python
async def _provision(
    db: AsyncSession, username: str, password: str, *, is_platform_admin: bool
) -> User:
    existing = (await db.execute(
        select(User).where(User.username == username, User.account_source == "desktop")
    )).scalar_one_or_none()
    if existing:
        raise AccountExistsError(username)
    code = await _unique_tenant_code(db, f"desktop-{username}")
    tenant = Tenant(tenant_name=f"{username} 的工作空间", tenant_code=code, status=1, max_applications=100)
    db.add(tenant)
    await db.flush()
    await seed_default_roles(db, tenant.id, commit=False)
    user = User(
        username=username, display_name=username,
        hashed_password=get_password_hash(password),
        is_active=True, is_platform_admin=is_platform_admin, account_source="desktop",
    )
    db.add(user)
    await db.flush()
    admin_role = (await db.execute(
        select(Role).where(Role.tenant_id == tenant.id, Role.role_code == "R_tenant_admin")
    )).scalar_one_or_none()
    if admin_role is None:
        raise RuntimeError(f"seed_default_roles 未产出 R_tenant_admin (tenant {tenant.id})")
    db.add(UserTenant(
        user_id=user.id, tenant_id=tenant.id, role_id=admin_role.id, is_default=True, status=1,
    ))
    await db.flush()
    return user


async def provision_desktop_account(db: AsyncSession, username: str, password: str) -> User:
    """federation 镜像 + 公网 admin 开号。**永远 is_platform_admin=False** —— 结构上
    不接受该参, 杜绝跨 federation 提权 (信任边界铁律)。"""
    return await _provision(db, username, password, is_platform_admin=False)


async def provision_local_admin_account(db: AsyncSession, username: str, password: str) -> User:
    """仅本机 authority 单机自洽开号 (seed_desktop_account.py): 本机管理员。
    绝不可经任何公网/federation 路径调用。"""
    return await _provision(db, username, password, is_platform_admin=True)
```

（`provision_desktop_account` 签名去掉 `*, is_platform_admin` 参；其余逻辑搬进 `_provision`。`_federation_login`、`admin_create_account` 已是无参调用，无需改。）

- [ ] **Step 4: 改 seed 脚本**

`backend/scripts/seed_desktop_account.py` 里把 `provision_desktop_account(..., is_platform_admin=True)` 改为：

```python
    user = await da.provision_local_admin_account(db, args.username, args.password)
```

（搜该文件里对 `provision_desktop_account` 的调用，替换为 `provision_local_admin_account`，去掉 `is_platform_admin=True`。）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_accounts.py -v`
Expected: PASS（原有 4 + 新 2）

- [ ] **Step 6: 提交**

```bash
git add backend/app/desktop_accounts.py backend/scripts/seed_desktop_account.py backend/tests/test_desktop_accounts.py
git commit -m "fix(desktop): 开号权限结构性强制 — federation 路径不接受 is_platform_admin

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Part 1+信任边界全量回归**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: 与改前预存失败数一致（基线见 MEMORY: ~1 预存失败 test_tool_registry），零新增失败。

---

## Part 3 — 引导式 onboarding + 桌面功能边界（前端）

### Task 6: onboarding 状态 composable

**Files:**
- Create: `frontend/src/composables/useOnboardingState.ts`
- Test: `frontend/src/composables/useOnboardingState.spec.ts`

**背景:** first-run 检测复用现成 `platformEnvApi.list()`（返 `PlatformEnv[]`）+ `llmConfigApi.list()`（返 `LlmConfig[]`），两者皆空即未配齐。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/composables/useOnboardingState.spec.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import { fetchOnboardingState } from './useOnboardingState'

describe('fetchOnboardingState', () => {
  it('configured=false when both empty', async () => {
    const s = await fetchOnboardingState(
      async () => [],
      async () => [],
    )
    expect(s).toEqual({ hasEnv: false, hasLlm: false, configured: false })
  })

  it('configured=true only when both present', async () => {
    const s = await fetchOnboardingState(
      async () => [{ id: 1 } as any],
      async () => [{ id: 1 } as any],
    )
    expect(s.configured).toBe(true)
  })

  it('configured=false when only one present', async () => {
    const s = await fetchOnboardingState(
      async () => [{ id: 1 } as any],
      async () => [],
    )
    expect(s.configured).toBe(false)
  })

  it('treats fetch errors as not-configured (空库新机首启 list 可能 401/空)', async () => {
    const s = await fetchOnboardingState(
      async () => { throw new Error('x') },
      async () => [],
    )
    expect(s.configured).toBe(false)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/composables/useOnboardingState.spec.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

Create `frontend/src/composables/useOnboardingState.ts`:

```typescript
// 桌面首次启动状态: 当前租户是否已配 aPaaS 环境 + LLM 模型。
// 注入 fetcher 便于单测; 默认用真实 API。
import { platformEnvApi } from '@/api/platformEnv'
import { llmConfigApi } from '@/api/llmConfig'

export interface OnboardingState {
  hasEnv: boolean
  hasLlm: boolean
  configured: boolean
}

export async function fetchOnboardingState(
  listEnvs: () => Promise<unknown[]> = () => platformEnvApi.list(),
  listLlms: () => Promise<unknown[]> = () => llmConfigApi.list(),
): Promise<OnboardingState> {
  let hasEnv = false
  let hasLlm = false
  try { hasEnv = (await listEnvs()).length > 0 } catch { hasEnv = false }
  try { hasLlm = (await listLlms()).length > 0 } catch { hasLlm = false }
  return { hasEnv, hasLlm, configured: hasEnv && hasLlm }
}
```

（确认 `@/api/platformEnv` 导出名是 `platformEnvApi`、`@/api/llmConfig` 是 `llmConfigApi`；若实际默认导出名不同，按文件实际改 import。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/composables/useOnboardingState.spec.ts`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/composables/useOnboardingState.ts frontend/src/composables/useOnboardingState.spec.ts
git commit -m "feat(desktop): onboarding 状态 composable — 复用 platformEnv/llmConfig list

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 7: 桌面功能边界 meta + 守卫纯逻辑

**Files:**
- Create: `frontend/src/router/desktopGuard.ts`
- Test: `frontend/src/router/desktopGuard.spec.ts`

**背景:** 用路由 `meta.desktop`（`'hidden'` = 桌面不可用，未标=可用）作桌面可用性单一来源，取代散落 `__DESKTOP__`。守卫纯逻辑抽出可测。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/router/desktopGuard.spec.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { resolveDesktopRedirect } from './desktopGuard'

describe('resolveDesktopRedirect', () => {
  it('在线版不拦截 hidden 路由', () => {
    expect(resolveDesktopRedirect(false, { desktop: 'hidden' }, '/platform-admin')).toBeNull()
  })
  it('桌面版 hidden 路由 → /desktop-unavailable', () => {
    expect(resolveDesktopRedirect(true, { desktop: 'hidden' }, '/platform-admin'))
      .toBe('/desktop-unavailable')
  })
  it('桌面版普通路由放行', () => {
    expect(resolveDesktopRedirect(true, {}, '/apps')).toBeNull()
  })
  it('已在 unavailable 页不再重定向(防环)', () => {
    expect(resolveDesktopRedirect(true, { desktop: 'hidden' }, '/desktop-unavailable')).toBeNull()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/router/desktopGuard.spec.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

Create `frontend/src/router/desktopGuard.ts`:

```typescript
// 桌面功能边界守卫纯逻辑。meta.desktop==='hidden' 的路由在桌面 build 下落降级页。
export function resolveDesktopRedirect(
  isDesktop: boolean,
  meta: { desktop?: 'hidden' | 'ok' },
  targetPath: string,
): string | null {
  if (!isDesktop) return null
  if (meta.desktop !== 'hidden') return null
  if (targetPath === '/desktop-unavailable') return null
  return '/desktop-unavailable'
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/router/desktopGuard.spec.ts`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/router/desktopGuard.ts frontend/src/router/desktopGuard.spec.ts
git commit -m "feat(desktop): 功能边界守卫纯逻辑 + meta.desktop 单一来源

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 8: 路由接线 — 边界 meta + 降级页 + 首启向导分流

**Files:**
- Modify: `frontend/src/router/index.ts`
- Create: `frontend/src/views/DesktopUnavailable.vue`

**背景:** 把 meta + 守卫 + 首启分流接进 `beforeEach`。首启分流：桌面 + 已登录 + 未配齐 + 不在向导/登录页 → 去 `/desktop-setup`。

- [ ] **Step 1: 建降级页**

Create `frontend/src/views/DesktopUnavailable.vue`:

```vue
<template>
  <div class="du-wrap">
    <h2>此功能在桌面版不可用</h2>
    <p>该功能依赖在线平台管理控制台，桌面版未包含。请在浏览器中使用在线版，或返回主界面继续配置/二次开发。</p>
    <el-button type="primary" @click="$router.replace('/')">返回主界面</el-button>
  </div>
</template>
<script setup lang="ts"></script>
<style scoped>
.du-wrap { max-width: 520px; margin: 96px auto; text-align: center; }
.du-wrap p { color: var(--el-text-color-secondary); margin: 16px 0 24px; }
</style>
```

- [ ] **Step 2: 路由加 meta.desktop='hidden' + 两个新路由**

在 `frontend/src/router/index.ts` 给依赖 admin-spa 的路由加 `meta.desktop: 'hidden'`：
- `/platform-admin/:pathMatch(.*)*`（PlatformAdminEmbed）的 meta 加 `desktop: 'hidden'`
- `/admin/tenants`（PlatformTenants）的 meta 加 `desktop: 'hidden'`

加两个路由（`requiresAuth` 但不加 admin 门）：

```typescript
    {
      path: '/desktop-setup',
      name: 'DesktopSetup',
      component: () => import('@/views/DesktopSetupWizard.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/desktop-unavailable',
      name: 'DesktopUnavailable',
      component: () => import('@/views/DesktopUnavailable.vue'),
      meta: { requiresAuth: true }
    },
```

- [ ] **Step 3: beforeEach 接线**

在 `frontend/src/router/index.ts` 顶部 import：

```typescript
import { resolveDesktopRedirect } from './desktopGuard'
import { fetchOnboardingState } from '@/composables/useOnboardingState'
```

在 `beforeEach` 里，现有 platform-admin 重定向之后、`if (to.path === '/login' ...)` 之前，插入桌面专属逻辑（整段仅 `__DESKTOP__` 下生效，在线 build tree-shake）：

```typescript
  if (__DESKTOP__ && userStore.token) {
    // 功能边界: hidden 路由落降级页
    const red = resolveDesktopRedirect(true, (to.meta as any), to.path)
    if (red) { next({ path: red, replace: true }); return }
    // 首启分流: 未配齐 aPaaS+LLM → 向导 (排除向导/登录/降级页自身, 防环)
    const exempt = ['/desktop-setup', '/desktop-unavailable', '/login'].some(p => to.path.startsWith(p))
    if (!exempt) {
      const st = await fetchOnboardingState()
      if (!st.configured) { next({ path: '/desktop-setup', replace: true }); return }
    }
  }
```

- [ ] **Step 4: 验证守卫单测仍绿 + 桌面 build 通过**

Run: `cd frontend && npx vitest run src/router/desktopGuard.spec.ts src/composables/useOnboardingState.spec.ts`
Expected: PASS

Run: `cd frontend && npm run build:nocheck`（确认桌面分支编译通过；vue-tsc 预存坏故用 nocheck，见 MEMORY [[vue_tsc_vacuous_tsconfig_2026_06_04]]）
Expected: build 成功无报错

- [ ] **Step 5: 提交**

```bash
git add frontend/src/router/index.ts frontend/src/views/DesktopUnavailable.vue
git commit -m "feat(desktop): 路由接线 — 功能边界降级页 + 首启向导分流

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 9: DesktopSetupWizard 三步向导

**Files:**
- Create: `frontend/src/views/DesktopSetupWizard.vue`

**背景:** 三步——连 aPaaS 环境 / 配 LLM 令牌 / 完成。全部复用现成 `platformEnvApi`（`create`/`test`/`setDefault`）+ `llmConfigApi`（`create`）。WKWebView 无调试器，用 chrome-devtools/playwright MCP 连 sidecar 端口渲染验证。

- [ ] **Step 1: 实现向导组件**

Create `frontend/src/views/DesktopSetupWizard.vue`:

```vue
<template>
  <div class="wiz-wrap">
    <el-steps :active="step" finish-status="success" simple>
      <el-step title="连接 aPaaS 环境" />
      <el-step title="配置 LLM 模型" />
      <el-step title="完成" />
    </el-steps>

    <div v-if="step === 0" class="wiz-step">
      <el-form label-width="120px">
        <el-form-item label="环境名称"><el-input v-model="env.env_name" placeholder="如 Trail-mars" /></el-form-item>
        <el-form-item label="aPaaS 地址"><el-input v-model="env.base_url" placeholder="https://..." /></el-form-item>
        <el-form-item label="平台租户ID"><el-input v-model="env.platform_tenant_id" /></el-form-item>
        <el-form-item label="账号"><el-input v-model="env.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="env.password" type="password" show-password /></el-form-item>
      </el-form>
      <div class="wiz-foot">
        <el-button @click="skip">稍后配置</el-button>
        <el-button type="primary" :loading="busy" @click="saveEnv">保存并测试连通</el-button>
      </div>
      <p v-if="msg" class="wiz-msg" :class="{ err: msgErr }">{{ msg }}</p>
    </div>

    <div v-else-if="step === 1" class="wiz-step">
      <el-form label-width="120px">
        <el-form-item label="供应商">
          <el-select v-model="llm.provider" @change="onProvider">
            <el-option label="Dolphin" value="dolphin" />
          </el-select>
        </el-form-item>
        <el-form-item label="API 地址"><el-input v-model="llm.api_base" /></el-form-item>
        <el-form-item label="模型"><el-input v-model="llm.model" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="llm.api_key" placeholder="你的 omnigate 令牌" /></el-form-item>
      </el-form>
      <div class="wiz-foot">
        <el-button @click="skip">稍后配置</el-button>
        <el-button type="primary" :loading="busy" @click="saveLlm">保存</el-button>
      </div>
      <p v-if="msg" class="wiz-msg" :class="{ err: msgErr }">{{ msg }}</p>
    </div>

    <div v-else class="wiz-step wiz-done">
      <h3>配置完成</h3>
      <p>已连接 aPaaS 环境并配好模型，可以开始智能配置 / 二次开发了。</p>
      <el-button type="primary" @click="$router.replace('/')">进入工作台</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { platformEnvApi } from '@/api/platformEnv'
import { llmConfigApi } from '@/api/llmConfig'

const step = ref(0)
const busy = ref(false)
const msg = ref('')
const msgErr = ref(false)

const env = reactive({ env_name: '', base_url: '', platform_tenant_id: '', username: '', password: '' })
const llm = reactive({ provider: 'dolphin', api_base: 'http://ai-agent.dfy.definesys.cn/omnigate/0', model: 'gpt-5.5', api_key: '' })

function onProvider() {
  if (llm.provider === 'dolphin') {
    llm.api_base = 'http://ai-agent.dfy.definesys.cn/omnigate/0'
    llm.model = 'gpt-5.5'
  }
}

async function saveEnv() {
  busy.value = true; msg.value = ''; msgErr.value = false
  try {
    const { id } = await platformEnvApi.create({
      env_name: env.env_name, base_url: env.base_url,
      platform_tenant_id: env.platform_tenant_id,
      username: env.username, password: env.password,
    })
    const r = await platformEnvApi.test(id)
    if (!r.ok) { msg.value = `连通测试失败: ${r.error || r.status}`; msgErr.value = true; return }
    await platformEnvApi.setDefault(id)
    msg.value = '环境已连接'
    step.value = 1
  } catch (e: any) {
    msg.value = `保存失败: ${e?.message || e}`; msgErr.value = true
  } finally { busy.value = false }
}

async function saveLlm() {
  busy.value = true; msg.value = ''; msgErr.value = false
  try {
    await llmConfigApi.create({
      provider: llm.provider, api_base: llm.api_base,
      model: llm.model, api_key: llm.api_key,
      purpose: 'builder', is_default: true,
    } as any)
    step.value = 2
  } catch (e: any) {
    msg.value = `保存失败: ${e?.message || e}`; msgErr.value = true
  } finally { busy.value = false }
}

function skip() {
  ElMessage.info('已跳过，稍后可在「平台配置」继续设置')
  if (step.value === 0) step.value = 1
  else step.value = 2
}
</script>

<style scoped>
.wiz-wrap { max-width: 640px; margin: 48px auto; }
.wiz-step { margin-top: 32px; }
.wiz-foot { display: flex; justify-content: flex-end; gap: 12px; margin-top: 8px; }
.wiz-msg { margin-top: 12px; color: var(--el-color-success); }
.wiz-msg.err { color: var(--el-color-danger); }
.wiz-done { text-align: center; }
</style>
```

**执行者注意:** `platformEnvApi.create` 入参以 `frontend/src/api/platformEnv.ts:16` 实际签名为准；`llmConfigApi.create` 入参以 `frontend/src/api/llmConfig.ts` 实际签名为准——如字段名不符（如 `api_base`/`model`/`purpose`），按 API 文件实际字段改，别硬套。

- [ ] **Step 2: 桌面 build 通过**

Run: `cd frontend && npm run build:nocheck`
Expected: build 成功

- [ ] **Step 3: 真机/伪真机验证（chrome-devtools 或 playwright MCP）**

打包或起 dev sidecar，连 `http://127.0.0.1:<sidecar端口>/`：
1. 用一个全新空库桌面号登录 → 应自动落 `/desktop-setup`（首启分流生效）。
2. 走完三步（填真实 trial 环境 + omnigate 令牌）→ 环境测试通过 → 配模型 → 完成 → 进 `/`。
3. 重登 → 不再进向导（已配齐）。
4. 桌面号深链 `/platform-admin` → 落 `/desktop-unavailable` 降级页（非白屏）。

记录截图/快照为证。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/DesktopSetupWizard.vue
git commit -m "feat(desktop): 首次启动三步向导 — 连 aPaaS + 配 LLM(复用现成接口)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 10: RailSidebar 隐藏桌面不可用导航项

**Files:**
- Modify: `frontend/src/components/v2/RailSidebar.vue`

**背景:** 导航项可见性归一到 `meta.desktop`——桌面 build 下不渲染指向 `meta.desktop==='hidden'` 路由的导航项，复核既有 `platformNavItem` 绕过点。

- [ ] **Step 1: 实现**

在 `frontend/src/components/v2/RailSidebar.vue`：对每个导航项，桌面 build 下若其目标路由 `meta.desktop==='hidden'` 则不渲染。`platformNavItem`（现 `RailSidebar.vue:35` 桌面已指 `/platform-envs`）保持指 `/platform-envs`（非 hidden），无需隐藏。主要确保任何仍指向 `/platform-admin`、`/admin/tenants` 的导航项在桌面 build 下隐藏。用 `router.resolve(path).meta.desktop === 'hidden'` 判断，或在导航项数据里直接加 `desktopHidden: true` 标志。

实现示例（在计算导航项可见性处）：

```typescript
import { useRouter } from 'vue-router'
const router = useRouter()
function desktopHidden(path: string): boolean {
  if (!__DESKTOP__) return false
  try { return (router.resolve(path).meta as any)?.desktop === 'hidden' } catch { return false }
}
```

在导航项 `v-for`/`v-if` 上加 `v-if="!desktopHidden(item.path)"`（按 RailSidebar 实际模板结构落位）。

- [ ] **Step 2: 桌面 build 通过 + 验证**

Run: `cd frontend && npm run build:nocheck`
Expected: build 成功

伪真机（chrome-devtools MCP 连 sidecar）确认：桌面号登录后侧栏无指向 `/platform-admin`/`/admin/tenants` 的死链入口；`/platform-envs` 入口在（tenant_admin 可见）。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/v2/RailSidebar.vue
git commit -m "feat(desktop): 侧栏隐藏桌面不可用导航项(读 meta.desktop)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Part 1 撤旁路+持久化密钥 → Task 1 ✓
- Part 3 票据 issuer 标记 → Task 2(校验)+Task 3(federation 打标) ✓
- Part 3 共享后端拒收 → Task 2(decode 校验)+Task 4(启动断言) ✓
- Part 3 开号权限启动断言/结构强制 → Task 5 ✓
- Part 2a 引导式向导 → Task 6(状态)+Task 8(分流)+Task 9(向导) ✓
- Part 2b 功能边界系统梳理 → Task 7(守卫逻辑)+Task 8(meta+降级页)+Task 10(导航隐藏) ✓

**类型一致性:** `fetchOnboardingState`/`OnboardingState`、`resolveDesktopRedirect`、`ensure_encryption_key`、`provision_local_admin_account`、`_DESKTOP_ISSUER`、`accepted_issuers_set`、`assert_shared_backend_issuer_safety` 跨任务命名一致 ✓

**已知执行期需对账（非占位，是「以实际文件为准」的对账点）:**
- Task 6/9 的 API 导出名与 `create` 入参字段，须对 `frontend/src/api/platformEnv.ts`、`llmConfig.ts` 实际签名（计划已注明对账）。
- Task 10 的导航项 `v-if` 落位须按 RailSidebar 实际模板结构。

**回归基线:** 后端全量 `pytest tests/ -q` 与改前预存失败数一致（MEMORY 记 ~1 预存 test_tool_registry），零新增；前端 `npm run build:nocheck` 通过（vue-tsc 预存坏不阻塞）。
