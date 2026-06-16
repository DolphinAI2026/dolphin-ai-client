# 桌面端自动更新(Tauri updater)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 桌面端做成 Claude/Codex 式应用内自动更新 —— app 启动检测新版本、用户一键原地升级重启;发版只需开发者跑一条命令。

**Architecture:** account-service(agent.dfy)新增更新托管端点(GET manifest/包 + 平台管理员 POST 上传),文件落已挂载的 PVC(`/data`)。Tauri 端加 updater + process 插件,内嵌公钥验签;前端 `__DESKTOP__` 启动检查 + 手动按钮,用 Element Plus 弹窗提示。发版脚本 build(arm+x64,开 updater 产物)→ 私钥签名 → 拼 latest.json → 上传。

**Tech Stack:** Tauri v2.11 / tauri-plugin-updater / tauri-plugin-process / FastAPI(account-service)/ minisign 签名 / Element Plus 弹窗。

**关联:** spec `docs/superpowers/specs/2026-06-16-desktop-auto-update-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `backend/app/config.py` | 加 `desktop_updates_dir` 设置 | 改 |
| `backend/app/routes/desktop_updates.py` | 更新托管路由(GET manifest/包 + POST 平台管理员上传) | 建 |
| `backend/services/account_service/main.py` | 挂 desktop_updates 路由(无 /api 前缀) | 改 |
| `backend/tests/test_desktop_updates.py` | 路由单测 | 建 |
| `src-tauri/Cargo.toml` | 加 updater + process Rust 依赖 | 改 |
| `src-tauri/src/lib.rs` | 注册两插件 | 改 |
| `src-tauri/tauri.conf.json` | updater 配置 + createUpdaterArtifacts | 改 |
| `src-tauri/capabilities/default.json` | 加 updater + process 权限 | 改 |
| `frontend/src/utils/desktopUpdate.ts` | 检查/下载/重启逻辑 | 建 |
| `frontend/src/components/v2/RailSidebar.vue` | 「检查更新」按钮(仅 __DESKTOP__) | 改 |
| `frontend/src/App.vue`(或根组件)| 启动自动检查 | 改 |
| `scripts/release-desktop.sh` | 一键发版(build+签名+上传) | 建 |
| `keys/`(gitignore)| 签名私钥(本机,备份) | 一次性 |

---

## Phase 1 — 服务端更新托管端点(TDD)

### Task 1: 加 `desktop_updates_dir` 配置

**Files:**
- Modify: `backend/app/config.py`(`Settings` 类,起于第 17 行)

- [ ] **Step 1: 看现有 Settings 字段风格**

Run: `sed -n '17,60p' backend/app/config.py`
Expected: 看到 `class Settings(BaseSettings)` 下一串 `xxx: type = Field(...)` 或 `xxx: type = default`。

- [ ] **Step 2: 加字段**

在 `Settings` 类里(其它字段旁)加:

```python
    # 桌面更新产物目录(account-service 挂 PVC /data)。GET manifest/包 + 平台管理员上传都读写这里。
    desktop_updates_dir: str = "/data/desktop-updates"
```

> pydantic-settings 会自动读环境变量 `DESKTOP_UPDATES_DIR` 覆盖。

- [ ] **Step 3: 验证导入不炸**

Run: `cd backend && .venv/bin/python -c "from app.config import settings; print(settings.desktop_updates_dir)"`
Expected: 打印 `/data/desktop-updates`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(desktop-updates): config 加 desktop_updates_dir"
```

---

### Task 2: 更新托管路由 — GET manifest + GET 包文件

**Files:**
- Create: `backend/app/routes/desktop_updates.py`
- Create: `backend/tests/test_desktop_updates.py`

