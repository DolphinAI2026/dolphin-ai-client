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
from app.models import User, Application, PlatformEnv
from app.deps import get_auth_context, AuthContext
from app.config import settings
from app.json_utils import loads_if_str
from app.error_messages import APAAS_TOKEN_EXPIRED_GENERIC, is_apaas_token_error
from app.services.config_converter import convert_analysis_to_app_config
from app.crypto import decrypt_password

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

    # 2026-05-16 夜：从 application.platform_env_id 查 platform_envs.token，不再
    # 走 user.apaas_token 老链路 — 老链路只对"用户手动在 admin 连过 apaas"的账户
    # work，ai-chat/agent 切流后 admin 账户的 apaas_token 是过期 SQL workaround 塞的。
    # 新链路：应用绑 env_id (FK)，token 从 platform_envs 读，env 刷新 token 自动跟。
    if not app.platform_env_id:
        raise HTTPException(
            status_code=400,
            detail="应用未关联平台环境（platform_env_id 空），请在 admin 给应用绑定 env"
        )
    env_result = await db.execute(
        select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id)
    )
    env_obj = env_result.scalar_one_or_none()
    if not env_obj:
        raise HTTPException(
            status_code=400,
            detail=f"应用关联的 env (id={app.platform_env_id}) 不存在，请在 admin 重连"
        )

    # 2026-05-23 token 首次自愈 (P0 C 方案 A): env.token 为空时自动 login 拿 token.
    # 跟 mcp_server._call_apaas_platform_tool 的首次自愈对齐 (commit 6cb7ce0), 解决
    # 之前 deploy_application 撞 'token 为空' hard fail 让用户去 admin 重连的体验.
    if not env_obj.token and env_obj.username and env_obj.password_enc:
        try:
            password = decrypt_password(env_obj.password_enc)
            tmp_client = APaaSClient(
                base_url=env_obj.base_url,
                tenant_id=env_obj.platform_tenant_id,
            )
            login_result = await tmp_client.login(env_obj.username, password)
            new_token = ((login_result or {}).get("token") or "").strip()
            if new_token:
                env_obj.token = new_token
                env_obj.status = "connected"
                await db.commit()
                logger.info("generate /apps/%s/generate: token 首次自愈成功 env=%s", app_id, env_obj.id)
        except Exception as exc:
            logger.warning("generate /apps/%s/generate: token 首次自愈失败 env=%s: %s", app_id, env_obj.id, exc)

    if not env_obj.token:
        raise HTTPException(
            status_code=400,
            detail=f"应用关联的 env (id={app.platform_env_id}) 没有可用 token 且自动登录失败，"
                   f"请在 admin 重连环境刷新 token"
        )

    config = loads_if_str(app.config_preview)
    client = APaaSClient(
        base_url=env_obj.base_url,
        tenant_id=env_obj.platform_tenant_id,
        token=env_obj.token,
    )
    # 记住已有的 apaas_app_id（SSE generator 需要自己的 session）
    existing_apaas_app_id = app.apaas_app_id

    # 在主 db session 中预创建 in_progress 部署记录（rollback 历史依赖这条记录）
    from .deploy_history import create_deploy_record_pre
    deploy_record = await create_deploy_record_pre(
        db, app, current_user, deploy_type="deploy", version_label=None
    )
    record_id = deploy_record.id

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.models import DeployRecord
        from .deploy_history import complete_deploy_record
        # SSE 用独立 session（外部 session 在 EventSourceResponse 返回时已被释放）
        async with AsyncSessionLocal() as session:
            # 在新 session 中重新加载 app 对象 + DeployRecord
            result = await session.execute(
                select(Application).where(Application.id == app_id)
            )
            app_obj = result.scalar_one()
            rec_result = await session.execute(
                select(DeployRecord).where(DeployRecord.id == record_id)
            )
            record = rec_result.scalar_one()

            event_log: list[dict] = []  # SSE event 累计快照（截断防爆 JSON）
            error_msg_for_record: Optional[str] = None
            success = False

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
                    # 累积 event 到 record event_log（限制 200 条防止 JSON 太大）
                    if len(event_log) < 200:
                        event_log.append(event)
                    yield {"event": "progress", "data": json.dumps(event, ensure_ascii=False)}
                    if event.get("type") == "complete":
                        app_obj.status = "completed"
                        await session.commit()
                        success = True
                    elif event.get("status") == "error":
                        app_obj.status = "failed"
                        await session.commit()
                        success = False
                        error_msg_for_record = event.get("error") or event.get("message") or "未知错误"

                yield {"event": "done", "data": json.dumps({"type": "done"})}
            except Exception as e:
                logger.error(f"应用 {app_id} 生成失败: {e}")
                app_obj.status = "failed"
                await session.commit()

                # 特殊处理401错误
                error_msg = str(e)
                if "401" in error_msg or is_apaas_token_error(error_msg) or "Unauthorized" in error_msg:
                    error_msg = APAAS_TOKEN_EXPIRED_GENERIC

                success = False
                error_msg_for_record = error_msg
                event_log.append({"type": "exception", "error": error_msg})
                yield {"event": "error", "data": json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False)}
            finally:
                # 不管 success/fail，always 落 DeployRecord 终态
                try:
                    await complete_deploy_record(
                        session, record, app_obj,
                        success=success,
                        error_message=error_msg_for_record,
                        event_log=event_log if event_log else None,
                    )
                except Exception as record_exc:
                    logger.warning(f"应用 {app_id} 部署记录写入失败: {record_exc}")

    return EventSourceResponse(event_generator())


