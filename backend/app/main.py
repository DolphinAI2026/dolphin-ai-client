import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings, APP_TITLE, APP_DESCRIPTION, APP_VERSION
from app.database import init_db
from app.routes import auth, conversations, chat, applications, apaas, generation_steps, coding, incremental_update, projects, marketplace, templates, platform_envs, platform_proxy, llm_configs, browser, requirements, harness, spec, sse, coding_v2


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时杀掉所有残留的 vibe-serve.js 进程（清理上次后端退出留下的孤儿进程）
    subprocess.run(["pkill", "-f", "vibe-serve.js"], capture_output=True)

    # 启动时初始化数据库
    await init_db()

    # 运行种子数据
    from app.seed_data import seed_initial_data
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)

    # 预热平台代理状态（避免首次请求 503）
    from app.routes.platform_proxy import _ensure_proxy_state
    try:
        await _ensure_proxy_state()
    except Exception:
        pass

    # 后台预热模板依赖缓存（不阻塞启动）
    import asyncio as _asyncio
    from app.coding.workspace import WorkspaceManager as _WM
    _asyncio.create_task(_WM().prewarm_template_deps())

    yield
    # 关闭时清理资源
    from app.coding.browser_service import BrowserService
    await BrowserService.get_instance().stop()


app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan
)

# CORS配置
cors_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
if settings.code_server_base_url:
    parsed = urlparse(settings.code_server_base_url)
    if parsed.scheme and parsed.netloc:
        ide_origin = f"{parsed.scheme}://{parsed.netloc}"
        if ide_origin not in cors_origins:
            cors_origins.append(ide_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(apaas.router, prefix="/api")
app.include_router(generation_steps.router, prefix="/api")
app.include_router(coding.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(marketplace.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(platform_envs.router, prefix="/api")
app.include_router(llm_configs.router, prefix="/api")
app.include_router(browser.router, prefix="/api")
app.include_router(requirements.router, prefix="/api")
app.include_router(harness.router, prefix="/api")
app.include_router(spec.router, prefix="/api")
app.include_router(sse.router, prefix="/api")
app.include_router(coding_v2.router, prefix="/api")
# 平台代理路由注册在根路径（/platform/... 和 /backend/... 需要直接匹配）
app.include_router(platform_proxy.router)


# 平台插件资源中间件：/{32位hex}/... → 代理到平台
import re as _re
_PLUGIN_HASH_RE = _re.compile(r'^/[0-9a-f]{32}/')

@app.middleware("http")
async def plugin_asset_middleware(request, call_next):
    if _PLUGIN_HASH_RE.match(request.url.path):
        from app.routes.platform_proxy import handle_plugin_asset_request
        return await handle_plugin_asset_request(request)
    return await call_next(request)


# 静态文件（浏览器预览页面等）
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/api/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
