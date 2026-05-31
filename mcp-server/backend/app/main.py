import subprocess
import json
import base64
import os
import time
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings, APP_TITLE, APP_DESCRIPTION, APP_VERSION
from app.database import init_db
from app.routes import (
    admin_mcp,
    agent_prompts,
    agents_config,
    ai_chat,
    apaas,
    app_adjust_chat,
    application_members,
    applications,
    auth,
    browser,
    chat,
    builder_mcp,
    coding_v2,
    coding_v2_spec,
    conversations,
    coding,
    current_app,
    db_connections,
    design_drafts,
    dolphin_sso,
    generation_steps,
    git_connection,
    git_webhook,
    harness,
    help_assistant,
    incremental_update,
    industry,
    llm_configs,
    marketplace,
    mcp_hub,
    mcp_platform,
    online_coding,
    online_coding_runtime,
    platform_envs,
    platform_proxy,
    preferences,
    projects,
    proposals,
    quick_db,
    requirements,
    runtime_v2,
    sandboxes,
    spec,
    specs_v2,
    sse,
    tenant_dolphin_agents,
    templates,
    vibe_coding_chat,
    voice,
    work_state,
)


async def _ensure_sqlite_shared_schema_compat() -> None:
    """Add MCP-only tenant columns when the standalone MCP shares the main SQLite DB.

    SQLAlchemy create_all does not alter existing tables. The main AI Builder DB can
    therefore predate the Dolphin binding columns used by the standalone MCP routes.
    Keep this additive and SQLite-only so production migrations remain explicit.
    """
    from sqlalchemy import text
    from app.database import engine

    if engine.url.get_backend_name() != "sqlite":
        return

    columns = {
        "dolphin_tenant_code": "VARCHAR(80)",
        "dolphin_tenant_id_str": "VARCHAR(80)",
        "dolphin_agent_code": "VARCHAR(40)",
        "dolphin_copilot_agent_code": "VARCHAR(40)",
        "dolphin_coding_agent_code": "VARCHAR(40)",
        "dolphin_app_adjust_agent_code": "VARCHAR(40)",
        "dolphin_requirements_agent_code": "VARCHAR(40)",
        "dolphin_customer_name": "VARCHAR(128)",
        "dolphin_server_url": "VARCHAR(255)",
    }
    async with engine.begin() as conn:
        rows = await conn.execute(text("PRAGMA table_info(tenants)"))
        existing = {str(row[1]) for row in rows}
        for name, ddl in columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE tenants ADD COLUMN {name} {ddl}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动 MCP server 的 session manager — Streamable HTTP transport 在 mount 模式下
    # 父 app lifespan 不会自动透传到子 ASGI，需要手动运行 session_manager。
    # 用 AsyncExitStack 跟主 lifespan 生命周期对齐。
    from contextlib import AsyncExitStack
    _exit_stack = AsyncExitStack()
    try:
        from app.mcp_server import mcp as _mcp_for_lifespan
        await _exit_stack.enter_async_context(_mcp_for_lifespan.session_manager.run())
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("MCP session manager 启动失败：%s", _exc)

    # 启动时杀掉所有残留的 vibe-serve.js 进程（清理上次后端退出留下的孤儿进程）
    subprocess.run(["pkill", "-f", "vibe-serve.js"], capture_output=True)

    # 启动时初始化数据库
    await init_db()
    await _ensure_sqlite_shared_schema_compat()

    # 运行种子数据
    from app.seed_data import seed_initial_data
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)

    # /industry + /marketplace demo data — idempotent，已 seeded 即 no-op
    try:
        from app.services.industry_seed import seed_industry_packs
        from app.services.marketplace_seed import seed_marketplace_components
        async with AsyncSessionLocal() as session:
            await seed_industry_packs(session)
            await seed_marketplace_components(session)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "industry/marketplace demo seed 启动失败 (非致命): %s", _exc,
        )

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

    # 2026-05-11 启动健康检查：tenants 必须配齐 1:1:1（apaas_env_id + dolphin_customer_name
    # + 至少一个 agent code），否则 WARN（不 fatal，让 admin 进平台管理后台补全）
    try:
        from sqlalchemy import select as _select
        from app.models import Tenant as _Tenant
        async with AsyncSessionLocal() as _hc_db:
            _tenants = (await _hc_db.execute(_select(_Tenant))).scalars().all()
        import logging as _logging
        _hc_log = _logging.getLogger("tenant_health_check")
        for _t in _tenants:
            _missing = []
            if not _t.apaas_env_id:
                _missing.append("apaas_env_id")
            if not _t.dolphin_customer_name:
                _missing.append("dolphin_customer_name")
            if not (_t.dolphin_copilot_agent_code or _t.dolphin_agent_code):
                _missing.append("dolphin_(copilot|default)_agent_code")
            if _missing:
                _hc_log.warning(
                    "[tenant 1:1:1 健康检查] tenant id=%s code=%s name=%s 缺配置: %s — "
                    "用户登录后 /dolphin/config 会 fail-fast，请进 /admin/tenants 补全",
                    _t.id, _t.tenant_code, _t.tenant_name, ", ".join(_missing),
                )
            else:
                _hc_log.info(
                    "[tenant 1:1:1 健康检查] tenant id=%s code=%s OK (apaas_env=%s, customer=%s)",
                    _t.id, _t.tenant_code, _t.apaas_env_id, _t.dolphin_customer_name,
                )
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("tenant health check failed (非致命): %s", _exc)

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
    await _exit_stack.aclose()


