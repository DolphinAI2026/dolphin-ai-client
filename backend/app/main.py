import subprocess
from contextlib import AsyncExitStack, asynccontextmanager
import json
import os
import time
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from app.config import settings, APP_TITLE, APP_DESCRIPTION, APP_VERSION
from app.database import init_db
from app.routes import (
    admin_mcp,
    agent_observability,
    agent_prompts,
    ai_chat,
    apaas,
    builder_mcp,
    application_members,
    applications,
    auth,
    browser,
    chat,
    coding,
    conversations,
    current_app,
    db_connections,
    desktop_auth,
    generation_steps,
    git_connection,
    harness,
    help_assistant,
    incremental_update,
    llm_configs,
    mcp_platform,
    mcp_hub,
    platform_envs,
    preferences,
    projects,
    requirements,
    runtime_proxy,
    skills as skills_routes,
    spec,
    sse,
    templates,
    tenant_logs,
    voice,
    work_state,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 安全门(deploy-readiness 阻断项): ENCRYPTION_KEY 不许用仓库里的默认值跑——
    # 否则所有 aPaaS 密码都用一把公开的 key 加密。本地开发/历史数据要继续用默认 key,
    # 必须显式 ALLOW_DEFAULT_ENCRYPTION_KEY=1 表态。
    _insecure_keys = {"", "default-key-change-in-production-32b", "__GENERATE__"}
    if settings.encryption_key in _insecure_keys and not settings.allow_default_encryption_key:
        raise RuntimeError(
            "ENCRYPTION_KEY 未配置或仍是仓库默认值, 拒绝启动。"
            "生产环境请设置随机密钥(如 openssl rand -base64 32);"
            "本地开发要沿用默认 key(历史数据已用它加密)请设 ALLOW_DEFAULT_ENCRYPTION_KEY=1。"
        )

    # 信任边界铁律: 非桌面 sidecar 的部署 = 共享后端, 绝不接受本地签票。
    if os.environ.get("DESKTOP_MODE") != "1":
        from app.auth import assert_shared_backend_issuer_safety
        assert_shared_backend_issuer_safety()

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

    # 把孤儿 workspace（无会话指向）补建 owner 会话，保证 workspace ↔ 会话 1:1
    try:
        from app.coding.migrate_orphan_workspaces import migrate_orphan_workspaces
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as _mig_db:
            await migrate_orphan_workspaces(_mig_db)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "migrate_orphan_workspaces failed (非致命): %s", e,
        )

    # 桌面 external 工作区: 启动从 DB 注册表恢复路径缓存
    try:
        from app.database import AsyncSessionLocal
        from app.coding.workspace import restore_external_workspaces
        async with AsyncSessionLocal() as _ws_sess:
            await restore_external_workspaces(_ws_sess)
    except Exception as _e:
        import logging as _lg
        _lg.getLogger(__name__).warning("restore_external_workspaces 失败(非致命): %s", _e)

    # 后台预热模板依赖缓存（不阻塞启动）
    import asyncio as _asyncio
    from app.coding.workspace import WorkspaceManager as _WM
    _asyncio.create_task(_WM().prewarm_template_deps())

    async with AsyncExitStack() as mcp_stack:
        for mcp_obj in (globals().get("_main_mcp"), globals().get("_support_triage_mcp")):
            if mcp_obj is not None:
                await mcp_stack.enter_async_context(mcp_obj.session_manager.run())

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
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api")
app.include_router(desktop_auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(ai_chat.router, prefix="/api")
app.include_router(skills_routes.router, prefix="/api")
app.include_router(agent_observability.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(apaas.router, prefix="/api")
app.include_router(generation_steps.router, prefix="/api")
app.include_router(coding.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(platform_envs.router, prefix="/api")
app.include_router(db_connections.router, prefix="/api")
app.include_router(llm_configs.router, prefix="/api")
app.include_router(browser.router, prefix="/api")
app.include_router(harness.router, prefix="/api")
app.include_router(spec.router, prefix="/api")
app.include_router(sse.router, prefix="/api")
app.include_router(application_members.router, prefix="/api")
app.include_router(git_connection.router, prefix="/api")
app.include_router(git_connection.app_router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(work_state.router, prefix="/api")
app.include_router(help_assistant.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(requirements.router, prefix="/api")
app.include_router(tenant_logs.router, prefix="/api")
app.include_router(current_app.router, prefix="/api")
app.include_router(admin_mcp.router, prefix="/api")
app.include_router(mcp_platform.router, prefix="/api")
app.include_router(builder_mcp.router, prefix="/api")
app.include_router(mcp_hub.router)
# 自开发整页预览的运行态反向代理 (/app + /apaas, 根级无前缀) —— 复活自 e361c7bc
# 误删的 platform_proxy 运行态部分。详见 app/routes/runtime_proxy.py 顶注。
app.include_router(runtime_proxy.router)


class _McpBearerAuthAsgiMiddleware:
    """Protect the embedded Streamable HTTP MCP endpoint with MCP_API_KEYS.

    External MCP gateways are not consistent about auth header names. Standard
    clients use `Authorization: Bearer <key>`, while the Dolphin gateway sends
    `X-API-Key` / `X-AI-GW-KEY`. Accept all three against the same
    MCP_API_KEYS list.
    """

    def __init__(self, app, service: str | None = None):
        self.app = app
        self.service = service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from app.mcp_keys import get_mcp_api_keys

        keys = set(await get_mcp_api_keys())
        if not keys:
            await self._send_json(send, 503, b'{"detail":"MCP key not configured"}')
            return
        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers") or []
        }
        token = self._extract_token(headers)
        if token not in keys:
            await self._send_json(send, 401, b'{"detail":"Invalid MCP bearer token"}')
            return

        scope = self._scope_with_mcp_accept(scope)
        started = time.perf_counter()
        body = await self._read_body(receive)
        if not body.strip() and scope.get("method") == "POST":
            body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        method = self._mcp_method(body)
        status_code = 200
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send_with_status(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 200)
            await send(message)

        try:
            await self.app(scope, replay_receive, send_with_status)
        finally:
            if method == "tools/list":
                self._append_mcp_log(
                    scope=scope,
                    method=method,
                    status_code=status_code,
                    success=200 <= status_code < 400,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )

    def _extract_token(self, headers: dict[str, str]) -> str:
        auth = (headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if auth and " " not in auth:
            return auth
        for name in ("x-api-key", "x-ai-gw-key", "x-mcp-api-key"):
            value = (headers.get(name) or "").strip()
            if value:
                return value[7:].strip() if value.lower().startswith("bearer ") else value
        return ""

    def _scope_with_mcp_accept(self, scope) -> dict:
        headers = [
            (key, value)
            for key, value in (scope.get("headers") or [])
            if key.lower() != b"accept"
        ]
        headers.append((b"accept", b"application/json, text/event-stream"))
        updated = dict(scope)
        updated["headers"] = headers
        return updated

    async def _send_json(self, send, status: int, body: bytes):
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})

    async def _read_body(self, receive) -> bytes:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                break
            chunks.append(message.get("body") or b"")
            if not message.get("more_body"):
                break
        return b"".join(chunks)

    def _mcp_method(self, body: bytes) -> str | None:
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            return None
        if isinstance(data, dict):
            return data.get("method")
        return None

    def _append_mcp_log(
        self,
        *,
        scope,
        method: str,
        status_code: int,
        success: bool,
        elapsed_ms: int,
    ) -> None:
        try:
            from app.routes.mcp_platform import append_mcp_call_log
            append_mcp_call_log({
                "service": self.service,
                "path": scope.get("path"),
                "rpc_method": method,
                "tool": None,
                "request_arguments": {},
                "request_headers": {"authorization": "Bearer <MCP_API_KEYS>"},
                "status_code": status_code,
                "success": success,
                "error": None if success else f"HTTP {status_code}",
                "auth_source": "mcp_api_key",
                "elapsed_ms": elapsed_ms,
            })
        except Exception:
            pass


# Embedded MCP endpoint for Dolphin / external agents:
# mount path + FastMCP default path => /api/mcp/mcp
from app.mcp_server import mcp as _main_mcp  # noqa: E402
app.mount(
    "/api/mcp",
    _McpBearerAuthAsgiMiddleware(_main_mcp.streamable_http_app()),
    name="main-mcp",
)
from app.support_triage_mcp import mcp as _support_triage_mcp  # noqa: E402
app.mount(
    "/api/support-triage-mcp",
    _McpBearerAuthAsgiMiddleware(_support_triage_mcp.streamable_http_app(), service="support-triage"),
    name="support-triage-mcp",
)
app.include_router(agent_prompts.router, prefix="/api")
# SSE 防缓冲 middleware：text/event-stream 响应自动注入 X-Accel-Buffering: no
#
# 注意：原本用 @app.middleware("http")（即 BaseHTTPMiddleware）实现，但
# BaseHTTPMiddleware 的 call_next buffering 跟流式 SSE 不兼容，会切断 MCP
# 服务器的 message 流（外部 agent 拿不到 tools/list 响应）。
# 改成纯 ASGI middleware 后，对所有 mount 都安全透传。


class _SseNoBufferingAsgiMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def _wrapped_send(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                content_type = b""
                for k, v in headers:
                    if k.lower() == b"content-type":
                        content_type = v
                        break
                if content_type.startswith(b"text/event-stream"):
                    headers = [(k, v) for k, v in headers if k.lower() not in (b"x-accel-buffering", b"cache-control")]
                    headers.append((b"x-accel-buffering", b"no"))
                    headers.append((b"cache-control", b"no-cache, no-transform"))
                    message = dict(message)
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, _wrapped_send)


app.add_middleware(_SseNoBufferingAsgiMiddleware)


class _SpaStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


# 平台管理前端静态资源。开发时由 frontend:5173 代理 /admin 到这里，
# 因此本地只需要 5173 + 8000 + 8004 三个端口。
_admin_spa_dir = Path(__file__).resolve().parents[2] / "admin-spa" / "dist"
if _admin_spa_dir.is_dir():
    @app.get("/platform-admin", include_in_schema=False)
    async def platform_admin_index():
        return FileResponse(_admin_spa_dir / "index.html")

    @app.get("/ai-builder/admin", include_in_schema=False)
    async def prefixed_admin_index():
        return FileResponse(_admin_spa_dir / "index.html")

    @app.get("/ai-builder/platform-admin", include_in_schema=False)
    async def prefixed_platform_admin_index():
        return FileResponse(_admin_spa_dir / "index.html")

    app.mount("/admin", _SpaStaticFiles(directory=str(_admin_spa_dir), html=True), name="admin-spa")
    # 线上入口 /ai-builder/platform-admin 由主前端接管；若外层 nginx/Ingress
    # 暂时把该路径转到后端，也返回管理台 SPA，避免直接暴露 FastAPI 404。
    app.mount("/platform-admin", _SpaStaticFiles(directory=str(_admin_spa_dir), html=True), name="platform-admin-spa")
    app.mount("/ai-builder/admin", _SpaStaticFiles(directory=str(_admin_spa_dir), html=True), name="prefixed-admin-spa")


# 静态文件（浏览器预览页面等）
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/api/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# ── 桌面 sidecar: DESKTOP_MODE 下同源托管桌面前端构建产物 ──────────────
# 在线版不受影响(默认 DESKTOP_MODE 未设)。必须放在所有 include_router /
# app.mount / runtime_proxy 之后, 让显式 API/admin/反代路由优先匹配,
# 这个 "/" 挂载只作为前端 SPA 的兜底。
if os.environ.get("DESKTOP_MODE") == "1":
    import logging as _logging
    import sys as _sys

    _desktop_logger = _logging.getLogger(__name__)

    _explicit = os.environ.get("DESKTOP_FRONTEND_DIR")
    if _explicit:
        _desktop_fe = Path(_explicit)
    elif getattr(_sys, "_MEIPASS", None):  # PyInstaller 冻结态
        _desktop_fe = Path(_sys._MEIPASS) / "frontend_dist"
    else:  # 本机 dev
        _desktop_fe = Path(__file__).resolve().parents[2] / "frontend" / "dist-desktop"

    if _desktop_fe.is_dir():
        app.mount("/", _SpaStaticFiles(directory=str(_desktop_fe), html=True), name="desktop-frontend")
        _desktop_logger.info("[desktop] mounted frontend SPA at / from %s", _desktop_fe)
    else:
        _desktop_logger.warning("[desktop] DESKTOP_MODE=1 but frontend dir not found: %s", _desktop_fe)
