"""aPaaS 完整构建编排器

将所有原子 Skills 组合为端到端的构建流程。
流程：创建应用 → 角色 → 字典 → 模型 → 表单 → 权限 → 发布
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
    create_permissions,
    deploy_app,
)

logger = logging.getLogger(__name__)


async def run_full_build(
    client: APaaSClient,
    config: dict,
    app_name: Optional[str] = None,
    app_code: Optional[str] = None,
    existing_app_id: Optional[str] = None,
) -> AsyncGenerator[Dict, None]:
    """完整构建流程：创建应用 → 角色 → 字典 → 模型 → 表单 → 权限 → 发布。

    Args:
        client: 已登录的 APaaSClient
        config: 预览格式配置 {"data": {"models", "roles", "dicts", "permissions"}}
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
    permissions = data.get("permissions", [])

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
    role_codes = {}
    try:
        if roles:
            await create_roles(client, app_id, roles)
            names = '、'.join(r['name'] for r in roles)
            yield {"stage": 1, "status": "running", "step": f"创建角色: {names}"}
            # 记录角色编码供权限配置使用
            for r in roles:
                role_codes[r.get("code", r["name"])] = r

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
    form_results = []
    try:
        model_results, model_payload, code_map = await create_models(
            client, app_id, models
        )
        for m in models:
            yield {"stage": 2, "status": "running", "step": f"✅ {m['name']} 数据模型"}

        form_results = await create_form(
            client, app_id, models, dicts,
            model_results, model_payload, code_map, dict_code_map,
        )
        for m in models:
            yield {"stage": 2, "status": "running", "step": f"✅ {m['name']} 表单"}

        yield {"stage": 2, "status": "done", "step": "业务表单配置完成"}
    except Exception as e:
        yield {"stage": 2, "status": "error", "step": f"业务表单创建失败: {e}"}
        return

    # Stage 3: 权限配置
    yield {"stage": 3, "status": "running", "step": "开始配置权限..."}
    try:
        # form_results 可能是 API 返回的原始数据，需要适配
        adapted_form_results = _adapt_form_results(form_results, models, code_map)
        perm_result = await create_permissions(
            client, app_id, permissions, adapted_form_results, role_codes,
        )
        count = perm_result.get("permissions_count", 0)
        yield {"stage": 3, "status": "done", "step": f"权限配置完成（{count} 个表单）"}
    except Exception as e:
        logger.error(f"权限配置失败: {e}", exc_info=True)
        yield {"stage": 3, "status": "done", "step": f"权限配置跳过: {e}"}

    # Stage 4: 发布应用
    yield {"stage": 4, "status": "running", "step": "正在发布应用..."}
    try:
        deploy_result = await deploy_app(client, app_id)
        version = deploy_result.get("version", "")
        yield {"stage": 4, "status": "done", "step": f"应用发布成功 (v{version})"}
    except Exception as e:
        logger.error(f"应用发布失败: {e}", exc_info=True)
        yield {"stage": 4, "status": "done", "step": f"应用发布跳过: {e}"}

    yield {"type": "complete", "message": "应用生成完成", "app_id": app_id}


def _adapt_form_results(
    form_results: list,
    models: List[Dict],
    code_map: Dict[str, str],
) -> List[Dict]:
    """将 create_form 返回的结果适配为权限配置所需的格式。

    权限配置需要 formCode/formId/formName，但 create_form_config API
    返回的格式可能不一致，这里做兼容处理。
    """
    if not form_results:
        return []

    adapted = []
    if isinstance(form_results, list):
        for i, fr in enumerate(form_results):
            if isinstance(fr, dict) and fr.get("formId"):
                adapted.append(fr)
            elif isinstance(fr, dict):
                # 尝试从返回数据中提取
                adapted.append({
                    "formId": fr.get("formId", fr.get("id", "")),
                    "formCode": fr.get("formCode", ""),
                    "formName": fr.get("formName", models[i]["name"] if i < len(models) else ""),
                })
    return adapted
