from app.routes.coding import _normalize_stream_payload


def test_normalize_stream_payload_preserves_user_attachments():
    out = _normalize_stream_payload([
        {
            "type": "user",
            "content": "数据字典是不是没有生成全啊?",
            "attachments": [
                {
                    "kind": "image",
                    "filename": "dict.png",
                    "url": "/api/coding/workspace/ws-1/raw?file_path=uploads%2Fdict.png",
                    "relative_path": "uploads/dict.png",
                    "content_type": "image/png",
                    "unsafe": "<script>",
                }
            ],
        }
    ])

    assert out == [
        {
            "type": "user",
            "content": "数据字典是不是没有生成全啊?",
            "attachments": [
                {
                    "kind": "image",
                    "filename": "dict.png",
                    "url": "/api/coding/workspace/ws-1/raw?file_path=uploads%2Fdict.png",
                    "relative_path": "uploads/dict.png",
                    "content_type": "image/png",
                }
            ],
        }
    ]