路由前缀 `/desktop-updates`,**account-service 无 `/api` 前缀挂载**,所以公网路径 = `https://agent.dfy.definesys.cn/account-api/desktop-updates/...`(ingress 去掉 `/account-api`)。两个 GET 端点**不鉴权**(更新产物公开,靠签名防篡改)。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_desktop_updates.py`:

```python
"""桌面更新托管端点测试。GET 不鉴权; 文件名白名单防穿越; POST 见 test_desktop_updates_admin。"""
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_updates.py -q`
Expected: FAIL（`ModuleNotFoundError: app.routes.desktop_updates` 或 import error）

- [ ] **Step 3: 写路由**

`backend/app/routes/desktop_updates.py`:

```python
"""桌面端自动更新托管(account-service 专用)。

- GET /desktop-updates/latest.json  → Tauri updater 拉的 manifest(不鉴权)
- GET /desktop-updates/{filename}   → 下发签名包 .app.tar.gz(不鉴权, 文件名白名单)
- POST /desktop-updates/admin/publish → 平台管理员发版上传(见 Task 3)

文件落 settings.desktop_updates_dir(account-service 挂 PVC /data)。
"""
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings

router = APIRouter(prefix="/desktop-updates", tags=["desktop-updates"])

# 只允许下载更新包 / sig / manifest。挡掉路径穿越与任意文件读取。
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(app\.tar\.gz|app\.tar\.gz\.sig|json)$")


def _updates_dir() -> Path:
    d = Path(settings.desktop_updates_dir)
    return d


@router.get("/latest.json")
async def latest_json():
    f = _updates_dir() / "latest.json"
    if not f.is_file():
        raise HTTPException(status_code=404, detail="no update manifest")
    return JSONResponse(content=json.loads(f.read_text(encoding="utf-8")))


@router.get("/{filename}")
async def get_package(filename: str):
    if not _SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="bad filename")
    f = _updates_dir() / filename
    # 二次防穿越: 解析后必须仍在更新目录内
    try:
        f.resolve().relative_to(_updates_dir().resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="bad path")
    if not f.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(f))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_updates.py -q`
Expected: 5 passed（`latest.json` 路由先于 `{filename}` 注册，所以 `latest.json` 不会被 `{filename}` 抢匹配；若被抢，把 `latest.json` 路由定义放在 `{filename}` 之前即可——本代码已如此排序）

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/desktop_updates.py backend/tests/test_desktop_updates.py
git commit -m "feat(desktop-updates): GET manifest/包 端点 + 文件名白名单"
```

---

### Task 3: 平台管理员发版上传端点

**Files:**
- Modify: `backend/app/routes/desktop_updates.py`
- Modify: `backend/tests/test_desktop_updates.py`

复用 desktop_auth.py 的鉴权:`Depends(get_auth_context)` + `ctx.user.is_platform_admin`。

- [ ] **Step 1: 写失败测试(追加)**

在 `backend/tests/test_desktop_updates.py` 末尾追加。鉴权 fixture 镜像 `tests/test_desktop_auth_routes.py` 的 `admin_client`(StaticPool + monkeypatch AsyncSessionLocal + dependency_overrides[get_db]):

```python
import app.database as database
from app.database import Base, get_db
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.auth import create_access_token, get_password_hash
from app.models import User


@pytest_asyncio.fixture
async def admin_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod.settings, "desktop_updates_dir", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    async with Session() as s:
        admin = User(username="pubadmin", display_name="A", hashed_password=get_password_hash("adminpass123"),
                     is_active=True, is_platform_admin=True, account_source="desktop")
        s.add(admin); await s.flush(); aid = admin.id; await s.commit()
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
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {token}"}) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_publish_requires_platform_admin(client):
    c, _ = client  # 无 token 的普通 client
    resp = await c.post("/desktop-updates/admin/publish",
                        data={"manifest": json.dumps({"version": "0.2.0", "platforms": {}})})
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_updates.py -q`
Expected: 新增 4 个 FAIL（`405 Method Not Allowed` 或路由不存在）

