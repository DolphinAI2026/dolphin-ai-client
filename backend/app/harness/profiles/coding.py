"""CodingProfile — 智能开发模式

将完整的 Coding Pipeline（场景检测 → 工作区 → Agent）
桥接到 Harness EventBus，提供统一的 thread/turn/event 运行时。
"""
import logging
import os

from app.database import AsyncSessionLocal
from app.harness.contracts import ThreadContext, TurnContext
from app.harness.events import EventBus, ITEM_STARTED, ITEM_DELTA, ITEM_COMPLETED
from app.harness.profiles import HarnessProfile, register_profile

logger = logging.getLogger(__name__)


def _coding_use_runagent() -> bool:
    """Phase 1' cutover 开关:Code 改由 run_agent(统一引擎)驱动,而非 coding 流水线。

    默认关(走旧 coding 流水线)。真机验证通过后翻默认,再退役旧流水线。
    """
    return os.getenv("CODING_USE_RUNAGENT", "").strip().lower() in ("1", "true", "yes", "on")

# Pipeline 事件 → Harness item_kind 映射
_PIPELINE_EVENT_TO_KIND = {
    "step": "system",
    "content": "content",
    "scene_detected": "system",
    "agent_thinking": "thinking",
    "agent_thinking_delta": "thinking",
    "agent_tool": "tool_call",
    "agent_result": "tool_result",
    "agent_command_output": "tool_result",
    "agent_done": "system",
    "agent_error": "system",
    "done": "system",
    "error": "system",
    "run_result": "system",       # 对话驱动运行/预览结果(透传, 前端自动亮预览位)
    "autofix_round": "system",    # C5 自愈轮结果
}


