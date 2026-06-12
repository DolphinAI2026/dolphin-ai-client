"""aPaaS 平台会话 / token 自愈 — 全仓共享设施（single source of truth）。

约定（铁律，写新 apaas 调用前必读）：
    routes 层禁止裸 `APaaSClient()` 调读接口 —— 一律走 `call_apaas_with_relogin`。
    aPaaS token 会过期 → 读接口撞 401。本模块用 env 账号密码自动重登 + 重试一次，
    让 token 过期对用户无感。绕过它直连 = 用户隔几小时就撞一次 401 报错。

为什么 401 重试一次是安全的（读 + 大多数写都安全）：
    401 发生在认证层（请求还没到达业务逻辑），即「这次调用根本没执行」。
    重登拿新 token 后重试一次，不会产生重复副作用。
    （唯一不安全的是「请求已执行但响应链路把 token 错误冒泡成 401」这种罕见情形，
     实践中 apaas 不会这么干 —— 业务错有独立 error_code，见 mcp error_messages。）

历史：本模块的三个函数原本住在 `app/coding/apaas_tools.py`（AI Coding 工具层），
    但全仓 17 个文件 53 处直连 APaaSClient 只有约 22 处走自愈，平行实现散落多处
    （如 incremental_update._try_refresh_env_token，且 decrypt 用错 base64）。
    2026-06-12 抽到这里做共享设施，apaas_tools 留 re-export 保既有调用零改动。

三个函数：
    _get_apaas_client(env_id, db)        按 platform_env_id 拿登录态 APaaSClient
    _relogin_apaas_env(env_id, db)       用 env 账密重登、刷新并持久化 token（返 bool）
    call_apaas_with_relogin(env_id, db, fn)  跑 fn(client)，撞 401 自动重登重试一次
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _get_apaas_client(platform_env_id: int, db: AsyncSession):
    """按 platform_env_id 拿登录态的 APaaSClient。

    依赖 platform_envs 表已配齐 base_url + platform_tenant_id + token。
    """
    from app.models import PlatformEnv
    from app.apaas_client import APaaSClient
    from sqlalchemy import select

    row = await db.execute(select(PlatformEnv).where(PlatformEnv.id == platform_env_id))
    env = row.scalar_one_or_none()
    if env is None:
        raise ValueError(
            f"应用绑定的平台环境(platform_env_id={platform_env_id})不存在或已被删除，"
            f"请在「平台环境」中重新连接该环境后重试"
        )
    if not env.token:
        raise ValueError(
            f"platform_env_id={platform_env_id} 未登录 aPaaS（token 为空），"
            f"请先在「平台管理 → aPaaS 租户」点『刷新租户』，或在「平台环境」为该环境配置账号密码"
        )
    return APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id or "default",
        token=env.token,
    )


async def _relogin_apaas_env(platform_env_id: int, db: AsyncSession) -> bool:
    """用 env 账号密码重新登录 aPaaS，刷新并持久化 token。成功返 True。

    aPaaS token 会过期 → 读接口撞 401。有 username/password_enc 的 env 自动重登，
    用户无感。无凭据则返 False（调用方按原 401 处理）。
    """
    from app.models import PlatformEnv
    from app.apaas_client import APaaSClient
    from app.crypto import decrypt_password
    from sqlalchemy import select

    env = (
        await db.execute(select(PlatformEnv).where(PlatformEnv.id == platform_env_id))
    ).scalar_one_or_none()
    if env is None or not env.username or not env.password_enc:
        return False
    try:
        password = decrypt_password(env.password_enc)
        tmp = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id or "default")
        res = await tmp.login(env.username, password)
        new_token = ((res or {}).get("token") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("apaas relogin env=%s 失败: %s", platform_env_id, exc)
        return False
    if not new_token:
        return False
    env.token = new_token
    env.status = "connected"
    await db.commit()
    logger.info("apaas relogin env=%s 成功，token 已刷新", platform_env_id)
    return True


async def call_apaas_with_relogin(platform_env_id: int, db: AsyncSession, fn):
    """跑一次 aPaaS 调用；撞 token 失效(401) → 自动重登 + 重试一次。

    fn: async callable(client) -> result。让 token 过期对用户无感（复用 env 账号密码）。

    全仓 apaas 读接口的统一入口 —— 别裸 APaaSClient() 调读接口绕过它。
    """
    from app.error_messages import is_apaas_token_error

    async def _get_client_with_empty_token_relogin():
        try:
            return await _get_apaas_client(platform_env_id, db)
        except Exception as exc:  # noqa: BLE001
            if not is_apaas_token_error(str(exc)):
                raise
            logger.info("apaas env=%s token 不可用，尝试重登刷新", platform_env_id)
            if not await _relogin_apaas_env(platform_env_id, db):
                raise
            return await _get_apaas_client(platform_env_id, db)

    client = await _get_client_with_empty_token_relogin()
    try:
        return await fn(client)
    except Exception as exc:  # noqa: BLE001
        if not is_apaas_token_error(str(exc)):
            raise
        logger.info("apaas 调用撞 token 失效，尝试重登重试 env=%s", platform_env_id)
        if not await _relogin_apaas_env(platform_env_id, db):
            raise
        client2 = await _get_client_with_empty_token_relogin()
        return await fn(client2)
