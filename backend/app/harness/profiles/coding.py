"""CodingProfile — 智能开发模式

将完整的 Coding Pipeline（场景检测 → 工作区 → Agent → IDE URL）
桥接到 Harness EventBus，提供统一的 thread/turn/event 运行时。
"""
import logging

from app.database import AsyncSessionLocal
from app.harness.contracts import ThreadContext, TurnContext
from app.harness.events import EventBus, ITEM_STARTED, ITEM_DELTA, ITEM_COMPLETED
from app.harness.profiles import HarnessProfile, register_profile

logger = logging.getLogger(__name__)

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
        - workspace_id, conversation_id, selected_model, project_id
        - code_server_base_url, api_base_builder, ide_token
        """
        from app.coding.pipeline import PipelineParams, run_coding_pipeline

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
            code_server_base_url=meta.get("code_server_base_url", ""),
            api_base_builder=meta.get("api_base_builder"),
            ide_token=meta.get("ide_token"),
        )

        result_text = ""
        done_data = {}

        async with AsyncSessionLocal() as db:
            async for event in run_coding_pipeline(params, db):
                event_type = event.get("type", "")

                # 桥接不同事件类型到 harness EventBus
                if event_type == "agent_thinking_delta":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "thinking", "text": event.get("content", "")},
                        item_kind="thinking", persist=False,
                    )

                elif event_type == "agent_thinking":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "thinking", "text": event.get("content", "")},
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
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "content", "text": event.get("content", "")},
                        item_kind="content",
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
                    if event.get("ide_url"):
                        thread_ctx.metadata["ide_url"] = event["ide_url"]

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

        ide_url = done_data.get("ide_url") or thread_ctx.metadata.get("ide_url")
        if ide_url:
            artifacts.append({
                "artifact_type": "ide_url",
                "artifact_key": f"ide_{turn_ctx.turn_id}",
                "content": {"url": ide_url},
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
