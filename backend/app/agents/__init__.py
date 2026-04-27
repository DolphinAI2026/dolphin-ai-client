"""Agents 模块 — BaseAgent runtime + 各 agent 子类。

架构：
- base.py：BaseAgent 基类 + 类型定义
- publisher.py：EventPublisher（发 SSE 事件到 conversation_events）
- trace_writer.py：TraceWriter（写 agent_traces）
- brainstorm/：BrainstormAgent
- coding/：CodingAgent（原 VibeCodingAgent）
- verification/：VerificationAgent
- orchestrator.py：Pipeline Orchestrator（phase 状态机）
"""
