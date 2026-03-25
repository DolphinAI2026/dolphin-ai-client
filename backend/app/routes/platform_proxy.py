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
    """在 HTML <head> 中注入 SSO 脚本"""
    escaped = json.dumps(vuex_state)
    # CSS: 隐藏平台顶部导航栏 + JS: 延迟隐藏兜底
    style = (
        "\n<style id='iframe-overrides'>\n"
        "  .header-wrap, .layout-header, .main-header, .platform-header,\n"
        "  .x-header, #header, header.el-header, .el-header,\n"
        "  .tenant-header, .app-top-header { display: none !important; }\n"
        "</style>\n"
    )
    script = (
        "\n<script>\n"
        "(function(){\n"
        "  try {\n"
        "    var k='__vuex__local', v=" + escaped + ";\n"
        "    localStorage.setItem(k,v);\n"
        "    console.log('[SSO] token injected');\n"
        "  }catch(ex){console.error('[SSO]',ex)}\n"
        "  // 延迟隐藏顶部导航（兜底，等 Vue 渲染完成）\n"
        "  setTimeout(function(){\n"
        "    var h=document.querySelector('.header-wrap,.layout-header,.main-header,.x-header,.el-header,header');\n"
        "    if(h&&h.offsetHeight<80){h.style.display='none';}\n"
        "    // 通用：隐藏第一个 header 高度 < 80px 的元素\n"
        "    document.querySelectorAll('header,[class*=header]').forEach(function(el){\n"
        "      if(el.offsetHeight>0&&el.offsetHeight<80&&el.offsetWidth>window.innerWidth*0.8){\n"
        "        el.style.display='none';\n"
        "      }\n"
        "    });\n"
        "  }, 3000);\n"
        "})();\n"
        "</script>\n"
    )
    inject = style + script
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
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import Application, PlatformEnv
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

        # 查环境
        env = None
        if app.platform_env_id:
            r = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
            env = r.scalar_one_or_none()
        if not env:
            r = await db.execute(
                select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
            )
            env = r.scalar_one_or_none()
        if not env or not env.token:
            return Response(content="<h3>平台环境未配置</h3>", media_type="text/html")

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
    redirect_path = f"/platform/{tid}/admin/app-store/edit-app?appId={app.apaas_app_id}&currentStepIndex=2"
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
    return Response(content=html, media_type="text/html")


# ============================================================
# 全量代理：/platform/... 和 /backend/...
# ============================================================

async def _proxy_request(request: Request, path: str, inject_auth: bool = False) -> Response:
    """通用代理逻辑"""
    host = _proxy_state.get("host")
    if not host:
        return Response(content="Proxy not initialized", status_code=503)

    # 构建目标 URL
    qs = str(request.query_params)
    target = f"{host}/{path}"
    if qs:
        target += f"?{qs}"

    # 请求头
    headers = {}
    if inject_auth:
        headers["xdaptoken"] = _proxy_state.get("token", "")
        headers["xdaptenantid"] = _proxy_state.get("tenant_id", "")
    for h in ("content-type", "accept", "accept-language"):
        val = request.headers.get(h)
        if val:
            headers[h] = val

    # 静态资源缓存（/platform/static/、/platform/dll/ 等带哈希的文件）
    is_static = request.method == "GET" and any(
        seg in path for seg in ("/static/", "/dll/", "/img/", "/fonts/", ".css", ".js", ".woff", ".ttf", ".png", ".ico")
    )
    if is_static and target in _static_cache:
        cached = _static_cache[target]
        return Response(content=cached[0], media_type=cached[1])

    client = _get_client()
    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
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
    return await _proxy_request(request, f"platform/{path}", inject_auth=False)


# 代理平台 API /backend/...（注入认证头）
@router.api_route("/backend/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_backend(request: Request, path: str):
    return await _proxy_request(request, f"backend/{path}", inject_auth=True)


# 代理平台插件 /plugin/...
@router.api_route("/plugin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_plugin(request: Request, path: str):
    return await _proxy_request(request, f"plugin/{path}", inject_auth=True)


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
