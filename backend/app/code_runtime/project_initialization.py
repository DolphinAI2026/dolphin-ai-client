"""Read-only project initialization message dispatch for Code shells."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException

from app.code_runtime.service import code_session_route_id
from app.models.ai_chat import AIChatSession, CodeRuntimeBinding


ProjectInitializationDispatchState = Literal["sent", "already_sent", "retryable_failed"]
RuntimeMessageSender = Callable[[str, str, str], Awaitable[Any]]

PROJECT_INITIALIZATION_PROMPT = """你正在执行项目初始化的只读检查。

非 Git 项目同样有效。仅允许检查：项目结构、README 和 AGENTS 指南、依赖清单与锁文件、入口文件和脚本、Git 状态，以及当前环境可用性。允许进行 Git、Python、Node 的只读可用性检查。
禁止 git init；禁止文件创建/删除；禁止系统环境和工程配置修改；禁止写入或修改任何文件；禁止安装依赖；禁止构建；禁止测试；禁止启动服务；禁止执行迁移；禁止 Git 修改（包括 add、commit、reset、checkout）。

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


def _project_initialization_identity(session: AIChatSession) -> str | None:
    logical_application_id = str(session.logical_application_id or "").strip()
    execution_location = str(session.execution_location or "").strip().lower()
    try:
        shell_session_ref = code_session_route_id(int(session.id))
    except (TypeError, ValueError):
        return None
    if not logical_application_id or execution_location != "local":
        return None
    return f"project_initialization:{logical_application_id}:local:{shell_session_ref}"


def project_initialization_client_message_id(session: AIChatSession) -> str:
    identity = _project_initialization_identity(session)
    if identity is None:
        identity = f"project_initialization_invalid:{session.id}:{session.public_id or ''}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"msg_project_init_{digest}"


async def dispatch_project_initialization_message(
    session: AIChatSession,
    binding: CodeRuntimeBinding,
    send_runtime_message: RuntimeMessageSender,
) -> ProjectInitializationDispatchResult:
    """Send the stable one-time message and retain a retryable terminal record."""

    session_id = str(session.public_id or session.id)
    existing_task_key = str(session.initialization_task_key or "").strip()
    if session.initialization_task_state in {"sent", "completed"}:
        return ProjectInitializationDispatchResult(
            session_id=session_id,
            state="already_sent",
            client_message_id=existing_task_key or project_initialization_client_message_id(session),
        )

    client_message_id = project_initialization_client_message_id(session)
    result = ProjectInitializationDispatchResult(
        session_id=session_id,
        state="retryable_failed",
        client_message_id=client_message_id,
    )
    if _project_initialization_identity(session) is None:
        session.initialization_task_state = "retryable_failed"
        return result

    session.initialization_task_key = client_message_id

    binding_status = str(binding.status or "").strip().lower()
    runtime_session_id = str(binding.runtime_session_id or "").strip()
    if binding_status != "ready" or not runtime_session_id:
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
