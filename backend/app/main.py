import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings, APP_TITLE, APP_DESCRIPTION, APP_VERSION
from app.database import init_db
from app.routes import (
    ai_chat,
    apaas,
    application_members,
    applications,
    auth,
    browser,
    chat,
    coding,
    coding_v2,
    coding_v2_spec,
    conversations,
    generation_steps,
    git_connection,
    git_webhook,
    harness,
    help_assistant,
    incremental_update,
    llm_configs,
    marketplace,
    online_coding,
    online_coding_runtime,
    platform_envs,
    platform_proxy,
    preferences,
    projects,
    proposals,
    sandboxes,
    spec,
    sse,
    templates,
    vibe_coding_chat,
    voice,
    work_state,
)


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

    # 清理进程上次退出时悬挂的 coding session
    # （uvicorn --reload / 崩溃 / 部署重启留下的 status='running' 行）
    try:
        from app.startup_recovery import sweep_dead_coding_sessions
        await sweep_dead_coding_sessions()
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "startup recovery sweep failed (非致命): %s", e,
        )

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

    # Vibe Coding 沙箱容器空闲回收 — 周期性 stop 长时间无活跃的容器（保留容器，下次 start 复用）
    async def _vibe_reap_loop():
        from app.vibe_coding.docker_runtime import get_runtime as _get_rt
        import logging as _logging
        _log = _logging.getLogger("vibe_coding.reaper")
        while True:
            await _asyncio.sleep(300)  # 5 分钟扫一次
            try:
                rt = _get_rt()
                if not await rt.is_available():
                    continue
                stopped = await rt.reap_idle()
                if stopped:
                    _log.info("Reaped %d idle sandbox(es): %s", len(stopped), stopped)
            except Exception as exc:
                _log.warning("vibe reaper iteration failed: %s", exc)

    _asyncio.create_task(_vibe_reap_loop())

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
app.include_router(ai_chat.router, prefix="/api")
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
app.include_router(harness.router, prefix="/api")
app.include_router(spec.router, prefix="/api")
app.include_router(sse.router, prefix="/api")
app.include_router(coding_v2.router, prefix="/api")
app.include_router(coding_v2_spec.router, prefix="/api")
app.include_router(application_members.router, prefix="/api")
app.include_router(proposals.app_router, prefix="/api")
app.include_router(proposals.prop_router, prefix="/api")
app.include_router(git_connection.router, prefix="/api")
app.include_router(git_connection.app_router, prefix="/api")
app.include_router(git_webhook.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(work_state.router, prefix="/api")
app.include_router(online_coding.router, prefix="/api")
app.include_router(online_coding_runtime.router, prefix="/api")
app.include_router(vibe_coding_chat.router, prefix="/api")
app.include_router(help_assistant.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(sandboxes.router, prefix="/api")
# 平台代理路由注册在根路径（/platform/... 和 /backend/... 需要直接匹配）
app.include_router(platform_proxy.router)


# ─────────────────────── MCP Server ───────────────────────
# 把 ai-builder 应用领域能力封装为 MCP 工具暴露给得小帆等 agent 平台。
# 详见 backend/app/mcp_server.py
try:
    from app.mcp_server import mcp as _mcp_server, is_valid_api_key as _mcp_is_valid_api_key

    class _McpAuthMiddleware:
        """ASGI 中间件：校验 Authorization: Bearer <MCP_API_KEY>（或 ?api_key=xxx）。

        生产 nginx 反代 /ai-builder/api/* → :8003/api/*，要让 MCP advertise 的 message
        endpoint 包含 /ai-builder 前缀，靠 uvicorn 启动参数 --root-path=/ai-builder
        （ASGI 标准做法），这里中间件不动 scope。
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            auth = headers.get("authorization", "")
            api_key = ""
            if auth.lower().startswith("bearer "):
                api_key = auth[7:].strip()
            if not api_key:
                # fallback: query string
                qs = scope.get("query_string", b"").decode()
                for part in qs.split("&"):
                    if part.startswith("api_key="):
                        api_key = part[len("api_key="):]
                        break
            if not _mcp_is_valid_api_key(api_key):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error":"unauthorized: invalid or missing MCP API key"}',
                })
                return
            await self.app(scope, receive, send)

    # 不传 mount_path 给 sse_app —— starlette mount 会通过 ASGI scope.root_path
    # 自动给 client 拼上 /api/mcp 前缀。传了反而双前缀（/api/mcp/api/mcp/messages/）。
    _mcp_app = _mcp_server.sse_app()
    app.mount("/api/mcp", _McpAuthMiddleware(_mcp_app))
    import logging as _logging
    _logging.getLogger(__name__).info("MCP server mounted at /api/mcp/sse")
except Exception as exc:
    import logging as _logging
    _logging.getLogger(__name__).warning("MCP server 启用失败（不影响主应用）：%s", exc)


# 平台插件资源中间件：/{32位hex}/... → 代理到平台
import re as _re
_PLUGIN_HASH_RE = _re.compile(r'^/[0-9a-f]{32}/')

@app.middleware("http")
async def plugin_asset_middleware(request, call_next):
    if _PLUGIN_HASH_RE.match(request.url.path):
        from app.routes.platform_proxy import handle_plugin_asset_request
        return await handle_plugin_asset_request(request)
    return await call_next(request)


# SSE 防缓冲 middleware：所有 text/event-stream 响应自动注入 header，
# 避免 nginx / 反向代理缓冲导致前端看不到增量 + 中途断连报 "network error"。
# 对 EventSourceResponse 兜底（nginx 的 proxy_buffering off 失效时仍可生效）。
@app.middleware("http")
async def sse_no_buffering_middleware(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Cache-Control"] = "no-cache, no-transform"
    return response


# 静态文件（浏览器预览页面等）
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/api/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