app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan
)


# CORS配置
cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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

# 注册路由（Phase 2 砍后：14 个 router，参见 docs/refactor-mcp-server/01-route-cull-plan.md）
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(ai_chat.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(apaas.router, prefix="/api")
app.include_router(generation_steps.router, prefix="/api")
app.include_router(incremental_update.router, prefix="/api")
app.include_router(coding.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(marketplace.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(platform_envs.router, prefix="/api")
app.include_router(quick_db.router, prefix="/api")
app.include_router(db_connections.router, prefix="/api")
app.include_router(llm_configs.router, prefix="/api")
app.include_router(browser.router, prefix="/api")
app.include_router(mcp_platform.router, prefix="/api")
app.include_router(admin_mcp.router, prefix="/api")
app.include_router(builder_mcp.router, prefix="/api")
app.include_router(mcp_hub.router)
app.include_router(harness.router, prefix="/api")
app.include_router(spec.router, prefix="/api")
app.include_router(specs_v2.router, prefix="/api")
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
app.include_router(dolphin_sso.router, prefix="/api")
app.include_router(requirements.router, prefix="/api")
app.include_router(app_adjust_chat.router, prefix="/api")
app.include_router(tenant_dolphin_agents.router, prefix="/api")
app.include_router(current_app.router, prefix="/api")
app.include_router(design_drafts.router, prefix="/api")
app.include_router(agents_config.router, prefix="/api")
app.include_router(industry.router, prefix="/api")
app.include_router(runtime_v2.router, prefix="/api")
app.include_router(agent_prompts.router, prefix="/api")
# 2026-05-19 Chrome extension WebSocket bridge — image #50 follow-up POC
from app.routes import browser_ext_ws  # noqa: E402
app.include_router(browser_ext_ws.router)
# HTML 预览也挂 /api 前缀，和 API 路由保持同一入口。
app.include_router(design_drafts.html_router, prefix="/api")
# 平台代理路由注册在根路径（/platform/... 和 /backend/... 需要直接匹配）
app.include_router(platform_proxy.router)


# ─────────────────────── MCP Server ───────────────────────
# 把 ai-builder 应用领域能力封装为 MCP 工具暴露给得小帆等 agent 平台。
# 详见 backend/app/mcp_server.py
try:
    from app.mcp_server import mcp as _mcp_server, is_valid_api_key as _mcp_is_valid_api_key

    class _McpAuthMiddleware:
        """ASGI 中间件：MCP 入口鉴权 + 请求级身份装填。

        三条入口路径（优先级从高到低）：
        1) Authorization: Bearer <ai-builder JWT>
           → 解 JWT 验签 + 装 McpRequestCtx 到 ContextVar，工具直接拿 ctx 不再
             依赖 caller-trusted user_id 参数。无需另传 MCP_API_KEY。
        2) Authorization: Bearer <MCP_API_KEY> + X-AiBuilder-Token: <ai-builder JWT>
           → 平台凭证 + 用户 JWT 双轨，向后兼容老 dolphin 接入方式同时支持新身份。
        3) Authorization: Bearer <MCP_API_KEY>（或 ?api_key=…）
           → 老平台凭证模式，工具内 _resolve_identity 走 caller user_id 参数 +
             alias cache + DB 反查兜底（带 deprecation log）。

        生产 nginx 反代 /ai-builder/api/* → 后端 /api/*，要让 MCP advertise 的 message
        endpoint 包含 /ai-builder 前缀，靠 uvicorn 启动参数 --root-path=/ai-builder
        （ASGI 标准做法），这里中间件不动 scope。
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            # 防御性 BaseExceptionGroup 展开（2026-05-13 加，二级 bug 修）：
            # mcp SDK 内 anyio task group 抛 ClosedResourceError 多数情况自己消化在
            # streamable_http.py:879 message_router 内部，不冒到这里；但万一未来 SDK
            # 升级或我们工具自己用 anyio task group，让 sub-exception 不被 group 的
            # default __str__（"unhandled errors in a TaskGroup (N sub-exception)"）
            # 吞掉真凶。
            try:
                await self._dispatch(scope, receive, send)
                return
            except BaseExceptionGroup as eg:  # noqa: F821  py3.11+
                logger.error(
                    "_McpAuthMiddleware caught BaseExceptionGroup: %d sub-exception(s) path=%s",
                    len(eg.exceptions), scope.get("path", "?"),
                )
                for idx, sub in enumerate(eg.exceptions):
                    logger.error(
                        "  sub[%d/%d] %r", idx + 1, len(eg.exceptions), sub,
                        exc_info=(type(sub), sub, sub.__traceback__),
                    )
                raise

        async def _dispatch(self, scope, receive, send):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            auth = headers.get("authorization", "")
            x_aib_token = headers.get("x-aibuilder-token", "").strip()
            x_apaas_token = headers.get("x-apaas-token", "").strip()
            x_apaas_tenant_id = headers.get("x-apaas-tenant-id", "").strip()
            # 🆕 2026-05-10 Phase 6：dolphin omnigate 透传的 3 个 Header（实测证据）：
            #   - X-AI-GW-KEY  : MCP 网关共享 key（auth_config.token）
            #   - user-token   : 当前用户的 dolphin access token JWT
            #   - tanant_id    : dolphin 租户 ID（注意 dolphin 这边拼错了 tenant→tanant）
            # 见 https://dolphin-trial.definesys.cn/mcp/48 → "请求参数" Header 表
            # 🆕 2026-05-10 Phase 6 future-proof：当 dolphin 团队启用 auth_mapping_enabled
            # 后会透传 user-token + tanant_id（实测当前是 false，omnigate 只发 Authorization
            # Bearer <平台 token> + X-Forwarded-* + User-Agent: Go-http-client；admin /mcp/48
            # 详情页上写的 3 个必填 header 仅用于 SDK 客户端模式，不在 chat 转发路径里）。
            # 注：dolphin 自己拼写错 tanant_id（少 e），透传时按这个；同时 fallback tenant_id 兼容。
            user_token = headers.get("user-token", "").strip()
            dolphin_tenant_id = (headers.get("tanant_id") or headers.get("tenant_id") or "").strip()
            x_ai_gw_key = headers.get("x-ai-gw-key", "").strip()

            bearer = ""
            if auth.lower().startswith("bearer "):
                bearer = auth[7:].strip()

            from app.mcp_request_ctx import set_mcp_ctx, reset_mcp_ctx

            # ① 试解 Authorization: Bearer 是不是 ai-builder JWT
            #    JWT 三段 base64url，通过先快速匹配；解失败则 fallback 当作 API key
            req_ctx = None
            if bearer and bearer.count(".") == 2:
                req_ctx = await _try_resolve_aibuilder_jwt(bearer)
                if req_ctx:
                    # JWT 模式：直接装 ctx 透传，不再校验 MCP_API_KEY
                    body, replay_receive = await self._read_and_replay(receive)
                    token = set_mcp_ctx(req_ctx)
                    try:
                        await self._call_app_with_log(scope, replay_receive, send, body, req_ctx, api_key_source="ai_builder_jwt")
                    finally:
                        reset_mcp_ctx(token)
                    return

            # ② Authorization 不是 JWT → 当作 MCP_API_KEY；同时尝试 X-AiBuilder-Token
            #    或 dolphin 透传的 user-token + tanant_id（X-AI-GW-KEY 也接受作为平台凭证）
            api_key = bearer or x_ai_gw_key
            if not api_key:
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

            # ③ MCP_API_KEY/X-AI-GW-KEY 通过 → 尝试用户身份解析（按优先级降级）
            #   3a) X-APaaS-Token + X-APaaS-Tenant-Id: aPaaS 原生用户身份。
            #       这是新 MCP 工具链的首选路径：只装 aPaaS token/tenant，不伪造
            #       ai-builder 本地用户/租户作为业务身份。
            #   3b) X-AiBuilder-Token: 是 ai-builder JWT，直接解
            #   3c) user-token: dolphin 用户 access token，sub = dolphin user_id；
            #       通过 dolphin_sso_v2 cache 反查，或落到 username 反查 ai-builder User
            if x_apaas_token and x_apaas_tenant_id:
                from app.mcp_request_ctx import McpRequestCtx
                req_ctx = McpRequestCtx(
                    local_user_id=0,
                    local_tenant_id=0,
                    apaas_token=x_apaas_token,
                    apaas_tenant_id=x_apaas_tenant_id,
                    auth_source="apaas_user_token",
                )
            if not req_ctx and x_aib_token:
                req_ctx = await _try_resolve_aibuilder_jwt(x_aib_token)
            if not req_ctx and user_token:
                req_ctx = await _try_resolve_dolphin_user_token(user_token, dolphin_tenant_id)

            if req_ctx:
                body, replay_receive = await self._read_and_replay(receive)
                token = set_mcp_ctx(req_ctx)
                try:
                    await self._call_app_with_log(scope, replay_receive, send, body, req_ctx, api_key_source="mcp_api_key")
                finally:
                    reset_mcp_ctx(token)
            else:
                body, replay_receive = await self._read_and_replay(receive)
                if self._is_identity_optional_request(body):
                    await self._call_app_with_log(scope, replay_receive, send, body, None, api_key_source="mcp_api_key")
                    return
                self._append_call_log(
                    scope,
                    body,
                    status=401,
                    response_body=(
                        '{"error":"unauthorized: missing end-user identity; '
                        'provide Authorization: Bearer <ai-builder JWT>, '
                        'X-AiBuilder-Token, X-APaaS-Token / X-APaaS-Tenant-Id, '
                        'or dolphin user-token/tanant_id headers"}'
                    ),
                    req_ctx=None,
                    api_key_source="mcp_api_key",
                )
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")],
                })
                await send({
                    "type": "http.response.body",
                    "body": (
                        b'{"error":"unauthorized: missing end-user identity; '
                        b'provide Authorization: Bearer <ai-builder JWT>, '
                        b'X-AiBuilder-Token, X-APaaS-Token / X-APaaS-Tenant-Id, '
                        b'or dolphin user-token/tanant_id headers"}'
                    ),
                })

        async def _read_and_replay(self, receive):
            messages = []
            body = b""
            while True:
                message = await receive()
                messages.append(message)
                if message.get("type") == "http.request":
                    body += message.get("body", b"") or b""
                    if not message.get("more_body", False):
                        break
                else:
                    break

            async def _replay():
                if messages:
                    return messages.pop(0)
                return {"type": "http.request", "body": b"", "more_body": False}

            return body, _replay

        def _is_identity_optional_request(self, body: bytes) -> bool:
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                return False
            optional_methods = {
                "initialize",
                "notifications/initialized",
                "ping",
                "prompts/list",
                "resources/list",
                "tools/list",
            }
            if isinstance(payload, list):
                return all(isinstance(item, dict) and item.get("method") in optional_methods for item in payload)
            return isinstance(payload, dict) and payload.get("method") in optional_methods

        async def _call_app_with_log(self, scope, receive, send, body: bytes, req_ctx, api_key_source: str):
            import time as _time
            started = _time.perf_counter()
            status = 500
            chunks: list[bytes] = []

            async def _send(message):
                nonlocal status
                if message.get("type") == "http.response.start":
                    status = int(message.get("status") or 0)
                elif message.get("type") == "http.response.body":
                    part = message.get("body", b"") or b""
                    if part and sum(len(x) for x in chunks) < 4000:
                        chunks.append(part[:4000])
                await send(message)

            try:
                await self.app(scope, receive, _send)
            finally:
                elapsed_ms = int((_time.perf_counter() - started) * 1000)
                response_text = b"".join(chunks).decode("utf-8", errors="replace")
                self._append_call_log(
                    scope,
                    body,
                    status=status,
                    response_body=response_text,
                    req_ctx=req_ctx,
                    api_key_source=api_key_source,
                    elapsed_ms=elapsed_ms,
                )

        def _redact_for_log(self, value, *, depth: int = 0):
            if depth > 6:
                return "<max-depth>"
            if isinstance(value, dict):
                out = {}
                for key, item in value.items():
                    k = str(key)
                    kl = k.lower()
                    if any(s in kl for s in ("token", "key", "secret", "password", "authorization")):
                        if isinstance(item, str) and item:
                            out[k] = f"{item[:6]}...{item[-4:]}" if len(item) > 14 else "***"
                        else:
                            out[k] = "***" if item is not None else None
                    elif k in ("md_content", "new_md", "content") and isinstance(item, str):
                        out[k] = {
                            "type": "text",
                            "length": len(item),
                            "preview": item[:240],
                        }
                    else:
                        out[k] = self._redact_for_log(item, depth=depth + 1)
                return out
            if isinstance(value, list):
                if len(value) > 20:
                    return [self._redact_for_log(x, depth=depth + 1) for x in value[:20]] + [f"<{len(value) - 20} more>"]
                return [self._redact_for_log(x, depth=depth + 1) for x in value]
            if isinstance(value, str) and len(value) > 1000:
                return {"type": "text", "length": len(value), "preview": value[:240]}
            return value

        def _mcp_header_info(self, scope) -> dict:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

            def fp(name: str) -> str | None:
                value = (headers.get(name) or "").strip()
                if not value:
                    return None
                if name == "authorization" and value.lower().startswith("bearer "):
                    value = value[7:].strip()
                return f"{value[:6]}...{value[-4:]}" if len(value) > 14 else "***"

            def jwt_summary(value: str | None) -> dict | None:
                value = (value or "").strip()
                if not value or value.count(".") != 2:
                    return None
                try:
                    payload = value.split(".")[1]
                    payload += "=" * (-len(payload) % 4)
                    data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
                    if not isinstance(data, dict):
                        return {"jwt_parse": "failed"}
                    exp = data.get("exp")
                    subject = (
                        data.get("account")
                        or data.get("username")
                        or data.get("userName")
                        or data.get("name")
                        or data.get("xdapuserid")
                        or data.get("sub")
                    )
                    summary = {
                        "jwt_parse": "ok",
                        "subject": str(subject) if subject is not None else None,
                        "xdapuserid": str(data.get("xdapuserid")) if data.get("xdapuserid") is not None else None,
                        "sub": str(data.get("sub")) if data.get("sub") is not None else None,
                        "exp": exp,
                        "expired": bool(exp and int(exp) < int(time.time())),
                    }
                    if exp:
                        summary["exp_at"] = datetime.fromtimestamp(int(exp)).isoformat(timespec="seconds")
                    return summary
                except Exception:
                    return {"jwt_parse": "failed"}

            return {
                "authorization": bool(headers.get("authorization")),
                "authorization_fingerprint": fp("authorization"),
                "x_ai_gw_key": bool(headers.get("x-ai-gw-key")),
                "x_ai_gw_key_fingerprint": fp("x-ai-gw-key"),
                "x_apaas_token": bool(headers.get("x-apaas-token")),
                "x_apaas_token_fingerprint": fp("x-apaas-token"),
                "x_apaas_token_claims": jwt_summary(headers.get("x-apaas-token")),
                "x_apaas_tenant_id": headers.get("x-apaas-tenant-id") or None,
                "x_aibuilder_token": bool(headers.get("x-aibuilder-token")),
                "user_token": bool(headers.get("user-token")),
                "dolphin_tenant_id": headers.get("tanant_id") or headers.get("tenant_id") or None,
            }

        def _mcp_request_info(self, body: bytes) -> dict:
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                return {"rpc_method": "", "tool": "", "request_params": None, "request_arguments": None}
            item = payload[0] if isinstance(payload, list) and payload else payload
            if not isinstance(item, dict):
                return {"rpc_method": "", "tool": "", "request_params": None, "request_arguments": None}
            method = str(item.get("method") or "")
            tool = ""
            params = item.get("params")
            arguments = None
            if method == "tools/call" and isinstance(params, dict):
                tool = str(params.get("name") or "")
                arguments = params.get("arguments")
            return {
                "rpc_method": method,
                "tool": tool,
                "request_params": self._redact_for_log(params),
                "request_arguments": self._redact_for_log(arguments),
            }

        def _append_call_log(
            self,
            scope,
            body: bytes,
            *,
            status: int,
            response_body: str,
            req_ctx,
            api_key_source: str,
            elapsed_ms: int = 0,
        ) -> None:
            try:
                from app.routes.mcp_platform import append_mcp_call_log
                info = self._mcp_request_info(body)
                path = scope.get("path") or ""
                success, error_text = self._mcp_response_outcome(status, response_body)
                append_mcp_call_log({
                    "service": path.split("/mcp", 1)[0] + "/mcp" if "/mcp" in path else path,
                    "path": path,
                    "rpc_method": info["rpc_method"],
                    "tool": info["tool"],
                    "request_params": info.get("request_params"),
                    "request_arguments": info.get("request_arguments"),
                    "request_headers": self._mcp_header_info(scope),
                    "status_code": status,
                    "success": success,
                    "error": error_text,
                    "auth_source": getattr(req_ctx, "auth_source", "") if req_ctx else api_key_source,
                    "apaas_tenant_id": getattr(req_ctx, "apaas_tenant_id", None) if req_ctx else None,
                    "apaas_user_id": getattr(req_ctx, "apaas_user_id", None) if req_ctx else None,
                    "local_user_id": getattr(req_ctx, "local_user_id", 0) if req_ctx else 0,
                    "local_tenant_id": getattr(req_ctx, "local_tenant_id", 0) if req_ctx else 0,
                    "elapsed_ms": elapsed_ms,
                })
            except Exception:
                pass

        def _mcp_response_outcome(self, status: int, response_body: str) -> tuple[bool, str]:
            if int(status or 0) >= 400:
                return False, (response_body or "")[:500]
            try:
                payload = json.loads(response_body or "{}")
                result = payload.get("result") if isinstance(payload, dict) else None
                if isinstance(result, dict) and result.get("isError") is True:
                    return False, json.dumps(result, ensure_ascii=False)[:500]
                content = result.get("content") if isinstance(result, dict) else None
                if isinstance(content, list) and content:
                    text = content[0].get("text") if isinstance(content[0], dict) else None
                    if isinstance(text, str):
                        try:
                            tool_payload = json.loads(text)
                        except Exception:
                            tool_payload = None
                        if isinstance(tool_payload, dict) and tool_payload.get("ok") is False:
                            return False, str(tool_payload.get("message") or tool_payload)[:500]
            except Exception:
                pass
            return True, ""


    async def _try_resolve_aibuilder_jwt(jwt_str: str):
        """JWT → McpRequestCtx，None 表示 JWT 无效（不应抛异常打断中间件）。"""
        try:
            from app.auth import decode_token
            from app.database import AsyncSessionLocal
            from app.models import User
            from sqlalchemy import select as _select
            from app.mcp_request_ctx import McpRequestCtx

            payload = decode_token(jwt_str)
            sub = payload.get("sub")
            if sub is None:
                return None
            local_uid = int(sub)
            local_tid = int(payload.get("tid") or 0)
            apaas_sub = payload.get("apaas_sub")
            apaas_tid = payload.get("apaas_tid")
            username = payload.get("username")

            # JWT 没 apaas claim 时回退查 user 行（老 JWT 兼容）
            if not apaas_sub or not apaas_tid:
                async with AsyncSessionLocal() as db:
                    u = (await db.execute(
                        _select(User).where(User.id == local_uid)
                    )).scalar_one_or_none()
                    if u and u.is_active:
                        if not apaas_sub:
                            apaas_sub = u.apaas_user_id
                        if not apaas_tid:
                            apaas_tid = u.apaas_tenant_id
                        if not username:
                            username = u.username
                    elif not u:
                        return None
            return McpRequestCtx(
                local_user_id=local_uid,
                local_tenant_id=local_tid,
                apaas_user_id=str(apaas_sub) if apaas_sub else None,
                apaas_tenant_id=str(apaas_tid) if apaas_tid else None,
                username=username,
                auth_source="ai_builder_jwt",
            )
        except Exception:
            return None


    async def _try_resolve_dolphin_user_token(user_token: str, dolphin_tenant_id: str = ""):
        """dolphin omnigate 透传的 user-token header → 反查 ai-builder 本地 user。

        user-token 是 dolphin 当前用户的 access token JWT (HS512)，载荷形如：
          {"type":"access","sub":"<dolphin_user_id>","iat":..,"exp":..}

        反查路径（优先级递降）：
          a) dolphin_sso_v2._TOKEN_CACHE 反查（_TOKEN_CACHE 是 user_id → token，
             但我们要 token → user_id。线性扫，cache 大小 = 活跃 ai-builder 用户数）
          b) 解 JWT.sub 调 dolphin /api/auth/me 拿 username，按 username 反查 User
          c) 都 miss → None，让中间件落到老路径兜底

        见 https://dolphin-trial.definesys.cn/mcp/48 详情页"请求参数 Header"段证据。
        """
        if not user_token or user_token.count(".") != 2:
            return None
        try:
            import base64 as _b64, json as _json
            from app.mcp_request_ctx import McpRequestCtx
            from app.database import AsyncSessionLocal
            from app.models import User
            from sqlalchemy import select as _select

            # 解 dolphin JWT 拿 sub（不验签 — dolphin 自家签的我们没 secret）
            try:
                p = user_token.split(".")[1]
                p += "=" * (-len(p) % 4)
                pl = _json.loads(_b64.urlsafe_b64decode(p))
                dolphin_sub = pl.get("sub")
            except Exception:
                return None
            if not dolphin_sub:
                return None

            # a) cache 反查
            try:
                from app.services.dolphin_sso_v2 import _TOKEN_CACHE, _LOCK
                with _LOCK:
                    matched_uid = None
                    for uid, (tok, sub, _exp) in _TOKEN_CACHE.items():
                        if str(sub) == str(dolphin_sub):
                            matched_uid = uid
                            break
                if matched_uid:
                    async with AsyncSessionLocal() as _db:
                        u = (await _db.execute(
                            _select(User).where(User.id == matched_uid)
                        )).scalar_one_or_none()
                        if u and u.is_active:
                            from app.deps import resolve_default_tenant_id_for_user
                            local_tid = await resolve_default_tenant_id_for_user(_db, u.id) or 0
                            import logging as _lg
                            _lg.getLogger(__name__).info(
                                "MCP user-token resolved via cache: dolphin_sub=%s → local uid=%s tid=%s",
                                dolphin_sub, u.id, local_tid,
                            )
                            return McpRequestCtx(
                                local_user_id=u.id,
                                local_tenant_id=local_tid,
                                apaas_user_id=u.apaas_user_id or None,
                                apaas_tenant_id=u.apaas_tenant_id or None,
                                username=u.username,
                                auth_source="dolphin_user_token",
                            )
            except Exception as exc:
                import logging as _lg
                _lg.getLogger(__name__).warning("dolphin cache 反查异常: %s", exc)

            # b) 调 dolphin /api/auth/me 拿 username
            try:
                import httpx as _httpx
                from app.config import settings as _settings
                server = (_settings.dolphin_server_url or "").rstrip("/")
                if server:
                    async with _httpx.AsyncClient(timeout=8) as _c:
                        r = await _c.get(f"{server}/api/auth/me",
                                         headers={"Authorization": f"Bearer {user_token}"})
                        if r.status_code == 200:
                            d = r.json()
                            uname = d.get("username") or d.get("nickname")
                            if uname:
                                async with AsyncSessionLocal() as _db:
                                    u = (await _db.execute(
                                        _select(User).where(User.username == uname)
                                    )).scalar_one_or_none()
                                    if u and u.is_active:
                                        from app.deps import resolve_default_tenant_id_for_user
                                        local_tid = await resolve_default_tenant_id_for_user(_db, u.id) or 0
                                        # 顺手把映射写到 cache，下次直接命中
                                        from app.services.dolphin_sso_v2 import _TOKEN_CACHE, _LOCK, _CACHE_TTL
                                        import time as _time
                                        with _LOCK:
                                            _TOKEN_CACHE[u.id] = (user_token, int(dolphin_sub), _time.time() + _CACHE_TTL)
                                        import logging as _lg
                                        _lg.getLogger(__name__).info(
                                            "MCP user-token resolved via dolphin /me: dolphin_sub=%s "
                                            "username=%s → local uid=%s tid=%s",
                                            dolphin_sub, uname, u.id, local_tid,
                                        )
                                        return McpRequestCtx(
                                            local_user_id=u.id,
                                            local_tenant_id=local_tid,
                                            apaas_user_id=u.apaas_user_id or None,
                                            apaas_tenant_id=u.apaas_tenant_id or None,
                                            username=u.username,
                                            auth_source="dolphin_user_token_meq",
                                        )
            except Exception as exc:
                import logging as _lg
                _lg.getLogger(__name__).warning("dolphin /me 反查异常: %s", exc)
        except Exception:
            pass
        return None


    import logging as _logging

    # 所有 MCP 工具统一暴露在一个 Streamable HTTP endpoint。
    _mcp_streamable = _mcp_server.streamable_http_app()
    # streamable_http_app 内 path 是 /mcp → 公开 URL: /api/mcp/mcp
    app.mount("/api/mcp", _McpAuthMiddleware(_mcp_streamable))
    _logging.getLogger(__name__).info(
        "Unified MCP mounted: streamable=/api/mcp/mcp"
    )
except Exception as exc:
    import logging as _logging
    _logging.getLogger(__name__).warning("MCP server 启用失败（不影响主应用）：%s", exc)


# 平台插件资源中间件：/{32位hex}/... → 代理到平台
# SSE 防缓冲 middleware：text/event-stream 响应自动注入 X-Accel-Buffering: no
#
# 注意：这两个原本用 @app.middleware("http")（即 BaseHTTPMiddleware）实现，
# 但 BaseHTTPMiddleware 的 call_next buffering 跟流式 SSE 不兼容，会切断 MCP
# 服务器的 message 流（dolphin agent 拿不到 tools/list 响应）。
# 改成纯 ASGI middleware 后，对所有 mount（包括 /api/mcp）都安全透传。
import re as _re
from starlette.requests import Request as _StarletteRequest
_PLUGIN_HASH_RE = _re.compile(r'^/[0-9a-f]{32}/')


class _PluginAssetAsgiMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and _PLUGIN_HASH_RE.match(scope.get("path", "")):
            from app.routes.platform_proxy import handle_plugin_asset_request
            request = _StarletteRequest(scope, receive=receive)
            response = await handle_plugin_asset_request(request)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


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
app.add_middleware(_PluginAssetAsgiMiddleware)


# 静态文件（浏览器预览页面等）
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/api/static", StaticFiles(directory=str(_static_dir)), name="static")


def _external_base_paths() -> list[str]:
    paths: list[str] = []
    for value in (os.getenv("BASE_PATH"), os.getenv("ROOT_PATH"), "/ai-builder"):
        if not value:
            continue
        path = "/" + value.strip("/")
        if path == "/":
            continue
        if path not in paths:
            paths.append(path)
    return paths


def _configured_external_base_paths() -> set[str]:
    paths: set[str] = set()
    for value in (os.getenv("BASE_PATH"), os.getenv("ROOT_PATH")):
        if not value:
            continue
        path = "/" + value.strip("/")
        if path != "/":
            paths.add(path)
    return paths


def _legacy_base_redirect_target(path: str) -> str | None:
    configured = _configured_external_base_paths()
    for base_path in _external_base_paths():
        if base_path in configured:
            continue
        if path == base_path:
            return "/"
        if path.startswith(f"{base_path}/"):
            return path.removeprefix(base_path) or "/"
    return None


def _redirect_with_query(request: Request, path: str) -> RedirectResponse:
    query = request.url.query
    return RedirectResponse(url=f"{path}?{query}" if query else path)


def _strip_external_base_path(path: str) -> str:
    for base_path in _external_base_paths():
        if path == base_path:
            return "/"
        if path.startswith(f"{base_path}/"):
            return path.removeprefix(base_path)
    return path

# 2026-05-13: admin-spa 静态资源（Dockerfile multi-stage build 产物 mount 到 /app/admin-spa/dist）
# 浏览器访问 https://<host>/<base>/admin/ → ingress rewrite 砍 base → /admin → 这个 mount
# admin-spa 编译期按环境注入 VITE_API_BASE_URL。
# html=True 让 SPA history-mode router 走 fallback 到 index.html
_admin_spa_dir = Path(__file__).resolve().parent.parent.parent / "admin-spa" / "dist"
if _admin_spa_dir.is_dir():
    class _AdminSpaFallbackMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                return await self.app(scope, receive, send)
            method = scope.get("method", "GET")
            path = scope.get("path") or ""
            if method in ("GET", "HEAD"):
                redirect_target = _legacy_base_redirect_target(path)
                if redirect_target and redirect_target.startswith("/admin"):
                    request = Request(scope, receive)
                    response = _redirect_with_query(request, redirect_target)
                    return await response(scope, receive, send)
                normalized = _strip_external_base_path(path)
                if (
                    normalized.startswith("/admin/")
                    and not normalized.startswith("/admin/assets/")
                    and "." not in normalized.rsplit("/", 1)[-1]
                ):
                    response = FileResponse(_admin_spa_dir / "index.html")
                    return await response(scope, receive, send)
            return await self.app(scope, receive, send)

    app.add_middleware(_AdminSpaFallbackMiddleware)
    app.mount("/admin", StaticFiles(directory=str(_admin_spa_dir), html=True), name="admin")
    import logging as _logging
    _logging.getLogger(__name__).info(f"admin-spa mounted at /admin from {_admin_spa_dir}")

    @app.get("/admin", include_in_schema=False)
    async def admin_spa_redirect():
        return RedirectResponse(url="/admin/")

    @app.get("/platform-admin", include_in_schema=False)
    async def platform_admin_redirect():
        frontend_index = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist" / "index.html"
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return RedirectResponse(url="/admin/")

    @app.get("/platform-admin/{spa_path:path}", include_in_schema=False)
    async def platform_admin_prefixed_redirect(spa_path: str):
        frontend_index = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist" / "index.html"
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        clean_path = spa_path.strip("/")
        return RedirectResponse(url=f"/admin/{clean_path}" if clean_path else "/admin/")

    def _make_admin_prefixed_fallback(base_path: str):
        async def admin_spa_prefixed_fallback(spa_path: str, request: Request):
            """Serve admin SPA history routes when ingress preserves external base path."""
            path = request.scope.get("path") or ""
            redirect_target = _legacy_base_redirect_target(path)
            if redirect_target:
                return _redirect_with_query(request, redirect_target)
            target = (_admin_spa_dir / spa_path).resolve()
            try:
                target.relative_to(_admin_spa_dir.resolve())
            except ValueError:
                target = _admin_spa_dir / "index.html"
            if target.is_file():
                return FileResponse(target)
            return FileResponse(_admin_spa_dir / "index.html")

        return admin_spa_prefixed_fallback

    for _base_path in _external_base_paths():
        app.add_api_route(
            f"{_base_path}/admin/{{spa_path:path}}",
            _make_admin_prefixed_fallback(_base_path),
            methods=["GET"],
            include_in_schema=False,
            name=f"admin_spa_prefixed_fallback_{_base_path.strip('/').replace('/', '_')}",
        )


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# Builder 前端静态资源（Dockerfile multi-stage build 产物 mount 到 /app/frontend/dist）
# 浏览器访问 https://<host>/<base>/ → ingress rewrite 砍 base → / → 这个 mount。
# 平台管理继续由 admin-spa 接管 /admin/*。
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dir.is_dir():
    class _FrontendSpaFallbackMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                return await self.app(scope, receive, send)
            method = scope.get("method", "GET")
            path = scope.get("path") or ""
            normalized = _strip_external_base_path(path)
            excluded_prefixes = (
                "/api",
                "/admin",
                "/platform",
                "/backend",
                "/smartbi",
                "/xdap-",
                "/apaas",
                "/plugin",
            )
            redirect_target = _legacy_base_redirect_target(path)
            if (
                method in ("GET", "HEAD")
                and redirect_target
                and not normalized.startswith(excluded_prefixes)
                and not _PLUGIN_HASH_RE.match(normalized)
            ):
                request = Request(scope, receive)
                response = _redirect_with_query(request, redirect_target)
                return await response(scope, receive, send)
            if (
                method in ("GET", "HEAD")
                and not normalized.startswith(excluded_prefixes)
                and not _PLUGIN_HASH_RE.match(normalized)
                and "." not in normalized.rsplit("/", 1)[-1]
            ):
                response = FileResponse(_frontend_dir / "index.html")
                return await response(scope, receive, send)
            return await self.app(scope, receive, send)

    app.add_middleware(_FrontendSpaFallbackMiddleware)

    def _make_frontend_prefixed_fallback(base_path: str):
        async def frontend_spa_prefixed_fallback(spa_path: str, request: Request):
            """Serve Builder frontend when ingress preserves external base path."""
            path = request.scope.get("path") or ""
            redirect_target = _legacy_base_redirect_target(path)
            if redirect_target:
                return _redirect_with_query(request, redirect_target)
            if spa_path.startswith(("api/", "admin/")):
                raise HTTPException(status_code=404, detail="not found")
            target = (_frontend_dir / spa_path).resolve()
            try:
                target.relative_to(_frontend_dir.resolve())
            except ValueError:
                target = _frontend_dir / "index.html"
            if target.is_file():
                return FileResponse(target)
            return FileResponse(_frontend_dir / "index.html")

        return frontend_spa_prefixed_fallback

    for _base_path in _external_base_paths():
        app.add_api_route(
            f"{_base_path}/{{spa_path:path}}",
            _make_frontend_prefixed_fallback(_base_path),
            methods=["GET"],
            include_in_schema=False,
            name=f"frontend_spa_prefixed_fallback_{_base_path.strip('/').replace('/', '_')}",
        )

    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
    import logging as _logging
    _logging.getLogger(__name__).info(f"Builder frontend mounted at / from {_frontend_dir}")
