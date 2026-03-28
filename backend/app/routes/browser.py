"""
浏览器预览 API — 提供 Playwright headless Chromium 的 REST 接口。
所有 action 端点直接返回 JPEG 截图。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query, Response
from pydantic import BaseModel

from app.coding.browser_service import BrowserService
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding/workspace/{ws_id}/browser", tags=["browser"])


# ---------- Auth ----------

def _verify_token(ws_id: str, token: str):
    """复用 IDE access token 验证"""
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="无效或已过期的访问令牌")
    if payload.get("type") != "ide_access" or payload.get("ws") != ws_id:
        raise HTTPException(status_code=403, detail="访问令牌与当前工作区不匹配")
    return payload


def _get_token(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> str:
    """从 Header 或 Query 参数中提取 token"""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    if token:
        return token
    raise HTTPException(status_code=401, detail="缺少访问令牌")


def _jpeg_response(data: bytes) -> Response:
    return Response(content=data, media_type="image/jpeg")


# ---------- Request Models ----------

class LaunchRequest(BaseModel):
    url: Optional[str] = None

class NavigateRequest(BaseModel):
    url: str

class ClickRequest(BaseModel):
    x: int
    y: int

class DoubleClickRequest(BaseModel):
    x: int
    y: int

class TypeRequest(BaseModel):
    text: str

class PressRequest(BaseModel):
    key: str  # e.g. "Enter", "Tab", "Backspace", "Escape"

class ScrollRequest(BaseModel):
    x: int
    y: int
    delta_x: int = 0
    delta_y: int = -300  # 负数向下滚


class InjectRequest(BaseModel):
    script_url: str
    css_url: Optional[str] = None


# ---------- Endpoints ----------

@router.post("/launch")
async def launch_browser(
    ws_id: str,
    req: LaunchRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """启动浏览器会话，可选导航到初始 URL"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    try:
        screenshot = await service.launch_session(ws_id, req.url)
        return _jpeg_response(screenshot)
    except Exception as e:
        logger.error(f"Failed to launch browser for {ws_id}: {e}")
        raise HTTPException(status_code=500, detail=f"启动浏览器失败: {str(e)}")


@router.post("/navigate")
async def navigate(
    ws_id: str,
    req: NavigateRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """导航到指定 URL"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在，请先启动")
    screenshot = await session.navigate(req.url)
    return _jpeg_response(screenshot)


@router.post("/click")
async def click(
    ws_id: str,
    req: ClickRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """在指定坐标点击"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.click(req.x, req.y)
    return _jpeg_response(screenshot)


@router.post("/dblclick")
async def dblclick(
    ws_id: str,
    req: DoubleClickRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """双击指定坐标"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.double_click(req.x, req.y)
    return _jpeg_response(screenshot)


@router.post("/type")
async def type_text(
    ws_id: str,
    req: TypeRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """在当前焦点输入文字"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.type_text(req.text)
    return _jpeg_response(screenshot)


@router.post("/press")
async def press_key(
    ws_id: str,
    req: PressRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """按下指定按键"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.press_key(req.key)
    return _jpeg_response(screenshot)


@router.post("/scroll")
async def scroll(
    ws_id: str,
    req: ScrollRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """在指定位置滚动"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.scroll(req.x, req.y, req.delta_x, req.delta_y)
    return _jpeg_response(screenshot)


@router.get("/screenshot")
async def screenshot(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """获取当前截图"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    data = await session.screenshot()
    return _jpeg_response(data)


@router.post("/back")
async def go_back(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """浏览器后退"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.go_back()
    return _jpeg_response(screenshot)


@router.post("/forward")
async def go_forward(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """浏览器前进"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.go_forward()
    return _jpeg_response(screenshot)


@router.post("/refresh")
async def refresh(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """刷新页面"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.reload()
    return _jpeg_response(screenshot)


@router.post("/inject")
async def inject_component(
    ws_id: str,
    req: InjectRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """注入自开发组件 JS/CSS"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    screenshot = await session.inject_script(req.script_url, req.css_url)
    return _jpeg_response(screenshot)


@router.post("/auto-inject")
async def auto_inject_component(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """自动注入当前 workspace 的组件（读取 apaas.json + 查找 serve 端口）"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    session = service.get_session(ws_id)
    if not session:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")

    from app.coding.workspace import WorkspaceManager
    import json

    wm = WorkspaceManager()

    # 1. 检查 serve 是否运行
    serve_info = wm.is_serve_running(ws_id)
    if not serve_info.get("running"):
        # 自动启动 serve
        serve_result = await wm.start_serve(ws_id)
        if serve_result.get("status") == "error":
            raise HTTPException(status_code=500, detail=f"启动 serve 失败: {serve_result.get('message')}")
        serve_port = serve_result.get("port")
    else:
        serve_port = serve_info.get("port")

    # 2. 读取 apaas.json 获取组件名
    ws_path = wm.get_workspace_path(ws_id)
    apaas_json_path = ws_path / "src" / "apaas.json"
    if not apaas_json_path.exists():
        raise HTTPException(status_code=404, detail="找不到 src/apaas.json")

    apaas_config = json.loads(apaas_json_path.read_text())
    output_name = apaas_config.get("outputName", ws_id)

    # 3. 构造 JS/CSS URL 并注入
    script_url = f"https://localhost:{serve_port}/{output_name}.umd.js"
    css_url = f"https://localhost:{serve_port}/{output_name}.css"

    screenshot = await session.inject_script(script_url, css_url)
    return _jpeg_response(screenshot)


@router.get("/serve-info")
async def serve_info(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """获取 workspace 的 serve 状态和组件信息"""
    _verify_token(ws_id, _get_token(authorization, token))

    from app.coding.workspace import WorkspaceManager
    import json

    wm = WorkspaceManager()
    serve_status = wm.is_serve_running(ws_id)

    # 读取组件名
    ws_path = wm.get_workspace_path(ws_id)
    output_name = ws_id
    try:
        apaas_config = json.loads((ws_path / "src" / "apaas.json").read_text())
        output_name = apaas_config.get("outputName", ws_id)
    except Exception:
        pass

    return {
        "serve_running": serve_status.get("running", False),
        "serve_port": serve_status.get("port"),
        "output_name": output_name,
    }


@router.post("/close")
async def close_browser(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """关闭浏览器会话"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    await service.close_session(ws_id)
    return {"status": "closed"}


@router.get("/status")
async def session_status(
    ws_id: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """获取浏览器会话状态"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    return service.get_status(ws_id)
