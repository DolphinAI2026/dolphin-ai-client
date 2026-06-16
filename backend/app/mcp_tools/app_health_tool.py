from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


def register(mcp, *_args, **_kwargs) -> dict:
    """注册 compute_app_health 工具。

    与其它读工具一致用 (env_id, apaas_app_id) 入参；自开 DB 会话给
    call_apaas_with_relogin 加载 env 凭据。只读、不落库（落库由 REST 接口做）。
    """

    @mcp.tool()
    async def compute_app_health(env_id: int, apaas_app_id: str) -> dict:
        """对指定应用做确定性健康体检，返回结构化记分卡（总分/各维度分/findings）。

        供 agent 在确定指标上叙述；分数与 findings 由规则引擎产出，勿自行编造。
        """
        if not str(apaas_app_id or "").strip():
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
        from app.database import AsyncSessionLocal
        from app.services.app_health.service import run_app_health

        app = SimpleNamespace(id=0, tenant_id=0, apaas_app_id=str(apaas_app_id).strip())
        try:
            async with AsyncSessionLocal() as db:
                report = await run_app_health(app, env_id, db, as_of=datetime.utcnow(), persist=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error_code": "HEALTH_FAILED", "message": str(exc)[:300]}
        return {"ok": True, **report}

    return {"compute_app_health": compute_app_health}