# ─────────── 2026-05-28: 服务端后台生成（"一键到底"修复） ───────────
#
# 背景：AIChatPage 的 generate_app_from_doc 只建本地草稿、不碰 apaas（md 文档 ≠ 应用）。
# 真生成原本只能靠浏览器驱动的 SSE / step-loop —— 多 tab KeepAlive 一切走就断
# （实测 mega-erp 被切 tab 卡在 29/285）。这里把 generator_v2.run_complete_generation
# 包成 asyncio 后台任务：POST 立即返回，生成在服务端独立 session 里跑完，
# 前端轮询 GET /{app_id}/steps/status 看进度。不依赖浏览器连接 —— 切 tab / 断网都不影响。
import asyncio as _asyncio

# 持有后台任务引用，防止被 GC 提前回收（asyncio 弱引用任务的经典坑）
_BG_GEN_TASKS: set = set()


async def _resolve_env_and_client(app_obj: Application, session: AsyncSession):
    """从 app.platform_env_id 解析 env + token 首次自愈 + 建 APaaSClient。

    失败抛 ValueError（调用方转 HTTP 400 / 标 failed）。与 GET /generate 同套 token 自愈逻辑。
    """
    from app.apaas_client import APaaSClient
    if not app_obj.platform_env_id:
        raise ValueError("应用未关联平台环境（platform_env_id 空），请先在 admin 给应用绑定环境")
    env_obj = (await session.execute(
        select(PlatformEnv).where(PlatformEnv.id == app_obj.platform_env_id)
    )).scalar_one_or_none()
    if not env_obj:
        raise ValueError(f"应用关联的环境 (id={app_obj.platform_env_id}) 不存在，请在 admin 重连")
    if not env_obj.token and env_obj.username and env_obj.password_enc:
        try:
            password = decrypt_password(env_obj.password_enc)
            tmp_client = APaaSClient(base_url=env_obj.base_url, tenant_id=env_obj.platform_tenant_id)
            login_result = await tmp_client.login(env_obj.username, password)
            new_token = ((login_result or {}).get("token") or "").strip()
            if new_token:
                env_obj.token = new_token
                env_obj.status = "connected"
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("generate-run token 首次自愈失败 env=%s: %s", env_obj.id, exc)
    if not env_obj.token:
        raise ValueError(f"环境 (id={app_obj.platform_env_id}) 无可用 token 且自动登录失败，请在 admin 重连刷新")
    client = APaaSClient(
        base_url=env_obj.base_url,
        tenant_id=env_obj.platform_tenant_id,
        token=env_obj.token,
    )
    return client, env_obj


