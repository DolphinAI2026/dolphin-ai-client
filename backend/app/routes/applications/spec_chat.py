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
    2. 真 LLM (SPEC_CHAT_USE_REAL_LLM=true): system prompt 让 LLM 边输出文本边在结尾给 JSON patch
       兜底 (env 没开 / cfg 不可用 / JSON 解析失败): 走 rule-based mock parser
       含"字段"→ 加 placeholder 字段; 含"角色"→ 加角色; 含"字典"→ 加字典等
    3. 把 patch 应用到 spec_sections (调 update_spec_section, draft_version+1)
    4. SSE stream 把 token + spec_change + done 事件吐回前端

事件类型 (跟前端 SpecChatPanel.vue 对齐):
    started      { app_id, active_chapter, mock_llm }
    token        { content }              — AI 文本流, 前端 append 到当前气泡
    spec_change  { section_type, section_key, before, after, summary, mcp_tool }
                                          — 写入草稿后通知, 前端显 diff card
    done         { reply, applied: bool }
    error        { message }

LLM 路径设计 (复用 /config-chat-stream 模式):
    - LLM cfg 走 _resolve_builder_llm_cfg (跟 ConfigAssistant 同一套租户模型配置)
    - 流式: LLMClient.chat_completion_stream → 每个 chunk 是 OpenAI delta 格式 JSON 字符串,
      抽 choices[0].delta.content 转 SSE token 事件给前端
    - LLM 输出格式: 自然语言摘要 + 末尾 ```json {"summary": "...", "patch": {...}} ``` 块
    - 流完后正则抽 json 块, 解析失败兜底走 mock parser

环境变量:
    SPEC_CHAT_USE_REAL_LLM=true  → 启用真 LLM (默关, 保 demo 兼容)
    SPEC_CHAT_USE_REAL_LLM=false / 不设 → 走 mock rule-based parser

关键点:
    - section_type 跟 SpecSection model 严格对齐 — form/list/process/page/permission/data_model.
    - active_chapter 是前端章节 key (e.g. 'data_model' / 'roles' / 'dict'),
      _chapter_to_section_type 把 frontend 章节映射到 backend section_type.
    - 不新建 LLMClient — 直接复用 app.llm_client.LLMClient (跟 config-chat-stream 一致).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.llm_client import LLMClient
from app.models import Application
from app.models.spec_section import SpecSection, VALID_SECTION_TYPES
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.mcp_spec_sections import (
    read_spec_section,
    update_spec_section,
)
from app.routes.applications._helpers import _resolve_builder_llm_cfg

router = APIRouter()
logger = logging.getLogger(__name__)


