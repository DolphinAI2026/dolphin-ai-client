# 桌面交付驾驶舱 Phase 0 — 打包 Spike 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 证明「Tauri(macOS) 壳 + PyInstaller 打包的 FastAPI sidecar + WKWebView 同源加载现有 Vue 前端 + 连真实 aPaaS/LLM」这条地基跑得通——产出一个能双击运行、登录 trial 环境(mars 租户)并完成一次低代码配置动作的 `.app`。不碰交付层。

**Architecture:** sidecar 一体化同源方案。Python 后端用 `VITE_BASE_URL=/` 重新构建的前端 dist 由 FastAPI 自己用 `_SpaStaticFiles` 托管在 `/`，API 仍在 `/api`，二者同源 → 前端零改、无需 CORS/反代/端口注入。PyInstaller 把后端(含前端 dist)打成 onefile 单体二进制；Tauri 作为外壳用 `externalBin` 捆绑它、启动时按动态端口拉起、轮询 `/api/health` 就绪后用 `WebviewUrl::External` 让 WKWebView 加载 `http://127.0.0.1:<port>/`，退出时杀掉 sidecar。aPaaS/LLM 凭据通过 app-data 目录下的 `profile.env` 注入(不进仓库、不进 bundle)。

**Tech Stack:** Tauri 2.x (Rust, `tauri-plugin-shell`)、Python 3.13 + FastAPI/uvicorn + PyInstaller 6.x (onefile)、Vue 3 + Vite (桌面 base=`/` 构建)、SQLite (aiosqlite)。

---

## 前置说明(实现者必读)

- **本机环境**：macOS Apple Silicon，target triple = `aarch64-apple-darwin`(用 `rustc --print host-tuple` 确认)。Python 在 `backend/.venv`(3.13)。前端在 `frontend/`(已有 `node_modules`、`dist`)。
- **不要碰在线版行为**：所有桌面专属逻辑用环境变量 `DESKTOP_MODE=1` 门控；前端桌面构建输出到独立目录 `frontend/dist-desktop`，不覆盖在线版 `frontend/dist`。
- **关键事实锚点**(已核实)：
  - 健康检查已存在：`backend/app/main.py:410-412` `@app.get("/api/health")` → `{"status":"ok"}`。
  - SPA 静态托管基类已存在：`backend/app/main.py:371-378` `class _SpaStaticFiles(StaticFiles)`(404→index.html 回退)。
  - 业务 API 路由前缀 `/api`：`backend/app/main.py:332` 起的 `include_router(..., prefix="/api")`。
  - 配置在 import 期实例化：`backend/app/config.py:139` `settings = Settings()`(缺 `JWT_SECRET_KEY` 即 ValidationError)。
  - playwright 顶层 import：`backend/app/coding/browser_service.py:13`；其路由注册于 `backend/app/main.py:150`(`browser.router`)。
  - SQLite URL 形如 `sqlite+aiosqlite:////绝对路径`(四斜杠)；相对路径会被 `config.py:118-140` 锚定到 `backend/`。
- **本计划的"测试"约定**：Task 1–3 是后端 Python，走标准 TDD(先写失败测试)。Task 4–9 是打包/集成，无法单元化，"测试"= 给出确切命令 + 期望输出的冒烟验证;每步都能独立判定通过/失败。

---

## File Structure

新增文件：
- `backend/desktop_sidecar.py` — 桌面 sidecar 入口：解析 `--port`/`--data-dir`，注入环境变量(SQLite 路径、JWT 密钥持久化、`ALLOW_DEFAULT_ENCRYPTION_KEY`、`DESKTOP_MODE`)，加载可选 `profile.env`，再 `from app.main import app` 并 `uvicorn.run(app, ...)`。一个职责：把"裸进程"变成"自带本地配置的可冻结进程"。
- `backend/ruijing-sidecar.spec` — PyInstaller 打包描述：collect/hidden-import/exclude/数据文件，产 onefile。
- `backend/tests/test_desktop_sidecar.py` — Task 3 的测试。
- `backend/tests/test_desktop_static_mount.py` — Task 2 的测试。
- `src-tauri/` — Tauri 工程(`npx tauri init` 生成)，其中重点改 `tauri.conf.json`、`Cargo.toml`、`src/lib.rs`、`capabilities/default.json`。
- `src-tauri/binaries/` — 放打包好的 sidecar(带 triple 后缀)。
- `scripts/build-desktop.sh` — 串起：前端桌面构建 → PyInstaller → rename 到 `src-tauri/binaries/` → `tauri build`。

修改文件：
- `backend/app/coding/browser_service.py` — 把 playwright 顶层 import 改为函数内惰性 import(使模块在无 playwright 时可被 import，便于 PyInstaller 排除)。
- `backend/app/main.py` — 文件末尾新增 DESKTOP_MODE 下挂载 `frontend/dist-desktop` 到 `/` 的逻辑(复用 `_SpaStaticFiles`，frozen 时从 `sys._MEIPASS` 定位)。
- `frontend/package.json` — 新增 `build:desktop` 脚本。
- `backend/.gitignore`(或根 `.gitignore`) — 忽略 `frontend/dist-desktop`、`src-tauri/binaries/`、`backend/build`、`backend/dist`。

