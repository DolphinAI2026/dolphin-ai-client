"""Recover standalone Web Console sessions from an authenticated Builder session."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.builder_ai_management import exchange_web_console_session
from app.deps import AuthContext, get_auth_context

router = APIRouter()


class WebConsoleSessionResponse(BaseModel):
    access_token: str
    tenant_id: str


@router.post("/web-console/session", response_model=WebConsoleSessionResponse)
async def create_web_console_session(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> WebConsoleSessionResponse:
    user = ctx.user
    if user.account_source != "apaas":
        raise HTTPException(status_code=403, detail="当前账号不能创建 standalone 管理会话")

    apaas_token = str(user.apaas_token or "").strip()
    apaas_tenant_id = str(ctx.apaas_tenant_id or user.apaas_tenant_id or "").strip()
    apaas_user_id = str(ctx.apaas_user_id or user.apaas_user_id or user.id or "").strip()
    if not apaas_token or not apaas_tenant_id:
        raise HTTPException(status_code=401, detail="aPaaS 登录态已失效，请重新登录")

    session = await exchange_web_console_session(
        user_id=apaas_user_id,
        username=user.username,
        apaas_access_token=apaas_token,
        apaas_tenant_id=apaas_tenant_id,
    )
    if not session:
        raise HTTPException(status_code=503, detail="Builder AI 管理服务未启用")
    return WebConsoleSessionResponse(
        access_token=session["access_token"],
        tenant_id=session["tenant_id"],
    )
