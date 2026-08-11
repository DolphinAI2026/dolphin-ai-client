from types import SimpleNamespace

import pytest

from app.routes import ai_chat
from app.routes.ai_chat import _derive_session_title


def test_derive_session_title_from_markdown_h1_for_attachment_only_chat():
    title = _derive_session_title(
        artifacts=[
            SimpleNamespace(
                filename="配额申请_配置文档.md",
                content="# 配额申请配置文档\n\n## 使用说明\n...",
            )
        ]
    )

    assert title == "配额申请配置文档"


def test_derive_session_title_falls_back_to_attachment_filename():
    title = _derive_session_title(
        attachments=[
            SimpleNamespace(filename="配额申请_配置文档.md"),
        ]
    )

    assert title == "配额申请配置文档"


@pytest.mark.asyncio
async def test_system_assistant_first_turn_title_keeps_the_user_question(monkeypatch):
    async def unrelated_model_title(*_args, **_kwargs):
        return "理论上应用能干什么"

    monkeypatch.setattr(ai_chat, "generate_title", unrelated_model_title)

    title = await ai_chat._derive_first_turn_title(
        None,
        SimpleNamespace(assistant_profile="system_assistant"),
        "排查组织切换后仍显示管理员组织",
    )

    assert title == "排查组织切换后仍显示管理员组织"


@pytest.mark.asyncio
async def test_entry_agent_first_turn_title_keeps_model_summary(monkeypatch):
    async def generated_title(*_args, **_kwargs):
        return "组织切换异常排查"

    monkeypatch.setattr(ai_chat, "generate_title", generated_title)

    title = await ai_chat._derive_first_turn_title(
        None,
        SimpleNamespace(assistant_profile="entry_agent"),
        "帮我看看这个问题",
    )

    assert title == "组织切换异常排查"
