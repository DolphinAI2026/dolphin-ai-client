"""C5 · AI 自愈循环 drive_coding_with_autofix（SP1-b）。

包在 CodingAgentStreamAdapter.run 外层：每轮 agent 改完代码后
build/serve + CDP launch_capture 抓 console/network，收集失败信号，
有信号则把 fix_hint 塞回 ctx.input、round_index 塞回 ctx.extra，再跑一轮。

停止条件（任一）：本轮无新信号 / 同一报错重复 / 达 max_autofix_rounds。
token 计入 agent._tokens_input/_output（adapter.run 内已累加，driver 只读出做 budget marker）。

不破坏现有 pipeline SSE 事件流：agent 事件原样 yield；driver 仅在每轮之间
额外 yield {"type": "autofix_round", ...} marker（pipeline append 进 replay 即可，
前端不识别也无副作用）。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from app.agents.coding.adapter import CodingAgentStreamAdapter
from app.agents.coding.agent import CodingAgent
from app.agents.coding.autofix_signals import (
    build_fix_hint,
    collect_build_errors,
    collect_runtime_errors,
    signals_signature,
)

logger = logging.getLogger(__name__)


def _get_browser_service():
    """间接拿 BrowserService 单例，便于测试 monkeypatch。"""
    from app.coding.browser_service import BrowserService
    return BrowserService.get_instance()


async def _capture_runtime_errors(preview_url: str) -> list[str]:
    """起一个 CDP 抓取会话加载 preview_url，收 console/network 失败信号后关闭。

    CDP 缺失/启动失败按 spec §6 降级为「仅日志，无运行时抓取」——不阻断自愈。
    """
    browser = _get_browser_service()
    session_id: Optional[str] = None
    try:
        session_id = browser.launch_capture(preview_url, headless=True)
        console_logs = browser.get_console_logs(session_id, 0) or []
        network = browser.get_network_requests(session_id, 0) or []
        return collect_runtime_errors(console_logs, network)
    except Exception:
        logger.warning("autofix: CDP 抓取失败，降级为仅 build 校验", exc_info=True)
        return []
    finally:
        if session_id is not None:
            try:
                browser.close_capture(session_id)
            except Exception:
                logger.warning("autofix: close_capture 失败（忽略）", exc_info=True)


async def drive_coding_with_autofix(
    *,
    agent: CodingAgent,
    adapter: CodingAgentStreamAdapter,
    requirement: str,
    conversation_summary: str,
    model: str,
    max_turns: int,
    ws_mgr: Any,
    preview_url: Optional[str],
    max_autofix_rounds: int = 3,
) -> AsyncIterator[dict[str, Any]]:
    """驱动 CodingAgent 跑 ≤ max_autofix_rounds 轮，每轮后验收并按需注入 fix_hint。"""
    ws_id = agent.ctx.workspace_id
    prev_signature: Optional[str] = None

    for round_index in range(max_autofix_rounds):
        # round_index>0 时，本轮 fix_hint 已在上一轮末尾写进 ctx.input（见下方）
        agent.ctx.extra = dict(agent.ctx.extra or {})
        agent.ctx.extra["round_index"] = round_index

        # 跑一轮 agent（事件原样透传给 pipeline）
        async for event in adapter.run(
            requirement=requirement,
            conversation_summary=conversation_summary,
            max_turns=max_turns,
            model=model,
        ):
            yield event

        tokens_in = getattr(agent, "_tokens_input", 0)
        tokens_out = getattr(agent, "_tokens_output", 0)

        yield {
            "type": "autofix_round", "round": round_index, "status": "verifying",
            "errors": [], "tokens_input": tokens_in, "tokens_output": tokens_out, "dev_url": preview_url or "",
        }

        # 1. build 校验
        build_errors: list[str] = []
        if ws_id:
            try:
                build_result = await ws_mgr.build_project(ws_id)
                build_errors = collect_build_errors(build_result)
            except Exception as e:
                build_errors = [f"构建过程异常: {e}"]

        # 2. 运行时抓取（仅在 build 通过且有 preview_url 时；build 已失败无需起服务）
        runtime_errors: list[str] = []
        if not build_errors and preview_url:
            runtime_errors = await _capture_runtime_errors(preview_url)

        all_errors = build_errors + runtime_errors

        # 3. 无信号 → 干净，停
        if not all_errors:
            yield {
                "type": "autofix_round", "round": round_index, "status": "clean",
                "errors": [], "tokens_input": tokens_in, "tokens_output": tokens_out, "dev_url": preview_url or "",
            }
            agent.ctx.input.pop("fix_hint", None)
            return

        # 4. 同一报错重复 → 如实上报并停
        signature = signals_signature(build_errors, runtime_errors)
        if signature == prev_signature:
            yield {
                "type": "autofix_round", "round": round_index, "status": "repeated",
                "errors": all_errors, "tokens_input": tokens_in, "tokens_output": tokens_out, "dev_url": preview_url or "",
            }
            agent.ctx.input.pop("fix_hint", None)
            return
        prev_signature = signature

        # 5. 还有重试名额 → 注入 fix_hint，下一轮重跑；否则上限耗尽，停
        if round_index + 1 < max_autofix_rounds:
            agent.ctx.input = dict(agent.ctx.input or {})
            agent.ctx.input["fix_hint"] = build_fix_hint(build_errors, runtime_errors)
            yield {
                "type": "autofix_round", "round": round_index, "status": "fixing",
                "errors": all_errors, "tokens_input": tokens_in, "tokens_output": tokens_out, "dev_url": preview_url or "",
            }
        else:
            yield {
                "type": "autofix_round", "round": round_index, "status": "exhausted",
                "errors": all_errors, "tokens_input": tokens_in, "tokens_output": tokens_out, "dev_url": preview_url or "",
            }
            agent.ctx.input.pop("fix_hint", None)
            return
