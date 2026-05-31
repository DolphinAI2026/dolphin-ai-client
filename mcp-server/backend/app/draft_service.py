"""Draft 业务编排层。

承接 MCP 工具 (save_design_draft / patch_design_draft / promote_draft_to_app /
apply_draft_to_live_app / get_draft_summary) 的真实业务逻辑，把现有的解析/校验/部署
能力组合起来，对 agent 隐藏中间细节。

约定：
- 所有函数返回 dict，成功带 ok=True + 业务字段，失败用 draft_errors.err_response。
- 不直接抛异常给 agent（除非是真正的程序 bug），平台错误一律转 structured error。
- draft 不可变：patch 总是产新行，原 draft 标 superseded。
"""
from __future__ import annotations
import json
import logging
import secrets
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.design_draft import DesignDraft
from app.draft_errors import (
    ErrorCode,
    LEVEL_FREEFORM,
    LEVEL_PARTIAL,
    LEVEL_NOT_FOUND,
    LEVEL_INVALID_PATCH,
    LEVEL_PLATFORM_ERROR,
    StructuredError,
    err_response,
    single_err,
)

logger = logging.getLogger(__name__)


# ───────────────────────────── 工具函数 ─────────────────────────────

def _new_draft_id() -> str:
    """生成 d_xxxxxx 形式的 draft id。"""
    return f"d_{secrets.token_hex(6)}"


def _build_preview_url(draft_id: str) -> str:
    """构造预览页 URL。base 应指向 /mcp-server/api（线上）或 http://localhost:8004/api（本地）。"""
    base = getattr(settings, "preview_base_url", "") or "http://localhost:8004/api"
    return f"{base}/design-preview/{draft_id}"


def _build_summary(spec: dict) -> str:
    """从 spec_json 生成一行摘要："销售管理｜模型 5｜表单 5｜审批流 1｜角色 4"。"""
    app_info = spec.get("app_info") if isinstance(spec.get("app_info"), dict) else {}
    app_name = (
        spec.get("appName")
        or spec.get("app_name")
        or app_info.get("app_name")
        or app_info.get("name")
        or "未命名"
    )
    n_models = len(spec.get("models") or spec.get("dataModels") or [])
    n_forms = len(spec.get("forms") or [])
    n_flows = len(spec.get("flows") or spec.get("workflows") or spec.get("processes") or [])
    n_roles = len(spec.get("roles") or [])
    n_dicts = len(spec.get("dicts") or [])
    return f"{app_name}｜模型 {n_models}｜表单 {n_forms}｜审批流 {n_flows}｜角色 {n_roles}｜字典 {n_dicts}"


def _to_dict(draft: DesignDraft, *, with_summary_only: bool = True) -> dict:
    """draft ORM → 返回给 agent / API 的 dict。默认不返回 md_content。"""
    out = {
        "draft_id": draft.id,
        "status": draft.status,
        "level": draft.level,
        "summary": draft.summary,
        "preview_url": _build_preview_url(draft.id),
        "parent_draft_id": draft.parent_draft_id,
        "app_id": draft.app_id,
        "apaas_app_id": draft.apaas_app_id,
        "env": draft.env,
        "admin_url": draft.admin_url,
        "web_url": draft.web_url,
        "summary_of_change": draft.summary_of_change,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }
    if not with_summary_only:
        out["md_content"] = draft.md_content
        out["spec_json"] = json.loads(draft.spec_json) if draft.spec_json else None
    return out


# ───────────────────────────── save_design_draft ─────────────────────────────