- [ ] **Step 3: 实现上传端点(追加到 desktop_updates.py)**

在 `backend/app/routes/desktop_updates.py` 顶部 import 补:

```python
from typing import Annotated
from fastapi import Depends, Form, UploadFile, File
from app.deps import get_auth_context, AuthContext
```

末尾追加:

```python
@router.post("/admin/publish")
async def publish_update(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    manifest: Annotated[str, Form()],
    packages: Annotated[list[UploadFile] | None, File()] = None,
):
    """平台管理员发版: 写 manifest + 包到更新目录。仅 is_platform_admin。"""
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可发版")
    try:
        parsed = json.loads(manifest)
    except ValueError:
        raise HTTPException(status_code=400, detail="manifest 不是合法 JSON")
    if not isinstance(parsed, dict) or "version" not in parsed or "platforms" not in parsed:
        raise HTTPException(status_code=400, detail="manifest 缺 version/platforms")

    d = _updates_dir()
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for up in (packages or []):
        name = os.path.basename(up.filename or "")
        if not _SAFE_NAME.match(name) or name == "latest.json":
            raise HTTPException(status_code=400, detail=f"包名非法: {name}")
        data = await up.read()
        tmp = d / (name + ".part")
        tmp.write_bytes(data)
        tmp.replace(d / name)  # 原子 rename
        written.append(name)

    # manifest 最后写(原子), 保证拉到 manifest 时包已就位
    tmp = d / "latest.json.part"
    tmp.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "latest.json")
    return {"ok": True, "manifest_version": parsed["version"], "packages": written}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_updates.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/desktop_updates.py backend/tests/test_desktop_updates.py
git commit -m "feat(desktop-updates): 平台管理员发版上传端点(原子写+校验)"
```

---

### Task 4: account-service 挂载更新路由

**Files:**
- Modify: `backend/services/account_service/main.py`

- [ ] **Step 1: 挂载(无 /api 前缀)**

在 `create_app()` 里 `app.include_router(desktop_auth.router, prefix="/api")` 之后加:

```python
    from app.routes import desktop_updates
    app.include_router(desktop_updates.router)  # 无 /api 前缀 → /account-api/desktop-updates/...
```

- [ ] **Step 2: 冒烟测试**

Run:
```bash
cd backend && .venv/bin/python -c "
from services.account_service.main import create_app
app = create_app()
paths = sorted([r.path for r in app.routes])
assert '/desktop-updates/latest.json' in paths, paths
print('OK', [p for p in paths if 'desktop-updates' in p])
"
```
Expected: `OK ['/desktop-updates/admin/publish', '/desktop-updates/latest.json', '/desktop-updates/{filename}']`

- [ ] **Step 3: Commit**

```bash
git add backend/services/account_service/main.py
git commit -m "feat(desktop-updates): account-service 挂载更新路由"
```

---

## Phase 2 — 签名密钥(人工门:私钥要你保管)

### Task 5: 生成 Tauri 签名密钥对

> ⚠️ 人工步骤,产出私钥需用户(大明哥)妥善备份。subagent 执行到此**停下来交给人工**。

**Files:**
- Create: `keys/ruijing-updater.key`(私钥,**加入 .gitignore**,本机 + 离线备份)
- 公钥字符串记下来供 Task 7 用

- [ ] **Step 1: gitignore 私钥目录**

在仓库根 `.gitignore` 追加:
```
/keys/
```

- [ ] **Step 2: 生成密钥对**

Run:
```bash
cd "/Users/mars/Vibe Coding/ai-builder"
mkdir -p keys
npx @tauri-apps/cli signer generate -w keys/ruijing-updater.key
```
- 会提示设密码(记到密码管理器)。
- 产出 `keys/ruijing-updater.key`(私钥)+ `keys/ruijing-updater.key.pub`(公钥)。
- 终端也会打印公钥 base64。

- [ ] **Step 3: 备份私钥(人工)**

