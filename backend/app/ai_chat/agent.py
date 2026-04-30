"""AIChat agent loop — 接 LLM tool calling，自主决定调哪些工具直到给出 final 回答。

核心循环：
  user msg → LLM (with tools) → 看 finish_reason
    ↳ "tool_calls" → 执行每个 tool → 把 result 加 messages → 再调 LLM
    ↳ "stop"      → 输出 final assistant text → 退出 loop
    ↳ ask_user 工具调用 → 暂停（等用户答）

事件流（async generator yield 的）：
  thinking          / 一段思考文本
  tool_call_start   / 准备调某个工具
  tool_call_end     / 工具执行结果
  ask_user          / 反问，loop 暂停
  assistant_message / 最终回复
  artifact_created  / 新产出物（write_artifact 触发）
  done              / loop 完结
  error             / 异常
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

from app.crypto import decrypt_password
from app.doc_spec_standard import STANDARD_DOC_FORMAT
from app.models import (
    AIChatSession,
    AIChatMessage,
    AIChatToolCall,
    AIChatAttachment,
    AIChatArtifact,
    LLMConfig,
)
from app.ai_chat.tools import TOOL_SCHEMAS, execute_tool

logger = logging.getLogger(__name__)


# ─────────────────────────── System prompt ───────────────────────────

SYSTEM_PROMPT = f"""你是 aPaaS 平台的 AI 需求分析师，帮用户把模糊的搭建需求梳理成**可被 Builder 流水线直接解析的标准设计文档**。

工作模式：
1. 用户上传材料后，主动调 read_attachment 读取每个相关附件
2. 数据类材料（xlsx/csv）可用 run_python 编程分析（pandas / openpyxl 都能用）
3. 必要时调 ask_clarifying_question 反问用户澄清需求边界，每次最多 1-2 个关键问题
4. 当需求清晰后，调 write_artifact 输出 markdown 设计文档；filename 建议 `{{应用名}}-设计文档.md`

⚠️ 你产出的 markdown 会被 aPaaS Builder 的 doc_pipeline 直接解析、自动生成模型/表单/角色/权限。
**必须严格遵循下面的章节顺序、表格列名、字段编码命名约束**——任何偏差都会让 Builder 解析失败、退化到 LLM 兜底（慢且不准）。

{STANDARD_DOC_FORMAT}

## 输出准则（除上面格式硬约束外）
- 主动用工具，不要让用户反复催促
- 一次回复里可以连续调多个工具（并行）
- 不要凭空捏造，所有结论都基于读到的材料 + 用户确认的边界
- 反问要少而精，只问真正影响设计的关键点
- 输出 md 时严格按上面 6 个章节顺序，章节不能跳过；缺信息留空单元格即可，不要写"未定义"、"待定"占位文字
- 模型/表单/字段命名：英文 snake_case + 业务前缀（避免 name/status 这种通用字段直接用，要 ncr_status / supplier_name）
- **应用编码（appCode）必须满足**：只允许小写字母 / 数字 / 中划线 `-`，以小写字母开头，长度 ≤ 17 字符（正则 `^[a-z][a-z0-9-]{0,16}$`）。**禁止下划线**。如果业务名很长，要主动缩写（如"电力设备管理系统" → `power-equip-mgmt` 或 `power-equip` 而不是 `power_equipment_management`）
- 数据模型只描述"字段在数据库怎么存"，不要在数据模型表里写字典/关联/组件，那些都在「五、表单定义」里
- 数据单选/数据选择/关联表单字段引用的目标模型，必须先在 ## 四、数据模型 里建出来；没材料支持就不要写这种引用，改用单行输入

