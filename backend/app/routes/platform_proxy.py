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
import re
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
    "password": "",
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
        _proxy_state["password"] = password
        return True
    except Exception as e:
        logger.warning(f"Failed to refresh platform token: {type(e).__name__}: {e}")
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


def _error_html(title: str, detail: str) -> str:
    """生成带样式的错误页 HTML，在 iframe 内清晰可读，body 上带 data-proxy-error 供前端检测"""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{margin:0;display:flex;align-items:center;justify-content:center;"
        "height:100vh;font-family:-apple-system,sans-serif;background:#f8f8fc;}"
        ".box{text-align:center;color:#555;padding:32px}"
        "h3{font-size:16px;font-weight:600;color:#333;margin:0 0 8px}"
        "p{font-size:13px;margin:0;color:#888}</style></head>"
        f"<body data-proxy-error='1'><div class='box'><h3>{title}</h3><p>{detail}</p></div></body></html>"
    )


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


# 2026-05-25: 真实命中得帆云 v5 平台全局 nav 的 selectors (实测 admin/app-store/edit-app
# 页面 inspect 到的). 老 selectors (.header-wrap / .layout-header / ...) 保留兜底,
# 跨版本 apaas / 其他得帆云实例可能用到.
_HEADER_SELECTORS = (
    ".base-header,.base-header__container,"
    ".header-wrap,.layout-header,.main-header,.platform-header,"
    ".x-header,#header,header.el-header,.el-header,.tenant-header,.app-top-header"
)

def _inject_sso_script(html: str, vuex_state: str) -> str:
    """在 </head> 前注入 SSO token + **强制隐藏**平台全局 nav.

    2026-05-25 翻转: 老逻辑是强制 show 平台 nav (为了完整平台体验),
    现在 ChatPage 有自己的 TopBar, 平台 nav (得帆云 logo / 资源市场 / 应用市场 /
    用户头像) 全是冗余 chrome 跟外层重叠. 改成强制 hide.

    保留: 伪装非 iframe (防平台 frame busting). 应用编辑 header + tab 栏 (不在
    _HEADER_SELECTORS 范围) 不受影响 — 用户仍能切 \"应用信息/访问权限/...\" 等 tab.
    """
    escaped = json.dumps(vuex_state)

    # CSS: 强制 hide 平台全局 nav. !important 覆盖平台默认样式
    style = (
        "\n<style id='apaas-builder-overrides'>\n"
        + ",\n".join(s.strip() for s in _HEADER_SELECTORS.split(",")) + " {\n"
        "  display: none !important;\n"
        "  visibility: hidden !important;\n"
        "  height: 0 !important;\n"
        "  overflow: hidden !important;\n"
        "  pointer-events: none !important;\n"
        "}\n"
        "</style>\n"
    )

    script = (
        "\n<script>\n"
        "(function(){\n"
        # 伪装非 iframe — 防平台 frame busting (top/parent 让 if(window!==top) 短路)
        "  ['top','parent','frameElement'].forEach(function(k){\n"
        "    try{\n"
        "      Object.defineProperty(window,k,{\n"
        "        get:function(){return k==='frameElement'?null:window;},\n"
        "        configurable:true\n"
        "      });\n"
        "    }catch(e){}\n"
        "  });\n"
        # SSO：写入 Vuex token，平台初始化时自动读取，无需手动登录
        "  try{\n"
        "    localStorage.setItem('__vuex__local'," + escaped + ");\n"
        "    sessionStorage.setItem('__vuex__session'," + escaped + ");\n"
        "    console.log('[SSO] token injected');\n"
        "  }catch(ex){console.error('[SSO]',ex)}\n"
        # MutationObserver: 平台 JS 动态显示 nav 时也按下去 (反向 forceShow)
        "  var SEL='" + _HEADER_SELECTORS + "';\n"
        "  function forceHide(el){\n"
        "    el.style.setProperty('display','none','important');\n"
        "    el.style.setProperty('visibility','hidden','important');\n"
        "    el.style.setProperty('height','0','important');\n"
        "  }\n"
        "  function observe(){\n"
        "    document.querySelectorAll(SEL).forEach(forceHide);\n"
        "    var obs=new MutationObserver(function(muts){\n"
        "      muts.forEach(function(m){\n"
        "        var el=m.target;\n"
        "        if(el.nodeType===1){\n"
        "          var cs=window.getComputedStyle(el);\n"
        "          if(cs.display!=='none'){ forceHide(el); }\n"
        "        }\n"
        "      });\n"
        "    });\n"
        "    document.querySelectorAll(SEL).forEach(function(el){\n"
        "      obs.observe(el,{attributes:true,attributeFilter:['style','class']});\n"
        "    });\n"
        "  }\n"
        "  if(document.readyState==='loading'){\n"
        "    document.addEventListener('DOMContentLoaded',observe);\n"
        "  }else{\n"
        "    observe();\n"
        "  }\n"
        "  setTimeout(observe,1500);\n"
        "  setTimeout(observe,3500);\n"
        "})();\n"
        "</script>\n"
    )

    inject = style + script
    html_lower = html.lower()
    if "</head>" in html_lower:
        idx = html_lower.index("</head>")
        return html[:idx] + inject + html[idx:]
    if "<head>" in html_lower:
        idx = html_lower.index("<head>") + len("<head>")
        return html[:idx] + inject + html[idx:]
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
    _proxy_state["password"] = body.get("password", "")
    logger.info(f"Proxy initialized: host={_proxy_state['host']}, tenant={_proxy_state['tenant_id']}")
    return {"ok": True}


