from datetime import datetime

from app.routes.chat import _append_decision_message, _format_pending_decision_message
from app.builder_spec.schema import Decision, Phase


def _decision(
    decision_id: str,
    topic: str,
    *,
    why_blocking: str = "需要确认后才能继续生成配置",
    options: list[str] | None = None,
    resolved: bool = False,
) -> Decision:
    return Decision(
        id=decision_id,
        topic=topic,
        why_blocking=why_blocking,
        options=options or [],
        blocking=True,
        raised_in_phase=Phase.GATHERING,
        resolved=resolved,
        created_at=datetime(2026, 4, 27, 10, 0, 0),
    )


def test_pending_decisions_are_rendered_as_chat_reply():
    message = _format_pending_decision_message([
        _decision(
            "d_scope",
            "组织使用范围",
            options=["单仓库使用", "多个仓库统一管理"],
        ),
        _decision("d_stock", "库存数量口径", resolved=True),
    ])

    assert "我需要你确认「组织使用范围」" in message
    assert "组织使用范围" in message
    assert "单仓库使用" not in message
    assert "多个仓库统一管理" not in message
    assert "库存数量口径" not in message


def test_append_decision_message_does_not_duplicate_existing_question():
    existing = "接下来需要确认组织使用范围，我会根据你的回复继续。"
    final_text, appended = _append_decision_message(
        existing,
        [_decision("d_scope", "组织使用范围")],
    )

    assert final_text == existing
    assert appended == ""
