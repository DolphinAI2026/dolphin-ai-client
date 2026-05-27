"""SPEC chat stream — 设计 tab 内嵌对话改 SPEC 草稿 (U8).

URL prefix:  /applications/{app_id}/spec-chat-stream

定位 (跟现有 ConfigAssistant 浮窗区分):

    现有 ConfigAssistant            SPEC Chat (本模块)
    ────────────────────            ─────────────────────────
    改 apaas 真配置                 改 spec_sections 草稿
    立即生效                        否, 写草稿等用户"确认并生成"
    短链 / 单点 / 像素级            长链 / 批量 / 语义级
    执行型                          设计型

数据流:
    1. 用户消息进来 → 加载 app + spec_sections 已有 (作上下文)
    2. (MVP) 用 hard-code 规则解析意图: 含"字段"→ 加 placeholder 字段;
       含"角色" → 加角色; 含"字典" → 加字典等
    3. (P2) 真接 LLM — system prompt 让 LLM 输出 JSON patch
    4. 把 patch 应用到 spec_sections (调 update_spec_section, draft_version+1)
    5. SSE stream 把 token + spec_change + done 事件吐回前端

事件类型 (跟前端 SpecChatPanel.vue 对齐):
    started      { app_id, active_chapter }
    token        { content }              — AI 文本流, 前端 append 到当前气泡
    spec_change  { section_type, section_key, before, after, summary, mcp_tool }
                                          — 写入草稿后通知, 前端显 diff card
    done         { reply, applied: bool }
    error        { message }

MVP 设计选择:
    - 不真调 LLM (现有 LLMClient 调用有 cfg 加载复杂度), 用 echo bot + rule-based.
    - 不写库 (chat_session 持久化由 P2 同 ConfigAssistant 一样接).
    - 章节切回前端 props.active_chapter, backend 只决定改哪个 spec_section.
    - spec_section 不存在时自动 init 一个空 (避开 NOT_FOUND 错挡), 让 demo flow 通.

关键点:
    - section_type 跟 SpecSection model 严格对齐 — form/list/process/page/permission/data_model.
    - active_chapter 是前端章节 key (e.g. 'data_model' / 'roles' / 'dict'),
      _chapter_to_section_type 把 frontend 章节映射到 backend section_type.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Application
from app.models.spec_section import SpecSection, VALID_SECTION_TYPES
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.mcp_spec_sections import (
    read_spec_section,
    update_spec_section,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic body
# ---------------------------------------------------------------------------


class SpecChatHistoryItem(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class SpecChatBody(BaseModel):
    message: str
    active_chapter: str = "data_model"  # frontend ChapterKey
    history: list[SpecChatHistoryItem] = []


# ---------------------------------------------------------------------------
# Chapter (frontend) → section_type (backend SpecSection) 映射
# ---------------------------------------------------------------------------
#
# 前端 SpecDesignPanel CHAPTERS 共 10 章; backend SpecSection.section_type 共 6 类.
# 多对一: e.g. menus / form / list 都映射到对应 backend type;
# app_info / integration / datasource 没有对应草稿层 (MVP 只能改下面 6 类).
#
_CHAPTER_TO_SECTION_TYPE: dict[str, str] = {
    "data_model": "data_model",
    "dict": "data_model",     # 字典也归到 data_model section 的子结构
    "roles": "permission",
    "menus": "page",          # 菜单结构改 page section
    "form": "form",
    "list": "list",
    "process": "process",
}


def _resolve_section_type(chapter: str) -> Optional[str]:
    """frontend chapter key → backend section_type, 不支持返 None."""
    return _CHAPTER_TO_SECTION_TYPE.get(chapter)


# ---------------------------------------------------------------------------
# Mock LLM — rule-based intent parser (MVP 兜底)
# ---------------------------------------------------------------------------
#
# 第一版不真调 LLM. 解析用户消息含的关键词 (字段/角色/字典/菜单/流程), 给出
# 1) AI 回复文本 (token 化, 模拟 streaming);
# 2) 一个 patch (dict 加到现有 spec_json 里).
# patch 应用语义 (3 种):
#   - "add_field":      data_model section 里加一个 placeholder 字段
#   - "add_role":       permission section 里加一个角色
#   - "add_dict_option": data_model section 里加字典选项
#   - 都不匹配:          只 echo 不改 SPEC
#
# 关键词检测 case-insensitive, 中英文兼容.


def _mock_parse_intent(message: str, chapter: str) -> dict:
    """Return {kind: 'add_field'|'add_role'|...|'noop', summary: str, patch: dict}.

    patch 仅包含 *要 merge 进 spec_json 的增量*, apply 时跟现有 spec 合并.
    """
    msg = message.strip().lower()
    # 提取引号 / 顿号包裹的"名字" — 简单 demo, 不真做 NLU
    quoted = re.search(r"[\"'「](.+?)[\"'」]", message)
    name_hint = quoted.group(1) if quoted else None

    if any(k in msg for k in ("字段", "field", "属性")):
        field_name = name_hint or "新字段"
        return {
            "kind": "add_field",
            "summary": f"在数据模型加字段「{field_name}」",
            "patch": {
                "_added_fields": [
                    {
                        "name": field_name,
                        "code": f"new_field_{int(datetime.utcnow().timestamp())}",
                        "type": "VARCHAR",
                        "required": False,
                        "description": "AI 草稿 — 待用户调类型/必填",
                        "_pending": True,
                    }
                ]
            },
        }

    if any(k in msg for k in ("角色", "role", "权限组")):
        role_name = name_hint or "新角色"
        return {
            "kind": "add_role",
            "summary": f"加角色「{role_name}」",
            "patch": {
                "_added_roles": [
                    {
                        "name": role_name,
                        "code": f"role_{int(datetime.utcnow().timestamp())}",
                        "description": "AI 草稿 — 待用户调权限矩阵",
                        "_pending": True,
                    }
                ]
            },
        }

    if any(k in msg for k in ("字典", "dict", "选项")):
        dict_name = name_hint or "新字典项"
        return {
            "kind": "add_dict_option",
            "summary": f"加字典选项「{dict_name}」",
            "patch": {
                "_added_dict_options": [
                    {
                        "name": dict_name,
                        "code": f"opt_{int(datetime.utcnow().timestamp())}",
                        "_pending": True,
                    }
                ]
            },
        }

    if any(k in msg for k in ("菜单", "menu")):
        menu_name = name_hint or "新菜单"
        return {
            "kind": "add_menu",
            "summary": f"加菜单「{menu_name}」",
            "patch": {
                "_added_menus": [
                    {
                        "name": menu_name,
                        "code": f"menu_{int(datetime.utcnow().timestamp())}",
                        "_pending": True,
                    }
                ]
            },
        }

    if any(k in msg for k in ("流程", "process", "审批")):
        proc_name = name_hint or "新流程"
        return {
            "kind": "add_process",
            "summary": f"加流程「{proc_name}」",
            "patch": {
                "_added_processes": [
                    {
                        "name": proc_name,
                        "code": f"proc_{int(datetime.utcnow().timestamp())}",
                        "_pending": True,
                    }
                ]
            },
        }

    return {"kind": "noop", "summary": "", "patch": {}}


def _mock_reply_text(intent: dict, chapter: str) -> str:
    """根据 intent 生成 AI 回复 (1-2 句中文)。"""
    if intent["kind"] == "noop":
        return (
            "我理解你想做的方向 — 但目前 MVP 只能识别"
            "「字段 / 角色 / 字典 / 菜单 / 流程」关键词. "
            "试试: 「加字段 备注」或 「加角色 财务专员」."
        )
    summary = intent["summary"]
    return (
        f"已为你生成 SPEC 草稿: {summary}. "
        f"接受后写入 spec_sections (draft_version+1), 不直接生效到 apaas. "
        f"等改完所有点, 点顶部「确认并生成」让 AI 翻成 apaas 配置."
    )


# ---------------------------------------------------------------------------
# 把 patch 应用到 spec_sections — 落库
# ---------------------------------------------------------------------------


async def _apply_patch_to_section(
    db: AsyncSession,
    app_id: int,
    section_type: str,
    section_key: str,
    patch: dict,
    summary: str,
) -> dict:
    """读现有 spec → merge patch → update_spec_section, 返 {before, after} dict.

    section 不存在时自动创建一个空草稿 (避开 NOT_FOUND 阻塞 demo flow).
    """
    # 读现有 (可能不存在)
    existing = await read_spec_section(db, app_id, section_type, section_key)
    before_spec: dict = {}
    if existing.get("ok"):
        before_spec = existing.get("section", {}).get("spec_json") or {}
        if not isinstance(before_spec, dict):
            before_spec = {}

    # 没有 → 直接新建一行 (绕开 NOT_FOUND)
    row_exists = existing.get("ok")
    if not row_exists:
        # 新建草稿: spec_json = patch 自身, base_version=0 表示没从 apaas init 过
        new_row = SpecSection(
            application_id=app_id,
            section_type=section_type,
            section_key=section_key,
            spec_json=json.dumps(patch, ensure_ascii=False),
            base_version=0,
            draft_version=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(new_row)
        await db.commit()
        return {
            "before": before_spec,
            "after": patch,
            "summary": summary,
            "created": True,
        }

    # 已存在 → merge (list 追加, dict 合并)
    after_spec = dict(before_spec)
    for k, v in patch.items():
        if isinstance(v, list) and isinstance(after_spec.get(k), list):
            after_spec[k] = (after_spec.get(k) or []) + v
        elif isinstance(v, list):
            after_spec[k] = list(v)
        elif isinstance(v, dict) and isinstance(after_spec.get(k), dict):
            after_spec[k] = {**after_spec.get(k, {}), **v}
        else:
            after_spec[k] = v

    result = await update_spec_section(
        db,
        app_id=app_id,
        section_type=section_type,
        section_key=section_key,
        spec_json=after_spec,
        diff_summary=summary,
    )
    if not result.get("ok"):
        # 把 mcp tool 的错向上抛
        raise HTTPException(status_code=400, detail=result)
    return {
        "before": before_spec,
        "after": after_spec,
        "summary": summary,
        "created": False,
    }


# ---------------------------------------------------------------------------
# SSE event stream
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def _spec_chat_event_stream(
    app_id: int,
    body: SpecChatBody,
    ctx: AuthContext,
    db: AsyncSession,
):
    """SSE 主生成器 — 解析意图, 落库, 吐 token + spec_change + done."""
    try:
        # ── 1. 权限校验 + 应用加载 ─────────────────────────────────────────
        result = await db.execute(
            select(Application).where(
                Application.id == app_id,
                Application.tenant_id == ctx.tenant_id,
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            yield _sse("error", {"message": "应用不存在"})
            return
        await check_resource_permission(ctx, db, app, "application", Action.EDIT)

        # ── 2. 章节 → section_type 映射 ───────────────────────────────────
        section_type = _resolve_section_type(body.active_chapter)
        if not section_type:
            yield _sse("error", {
                "message": (
                    f"章节「{body.active_chapter}」当前不支持 chat 改 SPEC "
                    f"(MVP 仅支持: data_model / dict / roles / menus / form / list / process). "
                    f"切到支持的章节再发起对话."
                )
            })
            return

        # ── 3. started 事件 ────────────────────────────────────────────────
        yield _sse("started", {
            "app_id": app_id,
            "active_chapter": body.active_chapter,
            "section_type": section_type,
            "mock_llm": True,
        })

        # ── 4. 解析意图 + 生成回复 (mock) ──────────────────────────────────
        intent = _mock_parse_intent(body.message, body.active_chapter)
        reply_text = _mock_reply_text(intent, body.active_chapter)

        # ── 5. token-by-token 模拟 streaming (按字符切, 30ms/字) ──────────
        for ch in reply_text:
            yield _sse("token", {"content": ch})
            # 真 streaming 节奏 — 让前端有"逐字打出"视觉
            await asyncio.sleep(0.015)

        # ── 6. 如果有 patch, 应用到 spec_sections + 发 spec_change ──────
        applied = False
        if intent["kind"] != "noop" and intent["patch"]:
            # section_key 选择: data_model section 用 chapter 名 (e.g. 'main' / 'dict');
            # permission section 用 'global'; 其他用 'default'.
            section_key = _section_key_for(body.active_chapter, section_type)
            try:
                diff = await _apply_patch_to_section(
                    db,
                    app_id=app_id,
                    section_type=section_type,
                    section_key=section_key,
                    patch=intent["patch"],
                    summary=intent["summary"],
                )
                yield _sse("spec_change", {
                    "section_type": section_type,
                    "section_key": section_key,
                    "before": diff["before"],
                    "after": diff["after"],
                    "summary": diff["summary"],
                    "created": diff.get("created", False),
                    # P2 真接 LLM 后这里会带 mcp_tool 名 (e.g. add_apaas_model_field),
                    # MVP 给 placeholder 让前端 UI 能渲染.
                    "mcp_tool": _intent_to_mcp_tool(intent["kind"]),
                })
                applied = True
            except HTTPException as exc:
                yield _sse("error", {
                    "message": f"草稿落库失败: {exc.detail}",
                })
                return
            except Exception as exc:
                logger.exception("spec_chat: apply_patch failed")
                yield _sse("error", {"message": f"草稿落库异常: {exc!r}"})
                return

        # ── 7. done 事件 ──────────────────────────────────────────────────
        yield _sse("done", {
            "reply": reply_text,
            "applied": applied,
            "intent_kind": intent["kind"],
        })

    except Exception as exc:
        logger.exception("spec_chat_stream failed")
        yield _sse("error", {"message": str(exc)})


def _section_key_for(chapter: str, section_type: str) -> str:
    """根据 chapter + section_type 算 section_key.

    O1 阶段 SpecSection 用 (section_type, section_key) 复合键.
    MVP: 每个 chapter 对应一个固定 key, 后续可以按 model_id / form_id 细分.
    """
    if chapter == "dict":
        return "dict"
    if chapter == "data_model":
        return "main"
    if chapter == "roles":
        return "global"
    if chapter == "menus":
        return "global"
    if chapter == "form":
        return "default"
    if chapter == "list":
        return "default"
    if chapter == "process":
        return "default"
    return "default"


def _intent_to_mcp_tool(kind: str) -> str:
    """intent kind → MCP 工具名 (UI 显示用), MVP 占位.

    P2 真接 LLM 后, LLM 自己产 mcp_tool 名; MVP 给固定映射让 UI 显得真.
    """
    return {
        "add_field": "add_apaas_model_field",
        "add_role": "create_apaas_app_role",
        "add_dict_option": "add_apaas_dict_option",
        "add_menu": "create_apaas_menu",
        "add_process": "save_apaas_process",
    }.get(kind, "")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/{app_id}/spec-chat-stream")
async def spec_chat_stream(
    app_id: int,
    body: SpecChatBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SSE chat — 用对话改 SPEC 草稿 (设计 tab 内嵌).

    跟 /config-chat-stream 区分:
      - config-chat: 改 apaas 真配置, 立即生效, 短链
      - spec-chat:   改 spec_sections 草稿, 等用户"确认并生成", 长链
    """
    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(_spec_chat_event_stream(app_id, body, ctx, db))
