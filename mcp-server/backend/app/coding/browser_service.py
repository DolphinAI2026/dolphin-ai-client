"""
Playwright 浏览器服务 — 管理 headless Chromium 实例，提供截图+交互 API。
每个 workspace 一个独立的 BrowserContext（cookie/存储隔离）。
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

# 配置常量
MAX_SESSIONS = 5
IDLE_TIMEOUT_SECONDS = 30 * 60  # 30 分钟无操作自动关闭
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
JPEG_QUALITY = 60


class BrowserSession:
    """单个 workspace 的浏览器会话"""

    def __init__(self, ws_id: str, context: BrowserContext, page: Page):
        self.ws_id = ws_id
        self.context = context
        self.page = page
        self.last_active = time.time()
        self.created_at = time.time()

    def touch(self):
        self.last_active = time.time()

    @property
    def is_idle(self) -> bool:
        return (time.time() - self.last_active) > IDLE_TIMEOUT_SECONDS

    async def screenshot(self) -> bytes:
        """返回当前页面的 JPEG 截图"""
        self.touch()
        return await self.page.screenshot(type="jpeg", quality=JPEG_QUALITY)

    async def navigate(self, url: str) -> bytes:
        """导航到指定 URL，返回截图（即使导航出错也尝试返回截图）"""
        self.touch()
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            # 即使出错（如重定向过多），也尝试截图当前状态
            logger.warning(f"Navigation error (still taking screenshot): {e}")
        await self.page.wait_for_timeout(1000)
        return await self.screenshot()

    async def click(self, x: int, y: int) -> bytes:
        """在指定坐标点击，返回截图"""
        self.touch()
        await self.page.mouse.click(x, y)
        # 等待可能的导航或 DOM 更新
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        await self.page.wait_for_timeout(200)
        return await self.screenshot()

    async def double_click(self, x: int, y: int) -> bytes:
        """双击，返回截图"""
        self.touch()
        await self.page.mouse.dblclick(x, y)
        await self.page.wait_for_timeout(500)
        return await self.screenshot()

    async def type_text(self, text: str) -> bytes:
        """在当前焦点输入文字，返回截图"""
        self.touch()
        await self.page.keyboard.type(text, delay=20)
        await self.page.wait_for_timeout(100)
        return await self.screenshot()

    async def press_key(self, key: str) -> bytes:
        """按下指定按键（如 Enter, Tab, Backspace），返回截图"""
        self.touch()
        await self.page.keyboard.press(key)
        await self.page.wait_for_timeout(100)
        return await self.screenshot()

    async def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = -300) -> bytes:
        """在指定位置滚动，返回截图"""
        self.touch()
        await self.page.mouse.move(x, y)
        await self.page.mouse.wheel(delta_x, delta_y)
        await self.page.wait_for_timeout(200)
        return await self.screenshot()

    async def go_back(self) -> bytes:
        """后退，返回截图"""
        self.touch()
        await self.page.go_back(timeout=10000)
        await self.page.wait_for_timeout(1000)
        return await self.screenshot()

    async def go_forward(self) -> bytes:
        """前进，返回截图"""
        self.touch()
        await self.page.go_forward(timeout=10000)
        await self.page.wait_for_timeout(1000)
        return await self.screenshot()

    async def reload(self) -> bytes:
        """刷新页面，返回截图"""
        self.touch()
        await self.page.reload(timeout=30000)
        await self.page.wait_for_timeout(1000)
        return await self.screenshot()

    async def get_url(self) -> str:
        """获取当前页面 URL"""
        return self.page.url

    async def inject_script(self, script_url: str, css_url: Optional[str] = None) -> bytes:
        """注入外部 JS 和 CSS，返回截图"""
        self.touch()
        js = f"""
        (function() {{
            var existing = document.querySelector('script[data-vibe-inject]');
            if (existing) existing.remove();
            var s = document.createElement('script');
            s.src = '{script_url}';
            s.setAttribute('data-vibe-inject', 'true');
            document.head.appendChild(s);
        }})()
        """
        if css_url:
            js += f"""
            ;(function() {{
                var existingCss = document.querySelector('link[data-vibe-inject]');
                if (existingCss) existingCss.remove();
                var l = document.createElement('link');
                l.rel = 'stylesheet';
                l.href = '{css_url}';
                l.setAttribute('data-vibe-inject', 'true');
                document.head.appendChild(l);
            }})()
            """
        await self.page.evaluate(js)
        await self.page.wait_for_timeout(2000)
        return await self.screenshot()

    async def close(self):
        """关闭会话"""
        try:
            await self.context.close()
        except Exception as e:
            logger.warning(f"Error closing browser context for {self.ws_id}: {e}")


class BrowserService:
    """浏览器服务单例 — 管理共享的 Playwright Chromium 实例"""

    _instance: Optional["BrowserService"] = None

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._sessions: dict[str, BrowserSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "BrowserService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self):
        """启动 Playwright 和 Chromium"""
        if self._browser:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--ignore-certificate-errors",
            ],
        )
        # 启动空闲清理定时器
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("BrowserService started with headless Chromium")

    async def stop(self):
        """关闭所有会话和浏览器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None

        for ws_id in list(self._sessions.keys()):
            await self.close_session(ws_id)

        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("BrowserService stopped")

    async def _cleanup_loop(self):
        """定期清理空闲会话"""
        while True:
            try:
                await asyncio.sleep(60)
                idle_sessions = [
                    ws_id for ws_id, session in self._sessions.items()
                    if session.is_idle
                ]
                for ws_id in idle_sessions:
                    logger.info(f"Closing idle browser session: {ws_id}")
                    await self.close_session(ws_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Browser cleanup error: {e}")

    async def launch_session(self, ws_id: str, url: Optional[str] = None) -> bytes:
        """为 workspace 创建浏览器会话，返回初始截图"""
        if not self._browser:
            await self.start()

        # 如果已有会话，先关闭
        if ws_id in self._sessions:
            await self.close_session(ws_id)

        # 检查并发限制
        if len(self._sessions) >= MAX_SESSIONS:
            # 关闭最旧的空闲会话
            oldest = min(self._sessions.values(), key=lambda s: s.last_active)
            logger.info(f"Max sessions reached, closing oldest: {oldest.ws_id}")
            await self.close_session(oldest.ws_id)

        context = await self._browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            ignore_https_errors=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = await context.new_page()

        session = BrowserSession(ws_id, context, page)
        self._sessions[ws_id] = session

        if url:
            return await session.navigate(url)
        else:
            return await session.screenshot()

    def get_session(self, ws_id: str) -> Optional[BrowserSession]:
        """获取现有会话"""
        session = self._sessions.get(ws_id)
        if session:
            session.touch()
        return session

    async def close_session(self, ws_id: str):
        """关闭指定会话"""
        session = self._sessions.pop(ws_id, None)
        if session:
            await session.close()
            logger.info(f"Browser session closed: {ws_id}")

    def get_status(self, ws_id: str) -> dict:
        """获取会话状态"""
        session = self._sessions.get(ws_id)
        if not session:
            return {"active": False}
        return {
            "active": True,
            "url": session.page.url,
            "created_at": session.created_at,
            "last_active": session.last_active,
            "idle_seconds": int(time.time() - session.last_active),
        }

    def list_sessions(self) -> list[dict]:
        """列出所有活跃会话"""
        return [
            {"ws_id": ws_id, **self.get_status(ws_id)}
            for ws_id in self._sessions
        ]
