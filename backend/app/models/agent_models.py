"""Agent 架构相关数据模型（P1.2）。

7 张表：
- agent_messages          用户可见的消息流
- brainstorm_sessions     BrainstormAgent 会话状态
- specs                   Spec 契约版本链
- coding_sessions         CodingAgent 执行记录
- verification_reports    AC 验收报告
- agent_traces            Agent 内部调试 trace
- conversation_events     SSE 事件缓存（支持断线重连）

所有 id 字段使用 String(64)，存 ULID/UUID hex。
JSON 字段同时兼容 SQLite 和 MySQL。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ══════════════════════════════════════════════════════════════
# 1. agent_messages — 用户可见消息流
# ══════════════════════════════════════════════════════════════

class AgentMessage(Base):
    """用户可见的消息流（含用户说的、agent 说的、反问气泡、Spec emit 通知等）。

    与旧 messages 表的区别：
    - 支持多 agent source 标注
    - 支持 content_type（text / markdown / spec_draft / verification_report）
    - 支持 extra 元数据（question_id / spec_id / tool_name 等）
    - 不存 agent 内部 tool loop 每一步（那些走 agent_traces）
    """
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True,
    )

    source: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="user / brainstorm / coding / verification / system",
    )
    source_session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    role: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="user / assistant / system",
    )
    content_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="text",
        comment="text / markdown / spec_draft / verification_report / tool_summary / question",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True,
    )

    __table_args__ = (
        Index("ix_agent_messages_conv_time", "conversation_id", "created_at"),
    )


# ══════════════════════════════════════════════════════════════
# 2. brainstorm_sessions
# ══════════════════════════════════════════════════════════════

class BrainstormSession(Base):
    """BrainstormAgent 的会话状态。

    对应一次"需求澄清到 Spec 产出"的完整会话。迭代模式下可能有多个 session。
    """
    __tablename__ = "brainstorm_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True,
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active",
        comment="active / paused / completed / aborted / suspended",
    )

    scene_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="当前识别的场景（反问过程中可能变化）",
    )

    final_spec_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="completed 时指向最终 Spec",
    )

    trigger_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="initial",
        comment="initial / iterate_minor / iterate_major",
    )
    parent_spec_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="iterate 时指向被迭代的 Spec",
    )

    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Agent snapshot（用于 suspend / resume）
    agent_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ══════════════════════════════════════════════════════════════
# 3. specs — Spec 契约版本链
# ══════════════════════════════════════════════════════════════

class Spec(Base):
    """Brainstorm 产出、Coding 消费的结构化契约。

    内容完整存 JSON content，常用字段抽出来做索引。
    支持版本链（version / parent_version）。
    """
    __tablename__ = "specs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brainstorm_session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("brainstorm_sessions.id"), nullable=False, index=True,
    )

    # —— 索引/查询用字段（抽列） —— #
    schema_version: Mapped[str] = mapped_column(String(10), default="1.0", nullable=False)
    scene_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    code_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    widget_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="agent / user / mixed",
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # —— 完整 Spec JSON —— #
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_specs_session_version", "brainstorm_session_id", "version"),
        Index("ix_specs_code_version", "code_name", "version"),
    )


# ══════════════════════════════════════════════════════════════
# 4. coding_sessions
# ══════════════════════════════════════════════════════════════

class CodingSession(Base):
    """CodingAgent 的执行记录。消费某版 Spec 产出代码。"""
    __tablename__ = "coding_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True,
    )
    spec_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("specs.id"), nullable=False, index=True,
    )
    workspace_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        comment="pending / running / completed / failed / aborted",
    )

    trigger_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="initial",
        comment="initial / patch / retry",
    )
    trigger_report_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="retry 时指向触发的 verification report",
    )

    turns_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    files_written: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    agent_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ══════════════════════════════════════════════════════════════
# 5. verification_reports
# ══════════════════════════════════════════════════════════════

class VerificationReport(Base):
    """VerificationAgent 的 AC 验收报告。"""
    __tablename__ = "verification_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coding_session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("coding_sessions.id"), nullable=False, index=True,
    )
    spec_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="冗余，方便按 Spec 查所有报告",
    )

    overall_status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="passed / failed / partial",
    )
    passed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 每条 AC 的检查结果 [{ac_id / ac_index, description, status, evidence, confidence}]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # constraints 检查结果 [{text, severity, status, evidence}]
    constraint_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ══════════════════════════════════════════════════════════════
# 6. agent_traces — 内部调试 trace
# ══════════════════════════════════════════════════════════════

class AgentTrace(Base):
    """Agent 内部的 LLM 调用 / tool call / thinking / error trace。

    不推送给前端，用于调试、审计、token 成本核算。
    TTL 建议 90 天后 archive 或删除。
    """
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # 多态关联（不做 FK，用 session_type + session_id 组合查询）
    session_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="brainstorm / coding / verification",
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    seq: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="session 内单调递增",
    )
    turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="llm_request / llm_response / tool_call / tool_result / thinking / nudge / error / retry / state_change",
    )

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    tokens_input: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True,
    )

    __table_args__ = (
        Index("ix_agent_traces_session", "session_type", "session_id", "seq"),
    )


# ══════════════════════════════════════════════════════════════
# 7. conversation_events — SSE 事件缓存
# ══════════════════════════════════════════════════════════════

class ConversationEvent(Base):
    """发送给前端的 SSE 事件缓存，支持断线重连补发。

    与 agent_traces 区别：
    - agent_traces 是内部调试，不推前端
    - conversation_events 是面向用户的事件
    - 保留 7 天（超过删除）
    """
    __tablename__ = "conversation_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True,
    )

    seq: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="conversation 内单调递增，用于断线重连的 last_seen_seq",
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_conv_events_conv_seq", "conversation_id", "seq"),
    )
