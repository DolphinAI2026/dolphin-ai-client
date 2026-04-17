"""应用生成 & 配置转换相关路由。

2 条：
  GET   /{app_id}/generate          — SSE 流式生成 aPaaS 应用（调 generator_v2.run_complete_generation）
  POST  /convert-config             — 需求分析结果 → AppConfig 转换（纯 Python）
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from jose import JWTError, jwt

from app.database import get_db
from app.models import User, Application
from app.deps import get_auth_context, AuthContext
from app.config import settings
from app.json_utils import loads_if_str
from app.error_messages import APAAS_TOKEN_EXPIRED_GENERIC, is_apaas_token_error
from app.services.config_converter import convert_analysis_to_app_config

router = APIRouter()
logger = logging.getLogger(__name__)


class ConvertConfigRequest(BaseModel):
    doc_result: dict


@router.get("/{app_id}/generate")
async def generate_application(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(None),
):
    from app.apaas_client import APaaSClient
    from app.generator_v2 import run_complete_generation

    # SSE不能设置Authorization header，通过query param传token
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证token")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", 0))
        tenant_id = payload.get("tid")
        if tenant_id is None:
            raise HTTPException(status_code=403, detail="平台管理员无法生成应用")
        tenant_id = int(tenant_id)
    except (JWTError, Exception):
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户不存在")

    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空")
    if not current_user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台，请先在设置中连接APaaS平台")

    config = loads_if_str(app.config_preview)
    client = APaaSClient(base_url=current_user.apaas_base_url, tenant_id=current_user.apaas_tenant_id, token=current_user.apaas_token)
    # 记住已有的 apaas_app_id（SSE generator 需要自己的 session）
    existing_apaas_app_id = app.apaas_app_id

    async def event_generator():
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            # 在新 session 中重新加载 app 对象
            result = await session.execute(
                select(Application).where(Application.id == app_id)
            )
            app_obj = result.scalar_one()

            try:
                if not existing_apaas_app_id:
                    apaas_result = await client.create_app(app_obj.app_name, app_obj.app_code, app_obj.description or "")
                    apaas_app_id = str(apaas_result) if isinstance(apaas_result, str) else str(apaas_result.get("id", apaas_result.get("appId", "")))
                    app_obj.apaas_app_id = apaas_app_id
                    app_obj.status = "generating"
                    await session.commit()
                    logger.info(f"应用 {app_id} 平台创建成功, apaas_app_id={apaas_app_id}")
                    yield {"event": "progress", "data": json.dumps({"stage": -1, "status": "running", "step": f"应用已创建: {app_obj.app_name}"}, ensure_ascii=False)}
                else:
                    apaas_app_id = existing_apaas_app_id
                    app_obj.status = "generating"
                    await session.commit()
                    yield {"event": "progress", "data": json.dumps({"stage": -1, "status": "running", "step": f"复用已有平台应用: {apaas_app_id}"}, ensure_ascii=False)}

                async for event in run_complete_generation(client, apaas_app_id, config):
                    yield {"event": "progress", "data": json.dumps(event, ensure_ascii=False)}
                    if event.get("type") == "complete":
                        app_obj.status = "completed"
                        await session.commit()
                    elif event.get("status") == "error":
                        app_obj.status = "failed"
                        await session.commit()

                yield {"event": "done", "data": json.dumps({"type": "done"})}
            except Exception as e:
                logger.error(f"应用 {app_id} 生成失败: {e}")
                app_obj.status = "failed"
                await session.commit()

                # 特殊处理401错误
                error_msg = str(e)
                if "401" in error_msg or is_apaas_token_error(error_msg) or "Unauthorized" in error_msg:
                    error_msg = APAAS_TOKEN_EXPIRED_GENERIC

                yield {"event": "error", "data": json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/convert-config")
async def convert_config(
    body: ConvertConfigRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Convert a requirements AnalysisResult JSON directly to AppConfig format.
    Pure Python transformation — no LLM calls, no markdown roundtrip.
    """
    try:
        config = convert_analysis_to_app_config(body.doc_result)
        return {"config": config}
    except Exception as e:
        logger.error(f"Config conversion failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"配置转换失败: {str(e)}")
