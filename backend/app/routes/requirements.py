"""需求分析助手 → ai-builder 中转。

两条数据来源（前端 GET /requirements/latest-doc 一次返回，对前端透明）：

1. **MCP 推送**：dolphin agent 81 调 mcp_server.submit_design_doc 工具时
   把 md 写进 cache。最快路径，但当前因 dolphin 平台 MCP 注册表缓存
   暂不可用。

2. **自动抓取**：cache 为空时，用用户的 dolphin 镜像 token 调 dolphin chat
   历史 API 拉最近一次对话，从最后一条 ASSISTANT 消息的 TEXT block 里
   正则提取 ```markdown ... ``` 块。这是当前主要数据源。

前端点「→ Builder」时 POST consume-doc/{pid} 把 cache 拿走，避免下次
轮询又显示同一份。
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.mcp_server import (
    _REQUIREMENTS_DOC_CACHE,
    _consume_requirements_doc,
    _do_validate_builder_doc,
    _peek_requirements_doc,
)
from app.services.dolphin_user import get_user_dolphin_credentials

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/requirements", tags=["requirements-assistant"])


# agent_code → agent_id (release_id) 的进程内缓存（避免每次轮询都查 runtime）
_AGENT_ID_CACHE: dict[str, int] = {}

# session_id → 上次拉到的最后一条 assistant message id；用作"消息是否变化"的去重 key
_LAST_SEEN_MSG_ID: dict[int, str] = {}  # ai_builder_user_id → last assistant message id


# ── markdown 提取正则 ────────────────────────────────────────────────
# 匹配 ```markdown / ```md / ``` 标题包裹的代码块（DOTALL，非贪婪）
_MD_BLOCK_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def _extract_md_block(text: str) -> Optional[str]:
    """从一段 assistant 文本里抓 6 章节 markdown 块；找不到返回 None。

    优先策略：找含「一、应用信息」「二、角色列表」等标志的最长块。
    """
    if not text:
        return None
    candidates: list[str] = []
    for m in _MD_BLOCK_RE.finditer(text):
        body = m.group(1).strip()
        if body and ("应用信息" in body or "角色列表" in body or "数据模型" in body):
            candidates.append(body)
    if candidates:
        return max(candidates, key=len)
    # fallback: 整段文本本身可能就是 md（agent 没用 code block 包）
    if "## 一、应用信息" in text or "应用信息" in text and "角色列表" in text:
        return text.strip()
    return None


# ── dolphin chat 历史抓取 ────────────────────────────────────────────


async def _resolve_agent_id(client: httpx.AsyncClient, agent_code: str) -> Optional[int]:
    """用 agent_code 拿 release agent_id（dolphin sessions API 用 agent_id 而非 code）。"""
    if agent_code in _AGENT_ID_CACHE:
        return _AGENT_ID_CACHE[agent_code]
    try:
        r = await client.get(f"/api/agentChat/agent/run/runtime/{agent_code}")
        if r.status_code != 200:
            return None
        data = r.json() or {}
        aid = data.get("id")
        if isinstance(aid, int) and aid > 0:
            _AGENT_ID_CACHE[agent_code] = aid
            return aid
    except Exception as exc:
        logger.warning("dolphin runtime 拿 agent_id 失败: %s", exc)
    return None


async def _try_extract_md_from_dolphin(
    db: AsyncSession, user, agent_code: str
) -> Optional[dict]:
    """从 dolphin 当前用户最新 session 的最后一条 ASSISTANT 消息抽 md。

    返回 None：没找到 / 无变化 / dolphin 调用失败。
    返回 dict：{file_name, md_content, score, message_id}
    """
    if not agent_code:
        return None
    try:
        access_token, _dolphin_uid = await get_user_dolphin_credentials(db, user)
    except Exception as exc:
        logger.info("拿 dolphin 镜像 token 失败 user=%s: %s", user.id, exc)
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Tenant-Id": settings.dolphin_tenant_id or "default",
    }
    base = settings.dolphin_server_url.rstrip("/")

    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=15.0) as cli:
        agent_id = await _resolve_agent_id(cli, agent_code)
        if not agent_id:
            return None

        # 拉用户最新 sessions（最多 3 个，dolphin 默认按 last_update_date desc）
        try:
            r = await cli.get(
                "/api/agentChat/agent/run/sessions",
                params={"agent_id": agent_id, "page": 1, "size": 3},
            )
            if r.status_code != 200:
                return None
            sessions = (r.json() or {}).get("content") or []
        except Exception as exc:
            logger.info("dolphin sessions 拉取失败: %s", exc)
            return None
        if not sessions:
            return None

        # 在最近 3 个 session 里找含 markdown 块的最新 ASSISTANT 消息
        for sess in sessions:
            sid = sess.get("session_id") or sess.get("id")
            if not sid:
                continue
            try:
                rm = await cli.get(
                    f"/api/agentChat/agent/run/sessions/{sid}/messages",
                    params={"page": 1, "size": 50},
                )
                if rm.status_code != 200:
                    continue
                msgs = (rm.json() or {}).get("content") or []
            except Exception as exc:
                logger.info("dolphin messages 拉取失败 sid=%s: %s", sid, exc)
                continue

            # 倒序找最近的 ASSISTANT 消息（messages 通常按时间正序，倒着遍历更快命中最新）
            for msg in reversed(msgs):
                if msg.get("role") != "ASSISTANT":
                    continue
                blocks = msg.get("blocks") or []
                # 拼所有 TEXT block 的 text
                text_parts: list[str] = []
                file_name_hint = ""
                for b in blocks:
                    if b.get("type") == "TEXT" and isinstance(b.get("text"), str):
                        text_parts.append(b["text"])
                    elif b.get("type") == "TOOLUSE" and b.get("tool_status") == "COMPLETE":
                        # 顺便从 execute_skill_python 输出里抓沙箱文件名
                        out = b.get("tool_output") or ""
                        if isinstance(out, str) and "/workspace/skills/" in out:
                            fm = re.search(r"/workspace/skills/([^\"\\s,)]+\.md)", out)
                            if fm:
                                file_name_hint = fm.group(1)
                full_text = "\n\n".join(text_parts)
                md = _extract_md_block(full_text)
                if md:
                    score = (_do_validate_builder_doc(md) or {}).get("score", 0)
                    # 从 md H1 推 file_name；fallback 到沙箱文件名 / 通用
                    fname = file_name_hint or "design-doc.md"
                    h1 = re.search(r"^\s*#\s+([^\n]+?)\s*$", md, re.MULTILINE)
                    if h1 and not file_name_hint:
                        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", h1.group(1).strip())[:40]
                        if slug:
                            fname = f"{slug.lower().strip('-')}-design.md"
                    return {
                        "file_name": fname,
                        "md_content": md,
                        "score": score,
                        "message_id": msg.get("id"),
                    }
        return None


# ── HTTP routes ──────────────────────────────────────────────────────


@router.get("/latest-doc")
async def get_latest_requirements_doc(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """前端轮询 — 拿当前用户从需求分析助手「最新」的设计文档。

    优先 mcp_server cache（agent 主动 submit_design_doc）；空时自动抓 dolphin
    chat 历史里最近一次 ASSISTANT 消息的 markdown 块。

    返回 has_doc=False 时前端右侧面板显示空态（粘贴引导）。
    """
    rec = _peek_requirements_doc(ctx.user.id)
    if rec:
        return {
            "has_doc": True,
            "pending_id": rec["pending_id"],
            "file_name": rec["file_name"],
            "md_content": rec["md_content"],
            "score": rec.get("score", 0),
            "submitted_at": rec.get("submitted_at"),
            "source": rec.get("source") or "mcp",
        }

    # cache miss → fall back 到 dolphin chat 历史抓取
    agent_code = settings.dolphin_requirements_agent_code or ""
    extracted = await _try_extract_md_from_dolphin(db, ctx.user, agent_code)
    if not extracted:
        return {"has_doc": False}

    msg_id = extracted.get("message_id") or ""
    # 同一消息别再重复"提示用户"（前端 ElMessage.success 在 pending_id 变时弹）
    # 给同一 message id 复用稳定 pending_id（hash 前 12 位）
    pending_id = uuid.uuid5(uuid.NAMESPACE_URL, f"dolphin-msg:{msg_id}").hex[:16]

    rec = {
        "pending_id": pending_id,
        "file_name": extracted["file_name"],
        "md_content": extracted["md_content"],
        "score": extracted.get("score", 0),
        "submitted_at": time.time(),
        "source": "dolphin-chat-history",
        "tenant_id": ctx.tenant_id,
    }
    # 写 cache 让前端"→ Builder"的 consume 能命中；下次轮询也快
    _REQUIREMENTS_DOC_CACHE[ctx.user.id] = rec
    _LAST_SEEN_MSG_ID[ctx.user.id] = msg_id

    return {
        "has_doc": True,
        "pending_id": rec["pending_id"],
        "file_name": rec["file_name"],
        "md_content": rec["md_content"],
        "score": rec["score"],
        "submitted_at": rec["submitted_at"],
        "source": rec["source"],
    }


@router.post("/consume-doc/{pending_id}")
async def consume_requirements_doc(
    pending_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """点「→ Builder」之后调一次：从 cache 拿走 md，避免后续轮询又显示同一份。

    校验 pending_id：用户在 dolphin 反复修改时 cache 会更新到新 pending_id，
    旧的请求传过来要被拒绝（防止用户跳过去后又跳错版本）。
    """
    rec = _consume_requirements_doc(ctx.user.id, pending_id)
    if not rec:
        raise HTTPException(404, "no pending design doc for this user, or pending_id mismatch")
    # consume 后清掉 last seen，让用户下次再聊新对话能再被自动抓到
    _LAST_SEEN_MSG_ID.pop(ctx.user.id, None)
    return {
        "ok": True,
        "file_name": rec["file_name"],
        "md_content": rec["md_content"],
        "score": rec.get("score", 0),
    }
