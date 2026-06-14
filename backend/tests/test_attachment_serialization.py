"""粘贴的截图在会话历史里要能显示 → 后端附件序列化必须回带图片 data URL。

历史 bug:`_attachment_to_dict` 只回 `has_image: bool`,不回 `image_data_url`,前端历史
拿不到图片数据 → 用户消息气泡里的截图不显示(虽然 AI 收到了 vision)。
"""
from app.models.ai_chat import AIChatAttachment
from app.routes.ai_chat import _attachment_to_dict


def test_image_attachment_includes_data_url():
    att = AIChatAttachment(
        session_id=1,
        filename="shot.png",
        kind="image",
        mime="image/png",
        size_bytes=100,
        image_data_url="data:image/png;base64,AAAA",
    )
    d = _attachment_to_dict(att)
    assert d["has_image"] is True
    assert d["image_data_url"] == "data:image/png;base64,AAAA"


def test_non_image_attachment_no_data_url():
    att = AIChatAttachment(
        session_id=1,
        filename="doc.pdf",
        kind="pdf",
        mime="application/pdf",
        size_bytes=100,
        content_text="hello",
    )
    d = _attachment_to_dict(att)
    assert d["has_image"] is False
    # 非图片不回带 image_data_url(避免响应膨胀)
    assert d.get("image_data_url") is None
