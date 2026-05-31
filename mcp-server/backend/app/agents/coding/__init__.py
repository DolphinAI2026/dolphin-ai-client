"""CodingAgent — 从 VibeCodingAgent 迁移到 BaseAgent 架构。

迁移阶段（见 docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md § P1.1d）：
- Stage 2.1: tool_registry 包装 + 骨架
- Stage 2.2: LLM 流式调用
- Stage 2.3: Prompt 构造 + 场景分支
- Stage 2.4: 循环检测 + 状态序列化 + context 压缩
- Stage 3: Pipeline Adapter（事件格式兼容）
- Stage 4: 删除 VibeCodingAgent
"""

from app.agents.coding.adapter import CodingAgentStreamAdapter
from app.agents.coding.agent import CodingAgent

__all__ = ["CodingAgent", "CodingAgentStreamAdapter"]
