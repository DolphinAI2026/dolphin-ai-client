"""Harness Core — 统一执行引擎

为智能搭建、辅助搭建、智能开发、需求分析提供统一的
thread/turn/event 运行时基础设施。
"""

# 确保 ORM models 被 SQLAlchemy Base 注册（create_all 会创建表）
from app.harness.models import (  # noqa: F401
    HarnessThread,
    HarnessTurn,
    HarnessItem,
    HarnessArtifact,
    HarnessApproval,
)

# 注册 profiles（导入即注册）
import app.harness.profiles.coding  # noqa: F401

# 公共 API
from app.harness.contracts import ThreadContext, TurnContext, HarnessEvent, ThreadInfo  # noqa: F401
from app.harness.events import EventBus  # noqa: F401
from app.harness.profiles_base import HarnessProfile, register_profile, get_profile, list_profiles  # noqa: F401
from app.harness.manager import HarnessManager  # noqa: F401
from app.harness.sse_adapter import get_sse_adapter  # noqa: F401