---

## Task 1: 让 browser_service 的 playwright 改为惰性 import

**Files:**
- Modify: `backend/app/coding/browser_service.py:13`(及实际用到 playwright 类型的方法体)
- Test: `backend/tests/test_browser_service_import.py`(Create)

目标：模块顶层不再 import playwright，使得卸载/排除 playwright 后 `import app.coding.browser_service` 仍成功(PyInstaller `--exclude-module playwright` 才不会在启动链上崩)。

- [ ] **Step 1: 先读懂现状**

Run: `sed -n '1,40p' backend/app/coding/browser_service.py`
确认第 13 行附近是 `from playwright.async_api import ...`，并记下后面哪些方法用到这些符号(如 `async_playwright`、`Browser`、`Page`)。

- [ ] **Step 2: 写失败测试 — 模拟 playwright 不可用仍能 import 模块**

Create `backend/tests/test_browser_service_import.py`:

```python
import builtins
import importlib
import sys

import pytest


def test_browser_service_imports_without_playwright(monkeypatch):
    """playwright 被排除/未安装时, 模块顶层 import 不应失败 (PyInstaller exclude 前提)。"""
    # 卸掉已加载的目标模块与 playwright, 强制重新 import
    for name in list(sys.modules):
        if name == "app.coding.browser_service" or name.startswith("playwright"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # 顶层 import 必须成功(惰性化之后)
    mod = importlib.import_module("app.coding.browser_service")
    assert mod is not None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_browser_service_import.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'playwright'`(因为顶层还在 import)。

- [ ] **Step 4: 惰性化 import**

把 `backend/app/coding/browser_service.py` 顶层的 `from playwright.async_api import async_playwright, Browser, Page`(以实际行为准)删除；在每个真正用到它们的方法体开头加局部 import。例如：

```python
# 顶层删除 playwright import; 若有类型注解用到 Browser/Page, 改成字符串注解或 TYPE_CHECKING 块:
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # 仅类型检查期, 运行/打包不 import
    from playwright.async_api import Browser, Page


class BrowserService:
    async def _ensure_browser(self):
        from playwright.async_api import async_playwright  # 惰性: 仅调用时 import
        self._pw = await async_playwright().start()
        # ...原逻辑不变
```

对每个用到 `async_playwright`/`Browser`/`Page` 运行期符号的方法，都在方法体内 `from playwright.async_api import ...`。类属性/注解一律改成字符串或放进 `TYPE_CHECKING`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_browser_service_import.py -v`
Expected: PASS。

- [ ] **Step 6: 回归 — 确认正常环境下整个 app 仍能 import**

Run: `cd backend && .venv/bin/python -c "import app.main; print('app import OK')"`
Expected: 打印 `app import OK`，无 traceback。

- [ ] **Step 7: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/coding/browser_service.py backend/tests/test_browser_service_import.py
git commit -m "refactor(coding): playwright 改惰性 import, 为桌面 sidecar 排除做准备

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: DESKTOP_MODE 下用 FastAPI 同源托管桌面前端 dist

**Files:**
- Modify: `backend/app/main.py`(文件末尾，`/api/health` 之后追加)
- Test: `backend/tests/test_desktop_static_mount.py`(Create)

目标：当 `DESKTOP_MODE=1` 时，把桌面前端构建目录挂到 `/`，复用现成 `_SpaStaticFiles`(404→index.html)。dev(非冻结)从 `frontend/dist-desktop` 取；冻结(`sys._MEIPASS`)从 `frontend_dist` 取。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_desktop_static_mount.py`:

```python
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_desktop_mode_serves_spa_index(monkeypatch, tmp_path):
    """DESKTOP_MODE=1 且存在桌面 dist 时, GET / 返回前端 index.html; 未知前端路由回退 index.html。"""
    # 造一个假的桌面 dist
    fe = tmp_path / "dist-desktop"
    fe.mkdir()
    (fe / "index.html").write_text("<!doctype html><title>desktop-spa</title>", encoding="utf-8")

    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("DESKTOP_FRONTEND_DIR", str(fe))  # 测试用显式目录覆盖

    # 必须在设置 env 之后再 import, 否则 mount 逻辑读不到 DESKTOP_MODE
    import importlib
    import app.main as main_mod
    importlib.reload(main_mod)

    client = TestClient(main_mod.app)
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "desktop-spa" in r_root.text

    r_spa = client.get("/some/client/route")  # 前端 history 路由
    assert r_spa.status_code == 200
    assert "desktop-spa" in r_spa.text

    # API 仍优先于静态回退
    r_api = client.get("/api/health")
    assert r_api.status_code == 200
    assert r_api.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_static_mount.py -v`
Expected: FAIL — `GET /` 返回 404(还没挂载主前端)。

- [ ] **Step 3: 在 main.py 末尾追加桌面挂载逻辑**

在 `backend/app/main.py` 文件**最末尾**(即 `@app.get("/api/health")` 之后)追加：

