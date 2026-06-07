from types import SimpleNamespace

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
