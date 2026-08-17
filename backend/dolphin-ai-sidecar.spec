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

# 文档/PDF/表格解析依赖 (上传附件 _parse_uploaded_document 需要):
#   docx=python-docx, pptx=python-pptx, openpyxl=xlsx, pdfplumber+pdfminer+pypdfium2=pdf, PIL=Pillow
# collect_all 收齐 datas(如 pdfminer 的 cmap / PIL 字体) + binaries(pypdfium2 .so/.dll) + hiddenimports。
# pypdfium2_raw 必须走 collect_all: 它的原生 libpdfium.dylib/.so/.dll 是 binary,
# 只放 hiddenimports 不会被打进包 (verified: collect_all 才抓 libpdfium.dylib + version.json)。
for pkg in ["docx", "pptx", "openpyxl", "pdfplumber", "pdfminer", "PIL",
            "pypdfium2", "pypdfium2_raw"]:
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
    # WorkspaceManager imports this at module load. Keep it explicit because
    # PyInstaller's package scan has omitted it from macOS onefile builds.
    "app.coding.form_component_editor",
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
    # 文档解析二级隐藏依赖 (collect_all 主包不一定带全):
    #   PIL=Pillow 的导入名; XlsxWriter/et_xmlfile 是 openpyxl 的可选写/读依赖;
    #   typing_extensions 被多个解析库动态引用。
    # pypdfium2/pypdfium2_raw 已上移到 collect_all 循环 (需收原生 dylib), 不再在此重复。
    "PIL", "PIL._imaging",
    "et_xmlfile", "xlsxwriter",
    "typing_extensions",
]

# TLS 证书 (httpx)
datas += collect_data_files("certifi")

# 前端构建产物 -> _MEIPASS/frontend_dist (与 main.py 的桌面挂载约定一致)
if os.path.isdir(FRONTEND_DIST):
    datas += [(FRONTEND_DIST, "frontend_dist")]

# 后端运行期数据文件 (存在才加)
#   desktop/preset-skills: 随包预置 skill, 首启由 build_env._sync_preset_skills
#   覆盖式同步进 data_dir/skills/platform/ (冻结态资源在 _MEIPASS/desktop/preset-skills)
for src, dst in [("app/templates", "app/templates"),
                 ("templates", "templates"),
                 ("tool_registry.yaml", "."),
                 ("app/static", "app/static"),
                 ("desktop/preset-skills", "desktop/preset-skills")]:
    if os.path.exists(os.path.join(BACKEND, src)):
        datas += [(os.path.join(BACKEND, src), dst)]

# 不需要的重依赖: 排除以缩小体积、避开无法冻结的 playwright
# 注意: aiomysql/pymysql 不能排除 — quick_db.py 在模块顶层 import aiomysql
# 注意: 文档/PDF/表格解析依赖 (pdfplumber/pdfminer/pypdfium2/docx/pptx/openpyxl/PIL) 已不再排除 —
#       上传附件 _parse_uploaded_document 现在就会调用, 排除会导致桌面端 ImportError 静默吞错。
excludes = [
    "playwright", "kubernetes_asyncio", "kubernetes",
    "pytest", "pytest_asyncio", "watchfiles",
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
    name="dolphin-ai-sidecar",
    debug=False,
    strip=False,
    upx=False,
    console=(os.name != "nt"),
    onefile=True,
)
