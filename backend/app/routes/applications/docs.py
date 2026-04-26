"""文档上传 & 文档版本相关路由。

6 条：
  POST   /upload-doc
  POST   /upload-doc-with-conversation
  POST   /{app_id}/upload-doc-version
  GET    /{app_id}/doc-versions
  DELETE /{app_id}/doc-versions/{version_id}
  GET    /doc-versions-by-conversation/{conversation_id}

Docs 组专用 helper（随路由一起搬入，仅此处使用）：
  _build_doc_upload_context_summary
  _persist_doc_upload
  _iter_parse_progress_events
  _find_v1_doc_version
  _merge_configs
  _remove_deleted_from_config

跨组共享 helper（_dump_preview_config 等）从 parent package 延迟 import，
避免 __init__.py ↔ docs.py 循环。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, desc, delete, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models import User, Application, DocumentVersion, Conversation, ChangePlan, Message
from app.auth import get_current_user
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.json_utils import loads_if_str

router = APIRouter()
logger = logging.getLogger(__name__)


class DraftDocUpdateRequest(BaseModel):
    instruction: str
    conversation_id: Optional[int] = None
    current_doc: Optional[str] = None


# 共享 helper 直接从 sibling _helpers.py 取，不再通过 parent package 代理
from ._helpers import (  # noqa: F401
    _dump_preview_config,
    _dump_parsed_config,
    _ensure_doc_version_parsed_config,
    _ensure_doc_version_rendered_content,
    _infer_app_name_from_doc,
    _render_doc_content_from_config,
    _resolve_builder_llm_cfg,
    _DEFAULT_APP_NAMES,
)


# ---------------------------------------------------------------------------
# docs-private helpers + routes
# 以下内容从 applications/__init__.py 原样搬入（L1713-2667）
# 跨组共享的 helper（_dump_preview_config / _dump_parsed_config / _ensure_doc_version_* /
# _render_doc_content_from_config / _infer_app_name_from_doc / _resolve_builder_llm_cfg）
# 在函数体内通过 `from . import _xxx` 延迟引入，避免循环。
# ---------------------------------------------------------------------------
@router.post("/upload-doc")
async def upload_design_doc(
    file: UploadFile = File(...),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """上传功能设计文档(.md)，用 AI 解析为 preview JSON"""
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    content = await file.read()
    text = content.decode('utf-8')

    from app.doc_pipeline import parse_document
    try:
        result = await parse_document(text)
        data = result.get("data", result)
    except Exception as e:
        logger.error(f"文档解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")

    # 若解析结果是默认值，优先从文档正文/标题推断，退回文件名
    if str(data.get("appName") or "").strip() in _DEFAULT_APP_NAMES:
        inferred = _infer_app_name_from_doc(text, file.filename or "")
        if inferred:
            data["appName"] = inferred

    return {
        "type": "preview",
        "data": data,
        "document_content": text
    }


def _build_doc_upload_context_summary(data: dict, fname: str) -> str:
    """生成文档上传后保存到 Conversation 的系统上下文消息文本。

    纯字符串拼接，无副作用。保留原文案（"用户上传了设计文档《...》"等）
    以免破坏已有对话的系统消息格式约定。
    """
    models_summary = [
        f"- {m.get('name')}：{', '.join(f.get('name', '') for f in m.get('fields', []))}"
        for m in data.get("models", [])
    ]
    dicts_summary = [
        f"- {d.get('name')}（{d.get('code')}）：{', '.join(o.get('name','') for o in d.get('options',[]))}"
        for d in data.get("dicts", [])
    ]
    roles_summary = [r.get('name', '') for r in data.get("roles", [])]

    context_content = f"用户上传了设计文档《{fname}》，已解析为以下配置摘要：\n\n"
    context_content += f"应用名：{data.get('appName', '业务应用')}\n"
    context_content += f"角色：{', '.join(roles_summary)}\n\n"
    context_content += f"数据字典：\n" + "\n".join(dicts_summary) + "\n\n"
    context_content += f"业务表单：\n" + "\n".join(models_summary) + "\n\n"
    context_content += "用户可能会要求修改配置。当用户确认后，生成完整的配置JSON。"
    return context_content


async def _persist_doc_upload(
    *,
    data: dict,
    fname: str,
    text: str,
    parse_meta: dict,
    existing_conversation_id: Optional[int],
    user_id: int,
    tenant_id: Optional[int],
    v1_parsed_config: Optional[dict],
    is_incremental: bool,
) -> dict:
    """把文档解析结果持久化到 DB（Conversation / Messages / DocumentVersion），
    返回 SSE done 事件要用的 done_data dict。

    副作用契约（跟原直线代码完全一致）：
      - 用独立 AsyncSessionLocal session；不会改主请求 db
      - 增量模式复用 existing_conversation_id，否则新建 Conversation
      - 写 4 条 system Message：上下文摘要 / doc_raw json / config json / doc_raw 代码块
      - 增量模式计算 resource_diff 并用 normalized_new_config 覆盖 data
      - 新增 DocumentVersion（version = max_ver + 1，content_hash 用 config json sha256）
      - 返回 done_data 含 conversation_id / preview / rendered_doc / parse_meta /
        version / is_incremental；增量模式追加 diff 字段
    """
    from app.database import AsyncSessionLocal
    from app.config_diff import compute_config_diff

    async with AsyncSessionLocal() as session:
        from app.models import Conversation, Message

        # 增量模式复用已有对话，首次上传创建新对话
        if existing_conversation_id:
            conv_id = existing_conversation_id
        else:
            conversation = Conversation(
                user_id=user_id, tenant_id=tenant_id,
                title=f"文档：{fname}", agent_type="builder", status="active"
            )
            session.add(conversation)
            await session.flush()
            conv_id = conversation.id

        # 系统上下文消息
        context_content = _build_doc_upload_context_summary(data, fname)
        session.add(Message(conversation_id=conv_id, role="system", content=context_content))

        # 保存原始文档内容（供后续创建 DocumentVersion 使用）
        doc_raw_msg = json.dumps({"type": "doc_raw", "filename": fname, "content": text}, ensure_ascii=False)
        session.add(Message(conversation_id=conv_id, role="system", content=doc_raw_msg))

        models_count = len(data.get("models", []))
        roles_count = len(data.get("roles", []))
        dicts_count = len(data.get("dicts", []))

        resource_diff = None
        if is_incremental and v1_parsed_config:
            # 增量模式：用 config_diff 展示差异（会自动完成编码继承）
            resource_diff = compute_config_diff(v1_parsed_config, data)
            # 使用编码继承后的配置，确保 V1 的 code 被保留
            if resource_diff.normalized_new_config:
                data = resource_diff.normalized_new_config

        # 保存完整配置 JSON 作为 system 消息（刷新页面时可恢复）
        config_msg = '```json\n' + _dump_preview_config(data) + '\n```'
        session.add(Message(conversation_id=conv_id, role="system", content=config_msg))

        # 保存原始文档内容（用于后续创建 DocumentVersion）
        doc_msg = '```doc_raw\n' + json.dumps({"filename": fname, "raw_content": text}, ensure_ascii=False) + '\n```'
        session.add(Message(conversation_id=conv_id, role="system", content=doc_msg))

        # 自动保存 DocumentVersion（conversation_id 关联，application_id 待后续绑定）
        import hashlib
        # 检查同一 conversation 下已有版本号
        existing_ver_result = await session.execute(
            select(sa_func.max(DocumentVersion.version))
            .where(DocumentVersion.conversation_id == conv_id)
        )
        max_ver = existing_ver_result.scalar() or 0
        new_version = max_ver + 1

        config_json_str = _dump_parsed_config(data)
        rendered_doc = _render_doc_content_from_config(
            data.get("appName", ""),
            data.get("appCode", ""),
            data,
        )

        doc_ver = DocumentVersion(
            application_id=None,
            conversation_id=conv_id,
            version=new_version,
            filename=fname,
            content_hash=hashlib.sha256(config_json_str.encode()).hexdigest(),
            raw_content=rendered_doc,
            parsed_config=config_json_str,
            parent_version=max_ver if max_ver > 0 else None,
            summary=f"{models_count} 模型, {dicts_count} 字典, {roles_count} 角色",
        )
        session.add(doc_ver)

        # ── 同步建 Spec 并挂到 conversation.spec_id（Phase A-E SPEC 路径）──
        # 修复：V1 doc_pipeline 只写 current_config 不写 Spec，导致 ChatPage
        # SpecCanvas 显示空。这里用 bootstrap_from_legacy_config 从已解析
        # config 派生一份 Spec（首次或 spec 仍空时）。
        try:
            from app.spec.persistence import bootstrap_from_legacy_config, save_spec

            conv_row = (await session.execute(
                select(Conversation).where(Conversation.id == conv_id)
            )).scalar_one()

            need_create_spec = True
            if conv_row.spec_id:
                # 既有 Spec：检查是否仍为空（无 goal + 无 objects），空则覆盖
                from app.models.spec import Spec as SpecORM
                existing = (await session.execute(
                    select(SpecORM).where(SpecORM.id == conv_row.spec_id)
                )).scalar_one_or_none()
                if existing and existing.completeness_total > 0:
                    need_create_spec = False  # 已有内容，不覆盖

            if need_create_spec:
                spec_obj = bootstrap_from_legacy_config(
                    application_id=None,
                    legacy_config=data,
                    created_by=user_id,
                )
                await save_spec(session, spec_obj, tenant_id=tenant_id or 1)
                conv_row.spec_id = spec_obj.id
        except Exception as e:
            logger.warning(f"_persist_doc_upload: spec backfill 失败（不阻断主流程）: {e}")

        await session.commit()

        done_data = {
            "conversation_id": conv_id,
            "preview": data,
            "rendered_doc": rendered_doc,
            "parse_meta": parse_meta,
            "version": new_version,
            "is_incremental": is_incremental,
        }
        # 增量模式下额外返回 diff 信息
        if is_incremental and resource_diff is not None:
            done_data["diff"] = resource_diff.to_dict()

        return done_data


def _iter_parse_progress_events(data: dict, parse_meta: dict):
    """为一份已解析的 preview data 生成所有 SSE progress 事件。

    严格保持与原直线代码一模一样的事件顺序、字段名、message 文本：
      1. [skeleton] 骨架完成：N 个模型、N 个字典、N 个角色 + data=skeleton_data
      2. [roles] / [dicts] / [models] / [forms] / [permissions] batch 事件
         （各自模块非空时才发；batch 内容是 data[模块] 本身）
      3. [complete] 配置组装完成 + data=data + parse_meta=parse_meta

    这是 SSE 契约的核心，前端 ChatPage.vue 依赖 message 前缀里的
    phase 名来分派状态。调用方 `yield from` 本生成器以保持顺序。
    """
    roles_count = len(data.get("roles", []))
    dicts_count = len(data.get("dicts", []))
    models_count = len(data.get("models", []))

    skeleton_data = {
        "appName": data.get("appName", ""),
        "appCode": data.get("appCode", ""),
        "roles": data.get("roles", []),
    }
    yield {"event": "progress", "data": json.dumps({
        "message": f"[skeleton] 骨架完成：{models_count} 个模型、{dicts_count} 个字典、{roles_count} 个角色",
        "data": skeleton_data,
    }, ensure_ascii=False)}

    if data.get("roles"):
        yield {"event": "progress", "data": json.dumps({
            "message": f"[roles] 角色生成完成：{roles_count} 个",
            "batch": data["roles"],
        }, ensure_ascii=False)}
    if data.get("dicts"):
        yield {"event": "progress", "data": json.dumps({
            "message": f"[dicts] 字典生成完成：{dicts_count} 个",
            "batch": data["dicts"],
        }, ensure_ascii=False)}
    if data.get("models"):
        yield {"event": "progress", "data": json.dumps({
            "message": f"[models] 模型生成完成：{models_count} 个",
            "batch": data["models"],
        }, ensure_ascii=False)}
    if data.get("forms"):
        forms_count = len(data.get("forms", []))
        yield {"event": "progress", "data": json.dumps({
            "message": f"[forms] 表单生成完成：{forms_count} 个",
            "batch": data["forms"],
        }, ensure_ascii=False)}
    if data.get("permissions"):
        yield {"event": "progress", "data": json.dumps({
            "message": "[permissions] 权限生成完成",
            "batch": data["permissions"],
        }, ensure_ascii=False)}
    yield {"event": "progress", "data": json.dumps({
        "message": "[complete] 配置组装完成",
        "data": data,
        "parse_meta": parse_meta,
    }, ensure_ascii=False)}


async def _find_v1_doc_version(
    db: AsyncSession,
    conversation_id: Optional[int],
) -> Optional[dict]:
    """若 conversation_id 存在，查该对话下最新的 DocumentVersion 作为 V1 基线。

    返回精简 dict（raw_content / parsed_config / version），或 None。
    """
    if not conversation_id:
        return None
    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.conversation_id == conversation_id)
        .order_by(desc(DocumentVersion.version))
        .limit(1)
    )
    doc_obj = result.scalar_one_or_none()
    if not doc_obj:
        return None
    return {
        "raw_content": doc_obj.raw_content,
        "parsed_config": doc_obj.parsed_config,
        "version": doc_obj.version,
    }


@router.post("/upload-doc-with-conversation")
async def upload_doc_with_conversation(
    file: UploadFile = File(...),
    conversation_id: Optional[int] = Form(None),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """上传功能设计文档并创建对话会话（SSE 流式返回解析进度）

    支持两种模式：
    - V1（首次上传）：不传 conversation_id，完整解析，创建新对话
    - V2+（增量上传）：传 conversation_id，对比文档文本，只解析变化部分

    事件格式：
    - event: progress / data: {"message": "..."} — 解析进度
    - event: done / data: {"conversation_id":N, "preview":{...}} — 完成
    - event: error / data: {"message": "..."} — 失败
    """
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    content = await file.read()
    text = content.decode('utf-8')
    fname = file.filename or ""

    # 把 db session 相关的值先存好
    user_id = current_user.id
    tenant_id = ctx.tenant_id
    existing_conversation_id = conversation_id

    # 获取当前对话/租户绑定的 Builder 模型，避免文档解析回退到 .env 默认模型
    _tenant_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        tenant_id,
        conversation_id=existing_conversation_id,
    )

    # 如果传了 conversation_id，预先查找 V1 文档版本作为增量对比基线
    v1_doc_info: Optional[dict] = await _find_v1_doc_version(db, existing_conversation_id)

    async def event_generator():
        import asyncio
        from app.database import AsyncSessionLocal
        from app.doc_text_differ import diff_sections, get_diff_stats
        from app.doc_pipeline import parse_document
        from app.config_diff import compute_config_diff

        data = None
        diff_result = None
        is_incremental = bool(v1_doc_info)
        v1_parsed_config = None

        try:
            # ── 增量模式：有 V1 文档时先检查是否有变化 ──
            if v1_doc_info and v1_doc_info.get("raw_content"):
                yield {"event": "progress", "data": json.dumps({"message": "正在对比文档..."}, ensure_ascii=False)}
                diff_result = diff_sections(v1_doc_info["raw_content"], text)
                diff_stats = get_diff_stats(diff_result)
                total_changes = diff_stats["added"] + diff_stats["modified"] + diff_stats["removed"]

                if total_changes == 0:
                    yield {"event": "error", "data": json.dumps({"message": "文档内容无变化，无需重新上传"}, ensure_ascii=False)}
                    return

                yield {"event": "progress", "data": json.dumps({
                    "message": f"发现 {total_changes} 个章节变化（新增 {diff_stats['added']} 个，修改 {diff_stats['modified']} 个，删除 {diff_stats['removed']} 个）",
                    "diff_stats": diff_stats,
                }, ensure_ascii=False)}

            # ── 全量解析：用 asyncio.Queue 实时把进度推给前端 ──
            # 队列中的元素为 (msg, batch) 元组，batch 为可选的已解析模块数据
            progress_queue: asyncio.Queue = asyncio.Queue()

            async def _on_progress(msg: str, *, batch=None):
                await progress_queue.put((msg, batch))

            # 启动解析任务（与 SSE 流并发）
            parse_task = asyncio.create_task(
                parse_document(text, llm_cfg=_tenant_llm_cfg, on_progress=_on_progress)
            )

            # 实时转发进度消息，直到解析完成
            while not parse_task.done():
                try:
                    item = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                    msg, batch = item if isinstance(item, tuple) else (item, None)
                    payload = {"message": msg}
                    if batch is not None:
                        payload["batch"] = batch
                    yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    pass

            # 排干队列中剩余消息
            while not progress_queue.empty():
                item = progress_queue.get_nowait()
                msg, batch = item if isinstance(item, tuple) else (item, None)
                payload = {"message": msg}
                if batch is not None:
                    payload["batch"] = batch
                yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False)}

            # 取解析结果（若抛异常会在此处重新抛出）
            parse_result = parse_task.result()
            parse_meta = parse_result.get("parse_meta", {}) if isinstance(parse_result, dict) else {}
            data = parse_result.get("data", parse_result)

            # LLM 返回的 appName 常常是"应用"/"未命名应用"等默认值；必须在发出任何
            # SSE 事件（skeleton/complete/done）之前把它推断为文档里的真实名字，
            # 否则前端 skeleton 阶段会先把默认值写入 store，后续事件的守卫逻辑会
            # 阻止覆盖，最终界面显示"未命名应用"。
            if isinstance(data, dict) and str(data.get("appName") or "").strip() in _DEFAULT_APP_NAMES:
                inferred = _infer_app_name_from_doc(text, fname)
                if inferred:
                    data["appName"] = inferred

            # ── 增量模式：用纯代码 diff 与 V1 config 对比，继承编码 ──
            if v1_doc_info and v1_doc_info.get("parsed_config"):
                try:
                    v1_parsed_config = loads_if_str(v1_doc_info["parsed_config"])
                    yield {"event": "progress", "data": json.dumps({"message": "对比配置差异..."}, ensure_ascii=False)}
                    resource_diff = compute_config_diff(v1_parsed_config, data)
                    if resource_diff.normalized_new_config:
                        data = resource_diff.normalized_new_config
                except Exception as e:
                    logger.warning(f"增量 diff 失败，使用全量解析结果: {e}")

            if data:
                for evt in _iter_parse_progress_events(data, parse_meta):
                    yield evt

        except Exception as e:
            err_msg = str(e) or repr(e) or type(e).__name__
            logger.error(f"文档解析失败: {err_msg}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": f"文档解析失败: {err_msg}"}, ensure_ascii=False)}
            return

        if not data:
            yield {"event": "error", "data": json.dumps({"message": "配置生成失败：无数据"}, ensure_ascii=False)}
            return

        # 兜底：若推断仍未覆盖（例如进入了增量 diff 分支把 data 换了引用），
        # 这里再兜一次，确保最终保存到 DB / SSE done 事件里的 appName 不是默认值。
        if str(data.get("appName") or "").strip() in _DEFAULT_APP_NAMES:
            data["appName"] = _infer_app_name_from_doc(text, fname) or "业务应用"

        # 创建对话 + 消息 + DocumentVersion（独立 session）
        done_data = await _persist_doc_upload(
            data=data,
            fname=fname,
            text=text,
            parse_meta=parse_meta,
            existing_conversation_id=existing_conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            v1_parsed_config=v1_parsed_config,
            is_incremental=is_incremental,
        )
        yield {
            "event": "done",
            "data": json.dumps(done_data, ensure_ascii=False),
        }

    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())


# ── 文档驱动增量开发 ──────────────────────────────────



def _merge_configs(v1_config: dict, partial_v2_config: dict, text_diff: dict) -> dict:
    """合并 V1 未变更部分 + V2 变更部分（AI 只解析了变更章节）。

    策略：以 V1 config 为基础，用 partial_v2_config（变更章节的解析结果）覆盖/补充。
    - partial_v2_config 中的 models/dicts/roles：如果 code 匹配 V1 则替换，否则新增
    - V1 中不在 partial_v2_config 中出现的（未变更章节的数据）：保留
    - removed 章节对应的数据：不包含在 partial_v2_config 中，需要从 V1 移除
    """
    from copy import deepcopy

    merged = deepcopy(v1_config)

    # 收集变更解析出的 codes
    v2_model_codes = {m.get("code", ""): m for m in partial_v2_config.get("models", []) if m.get("code")}
    v2_dict_codes = {d.get("code", ""): d for d in partial_v2_config.get("dicts", []) if d.get("code")}
    v2_role_codes = {r.get("code", ""): r for r in partial_v2_config.get("roles", []) if r.get("code")}

    # 更新 models：替换已存在的，追加新增的
    existing_model_codes = {m.get("code", "") for m in merged.get("models", [])}
    new_models = []
    for m in merged.get("models", []):
        code = m.get("code", "")
        if code in v2_model_codes:
            new_models.append(v2_model_codes[code])  # 替换为新版本
        else:
            new_models.append(m)  # 保留未变更的
    # 追加全新的模型
    for code, m in v2_model_codes.items():
        if code not in existing_model_codes:
            new_models.append(m)
    merged["models"] = new_models

    # 更新 dicts
    existing_dict_codes = {d.get("code", "") for d in merged.get("dicts", [])}
    new_dicts = []
    for d in merged.get("dicts", []):
        code = d.get("code", "")
        if code in v2_dict_codes:
            new_dicts.append(v2_dict_codes[code])
        else:
            new_dicts.append(d)
    for code, d in v2_dict_codes.items():
        if code not in existing_dict_codes:
            new_dicts.append(d)
    merged["dicts"] = new_dicts

    # 更新 roles
    existing_role_codes = {r.get("code", "") for r in merged.get("roles", [])}
    new_roles = []
    for r in merged.get("roles", []):
        code = r.get("code", "")
        if code in v2_role_codes:
            new_roles.append(v2_role_codes[code])
        else:
            new_roles.append(r)
    for code, r in v2_role_codes.items():
        if code not in existing_role_codes:
            new_roles.append(r)
    merged["roles"] = new_roles

    # 更新 appName（如果变更解析结果中有）
    if partial_v2_config.get("appName"):
        merged["appName"] = partial_v2_config["appName"]

    return merged


def _remove_deleted_from_config(v1_config: dict, text_diff: dict) -> dict:
    """当只有删除章节（无新增/修改）时，从 V1 config 中移除被删除章节对应的内容。

    注意：由于章节标题和 config 中的 model/dict 名称不一定完全对应，
    这里采取保守策略 — 只返回 V1 config 的副本。
    真正的删除判断由后续的 semantic_diff 来处理。
    """
    from copy import deepcopy
    return deepcopy(v1_config)


@router.post("/{app_id}/draft-doc-update")
async def draft_doc_update(
    app_id: int,
    body: DraftDocUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """根据自然语言更新诉求生成新版标准 SPEC 草稿。

    这里不直接执行更新，只产出稳定的 Markdown 文档；前端随后复用
    upload-doc-version 的严格解析、版本记录和变更计划流程。
    """
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="更新诉求不能为空")

    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    current_config: dict = {}
    if app.config_preview:
        try:
            loaded = loads_if_str(app.config_preview)
            current_config = loaded.get("data", loaded) if isinstance(loaded, dict) else {}
        except Exception:
            current_config = {}

    current_doc = (body.current_doc or "").strip()
    if not current_doc:
        latest_result = await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.application_id == app.id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
        latest_doc = latest_result.scalar_one_or_none()
        if latest_doc:
            current_doc = await _ensure_doc_version_rendered_content(db, app, latest_doc)

    conversation: Conversation | None = None
    if body.conversation_id:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.tenant_id == ctx.tenant_id,
            )
        )
        conversation = conv_result.scalar_one_or_none()
        if conversation:
            db.add(Message(
                conversation_id=conversation.id,
                role="user",
                content=f"【更新应用】{instruction}",
            ))
            await db.commit()

    doc_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        ctx.tenant_id,
        conversation_id=body.conversation_id,
    )
    if doc_llm_cfg:
        doc_llm_cfg = {**doc_llm_cfg, "max_tokens": 8000}

    from app.routes.requirements import (
        GENERATE_DOC_PROMPT,
        _complete_with_config,
        _repair_doc_json,
        _regenerate_doc_json,
        extract_json,
        is_valid_doc_result,
    )
    from app.services.config_converter import convert_analysis_to_app_config

    app_name = app.app_name or current_config.get("appName") or "业务应用"
    app_code = app.app_code or current_config.get("appCode") or current_config.get("app_code") or ""
    current_config_text = json.dumps(current_config, ensure_ascii=False, indent=2)[:60000]
    current_doc_text = current_doc[:60000]

    messages = [
        {
            "role": "system",
            "content": (
                "你是 aPaaS 应用更新设计助手。你的任务是基于现有应用 SPEC 和配置，"
                "把用户的增量更新诉求合并成一份完整的新版功能设计文档 JSON。"
                "必须保留未被更新诉求影响的模型、字段、角色、字典、流程、权限和自开发定义。"
                "只输出 JSON，不要输出 Markdown、解释、注释或代码块。"
            ),
        },
        {
            "role": "user",
            "content": f"""当前应用：{app_name}