把 `keys/ruijing-updater.key` + 密码存进密码管理器/离线备份。**丢失=无法再推被已装 app 接受的更新。**

- [ ] **Step 4: 记下公钥**

Run: `cat keys/ruijing-updater.key.pub`
把内容(单行 base64)留给 Task 7。

> 无需 commit(私钥已 gitignore;公钥进 tauri.conf.json 由 Task 7 提交)。

---

## Phase 3 — App 端(Tauri 插件 + 配置 + 前端)

### Task 6: 加 updater + process Rust 插件

**Files:**
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/src/lib.rs`

- [ ] **Step 1: Cargo.toml 加依赖**

在 `[dependencies]` 段(`tauri-plugin-shell = "2"` 旁)加:
```toml
tauri-plugin-updater = "2"
tauri-plugin-process = "2"
```

- [ ] **Step 2: lib.rs 注册插件**

在 `tauri::Builder::default()` 之后、`.plugin(tauri_plugin_shell::init())` 旁加:
```rust
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
```

- [ ] **Step 3: 验证 Rust 编译**

Run: `cd src-tauri && cargo check 2>&1 | tail -5`
Expected: `Finished` 无 error（首次会拉新 crate，稍慢）

- [ ] **Step 4: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/lib.rs
git commit -m "feat(desktop): 加 tauri updater + process 插件"
```

---

### Task 7: tauri.conf.json updater 配置 + capability

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/capabilities/default.json`

- [ ] **Step 1: bundle 开 updater 产物**

`src-tauri/tauri.conf.json` 的 `"bundle"` 对象里(`"active": true` 旁)加:
```json
    "createUpdaterArtifacts": true,
```

- [ ] **Step 2: 加 plugins.updater**

在 `tauri.conf.json` 顶层(与 `"app"`/`"bundle"` 同级)加(`<公钥>` 用 Task 5 的公钥):
```json
  "plugins": {
    "updater": {
      "endpoints": ["https://agent.dfy.definesys.cn/account-api/desktop-updates/latest.json"],
      "pubkey": "<Task5 的公钥单行 base64>"
    }
  }
```

- [ ] **Step 3: capability 加权限**

`src-tauri/capabilities/default.json` 的 `"permissions"` 数组追加(在 `"shell:allow-open"` 后):
```json
    "updater:default",
    "process:allow-restart"
```

> 实现时核对标识符:`grep -o '"updater:[a-z-]*"\|"process:[a-z-]*"' src-tauri/gen/schemas/desktop-schema.json | sort -u`。若 `updater:default` 不存在,用 `updater:allow-check` + `updater:allow-download-and-install`。

- [ ] **Step 4: 验证配置合法**

Run: `cd src-tauri && cargo check 2>&1 | tail -3`(tauri 在 build.rs 校验 capability/config)
Expected: 无 error

- [ ] **Step 5: Commit**

```bash
git add src-tauri/tauri.conf.json src-tauri/capabilities/default.json
git commit -m "feat(desktop): updater 配置(endpoint+公钥)+ capability"
```

---

### Task 8: 前端更新逻辑 desktopUpdate.ts

**Files:**
- Create: `frontend/src/utils/desktopUpdate.ts`
- 依赖: `npm i @tauri-apps/plugin-updater @tauri-apps/plugin-process`

提示框用 Element Plus `ElMessageBox`(webview 内 web 弹窗,无需额外 Tauri dialog 插件)。

- [ ] **Step 1: 装 JS 依赖**

Run: `cd frontend && npm install @tauri-apps/plugin-updater @tauri-apps/plugin-process`
Expected: 安装成功,package.json 出现两包。

- [ ] **Step 2: 写 desktopUpdate.ts**

`frontend/src/utils/desktopUpdate.ts`:

```typescript
// 桌面端自动更新。仅 __DESKTOP__ 下生效:在线版调用是 no-op。
// 提示用 Element Plus 弹窗(webview 内可用),下载/安装/重启用 tauri 插件。
import { ElMessageBox, ElMessage } from 'element-plus'