# 2026-05-25: 菜单类型 → 平台 editor sub-path. 跟 super-agents-dev openLowCodeEditorDirectly
# 的 URL pattern 对齐. MODEL=数据模型(fn-config 子集), QUOTE=引用表单, 其他默认 fn-config.
_MENU_TYPE_TO_EDITOR_PATH = {
    "MODEL": "data-model-fn-config",
    "MENU_TYPE_MODEL": "data-model-fn-config",
    "QUOTE": "quote-fn-config",
    "MENU_TYPE_QUOTE": "quote-fn-config",
}


def _build_menu_redirect_path(tid: str, apaas_app_id: str,
                               menu_id: str = "", form_id: str = "",
                               menu_type: str = "") -> str:
    """根据菜单类型构建 platform iframe redirect_path.

    - 不传 menu_id → 应用编辑总览页 (老行为)
    - 传 menu_id  → 该菜单对应的表单/模型编辑器
    """
    if not menu_id.strip():
        return f"/platform/{tid}/admin/app-store/edit-app?appId={apaas_app_id}&currentStepIndex=0"

    sub_path = _MENU_TYPE_TO_EDITOR_PATH.get((menu_type or "").upper(), "fn-config")
    base = f"/platform/{tid}/default/{sub_path}"
    qs_parts = [
        f"appId={apaas_app_id}",
        f"menuId={menu_id}",
    ]
    if form_id.strip():
        qs_parts.append(f"formId={form_id}")
    qs_parts.extend(["processVersion=false", "embed=1", "hideClose=1"])
    return f"{base}?{'&'.join(qs_parts)}"


