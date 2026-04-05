"""
Platform Reverse Proxy — 全量反向代理得帆云平台，实现 iframe SSO

原理：
1. iframe 加载 /api/platform-proxy/entry?app_id=xxx (同源 localhost:8001)
2. 后端代理平台 HTML，注入 JS 将 token 写入 localStorage (__vuex__local)
3. 平台 JS 加载的资源 /platform/... → 代理到真实平台
4. 平台 API 请求 /backend/... → 代理到真实平台（注入 auth headers）
5. 全部同源，无跨域问题，SSO 完成
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.apaas_client import APaaSClient
from app.crypto import decrypt_password
from app.database import AsyncSessionLocal
from app.models import PlatformEnv

logger = logging.getLogger(__name__)
router = APIRouter(tags=["platform-proxy"])

# ── 全局状态：当前代理目标 ──
# iframe 入口设置后，后续的 /platform/ 和 /backend/ 请求都代理到同一个平台
_proxy_state: dict = {
    "host": "",       # e.g. https://apaas-dev8.dfy.definesys.cn
    "token": "",
    "tenant_id": "",
    "username": "",
}

_http_client: Optional[httpx.AsyncClient] = None
_static_cache: dict = {}  # 静态资源缓存 {url: (content, content_type)}


async def _refresh_env_token(env: PlatformEnv) -> bool:
    """使用环境中保存的账号密码刷新平台 token。"""
    if not env.username or not env.password_enc:
        return False
    try:
        password = decrypt_password(env.password_enc)
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
        login_result = await client.login(env.username, password)
        token = login_result.get("token", "")
        if not token:
            return False
        env.token = token
        env.status = "connected"
        _proxy_state["host"] = env.base_url.rstrip("/").replace("/backend", "")
        _proxy_state["token"] = token
        _proxy_state["tenant_id"] = env.platform_tenant_id
        _proxy_state["username"] = env.username or ""
        return True
    except Exception as e:
        logger.warning(f"Failed to refresh platform token: {e}")
        return False


async def _find_proxy_env() -> Optional[PlatformEnv]:
    """按当前代理状态定位环境，供 token 续期使用。"""
    host = _proxy_state.get("host", "").rstrip("/")
    tenant_id = _proxy_state.get("tenant_id", "")
    async with AsyncSessionLocal() as db:
        if host and tenant_id:
            result = await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.base_url.like(f"{host}%"),
                    PlatformEnv.platform_tenant_id == tenant_id,
                ).limit(1)
            )
            env = result.scalar_one_or_none()
            if env:
                return env
        result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.status == "connected").limit(1)
        )
        return result.scalar_one_or_none()


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            verify=False,
        )
    return _http_client


def _extract_user_id_from_token(token: str) -> str:
    """从平台 JWT token 中提取 xdapuserid"""
    import base64
    try:
        payload_b64 = token.split(".")[1]
        # 补齐 base64 padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return str(payload.get("xdapuserid", ""))
    except Exception:
        return ""


def _build_vuex_state(token: str, tenant_id: str, username: str) -> str:
    """构建 __vuex__local 值 — 模拟真实登录后的完整 Vuex 状态"""
    user_id = _extract_user_id_from_token(token)
    state = {
        "authModule": {
            "tenantBlock": {
                "token": token,
                "oriToken": None,
                "tenantId": tenant_id,
            },
            "platformBlock": {
                "token": token,
                "oriToken": None,
            },
            "userInfo": {
                "id": user_id,
                "account": username,
                "username": username,
                "phone": username,
                "accountType": "FORMAL",
                "tenant": {
                    "id": tenant_id,
                    "role": "ADMIN",
                    "roleName": "组织管理员",
                    "activeFlag": False,
                    "allowRelease": True,
                    "appAdminFlag": False,
                    "tenantType": "NORMAL",
                },
            },
            "orgs": [
                {
                    "id": tenant_id,
                    "roleName": "ADMIN",
                    "role": "ADMIN",
                }
            ],
            "adminAuth": {
                "system": True,
                "tenant": True,
                "biTenantAdmin": True,
            },
            "accountConfiguration": {},
            "accountSecurity": {},
            "appFormat": {},
            "variableConfigInfo": None,
            "wxInfo": None,
        }
    }
    return json.dumps(state, ensure_ascii=False)


def _inject_sso_script(html: str, vuex_state: str) -> str:
    """在 HTML <head> 中注入 SSO 脚本。

    这里只做登录态注入，不再额外隐藏顶部 header。
    平台编辑页会复用多层 header / toolbar 容器，粗暴隐藏会把
    “应用详情 / 访问权限 / 菜单功能”等上方信息一起误伤，导致
    iframe 中出现空白占位。
    """
    escaped = json.dumps(vuex_state)
    script = (
        "\n<script>\n"
        "(function(){\n"
        "  var selectors = [\n"
        "    '.app-top-header',\n"
        "    '.header-wrap',\n"
        "    '.layout-header',\n"
        "    '.main-header',\n"
        "    '.tenant-header',\n"
        "    '.platform-header',\n"
        "    '.x-header',\n"
        "    '#header',\n"
        "    'header.el-header',\n"
        "    '.el-header',\n"
        "    '.page-header',\n"
        "    '.edit-header',\n"
        "    '.app-detail-header',\n"
        "    '.app-edit-header',\n"
        "    '.step-tabs',\n"
        "    '.tab-header'\n"
        "  ];\n"
        "  function repairHeaders(){\n"
        "    try {\n"
        "      var override = document.querySelector('#iframe-overrides');\n"
        "      if (override && override.parentNode) override.parentNode.removeChild(override);\n"
        "      selectors.forEach(function(selector){\n"
        "        document.querySelectorAll(selector).forEach(function(el){\n"
        "          if (el && el.style) {\n"
        "            if (el.style.display === 'none') el.style.removeProperty('display');\n"
        "            if (el.style.visibility === 'hidden') el.style.removeProperty('visibility');\n"
        "            if (el.style.opacity === '0') el.style.removeProperty('opacity');\n"
        "            if (el.style.height === '0px') el.style.removeProperty('height');\n"
        "            if (el.style.maxHeight === '0px') el.style.removeProperty('max-height');\n"
        "          }\n"
        "          if (typeof el.hidden !== 'undefined' && el.hidden) el.hidden = false;\n"
        "        });\n"
        "      });\n"
        "    } catch (repairErr) {\n"
        "      console.warn('[SSO repair]', repairErr);\n"
        "    }\n"
        "  }\n"
        "  try {\n"
        "    var k='__vuex__local', v=" + escaped + ";\n"
        "    localStorage.setItem(k,v);\n"
        "    console.log('[SSO] token injected');\n"
        "  }catch(ex){console.error('[SSO]',ex)}\n"
        "  repairHeaders();\n"
        "  var attempts = 0;\n"
        "  var timer = setInterval(function(){\n"
        "    attempts += 1;\n"
        "    repairHeaders();\n"
        "    if (attempts >= 40) clearInterval(timer);\n"
        "  }, 500);\n"
        "  try {\n"
        "    var observer = new MutationObserver(function(){ repairHeaders(); });\n"
        "    observer.observe(document.documentElement || document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class', 'hidden'] });\n"
        "    setTimeout(function(){ observer.disconnect(); }, 20000);\n"
        "  } catch (obsErr) {\n"
        "    console.warn('[SSO observer]', obsErr);\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
    inject = script
    if "<head>" in html:
        return html.replace("<head>", "<head>" + inject, 1)
    return inject + html


# ============================================================
# 入口：iframe 加载此 URL
# ============================================================

@router.post("/api/platform-proxy/init")
async def proxy_init(request: Request):
    """初始化代理状态（前端在加载 iframe 前调用）"""
    body = await request.json()
    _proxy_state["host"] = body.get("host", "")
    _proxy_state["token"] = body.get("token", "")
    _proxy_state["tenant_id"] = body.get("tenant_id", "")
    _proxy_state["username"] = body.get("username", "")
    logger.info(f"Proxy initialized: host={_proxy_state['host']}, tenant={_proxy_state['tenant_id']}")
    return {"ok": True}


@router.get("/api/platform-proxy/entry")
async def proxy_entry(
    app_id: int,
    request: Request,
):
    """iframe SSO 入口 — 获取平台信息、代理 HTML、注入 token"""
    from app.models import Application
    from app.deps import get_auth_context_from_token

    # 从 query 或 header 获取 auth token
    auth_token = request.query_params.get("_auth") or ""
    if not auth_token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            auth_token = auth_header[7:]

    if not auth_token:
        return Response(content="<h3>未认证</h3>", media_type="text/html", status_code=401)

    try:
        ctx = await get_auth_context_from_token(auth_token)
    except Exception:
        return Response(content="<h3>认证失败</h3>", media_type="text/html", status_code=401)

    async with AsyncSessionLocal() as db:
        # 查应用
        result = await db.execute(
            select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
        )
        app = result.scalar_one_or_none()
        if not app or not app.apaas_app_id:
            return Response(content="<h3>应用未部署</h3>", media_type="text/html")

        # 查环境：按优先级依次查 应用绑定 → 默认环境 → 任意已连接环境
        env = None
        if app.platform_env_id:
            r = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
            env = r.scalar_one_or_none()
        if not env or not env.token:
            r = await db.execute(
                select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
            )
            env = r.scalar_one_or_none()
        if not env or not env.token:
            r = await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.tenant_id == ctx.tenant_id,
                    PlatformEnv.status == "connected",
                ).limit(1)
            )
            env = r.scalar_one_or_none()
        if not env:
            return Response(content="<h3>平台环境未配置</h3>", media_type="text/html")

        refreshed = False
        if env.username and env.password_enc:
            refreshed = await _refresh_env_token(env)
        elif not env.token:
            refreshed = await _refresh_env_token(env)

        if refreshed:
            await db.commit()
        elif not env.token:
            return Response(content="<h3>平台环境未登录</h3>", media_type="text/html")

        host = env.base_url.rstrip("/").replace("/backend", "")
        tid = env.platform_tenant_id

    # 保存代理状态（后续 /platform/ 和 /backend/ 请求用）
    _proxy_state["host"] = host
    _proxy_state["token"] = env.token
    _proxy_state["tenant_id"] = tid
    _proxy_state["username"] = env.username or ""

    # 生成 SSO 注入页面：先写 localStorage，再重定向到代理路径
    vuex = _build_vuex_state(env.token, tid, env.username or "")
    escaped_vuex = json.dumps(vuex)
    redirect_path = f"/platform/{tid}/admin/app-store/edit-app?appId={app.apaas_app_id}&currentStepIndex=0"
    redirect_json = json.dumps(redirect_path)

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        "body{margin:0;background:#0a0a14;display:flex;align-items:center;justify-content:center;height:100vh;font-family:-apple-system,sans-serif}"
        ".box{text-align:center;color:rgba(255,255,255,0.5)}"
        ".spinner{width:36px;height:36px;border:3px solid rgba(124,58,237,0.15);border-top-color:#7c3aed;"
        "border-radius:50%;animation:s .7s linear infinite;margin:0 auto 16px}"
        "@keyframes s{to{transform:rotate(360deg)}}"
        "p{font-size:14px;margin:0;letter-spacing:0.5px}"
        "</style></head><body>"
        "<div class='box'><div class='spinner'></div><p>正在连接平台...</p></div>"
        "<script>\n"
        "try{\n"
        "  localStorage.setItem('__vuex__local'," + escaped_vuex + ");\n"
        "  console.log('[SSO] token set');\n"
        "}catch(e){console.error(e)}\n"
        "window.location.replace(" + redirect_json + ");\n"
        "</script></body></html>"
    )
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ============================================================
# 全量代理：/platform/... 和 /backend/...
# ============================================================

async def _ensure_proxy_state():
    """确保 proxy state 已初始化，如果为空则从数据库恢复"""
    if _proxy_state.get("host"):
        return True
    try:
        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(PlatformEnv).where(PlatformEnv.status == "connected").limit(1)
            )
            env = r.scalar_one_or_none()
            if env:
                if not env.token and not await _refresh_env_token(env):
                    return False
                if env.token:
                    await db.commit()
                    logger.info(f"Proxy state auto-recovered: host={_proxy_state['host']}")
                    return True
    except Exception as e:
        logger.warning(f"Failed to auto-recover proxy state: {e}")
    return False


async def _proxy_request(request: Request, path: str, inject_auth: bool = False) -> Response:
    """通用代理逻辑"""
    host = _proxy_state.get("host")
    if not host:
        if not await _ensure_proxy_state():
            return Response(content="Proxy not initialized", status_code=503)
        host = _proxy_state.get("host")

    # 构建目标 URL
    qs = str(request.query_params)
    target = f"{host}/{path}"
    if qs:
        target += f"?{qs}"

    # 请求头
    headers = {}
    if inject_auth:
        import time as _time
        headers["xdaptoken"] = _proxy_state.get("token", "")
        headers["xdaptenantid"] = _proxy_state.get("tenant_id", "")
        headers["xdaptimestamp"] = str(int(_time.time() * 1000))
    # 透传前端发来的认证头（平台 JS 自己会带 xdaptoken/xdaptimestamp）
    for h in ("content-type", "accept", "accept-language",
              "xdaptoken", "xdaptenantid", "xdaptimestamp", "appid"):
        val = request.headers.get(h)
        if val:
            headers[h] = val

    # 静态资源缓存（/platform/static/、/platform/dll/ 等带哈希的文件）
    is_static = request.method == "GET" and any(
        seg in path for seg in ("/static/", "/dll/", "/img/", "/fonts/", ".css", ".woff", ".ttf", ".png", ".ico")
    ) and "env.tmpl.js" not in path  # env.tmpl.js 需要每次改写，不能缓存
    if is_static and target in _static_cache:
        cached = _static_cache[target]
        return Response(content=cached[0], media_type=cached[1])

    client = _get_client()
    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
        resp = await client.request(method=request.method, url=target, headers=headers, content=body)

        if resp.status_code == 401 and _proxy_state.get("username"):
            env = await _find_proxy_env()
            if env and await _refresh_env_token(env):
                async with AsyncSessionLocal() as db:
                    await db.merge(env)
                    await db.commit()
                if inject_auth:
                    import time as _time
                    headers["xdaptoken"] = _proxy_state.get("token", "")
                    headers["xdaptenantid"] = _proxy_state.get("tenant_id", "")
                    headers["xdaptimestamp"] = str(int(_time.time() * 1000))
                resp = await client.request(method=request.method, url=target, headers=headers, content=body)

        resp_headers = {}
        for k, v in resp.headers.items():
            kl = k.lower()
            if kl in ("content-type", "cache-control", "etag", "last-modified", "content-disposition"):
                resp_headers[k] = v

        content = resp.content
        ct = resp.headers.get("content-type", "")

        # HTML 响应注入 SSO 脚本（确保 token 在 localStorage 中）
        token = _proxy_state.get("token", "")
        if "text/html" in ct and token:
            html_text = content.decode("utf-8", errors="replace")
            vuex = _build_vuex_state(token, _proxy_state.get("tenant_id", ""), _proxy_state.get("username", ""))
            content = _inject_sso_script(html_text, vuex).encode("utf-8")
            resp_headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            resp_headers["Pragma"] = "no-cache"
            resp_headers["Expires"] = "0"

        # 缓存静态资源
        if is_static and resp.status_code == 200:
            _static_cache[target] = (content, ct)

        return Response(content=content, status_code=resp.status_code, headers=resp_headers)
    except Exception as e:
        logger.error(f"Proxy error [{path}]: {e}")
        return Response(content=str(e), status_code=502)


# 代理平台前端资源 /platform/...
@router.api_route("/platform/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_platform(request: Request, path: str):
    return await _proxy_request(request, f"platform/{path}", inject_auth=True)


# 代理平台 API /backend/...（注入认证头）
@router.api_route("/backend/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_backend(request: Request, path: str):
    return await _proxy_request(request, f"backend/{path}", inject_auth=True)


# 代理平台插件 /plugin/...
@router.api_route("/plugin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_plugin(request: Request, path: str):
    return await _proxy_request(request, f"plugin/{path}", inject_auth=True)


# 代理平台管理 API /xdap-admin/...（插件查询、帮助文档、租户管理等）
@router.api_route("/xdap-admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_xdap_admin(request: Request, path: str):
    return await _proxy_request(request, f"backend/xdap-admin/{path}", inject_auth=True)


# 代理平台插件 API /xdap-plugin/...
@router.api_route("/xdap-plugin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_xdap_plugin(request: Request, path: str):
    return await _proxy_request(request, f"backend/xdap-plugin/{path}", inject_auth=True)


# 代理其他平台路径 /xdap-open/..., /smartbi/..., /apaas/...
@router.api_route("/xdap-open/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_xdap_open(request: Request, path: str):
    return await _proxy_request(request, f"xdap-open/{path}", inject_auth=True)


@router.api_route("/smartbi/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_smartbi(request: Request, path: str):
    return await _proxy_request(request, f"smartbi/{path}", inject_auth=True)


@router.api_route("/apaas/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_apaas(request: Request, path: str):
    return await _proxy_request(request, f"apaas/{path}", inject_auth=True)


# 代理平台插件包资源 /{32位hex}/... （插件 JS/CSS/图片等）
# FastAPI 不支持正则路由，用中间件方式在 main.py 中注册
# 这里提供处理函数供中间件调用
async def handle_plugin_asset_request(request: Request) -> Response:
    """处理插件资源请求：/{32位hex}/admin/..."""
    path = request.url.path.lstrip("/")
    return await _proxy_request(request, path, inject_auth=False)