```python
# ── 桌面 sidecar: DESKTOP_MODE 下同源托管桌面前端构建产物 ──────────────
# 在线版不受影响(默认 DESKTOP_MODE 未设)。必须放在所有 include_router /
# app.mount / runtime_proxy 之后, 让显式 API/admin/反代路由优先匹配,
# 这个 "/" 挂载只作为前端 SPA 的兜底。
if os.environ.get("DESKTOP_MODE") == "1":
    import sys as _sys

    _explicit = os.environ.get("DESKTOP_FRONTEND_DIR")
    if _explicit:
        _desktop_fe = Path(_explicit)
    elif getattr(_sys, "_MEIPASS", None):  # PyInstaller 冻结态
        _desktop_fe = Path(_sys._MEIPASS) / "frontend_dist"
    else:  # 本机 dev
        _desktop_fe = Path(__file__).resolve().parents[2] / "frontend" / "dist-desktop"

    if _desktop_fe.is_dir():
        app.mount("/", _SpaStaticFiles(directory=str(_desktop_fe), html=True), name="desktop-frontend")
        logger.info("[desktop] mounted frontend SPA at / from %s", _desktop_fe)
    else:
        logger.warning("[desktop] DESKTOP_MODE=1 but frontend dir not found: %s", _desktop_fe)
```

确认文件顶部已 import `os`(main.py:4 有)、`Path`(已用于 admin-spa 挂载，存在)、`logger`(已用)。若 `Path` 未在顶层 import，则在文件顶部 import 区加 `from pathlib import Path`(先 `grep -n "from pathlib import Path" backend/app/main.py` 确认)。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_static_mount.py -v`
Expected: PASS(3 个断言全过)。

- [ ] **Step 5: 回归 — 非 DESKTOP_MODE 时不挂载(在线版不变)**

Run: `cd backend && DESKTOP_MODE= .venv/bin/python -c "import app.main as m; from fastapi.testclient import TestClient; c=TestClient(m.app); print('root status', c.get('/').status_code)"`
Expected: `root status 404`(在线版根路径行为不变；只要不是 200 的 SPA 即可)。

- [ ] **Step 6: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/main.py backend/tests/test_desktop_static_mount.py
git commit -m "feat(desktop): DESKTOP_MODE 下 FastAPI 同源托管前端 SPA

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 桌面 sidecar 入口 desktop_sidecar.py

**Files:**
- Create: `backend/desktop_sidecar.py`
- Test: `backend/tests/test_desktop_sidecar.py`

目标：一个可被 PyInstaller 当入口的脚本：解析参数→注入所有必需环境变量(在 `import app.*` 之前)→加载可选 `profile.env`→启动 uvicorn(传 app 对象而非字符串)。

- [ ] **Step 1: 写失败测试(测纯函数, 不真起 uvicorn)**

Create `backend/tests/test_desktop_sidecar.py`:

```python
import os
from pathlib import Path

import desktop_sidecar as ds


