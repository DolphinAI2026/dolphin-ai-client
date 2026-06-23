"""预览真数据解析 —— serve 路由(manage_serve)与 agent 驱动预览(_run_workspace_preview)共用。

之前只有 HTTP 路由 manage_serve 会解析真数据 env，agent 在对话里跑预览走的是
mock；把解析逻辑抽到这里，两条路共用，agent 跑预览也能接已部署应用的真实平台数据。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apaas_client import APaaSClient
from app.coding.workspace import WorkspaceManager, _preview_api_base_path
from app.models import Application


async def resolve_preview_api_base(
    ws_id: str,
    tenant_id: int,
    db: AsyncSession,
    *,
    apaas_user: Optional[Any] = None,
) -> Optional[str]:
    """ws → 绑定的已部署应用 → /apaas/backend/{tenant}/{app} 真数据前缀。

    任一缺失(未绑定/未部署)→ None，调用方据此回退 mock。

    apaas_user：带 apaas_token/base_url/tenant_id 的登录用户(HTTP 路由有，传它走快路)；
    agent 路径没有登录用户 → 不传，走 platform_env_id 的 relogin 兜底。
    """
    from app.coding.apaas_tools import call_apaas_with_relogin

    app_id = WorkspaceManager().get_project_id(ws_id)
    if not app_id:
        return None
    app = (await db.execute(
        select(Application).where(
            Application.id == app_id, Application.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if not app or not app.platform_env_id or not app.apaas_app_id:
        return None

    if apaas_user is not None and getattr(apaas_user, "apaas_token", None):
        client = APaaSClient(
            base_url=apaas_user.apaas_base_url,
            tenant_id=apaas_user.apaas_tenant_id,
            token=apaas_user.apaas_token,
        )
        detail = await client.query_app_detail(str(app.apaas_app_id))
    else:
        detail = await call_apaas_with_relogin(
            app.platform_env_id, db,
            lambda c: c.query_app_detail(str(app.apaas_app_id)),
        )
    if not detail:
        return None
    return _preview_api_base_path(
        str(detail.get("tenantCode") or ""), str(detail.get("appCode") or "")
    )


def self_proxy_target() -> str:
    """后端自身回环 origin —— 预览 devServer 把 /apaas 同源代理到这里(runtime_proxy 注 token)。

    与 mcp_server._INTERNAL_BASE 同源：跟随后端 settings.port（桌面 sidecar 经
    --port/build_env 注入真实端口；本地默认 8000）。HTTP 路由能用 request.base_url，
    agent 路径没有 request，只能靠自知端口。
    """
    from app.config import settings
    return f"http://127.0.0.1:{getattr(settings, 'port', 8000)}"