export async function checkAndPromptUpdate(opts: { silentIfNone: boolean }): Promise<void> {
  if (!__DESKTOP__) return
  let update: any = null
  try {
    const updater = await import('@tauri-apps/plugin-updater')
    update = await updater.check()
  } catch (e) {
    if (!opts.silentIfNone) ElMessage.error('检查更新失败:无法连接更新服务')
    console.error('[update] check 失败', e)
    return
  }
  if (!update) {
    if (!opts.silentIfNone) ElMessage.success('已是最新版本')
    return
  }
  try {
    await ElMessageBox.confirm(
      `发现新版本 ${update.version}\n\n${update.body || ''}`,
      '有可用更新',
      { confirmButtonText: '立即更新', cancelButtonText: '稍后', type: 'info' },
    )
  } catch {
    return // 用户点了「稍后」
  }
  const loading = ElMessage({ message: '正在下载更新…', duration: 0 })
  try {
    await update.downloadAndInstall()
    loading.close()
    const proc = await import('@tauri-apps/plugin-process')
    await proc.relaunch()
  } catch (e) {
    loading.close()
    ElMessage.error('更新失败,请稍后重试或手动下载')
    console.error('[update] downloadAndInstall 失败', e)
  }
}
```

- [ ] **Step 3: 验证桌面构建打进 updater 调用**

Run: `cd frontend && npm run build:desktop >/dev/null 2>&1 && grep -rl "plugin:updater" dist-desktop/assets/ | head -1`
Expected: 命中一个文件（说明 updater 调用进了桌面包）

- [ ] **Step 4: 验证在线构建 tree-shake 掉**

Run: `cd frontend && VITE_BASE_URL=/ai-builder/ npx vite build --outDir /tmp/online-upd --emptyOutDir >/dev/null 2>&1; grep -rl "plugin:updater" /tmp/online-upd/assets/ | wc -l`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/desktopUpdate.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(desktop): desktopUpdate 检查/下载/重启(ElMessageBox 提示)"
```

---

### Task 9: 启动自动检查 + 手动「检查更新」按钮

**Files:**
- Modify: `frontend/src/App.vue`(根组件 onMounted 自动检查)
- Modify: `frontend/src/components/v2/RailSidebar.vue`(手动按钮)

- [ ] **Step 1: 看 App.vue 结构**

Run: `sed -n '1,40p' frontend/src/App.vue`
Expected: 看到 `<script setup>` 与是否已有 `onMounted`。

- [ ] **Step 2: App.vue 启动检查**

在 `frontend/src/App.vue` 的 `<script setup lang="ts">` 里加(已有 onMounted 则并入):

```typescript
import { onMounted } from 'vue'
import { checkAndPromptUpdate } from '@/utils/desktopUpdate'

onMounted(() => {
  // 仅桌面端;启动静默检查,有新版才弹窗。
  void checkAndPromptUpdate({ silentIfNone: true })
})
```

- [ ] **Step 3: RailSidebar 手动按钮**

在 `frontend/src/components/v2/RailSidebar.vue` 底部用户区(参考已有 `platformEntryVisible` 那段 __DESKTOP__ 条件渲染)加一个仅 `__DESKTOP__` 显示的按钮:

```vue
<button v-if="__DESKTOP__" class="nav-secondary" @click="onCheckUpdate">检查更新</button>
```

`<script setup>` 里:
```typescript
import { checkAndPromptUpdate } from '@/utils/desktopUpdate'
function onCheckUpdate() { void checkAndPromptUpdate({ silentIfNone: false }) }
```

> 样式复用该文件已有的次级按钮 class(实现时照抄邻近「退出登录」等按钮的 class 名,别新造)。