def test_load_profile_env_merges_into_environ(tmp_path, monkeypatch):
    p = tmp_path / "profile.env"
    p.write_text(
        "# comment\nAPAAS_BASE_URL=https://trial.example\n"
        'ANTHROPIC_API_KEY="sk-abc"\n\nEMPTYLINE_IGNORED\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("APAAS_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ds.load_profile_env(p)
    assert os.environ["APAAS_BASE_URL"] == "https://trial.example"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-abc"  # 引号被剥掉


def test_load_profile_env_missing_file_is_noop(tmp_path):
    ds.load_profile_env(tmp_path / "nope.env")  # 不存在不报错


def test_ensure_jwt_secret_persists(tmp_path):
    s1 = ds.ensure_jwt_secret(tmp_path)
    s2 = ds.ensure_jwt_secret(tmp_path)
    assert s1 and s1 == s2  # 第二次复用持久化的值
    assert (tmp_path / "jwt_secret").read_text(encoding="utf-8").strip() == s1


def test_build_env_sets_required_keys(tmp_path):
    env = ds.build_env(data_dir=tmp_path, port=8799)
    assert env["DESKTOP_MODE"] == "1"
    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "8799"
    assert env["DATABASE_URL"] == f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"
    assert env["ALLOW_DEFAULT_ENCRYPTION_KEY"] == "1"
    assert env["JWT_SECRET_KEY"]  # 非空
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_sidecar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'desktop_sidecar'`。

- [ ] **Step 3: 实现 desktop_sidecar.py**

Create `backend/desktop_sidecar.py`:

```python
"""桌面交付驾驶舱 — 本地 sidecar 入口 (被 PyInstaller 打成 onefile)。

职责: 在 import 任何 app.* (会在 import 期实例化 Settings) 之前, 把本地运行
所需的全部环境变量注入 os.environ, 然后以 app 对象方式启动 uvicorn。
"""
import argparse
import multiprocessing
import os
import secrets
from pathlib import Path


def load_profile_env(path: Path) -> None:
    """把 app-data 目录下的 profile.env (dotenv 风格) 合并进 os.environ。
    用于注入 trial aPaaS / LLM 凭据, 不进仓库也不进 bundle。文件不存在则 no-op。
    """
    if not path or not Path(path).is_file():
        return
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val


def ensure_jwt_secret(data_dir: Path) -> str:
    """每安装实例持久化一个 JWT 密钥 (避免每次启动 session 失效)。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "jwt_secret"
    if f.is_file():
        existing = f.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    val = secrets.token_urlsafe(48)
    f.write_text(val, encoding="utf-8")
    return val


def build_env(data_dir: Path, port: int) -> dict:
    """构造并写入本地运行所需的环境变量, 返回写入的子集 (便于测试)。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    written = {
        "DESKTOP_MODE": "1",
        "HOST": "127.0.0.1",
        "PORT": str(port),
        # 绝对路径(四斜杠), 避免被 config._normalize_database_url 锚定到 backend/
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        # Phase 0 spike: 允许默认加密 key。Phase 1 改为每实例生成持久化 ENCRYPTION_KEY。
        "ALLOW_DEFAULT_ENCRYPTION_KEY": "1",
        "JWT_SECRET_KEY": ensure_jwt_secret(data_dir),
    }
    for k, v in written.items():
        os.environ[k] = v
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("SIDECAR_PORT", "8799")))
    parser.add_argument("--data-dir", type=str, default=os.environ.get("SIDECAR_DATA_DIR", ""))
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else (Path.home() / ".ruijing-builder")

    # 1) 先注入基础 env (必须早于任何 app.* import)
    build_env(data_dir=data_dir, port=args.port)
    # 2) 再叠加用户的 profile.env (aPaaS/LLM 凭据), 允许覆盖默认
    load_profile_env(data_dir / "profile.env")

    # 3) 现在才 import app (此时 Settings() 能读到上面注入的 env)
    import uvicorn
    from app.main import app  # noqa: E402  传 app 对象, 不用 "app.main:app" 字符串

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # 冻结二进制下安全 (即便单 worker 也加, 保险)
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_sidecar.py -v`
Expected: PASS(4 个测试全过)。

- [ ] **Step 5: 手动冒烟 — 用解释器直接跑 sidecar(未打包), 验证 SQLite 起服务 + 健康检查**

```bash
cd backend
.venv/bin/python desktop_sidecar.py --port 8799 --data-dir /tmp/ruijing-spike &
SIDECAR_PID=$!
sleep 8   # 等 lifespan (init_db + seed) 起来
curl -s http://127.0.0.1:8799/api/health
echo
kill $SIDECAR_PID
```
Expected: 打印 `{"status":"ok"}`；`/tmp/ruijing-spike/app.db` 与 `jwt_secret` 已生成。

- [ ] **Step 6: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/desktop_sidecar.py backend/tests/test_desktop_sidecar.py
git commit -m "feat(desktop): sidecar 入口 desktop_sidecar.py (env 注入 + uvicorn 启动)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 前端桌面构建脚本 (base=/)

**Files:**
- Modify: `frontend/package.json`(scripts 增 `build:desktop`)

目标：用 `VITE_BASE_URL=/` 构建出 `frontend/dist-desktop`，使 `API_PREFIX` 回落到 `/api`、资产为根相对，配合 sidecar 同源托管。跳过 vue-tsc(预存类型错，参照已有 `build:nocheck`)。

- [ ] **Step 1: 增脚本**

在 `frontend/package.json` 的 `scripts` 块加一行(放在 `build:nocheck` 之后)：

```json
"build:desktop": "VITE_BASE_URL=/ vite build --outDir dist-desktop --emptyOutDir",
```

- [ ] **Step 2: 构建**

Run: `cd frontend && npm run build:desktop`
Expected: 构建成功，生成 `frontend/dist-desktop/index.html` 与 `frontend/dist-desktop/assets/`。

- [ ] **Step 3: 验证产物是根相对路径(关键)**

Run: `grep -o '"/[a-zA-Z]*/assets/[^"]*"' frontend/dist-desktop/index.html | head; grep -c '/ai-builder/' frontend/dist-desktop/index.html`
Expected: 资产引用以 `/assets/...` 开头(不是 `/ai-builder/assets/...`)；`/ai-builder/` 出现次数为 `0`。

- [ ] **Step 4: 端到端验证(dev 态) — sidecar 同源托管这份 dist**

```bash
cd backend
DESKTOP_FRONTEND_DIR="$(cd ../frontend/dist-desktop && pwd)" \
  .venv/bin/python desktop_sidecar.py --port 8799 --data-dir /tmp/ruijing-spike &
SIDECAR_PID=$!
sleep 8
echo "--- root (应为前端 HTML) ---"; curl -s http://127.0.0.1:8799/ | head -c 200; echo
echo "--- health (应为 JSON) ---"; curl -s http://127.0.0.1:8799/api/health; echo
kill $SIDECAR_PID
```
Expected: `/` 返回前端 `index.html`(含 `<div id="app">` 之类)；`/api/health` 返回 `{"status":"ok"}`。
> 注：此处 `DESKTOP_FRONTEND_DIR` 仅 dev 验证用；冻结态由 PyInstaller 把 dist 放进 `_MEIPASS/frontend_dist`，Task 5 处理。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
printf '\nfrontend/dist-desktop/\nsrc-tauri/binaries/\nbackend/build/\nbackend/dist/\n' >> .gitignore
git add frontend/package.json .gitignore
git commit -m "build(desktop): 增 build:desktop (base=/), 桌面前端构建到 dist-desktop

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: PyInstaller 打包 sidecar (onefile + 内嵌前端)

**Files:**
- Create: `backend/ruijing-sidecar.spec`

目标：把 `desktop_sidecar.py` 打成单文件可执行(含前端 dist-desktop、模板、tool_registry.yaml)，排除 playwright/k8s/重文档库，补齐 uvicorn/pydantic/sqlalchemy/cryptography/jose/lxml 等动态依赖。

- [ ] **Step 1: 确认 PyInstaller 已装(6.x)**

Run: `cd backend && .venv/bin/python -m PyInstaller --version || .venv/bin/pip install "pyinstaller>=6.6"`
Expected: 输出版本 ≥ 6.x。

- [ ] **Step 2: 写 spec 文件**

Create `backend/ruijing-sidecar.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: 桌面 sidecar (onefile, 含前端 dist-desktop)
import os
from PyInstaller.utils.hooks import (
    collect_all, collect_submodules, collect_data_files, collect_dynamic_libs,
)

