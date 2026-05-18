"""Vibe Coding agent loop。

跟 ai_chat/agent.py 同构（流式 / tool_calls / 跨轮重建 messages），但：
  - 没有 attachments 概念（产物是 workspace 内真实文件，agent 自己 read_file 即可）
  - 没有 artifact 表（write_file 直接落到 workspace）
  - LLM 配置走 harness/llm_resolver（不限 purpose），用户在 chat 顶部切换的模型存到 thread.selected_llm_config_id
  - thread 是 workspace 级别（不是 user 级别），消息记 user_id 标识发送者
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness.llm_resolver import resolve_llm_config, build_chat_completions_url
from app.models import (
    VibeCodingThread,
    VibeCodingMessage,
    VibeCodingToolCall,
)
from app.vibe_coding.prompts import SYSTEM_PROMPT
from app.vibe_coding.tools import TOOL_SCHEMAS, execute_tool

logger = logging.getLogger(__name__)


MAX_TURNS = 30
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_TOKENS = 8192


# ─────────────────────────── LLM 配置快照 ───────────────────────────


class _CfgSnapshot:
    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int, config_id: Optional[int]):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        self.config_id = config_id


async def _get_cfg(db: AsyncSession, thread: VibeCodingThread) -> _CfgSnapshot:
    """复用 ai-builder 的 llm_configs，不限 purpose（platform-envs 配的任何模型都能用）。"""
    resolved = await resolve_llm_config(
        db,
        thread.tenant_id,
        purpose="all",
        selected_config_id=thread.selected_llm_config_id,
    )
    if not resolved:
        raise RuntimeError(
            "找不到可用的 LLM 配置 — 请先在「平台环境 → 大模型」里配置一个并设为默认。"
        )
    return _CfgSnapshot(
        base_url=resolved.base_url,
        api_key=resolved.api_key,
        model=resolved.model,
        max_tokens=resolved.max_tokens,
        config_id=resolved.config_id,
    )


# ─────────────────────────── 流式 LLM 调用 ───────────────────────────


async def _call_llm_stream(
    cfg: _CfgSnapshot,
    messages: list[dict],
    abort_event: asyncio.Event,
    timeout: int = 240,
) -> AsyncIterator[dict]:
    """流式 chat/completions，yield:
      - {type: content_delta, text}
      - {type: tool_call_delta, index, id, name, arguments_so_far}
      - {type: done, message: {content, tool_calls}}
    """
    payload = {
        "model": cfg.model,
        "messages": messages,
        "tools": TOOL_SCHEMAS,
        "tool_choice": "auto",
        "temperature": DEFAULT_TEMPERATURE,
        "max_tokens": cfg.max_tokens,
        "stream": True,
    }
    url = build_chat_completions_url(cfg.base_url)
    accumulated = ""
    tool_buf: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10)) as client:
        async with client.stream(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=payload,
        ) as resp:
            # streaming response 在 raise_for_status 之前必须先 aread，否则
            # 上层 except 里访问 exc.response.text 会抛 "Attempted to access
            # streaming response content, without having called read()" —— 真实的
            # LLM 错误被这条 httpx 内部错误顶替，用户看不到根因
            if resp.status_code >= 400:
                await resp.aread()
                resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                if abort_event.is_set():
                    break
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    accumulated += delta["content"]
                    yield {"type": "content_delta", "text": delta["content"]}
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    buf = tool_buf.setdefault(
                        idx,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tc.get("id"):
                        buf["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        buf["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        buf["function"]["arguments"] += fn["arguments"]
                    yield {
                        "type": "tool_call_delta",
                        "index": idx,
                        "id": buf["id"],
                        "name": buf["function"]["name"],
                        "arguments_so_far": buf["function"]["arguments"],
                    }

    final_tool_calls = [tool_buf[k] for k in sorted(tool_buf.keys())]
    yield {
        "type": "done",
        "message": {
            "content": accumulated,
            "tool_calls": final_tool_calls if final_tool_calls else None,
        },
    }


# ─────────────────────────── 跨轮 messages 重建 ───────────────────────────


async def _build_initial_messages(
    db: AsyncSession,
    thread: VibeCodingThread,
    current_user_message: str,
    *,
    current_multimodal: Optional[list[dict]] = None,
    current_attachment_meta: Optional[list[dict]] = None,
) -> list[dict]:
    """把 thread 历史还原成 OpenAI messages 数组。

    - assistant 的 tool_use turn 必须带 tool_calls 字段，紧跟 role:tool 配对
    - 通过 provider_call_id 对齐 assistant.tool_calls[i].id
    - 当前 user message 单独传入，因为外部 routes 写库后不希望重读最新一条
    """
    # Phase D: prefer DB-stored prompt for agent_id='vibe' so admins can edit
    # the Vibe Coding system prompt via /agents UI; fall back to the hardcoded
    # SYSTEM_PROMPT (lazy seed inside resolve_prompt populates on first call).
    from app.services.prompt_resolver import resolve_prompt
    system_prompt = await resolve_prompt(
        db, thread.tenant_id,
        agent_id="vibe", phase="default",
        fallback=SYSTEM_PROMPT,
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    res = await db.execute(
        select(VibeCodingMessage)
        .where(VibeCodingMessage.thread_id == thread.id)
        .order_by(VibeCodingMessage.id.asc())
    )
    history = res.scalars().all()

    tc_res = await db.execute(
        select(VibeCodingToolCall)
        .where(VibeCodingToolCall.thread_id == thread.id)
        .order_by(VibeCodingToolCall.id.asc())
    )
    tcs_by_msg: dict[int, list[VibeCodingToolCall]] = {}
    for tc in tc_res.scalars().all():
        if tc.message_id is not None:
            tcs_by_msg.setdefault(tc.message_id, []).append(tc)

    # 排除最后一条（外部传 current_user_message 进来）
    for m in history[:-1]:
        if m.role == "user":
            messages.append({"role": "user", "content": m.content or ""})
        elif m.role == "assistant":
            meta = m.extra_meta or {}
            persisted_tool_calls = meta.get("tool_calls") if isinstance(meta, dict) else None
            if persisted_tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": persisted_tool_calls,
                })
                related = tcs_by_msg.get(m.id, [])
                tcs_by_call_id = {tc.provider_call_id: tc for tc in related if tc.provider_call_id}
                for ptc in persisted_tool_calls:
                    call_id = ptc.get("id")
                    if not call_id:
                        continue
                    tc_db = tcs_by_call_id.get(call_id)
                    result_content = (tc_db.result_text if tc_db else "") or ""
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_content,
                    })
            else:
                messages.append({"role": "assistant", "content": m.content or ""})

    # 当前 user message：附件存在时按 OpenAI multimodal 格式拼 content list
    text = current_user_message or ""
    # 在 text 末尾追加附件清单（无论 image 还是 file，都让 LLM 知晓）
    if current_attachment_meta:
        lines = ["", "[本轮附件]"]
        for a in current_attachment_meta:
            tag = "图片" if a.get("kind") == "image" else "文件"
            lines.append(
                f"- 【{tag}】{a.get('filename')}（{a.get('size', 0)} 字节，路径 {a.get('path')}）"
            )
        text = (text + "\n" + "\n".join(lines)).strip()

    if current_multimodal:
        # OpenAI 兼容的多模态：content 是 list，混合 text + image_url
        content_list: list[dict] = [{"type": "text", "text": text}]
        content_list.extend(current_multimodal)
        messages.append({"role": "user", "content": content_list})
    else:
        messages.append({"role": "user", "content": text})
    return messages


# ─────────────────────────── SSE 事件辅助 ───────────────────────────


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


# ─────────────────────────── 主 loop ───────────────────────────


async def run_agent(
    db: AsyncSession,
    thread: VibeCodingThread,
    current_user_message: str,
    abort_event: asyncio.Event,
    *,
    multimodal_attachments: Optional[list[dict]] = None,
    attachment_meta: Optional[list[dict]] = None,
) -> AsyncIterator[dict]:
    """跑 agent，yield SSE 事件。调用前 routes 应当已经把当前 user message 写库。

    multimodal_attachments: OpenAI 多模态 content 元素（image_url 数组），仅当轮注入。
    attachment_meta: 附件元数据列表（kind/filename/path），用于在 user message 末尾拼"附件清单"。
    """
    try:
        cfg = await _get_cfg(db, thread)
    except RuntimeError as exc:
        yield _sse("error", {"error": str(exc)})
        yield _sse("done", {"ok": False})
        return

    yield _sse("thinking", {"text": f"使用模型：{cfg.model}"})

    try:
        messages = await _build_initial_messages(
            db,
            thread,
            current_user_message,
            current_multimodal=multimodal_attachments,
            current_attachment_meta=attachment_meta,
        )
    except Exception as exc:
        yield _sse("error", {"error": f"构建上下文失败：{exc}"})
        yield _sse("done", {"ok": False})
        return

    asked_user = False

    for turn in range(MAX_TURNS):
        if abort_event.is_set():
            yield _sse("aborted", {"turn": turn})
            yield _sse("done", {"ok": False, "aborted": True})
            return

        assistant_msg: Optional[dict] = None
        try:
            async for chunk in _call_llm_stream(cfg, messages, abort_event):
                if chunk["type"] == "content_delta":
                    yield _sse("assistant_delta", {"text": chunk["text"]})
                elif chunk["type"] == "tool_call_delta":
                    yield _sse("tool_call_delta", {
                        "index": chunk["index"],
                        "name": chunk.get("name"),
                        "arguments_so_far": chunk.get("arguments_so_far") or "",
                    })
                elif chunk["type"] == "done":
                    assistant_msg = chunk["message"]
            if assistant_msg is None:
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True})
                return
        except httpx.HTTPStatusError as exc:
            # 兜底：万一 _call_llm_stream 没 aread，这里再读一次
            err_text = ""
            try:
                if not exc.response.is_closed:
                    await exc.response.aread()
                err_text = exc.response.text[:500]
            except Exception:
                err_text = "[无法读取响应体]"
            yield _sse("error", {
                "error": f"LLM 调用失败 {exc.response.status_code}: {err_text}"
            })
            yield _sse("done", {"ok": False})
            return
        except Exception as exc:
            yield _sse("error", {"error": f"LLM 调用失败：{exc}"})
            yield _sse("done", {"ok": False})
            return

        tool_calls = assistant_msg.get("tool_calls") or []
        content = (assistant_msg.get("content") or "").strip()

        # 加进 messages history 给后续轮看
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        if not tool_calls:
            # 终态：写库 final assistant 消息
            if content:
                asst_db = VibeCodingMessage(
                    thread_id=thread.id,
                    role="assistant",
                    content=content,
                )
                db.add(asst_db)
                await db.commit()
                await db.refresh(asst_db)
                yield _sse("assistant_message", {
                    "id": asst_db.id,
                    "thread_id": asst_db.thread_id,
                    "role": "assistant",
                    "content": content,
                    "created_at": asst_db.created_at.isoformat(),
                })
            yield _sse("done", {"ok": True})
            return

        # 持久化 tool_use turn（必须带 tool_calls 给跨轮重建用）
        if content:
            yield _sse("assistant_thinking_lock", {"text": content})

        asst_tool_use_db = VibeCodingMessage(
            thread_id=thread.id,
            role="assistant",
            content=content or "",
            extra_meta={"tool_calls": tool_calls},
        )
        db.add(asst_tool_use_db)
        await db.commit()
        await db.refresh(asst_tool_use_db)

        for tc in tool_calls:
            if abort_event.is_set():
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True})
                return

            tc_id = tc.get("id", "")
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}

            tc_db = VibeCodingToolCall(
                thread_id=thread.id,
                message_id=asst_tool_use_db.id,
                provider_call_id=tc_id or None,
                tool_name=tool_name,
                args_json=args,
                status="running",
                started_at=datetime.utcnow(),
            )
            db.add(tc_db)
            await db.commit()
            await db.refresh(tc_db)

            yield _sse("tool_call_start", {
                "id": tc_db.id,
                "message_id": asst_tool_use_db.id,
                "tool_name": tool_name,
                "args": args,
                "started_at": tc_db.started_at.isoformat() if tc_db.started_at else None,
            })

            try:
                result_text = await execute_tool(tool_name, args, thread, db)
                tc_db.status = "success"
                tc_db.result_text = result_text
            except Exception as exc:
                tc_db.status = "error"
                tc_db.error_message = str(exc)
                tc_db.result_text = f"错误：{exc}"
                result_text = tc_db.result_text

            tc_db.ended_at = datetime.utcnow()
            if tc_db.started_at:
                tc_db.duration_ms = int((tc_db.ended_at - tc_db.started_at).total_seconds() * 1000)
            await db.commit()
            await db.refresh(tc_db)

            yield _sse("tool_call_end", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "status": tc_db.status,
                "result_text": result_text[:800] + ("..." if len(result_text) > 800 else ""),
                "duration_ms": tc_db.duration_ms,
            })

            # ask_clarifying_question 的特殊处理：触发 ask_user 事件 + 标记暂停
            if tool_name == "ask_clarifying_question":
                try:
                    parsed = json.loads(result_text)
                    if isinstance(parsed, dict) and parsed.get("_special") == "ask_user":
                        yield _sse("ask_user", {
                            "tool_call_id": tc_db.id,
                            "question": parsed.get("question", ""),
                            "options": parsed.get("options", []),
                        })
                        asked_user = True
                except Exception:
                    pass

            # todo_write 成功 → 推送最新 todos 给前端渲染
            if tool_name == "todo_write" and tc_db.status == "success":
                yield _sse("todos_updated", {"todos": thread.todos or []})

            # run_command 后查一下 docker 沙箱端口映射 — agent 起 dev server 后前端可以立刻显示预览链接
            # 只推「既映射又监听」的端口，避免前端列出死链接
            if tool_name == "run_command" and tc_db.status == "success":
                try:
                    from app.vibe_coding.docker_runtime import get_runtime as _get_docker_runtime
                    _rt = _get_docker_runtime()
                    if await _rt.is_available():
                        _status = await _rt.container_status(thread.workspace_id)
                        if _status == "running":
                            _mapped = await _rt.all_host_ports(thread.workspace_id)
                            _listening = await _rt.listening_ports(thread.workspace_id)
                            _ports = {cp: hp for cp, hp in _mapped.items() if cp in _listening}
                            yield _sse("sandbox_ports_updated", {"ports": _ports})
                except Exception:
                    pass  # docker 不可用不影响主流程

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_text,
            })

        if asked_user:
            yield _sse("done", {"ok": True, "awaiting_user": True})
            return

    yield _sse("error", {"error": f"达到最大循环次数 {MAX_TURNS}，已停止"})
    yield _sse("done", {"ok": False})