- [ ] **Step 4: 验证构建**

Run: `cd frontend && npm run build:desktop 2>&1 | tail -2`
Expected: `✓ built`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.vue frontend/src/components/v2/RailSidebar.vue
git commit -m "feat(desktop): 启动自动检查更新 + 手动检查按钮"
```

---

## Phase 4 — 发版脚本

### Task 10: `scripts/release-desktop.sh`

**Files:**
- Create: `scripts/release-desktop.sh`

- [ ] **Step 1: 写脚本**

`scripts/release-desktop.sh`:

```bash
#!/usr/bin/env bash
# 一键发版桌面更新: build(arm+x64,签名+updater产物) → 拼 latest.json → 上传 account-service。
# 用法: VERSION=0.2.0 NOTES="修复xx" ADMIN_USER=xxx ADMIN_PASS=xxx \
#       TAURI_SIGNING_PRIVATE_KEY_PASSWORD=xxx bash scripts/release-desktop.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:?需要 VERSION}"
NOTES="${NOTES:-}"
BASE="https://agent.dfy.definesys.cn/account-api"
KEY="$ROOT/keys/ruijing-updater.key"
[ -f "$KEY" ] || { echo "缺私钥 $KEY"; exit 1; }
export TAURI_SIGNING_PRIVATE_KEY="$(cat "$KEY")"
: "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:?需要私钥密码}"

echo "==> 同步 tauri.conf.json version=$VERSION"
# macOS sed
sed -i '' "s/\"version\": \"[^\"]*\"/\"version\": \"$VERSION\"/" "$ROOT/src-tauri/tauri.conf.json"

echo "==> build arm + x64 (含 updater 产物)"
bash "$ROOT/scripts/build-desktop.sh"
bash "$ROOT/scripts/build-desktop-x86.sh"

ARM_DIR="$ROOT/src-tauri/target/release/bundle/macos"
X64_DIR="$ROOT/src-tauri/target/x86_64-apple-darwin/release/bundle/macos"
ARM_TGZ="$(ls "$ARM_DIR"/*.app.tar.gz | head -1)"
X64_TGZ="$(ls "$X64_DIR"/*.app.tar.gz | head -1)"
ARM_NAME="ruijing-${VERSION}-aarch64.app.tar.gz"
X64_NAME="ruijing-${VERSION}-x86_64.app.tar.gz"
cp "$ARM_TGZ" "/tmp/$ARM_NAME"; cp "$X64_TGZ" "/tmp/$X64_NAME"
ARM_SIG="$(cat "${ARM_TGZ}.sig")"
X64_SIG="$(cat "${X64_TGZ}.sig")"
PUB_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > /tmp/latest.json <<JSON
{
  "version": "$VERSION",
  "notes": "$NOTES",
  "pub_date": "$PUB_DATE",
  "platforms": {
    "darwin-aarch64": { "signature": $(printf '%s' "$ARM_SIG" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))'), "url": "$BASE/desktop-updates/$ARM_NAME" },
    "darwin-x86_64":  { "signature": $(printf '%s' "$X64_SIG" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))'), "url": "$BASE/desktop-updates/$X64_NAME" }
  }
}
JSON

echo "==> 平台管理员登录"
TOKEN="$(curl -s -X POST "$BASE/api/desktop-auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${ADMIN_USER:?}\",\"password\":\"${ADMIN_PASS:?}\"}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')"

echo "==> 上传 manifest + 包"
curl -s -X POST "$BASE/desktop-updates/admin/publish" \
  -H "Authorization: Bearer $TOKEN" \
  -F "manifest=</tmp/latest.json" \
  -F "packages=@/tmp/$ARM_NAME" \
  -F "packages=@/tmp/$X64_NAME"