BACKEND = os.path.abspath(".")            # 须在 backend/ 下运行 pyinstaller
FRONTEND_DIST = os.path.abspath(os.path.join("..", "frontend", "dist-desktop"))

datas, binaries, hiddenimports = [], [], []

# 带 C 扩展 / 数据 / 动态子模块的包: 一次性全收
for pkg in ["pydantic", "pydantic_core", "mcp", "passlib", "cryptography", "sse_starlette"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# 动态 import 的子模块
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("jose")
hiddenimports += collect_submodules("lxml")
hiddenimports += collect_submodules("sqlalchemy.dialects")
hiddenimports += [
    "app.main",                      # 入口用 from app.main import app, 保险再列
    "greenlet", "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "httptools", "websockets",
    "bcrypt", "charset_normalizer",
    "jose.backends.cryptography_backend",
    "lxml._elementpath",
]

# TLS 证书 (httpx)
datas += collect_data_files("certifi")

# 前端构建产物 -> _MEIPASS/frontend_dist (与 main.py 的桌面挂载约定一致)
if os.path.isdir(FRONTEND_DIST):
    datas += [(FRONTEND_DIST, "frontend_dist")]

# 后端运行期数据文件 (存在才加)
for src, dst in [("app/templates", "app/templates"),
                 ("templates", "templates"),
                 ("tool_registry.yaml", "."),
                 ("app/static", "app/static")]:
    if os.path.exists(os.path.join(BACKEND, src)):
        datas += [(os.path.join(BACKEND, src), dst)]

# Phase 0 不需要的重依赖: 排除以缩小体积、避开无法冻结的 playwright
excludes = [
    "playwright", "kubernetes_asyncio", "kubernetes",
    "pytest", "pytest_asyncio", "watchfiles",
    # Phase 0 不触发文档/PDF/表格解析, 先排除 (Phase 1 按需放回):
    "pdfplumber", "pdfminer", "pypdfium2", "pypdfium2_raw",
    "docx", "pptx", "openpyxl", "PIL",
    # 仅 MySQL 用 (sidecar 走 sqlite):
    "aiomysql", "pymysql",
]

a = Analysis(
    ["desktop_sidecar.py"],
    pathex=[BACKEND],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="ruijing-sidecar",
    debug=False, strip=False, upx=False, console=True,
    onefile=True,
)
```
> 注：若 `routes/quick_db.py` 等在启动链上硬 import `aiomysql`，build 后冒烟会暴露 ModuleNotFoundError——届时把 `aiomysql`/`pymysql` 从 `excludes` 移除并加进 `hiddenimports`。先按上面排除，靠 Step 4 冒烟迭代。

- [ ] **Step 3: 构建(确保前端 dist-desktop 已存在 — Task 4 产出)**

Run: `cd backend && .venv/bin/python -m PyInstaller ruijing-sidecar.spec --noconfirm`
Expected: 末尾 `Building EXE ... completed successfully`，产物在 `backend/dist/ruijing-sidecar`(单文件)。
> 若报缺模块：把模块名加入 spec 的 `hiddenimports` 重跑，直到通过。

- [ ] **Step 4: 冒烟 — 跑冻结二进制, 验证健康检查 + 同源前端 + 一次 SQLite/JWT 路径**

```bash
cd backend
./dist/ruijing-sidecar --port 8798 --data-dir /tmp/ruijing-frozen &
PID=$!
# onefile 首启要解压, 给足时间
for i in $(seq 1 30); do
  sleep 1
  if curl -sf http://127.0.0.1:8798/api/health >/dev/null; then break; fi
done
echo "--- health ---"; curl -s http://127.0.0.1:8798/api/health; echo
echo "--- root html ---"; curl -s http://127.0.0.1:8798/ | grep -o '<div id="app">' | head -1
echo "--- assets reachable ---"; curl -s -o /dev/null -w "%{http_code}\n" "$(curl -s http://127.0.0.1:8798/ | grep -o '/assets/[^"]*\.js' | head -1 | sed 's#^#http://127.0.0.1:8798#')"
kill $PID
```
Expected: health = `{"status":"ok"}`；root 含 `<div id="app">`；assets 的 js 返回 `200`。这条覆盖了 uvicorn 冻结、pydantic/sqlalchemy/cryptography/jose 启动链、前端内嵌三大故障面。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/ruijing-sidecar.spec
git commit -m "build(desktop): PyInstaller spec 打 sidecar onefile (内嵌前端, 排除 playwright/k8s)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Tauri 工程脚手架 + 配置

**Files:**
- Create: `src-tauri/`(`npx tauri init` 生成)
- Modify: `src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、`src-tauri/capabilities/default.json`

