"""自开发整页预览 — apaas 运行态反向代理 (按应用环境鉴权)。

历史: 原 platform_proxy.py (896 行) 在 e361c7bc 被整体删除, 本意是干掉**内嵌 apaas
编辑器** (ApaasEmbedIframe + 插件资源中间件 + SSO HTML 注入, 已知崩溃源, 已改深链)。
但同一 router 上还驮着 custom-page-host **自开发整页预览**所依赖的两条运行态代理,
被连带误删 → 预览拉 .umd.js 时 /app/... 404 (「组件包加载失败 (404?)」)。本文件复活
预览必需的两条 (不复活编辑器内嵌相关任何东西)。

两条路由分工 (2026-06-05 按应用环境鉴权重写, 治旧版「全局取第一个 connected 环境
注入其 token」的跨租户串号隐患 —— 库里现有 40+ connected 环境, 每 apaas 租户一条):
  - /app/{tenantCode}/{appCode}/...   静态 bundle (.umd.js / .css / img / config):
      apaas 运行态静态资源**公开**(nginx 按路径发, 实测无 token 也 200), 故 **不注入
      token** —— 既够用又彻底绕开跨租户串号。
  - /apaas/backend/{tenantCode}/{appCode}/...  组件运行时数据 ($request):
      需鉴权 → 从 path 里的 appCode 反查 Application → 锁定**该应用自己**绑定的
      PlatformEnv, 注入那个环境的 token (token 空则 relogin 刷新), 401 再 relogin 重试一次。

appCode 在两类 path 里都带 (accessUrl=/app/{tc}/{ac}/, 数据=/apaas/backend/{tc}/{ac}/),
所以无需全局单例状态, 每请求按 path 解析到正确租户。
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time as _time
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Application, PlatformEnv

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runtime-proxy"])

_http_client: Optional[httpx.AsyncClient] = None
_static_cache: dict = {}                 # 静态资源缓存 {url: (content, content_type)}
_appcode_env: dict[str, int] = {}        # app_code -> platform_env_id (应用→环境稳定, 可缓存)
_env_creds: dict[int, dict] = {}         # env_id -> {"host","token","tenant_id"}
_fallback_host: dict = {"host": ""}      # 解析不到应用时的兜底 host (静态仍可加载)
_editor_sessions: dict[str, dict] = {}   # sid -> {"host","token","tenant_id","expires_at"}
_EDITOR_COOKIE = "ab_editor_sid"
_EDITOR_SESSION_TTL_SECONDS = 60 * 60


def register_editor_session(*, host: str, token: str, tenant_id: str) -> str:
    """注册一个短期低代码后台编辑会话，供 /platform 和 /backend 代理注入登录态。"""
    _cleanup_editor_sessions()
    sid = secrets.token_urlsafe(24)
    _editor_sessions[sid] = {
        "host": (host or "").rstrip("/"),
        "token": token or "",
        "tenant_id": tenant_id or "",
        "expires_at": _time.time() + _EDITOR_SESSION_TTL_SECONDS,
    }
    return sid


def _cleanup_editor_sessions() -> None:
    now = _time.time()
    for sid, data in list(_editor_sessions.items()):
        if float(data.get("expires_at") or 0) <= now:
            _editor_sessions.pop(sid, None)


def _editor_session_from_request(request: Request) -> Optional[dict]:
    _cleanup_editor_sessions()
    sid = request.cookies.get(_EDITOR_COOKIE) or request.query_params.get("_ab_editor_sid") or ""
    data = _editor_sessions.get(sid)
    if not data:
        return None
    # 滑动续期，避免用户编辑超过首次加载窗口后静态/API 资源失效。
    data["expires_at"] = _time.time() + _EDITOR_SESSION_TTL_SECONDS
    return data


def _platform_auth_bootstrap_script(creds: dict) -> str:
    """给代理版 /platform HTML 注入 Vuex 持久化登录态。"""
    token = creds.get("token") or ""
    tenant_id = creds.get("tenant_id") or ""
    local_state = {
        "authModule": {
            "userInfo": {},
            "tenantBlock": {"token": token, "oriToken": None},
            "platformBlock": {"token": token, "oriToken": None},
            "orgs": [],
            "wxInfo": None,
            "adminAuth": {},
            "accountConfiguration": {},
            "appFormat": {},
            "accountSecurity": {},
            "variableConfigInfo": None,
        }
    }
    session_state = {
        "tenantModule": {
            "currentOrg": {"id": tenant_id},
            "orgs": [{"id": tenant_id}],
        }
    }
    payload = json.dumps(
        {
            "token": token,
            "tenantId": tenant_id,
            "localState": local_state,
            "sessionState": session_state,
        },
        ensure_ascii=False,
    )
    return (
        "<script>(function(){try{"
        f"var p={payload};"
        "localStorage.setItem('__vuex__local',JSON.stringify(p.localState));"
        "sessionStorage.setItem('__vuex__session',JSON.stringify(p.sessionState));"
        "localStorage.setItem('xdaptoken',p.token);"
        "sessionStorage.setItem('xdaptoken',p.token);"
        "localStorage.setItem('xdaptenantid',p.tenantId);"
        "sessionStorage.setItem('xdaptenantid',p.tenantId);"
        "}catch(e){console.warn('AI Builder 写入 aPaaS 登录态失败',e)}})();</script>"
    )


def _extract_app_code(path: str) -> str:
    """从代理 path 里取 appCode。

    path 已带前缀 (proxy_app_runtime 传 "app/...", proxy_apaas 传 "apaas/..."):
      app/{tenantCode}/{appCode}/...                → segs[2]
      apaas/backend/{tenantCode}/{appCode}/...       → segs[3]
      apaas/{tenantCode}/{appCode}/...   (退化)       → segs[2]
    取不到返 ""(调用方走 fallback host, 不注入 token)。
    """
    segs = [s for s in path.split("/") if s]
    if not segs:
        return ""
    if segs[0] == "app" and len(segs) >= 3:
        return segs[2]
    if segs[0] == "apaas":
        rest = segs[1:]
        if rest[:1] == ["backend"] and len(rest) >= 3:
            return rest[2]
        if len(rest) >= 2:
            return rest[1]
    return ""


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32, keepalive_expiry=30.0),
            follow_redirects=True,
            verify=False,
        )
    return _http_client


# 瞬时连接错误 — 连接未建立必定没发数据, 任何方法都可安全重试.
_CONNECT_EXC = (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout)
# 瞬时读错误 — 请求已发出, 只有幂等方法 (GET/HEAD/OPTIONS) 可安全重试.
_READ_EXC = (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError)


async def _request_with_retry(client: httpx.AsyncClient, *, method: str, url: str,
                              headers: dict, content, attempts: int = 3) -> httpx.Response:
    """对瞬时网络错误重试 — 自开发整页启动时并发拉 bundle + css + 数据, 上游 TLS
    建连偶发超时会让关键文件 502, 重试 2 次几乎必成功。"""
    idempotent = method.upper() in ("GET", "HEAD", "OPTIONS")
    for i in range(attempts):
        try:
            return await client.request(method=method, url=url, headers=headers, content=content)
        except _CONNECT_EXC:
            if i >= attempts - 1:
                raise
            await asyncio.sleep(0.3 * (i + 1))
        except _READ_EXC:
            if not idempotent or i >= attempts - 1:
                raise
            await asyncio.sleep(0.3 * (i + 1))
    raise RuntimeError("unreachable")  # pragma: no cover


def _error_html(title: str, detail: str) -> str:
    """带样式的错误页, body 上带 data-proxy-error 供前端检测。"""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{margin:0;display:flex;align-items:center;justify-content:center;"
        "height:100vh;font-family:-apple-system,sans-serif;background:#f8f8fc;}"
        ".box{text-align:center;color:#555;padding:32px}"
        "h3{font-size:16px;font-weight:600;color:#333;margin:0 0 8px}"
        "p{font-size:13px;margin:0;color:#888}</style></head>"
        f"<body data-proxy-error='1'><div class='box'><h3>{title}</h3><p>{detail}</p></div></body></html>"
    )


async def _env_id_for_app_code(app_code: str) -> Optional[int]:
    """path 里的 appCode → 该应用绑定的 platform_env_id (缓存)。

    app_code 在本库实践中全局唯一; 万一多租户撞码, 取最早一条并告警 (path 不带可
    区分的 env 信息, 无法进一步消歧)。"""
    if not app_code:
        return None
    if app_code in _appcode_env:
        return _appcode_env[app_code]
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Application.id, Application.platform_env_id).where(
                Application.app_code == app_code,
                Application.platform_env_id.is_not(None),
            ).order_by(Application.id)
        )).all()
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning("app_code=%s 命中 %d 个应用, 代理取最早一条 env=%s",
                       app_code, len(rows), rows[0][1])
    env_id = rows[0][1]
    _appcode_env[app_code] = env_id
    return env_id


async def _creds_for_env(env_id: int, *, force_refresh: bool = False) -> Optional[dict]:
    """env_id → {host, token, tenant_id}(缓存)。token 空或强刷时 relogin 刷新。"""
    if not force_refresh and env_id in _env_creds:
        return _env_creds[env_id]
    async with AsyncSessionLocal() as db:
        env = (await db.execute(select(PlatformEnv).where(PlatformEnv.id == env_id))).scalar_one_or_none()
        if env is None:
            return None
        if force_refresh or not env.token:
            from app.coding.apaas_tools import _relogin_apaas_env
            await _relogin_apaas_env(env_id, db)  # 内部 db.commit() 持久化 token
            env = (await db.execute(select(PlatformEnv).where(PlatformEnv.id == env_id))).scalar_one_or_none()
            if env is None:
                return None
        creds = {
            "host": env.base_url.rstrip("/").replace("/backend", ""),
            "token": env.token or "",
            "tenant_id": env.platform_tenant_id or "",
        }
        _env_creds[env_id] = creds
        return creds


async def _resolve_target(path: str) -> tuple[Optional[dict], Optional[int]]:
    """按 path 解析 (creds, env_id)。解析不到应用时退回 fallback host(无 token)。"""
    env_id = await _env_id_for_app_code(_extract_app_code(path))
    if env_id is not None:
        creds = await _creds_for_env(env_id)
        if creds:
            return creds, env_id
    # fallback: 任一 connected 环境的 host(全 trial 同 host), 仅供静态加载, 不带 token
    if not _fallback_host["host"]:
        async with AsyncSessionLocal() as db:
            env = (await db.execute(
                select(PlatformEnv).where(PlatformEnv.status == "connected").limit(1)
            )).scalar_one_or_none()
            if env:
                _fallback_host["host"] = env.base_url.rstrip("/").replace("/backend", "")
    if _fallback_host["host"]:
        return {"host": _fallback_host["host"], "token": "", "tenant_id": ""}, None
    return None, None


def _auth_headers(creds: dict) -> dict:
    return {
        "xdaptoken": creds.get("token", ""),
        "xdaptenantid": creds.get("tenant_id", ""),
        "xdaptimestamp": str(int(_time.time() * 1000)),
    }


async def _proxy_request(request: Request, path: str, *, need_token: bool) -> Response:
    """运行态代理 — 按 path 锁定应用环境, 静态资源缓存, 401(数据)relogin 重试一次。"""
    creds, env_id = await _resolve_target(path)
    if creds is None:
        return Response(content="Proxy not initialized", status_code=503)
    host = creds["host"]

    qs = str(request.query_params)
    target = f"{host}/{path}"
    if qs:
        target += f"?{qs}"

    headers: dict = {}
    if need_token and creds.get("token"):
        headers.update(_auth_headers(creds))
    # 透传前端发来的认证头 (平台 JS 自己也会带)
    for h in ("content-type", "accept", "accept-language",
              "xdaptoken", "xdaptenantid", "xdaptimestamp", "appid"):
        val = request.headers.get(h)
        if val:
            headers[h] = val

    # 静态资源缓存 (bundle / css / 字体 / 图片 — 带哈希, 内容不变)
    is_static = request.method == "GET" and any(
        seg in path for seg in ("/static/", "/dll/", "/img/", "/fonts/", ".css", ".js",
                                 ".woff", ".ttf", ".png", ".ico")
    )
    if is_static and target in _static_cache:
        cached = _static_cache[target]
        return Response(content=cached[0], media_type=cached[1])

    client = _get_client()
    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
        resp = await _request_with_retry(client, method=request.method, url=target, headers=headers, content=body)

        # 数据调用撞 401 → 刷新**该应用环境**的 token 重试一次 (不串别租户)
        if resp.status_code == 401 and need_token and env_id is not None:
            fresh = await _creds_for_env(env_id, force_refresh=True)
            if fresh and fresh.get("token"):
                headers.update(_auth_headers(fresh))
                resp = await _request_with_retry(client, method=request.method, url=target, headers=headers, content=body)

        resp_headers = {}
        for k, v in resp.headers.items():
            if k.lower() in ("content-type", "cache-control", "etag", "last-modified", "content-disposition"):
                resp_headers[k] = v

        content = resp.content
        ct = resp.headers.get("content-type", "")

        if is_static and resp.status_code == 200:
            _static_cache[target] = (content, ct)

        return Response(content=content, status_code=resp.status_code, headers=resp_headers)
    except Exception as e:  # noqa: BLE001
        detail = str(e) or type(e).__name__
        logger.error(f"Runtime proxy error [{path}]: {detail}")
        return Response(
            content=_error_html("连接平台失败", f"无法访问平台:{detail}"),
            media_type="text/html",
            status_code=502,
            headers={"X-Proxy-Error": "connection-failed"},
        )


async def _proxy_editor_request(request: Request, path: str) -> Response:
    """代理 aPaaS 管理后台编辑器，基于 editor-entry 建立的短期会话注入登录态。"""
    creds = _editor_session_from_request(request)
    if not creds:
        return Response(
            content=_error_html("低代码后台会话已失效", "请从 AI Builder 重新点击「打开低代码后台」。"),
            media_type="text/html",
            status_code=401,
        )
    host = creds["host"]
    target_path = path if path.startswith("/") else f"/{path}"
    qs_items = [(k, v) for k, v in request.query_params.multi_items() if k != "_ab_editor_sid"]
    qs = str(httpx.QueryParams(qs_items))
    target = f"{host}{target_path}"
    if qs:
        target += f"?{qs}"

    headers: dict = {}
    if creds.get("token"):
        headers.update(_auth_headers(creds))
    for h in ("content-type", "accept", "accept-language", "appid"):
        val = request.headers.get(h)
        if val:
            headers[h] = val

    client = _get_client()
    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
        resp = await _request_with_retry(client, method=request.method, url=target, headers=headers, content=body)
        resp_headers = {}
        for k, v in resp.headers.items():
            if k.lower() in ("content-type", "cache-control", "etag", "last-modified", "content-disposition"):
                resp_headers[k] = v

        content = resp.content
        ct = resp.headers.get("content-type", "")
        if request.method == "GET" and "text/html" in ct.lower() and path.startswith("/platform/"):
            try:
                text = content.decode(resp.encoding or "utf-8", errors="replace")
                script = _platform_auth_bootstrap_script(creds)
                if "</head>" in text:
                    text = text.replace("</head>", script + "</head>", 1)
                else:
                    text = script + text
                content = text.encode("utf-8")
                resp_headers["content-type"] = "text/html; charset=utf-8"
            except Exception as exc:  # noqa: BLE001
                logger.warning("注入 aPaaS 编辑器登录态失败: %s", exc)

        return Response(content=content, status_code=resp.status_code, headers=resp_headers)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc) or type(exc).__name__
        logger.error("Editor proxy error [%s]: %s", path, detail)
        return Response(
            content=_error_html("连接低代码后台失败", detail),
            media_type="text/html",
            status_code=502,
            headers={"X-Proxy-Error": "editor-connection-failed"},
        )


# 代理运行态数据请求 /apaas/...  (自开发组件 $request → /apaas/backend/{tenant}/{app}/...)
# 需鉴权 → 按 path 里 appCode 锁定该应用环境, 注入它自己的 token (治跨租户串号)。
@router.api_route("/apaas/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_apaas(request: Request, path: str):
    return await _proxy_request(request, f"apaas/{path}", need_token=True)


# 代理 apaas 应用**运行态** /app/...  (自开发整页 bundle: accessUrl = {host}/app/{tenant}/{app}/)
# 页面 + 全部静态资源 (.umd.js / .css / img / config) 都在这个前缀下, **公开无需 token**。
@router.api_route("/app/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_app_runtime(request: Request, path: str):
    return await _proxy_request(request, f"app/{path}", need_token=False)


@router.api_route("/platform/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_platform_editor(request: Request, path: str):
    return await _proxy_editor_request(request, f"/platform/{path}")


@router.api_route("/backend/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_platform_backend(request: Request, path: str):
    return await _proxy_editor_request(request, f"/backend/{path}")
