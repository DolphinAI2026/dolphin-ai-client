# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: 桌面 sidecar (onefile, 含前端 dist-desktop)
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

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
hiddenimports += collect_submodules("app")
hiddenimports += [
    "app.main",
    "greenlet", "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "httptools", "websockets",
    "bcrypt", "charset_normalizer",
    "jose.backends.cryptography_backend",
    "lxml._elementpath",
    # aiomysql: quick_db.py 在 module 顶层 import aiomysql — 不可排除
    "aiomysql", "pymysql",
    # anyio backends
    "anyio._backends._asyncio", "anyio._backends._trio",
    # email validation
    "email_validator",
    # passlib handlers
    "passlib.handlers.bcrypt", "passlib.handlers.sha2_crypt",
    # starlette / fastapi
    "starlette", "fastapi",
    # httpx for aiohttp-style requests
    "httpx", "httpcore",
    # multipart form parsing (可导入名是 multipart, 非 PyPI 名 python-multipart)
    "multipart",
    # gitpython
    "git",
    # yaml
    "yaml",
    # other common dynamic
    "sniffio", "exceptiongroup",
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
# 注意: aiomysql/pymysql 不能排除 — quick_db.py 在模块顶层 import aiomysql
excludes = [
    "playwright", "kubernetes_asyncio", "kubernetes",
    "pytest", "pytest_asyncio", "watchfiles",
    # Phase 0 不触发文档/PDF/表格解析, 先排除 (Phase 1 按需放回):
    "pdfplumber", "pdfminer", "pypdfium2", "pypdfium2_raw",
    "docx", "pptx", "openpyxl", "PIL",
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
