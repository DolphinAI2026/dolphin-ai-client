"""Read-only project initialization message dispatch for Code shells."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException

from app.models.ai_chat import AIChatSession, CodeRuntimeBinding


ProjectInitializationDispatchState = Literal["sent", "already_sent", "retryable_failed"]
RuntimeMessageSender = Callable[[str, str, str], Awaitable[Any]]

PROJECT_INITIALIZATION_PROMPT = """你正在执行项目初始化的只读检查。

仅允许检查：项目结构、README 和 AGENTS 指南、依赖清单与锁文件、入口文件和脚本、Git 状态，以及当前环境可用性。
禁止写入或修改任何文件；禁止安装依赖；禁止构建；禁止测试；禁止启动服务；禁止执行迁移；禁止 Git 修改（包括 add、commit、reset、checkout）。

请仅汇总发现、风险和后续建议，不要执行任何会改变项目、Git 状态或运行环境的操作。"""


@dataclass(frozen=True)
class ProjectInitializationDispatchResult:
    state: ProjectInitializationDispatchState
    session_id: str
    client_message_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "session_id": self.session_id,
            "client_message_id": self.client_message_id,
        }


def project_initialization_client_message_id(session: AIChatSession) -> str:
    identity = f"project_initialization:{session.id}:{session.public_id or ''}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"msg_project_init_{digest}"


async def dispatch_project_initialization_message(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    send_runtime_message: RuntimeMessageSender,
) -> ProjectInitializationDispatchResult:
    """Send the stable one-time message and retain a retryable terminal record."""

    client_message_id = project_initialization_client_message_id(session)
    session.initialization_task_key = client_message_id
    result = ProjectInitializationDispatchResult(
        session_id=str(session.public_id or session.id),
        state="retryable_failed",
        client_message_id=client_message_id,
    )
    if session.initialization_task_state == "sent":
        return ProjectInitializationDispatchResult(
            session_id=result.session_id,
            state="already_sent",
            client_message_id=client_message_id,
        )

    runtime_session_id = str(binding.runtime_session_id or "").strip()
    if not runtime_session_id:
        session.initialization_task_state = "retryable_failed"
        return result

    try:
        await send_runtime_message(
            runtime_session_id,
            client_message_id,
            PROJECT_INITIALIZATION_PROMPT,
        )
    except HTTPException:
        session.initialization_task_state = "retryable_failed"
        return result

    session.initialization_task_state = "sent"
    return ProjectInitializationDispatchResult(
        session_id=result.session_id,
        state="sent",
        client_message_id=client_message_id,
    )
