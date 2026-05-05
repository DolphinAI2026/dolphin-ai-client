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

# /latest-doc 响应级 cache：(user_id) → (timestamp, response_dict)
# 30s 内同一用户的轮询直接复用上次响应，不重复打 dolphin 4 个 API。
# 前端拿到 doc 后会从 5s 降到 30s 轮询，再叠加这层服务端 30s cache，dolphin
# 端实际负载 ~30s 一次，从 dolphin 视角看只剩下"用户主动停在该页面持续轮询"的
# 缓慢节奏，不会把 dolphin chat history API 打爆。
_LATEST_DOC_RESPONSE_CACHE: dict[int, tuple[float, dict]] = {}
_RESPONSE_CACHE_TTL = 30.0  # 秒


# ── markdown 提取正则 ────────────────────────────────────────────────
# 匹配 ```markdown / ```md / ``` 标题包裹的代码块（DOTALL，非贪婪）
_MD_BLOCK_RE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
# 匹配 Python `content = """..."""` 或 `content = '''...'''` 中的字符串内容
# agent 调 execute_skill_python 写沙箱 .md 时，code 字段里 md 全文以这种方式内嵌
_PY_CONTENT_RE = re.compile(
    r"""(?:content|md|text|doc)\s*=\s*(?P<q>"{3}|'{3})(?P<body>.*?)(?P=q)""",
    re.DOTALL,
)


def _looks_like_design_md(body: str) -> bool:
    """判定一段文本是不是 6 章节设计文档 — 至少含 2 个章节关键词。"""
    if not body or len(body) < 200:
        return False
    keywords = ("应用信息", "角色列表", "数据字典", "数据模型", "表单定义", "权限定义", "权限配置")
    hits = sum(1 for k in keywords if k in body)
    return hits >= 2


def _extract_md_block(text: str) -> Optional[str]:
    """从一段 assistant 文本里抓 6 章节 markdown 块；找不到返回 None。

    优先策略：找含「应用信息」「角色列表」等多标志的最长块。
    """
    if not text:
        return None
    candidates: list[str] = []
    for m in _MD_BLOCK_RE.finditer(text):
        body = m.group(1).strip()
        if _looks_like_design_md(body):
            candidates.append(body)
    if candidates:
        return max(candidates, key=len)
    # fallback: 整段文本本身可能就是 md（agent 没用 code block 包）
    if _looks_like_design_md(text):
        return text.strip()
    return None


def _extract_md_from_python_code(code: str) -> Optional[str]:
    """从 execute_skill_python 的 code 字段抽 `content = \"\"\"...\"\"\"` 里的 md。"""
    if not code:
        return None
    candidates: list[str] = []
    for m in _PY_CONTENT_RE.finditer(code):
        body = (m.group("body") or "").strip()
        if _looks_like_design_md(body):
            candidates.append(body)
    if candidates:
        return max(candidates, key=len)
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
        # dolphin 返回 id 是字符串 "82"，不是 int — 必须 int() 转换
        aid_raw = data.get("id")
        if aid_raw is None:
            return None
        try:
            aid = int(aid_raw)
        except (TypeError, ValueError):
            return None
        if aid > 0:
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
                # 收集 TEXT block 文本 + TOOLUSE 里 execute_skill_python 的 code/output
                text_parts: list[str] = []
                py_codes: list[str] = []
                py_outputs: list[str] = []
                file_name_hint = ""
                for b in blocks:
                    if b.get("type") == "TEXT" and isinstance(b.get("text"), str):
                        text_parts.append(b["text"])
                    elif b.get("type") == "TOOLUSE" and b.get("tool_status") == "COMPLETE":
                        if b.get("tool_name") != "execute_skill_python":
                            continue
                        out = b.get("tool_output") or ""
                        # tool_output 可能是 JSON string 或已解析 dict
                        out_data = out
                        if isinstance(out, str):
                            try:
                                import json as _json
                                out_data = _json.loads(out)
                            except Exception:
                                out_data = {"text": out}
                        if isinstance(out_data, dict):
                            inp = out_data.get("input") or {}
                            if isinstance(inp, dict) and isinstance(inp.get("code"), str):
                                py_codes.append(inp["code"])
                            if isinstance(out_data.get("text"), str):
                                py_outputs.append(out_data["text"])
                            # artifacts 里抽文件名
                            artifacts = out_data.get("artifacts") or []
                            for art in artifacts if isinstance(artifacts, list) else []:
                                name = (art or {}).get("name") or ""
                                if name.endswith(".md") and not file_name_hint:
                                    file_name_hint = name
                        # fallback：从原始 string 里抽 /workspace/skills/<name>.md
                        if isinstance(out, str) and not file_name_hint:
                            fm = re.search(r"/workspace/skills/([^\"\s,)]+\.md)", out)
                            if fm:
                                file_name_hint = fm.group(1)

                # 抽 md：对每个候选源单独 _extract_md_block / _extract_md_from_python_code，
                # 再按 _looks_like_design_md + 最长选最优。这样既能命中 ```markdown``` 块，
                # 也能命中"agent 直接贴整段 md 在 TEXT block 里"，还能命中沙箱代码内嵌。
                md_candidates: list[str] = []
                for txt in text_parts:
                    cand = _extract_md_block(txt)
                    if cand:
                        md_candidates.append(cand)
                for code in py_codes:
                    cand = _extract_md_from_python_code(code)
                    if cand:
                        md_candidates.append(cand)
                for out_text in py_outputs:
                    cand = _extract_md_block(out_text)
                    if cand:
                        md_candidates.append(cand)
                md = max(md_candidates, key=len) if md_candidates else None

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
    # 服务端 30s 节流：同一用户 30s 内复用上次响应，不重复打 dolphin
    now = time.time()
    cached_resp = _LATEST_DOC_RESPONSE_CACHE.get(ctx.user.id)
    if cached_resp and (now - cached_resp[0]) < _RESPONSE_CACHE_TTL:
        return cached_resp[1]

    rec = _peek_requirements_doc(ctx.user.id)
    if rec:
        resp = {
            "has_doc": True,
            "pending_id": rec["pending_id"],
            "file_name": rec["file_name"],
            "md_content": rec["md_content"],
            "score": rec.get("score", 0),
            "submitted_at": rec.get("submitted_at"),
            "source": rec.get("source") or "mcp",
        }
        _LATEST_DOC_RESPONSE_CACHE[ctx.user.id] = (now, resp)
        return resp

    # cache miss → fall back 到 dolphin chat 历史抓取
    agent_code = settings.dolphin_requirements_agent_code or ""
    extracted = await _try_extract_md_from_dolphin(db, ctx.user, agent_code)
    if not extracted:
        empty_resp = {"has_doc": False}
        _LATEST_DOC_RESPONSE_CACHE[ctx.user.id] = (now, empty_resp)
        return empty_resp

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

    resp = {
        "has_doc": True,
        "pending_id": rec["pending_id"],
        "file_name": rec["file_name"],
        "md_content": rec["md_content"],
        "score": rec["score"],
        "submitted_at": rec["submitted_at"],
        "source": rec["source"],
    }
    _LATEST_DOC_RESPONSE_CACHE[ctx.user.id] = (now, resp)
    return resp


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
    # consume 后清掉 last seen + response cache，让用户下次再聊新对话能立刻被抓到
    _LAST_SEEN_MSG_ID.pop(ctx.user.id, None)
    _LATEST_DOC_RESPONSE_CACHE.pop(ctx.user.id, None)
    return {
        "ok": True,
        "file_name": rec["file_name"],
        "md_content": rec["md_content"],
        "score": rec.get("score", 0),
    }