async def save_design_draft(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    md_content: str,
    parent_app_id: Optional[int] = None,
) -> dict:
    """保存设计文档。内部完成校验 + 解析 + 落库。"""
    from app.doc_standard_detector import detect
    from app.doc_pipeline import DocNotStandardError, parse_document

    # ─── Step 1: 校验 ─────────────────────────────────────────────
    detection = detect(md_content)
    level = detection.get("level", "freeform")

    if level == "freeform":
        return single_err(
            LEVEL_FREEFORM,
            ErrorCode.MISSING_SECTION,
            "文档不符合 Builder 标准格式，无法解析",
            fix="请按 [应用信息/角色/字典/模型/表单/流程配置/权限] 标准模板重新整理后再 save",
            warnings=detection.get("warnings", []),
            detected=detection,
        )

    # ─── Step 2: 解析 ─────────────────────────────────────────────
    try:
        parse_result = await parse_document(md_content)
        spec_data = parse_result.get("data", {}) if isinstance(parse_result, dict) else {}
    except DocNotStandardError as exc:
        logger.warning(
            "save_design_draft parse rejected by template contract: failed_modules=%s score=%s decision=%s",
            getattr(exc, "failed_modules", []),
            getattr(exc, "score", None),
            getattr(exc, "decision", None),
        )
        failed_modules = list(getattr(exc, "failed_modules", []) or [])
        failed_hint = ", ".join(failed_modules) or "未知模块"
        return single_err(
            LEVEL_FREEFORM,
            ErrorCode.DOC_MODULE_PARSE_FAILED,
            f"文档已到达后端，但 {failed_hint} 没有按 aPaaS Builder 标准模板解析通过，不是传输限制。",
            fix=(
                "请按标准模板重写失败模块：五、表单定义必须包含表单基本信息/表单字段/子表区域/按钮动作等标准表；"
                "权限定义必须使用标准权限矩阵表头和列数。不要只生成 /workspace/*.md 文件，也不要把文件路径当作草稿；"
                "修正后必须把完整 Markdown 文本作为 md_content 调用 save_design_draft。"
            ),
            failed_modules=failed_modules,
            parser_errors=list(getattr(exc, "errors", []) or []),
            score=getattr(exc, "score", None),
            decision=getattr(exc, "decision", None),
            should_retry=False,
        )
    except Exception as exc:
        logger.exception("parse_document failed")
        return single_err(
            LEVEL_PLATFORM_ERROR,
            ErrorCode.PLATFORM_API_FAILED,
            f"文档解析失败：{exc}",
            fix="检查 md 表格列名是否与标准模板一致",
        )

    # ─── Step 3: 落库 ─────────────────────────────────────────────
    summary = _build_summary(spec_data)
    draft = DesignDraft(
        id=_new_draft_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        md_content=md_content,
        spec_json=json.dumps(spec_data, ensure_ascii=False),
        summary=summary,
        level=level,
        warnings_json=json.dumps(detection.get("warnings", []), ensure_ascii=False) if detection.get("warnings") else None,
        status="active",
        app_id=parent_app_id,  # 整份替换场景：绑定到既有 app
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    return {
        "ok": True,
        "draft_id": draft.id,
        "level": level,
        "summary": summary,
        "preview_url": _build_preview_url(draft.id),
        "warnings": detection.get("warnings", []) if level == "partial" else [],
        "parent_app_id": parent_app_id,
        "next_action": {
            "tool": "ask_clarifying_question",
            "question": "设计文档已生成，请确认下一步操作：",
            "options": ["开始创建", "继续修改"],
            "instruction": (
                "不要让用户手打“开始创建/部署/OK”。请立即调用 ask_clarifying_question "
                "渲染以上选项；用户选择“开始创建”后再调用 promote_draft_to_app(draft_id)。"
            ),
        },
    }


# ───────────────────────────── get_draft_summary ─────────────────────────────

async def get_draft(db: AsyncSession, draft_id: str) -> Optional[DesignDraft]:
    result = await db.execute(select(DesignDraft).where(DesignDraft.id == draft_id))
    return result.scalar_one_or_none()


async def get_draft_summary(db: AsyncSession, draft_id: str) -> dict:
    draft = await get_draft(db, draft_id)
    if not draft:
        return single_err(
            LEVEL_NOT_FOUND,
            ErrorCode.DRAFT_NOT_FOUND,
            f"draft {draft_id} 不存在",
        )
    return {"ok": True, **_to_dict(draft, with_summary_only=True)}


async def get_draft_spec(db: AsyncSession, draft_id: str) -> dict:
    """给 admin-spa 预览页用，返回完整 spec_json。"""
    draft = await get_draft(db, draft_id)
    if not draft:
        return single_err(
            LEVEL_NOT_FOUND,
            ErrorCode.DRAFT_NOT_FOUND,
            f"draft {draft_id} 不存在",
        )
    return {
        "ok": True,
        "draft_id": draft.id,
        "summary": draft.summary,
        "level": draft.level,
        "spec": json.loads(draft.spec_json) if draft.spec_json else {},
        "warnings": json.loads(draft.warnings_json) if draft.warnings_json else [],
        "app_id": draft.app_id,
        "apaas_app_id": draft.apaas_app_id,
        "admin_url": draft.admin_url,
        "web_url": draft.web_url,
        "status": draft.status,
    }


# ───────────────────────────── promote_draft_to_app（骨架，P2 实现） ─────────────────────────────

async def promote_draft_to_app(
    db: AsyncSession,
    *,
    draft_id: str,
    env: str,
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把 draft 部署成新应用。

    内部串联：
      1. generate_app_from_doc(draft.md_content, env)  → 创建 ai-builder app（含 model/dict/form/perm）
      2. deploy_application(app_id, env)               → 推到 aPaaS 拿 apaas_app_id + admin_url
      3. 把 app_id / apaas_app_id / admin_url 回填到 draft，标 status='promoted'
    """
    draft = await get_draft(db, draft_id)
    if not draft:
        return single_err(LEVEL_NOT_FOUND, ErrorCode.DRAFT_NOT_FOUND, f"draft {draft_id} 不存在")
    if draft.status not in ("active",):
        return single_err(
            LEVEL_PLATFORM_ERROR,
            "DRAFT_NOT_ACTIVE",
            f"draft 状态 {draft.status}，不能 promote（只接受 active）",
        )
    if tenant_id and draft.tenant_id and int(draft.tenant_id) != int(tenant_id):
        return single_err(
            LEVEL_PLATFORM_ERROR,
            "DRAFT_TENANT_MISMATCH",
            (
                f"draft {draft_id} 属于 tenant_id={draft.tenant_id}，"
                f"当前 MCP 身份解析到 tenant_id={tenant_id}，拒绝 promote 以避免串租户。"
            ),
        )

    # 延迟 import 避免循环依赖（mcp_server 进程 import draft_service）
    from app.mcp_server import generate_app_from_doc, deploy_application

    # ─── Step 1: generate（创建 ai-builder 应用） ──────────────────
    gen_res = await generate_app_from_doc(
        md_content=draft.md_content,
        env=env,
        env_id=env_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if not isinstance(gen_res, dict) or not gen_res.get("ok"):
        draft.status = "failed"
        draft.failure_reason = f"generate 失败: {gen_res}"
        await db.commit()
        return single_err(
            LEVEL_PLATFORM_ERROR,
            ErrorCode.PLATFORM_API_FAILED,
            f"创建应用失败：{gen_res.get('summary') or gen_res.get('message') or gen_res}",
            extra={"upstream": gen_res},
        )

    app_id = gen_res.get("app_id")
    if not app_id:
        draft.status = "failed"
        draft.failure_reason = "generate 返回缺 app_id"
        await db.commit()
        return single_err(LEVEL_PLATFORM_ERROR, ErrorCode.PLATFORM_API_FAILED, "创建应用未返回 app_id")

    # ─── Step 2: deploy（推到 aPaaS） ────────────────────────────
    deploy_res = await deploy_application(
        app_id=app_id,
        env=env,
        env_id=env_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if not isinstance(deploy_res, dict):
        deploy_res = {}

    apaas_app_id = deploy_res.get("apaas_app_id")
    admin_url = deploy_res.get("apaas_admin_url")
    deploy_status = deploy_res.get("status")  # completed / in_progress

    # ─── Step 3: 回填 draft ──────────────────────────────────────
    draft.app_id = app_id
    draft.apaas_app_id = apaas_app_id
    draft.env = env
    draft.admin_url = admin_url
    draft.status = "promoted" if apaas_app_id else "active"
    if not apaas_app_id:
        draft.failure_reason = f"deploy 未拿到 apaas_app_id (status={deploy_status})"
    await db.commit()

    id_guide = {
        "local_app_id": app_id,
        "apaas_app_id": apaas_app_id,
        "draft_id": draft.id,
        "local_app_id_usage": "仅用于 AI Builder/MCP 本地应用接口，例如 get_application(app_id=...)",
        "apaas_app_id_usage": (
            "用于 aPaaS 平台工具和发布/自开发工具，例如 republish_apaas_app(apaas_app_id=...)、"
            "get_apaas_app_overview(apaas_app_id=...)"
        ),
    }
    next_actions = {
        "query_local_app": f"get_application(app_id={app_id})",
        "republish_apaas_app": (
            f'republish_apaas_app(apaas_app_id="{apaas_app_id}")'
            if apaas_app_id else
            "等待部署完成并拿到 apaas_app_id 后再调用 republish_apaas_app"
        ),
    }

    return {
        "ok": bool(apaas_app_id),
        "draft_id": draft.id,
        "app_id": app_id,
        "local_app_id": app_id,
        "apaas_app_id": apaas_app_id,
        "admin_url": admin_url,
        "status": "deployed" if apaas_app_id else "in_progress",
        "id_guide": id_guide,
        "next_actions": next_actions,
        "summary": (
            (
                "应用已创建并部署。"
                f"本地应用 ID={app_id}（仅用于 AI Builder/MCP 本地接口）；"
                f"aPaaS 发布应用 ID={apaas_app_id}（发布/自开发/aPaaS 工具必须用这个）。"
                f"后台地址：{admin_url}"
            )
            if apaas_app_id else
            (
                f"创建成功但部署未完成。本地应用 ID={app_id}；"
                "aPaaS 发布应用 ID 暂未生成，不能调用 republish_apaas_app。"
                f"等 30-60s 后用 get_application(app_id={app_id}) 复查 apaas_app_id。"
            )
        ),
        "polling_hint": deploy_res.get("polling_hint"),
    }


# ───────────────────────────── patch_design_draft（骨架，P4 实现） ─────────────────────────────

async def patch_design_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    action: dict,
    user_id: int,
    tenant_id: int,
) -> dict:
    """在 draft 上打补丁，生成新 draft 行。原 draft 标 superseded。

    P4 支持的 op：add_field / update_field / set_permission（见 draft_patch_engine.SUPPORTED_OPS）。
    """
    from app.draft_patch_engine import apply_patch, SUPPORTED_OPS
    from app.services.config_to_spec import config_to_markdown

    parent = await get_draft(db, draft_id)
    if not parent:
        return single_err(LEVEL_NOT_FOUND, ErrorCode.DRAFT_NOT_FOUND, f"draft {draft_id} 不存在")

    if not parent.spec_json:
        return single_err(
            LEVEL_INVALID_PATCH,
            "DRAFT_NO_SPEC",
            f"draft {draft_id} 没有 spec_json，无法 patch",
        )

    spec = json.loads(parent.spec_json)
    new_spec, summary_of_change, errors = apply_patch(spec, action)

    if errors:
        return err_response(
            LEVEL_INVALID_PATCH,
            [StructuredError(
                code=ErrorCode.PATCH_FIELD_INVALID if "缺" in errors[0] or "必须" in errors[0]
                else ErrorCode.PATCH_TARGET_NOT_FOUND,
                msg=errors[0],
                fix=f"支持的 op：{SUPPORTED_OPS}",
            )],
            retriable=False,
        )

    # 渲染新版 md（spec 是真相源，md 是从 spec 生成出来的视图）
    try:
        new_md = config_to_markdown(new_spec, app_description=new_spec.get("appDesc", ""))
    except Exception as exc:
        logger.exception("config_to_markdown failed after patch")
        return single_err(
            LEVEL_PLATFORM_ERROR,
            ErrorCode.PLATFORM_API_FAILED,
            f"patch 后渲染 md 失败：{exc}",
        )

    # 落新 draft，链上 parent_draft_id；保留 parent 的 app 绑定（apply 时用）
    new_draft = DesignDraft(
        id=_new_draft_id(),
        tenant_id=parent.tenant_id,
        user_id=parent.user_id,
        md_content=new_md,
        spec_json=json.dumps(new_spec, ensure_ascii=False),
        summary=_build_summary(new_spec),
        level=parent.level,
        parent_draft_id=parent.id,
        patch_action_json=json.dumps(action, ensure_ascii=False),
        summary_of_change=summary_of_change,
        # 应用绑定继承自 parent（修改场景下 apply 要回到同一 app）
        app_id=parent.app_id,
        apaas_app_id=parent.apaas_app_id,
        env=parent.env,
        admin_url=parent.admin_url,
        web_url=parent.web_url,
        status="active",
    )
    db.add(new_draft)

    # 标父 superseded（但只有 active 状态的才标，promoted/applied 不动以便回溯）
    if parent.status == "active":
        parent.status = "superseded"

    await db.commit()
    await db.refresh(new_draft)

    return {
        "ok": True,
        "draft_id": new_draft.id,
        "parent_draft_id": parent.id,
        "summary_of_change": summary_of_change,
        "summary": new_draft.summary,
        "preview_url": _build_preview_url(new_draft.id),
        "app_id": new_draft.app_id,  # 若 parent 已 promote，agent 后续用此 id 调 apply
    }


# ───────────────────────────── apply_draft_to_live_app（骨架，P4 实现） ─────────────────────────────

async def apply_draft_to_live_app(
    db: AsyncSession,
    *,
    draft_id: str,
    user_id: int,
    tenant_id: int,
) -> dict:
    """把新版 draft 应用到既有应用。

    P4 v1 实现：复用现有 update_app_from_doc 链路（doc_differ 算 change_plan + incremental_executor 执行）。
    传 draft.md_content 整份作为新版，让 server 算 diff。

    v2 改进方向（未实现）：从 patch chain 直接生成 incremental actions，跳过 doc_differ，
    省 diff 计算 + 避免 md re-render 引入的假阳性变更。
    """
    draft = await get_draft(db, draft_id)
    if not draft:
        return single_err(LEVEL_NOT_FOUND, ErrorCode.DRAFT_NOT_FOUND, f"draft {draft_id} 不存在")

    if not draft.app_id:
        return single_err(
            LEVEL_INVALID_PATCH,
            "DRAFT_NO_APP",
            f"draft {draft_id} 未绑定既有应用（app_id 为空），无法 apply。"
            "若要新建应用请用 promote_draft_to_app；若要修改既有应用，确保 patch 来源 draft 已 promote。",
        )

    from app.mcp_server import update_app_from_doc, execute_change_plan

    # ─── Step 1: upload-doc-version → 产 change_plan ──────────
    upd = await update_app_from_doc(
        app_id=draft.app_id,
        new_md=draft.md_content,
        env=draft.env or "",
    )
    if not isinstance(upd, dict) or not upd.get("ok"):
        draft.status = "failed"
        draft.failure_reason = f"update_app_from_doc 失败: {upd}"
        await db.commit()
        return single_err(
            LEVEL_PLATFORM_ERROR,
            ErrorCode.PLATFORM_API_FAILED,
            f"生成变更计划失败：{upd.get('summary') or upd}",
            extra={"upstream": upd},
        )

    plan_id = upd.get("change_plan_id") or upd.get("plan_id")
    if not plan_id:
        # 无变更（spec 已经一致）
        draft.status = "applied"
        await db.commit()
        return {
            "ok": True,
            "draft_id": draft.id,
            "app_id": draft.app_id,
            "status": "no_change",
            "summary": "spec 与线上一致，无需更新",
        }

    # ─── Step 2: execute change plan ──────────────────────────
    exec_res = await execute_change_plan(app_id=draft.app_id, plan_id=plan_id, env=draft.env or "")
    if not isinstance(exec_res, dict):
        exec_res = {}

    ok = bool(exec_res.get("ok") or exec_res.get("platform_synced"))
    draft.status = "applied" if ok else "failed"
    if not ok:
        draft.failure_reason = f"execute_change_plan 失败: {exec_res}"
    await db.commit()

    return {
        "ok": ok,
        "draft_id": draft.id,
        "app_id": draft.app_id,
        "apaas_app_id": draft.apaas_app_id,
        "admin_url": draft.admin_url,
        "plan_id": plan_id,
        "applied_count": exec_res.get("applied_count"),
        "status": "synced" if ok else "failed",
        "summary": (
            draft.summary_of_change or
            f"已同步 {exec_res.get('applied_count', '?')} 项变更到 app {draft.app_id}"
        ) if ok else f"同步失败：{exec_res.get('sync_errors') or exec_res}",
        "errors": exec_res.get("sync_errors", []) if not ok else None,
    }