@router.get("/api/platform-proxy/entry")
async def proxy_entry(
    app_id: int,
    request: Request,
    menu_id: str = "",
    form_id: str = "",
    menu_type: str = "",
):
    """iframe SSO 入口 — 获取平台信息、代理 HTML、注入 token.

    2026-05-25 扩展: 可选 menu_id / form_id / menu_type 直接进对应菜单的编辑器.
    AppMenuSidebar 点菜单后用这个 URL 切 iframe src.
    """
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
            return Response(
                content=_error_html("应用未部署到平台", "请先完成部署流程后再使用辅助搭建"),
                media_type="text/html",
                status_code=404,
                headers={"X-Proxy-Error": "not-deployed"},
            )

        # 辅助搭建必须严格使用应用绑定的平台环境，避免串到默认环境/其他已连接环境
        env = None
        if app.platform_env_id:
            r = await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.id == app.platform_env_id,
                    PlatformEnv.tenant_id == ctx.tenant_id,
                )
            )
            env = r.scalar_one_or_none()
            if not env:
                return Response(
                    content=_error_html("应用绑定环境不存在", "当前应用绑定的平台环境不存在，请重新选择环境后再进入辅助搭建"),
                    media_type="text/html",
                    status_code=404,
                    headers={"X-Proxy-Error": "bound-env-not-found"},
                )
        else:
            return Response(
                content=_error_html("应用未绑定环境", "当前应用还没有绑定平台环境，请先重新选择环境并完成一次生成"),
                media_type="text/html",
                status_code=409,
                headers={"X-Proxy-Error": "env-not-bound"},
            )

        # 有账号密码的环境每次都刷新 token，确保不用过期 token
        refreshed = False
        if env.username and env.password_enc:
            refreshed = await _refresh_env_token(env)

        if not refreshed and not env.token:
            return Response(
                content=_error_html("平台环境未登录", f"绑定环境「{env.env_name}」的登录态已失效，请在环境管理中重新登录该环境"),
                media_type="text/html",
                status_code=401,
                headers={"X-Proxy-Error": "env-not-logged-in"},
            )

        if refreshed:
            await db.commit()

        host = env.base_url.rstrip("/").replace("/backend", "")
        tid = env.platform_tenant_id
        password = ""
        if env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
            except Exception:
                password = ""

    # 保存代理状态（后续 /platform/ 和 /backend/ 请求用）
    _proxy_state["host"] = host
    _proxy_state["token"] = env.token
    _proxy_state["tenant_id"] = tid
    _proxy_state["username"] = env.username or ""
    _proxy_state["password"] = password

    # 生成 SSO 注入页面：先写 localStorage，再重定向到代理路径
    vuex = _build_vuex_state(env.token, tid, env.username or "")
    escaped_vuex = json.dumps(vuex)
    redirect_path = _build_menu_redirect_path(
        tid, app.apaas_app_id, menu_id=menu_id, form_id=form_id, menu_type=menu_type,
    )
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
        "  sessionStorage.setItem('__vuex__session'," + escaped_vuex + ");\n"
        "  console.log('[SSO] token set');\n"
        "}catch(e){console.error(e)}\n"
        "window.location.replace(" + redirect_json + ");\n"
        "</script></body></html>"
    )
    return Response(content=html, media_type="text/html")


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
                # token 已有时 _refresh_env_token 不会被调用 → 必须在此显式 set _proxy_state
                # 避免 backend 重启后第一个 /platform/* 请求拿到空 host 报"missing protocol"
                if env.token:
                    _proxy_state["host"] = env.base_url.rstrip("/").replace("/backend", "")
                    _proxy_state["token"] = env.token
                    _proxy_state["tenant_id"] = env.platform_tenant_id
                    _proxy_state["username"] = env.username or ""
                    try:
                        _proxy_state["password"] = decrypt_password(env.password_enc) if env.password_enc else ""
                    except Exception:
                        _proxy_state["password"] = ""
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
        # 2026-05-25: 抓 business-event save 用 — 用户手动配事件时落到文件给我们当模板
        if body and "event/save/event" in path:
            try:
                import os as _os, time as _t
                _capture_dir = "/Users/mars/Vibe Coding/apaas-builder-ai/docs/captures"
                _os.makedirs(_capture_dir, exist_ok=True)
                fname = f"business-event-save-captured-{int(_t.time())}.json"
                with open(f"{_capture_dir}/{fname}", "wb") as fp:
                    fp.write(body)
                logger.info(f"🎯 captured event/save body to {fname} ({len(body)} bytes)")
            except Exception as exc:
                logger.warning(f"capture event/save failed: {exc}")
        # 2026-05-25: 抓 menu/save 用 — 用户手动挂菜单到分组时落到文件
        if body and "menu/save/menu" in path:
            try:
                import os as _os, time as _t
                _capture_dir = "/Users/mars/Vibe Coding/apaas-builder-ai/docs/captures"
                _os.makedirs(_capture_dir, exist_ok=True)
                fname = f"menu-save-captured-{int(_t.time())}.json"
                with open(f"{_capture_dir}/{fname}", "wb") as fp:
                    fp.write(body)
                logger.info(f"🎯 captured menu/save body to {fname} ({len(body)} bytes)")
            except Exception as exc:
                logger.warning(f"capture menu/save failed: {exc}")
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
            # env.tmpl.js 加 cache-bust 强制 fresh fetch（防浏览器 disk cache 命中老的 dev8 版本）
            # 这一步必须在 SSO inject 之前，避免被 inject_sso_script 跳过。
            import time as _t_cb
            cache_bust = str(int(_t_cb.time()))
            html_text = re.sub(
                r'(<script[^>]*src=["\']?[^"\'>]*?env\.tmpl\.js)(["\']?)',
                rf'\1?_cb={cache_bust}\2',
                html_text,
            )
            vuex = _build_vuex_state(token, _proxy_state.get("tenant_id", ""), _proxy_state.get("username", ""))
            content = _inject_sso_script(html_text, vuex).encode("utf-8")

        # env.tmpl.js: 把里面的绝对 URL（VUE_APP_BASE_DOMAIN 等）改成同 origin，
        # 防 trial 平台自带的 dev8 残留（早期版本）或 trial 自己的 URL 让 iframe 跨域绕开 proxy。
        # 同时 no-cache 避免浏览器把老的 dev8 版本永久缓存（实测踩坑：trial 切回后 iframe 仍用浏览器 cache 跑 dev8）。
        if "env.tmpl.js" in path:
            try:
                js_text = content.decode("utf-8", errors="replace")
                # 任何 https://apaas-*.definesys.cn/backend/ 都改成相对 /backend/ — same-origin
                js_text = re.sub(
                    r"https?://apaas-[a-zA-Z0-9._-]+\.definesys\.cn/backend/?",
                    "/backend/",
                    js_text,
                )
                content = js_text.encode("utf-8")
            except Exception as exc:
                logger.warning(f"env.tmpl.js rewrite failed: {exc}")
            resp_headers["cache-control"] = "no-cache, no-store, must-revalidate"
            resp_headers.pop("etag", None)
            resp_headers.pop("last-modified", None)

        # 缓存静态资源
        if is_static and resp.status_code == 200:
            _static_cache[target] = (content, ct)

        return Response(content=content, status_code=resp.status_code, headers=resp_headers)
    except Exception as e:
        detail = str(e) or type(e).__name__
        logger.error(f"Proxy error [{path}]: {detail}")
        return Response(
            content=_error_html("连接平台失败", f"无法访问平台：{detail}"),
            media_type="text/html",
            status_code=502,
            headers={"X-Proxy-Error": "connection-failed"},
        )


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
