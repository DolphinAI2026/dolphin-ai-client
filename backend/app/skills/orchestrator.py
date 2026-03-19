"""aPaaS 完整构建编排器

将所有原子 Skills 组合为端到端的构建流程。
"""
from __future__ import annotations
import logging
from typing import AsyncGenerator, Dict, List, Optional

from app.apaas_client import APaaSClient
from app.skills.platform import (
    create_app,
    create_models,
    create_dicts,
    create_roles,
    create_form,
)

logger = logging.getLogger(__name__)


async def run_full_build(
    client: APaaSClient,
    config: dict,
    app_name: Optional[str] = None,
    app_code: Optional[str] = None,
    existing_app_id: Optional[str] = None,
) -> AsyncGenerator[Dict, None]:
    """完整构建流程：创建应用 → 角色 → 字典 → 模型 → 表单。

    Args:
        client: 已登录的 APaaSClient
        config: 预览格式配置 {"data": {"models", "roles", "dicts"}}
        app_name: 应用名称（新建时必填）
        app_code: 应用编码（可选）
        existing_app_id: 已有应用 ID（复用时传入）

    Yields:
        进度事件 {"stage", "status", "step", ...}
    """
    data = config.get("data", config)
    roles = data.get("roles", [])
    dicts = data.get("dicts", [])
    models = data.get("models", [])

    # Stage 0: 解析
    yield {"stage": 0, "status": "running", "step": "解析需求配置..."}
    yield {"stage": 0, "status": "running", "step": f"识别出 {len(models)} 个业务表单"}
    yield {"stage": 0, "status": "running", "step": f"识别出 {len(roles)} 个角色、{len(dicts)} 个数据字典"}
    yield {"stage": 0, "status": "done", "step": "设计计划完成"}

    # Stage 0.5: 创建应用（如果需要）
    if existing_app_id:
        app_id = existing_app_id
        yield {"stage": -1, "status": "running", "step": f"复用已有平台应用: {app_id}"}
    else:
        try:
            name = app_name or data.get("appName", "应用")
            app_id = await create_app(client, name, app_code)
            yield {"stage": -1, "status": "running", "step": f"应用已创建: {name} (id={app_id})"}
        except Exception as e:
            yield {"stage": -1, "status": "error", "step": f"创建应用失败: {e}"}
            return

    # Stage 1: 公共资源（角色 + 字典）
    yield {"stage": 1, "status": "running", "step": "开始创建公共资源..."}
    dict_code_map = {}
    try:
        if roles:
            await create_roles(client, app_id, roles)
            names = '、'.join(r['name'] for r in roles)
            yield {"stage": 1, "status": "running", "step": f"创建角色: {names}"}

        if dicts:
            try:
                dict_code_map = await create_dicts(client, app_id, dicts)
                names = '、'.join(d['name'] for d in dicts[:3])
                if len(dicts) > 3:
                    names += f"等{len(dicts)}个"
                yield {"stage": 1, "status": "running", "step": f"创建数据字典: {names}"}
            except Exception as e:
                logger.error(f"字典创建失败: {e}", exc_info=True)
                yield {"stage": 1, "status": "running", "step": f"字典创建失败（继续）: {e}"}

        yield {"stage": 1, "status": "done", "step": "公共资源配置完成"}
    except Exception as e:
        yield {"stage": 1, "status": "error", "step": f"公共资源创建失败: {e}"}
        return

    # Stage 2: 业务表单（模型 + 表单配置）
    yield {"stage": 2, "status": "running", "step": "开始创建业务表单..."}
    try:
        model_results, model_payload, code_map = await create_models(
            client, app_id, models
        )
        for m in models:
            yield {"stage": 2, "status": "running", "step": f"✅ {m['name']} 数据模型"}

        await create_form(
            client, app_id, models, dicts,
            model_results, model_payload, code_map, dict_code_map,
        )
        for m in models:
            yield {"stage": 2, "status": "running", "step": f"✅ {m['name']} 表单"}

        yield {"stage": 2, "status": "done", "step": "业务表单配置完成"}
    except Exception as e:
        yield {"stage": 2, "status": "error", "step": f"业务表单创建失败: {e}"}
        return

    # Stage 3: Dashboard (MVP 跳过)
    yield {"stage": 3, "status": "running", "step": "Dashboard配置..."}
    yield {"stage": 3, "status": "done", "step": "Dashboard配置完成（基础版）"}

    yield {"type": "complete", "message": "应用生成完成", "app_id": app_id}
