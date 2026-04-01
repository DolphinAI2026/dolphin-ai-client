"""Harness Core — Profile 系统（抽象基类 + 注册表 + NullProfile）"""
from abc import ABC, abstractmethod

from app.harness.contracts import ThreadContext, TurnContext
from app.harness.events import EventBus, ITEM_STARTED, ITEM_DELTA, ITEM_COMPLETED


class HarnessProfile(ABC):
    """所有 Harness profile 的抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Profile 标识符，如 'coding', 'builder', 'requirements', 'platform'。"""

    @abstractmethod
    async def build_context(self, thread_ctx: ThreadContext, turn_ctx: TurnContext) -> dict:
        """构建 LLM 上下文（system prompt, tools, history, llm_config）。"""

    @abstractmethod
    async def run_turn(self, thread_ctx: ThreadContext, turn_ctx: TurnContext,
                       event_bus: EventBus) -> str:
        """执行一轮。通过 event_bus 发布事件。返回结果摘要。"""

    def get_sse_adapter_name(self) -> str:
        """返回使用哪个 SSE 适配器。默认 'generic'。"""
        return "generic"


# ── Profile 注册表 ──────────────────────────────────

_PROFILE_REGISTRY: dict[str, type[HarnessProfile]] = {}


def register_profile(cls: type[HarnessProfile]) -> type[HarnessProfile]:
    """装饰器：注册一个 profile 类。"""
    # 临时实例化获取 name
    instance = object.__new__(cls)
    profile_name = cls.name.fget(instance)  # type: ignore[attr-defined]
    _PROFILE_REGISTRY[profile_name] = cls
    return cls


def get_profile(name: str) -> HarnessProfile:
    """按名称实例化已注册的 profile。"""
    cls = _PROFILE_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown harness profile: {name}. Available: {list(_PROFILE_REGISTRY.keys())}")
    return cls()


def list_profiles() -> list[str]:
    return list(_PROFILE_REGISTRY.keys())


# ── NullProfile（Phase 1 测试用）──────────────────

@register_profile
class NullProfile(HarnessProfile):
    """最小 profile，echo 用户输入。用于测试 harness 基础设施。"""

    @property
    def name(self) -> str:
        return "null"

    async def build_context(self, thread_ctx: ThreadContext, turn_ctx: TurnContext) -> dict:
        return {"system_prompt": "You are a test assistant.", "tools": [], "messages": []}

    async def run_turn(self, thread_ctx: ThreadContext, turn_ctx: TurnContext,
                       event_bus: EventBus) -> str:
        await event_bus.publish(
            ITEM_STARTED, turn_ctx.turn_id,
            {"kind": "content"}, item_kind="content",
        )
        await event_bus.publish(
            ITEM_DELTA, turn_ctx.turn_id,
            {"kind": "content", "text": f"Echo: {turn_ctx.user_input}"},
            item_kind="content",
        )
        await event_bus.publish(
            ITEM_COMPLETED, turn_ctx.turn_id,
            {"kind": "content"}, item_kind="content",
        )
        return f"Echoed: {turn_ctx.user_input}"
