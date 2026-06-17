"""粘贴的截图在会话历史里要能显示 → 后端附件序列化必须回带图片 data URL。

历史 bug:`_attachment_to_dict` 只回 `has_image: bool`,不回 `image_data_url`,前端历史
拿不到图片数据 → 用户消息气泡里的截图不显示(虽然 AI 收到了 vision)。
"""
from app.models.ai_chat import AIChatAttachment
from app.routes.ai_chat import _attachment_to_dict
from app.routes.chat import DOC_PARSE_ERROR_PREFIX


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
    # 真正有正文 → has_content_text True, 无解析失败标记
    assert d["has_content_text"] is True
    assert d["parse_failed"] is False
    assert d["parse_error"] is None


def test_parsed_ok_attachment_reports_content():
    att = AIChatAttachment(
        session_id=1, filename="ok.docx", kind="docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=100, content_text="正文内容",
    )
    d = _attachment_to_dict(att)
    assert d["has_content_text"] is True
    assert d["parse_failed"] is False
    assert d["parse_error"] is None


def test_failed_parse_attachment_not_reported_as_content():
    """解析失败时 content_text 存的是错误标记 → has_content_text 必须为 False,
    并单独透出 parse_failed/parse_error 让前端区分。"""
    att = AIChatAttachment(
        session_id=1, filename="bad.pdf", kind="pdf",
        mime="application/pdf", size_bytes=100,
        content_text=DOC_PARSE_ERROR_PREFIX + "桌面端缺少 PDF 解析库 (pdfplumber)",
    )
    d = _attachment_to_dict(att)
    # 关键回归: 旧实现 bool(content_text) 会误报 True
    assert d["has_content_text"] is False
    assert d["parse_failed"] is True
    assert d["parse_error"] == "桌面端缺少 PDF 解析库 (pdfplumber)"
