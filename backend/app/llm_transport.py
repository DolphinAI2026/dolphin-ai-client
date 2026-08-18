"""app/llm_transport.py — 共享的 OpenAI 兼容 LLM transport 层。

把 ai_chat/agent.py 那套最完善的 httpx 流式栈抽出来,让散落在
ai_chat / builder_spec / coding/pipeline / coding/read_query 的多份重写
收口到一处:

- OpenAI 兼容流式调用(httpx SSE 解析 / [DONE] / delta.content 累积 /
  tool_calls 按 index 累积 / usage chunk 采集)
- 可重试错误分类
- provider payload 兼容(enable_thinking 等)
- 非流式调用

接口设计成两种用法都能服务:
- 手写循环 → ``stream_chunks`` yield 归一化事件 dict
  ({"type":"content_delta"|"tool_call_delta"|"done", ...})
- 「累积到完整响应」→ ``stream_raw_sse_lines`` yield 原始 SSE 行
  (builder_spec 的 _open_stream / read_query 的 _stream_llm 各自解析),
  以及 ``complete`` 非流式拿 message。

故意只依赖 ``httpx`` 模块本身(运行时按全局查 ``httpx.AsyncClient``),
让既有测试对 ``httpx.AsyncClient`` 的 monkeypatch 继续生效。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from app.llm_reasoning import ReasoningSplitter, strip_think_blocks

import httpx

logger = logging.getLogger(__name__)

# ai_chat 历史默认:每次调用最多重试 2 次(含首发)。
DEFAULT_RETRY_ATTEMPTS = 2
_LLM_DIAGNOSTIC_MAX_VALUE_CHARS = 16_000
_LLM_DIAGNOSTIC_MAX_BODY_CHARS = 4_000
_LLM_DIAGNOSTIC_SENSITIVE_KEYS = (
    "authorization", "api_key", "apikey", "token", "secret", "password",
    "credential", "private_key", "kubeconfig",
)
_LLM_DIAGNOSTIC_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[^\s,;]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(https?://)[^/@\s]+@"), r"\1<redacted>@"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "<redacted-api-key>"),
    (re.compile(r"(?im)^([ \t]*(?:token|password|client-key-data|client-certificate-data|certificate-authority-data)\s*:\s*).*$"), r"\1<redacted>"),
    (re.compile(r"(?i)([\"']?(?:token|password|secret|api[_-]?key|kubeconfig|client[_-]?key[_-]?data)[\"']?\s*[:=]\s*[\"']?)[^\"',\n}\]]+"), r"\1<redacted>"),
)


class LLMEmptyResponseError(RuntimeError):
    """The gateway accepted a request but returned no usable response body."""


def _redact_diagnostic_text(value: str, *, limit: int = _LLM_DIAGNOSTIC_MAX_VALUE_CHARS) -> str:
    text = str(value or "")
    for pattern, replacement in _LLM_DIAGNOSTIC_SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        return text[:limit] + f"… [truncated; original_chars={len(text)}]"
    return text


def _safe_diagnostic_value(value: Any, *, key: str = "") -> Any:
    normalized = str(key).lower().replace("-", "_")
    if any(part in normalized for part in _LLM_DIAGNOSTIC_SENSITIVE_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _safe_diagnostic_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_diagnostic_value(item) for item in value]
    if isinstance(value, str):
        return _redact_diagnostic_text(value)
    return value


def _diagnostic_log_path() -> Path | None:
    """Return the durable local diagnostic log only where a data root exists."""
    try:
        from app import runtime
        root = runtime.desktop_data_dir() if runtime.is_desktop() else runtime.server_data_dir()
    except Exception:  # pragma: no cover - diagnostics must never break an LLM call
        return None
    return (root / "logs" / "llm-diagnostics.jsonl") if root else None


def _write_llm_diagnostic(record: dict[str, Any]) -> None:
    """Persist a bounded, redacted JSONL record without making logging a failure path."""
    try:
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        path = _diagnostic_log_path()
        if path is not None:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Keep one previous file for comparison while preventing a broken
            # gateway from filling the desktop data directory indefinitely.
            if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
                previous = path.with_suffix(".previous.jsonl")
                os.replace(path, previous)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (encoded + "\n").encode("utf-8"))
            finally:
                os.close(fd)
        logger.error("LLM_DIAGNOSTIC %s", encoded)
    except Exception:  # pragma: no cover - diagnostic recording is best-effort
        logger.exception("failed to write LLM diagnostic record")


def log_llm_failure(
    *,
    transport: str,
    target: str,
    payload: dict[str, Any],
    exc: Exception,
    attempt: int,
    response: httpx.Response | None = None,
) -> None:
    """Record request/response evidence for model failures, with credentials removed.

    The full payload shape is retained (including messages and tool schemas) so
    empty-200 and provider compatibility bugs can be reproduced from the local
    log.  Secrets are redacted and values are bounded before either disk or the
    regular process log sees them.
    """
    if getattr(exc, "_llm_diagnostic_logged", False):
        return
    try:
        setattr(exc, "_llm_diagnostic_logged", True)
    except Exception:
        pass
    metadata: dict[str, Any] = {}
    if response is not None:
        metadata = {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "request_id": response.headers.get("x-request-id") or response.headers.get("request-id"),
            "body_chars": len(response.content or b""),
            "body_preview": _redact_diagnostic_text(
                response.text or "", limit=_LLM_DIAGNOSTIC_MAX_BODY_CHARS,
            ),
        }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "llm_request_failed",
        "transport": transport,
        "attempt": attempt,
        "target": _redact_diagnostic_text(target, limit=2_000),
        "request": _safe_diagnostic_value(payload),
        "error_type": exc.__class__.__name__,
        "error": _redact_diagnostic_text(str(exc), limit=_LLM_DIAGNOSTIC_MAX_BODY_CHARS),
        "response": metadata or None,
    }
    _write_llm_diagnostic(record)


# ─────────────────────────── 错误分类 / 文案 ───────────────────────────


def is_retryable_llm_error(exc: Exception) -> bool:
    """网络瞬态错误才重试;HTTP 4xx/5xx(HTTPStatusError)不在此列。"""
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
            LLMEmptyResponseError,
        ),
    )


async def sleep_before_retry(attempt: int) -> None:
    await asyncio.sleep(0.8 * (attempt + 1))


def format_llm_error(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectError):
        return "连接模型网关失败，请稍后重试或检查模型服务网络。"
    if isinstance(exc, httpx.ConnectTimeout):
        return "连接模型网关超时，请稍后重试或检查模型服务网络。"
    if isinstance(exc, httpx.ReadError):
        return "模型网关读取响应失败，请稍后重试。"
    if isinstance(exc, httpx.ReadTimeout):
        return "模型网关响应超时，请稍后重试。"
    if isinstance(exc, httpx.WriteTimeout):
        return "向模型网关发送请求超时，请稍后重试。"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "模型网关连接中途断开，未返回完整响应，请稍后重试。"
    detail = str(exc).strip()
    return detail or exc.__class__.__name__


# ─────────────────────────── provider 兼容 ───────────────────────────


def apply_provider_payload_compat(model: str, base_url: str, payload: dict) -> dict:
    """按 provider 给 payload 打兼容补丁(原地改 + 返回同对象)。

    目前只有 qwen3 / dashscope 需要 ``enable_thinking=False``(否则思考模型
    会拖慢且污染输出)。历史上这个补丁散在 ai_chat / read_query 两处,
    分类器和 brainstorm 漏了 → 收口到这里,所有走 transport 的调用都覆盖。
    """
    m = (model or "").lower()
    b = (base_url or "").lower()
    if "qwen3" in m or "dashscope.aliyuncs.com" in b:
        payload["enable_thinking"] = False
    return payload


# ─────────────────────────── URL 归一化 ───────────────────────────


def chat_completions_url(base_url: str) -> str:
    """归一到 OpenAI 兼容 ``/chat/completions`` 端点。

    复用 routes.llm_configs.build_llm_chat_completions_url 的语义,避免再分叉。
    """
    from app.routes.llm_configs import build_llm_chat_completions_url

    return build_llm_chat_completions_url(base_url)


# ─────────────────────────── 流式增量合并 ───────────────────────────


def merge_tool_call_delta(acc: list[dict], delta_tool_calls: list[dict]) -> None:
    """OpenAI 流式 tool_calls 增量合并:按 index 聚合 id / name / arguments 片段。

    acc 元素结构: {"id", "type":"function", "function":{"name","arguments"}}。
    name / arguments 都是**累加**(分片到达),id 后到覆盖。
    """
    for d in delta_tool_calls or []:
        try:
            idx = int(d.get("index") or 0)
        except (TypeError, ValueError):
            idx = 0
        while len(acc) <= idx:
            acc.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        slot = acc[idx]
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


# ─────────────────────────── payload 构造 ───────────────────────────


def build_chat_payload(
    *,
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[str] = "auto",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    include_usage: bool = False,
    base_url: str = "",
    extra: Optional[dict] = None,
) -> dict:
    """构造 OpenAI 兼容 chat/completions payload + provider 兼容补丁。

    只在对应参数非 None 时落字段,尽量贴近各调用点原始 payload,避免
    引入它们以前没传的键(行为等价优先)。
    """
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if stream:
        payload["stream"] = True
        if include_usage:
            payload["stream_options"] = {"include_usage": True}
    else:
        payload["stream"] = False
    if extra:
        payload.update(extra)
    apply_provider_payload_compat(model, base_url, payload)
    return payload


def _headers(
    api_key: str,
    *,
    stream: bool = False,
    extra_headers: Optional[dict[str, str]] = None,
) -> dict:
    h = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if stream:
        h["Accept"] = "text/event-stream"
    if extra_headers:
        h.update(extra_headers)
    return h


# ─────────────────────────── 原始 SSE 行流 ───────────────────────────


async def stream_raw_sse_lines(
    *,
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: httpx.Timeout | float,
    url: Optional[str] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> AsyncIterator[str]:
    """打开 chat/completions 流,逐行 yield 原始 SSE 行(含 ``data:`` 前缀)。

    给「自己解析 SSE」的调用方用(builder_spec._open_stream /
    read_query._stream_llm)。非 200 先读完 body 再抛,避免 ResponseNotRead
    把真错盖住。``url`` 缺省时按 base_url 拼 ``/chat/completions``。
    """
    target = url or f"{base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            target,
            headers=_headers(api_key, stream=True, extra_headers=extra_headers),
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(
                    f"LLM API {resp.status_code}: {body[:300].decode(errors='replace')}"
                )
            async for line in resp.aiter_lines():
                yield line


# ─────────────────────────── 归一化 chunk 流 ───────────────────────────


async def _stream_chunks_once(
    *,
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: httpx.Timeout | float,
    abort_event: Optional[asyncio.Event],
    url: Optional[str] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> AsyncIterator[dict]:
    """单次(不含重试)流式调用,yield 归一化事件。

    事件:
      {"type":"content_delta","text": str}
      {"type":"tool_call_delta","index":int,"id":str,"name":str,"arguments_so_far":str}
      {"type":"done","message":{content,tool_calls},"usage":dict|None}
    """
    target = url or f"{base_url.rstrip('/')}/chat/completions"
    accumulated_content = ""
    usage_data: Optional[dict] = None
    tool_buf: dict[int, dict] = {}
    received_event = False
    # MiniMax 等把 reasoning 内联进 content 用 <think>...</think> 包裹 → 增量分离,
    # 让 content_delta / 累积 content 干净(不泄漏 <think> 进消息/标题)。
    reasoning_splitter = ReasoningSplitter()

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            target,
            headers=_headers(api_key, stream=True, extra_headers=extra_headers),
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                error = httpx.HTTPStatusError(
                    f"LLM API {resp.status_code}", request=resp.request, response=resp,
                )
                log_llm_failure(
                    transport="chat_completions_stream", target=target, payload=payload,
                    exc=error, attempt=1, response=resp,
                )
                raise error
            async for raw_line in resp.aiter_lines():
                if abort_event is not None and abort_event.is_set():
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
                received_event = True
                # usage chunk:choices 为空、带 usage(include_usage 开启后 [DONE] 前到达)
                if chunk.get("usage"):
                    usage_data = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                # DeepSeek 等用独立 reasoning_content 字段 → 单独走,不进 content。
                rc = delta.get("reasoning_content")
                if rc:
                    yield {"type": "reasoning_delta", "text": rc}
                if delta.get("content"):
                    visible, reasoning = reasoning_splitter.feed(delta["content"])
                    if reasoning:
                        yield {"type": "reasoning_delta", "text": reasoning}
                    if visible:
                        accumulated_content += visible
                        yield {"type": "content_delta", "text": visible}
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

    if not received_event:
        raise LLMEmptyResponseError("模型服务返回 HTTP 200，但流式响应没有任何有效 SSE 事件")

    # 流结束:吐出 splitter 残留(未闭合 <think> 残文不丢,作 reasoning)。
    tail_visible, tail_reasoning = reasoning_splitter.flush()
    if tail_reasoning:
        yield {"type": "reasoning_delta", "text": tail_reasoning}
    if tail_visible:
        accumulated_content += tail_visible
        yield {"type": "content_delta", "text": tail_visible}

    final_tool_calls = [tool_buf[k] for k in sorted(tool_buf.keys())]
    yield {
        "type": "done",
        "message": {
            "content": accumulated_content,
            "tool_calls": final_tool_calls if final_tool_calls else None,
        },
        "usage": usage_data,
    }


async def stream_chunks(
    *,
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: httpx.Timeout | float,
    abort_event: Optional[asyncio.Event] = None,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    url: Optional[str] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> AsyncIterator[dict]:
    """带瞬态错误重试的归一化流式调用。

    一旦已经吐出过任何 chunk(emitted_anything)就不再重试,避免把半截输出
    重放成重复内容 —— 与 ai_chat 历史语义一致。
    """
    last_error: Exception | None = None
    for attempt in range(retry_attempts):
        emitted_anything = False
        try:
            async for chunk in _stream_chunks_once(
                base_url=base_url,
                api_key=api_key,
                payload=payload,
                timeout=timeout,
                abort_event=abort_event,
                url=url,
                extra_headers=extra_headers,
            ):
                if chunk["type"] != "done":
                    emitted_anything = True
                yield chunk
            return
        except Exception as exc:
            log_llm_failure(
                transport="chat_completions_stream",
                target=url or f"{base_url.rstrip('/')}/chat/completions",
                payload=payload,
                exc=exc,
                attempt=attempt + 1,
                response=getattr(exc, "response", None),
            )
            last_error = exc
            if (
                emitted_anything
                or attempt >= retry_attempts - 1
                or not is_retryable_llm_error(exc)
            ):
                raise
            logger.warning(
                "LLM stream request failed before output, retrying: %s",
                format_llm_error(exc),
            )
            await sleep_before_retry(attempt)
    raise last_error or RuntimeError("LLM 调用失败")


# ─────────────────────────── 非流式 ───────────────────────────


async def complete(
    *,
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: httpx.Timeout | float,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    url: Optional[str] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> dict:
    """非流式 chat/completions。返回 OpenAI ``choices[0].message`` dict。"""
    target = url or f"{base_url.rstrip('/')}/chat/completions"
    last_error: Exception | None = None
    for attempt in range(retry_attempts):
        response: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = response = await client.post(
                    target,
                    headers=_headers(api_key, extra_headers=extra_headers),
                    json=payload,
                )
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError as exc:
                    body_preview = resp.text.strip().replace("\n", " ")[:300]
                    if not body_preview:
                        body_preview = "响应体为空"
                    raise LLMEmptyResponseError(
                        f"模型服务返回 HTTP {resp.status_code}，但响应不是有效 JSON：{body_preview}"
                    ) from exc
            if not isinstance(data, dict):
                raise RuntimeError("模型服务返回的 Chat Completions 响应不是 JSON 对象")
            message = data["choices"][0]["message"]
            # MiniMax 等把 reasoning 内联进 content 用 <think>...</think> → 剥离, content 干净。
            # 无 <think> 的 provider 此处是 no-op(不含标签直接返回原文)。
            content = message.get("content")
            if isinstance(content, str) and "<think" in content:
                visible, _reasoning = strip_think_blocks(content)
                message["content"] = visible
            return message
        except Exception as exc:
            log_llm_failure(
                transport="chat_completions",
                target=target,
                payload=payload,
                exc=exc,
                attempt=attempt + 1,
                response=response if response is not None else getattr(exc, "response", None),
            )
            last_error = exc
            if attempt >= retry_attempts - 1 or not is_retryable_llm_error(exc):
                raise
            logger.warning(
                "LLM non-stream request failed, retrying: %s", format_llm_error(exc)
            )
            await sleep_before_retry(attempt)
    raise last_error or RuntimeError("LLM 调用失败")