附件信息会在用户消息后附上"[已上传附件]"列表，告诉你有哪些可以读。"""


# ─────────────────────────── LLM 调用辅助 ───────────────────────────

class LLMConfigSnapshot:
    """快照 LLMConfig 的解密信息，避免 db 异步调用穿透到 httpx。"""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature


async def _resolve_llm_config(
    db: AsyncSession, session: AIChatSession
) -> LLMConfigSnapshot:
    """优先用 session.selected_llm_config_id；没指定则取该 tenant 的 default。"""
    cfg: Optional[LLMConfig] = None
    if session.selected_llm_config_id:
        res = await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == session.selected_llm_config_id,
                LLMConfig.tenant_id == session.tenant_id,
            )
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        # fallback：tenant default
        res = await db.execute(
            select(LLMConfig)
            .where(
                LLMConfig.tenant_id == session.tenant_id,
                LLMConfig.is_default == True,  # noqa: E712
                LLMConfig.status == "active",
            )
            .limit(1)
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        raise RuntimeError(
            "找不到可用的 LLM 配置，请先在「大模型管理」里配置一个并设为默认。"
        )
    return LLMConfigSnapshot(
        base_url=cfg.base_url,
        api_key=decrypt_password(cfg.api_key_enc),
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )


async def generate_title(
    db: AsyncSession,
    session: AIChatSession,
    user_message: str,
) -> Optional[str]:
    """根据用户首条消息生成 ≤24 字的会话标题。失败返回 None。"""
    try:
        cfg = await _resolve_llm_config(db, session)
    except Exception:
        return None
    prompt = (
        "请根据用户的下一条消息，用 不超过 16 个汉字 概括会话主题，"
        "直接输出标题文本本身（不要带引号、前缀或解释）。\n\n"
        f"用户消息：{user_message[:300]}"
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=20, write=10, pool=10)) as client:
            resp = await client.post(
                f"{cfg.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 60,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        title = (data["choices"][0]["message"].get("content") or "").strip()
        # 清理引号 / 多余前缀
        title = title.strip(' "\'`「」')
        if len(title) > 30:
            title = title[:30]
        return title or None
    except Exception as e:
        logger.warning("generate_title failed: %s", e)
        return None


async def _call_llm(
    cfg: LLMConfigSnapshot,
    messages: list[dict],
    tools: list[dict],
    timeout: int = 120,
) -> dict:
    """non-streaming chat completion + tool calling。返回 OpenAI 格式 response.choices[0].message"""
    payload = {
        "model": cfg.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10)) as client:
        resp = await client.post(
            f"{cfg.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]


async def _call_llm_stream(
    cfg: LLMConfigSnapshot,
    messages: list[dict],
    tools: list[dict],
    abort_event: asyncio.Event,
    timeout: int = 180,
) -> AsyncIterator[dict]:
    """流式 chat completion。yield 事件字典：

    - {"type": "content_delta", "text": "..."}
    - {"type": "tool_call_delta", "index": int, "id": str|None, "name": str|None, "arguments": str|None}
    - {"type": "done", "message": {content, tool_calls}}

    上层 run_agent 拼装好 final message 之后再走持久化。
    """
    payload = {
        "model": cfg.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": True,
    }
    accumulated_content = ""
    tool_buf: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10)) as client:
        async with client.stream(
            "POST",
            f"{cfg.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=payload,
        ) as resp:
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
                    text = delta["content"]
                    accumulated_content += text
                    yield {"type": "content_delta", "text": text}
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
            "content": accumulated_content,
            "tool_calls": final_tool_calls if final_tool_calls else None,
        },
    }


# ─────────────────────────── 构建 agent 输入 ───────────────────────────

async def _build_initial_messages(
    db: AsyncSession, session: AIChatSession, current_user_message: str
) -> list[dict]:
    """从历史消息 + 当前 user message 构造 LLM messages。"""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 历史消息（不含本次 user 消息——routes 已经写库了，这里读回来时要排除最新那条）
    res = await db.execute(
        select(AIChatMessage)
        .where(AIChatMessage.session_id == session.id)
        .order_by(AIChatMessage.id.asc())
    )
    history = res.scalars().all()
    for m in history[:-1]:  # 排除最后一条（最新 user message，外部传 current_user_message）
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})

    # 拼接附件清单到当前用户消息（让 LLM 知道有哪些附件可读）
    att_res = await db.execute(
        select(AIChatAttachment).where(AIChatAttachment.session_id == session.id)
    )
    attachments = att_res.scalars().all()
    suffix = ""
    if attachments:
        items = []
        for a in attachments:
            badge = "图片" if a.kind == "image" else f"{a.kind}"
            items.append(f"- 【{badge}】{a.filename}")
        suffix = "\n\n[已上传附件，可用 read_attachment 工具读取]\n" + "\n".join(items)

    messages.append({"role": "user", "content": (current_user_message or "") + suffix})
    return messages


# ─────────────────────────── 主 agent loop ───────────────────────────

MAX_TURNS = 20  # 工具循环最大轮数


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def run_agent(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
) -> AsyncIterator[dict]:
    """主 agent loop。yield SSE 事件给 routes 转发到前端。"""
    try:
        cfg = await _resolve_llm_config(db, session)
    except RuntimeError as e:
        yield _sse("error", {"error": str(e)})
        yield _sse("done", {"ok": False})
        return

    yield _sse("thinking", {"text": f"使用模型：{cfg.model}"})

    try:
        messages = await _build_initial_messages(db, session, current_user_message)
    except Exception as e:
        yield _sse("error", {"error": f"构建上下文失败：{e}"})
        yield _sse("done", {"ok": False})
        return

    asked_user = False  # 一旦 ask_user，loop 提前退出

    for turn in range(MAX_TURNS):
        if abort_event.is_set():
            yield _sse("aborted", {"turn": turn})
            yield _sse("done", {"ok": False, "aborted": True})
            return

        # 流式调用 LLM，逐 token 把 content_delta 推给前端
        assistant_msg: Optional[dict] = None
        try:
            async for chunk in _call_llm_stream(cfg, messages, TOOL_SCHEMAS, abort_event):
                if chunk["type"] == "content_delta":
                    yield _sse("assistant_delta", {"text": chunk["text"]})
                elif chunk["type"] == "tool_call_delta":
                    yield _sse(
                        "tool_call_delta",
                        {
                            "index": chunk["index"],
                            "name": chunk.get("name"),
                            "arguments_so_far": chunk.get("arguments_so_far") or "",
                        },
                    )
                elif chunk["type"] == "done":
                    assistant_msg = chunk["message"]
            if assistant_msg is None:
                # 流被外部 abort 了
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True})
                return
        except httpx.HTTPStatusError as e:
            yield _sse("error", {"error": f"LLM 调用失败 {e.response.status_code}: {e.response.text[:300]}"})
            yield _sse("done", {"ok": False})
            return
        except Exception as e:
            yield _sse("error", {"error": f"LLM 调用失败：{e}"})
            yield _sse("done", {"ok": False})
            return

        tool_calls = assistant_msg.get("tool_calls") or []
        content = (assistant_msg.get("content") or "").strip()

        # 把 LLM 的回复加进 messages history（让下一轮看到）
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        # 没有工具调用：output final 文本然后结束
        if not tool_calls:
            if content:
                # 持久化 assistant message
                asst_db = AIChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=content,
                )
                db.add(asst_db)
                await db.commit()
                await db.refresh(asst_db)
                yield _sse("assistant_message", {
                    "id": asst_db.id,
                    "session_id": asst_db.session_id,
                    "role": "assistant",
                    "content": content,
                    "created_at": asst_db.created_at.isoformat(),
                })
            yield _sse("done", {"ok": True})
            return

        # 有工具调用：每个执行一遍
        # 注：tool 之前的 content 已经通过 assistant_delta 流式推过了，
        # 前端会在 tool_call_start 时把 streaming buffer 锁定为一段"思考"
        if content:
            yield _sse("assistant_thinking_lock", {"text": content})

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

            # 持久化工具调用记录
            tc_db = AIChatToolCall(
                session_id=session.id,
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
                "tool_name": tool_name,
                "args": args,
                "started_at": tc_db.started_at.isoformat() if tc_db.started_at else None,
            })

            # 执行
            try:
                result_text = await execute_tool(tool_name, args, session, db)
                tc_db.status = "success"
                tc_db.result_text = result_text
            except Exception as e:
                tc_db.status = "error"
                tc_db.error_message = str(e)
                tc_db.result_text = f"错误：{e}"
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
                "result_text": result_text[:600] + ("..." if len(result_text) > 600 else ""),
                "duration_ms": tc_db.duration_ms,
            })

            # 特殊：write_artifact 成功 → 单独通知前端刷新右栏
            if tool_name == "write_artifact" and tc_db.status == "success":
                # 拿最新版本
                from sqlalchemy import desc as _desc
                res = await db.execute(
                    select(AIChatArtifact)
                    .where(
                        AIChatArtifact.session_id == session.id,
                        AIChatArtifact.filename == args.get("filename"),
                    )
                    .order_by(_desc(AIChatArtifact.version))
                    .limit(1)
                )
                art = res.scalar_one_or_none()
                if art:
                    yield _sse("artifact_created", {
                        "id": art.id,
                        "filename": art.filename,
                        "format": art.format,
                        "version": art.version,
                        "preview": art.content[:200],
                    })

            # 特殊：ask_clarifying_question → loop 暂停等用户
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

            # 把 tool_result 喂回 messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_text,
            })

        if asked_user:
            # 提了问题就停 loop，等下一轮 user send
            yield _sse("done", {"ok": True, "awaiting_user": True})
            return

    # 超过 MAX_TURNS
    yield _sse("error", {"error": f"达到最大循环次数 {MAX_TURNS}，已停止"})
    yield _sse("done", {"ok": False})