目标：在仓库根初始化 Tauri 工程，配好 externalBin、macOS ATS、不自动开窗、shell 插件与 sidecar 权限。

- [ ] **Step 1: 装 CLI 并 init**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
npm install -D @tauri-apps/cli@^2
npx tauri init --app-name "睿鲸 Builder" --window-title "睿鲸 Builder" \
  --frontend-dist "../frontend/dist-desktop" --dev-url "http://localhost:5173" \
  --before-dev-command "" --before-build-command ""
```
Expected: 生成 `src-tauri/`(含 `tauri.conf.json`、`Cargo.toml`、`src/`、`capabilities/`)。
> 若交互式提示，按上面值回答；`--before-*-command` 留空(我们用独立 build 脚本)。

- [ ] **Step 2: 确认 target triple**

Run: `rustc --print host-tuple`
Expected: `aarch64-apple-darwin`(记下，Task 7 重命名要用)。

- [ ] **Step 3: 配 tauri.conf.json**

编辑 `src-tauri/tauri.conf.json`，确保如下键(以 v2 schema 为准，字段名以 `npx tauri init` 生成的为基础微调)：

```json
{
  "productName": "睿鲸 Builder",
  "identifier": "com.ruijing.builder",
  "build": {
    "frontendDist": "../frontend/dist-desktop"
  },
  "app": {
    "windows": [],
    "security": { "csp": null }
  },
  "bundle": {
    "active": true,
    "targets": ["app", "dmg"],
    "externalBin": ["binaries/ruijing-sidecar"],
    "macOS": {
      "exceptionDomain": ""
    }
  }
}
```
要点：`"windows": []` → 不自动开窗(Task 7 在 sidecar 就绪后手动建窗)；`externalBin` 写 stem(磁盘文件带 triple 后缀)；`exceptionDomain: ""` → 放行明文 loopback(WKWebView 才能加载 http://127.0.0.1)。

- [ ] **Step 4: Cargo.toml 加 shell 插件**

在 `src-tauri/Cargo.toml` 的 `[dependencies]` 加：

```toml
tauri-plugin-shell = "2"
ureq = "2"
```
(`ureq` 用于就绪轮询的轻量 HTTP GET。)

- [ ] **Step 5: capabilities 放行 sidecar spawn**

编辑 `src-tauri/capabilities/default.json`，`permissions` 数组加：

```json
{
  "identifier": "shell:allow-spawn",
  "allow": [{ "name": "binaries/ruijing-sidecar", "sidecar": true, "args": true }]
}
```

- [ ] **Step 6: 提交脚手架**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add src-tauri package.json package-lock.json
git commit -m "build(desktop): Tauri 脚手架 + externalBin/ATS/shell 权限配置

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Rust setup — 拉起 sidecar、等就绪、开窗、退出清理

**Files:**
- Modify: `src-tauri/src/lib.rs`(`npx tauri init` 生成的 `run()` 主体)

目标：启动时选空闲端口 → spawn sidecar(传 `--port`/`--data-dir`)→ 轮询 `/api/health` → 就绪后建 WebView 窗加载 `http://127.0.0.1:<port>/` → 退出 kill sidecar。

- [ ] **Step 1: 改写 lib.rs**

把 `src-tauri/src/lib.rs` 内容替换为：

```rust
use std::sync::Mutex;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct SidecarChild(Mutex<Option<CommandChild>>);

fn pick_free_port() -> u16 {
    // 绑 0 让 OS 分配, 立刻释放, 把端口给 sidecar (spike 容忍 TOCTOU)
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8799)
}

fn wait_healthy(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{}/api/health", port);
    for _ in 0..60 {
        if let Ok(resp) = ureq::get(&url).timeout(std::time::Duration::from_secs(2)).call() {
            if resp.status() == 200 {
                return true;
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(1000));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarChild(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            let port = pick_free_port();

            // app-data 目录 (~/Library/Application Support/com.ruijing.builder)
            let data_dir = handle
                .path()
                .app_data_dir()
                .expect("app_data_dir");
            std::fs::create_dir_all(&data_dir).ok();

            let (mut rx, child) = handle
                .shell()
                .sidecar("ruijing-sidecar")
                .expect("sidecar binary not found")
                .args([
                    "--port".to_string(),
                    port.to_string(),
                    "--data-dir".to_string(),
                    data_dir.to_string_lossy().to_string(),
                ])
                .spawn()
                .expect("failed to spawn sidecar");

            // 存子进程句柄, 退出时 kill
            app.state::<SidecarChild>().0.lock().unwrap().replace(child);

            // 透传 sidecar 日志到 stdout (调试)
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Stdout(b) | CommandEvent::Stderr(b) = event {
                        print!("[sidecar] {}", String::from_utf8_lossy(&b));
                    }
                }
            });

            // 另起线程轮询就绪, 就绪后建窗 (在 main thread 外建窗 v2 允许, 用 AppHandle)
            std::thread::spawn(move || {
                if wait_healthy(port) {
                    let url = format!("http://127.0.0.1:{}/", port);
                    WebviewWindowBuilder::new(
                        &handle,
                        "main",
                        WebviewUrl::External(url.parse().unwrap()),
                    )
                    .title("睿鲸 Builder")
                    .inner_size(1440.0, 900.0)
                    .build()
                    .expect("failed to build window");
                } else {
                    eprintln!("[tauri] sidecar 未在超时内就绪");
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(child) = app.state::<SidecarChild>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
```
> 注：若 `tauri init` 生成的 `main.rs` 调的是 `app_lib::run()` 之类，保持其调用不变，只替换 `lib.rs` 的 `run()` 主体。函数名/crate 名以生成物为准。

