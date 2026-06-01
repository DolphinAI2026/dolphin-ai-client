"""read_query.py — AI Coding 只读应答路径

当用户意图为「读/问」(READ) 时，不建 workspace、不 codegen，
直接用只读 aPaaS 工具 + LLM tool-loop 回答问题，emit 工具 chip + 文字 + done。

主要出口：
  classify_coding_intent(tenant_id, model, message) -> "READ" | "BUILD"
  run_read_query(params, db)                        -> AsyncIterator[dict]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coding.apaas_tools import (
    APAAS_TOOL_DEFINITIONS,
    APAAS_TOOL_EXECUTORS_PLATFORM,
)

logger = logging.getLogger(__name__)

# ── 只给读路径暴露的只读工具子集 ──────────────────────
_READ_ONLY_TOOL_NAMES = {
    "list_apaas_apps",
    "list_apaas_app_menus",
    "list_apaas_form_views",
    "list_apaas_form_components",
    "list_apaas_app_models",
    "list_apaas_app_dicts",
    "get_apaas_app_overview",
    "list_apaas_models_in_env",
    "check_app_code_conflict",
}

READ_ONLY_TOOL_DEFINITIONS: list[dict] = [
    t for t in APAAS_TOOL_DEFINITIONS
    if t.get("function", {}).get("name") in _READ_ONLY_TOOL_NAMES
]

# tool executors 也只暴露只读子集，防止工具名冲突时意外执行写操作
_READ_ONLY_EXECUTORS: dict[str, Any] = {
    k: v for k, v in APAAS_TOOL_EXECUTORS_PLATFORM.items()
    if k in _READ_ONLY_TOOL_NAMES
}

# 读路径 tool-loop 最大轮数（避免 LLM 死循环）
_READ_MAX_TURNS = 8

# ─────────────────────────── 意图分类 ─────────────────────────────


async def classify_coding_intent(
    tenant_id: Optional[int],
    model: str,
    message: str,
) -> str:
    """轻量 LLM 调用：判断用户意图是「读/问」(READ) 还是「建代码」(BUILD)。

    保守兜底：任何失败或拿不准 → BUILD。
    绝不把"建代码"误判为 READ。
    """
    # 快速关键词判断 — 明确建代码关键词直接 BUILD，避免 LLM 延迟
    msg_lower = message.lower()
    _BUILD_KEYWORDS = {
        "建", "做", "创建", "新建", "写", "生成", "开发", "实现", "搭建", "构建",
        "编写", "制作", "设计", "做一个", "写一个", "建一个", "来一个",
        "组件", "页面", "接口", "api", "控件", "组件", "插件",
        "springboot", "vue", "react", "java", "python",
    }
    for kw in _BUILD_KEYWORDS:
        if kw in msg_lower:
            return "BUILD"

    system_prompt = """你是 AI Coding 模块的意图分类助手。
根据用户消息，判断用户意图是「读/查询」还是「建代码/开发」，只输出以下之一：
- READ：用户只想查询/了解现有平台信息（如：查看应用列表、读模型字段、了解菜单结构、查看字典等）
- BUILD：用户想开发/创建/修改代码或应用（如：建组件、写页面、开发接口、新建应用等）

**保守原则：不确定时输出 BUILD。**
只有消息明确是纯查询/读取且无任何创建/开发意图时才输出 READ。

示例：
"读一下有哪些应用" → READ
"列出所有应用" → READ
"这个模型有哪些字段" → READ
"查看图书借阅应用的菜单" → READ
"有哪些字典" → READ
"建个图书首页双端组件" → BUILD
"做一个数据查询页面" → BUILD
"写一个后端接口" → BUILD
"帮我创建应用" → BUILD
"上传文件组件" → BUILD"""

    try:
        from app.agents.coding.llm_config import load_coding_llm_config

        base_url, api_key, llm_model = await load_coding_llm_config(tenant_id, model)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8, read=20, write=8, pool=8)
        ) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"用户消息：{message[:300]}"},
                    ],
                    "max_tokens": 10,
                    "temperature": 0,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        # 清理 reasoning tag
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
        label = cleaned.upper().split()[0] if cleaned else "BUILD"
        if label == "READ":
            logger.info("[intent] 分类=READ, message=%r", message[:100])
            return "READ"
    except Exception as exc:
        logger.warning("[intent] 分类失败，兜底 BUILD: %s", exc)

    return "BUILD"


# ─────────────────────────── platform_env_id 解析 ──────────────────────────


async def _resolve_read_platform_env_id(
    tenant_id: Optional[int],
    db: AsyncSession,
) -> Optional[int]:
    """从租户默认 PlatformEnv 拿 platform_env_id（给读路径用）。"""
    if not tenant_id:
        return None
    try:
        from app.models import PlatformEnv

        res = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == tenant_id,
                PlatformEnv.is_default == True,  # noqa: E712
            ).limit(1)
        )
        env = res.scalar_one_or_none()
        if env:
            return int(env.id)
    except Exception as exc:
        logger.warning("[read_query] 解析 platform_env_id 失败: %s", exc)
    return None


# ─────────────────────────── 只读 tool-loop ────────────────────────────────

_READ_SYSTEM_PROMPT = """你是 aPaaS 平台的 AI 助手，帮用户查询和了解平台现有应用、模型、菜单、字典等信息。

