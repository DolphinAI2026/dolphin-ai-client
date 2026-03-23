"""Copilot 分步生成路由

GET  /applications/{app_id}/steps/status  — 获取所有步骤状态
POST /applications/{app_id}/steps/execute — 执行单个步骤
POST /applications/{app_id}/steps/reset   — 重置步骤
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, User
from app.schemas import (
    StepExecuteRequest, StepResetRequest,
    StepStatus, GenerationStatusResponse, StepExecuteResponse,
)
from app.step_executor import (
    execute_create_app, execute_create_roles_dicts,
    execute_create_model, execute_create_form,
    execute_create_workflow, execute_configure_permissions,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["生成步骤"])


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _load_state(app: Application) -> dict:
    if app.generation_state:
        state = json.loads(app.generation_state) if isinstance(app.generation_state, str) else app.generation_state
    else:
        state = {"steps_completed": [], "step_errors": {}}
        # 仅首次（无 generation_state）时兼容旧流程
        if app.apaas_app_id:
            state["steps_completed"].append("create_app")
            state["apaas_app_id"] = app.apaas_app_id
    return state


def _save_state(app: Application, state: dict):
    app.generation_state = json.dumps(state, ensure_ascii=False)


def _load_config(app: Application) -> dict:
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空，请先在对话中生成配置")
    return json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview


def _build_steps(config: dict, state: dict, apaas_app_id: str = None) -> list[StepStatus]:
    """根据 config 和 state 构建完整步骤列表。"""
    data = config.get("data", config)
    models = data.get("models", [])
    completed = set(state.get("steps_completed", []))
    errors = state.get("step_errors", {})

    # 如果平台应用已存在，create_app 步骤视为已完成
    app_created = "create_app" in completed or bool(apaas_app_id)

    steps: list[StepStatus] = []

    # 1. 创建应用
    steps.append(StepStatus(
        key="create_app", label="创建平台应用",
        status="completed" if app_created else ("error" if "create_app" in errors else "pending"),
        deps_met=True,
        error=errors.get("create_app"),
    ))

    # 2. 角色+字典
    steps.append(StepStatus(
        key="create_roles_dicts", label="创建角色+字典",
        status="completed" if "create_roles_dicts" in completed else ("error" if "create_roles_dicts" in errors else "pending"),
        deps_met=app_created,
        error=errors.get("create_roles_dicts"),
    ))

    # 3. 数据模型（每个独立）
    for idx, m in enumerate(models):
        key = f"create_model:{idx}"
        steps.append(StepStatus(
            key=key, label=f"创建模型: {m['name']}",
            status="completed" if key in completed else ("error" if key in errors else "pending"),
            deps_met=app_created,
            model_index=idx,
            error=errors.get(key),
        ))

    # 4. 表单（每个独立）
    for idx, m in enumerate(models):
        key = f"create_form:{idx}"
        model_key = f"create_model:{idx}"
        deps_ok = "create_roles_dicts" in completed and model_key in completed
        steps.append(StepStatus(
            key=key, label=f"创建表单: {m['name']}",
            status="completed" if key in completed else ("error" if key in errors else "pending"),
            deps_met=deps_ok,
            model_index=idx,
            error=errors.get(key),
        ))

    # 5. 审批流程（每个独立）
    workflows = data.get("workflows", [])
    all_forms_done = all(f"create_form:{i}" in completed for i in range(len(models)))
    for idx, wf in enumerate(workflows):
        key = f"create_workflow:{idx}"
        steps.append(StepStatus(
            key=key, label=f"创建流程: {wf.get('name', wf.get('form', f'流程{idx}'))}",
            status="completed" if key in completed else ("error" if key in errors else "pending"),
            deps_met=all_forms_done,
            error=errors.get(key),
        ))

    # 6. 权限
    all_workflows_done = all(f"create_workflow:{i}" in completed for i in range(len(workflows))) if workflows else True
    perm_deps = all_forms_done and all_workflows_done
    steps.append(StepStatus(
        key="configure_permissions", label="配置权限",
        status="completed" if "configure_permissions" in completed else ("error" if "configure_permissions" in errors else "pending"),
        deps_met=perm_deps,
        error=errors.get("configure_permissions"),
    ))

    return steps


async def _get_app(app_id: int, ctx: AuthContext, db: AsyncSession) -> Application:
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app


# ------------------------------------------------------------------
# GET /status
# ------------------------------------------------------------------

@router.get("/applications/{app_id}/steps/status", response_model=GenerationStatusResponse)
async def get_step_status(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = await _get_app(app_id, ctx, db)
    config = _load_config(app)
    state = _load_state(app)
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id
    steps = _build_steps(config, state, apaas_app_id)
    return GenerationStatusResponse(
        apaas_app_id=apaas_app_id,
        steps=steps,
    )


# ------------------------------------------------------------------
# POST /execute
# ------------------------------------------------------------------

@router.post("/applications/{app_id}/steps/execute", response_model=StepExecuteResponse)
async def execute_step(
    app_id: int,
    body: StepExecuteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.apaas_client import APaaSClient

    app = await _get_app(app_id, ctx, db)
    config = _load_config(app)
    state = _load_state(app)
    data = config.get("data", config)
    models = data.get("models", [])
    step_key = body.step
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id

    # 验证步骤存在
    steps = _build_steps(config, state, apaas_app_id)
    step_info = next((s for s in steps if s.key == step_key), None)
    if not step_info:
        raise HTTPException(status_code=400, detail=f"无效步骤: {step_key}")

    # 验证依赖
    if not step_info.deps_met:
        raise HTTPException(status_code=400, detail=f"步骤 {step_key} 的依赖尚未完成")

    # 如果已完成，跳过
    completed = set(state.get("steps_completed", []))
    if step_key in completed:
        return StepExecuteResponse(step=step_key, status="completed", result={"message": "已完成，跳过"})

    # 特殊处理：如果平台应用已存在，create_app 步骤直接跳过
    if step_key == "create_app" and apaas_app_id:
        # 确保 state 中记录了 apaas_app_id
        state["apaas_app_id"] = apaas_app_id
        state.setdefault("steps_completed", [])
        if "create_app" not in state["steps_completed"]:
            state["steps_completed"].append("create_app")
        _save_state(app, state)
        await db.commit()
        return StepExecuteResponse(step=step_key, status="completed", result={"message": "平台应用已存在，跳过创建"})

    # 获取用户的 apaas 连接信息（优先使用项目级 token 并自动刷新）
    user_result = await db.execute(select(User).where(User.id == ctx.user.id))
    user = user_result.scalar_one()

    # 尝试从项目获取 token（带自动刷新）
    from app.models import Project
    from app.routes.projects import ensure_platform_token
    project_result = await db.execute(
        select(Project).where(Project.id == app.project_id) if hasattr(app, 'project_id') and app.project_id else select(Project).where(Project.user_id == ctx.user.id).order_by(Project.updated_at.desc()).limit(1)
    )
    project = project_result.scalar_one_or_none()

    if project and project.platform_url:
        try:
            token = await ensure_platform_token(project, db)
            # 同步更新 user 表
            user.apaas_token = token
            await db.commit()
        except Exception:
            pass  # fallback to user token

    if not user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台，请在项目设置中连接")
    client = APaaSClient(
        base_url=user.apaas_base_url or (project.platform_url if project else None),
        tenant_id=user.apaas_tenant_id or (project.platform_tenant_id if project else None),
        token=user.apaas_token,
    )

    # 执行
    try:
        result = await _execute_step_impl(client, app, config, state, step_key, data, models)
        # 标记完成
        state.setdefault("steps_completed", [])
        if step_key not in state["steps_completed"]:
            state["steps_completed"].append(step_key)
        state.get("step_errors", {}).pop(step_key, None)
        _save_state(app, state)
        await db.commit()
        return StepExecuteResponse(step=step_key, status="completed", result=result)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"步骤 {step_key} 执行失败: {error_msg}", exc_info=True)

        # Token 过期时清除无效 token，让前端知道需要重新连接
        if "Token已过期" in error_msg or "401" in error_msg:
            user.apaas_token = None
            await db.commit()
            raise HTTPException(status_code=401, detail="APaaS平台Token已过期，请重新连接")

        state.setdefault("step_errors", {})[step_key] = error_msg
        _save_state(app, state)
        await db.commit()
        return StepExecuteResponse(step=step_key, status="error", error=error_msg)


async def _execute_step_impl(
    client, app: Application, config: dict, state: dict,
    step_key: str, data: dict, models: list,
) -> dict:
    """路由到具体步骤函数。"""
    apaas_app_id = state.get("apaas_app_id") or app.apaas_app_id
    suffix = state.get("suffix", "")

    if step_key == "create_app":
        result = await execute_create_app(client, app.app_name, app.app_code, app.description or "")
        state["apaas_app_id"] = result["apaas_app_id"]
        state["suffix"] = result["suffix"]
        app.apaas_app_id = result["apaas_app_id"]
        return result

    elif step_key == "create_roles_dicts":
        result = await execute_create_roles_dicts(
            client, apaas_app_id,
            data.get("roles", []), data.get("dicts", []), suffix,
        )
        state["dict_codes"] = result["dict_codes"]
        state["role_codes"] = result.get("role_codes", {})
        return result

    elif step_key.startswith("create_model:"):
        idx = int(step_key.split(":")[1])
        if idx >= len(models):
            raise ValueError(f"模型索引 {idx} 超出范围")
        result = await execute_create_model(client, apaas_app_id, models[idx], idx, suffix)
        # 合并 model_info
        state.setdefault("model_info", {})
        state["model_info"].update(result["model_info_entries"])
        return result

    elif step_key.startswith("create_form:"):
        idx = int(step_key.split(":")[1])
        if idx >= len(models):
            raise ValueError(f"表单索引 {idx} 超出范围")
        dict_codes = state.get("dict_codes", {})
        model_info = state.get("model_info", {})
        result = await execute_create_form(
            client, apaas_app_id, models[idx], idx,
            dict_codes, model_info, models,
        )
        state.setdefault("form_results", [])
        state["form_results"].append({
            "formId": result.get("formId", ""),
            "formCode": result.get("formCode", ""),
            "formName": result.get("formName", ""),
            "menuId": result.get("menuId", ""),
        })
        return result

    elif step_key.startswith("create_workflow:"):
        idx = int(step_key.split(":")[1])
        workflows = data.get("workflows", [])
        if idx >= len(workflows):
            raise ValueError(f"流程索引 {idx} 超出范围")
        form_results = state.get("form_results", [])
        role_codes = state.get("role_codes", {})
        return await execute_create_workflow(client, apaas_app_id, workflows[idx], form_results, role_codes)

    elif step_key == "configure_permissions":
        form_results = state.get("form_results", [])
        permissions = data.get("permissions", [])
        role_codes = state.get("role_codes", {})
        return await execute_configure_permissions(client, apaas_app_id, permissions, form_results, role_codes)

    else:
        raise ValueError(f"未知步骤: {step_key}")


# ------------------------------------------------------------------
# POST /reset
# ------------------------------------------------------------------

@router.post("/applications/{app_id}/steps/reset")
async def reset_step(
    app_id: int,
    body: StepResetRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = await _get_app(app_id, ctx, db)
    state = _load_state(app)

    if body.step:
        # 重置单个步骤
        completed = state.get("steps_completed", [])
        if body.step in completed:
            completed.remove(body.step)
        state.get("step_errors", {}).pop(body.step, None)
        # 重置特定步骤时清除关联数据
        if body.step == "create_app":
            app.apaas_app_id = None
            state.pop("apaas_app_id", None)
            state.pop("suffix", None)
        elif body.step == "create_roles_dicts":
            state.pop("dict_codes", None)
            state.pop("role_codes", None)
    else:
        # 重置全部
        state = {"steps_completed": [], "step_errors": {}}
        app.apaas_app_id = None

    _save_state(app, state)
    app.status = "draft"
    await db.commit()
    return {"ok": True}