echo
echo "==> 校验线上 manifest"
curl -s "$BASE/desktop-updates/latest.json" | python3 -m json.tool | head -5
echo "==> 完成 v$VERSION"
```

- [ ] **Step 2: 语法检查**

Run: `bash -n scripts/release-desktop.sh && chmod +x scripts/release-desktop.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/release-desktop.sh
git commit -m "feat(desktop): 一键发版脚本 release-desktop.sh"
```

---

## Phase 5 — 部署 + 端到端验证(人工门)

### Task 11: 部署 account-service(含更新端点)

> 人工/需 k8s 凭证。参考 `docs/account-service-deploy.md` + memory `deploy_crane_workaround_2026_06_08`。

- [ ] **Step 1: 重建镜像并推送**(crane 直推,绕 docker push broken pipe)

按 `deploy_crane_workaround` 三步:build → crane push → set image。镜像 tag 升一位(如 `dev-20260616-acctsvc4`)。

- [ ] **Step 2: 滚动 account-service**

```bash
kubectl -n apaas-builder set image deploy/account-service-dev account-service=hub.dfy.definesys.cn/ai-builder/apaas-builder:<新tag>
kubectl -n apaas-builder rollout status deploy/account-service-dev
```

- [ ] **Step 3: 验证端点活着(未发版时 manifest 404)**

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://agent.dfy.definesys.cn/account-api/desktop-updates/latest.json
```
Expected: `404`（还没发版,正常;updater 把 404 当"无更新")

---

### Task 12: 合体最终包 + 端到端更新验证

> 人工门:验证整条更新链路。这一版 = openExternal 修复 + updater,作为最后一次手动分发。

- [ ] **Step 1: 发首版(基线 v0.2.0)**

> 前提:**公网 account-service 上需有一个平台管理员账号**(就是管理后台开号用的那个 `is_platform_admin=True` 账号)。发版脚本用它登录拿 token 调上传端点。没有的话先在管理后台/直接入库建一个。

确保私钥密码 + 平台管理员账号就绪,跑:
```bash
VERSION=0.2.0 NOTES="桌面端首个自动更新版本(含低代码后台外链修复)" \
ADMIN_USER=<平台管理员> ADMIN_PASS=<密码> \
TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<私钥密码> \
bash scripts/release-desktop.sh
```
Expected: 线上 `latest.json` 返回 v0.2.0;两架构包可下载。

- [ ] **Step 2: 安装 v0.2.0 基线包**(arm + 一台 Intel/同事)

把 `/tmp/ruijing-0.2.0-*.app.tar.gz` 对应的 dmg(build 产物)装上,或直接解压 .app 到 /Applications。**这是最后一次手动安装。**

- [ ] **Step 3: 发一个更高版本验证升级**

```bash
VERSION=0.2.1 NOTES="验证自动更新" ADMIN_USER=... ADMIN_PASS=... \
TAURI_SIGNING_PRIVATE_KEY_PASSWORD=... bash scripts/release-desktop.sh
```

- [ ] **Step 4: 在已装 v0.2.0 的机器上重启 app**

Expected:启动弹「发现新版本 0.2.1」→ 点「立即更新」→ 下载→验签→替换→重启→版本变 0.2.1。手动点侧栏「检查更新」在最新版时提示「已是最新版本」。

- [ ] **Step 5: 验签失败回归**(可选,确认安全)

手动把线上 latest.json 的某架构 signature 改坏一位 → app 检查更新 → 下载后**验签失败、拒绝安装**(不会装上被篡改的包)。验证完恢复正确 manifest。

- [ ] **Step 6: 收尾**

更新 memory(桌面自动更新已上线 + 发版命令 + 私钥位置提醒);如需 push 分支由用户决定。

---

## 完成标准

- account-service 三端点上线,9 个服务端测试绿。
- 桌面包内置 updater:启动检测到新版能一键升级重启,验签生效。
- `release-desktop.sh` 一条命令完成发版。
- 合体 v0.2.0 包分发后,后续版本全自动更新,不再手动发包。