@register_profile
class CodingProfile(HarnessProfile):
    """智能开发 Profile — 委托 Coding Pipeline 执行完整开发流程。"""

    @property
    def name(self) -> str:
        return "coding"

    def get_sse_adapter_name(self) -> str:
        return "coding"

    async def build_context(self, thread_ctx: ThreadContext, turn_ctx: TurnContext) -> dict:
        """构建编码上下文（workspace info + conversation summary）。"""
        from app.coding.workspace import WorkspaceManager

        ws_id = thread_ctx.metadata.get("workspace_id", "")
        ws_mgr = WorkspaceManager()
        ws_info = {}
        try:
            ws_info = ws_mgr.get_workspace_info(ws_id) if ws_id else {}
        except Exception:
            pass

        return {
            "workspace_id": ws_id,
            "workspace_info": ws_info,
            "project_type": ws_info.get("project_type", ""),
        }

    async def run_turn(
        self,
        thread_ctx: ThreadContext,
        turn_ctx: TurnContext,
        event_bus: EventBus,
    ) -> str:
        """
        执行一轮编码。调用完整的 Coding Pipeline，桥接事件到 EventBus。

        thread_ctx.metadata 中应包含 pipeline 所需参数：
        - workspace_id, conversation_id, selected_model, project_id, app_id
        """
        from app.coding.pipeline import PipelineParams, run_coding_entry

        meta = thread_ctx.metadata

        params = PipelineParams(
            message=turn_ctx.user_input,
            user_id=thread_ctx.user_id,
            tenant_id=thread_ctx.tenant_id,
            workspace_id=meta.get("workspace_id"),
            conversation_id=meta.get("conversation_id") or thread_ctx.conversation_id,
            selected_model=meta.get("selected_model"),
            project_id=meta.get("project_id"),
            app_id=meta.get("app_id"),
            attachments=meta.get("attachments") or [],
        )

        # Phase 1' cutover(flag 默认关):Code 改由统一引擎 run_agent 驱动,退役 coding 流水线。
        # 旧路径(下方)原样保留,flag 翻默认 + 真机验证通过后再删。
        if _coding_use_runagent():
            return await self._run_turn_via_runagent(params, thread_ctx, turn_ctx, event_bus)

        result_text = ""
        done_data = {}

        async with AsyncSessionLocal() as db:
            async for event in run_coding_entry(params, db):
                event_type = event.get("type", "")

                # 桥接不同事件类型到 harness EventBus
                if event_type == "agent_thinking_delta":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "thinking", "text": event.get("content", ""), "reasoning": bool(event.get("reasoning"))},
                        item_kind="thinking", persist=False,
                    )

                elif event_type == "agent_thinking":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "thinking", "text": event.get("content", ""), "reasoning": bool(event.get("reasoning"))},
                        item_kind="thinking",
                    )

                elif event_type == "agent_tool":
                    await event_bus.publish(
                        ITEM_STARTED, turn_ctx.turn_id,
                        {
                            "kind": "tool_call",
                            "tool": event.get("tool", ""),
                            "tool_display": event.get("tool_display", ""),
                            "preview": event.get("input_preview", ""),
                            # CodingAgent.before_tool_call 把 write_file/edit_file 的富数据
                            # (file_path/old_string/new_string/content)放在 "input";转发它
                            # 前端才能渲染 edit 红绿 diff + write 行号(否则只剩 preview 字符串)。
                            # 旧字段 "args" 兜底(当前 agent 不发 args,留作前向兼容)。
                            "args": event.get("input") or event.get("args") or {},
                        },
                        item_kind="tool_call",
                    )

                elif event_type == "tool":
                    # 只读应答路径(read_query)的工具 chip:
                    # status=running → tool_call(开始), status=done → tool_result(结果)。
                    # 不映射会被静默丢——前端只能看到 ping 到底然后一句兜底话(实际发生过)。
                    if event.get("status") == "running":
                        _args = event.get("args") or {}
                        await event_bus.publish(
                            ITEM_STARTED, turn_ctx.turn_id,
                            {
                                "kind": "tool_call",
                                "tool": event.get("name", ""),
                                "tool_display": event.get("display", "") or event.get("name", ""),
                                "preview": ", ".join(f"{k}={str(v)[:60]}" for k, v in _args.items())[:120],
                                "args": _args,
                            },
                            item_kind="tool_call",
                        )
                    else:
                        _result = str(event.get("result") or "")
                        await event_bus.publish(
                            ITEM_COMPLETED, turn_ctx.turn_id,
                            {
                                "kind": "tool_result",
                                "tool": event.get("name", ""),
                                "output": _result[:2000],
                                "is_error": _result.startswith("Error"),
                            },
                            item_kind="tool_result",
                        )

                elif event_type == "agent_result":
                    await event_bus.publish(
                        ITEM_COMPLETED, turn_ctx.turn_id,
                        {
                            "kind": "tool_result",
                            "tool": event.get("tool", ""),
                            "output": event.get("output_preview", ""),
                            "is_error": event.get("is_error", False),
                        },
                        item_kind="tool_result",
                    )

                elif event_type == "agent_command_output":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {
                            "kind": "tool_result",
                            "tool": event.get("tool", ""),
                            "chunk": event.get("chunk", ""),
                        },
                        item_kind="tool_result", persist=False,
                    )

                elif event_type == "step":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "system", **event},
                        item_kind="system",
                    )

                elif event_type == "content":
                    # delta=read 路径逐 token 增量, 不持久化(否则一个回答几百行事件)
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "content", "text": event.get("content", ""), "delta": bool(event.get("delta"))},
                        item_kind="content",
                        persist=not bool(event.get("delta")),
                    )

                elif event_type == "scene_detected":
                    if event.get("conversation_id"):
                        thread_ctx.conversation_id = event["conversation_id"]
                        thread_ctx.metadata["conversation_id"] = event["conversation_id"]
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "system", **event},
                        item_kind="system", persist=False,
                    )

                elif event_type == "serve_started":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "system", **event},
                        item_kind="system", persist=False,
                    )

                elif event_type in ("run_result", "autofix_round"):
                    # 对话驱动运行/预览结果(run_workspace_preview 工具 / C5 自愈)。
                    # 以 system kind 透传 → CodingSSEAdapter passthrough 原样带上 type,
                    # 前端 sseHandlers[run_result/autofix_round] 才能收到 → 自动亮预览位。
                    # 不加这条会在 profile 层(无 else 兜底)被静默丢 —— 预览不自动开的根因(2026-06-19)。
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "system", **event},
                        item_kind="system", persist=False,
                    )

                elif event_type == "agent_done":
                    result_text = event.get("result", "")

                elif event_type == "agent_error":
                    raise RuntimeError(event.get("message", "Agent error"))

                elif event_type == "done":
                    done_data = event
                    if event.get("workspace_id"):
                        thread_ctx.metadata["workspace_id"] = event["workspace_id"]
                    if event.get("conversation_id"):
                        thread_ctx.conversation_id = event["conversation_id"]
                        thread_ctx.metadata["conversation_id"] = event["conversation_id"]
                    await event_bus.publish(
                        ITEM_COMPLETED, turn_ctx.turn_id,
                        {"kind": "system", **event},
                        item_kind="system",
                    )

                elif event_type == "error":
                    raise RuntimeError(event.get("message", "Pipeline error"))

                elif event_type == "heartbeat":
                    pass

        # 写入 artifacts（fire-and-forget，不阻塞返回）
        await self._save_turn_artifacts(
            thread_ctx, turn_ctx, done_data, result_text,
        )

        return result_text or done_data.get("workspace_id", "Pipeline completed")

    # ─────────────── Phase 1' cutover: run_agent 驱动 ───────────────

    @staticmethod
    def _ws_bind_view_context(ws_id: str) -> str | None:
        """硬绑既有工作区给 run_agent:所有文件/命令工具用这个 ws_id,禁止新建。

        Code 模式的工作区已存在(面板正显示它),run_agent 必须写进同一个 ws_id,
        否则它会 create_dev_workspace 另起一个 → 面板看不到改动。
        """
        if not ws_id:
            return None
        return (
            f"你正在代码工作区 ws_id='{ws_id}' 内做二次开发。"
            f"所有 read_workspace_file / write_workspace_files / edit_workspace_files / "
            f"glob_workspace / grep_workspace / run_workspace_command 工具都必须使用 "
            f"ws_id='{ws_id}';禁止调用 create_dev_workspace 新建工作区。"
        )

    @staticmethod
    def _tool_preview(args) -> str:
        if not isinstance(args, dict):
            return ""
        return ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())[:120]

    async def _get_or_create_ai_session(self, db, params, thread_ctx, ws_id: str):
        """取/建一个 AIChatSession 供 run_agent 跑(多轮历史累积在它名下)。

        ⚠️ 锚到稳定的 conversation_id(每轮请求都带),**不能**用 thread metadata:
        Code 端点每轮 create_thread 新建 thread,metadata 不跨轮 → 用它做 key 会每轮新建空
        session → 彻底失忆(实测过)。conversation_id == 本 AIChatSession.id(turn1 建好后经
        done 事件回传前端,前端续轮带回)。带 tenant/user/mode 守卫,防 id 撞库误用。
        注:这些 ai_chat session 暂不进 codingApi.getConversations 列表(会话列表统一留作后续)。
        """
        from app.models.ai_chat import AIChatSession

        cid = params.conversation_id
        if cid:
            existing = await db.get(AIChatSession, cid)
            if (existing is not None
                    and existing.tenant_id == params.tenant_id
                    and existing.user_id == params.user_id
                    and existing.mode == "code"):
                return existing

        ws_dir = None
        if ws_id:
            try:
                from app.coding.workspace import WorkspaceManager
                ws_dir = str(WorkspaceManager().get_workspace_path(ws_id))
            except Exception:
                ws_dir = None
        app_id_int = None
        try:
            if params.app_id:
                app_id_int = int(params.app_id)
        except (TypeError, ValueError):
            app_id_int = None

        session = AIChatSession(
            tenant_id=params.tenant_id,
            user_id=params.user_id,
            title=(params.message or "代码会话").replace("\n", " ").strip()[:50] or "代码会话",
            mode="code",
            app_id=app_id_int,
            workspace_dir=ws_dir,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def _run_turn_via_runagent(
        self,
        params,
        thread_ctx: ThreadContext,
        turn_ctx: TurnContext,
        event_bus: EventBus,
    ) -> str:
        """用统一引擎 run_agent 跑一轮 Code。

        run_agent 事件 → map_runagent_event → coding 事件 → EventBus(沿用前端契约)。
        既有 ws_id 经 view_context 硬绑;done 事件补回 workspace_id 让面板自动绑定。
        """
        import asyncio
        import json

        from app.agents.profile import resolve_profile
        from app.ai_chat.agent import run_agent
        from app.harness.profiles.runagent_event_map import map_runagent_event

        ws_id = params.workspace_id or thread_ctx.metadata.get("workspace_id") or ""
        result_text = ""
        last_assistant = ""
        done_data: dict = {}

        # dev-apaas profile:定制「确认即开干」提示词 + 收窄工具集(砍 deploy/生成/配置)。
        # 替掉 run_agent 默认的通用 Builder 提示词 + 全量工具(那套会反复确认 + 跑偏去部署)。
        profile = resolve_profile("dev-apaas")

        async with AsyncSessionLocal() as db:
            session = await self._get_or_create_ai_session(db, params, thread_ctx, ws_id)
            view_context = self._ws_bind_view_context(ws_id)
            abort_event = asyncio.Event()  # 停止经 harness task.cancel 生效(run-survival)

            async for ra in run_agent(
                db, session, params.message, abort_event, view_context=view_context,
                system_prompt_override=profile.system_prompt,
                tool_names_override=set(profile.tool_names),
            ):
                ev = ra.get("event", "")
                try:
                    data = json.loads(ra.get("data") or "{}")
                except Exception:
                    data = {}
                if ev == "assistant_message":
                    last_assistant = data.get("content", "") or last_assistant

                for ce in map_runagent_event(ev, data):
                    ct = ce.get("type")
                    if ct == "agent_thinking_delta":
                        await event_bus.publish(
                            ITEM_DELTA, turn_ctx.turn_id,
                            {"kind": "thinking", "text": ce.get("text", ""), "reasoning": False},
                            item_kind="thinking", persist=False,
                        )
                    elif ct == "content":
                        await event_bus.publish(
                            ITEM_DELTA, turn_ctx.turn_id,
                            {"kind": "content", "text": ce.get("content", ""), "delta": False},
                            item_kind="content",
                        )
                    elif ct == "agent_tool":
                        await event_bus.publish(
                            ITEM_STARTED, turn_ctx.turn_id,
                            {
                                "kind": "tool_call",
                                "tool": ce.get("action", ""),
                                "tool_display": ce.get("action", ""),
                                "preview": self._tool_preview(ce.get("args")),
                                "args": ce.get("args") or {},
                            },
                            item_kind="tool_call",
                        )
                    elif ct == "agent_result":
                        _res = str(ce.get("result") or "")
                        await event_bus.publish(
                            ITEM_COMPLETED, turn_ctx.turn_id,
                            {
                                "kind": "tool_result",
                                "tool": ce.get("action", ""),
                                "output": _res[:2000],
                                "is_error": ce.get("status") == "error",
                            },
                            item_kind="tool_result",
                        )
                    elif ct == "clarify":
                        # system passthrough → CodingSSEAdapter 原样带 type=clarify → 前端 clarify 卡
                        await event_bus.publish(
                            ITEM_DELTA, turn_ctx.turn_id,
                            {"kind": "system", **ce}, item_kind="system", persist=False,
                        )
                    elif ct == "agent_done":
                        result_text = ce.get("result", "") or result_text
                    elif ct == "done":
                        # conversation_id 回传 = 本 AIChatSession.id → 前端续轮带回 → 续轮复用同 session
                        # (修跨轮失忆:不能用每轮新建的 thread metadata 做稳定 key)。
                        ce = {**ce, "workspace_id": ws_id, "conversation_id": session.id}
                        done_data = ce
                        if ws_id:
                            thread_ctx.metadata["workspace_id"] = ws_id
                        thread_ctx.conversation_id = session.id
                        thread_ctx.metadata["conversation_id"] = session.id
                        await event_bus.publish(
                            ITEM_COMPLETED, turn_ctx.turn_id,
                            {"kind": "system", **ce}, item_kind="system",
                        )
                    elif ct == "error":
                        # run_agent 的「达到最大循环次数」是优雅兜底停止,不是崩;真错误也一样
                        # 软着陆:把信息当 content 展示 + 正常收尾,别 raise(否则前端红色崩溃 + Turn failed)。
                        _err = ce.get("error", "run_agent error")
                        await event_bus.publish(
                            ITEM_DELTA, turn_ctx.turn_id,
                            {"kind": "content",
                             "text": f"\n\n（本轮在达到处理上限或遇到问题时停止：{_err}）",
                             "delta": False},
                            item_kind="content",
                        )

        result_text = result_text or last_assistant
        await self._save_turn_artifacts(thread_ctx, turn_ctx, done_data, result_text)
        return result_text or done_data.get("workspace_id", "Pipeline completed")

    async def _save_turn_artifacts(
        self,
        thread_ctx: ThreadContext,
        turn_ctx: TurnContext,
        done_data: dict,
        result_text: str,
    ):
        """从 pipeline 完成数据中提取 artifacts 并批量写入。"""
        from app.harness.artifacts import save_artifacts_batch

        artifacts: list[dict] = []

        ws_id = done_data.get("workspace_id") or thread_ctx.metadata.get("workspace_id")
        if ws_id:
            artifacts.append({
                "artifact_type": "workspace",
                "artifact_key": ws_id,
                "content": {
                    "workspace_id": ws_id,
                    "project_name": thread_ctx.metadata.get("project_name", ""),
                    "project_type": thread_ctx.metadata.get("project_type", ""),
                },
            })

        if result_text:
            artifacts.append({
                "artifact_type": "agent_summary",
                "artifact_key": f"summary_{turn_ctx.turn_id}",
                "content": {"text": result_text[:5000]},
            })

        if not artifacts:
            return

        try:
            async with AsyncSessionLocal() as db:
                await save_artifacts_batch(
                    db,
                    thread_id=thread_ctx.thread_id,
                    turn_id=turn_ctx.turn_id,
                    artifacts=artifacts,
                )
        except Exception:
            logger.warning("Failed to save coding artifacts", exc_info=True)