- [ ] **Step 2: 把 sidecar 二进制放到位(带 triple 后缀)**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
mkdir -p src-tauri/binaries
TRIPLE=$(rustc --print host-tuple)
cp backend/dist/ruijing-sidecar "src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
chmod +x "src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
ls -la src-tauri/binaries/
```
Expected: 存在 `src-tauri/binaries/ruijing-sidecar-aarch64-apple-darwin` 且可执行。

- [ ] **Step 3: dev 运行整壳(联调)**

Run: `cd "/Users/mars/Vibe Coding/ai-builder" && npx tauri dev`
Expected: 编译 Rust → 控制台出现 `[sidecar] ...` 日志 → 健康就绪后弹出 WebView 窗，显示睿鲸 Builder 登录界面(本地 SQLite、未配 aPaaS 时为 local-only 登录页)。关闭窗口后进程退出，无残留 `ruijing-sidecar`(用 `pgrep -fl ruijing-sidecar` 确认为空)。
> 若窗口白屏：开 WebView 调试(Tauri dev 默认可右键检查)看 console；常见为 ATS(检查 exceptionDomain) 或端口/就绪未命中。

- [ ] **Step 4: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add src-tauri/src/lib.rs src-tauri/Cargo.toml
git commit -m "feat(desktop): Tauri setup 拉起 sidecar/等就绪/建窗/退出清理

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 一键构建脚本 + 出 .app/.dmg

**Files:**
- Create: `scripts/build-desktop.sh`

目标：固定构建顺序(前端→PyInstaller→rename→tauri build)，产出可分发的 `.app`/`.dmg`。

- [ ] **Step 1: 写脚本**

Create `scripts/build-desktop.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="$(rustc --print host-tuple)"

echo "==> 1/4 前端桌面构建 (base=/)"
cd "$ROOT/frontend" && npm run build:desktop

echo "==> 2/4 PyInstaller 打 sidecar (onefile, 内嵌前端)"
cd "$ROOT/backend" && .venv/bin/python -m PyInstaller ruijing-sidecar.spec --noconfirm

echo "==> 3/4 放置 sidecar 二进制 (triple=$TRIPLE)"
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/backend/dist/ruijing-sidecar" "$ROOT/src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
chmod +x "$ROOT/src-tauri/binaries/ruijing-sidecar-${TRIPLE}"

echo "==> 4/4 Tauri 出包"
cd "$ROOT" && npx tauri build

echo "==> 完成。产物:"
ls -la "$ROOT/src-tauri/target/release/bundle/macos/" 2>/dev/null || true
ls -la "$ROOT/src-tauri/target/release/bundle/dmg/" 2>/dev/null || true
```

- [ ] **Step 2: 赋可执行并运行**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
chmod +x scripts/build-desktop.sh
./scripts/build-desktop.sh
```
Expected: 末尾列出 `src-tauri/target/release/bundle/macos/睿鲸 Builder.app` 与 `.../dmg/*.dmg`。
> Phase 0 不签名/公证：首次打开走"右键→打开"或 `xattr -dr com.apple.quarantine "<.app 路径>"`。

- [ ] **Step 3: 双击运行打好的 .app, 验证(无 dev server)**

```bash
open "src-tauri/target/release/bundle/macos/睿鲸 Builder.app"
sleep 20
pgrep -fl ruijing-sidecar   # 应能看到 sidecar 进程
```
Expected: 弹出 WebView 窗显示登录页；`pgrep` 能看到 sidecar；关闭 app 后再 `pgrep -fl ruijing-sidecar` 为空(退出清理生效)。

- [ ] **Step 4: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add scripts/build-desktop.sh
git commit -m "build(desktop): 一键构建脚本 build-desktop.sh (前端→PyInstaller→rename→tauri build)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: 端到端验收 — 连 trial+mars 租户做一次低代码配置

**Files:**
- Create: `~/Library/Application Support/com.ruijing.builder/profile.env`(本机，不进仓库)
- Create: `docs/handoff-2026-06-16-desktop-phase0-spike-result.md`(验收记录)

目标：spike 的真正验收——桌面 app 连真实 aPaaS(trial 环境 + mars 租户)+ LLM，完成一次低代码配置动作，证明地基端到端成立。

- [ ] **Step 1: 写 profile.env(填入 trial 环境 + mars 租户的真实值)**

把团队现有可用的 trial aPaaS / LLM 配置(可从 `backend/.env` 历史或运维处取)写入该文件：

