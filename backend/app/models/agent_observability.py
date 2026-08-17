"""Agent 可观测统一底座 — 2 张表，所有 agent 链路的 run / step 都聚到这里。

- agent_run   一次运行（= 一条用户消息触发的完整工具循环）
- agent_step  run 内每一步（llm / tool / error / artifact）

写入只走 app/observability/recorder.py（旁路，吞自身异常，不影响主 agent）。
现有 AIChatToolCall / AgentTrace 等保留，埋点处双写。
关联用 run_id（uuid hex）做逻辑外键，不加硬 FK —— 跟 AgentTrace 一样，旁路表
不该因为主表行缺失而写不进去。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import String, Text, DateTime, Integer, JSON, Index
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 大结果文本：MySQL 用 LONGTEXT（4GB），SQLite 等价 TEXT。
# 本地定义（跟 models/ai_chat.py:24 同款），避免从 app.models 反向 import 造成循环。
BigText = Text().with_variant(LONGTEXT, "mysql")


class AgentRun(Base):
    """一次 agent 运行。"""

    __tablename__ = "agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    # ai_builder / config / coding / builder
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    app_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # model 不在 spec 表里，但 Phase 2「token→¥ 成本估算」明确需要按模型拆分，
    # 一列 nullable 几乎零成本，先采着，省得 Phase 2 再加列迁移。
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # running / success / error
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    __table_args__ = (
        # 租户作用域 + 时间倒序列表的复合索引
        Index("ix_agent_run_tenant_created", "tenant_id", "created_at"),
    )


class AgentStep(Base):
    """run 内一步。"""

    __tablename__ = "agent_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 逻辑外键 → AgentRun.run_id（不加硬 FK，旁路表）
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # llm / tool / error / artifact
    step_type: Mapped[str] = mapped_column(String(16), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    args_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result_text: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Nullable governance compatibility projection; ActionRun remains authoritative.
    action_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    result_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    snapshot_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # llm step 用
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_agent_step_run_seq", "run_id", "seq"),
    )