工作指引：
- 只调用只读工具查询信息，不创建、不修改任何内容
- 调用 list_apaas_apps 先了解有哪些应用，再根据用户需求深入查询
- 用清晰的中文回答用户问题，可以用表格/列表整理信息
- 如果没有可用的平台环境，直接说明并建议用户在「平台管理」中配置环境
- 回答简洁、结构清晰
"""


async def run_read_query(
    params: "PipelineParams",
    db: AsyncSession,
) -> AsyncIterator[dict]:
    """只读应答回路 — tool-calling loop + emit 事件。

    emit 事件类型：
      {"type": "tool", "name": ..., "status": "running"|"done", "result": ...}
      {"type": "content", "content": "..."}
      {"type": "done", "workspace_id": None, "ide_url": None, "conversation_id": None}

    不创建 workspace，不调 codegen。
    """
    # ── 解析 LLM 配置 ──────────────────────────────────────────────────────
    from app.agents.coding.llm_config import load_coding_llm_config

    try:
        base_url, api_key, llm_model = await load_coding_llm_config(
            params.tenant_id, params.selected_model or ""
        )
    except Exception as exc:
        yield {"type": "content", "content": f"LLM 配置加载失败：{exc}"}
        yield {"type": "done", "workspace_id": None, "ide_url": None, "conversation_id": None}
        return

    # ── 解析 platform_env_id ───────────────────────────────────────────────
    platform_env_id = await _resolve_read_platform_env_id(params.tenant_id, db)

    if not platform_env_id:
        # 没有环境时，LLM 也能回答一些通用问题，但 aPaaS 工具都没法用
        # 直接 LLM 回答（不带工具）
        yield {"type": "content", "content": "当前租户未配置可用的 aPaaS 平台环境，无法查询应用数据。\n请先在「平台管理 → aPaaS 租户」中配置并连接平台环境。"}
        yield {"type": "done", "workspace_id": None, "ide_url": None, "conversation_id": None}
        return

    # ── tool-loop ──────────────────────────────────────────────────────────
    messages: list[dict] = [
        {"role": "system", "content": _READ_SYSTEM_PROMPT},
        {"role": "user", "content": params.message},
    ]

    for _turn in range(_READ_MAX_TURNS):
        # LLM call（非流式，读路径不需要 streaming）
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)
            ) as client:
                payload: dict = {
                    "model": llm_model,
                    "messages": messages,
                    "tools": READ_ONLY_TOOL_DEFINITIONS,
                    "tool_choice": "auto",
                    "temperature": 0.2,
                    "max_tokens": 1200,
                }
                # 兼容 qwen3 / dashscope — disable thinking
                if "qwen3" in llm_model.lower() or "dashscope.aliyuncs.com" in base_url.lower():
                    payload["enable_thinking"] = False
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("[read_query] LLM 调用失败 turn=%d: %s", _turn, exc)
            yield {"type": "content", "content": f"查询时出现错误：{exc}"}
            break

        msg = data.get("choices", [{}])[0].get("message", {})
        tool_calls: list[dict] = msg.get("tool_calls") or []
        content: str = (msg.get("content") or "").strip()

        # 把 assistant 消息加进历史（不管有没有 tool_calls）
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        # 没有工具调用 → 输出最终答案
        if not tool_calls:
            if content:
                yield {"type": "content", "content": content}
            break

        # 有工具调用 → 逐个执行
        tool_result_messages: list[dict] = []
        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name", "")
            tc_id = tc.get("id") or fn_name

            # 只允许只读工具
            if fn_name not in _READ_ONLY_EXECUTORS:
                tool_result_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": f"Error: 工具 {fn_name!r} 不在只读工具列表中，不予执行。",
                })
                continue

            # 解析参数
            try:
                args_raw = tc.get("function", {}).get("arguments") or "{}"
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError:
                args = {}

            # emit tool running chip
            yield {
                "type": "tool",
                "name": fn_name,
                "status": "running",
                "args": args,
            }

            # 执行工具
            try:
                executor = _READ_ONLY_EXECUTORS[fn_name]
                result_str: str = await executor(args, platform_env_id, db)
            except Exception as exc:
                result_str = f"Error: {exc}"

            # emit tool done chip
            yield {
                "type": "tool",
                "name": fn_name,
                "status": "done",
                "result": result_str[:2000],  # 截断避免过长
            }

            tool_result_messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_str,
            })

        messages.extend(tool_result_messages)

    # 兜底：如果 loop 因 MAX_TURNS 耗尽退出、且最后消息是 tool result，给一条提示
    if messages and messages[-1].get("role") == "tool":
        yield {"type": "content", "content": "查询完成，如需了解更多请继续提问。"}

    yield {
        "type": "done",
        "workspace_id": None,
        "ide_url": None,
        "conversation_id": None,
    }


# ── 延迟引用避免循环 import ────────────────────────────────────────────────
# run_read_query 签名里用了 "PipelineParams" 字符串，在运行时不需要 import
# （PipelineParams 由调用方 pipeline.py 传入实例即可）