```bash
mkdir -p "$HOME/Library/Application Support/com.ruijing.builder"
cat > "$HOME/Library/Application Support/com.ruijing.builder/profile.env" <<'EOF'
# trial 环境 + mars 租户 (按实际值填; 双端口拓扑则用 APAAS_API_BASE + APAAS_RSA_PUB_URL)
APAAS_BASE_URL=<trial 的 aPaaS base url>
APAAS_API_BASE=<若双端口拓扑: API 根, 否则删本行>
APAAS_RSA_PUB_URL=<若双端口拓扑: RSA 公钥 url, 否则删本行>
APAAS_TENANT_ID=<mars 租户 id>
# LLM (二选一: Anthropic 兼容代理 / OpenAI 兼容网关)
ANTHROPIC_BASE_URL=<llm base url>
ANTHROPIC_API_KEY=<llm key>
ANTHROPIC_MODEL=<model 名>
EOF
```
> 这些值不知道时，向用户/运维确认 trial 环境的 `APAAS_*` 与可用 LLM 凭据。`profile.env` 在 app-data 目录，既不进仓库也不进 bundle。

- [ ] **Step 2: 重启 app 加载 profile**

```bash
pkill -f "睿鲸 Builder" 2>/dev/null; pkill -f ruijing-sidecar 2>/dev/null
open "src-tauri/target/release/bundle/macos/睿鲸 Builder.app"
```

- [ ] **Step 3: 在窗口内走一遍真实流程(人工)**

1. 用 mars 租户的 aPaaS 账号登录(应走 aPaaS 认证而非 local-only)。
2. 进入低代码配置主路径，针对 trial 上的一个应用做一次最小配置动作(例如让配置助手读取某表单/或做一次字段级配置变更)。
3. 观察：能列出 trial 上的真实应用/表单(证明 aPaaS 连通)；配置助手能调用 LLM(证明 LLM 连通)；动作落到 trial 环境。

Expected: 登录成功 + 能看到 trial 真实应用数据 + 完成一次配置动作且无致命报错。

- [ ] **Step 4: 抓证据**

```bash
# 截图窗口 (登录后/配置动作后各一张), 存到 docs
screencapture -o ~/Desktop/phase0-login.png
screencapture -o ~/Desktop/phase0-config.png
```
(或用窗口截图工具。)同时记录 sidecar 控制台是否有 aPaaS 401/LLM 报错。

- [ ] **Step 5: 写验收记录**

Create `docs/handoff-2026-06-16-desktop-phase0-spike-result.md`，记录：是否跑通、各环节结论(打包/启动/同源前端/aPaaS 连通/LLM 连通/退出清理)、踩到的坑与解法、onefile 启动耗时、bundle 体积、遗留问题(交给 Phase 1：profile UX、ENCRYPTION_KEY 每实例化、签名公证、按需放回文档库依赖、onedir 评估)。附截图。

- [ ] **Step 6: 提交验收记录**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add docs/handoff-2026-06-16-desktop-phase0-spike-result.md
git commit -m "docs(desktop): Phase 0 打包 spike 端到端验收记录

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage(对 Phase 0 验收标准逐条核对)：**
- 「Tauri(macOS) 壳」→ Task 6、7。
- 「PyInstaller 打 FastAPI sidecar」→ Task 3、5。
- 「WKWebView 加载 Vue」→ Task 2、4(同源托管)+ Task 7(External URL 建窗)。
- 「连真实 aPaaS/LLM(trial+mars)跑通登录 + 一次低代码配置」→ Task 9。
- 「本地自签即可，无需 Apple 账号」→ Task 8 Step 2 备注(quarantine 绕过)。
- 「能双击跑的 .app」→ Task 8。
- 裁依赖(playwright/k8s)→ Task 1 + Task 5 excludes。
- 覆盖完整，无遗漏标准。

**2. Placeholder scan：** 计划中的尖括号 `<...>` 仅出现在 Task 9 的 `profile.env`(真实凭据本就是 per-install 机密，不能硬编码进计划)与 lib.rs 的"以生成物为准"备注——均为运行者必须按本机实际填的值，非偷懒占位。其余步骤均给了可直接跑的完整代码/命令。

**3. Type/命名一致性：**
- sidecar 名 `ruijing-sidecar` 全程一致(spec EXE name / externalBin / capabilities / sidecar() 调用 / cp 重命名)。
- `DESKTOP_MODE` / `DESKTOP_FRONTEND_DIR` / `frontend_dist`(_MEIPASS 内目录名)在 main.py 挂载逻辑(Task 2)与 spec datas(Task 5)一致。
- 前端构建目录 `frontend/dist-desktop` 在 Task 4(产出)、Task 5(spec 读取)、Task 6(frontendDist)一致。
- 健康路径 `/api/health` 在 Task 4/5 冒烟与 Task 7 `wait_healthy` 一致。
- `desktop_sidecar.py` 的 `--port`/`--data-dir` 参数与 Task 7 spawn 的 args 一致。
- app identifier `com.ruijing.builder` 在 tauri.conf(Task 6)与 profile.env 路径(Task 9)、Rust `app_data_dir`(Task 7)一致。

无不一致。计划可执行。