async def _run_generation_detached(app_id: int, record_id: int) -> None:
    """后台跑完整 apaas 生成 —— 独立 session，consume run_complete_generation，更新 status。

    不向任何 client 流式输出（事件只累计到 DeployRecord）。客户端断开不影响本任务。
    """
    from app.database import AsyncSessionLocal
    from app.generator_v2 import run_complete_generation
    from app.models import DeployRecord
    from .deploy_history import complete_deploy_record

    async with AsyncSessionLocal() as session:
        app_obj = (await session.execute(
            select(Application).where(Application.id == app_id)
        )).scalar_one_or_none()
        if not app_obj:
            logger.error("generate-run: app %s 不存在，后台任务终止", app_id)
            return
        record = (await session.execute(
            select(DeployRecord).where(DeployRecord.id == record_id)
        )).scalar_one_or_none()

        event_log: list[dict] = []
        success = False
        err_msg: Optional[str] = None
        try:
            client, _env = await _resolve_env_and_client(app_obj, session)
            config = loads_if_str(app_obj.config_preview)
            if not app_obj.apaas_app_id:
                apaas_result = await client.create_app(
                    app_obj.app_name, app_obj.app_code, app_obj.description or ""
                )
                app_obj.apaas_app_id = (
                    str(apaas_result) if isinstance(apaas_result, str)
                    else str(apaas_result.get("id", apaas_result.get("appId", "")))
                )
                logger.info("generate-run: app %s 平台壳创建成功 apaas_app_id=%s", app_id, app_obj.apaas_app_id)
            app_obj.status = "generating"
            await session.commit()

            async for event in run_complete_generation(client, app_obj.apaas_app_id, config):
                if len(event_log) < 200:
                    event_log.append(event)
                if event.get("type") == "complete":
                    app_obj.status = "completed"
                    await session.commit()
                    success = True
                elif event.get("status") == "error":
                    app_obj.status = "failed"
                    await session.commit()
                    err_msg = event.get("error") or event.get("message") or "未知错误"
            logger.info("generate-run: app %s 生成结束 success=%s", app_id, success)
        except Exception as exc:  # noqa: BLE001
            logger.error("generate-run: app %s 后台生成异常: %s", app_id, exc)
            err_msg = str(exc)
            if "401" in err_msg or is_apaas_token_error(err_msg) or "Unauthorized" in err_msg:
                err_msg = APAAS_TOKEN_EXPIRED_GENERIC
            event_log.append({"type": "exception", "error": err_msg})
            try:
                app_obj.status = "failed"
                await session.commit()
            except Exception:  # noqa: BLE001
                pass
        finally:
            if record is not None:
                try:
                    await complete_deploy_record(
                        session, record, app_obj,
                        success=success, error_message=err_msg,
                        event_log=event_log or None,
                    )
                except Exception as rexc:  # noqa: BLE001
                    logger.warning("generate-run: app %s DeployRecord 写入失败: %s", app_id, rexc)


@router.post("/{app_id}/generate-run")
async def generate_application_async(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: AuthContext = Depends(get_auth_context),
):
    """一键到底：服务端后台触发真 apaas 生成（创建模型/表单/角色），**立即返回**。

    与 GET /{app_id}/generate（浏览器 SSE）的区别：本接口把生成丢进 asyncio 后台任务，
    不依赖客户端连接 —— 用户切 tab / 关页面 / 断网，生成照样在服务端跑完。
    进度查询走 GET /{app_id}/steps/status（按 apaas 真实对象重建）。

    幂等：已在生成中 → already_running；已完成且有 apaas_app_id → already_done。
    """
    if auth.tenant_id is None:
        raise HTTPException(status_code=403, detail="平台管理员无法生成应用")
    app = (await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == auth.tenant_id,
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空，无法生成")
    if app.status == "generating":
        return {"started": False, "already_running": True, "app_id": app_id, "status": "generating"}
    if app.status == "completed" and app.apaas_app_id:
        return {"started": False, "already_done": True, "app_id": app_id, "apaas_app_id": app.apaas_app_id}

    # 提前校验 env/token 可解析（fail fast，给用户明确错误而非后台静默失败）
    try:
        await _resolve_env_and_client(app, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    from .deploy_history import create_deploy_record_pre
    rec = await create_deploy_record_pre(db, app, auth.user, deploy_type="deploy", version_label=None)
    record_id = rec.id
    await db.commit()

    task = _asyncio.create_task(_run_generation_detached(app_id, record_id))
    _BG_GEN_TASKS.add(task)
    task.add_done_callback(_BG_GEN_TASKS.discard)
    logger.info("generate-run: app %s 后台生成已启动 (deploy_record=%s)", app_id, record_id)
    return {"started": True, "app_id": app_id, "status": "generating"}


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
