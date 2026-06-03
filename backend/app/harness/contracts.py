"""Harness Core — Pydantic 数据契约（内存传递 + SSE 序列化）"""
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class ThreadContext(BaseModel):
    """线程上下文，传递给 profile。"""
    thread_id: int
    tenant_id: int
    user_id: int
    profile_name: str
    conversation_id: Optional[int] = None
    metadata: dict = {}


class TurnContext(BaseModel):
    """轮次上下文。"""
    turn_id: int
    thread_id: int
    turn_index: int
    user_input: str


class HarnessEvent(BaseModel):
    """统一事件格式，EventBus 发出的每个事件。"""
    seq: int
    event_type: str
    thread_id: int
    turn_id: Optional[int] = None
    data: dict = {}
    timestamp: datetime


class ThreadInfo(BaseModel):
    """Thread API 响应。"""
    id: int
    tenant_id: int
    user_id: int
    profile_name: str
    status: str
    conversation_id: Optional[int] = None
    metadata: dict = {}
    last_seq: int = 0
    created_at: datetime
    updated_at: datetime


