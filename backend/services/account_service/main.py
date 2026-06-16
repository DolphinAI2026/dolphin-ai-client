"""account-service: 桌面账号权威。只挂认证 + 开号路由(desktop_auth.router)。
public_account_base_url 必须为空 → desktop_auth 走 authority 分支(本地校验)。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.database import init_db
from app.routes import desktop_auth
from services.account_service.admin_ui import ADMIN_UI_HTML


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()  # 建表 + 幂等迁移(含复合唯一)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="account-service", lifespan=lifespan)
    app.include_router(desktop_auth.router, prefix="/api")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "account-service"}

    @app.get("/admin-ui", response_class=HTMLResponse)
    async def admin_ui():
        return HTMLResponse(content=ADMIN_UI_HTML)

    return app


app = create_app()
