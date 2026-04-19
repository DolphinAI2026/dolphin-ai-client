"""BaseAgent 运行时的类型定义。

不依赖 LLM / DB / 具体 agent 实现，作为所有模块共享的基础类型。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


# ══════════════════════════════════════════════════════════════
# 枚举
# ══════════════════════════════════════════════════════════════

class AgentStatus(str, Enum):
    """Agent 生命周期状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"          # ask_user 等待用户回答时
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"        # 用户主动取消


class AgentType(str, Enum):
    """Agent 类型 - 用于 trace / event 的 namespace"""
    BRAINSTORM = "brainstorm"
    CODING = "coding"
    VERIFICATION = "verification"
    ORCHESTRATOR = "orchestrator"
    SYSTEM = "system"


class StopReason(str, Enum):
    """Agent 循环结束原因"""
    TERMINATE_CONDITION_MET = "terminate"    # should_terminate() 返回 True
    LLM_NO_TOOL_CALL = "no_tool_call"        # LLM 返回纯文本，未调用工具
    MAX_TURNS_EXCEEDED = "max_turns"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    ERROR = "error"


# ══════════════════════════════════════════════════════════════
# Tool 定义
# ══════════════════════════════════════════════════════════════

class ToolResult(BaseModel):
    """Tool 执行结果 — 反馈给 LLM 的结构"""
    success: bool
    content: str = Field(..., description="反馈给 LLM 的文本（作为 tool role 消息内容）")
    data: dict[str, Any] = Field(default_factory=dict, description="结构化数据，供 agent 内部消费")
    error: Optional[str] = None

    # 可选：tool 执行时产生的面向用户事件（如 ask_user 产生反问气泡）
    emit_event: Optional[dict[str, Any]] = Field(
        default=None,
        description="可选的前端事件 {type, data} — BaseAgent 会 publish 到 SSE",
    )

    # 可选：是否触发 agent pause（ask_user 典型用途）
    should_pause: bool = Field(
        default=False,
        description="True 时 agent 执行完此 tool 后 pause（等 resume）",
    )


# Tool 执行函数签名：async (args, context) -> ToolResult
ToolExecutor = Callable[[dict[str, Any], "AgentContext"], Awaitable[ToolResult]]


class Tool(BaseModel):
    """通用 Tool 定义 — 所有 agent 共享的工具抽象"""
    name: str
    description: str
    parameters_schema: dict[str, Any] = Field(
        ...,
        description="JSON schema，喂给 LLM（OpenAI function-calling 格式的 parameters 部分）",
    )
    execute: ToolExecutor = Field(..., exclude=True)

    # 策略标记
    requires_user: bool = Field(
        default=False,
        description="是否需要用户交互（如 ask_user）",
    )
    idempotent: bool = Field(
        default=True,
        description="是否幂等（影响重试策略）",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_openai_function(self) -> dict[str, Any]:
        """转成 OpenAI function-calling 格式（喂给 LLMClient）"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


# ══════════════════════════════════════════════════════════════
# AgentContext（依赖注入）
# ══════════════════════════════════════════════════════════════

class AgentContext(BaseModel):
    """Agent 运行时上下文 — 由 orchestrator 构造并注入。

    包含三类内容：
    1. 身份：session_id / conversation_id / user_id / tenant_id
    2. 依赖（非 Pydantic 模型对象）：db / publisher / trace_writer / llm_client
    3. 输入：input（各 agent 子类自定义 shape）+ 关联 ID（workspace / spec / parent session）
    """
    # —— 身份 —— #
    session_id: str
    conversation_id: int
    user_id: int
    tenant_id: int

    # —— 模型配置 —— #
    model: str

    # —— 关联 —— #
    parent_session_id: Optional[str] = None
    spec_id: Optional[str] = None
    workspace_id: Optional[str] = None

    # —— 输入（各 agent 自定义） —— #
    input: dict[str, Any] = Field(default_factory=dict)

    # —— 依赖（运行时注入，不参与 Pydantic 校验） —— #
    db: Optional[Any] = Field(default=None, exclude=True)
    publisher: Optional[Any] = Field(default=None, exclude=True)
    trace_writer: Optional[Any] = Field(default=None, exclude=True)
    llm_client: Optional[Any] = Field(default=None, exclude=True)

    # 扩展字段（orchestrator 可带额外信息）
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ══════════════════════════════════════════════════════════════
# AgentResult（agent 返回给 orchestrator）
# ══════════════════════════════════════════════════════════════

ProductT = TypeVar("ProductT")  # 各 agent 子类的产物类型（Spec / Report / FileSummary 等）


class AgentResult(BaseModel, Generic[ProductT]):
    """Agent 执行结果"""
    status: AgentStatus
    stop_reason: Optional[StopReason] = None
    product: Optional[ProductT] = None
    turns_used: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    error_message: Optional[str] = None

    # 持久化的 agent snapshot（用于 suspend/resume）
    snapshot: Optional[dict[str, Any]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ══════════════════════════════════════════════════════════════
# 内部：LLM 消息 / tool call（结构化表示，不依赖 LLM provider 格式）
# ══════════════════════════════════════════════════════════════

class ToolCall(BaseModel):
    """LLM 返回的 tool_call（OpenAI 风格）"""
    id: str
    name: str
    arguments_json: str        # JSON 字符串（OpenAI 合约）

    @property
    def arguments(self) -> dict[str, Any]:
        """解析 JSON 参数，失败返回空 dict"""
        import json
        try:
            return json.loads(self.arguments_json)
        except Exception:
            return {}


class LLMResponse(BaseModel):
    """LLM 调用结果的内部表示"""
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ══════════════════════════════════════════════════════════════
# 内部：Trace 事件 payload
# ══════════════════════════════════════════════════════════════

class TraceEventType(str, Enum):
    """agent_traces 的 event_type 枚举"""
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    NUDGE = "nudge"
    ERROR = "error"
    RETRY = "retry"
    STATE_CHANGE = "state_change"
