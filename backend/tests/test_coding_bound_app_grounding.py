"""bound 会话「先读应用上下文再写 SPEC」(3b 局部 tool-loop) 测试。

覆盖:
  Task1 app_id 透传(PipelineParams / CodingPipelineRequest)
  Task2 _resolve_bound_app(本地 app_id → apaas_app_id+env+name)
  Task3 _grounded_brainstorm(tool-loop: 先读应用再出 SPEC + apaas_app_id 锁定 + 回退)
  Task4 _first_turn_brainstorm 分支(解析不到 app → 不进 grounding)
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Task 1: app_id 透传 ──────────────────────────────────────────

def test_pipeline_params_carries_app_id():
    from app.coding.pipeline import PipelineParams
    p = PipelineParams(message="x", user_id=1, tenant_id=1, app_id="84799")
    assert p.app_id == "84799"


def test_coding_pipeline_request_has_app_id():
    from app.routes.harness import CodingPipelineRequest
    req = CodingPipelineRequest(message="x", app_id="84799")
    assert req.app_id == "84799"


# ── Task 2: _resolve_bound_app ──────────────────────────────────

async def test_resolve_bound_app_returns_handle():
    from app.coding import pipeline as pl
    app = MagicMock(apaas_app_id="84799", platform_env_id=3, app_name="通用B2B CRM", tenant_id=1)
    db = MagicMock()
    res = MagicMock(); res.scalar_one_or_none.return_value = app
    db.execute = AsyncMock(return_value=res)
    out = await pl._resolve_bound_app(tenant_id=1, app_id="10", db=db)
    assert out == ("84799", 3, "通用B2B CRM")


async def test_resolve_bound_app_none_when_missing_platform_fields():
    from app.coding import pipeline as pl
    app = MagicMock(apaas_app_id=None, platform_env_id=None, app_name="x", tenant_id=1)
    db = MagicMock()
    res = MagicMock(); res.scalar_one_or_none.return_value = app
    db.execute = AsyncMock(return_value=res)
    assert await pl._resolve_bound_app(tenant_id=1, app_id="10", db=db) is None


async def test_resolve_bound_app_none_when_no_app_id():
    from app.coding import pipeline as pl
    assert await pl._resolve_bound_app(tenant_id=1, app_id=None, db=MagicMock()) is None