当前应用编码：{app_code}

## 现有标准 SPEC
{current_doc_text or "（未找到已渲染 SPEC，以下配置 JSON 为准）"}

## 现有应用配置 JSON
{current_config_text}

## 本次更新诉求
{instruction}

请输出“更新后的完整结构化功能设计文档 JSON”，不是差异 JSON。要求：
1. 未被本次诉求影响的内容必须原样保留。
2. app_info.name 保持为“{app_name}”，app_info.code 优先保持“{app_code}”。
3. custom_development 必须输出数组；如果没有强制自开发项，也要输出 1 条 none/config_only 记录。
4. 复杂校验、计算、Hook、插件、外部接口、报表看板、定制页面/列表模块等配置无法完整覆盖的内容必须进入 custom_development。
5. 输出结构必须满足下面的 schema 指令：

{GENERATE_DOC_PROMPT}
""",
        },
    ]

    try:
        full_text = await _complete_with_config(doc_llm_cfg, messages, max_tokens=8000, temperature=0.0)
        try:
            doc_result = extract_json(full_text)
        except Exception:
            try:
                doc_result = await _repair_doc_json(doc_llm_cfg, full_text)
            except Exception:
                doc_result = await _regenerate_doc_json(doc_llm_cfg, messages)

        if not is_valid_doc_result(doc_result):
            raise ValueError("模型返回的设计文档结构不完整")

        app_config = convert_analysis_to_app_config(doc_result)
        app_config["appName"] = app_name
        if app_code:
            app_config["appCode"] = app_code
        custom_development = doc_result.get("custom_development")
        if isinstance(custom_development, list):
            app_config["custom_development"] = custom_development
        elif current_config.get("custom_development"):
            app_config["custom_development"] = current_config.get("custom_development")
        else:
            app_config["custom_development"] = [{
                "type": "config_only",
                "name": "暂无强制自开发项",
                "trigger": "当前需求可优先通过模型、表单、权限和基础流程配置覆盖",
                "scope": "如后续出现复杂交互、外部接口、算法规则或报表看板，再进入 IDE 自开发",
                "acceptance": "配置内容可完成主要业务闭环",
            }]

        if current_config.get("models") and not app_config.get("models"):
            raise ValueError("更新后文档未包含任何数据模型，已中止以避免覆盖现有应用")

        markdown = _render_doc_content_from_config(app_name, app_config.get("appCode", app_code), app_config)
        safe_code = re.sub(r"[^A-Za-z0-9_-]+", "-", app_config.get("appCode") or app_code or "app").strip("-").lower()
        filename = f"{safe_code or 'app'}-update-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.md"
        summary = f"已根据对话诉求生成新版 SPEC，包含 {len(app_config.get('models') or [])} 个模型、{len(app_config.get('forms') or [])} 张表单。"

        if conversation:
            db.add(Message(
                conversation_id=conversation.id,
                role="assistant",
                content=f"{summary} 已进入文档版本对比和变更计划确认。",
            ))
            await db.commit()

        return {
            "markdown": markdown,
            "filename": filename,
            "summary": summary,
            "doc_result": doc_result,
            "app_config": app_config,
        }
    except Exception as e:
        logger.error("draft doc update failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成新版 SPEC 失败: {str(e)}")


@router.post("/{app_id}/upload-doc-version")
async def upload_doc_version(
    app_id: int,
    file: UploadFile = File(...),
    conversation_id: int = Form(...),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """上传新版本设计文档，AI 解析后与当前配置做语义对比（SSE 流式返回进度）"""
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    # 加载应用
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    content_bytes = await file.read()
    text = content_bytes.decode('utf-8')
    fname = file.filename or ""

    # 获取租户 LLM 配置（供 AI 解析使用）
    from app.routes.chat import _get_tenant_llm_config as _get_llm_cfg
    _tenant_llm_cfg = await _get_llm_cfg(db, ctx.tenant_id)

    # 提前获取需要的值（SSE generator 不能用原始 db session）
    app_id_val = app.id
    tenant_id_val = ctx.tenant_id
    current_config_str = app.config_preview
    doc_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        tenant_id_val,
        conversation_id=conversation_id,
    )

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import build_structure_index, semantic_diff, diff_to_actions, compute_hash
        from app.config_diff import compute_config_diff
        from app.doc_text_differ import diff_sections, get_diff_stats
        import hashlib

        current_step = "初始化"

        try:
            current_step = "读取文档内容"
            yield {"event": "progress", "data": json.dumps({"step": "读取文档内容..."}, ensure_ascii=False)}

            # 1. 计算 hash
            content_hash = compute_hash(text)

            # 2. 检查是否与最新版本重复 & 获取 V1 文档版本
            v1_doc: Optional[dict] = None
            async with AsyncSessionLocal() as session:
                # 只和最新版本比较 hash（允许回退到旧版本）
                latest_result = await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app_id_val,
                    ).order_by(DocumentVersion.version.desc()).limit(1)
                )
                latest_ver = latest_result.scalar_one_or_none()
                if latest_ver and latest_ver.content_hash == content_hash:
                    yield {"event": "error", "data": json.dumps({"message": "文档内容未变化，无需上传"}, ensure_ascii=False)}
                    return

                # 3. 获取当前最大 version 及其 DocumentVersion 记录
                max_ver_result = await session.execute(
                    select(sa_func.max(DocumentVersion.version)).where(
                        DocumentVersion.application_id == app_id_val
                    )
                )
                max_ver = max_ver_result.scalar() or 0
                new_version = max_ver + 1

                # 获取 V1 文档记录（用于文本对比）
                if max_ver > 0:
                    v1_result = await session.execute(
                        select(DocumentVersion).where(
                            DocumentVersion.application_id == app_id_val,
                            DocumentVersion.version == max_ver,
                        )
                    )
                    v1_doc_obj = v1_result.scalar_one_or_none()
                    if v1_doc_obj:
                        # 提取需要的字段，避免 session 外访问
                        v1_doc = {
                            "raw_content": v1_doc_obj.raw_content,
                            "parsed_config": v1_doc_obj.parsed_config,
                            "version": v1_doc_obj.version,
                        }

            current_step = "解析文档结构"
            yield {"event": "progress", "data": json.dumps({"step": "解析文档结构..."}, ensure_ascii=False)}

            # 4. 构建章节索引
            structure_index = build_structure_index(text)

            # ── 全量解析新文档（纯代码优先，失败模块 LLM 修复）──
            from app.doc_pipeline import parse_document

            if v1_doc and v1_doc.get("raw_content"):
                # 有旧文档时先做文本对比，告知变化情况
                current_step = "对比文档章节"
                yield {"event": "progress", "data": json.dumps({"step": "text_diff", "message": "正在对比文档章节..."}, ensure_ascii=False)}
                text_diff = diff_sections(v1_doc["raw_content"], text)
                diff_stats = get_diff_stats(text_diff)
                yield {"event": "progress", "data": json.dumps({
                    "step": "text_diff",
                    "data": diff_stats,
                    "message": f"章节对比完成：新增 {diff_stats['added']}、修改 {diff_stats['modified']}、删除 {diff_stats['removed']}、未变更 {diff_stats['unchanged']}",
                }, ensure_ascii=False)}

            current_step = "解析文档"
            progress_messages = []

            async def _on_progress(msg: str, *, batch=None):
                progress_messages.append((msg, batch))

            yield {"event": "progress", "data": json.dumps({"step": "parse", "message": "检查文档标准度..."}, ensure_ascii=False)}
            # 更新比对必须使用纯代码解析（strict=True），禁用所有 LLM 兜底：
            # LLM 的非确定性会让 v1 / v2 解析产生系统性偏差，污染 diff 结果
            parse_result = await parse_document(
                text,
                llm_cfg=doc_llm_cfg,
                on_progress=_on_progress,
                strict=True,
            )
            parse_meta = parse_result.get("parse_meta", {}) if isinstance(parse_result, dict) else {}

            for item in progress_messages:
                msg, batch = item if isinstance(item, tuple) else (item, None)
                payload = {"step": "parse", "message": msg}
                if batch is not None:
                    payload["batch"] = batch
                yield {"event": "progress", "data": json.dumps(payload, ensure_ascii=False)}

            v2_config = parse_result.get("data", parse_result)

            current_step = "对比资源差异"
            yield {"event": "progress", "data": json.dumps({"step": "对比资源差异..."}, ensure_ascii=False)}

            # 6. 加载 V1 配置（从应用当前 config_preview）
            v1_config: dict = {}
            if current_config_str:
                try:
                    loaded = loads_if_str(current_config_str)
                    v1_config = loaded.get("data", loaded)
                except Exception:
                    pass

            # 7. 资源级差异对比（用于前端展示，会自动完成编码继承）
            resource_diff = compute_config_diff(v1_config, v2_config)
            # 使用编码继承后的配置，确保 V1 的 code 被保留
            if resource_diff.normalized_new_config:
                v2_config = resource_diff.normalized_new_config
            resource_diff_dict = resource_diff.to_dict()

            # 8. 语义对比（用于生成可勾选 actions）
            diff = semantic_diff(v1_config, v2_config)

            # 9. 生成 patch actions
            actions = diff_to_actions(diff, v2_config)

            # 10. 生成摘要
            summary = resource_diff.summary or f"文档 V{new_version} 资源变更分析完成"

            current_step = "保存版本记录"
            yield {"event": "progress", "data": json.dumps({"step": "保存版本记录..."}, ensure_ascii=False)}

            # 11. 创建 DocumentVersion + ChangePlan
            async with AsyncSessionLocal() as session:
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                rendered_doc = _render_doc_content_from_config(
                    app_obj.app_name or v2_config.get("appName", ""),
                    app_obj.app_code or v2_config.get("appCode", ""),
                    v2_config,
                )
                config_json = _dump_parsed_config(v2_config)

                doc_ver = DocumentVersion(
                    application_id=app_id_val,
                    version=new_version,
                    filename=fname,
                    content_hash=hashlib.sha256(config_json.encode()).hexdigest(),
                    raw_content=rendered_doc,
                    structure_index=json.dumps(structure_index, ensure_ascii=False),
                    parsed_config=config_json,
                    parent_version=max_ver if max_ver > 0 else None,
                    summary=summary,
                )
                session.add(doc_ver)
                await session.flush()

                change_plan = ChangePlan(
                    application_id=app_id_val,
                    conversation_id=conversation_id,
                    from_version=max_ver,
                    to_version=new_version,
                    diff_summary=json.dumps(resource_diff_dict, ensure_ascii=False),
                    actions=json.dumps(actions, ensure_ascii=False),
                    status="pending",
                )
                session.add(change_plan)

                # 更新应用：文档版本 + 配置 + 状态
                app_obj.current_doc_version = new_version
                # 关键：用 V2 配置更新 config_preview（保留原始 appName）
                if app_obj.app_name:
                    v2_config["appName"] = app_obj.app_name
                app_obj.config_preview = _dump_preview_config(v2_config)
                # 上传了更新文档且生成了变更计划，但还未执行更新，进入“更新中”状态。
                if app_obj.apaas_app_id or app_obj.status in ("completed", "updating"):
                    app_obj.status = "updating"
                else:
                    app_obj.status = "draft"
                # 在 generation_state 中记录配置版本变更
                if app_obj.generation_state:
                    try:
                        from datetime import datetime as dt
                        gs = json.loads(app_obj.generation_state)
                        gs["config_version"] = new_version
                        gs["config_updated_at"] = dt.utcnow().isoformat()
                        app_obj.generation_state = json.dumps(gs, ensure_ascii=False)
                    except Exception:
                        pass

                await session.commit()
                await session.refresh(change_plan)

                yield {
                    "event": "done",
                    "data": json.dumps({
                        "version": new_version,
                        "from_version": max_ver,
                        "to_version": new_version,
                        "summary": summary,
                        "diff": resource_diff_dict,
                        "semantic_diff": diff,
                        "actions": actions,
                        "change_plan_id": change_plan.id,
                        "is_first_version": max_ver == 0,
                        "parsed_config": v2_config,
                        "rendered_doc": rendered_doc,
                        "parse_meta": parse_meta,
                    }, ensure_ascii=False),
                }

        except Exception as e:
            from app.doc_pipeline import DocNotStandardError

            if isinstance(e, DocNotStandardError):
                logger.warning(
                    f"文档未按模板规范：failed_modules={e.failed_modules}, score={e.score}, decision={e.decision}"
                )
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "code": "doc_not_standard",
                        "message": str(e),
                        "step": current_step,
                        "error_type": e.__class__.__name__,
                        "failed_modules": e.failed_modules,
                        "errors": e.errors[:20],
                        "standard_score": e.score,
                        "decision": e.decision,
                    }, ensure_ascii=False)
                }
                return

            logger.error(f"文档版本上传失败: {e}", exc_info=True)
            detail = str(e).strip() or repr(e).strip() or e.__class__.__name__
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": f"处理失败（步骤：{current_step}）：{detail}",
                    "step": current_step,
                    "error_type": e.__class__.__name__,
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())


@router.get("/{app_id}/doc-versions")
async def list_doc_versions(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取应用的文档版本历史"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(desc(DocumentVersion.version))
    )
    versions = result.scalars().all()

    # 同时加载关联的 change plans
    result = await db.execute(
        select(ChangePlan)
        .where(ChangePlan.application_id == app_id)
        .order_by(desc(ChangePlan.created_at))
    )
    plans = result.scalars().all()
    plans_by_to_version = {}
    for p in plans:
        plans_by_to_version.setdefault(p.to_version, []).append(p)

    items = []
    for v in versions:
        parsed_config = await _ensure_doc_version_parsed_config(db, v)
        rendered_content = await _ensure_doc_version_rendered_content(db, app, v)
        related_plans = plans_by_to_version.get(v.version, [])
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": rendered_content,
            "parsed_config": parsed_config,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
            "change_plans": [
                {
                    "id": p.id,
                    "from_version": p.from_version,
                    "to_version": p.to_version,
                    "status": p.status,
                    "created_at": str(p.created_at) if p.created_at else None,
                }
                for p in related_plans
            ],
        })

    await db.commit()

    return {
        "current_version": app.current_doc_version,
        "versions": items,
    }


@router.delete("/{app_id}/doc-versions/{version_id}")
async def delete_doc_version(
    app_id: int,
    version_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除指定文档版本，并同步应用当前版本指针。"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.application_id == app_id,
        )
    )
    doc_version = result.scalar_one_or_none()
    if not doc_version:
        raise HTTPException(status_code=404, detail="文档版本不存在")

    deleted_version_no = doc_version.version

    await db.execute(
        delete(ChangePlan).where(
            ChangePlan.application_id == app_id,
            (ChangePlan.to_version == deleted_version_no) | (ChangePlan.from_version == deleted_version_no),
        )
    )
    await db.delete(doc_version)
    await db.flush()

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(desc(DocumentVersion.version))
    )
    remaining_versions = result.scalars().all()

    latest = remaining_versions[0] if remaining_versions else None
    app.current_doc_version = latest.version if latest else None
    if latest and latest.parsed_config:
        try:
            parsed = loads_if_str(latest.parsed_config)
            app.config_preview = _dump_preview_config(parsed)
        except Exception:
            logger.warning("删除文档版本后同步 config_preview 失败", exc_info=True)
            app.config_preview = None
    else:
        app.config_preview = None

    await db.commit()
    return {
        "ok": True,
        "deleted_version": deleted_version_no,
        "current_version": app.current_doc_version,
    }


@router.get("/doc-versions-by-conversation/{conversation_id}")
async def list_doc_versions_by_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """通过 conversation_id 获取文档版本（在 Application 创建之前使用）"""
    from app.models import Conversation
    # 验证对话属于当前用户/租户
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == ctx.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.conversation_id == conversation_id)
        .order_by(desc(DocumentVersion.version))
    )
    versions = result.scalars().all()

    items = []
    for v in versions:
        parsed_config = await _ensure_doc_version_parsed_config(db, v)
        rendered_content = await _ensure_doc_version_rendered_content(db, None, v)
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": rendered_content,
            "parsed_config": parsed_config,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
        })

    await db.commit()

    return {
        "versions": items,
    }


# ── 获取单个应用信息 ──