def _real_llm_enabled() -> bool:
    """SPEC_CHAT_USE_REAL_LLM=true 启用真 LLM, 默 false 兼容 demo."""
    return (os.getenv("SPEC_CHAT_USE_REAL_LLM") or "").strip().lower() in ("1", "true", "yes", "on")


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

        # ── 3. 决定走真 LLM 还是 mock ────────────────────────────────────
        # 顺序: env 开 → 拉租户 LLM cfg → cfg 不可用 fallback mock.
        section_key = _section_key_for(body.active_chapter, section_type)
        use_real = _real_llm_enabled()
        llm_cfg: Optional[dict] = None
        cfg_load_err: Optional[str] = None
        if use_real:
            try:
                llm_cfg = await _resolve_builder_llm_cfg(
                    db,
                    ctx.tenant_id,
                    conversation_id=app.conversation_id,
                )
            except Exception as exc:  # noqa: BLE001
                cfg_load_err = repr(exc)
                logger.warning("spec_chat: _resolve_builder_llm_cfg failed: %s", exc)
            if not llm_cfg:
                logger.warning(
                    "spec_chat: 真 LLM 启用但租户 %s 没可用配置, fallback mock", ctx.tenant_id
                )
                use_real = False

        # started 事件 — 让前端日志看到走了哪条路径
        yield _sse("started", {
            "app_id": app_id,
            "active_chapter": body.active_chapter,
            "section_type": section_type,
            "section_key": section_key,
            "mock_llm": not use_real,
            "model": (llm_cfg or {}).get("model") if use_real else None,
            "provider": (llm_cfg or {}).get("provider") if use_real else None,
            "cfg_load_err": cfg_load_err,
        })

        # ── 4. 生成回复 + patch ─────────────────────────────────────────
        # 两条路径产出同形 (reply_text, intent), 后面应用 patch 用同一段代码.
        # ── 真 LLM 路径 ───────────────────────────────────────────────
        if use_real and llm_cfg is not None:
            try:
                # 拉当前 section 现有 spec, 作 LLM 上下文 (空也行, LLM 自己处理)
                existing_spec: dict = {}
                try:
                    existing = await read_spec_section(db, app_id, section_type, section_key)
                    if existing.get("ok") and existing.get("exists"):
                        raw_spec = existing.get("section", {}).get("spec_json")
                        if isinstance(raw_spec, str):
                            try:
                                existing_spec = json.loads(raw_spec)
                            except Exception:
                                existing_spec = {}
                        elif isinstance(raw_spec, dict):
                            existing_spec = raw_spec
                except Exception as exc:  # noqa: BLE001
                    logger.warning("spec_chat: read_spec_section 读现状失败: %s", exc)

                chapter_title = _CHAPTER_TITLES_FALLBACK.get(body.active_chapter, body.active_chapter)
                system_prompt = _build_llm_system_prompt(
                    chapter=body.active_chapter,
                    chapter_title=chapter_title,
                    section_type=section_type,
                    section_key=section_key,
                    existing_spec=existing_spec,
                )

                # 拼 messages (system + 截前 8 轮 history + 本次 user)
                messages: list[dict] = [{"role": "system", "content": system_prompt}]
                for turn in (body.history or [])[-8:]:
                    if turn.role in ("user", "assistant") and isinstance(turn.content, str):
                        messages.append({"role": turn.role, "content": turn.content})
                messages.append({"role": "user", "content": body.message})

                # 跑 stream — 复用 LLMClient.chat_completion_stream
                llm = LLMClient(
                    api_key=llm_cfg["api_key"],
                    base_url=llm_cfg["base_url"],
                    model=llm_cfg["model"],
                )
                full_reply = ""
                # 收集时只发"非 json 块"部分给前端 — 但流式中无法预知 json 块在哪.
                # 策略: 全部 token 都发, 前端 SpecChatPanel 不显 ```json``` 块 (它是
                # 普通 message append, ```json``` 包着的 patch 会自然嵌进文本流).
                # 不影响功能 — 前端有 diff card UI 显 patch, json 块作为"原始 LLM 输出"
                # 一起展示反而透明.
                try:
                    async for chunk_str in llm.chat_completion_stream(
                        messages,
                        max_tokens=llm_cfg.get("max_tokens", 2048),
                    ):
                        try:
                            chunk = json.loads(chunk_str)
                        except Exception:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}
                        content = delta.get("content") or ""
                        if content:
                            full_reply += content
                            yield _sse("token", {"content": content})
                except Exception as exc:
                    logger.exception("spec_chat: LLM stream failed")
                    yield _sse("error", {
                        "message": f"LLM 调用失败: {exc!r}; 可关闭 SPEC_CHAT_USE_REAL_LLM 回退 mock",
                    })
                    return

                # ── 5a. 抽 JSON patch ─────────────────────────────────────
                parsed = _extract_llm_patch(full_reply)
                if parsed is None:
                    # 解析失败 → 兜底走 mock parser, 起码让 demo flow 不死
                    logger.info(
                        "spec_chat: LLM 输出未给合法 JSON 块, fallback mock; preview=%r",
                        full_reply[:200],
                    )
                    intent = _mock_parse_intent(body.message, body.active_chapter)
                    reply_text = full_reply or _mock_reply_text(intent, body.active_chapter)
                else:
                    intent = {
                        "kind": parsed["kind"],
                        "summary": parsed["summary"] or f"修改 {section_type}",
                        "patch": parsed["patch"] or {},
                    }
                    reply_text = _strip_json_block(full_reply) or parsed["summary"]
                    # 真 LLM 给的 mcp_tool 优先, 没给 fallback 字典映射
                    if parsed.get("mcp_tool"):
                        intent["mcp_tool"] = parsed["mcp_tool"]

            except Exception as exc:
                logger.exception("spec_chat: 真 LLM 路径异常")
                yield _sse("error", {"message": f"LLM 路径异常: {exc!r}"})
                return

        # ── mock 路径 (env 不开 / cfg 不可用 / 真 LLM 兜底进来) ───────────
        else:
            intent = _mock_parse_intent(body.message, body.active_chapter)
            reply_text = _mock_reply_text(intent, body.active_chapter)
            # token-by-token 模拟 streaming (按字符切, 15ms/字)
            for ch in reply_text:
                yield _sse("token", {"content": ch})
                await asyncio.sleep(0.015)

        # ── 6. 如果有 patch, 应用到 spec_sections + 发 spec_change ──────
        applied = False
        intent_kind = intent.get("kind", "noop")
        intent_patch = intent.get("patch") or {}
        if intent_kind != "noop" and intent_kind != "other" and intent_patch:
            try:
                diff = await _apply_patch_to_section(
                    db,
                    app_id=app_id,
                    section_type=section_type,
                    section_key=section_key,
                    patch=intent_patch,
                    summary=intent.get("summary") or "",
                )
                # mcp_tool: LLM 给了就用 LLM 的, 否则走 kind 映射
                mcp_tool = intent.get("mcp_tool") or _intent_to_mcp_tool(intent_kind)
                yield _sse("spec_change", {
                    "section_type": section_type,
                    "section_key": section_key,
                    "before": diff["before"],
                    "after": diff["after"],
                    "summary": diff["summary"],
                    "created": diff.get("created", False),
                    "mcp_tool": mcp_tool,
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
            "intent_kind": intent_kind,
            "used_real_llm": use_real,
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

    真 LLM 时也可在 patch 里带 mcp_tool 字段; 没带就 fallback 到这个映射.
    """
    return {
        "add_field": "add_apaas_model_field",
        "add_role": "create_apaas_app_role",
        "add_dict_option": "add_apaas_dict_option",
        "add_menu": "create_apaas_menu",
        "add_process": "save_apaas_process",
    }.get(kind, "")


# ---------------------------------------------------------------------------
# 真 LLM — system prompt + JSON patch 抽取
# ---------------------------------------------------------------------------
#
# 复用 /config-chat-stream 同一套 LLMClient + _resolve_builder_llm_cfg, 但 prompt
# 完全不一样: spec_chat 不调 MCP 工具, 只生成 JSON patch 让 backend 自己应用到 spec_sections.
#
# LLM 输出协议:
#   1. 先正常用中文回复用户 (1-3 句话, 描述要改啥)
#   2. 末尾 ```json {"summary": "...", "patch": {...}, "mcp_tool": "..."} ``` 块
#   3. patch 结构按 section_type 不同 (见 prompt 模板里给的示例)
#
# 兜底: JSON 块抽不出 / 解析失败 → 走 mock rule-based parser, 保证 demo flow 不死.


def _build_llm_system_prompt(
    chapter: str,
    chapter_title: str,
    section_type: str,
    section_key: str,
    existing_spec: dict,
) -> str:
    """造 spec_chat 专用 system prompt.

    chapter_title 是中文章节名 (frontend 传不到 backend, 这里按 chapter 反推).
    existing_spec 是当前 section 的 spec_json (dict, 可能为空), 序列化到 prompt.
    """
    spec_json_text = json.dumps(existing_spec, ensure_ascii=False, indent=2)[:4000]
    if not existing_spec:
        spec_json_text = "(当前章节还没草稿, 这次改动会自动新建)"

    # patch 示例按 section_type 给, LLM 容易照样画
    patch_examples = {
        "data_model": (
            '{"_added_fields": [{"name": "备注", "code": "remark", "type": "VARCHAR", '
            '"required": false, "description": "AI 草稿"}]}'
        ),
        "permission": (
            '{"_added_roles": [{"name": "财务专员", "code": "R_FINANCE", '
            '"description": "AI 草稿 — 待用户调权限矩阵"}]}'
        ),
        "form": (
            '{"_added_components": [{"name": "申请人", "code": "applicant", '
            '"type": "TEXT", "required": true}]}'
        ),
        "list": (
            '{"_added_columns": [{"name": "申请日期", "code": "apply_date", '
            '"sortable": true, "width": 120}]}'
        ),
        "process": (
            '{"_added_stages": [{"name": "经理审批", "code": "manager_approve", '
            '"approver_type": "ROLE", "approver_code": "R_MANAGER"}]}'
        ),
        "page": (
            '{"_added_menus": [{"name": "新菜单", "code": "new_menu", "parent_code": null}]}'
        ),
    }
    patch_example = patch_examples.get(section_type, '{"_changes": [{"...": "..."}]}')

    return (
        "你是 SPEC 设计助手. 用户在编辑某 aPaaS 应用的 SPEC 文档草稿.\n\n"
        f"## 当前章节\n"
        f"- chapter: {chapter} (中文: {chapter_title})\n"
        f"- section_type: {section_type}\n"
        f"- section_key: {section_key}\n\n"
        "## 当前 SPEC 草稿\n"
        "```json\n"
        f"{spec_json_text}\n"
        "```\n\n"
        "## 你的任务\n"
        "用户提改动需求, 你输出:\n"
        "1. **先用 1-3 句中文回复**描述你要做的改动 (不要写代码块, 不要写 markdown 标题)\n"
        "2. **末尾紧跟一个 ```json``` 块**, 内容是 JSON patch 描述要改的内容\n\n"
        "## JSON patch 协议\n\n"
        "```json\n"
        "{\n"
        '  "summary": "1 句话总结要改什么 (UI 显示)",\n'
        '  "kind": "add_field" / "add_role" / "add_menu" / "add_process" / "add_dict_option" / "other",\n'
        '  "patch": <见下方 section_type 特定结构>,\n'
        '  "mcp_tool": "(可选) 对应的 MCP 工具名, e.g. add_apaas_model_field"\n'
        "}\n"
        "```\n\n"
        f"## 当前 section_type=\"{section_type}\" 的 patch 示例\n"
        "```json\n"
        f"{patch_example}\n"
        "```\n\n"
        "## 铁律\n"
        "- patch 只放 **增量** — 不要重复已存在的字段/角色, backend 会自动 merge 进现有 spec\n"
        "- 字段/角色/菜单的 code 用 snake_case 英文 (e.g. 'remark', 'R_FINANCE', 'borrow_apply'), 避开和现有 code 冲突\n"
        "- 不确定的字段 (type/required/length 等) 给合理默认, 别空着\n"
        "- 用户问『当前 SPEC 是什么样』这类只读问题时, kind=\"other\" + patch={} (不动 SPEC)\n"
        "- 用户说『改 / 删 / 删除』时, kind=\"other\" 暂返提示『MVP 只支持加, 改删走具体 chapter 编辑器』\n"
        "- 不要包含解释性 markdown 标题 / bullet list, 只要纯文本回复 + json 块\n"
        "- json 块必须是合法 JSON (双引号, 不带 trailing comma, 不写 comment)\n"
    )


def _extract_llm_patch(full_reply: str) -> Optional[dict]:
    """从 LLM 完整回复抽末尾的 ```json``` 块, 解析成 {summary, kind, patch, mcp_tool} dict.

    抽不出或 JSON parse 失败返 None — 调用方 fallback 到 mock parser.
    """
    if not full_reply:
        return None
    # 优先抽最后一个 ```json``` 块 (LLM 可能在文本里也出现 json 词, 取末尾最稳)
    matches = list(re.finditer(r"```json\s*(.*?)\s*```", full_reply, flags=re.DOTALL))
    if not matches:
        # 兜底: 直接找最后一个 {...} 块
        m = re.search(r"\{[^{}]*\"patch\"[^{}]*\}", full_reply, flags=re.DOTALL)
        if not m:
            return None
        raw = m.group(0)
    else:
        raw = matches[-1].group(1)

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("spec_chat: LLM JSON 块解析失败: %s; raw[:200]=%r", exc, raw[:200])
        return None
    if not isinstance(parsed, dict):
        logger.warning("spec_chat: LLM 输出不是 dict: type=%s", type(parsed).__name__)
        return None

    # 字段校验
    if "patch" not in parsed or not isinstance(parsed["patch"], dict):
        logger.warning("spec_chat: LLM 输出缺 patch 字段或非 dict")
        return None

    return {
        "kind": str(parsed.get("kind") or "other"),
        "summary": str(parsed.get("summary") or "").strip(),
        "patch": parsed["patch"],
        "mcp_tool": str(parsed.get("mcp_tool") or "").strip(),
    }


_CHAPTER_TITLES_FALLBACK = {
    "data_model": "数据模型",
    "dict": "数据字典",
    "roles": "角色权限",
    "menus": "菜单结构",
    "form": "表单设计",
    "list": "列表设计",
    "process": "流程设计",
}


def _strip_json_block(text: str) -> str:
    """LLM 回复里把 ```json``` 块剥掉, 留给前端 message 显示的"纯文本"."""
    if not text:
        return text
    return re.sub(r"```json\s*.*?\s*```", "", text, flags=re.DOTALL).strip()


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
