import json

from app.ai_chat.agent import (
    _compact_tool_args_for_storage,
    _compact_tool_call_for_storage,
)


def test_compacts_write_workspace_files_content_for_storage():
    args = {
        "ws_id": "ws_1",
        "files": [
            {
                "file_path": "src/App.vue",
                "content": "<template>" + ("x" * 50_000) + "</template>",
            }
        ],
    }

    compacted = _compact_tool_args_for_storage("write_workspace_files", args)

    assert compacted["ws_id"] == "ws_1"
    content = compacted["files"][0]["content"]
    assert content["_omitted_large_text"] is True
    assert content["chars"] > 50_000
    assert len(json.dumps(compacted, ensure_ascii=False)) < 2_000


def test_compacts_tool_call_arguments_string_for_message_history():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "write_artifact",
            "arguments": json.dumps(
                {
                    "filename": "SPEC.md",
                    "content": "# Title\n" + ("body\n" * 20_000),
                    "format": "md",
                },
                ensure_ascii=False,
            ),
        },
    }

    compacted = _compact_tool_call_for_storage(tool_call)
    stored_args = json.loads(compacted["function"]["arguments"])

    assert compacted["id"] == "call_1"
    assert stored_args["filename"] == "SPEC.md"
    assert stored_args["content"]["_omitted_large_text"] is True
    assert len(compacted["function"]["arguments"]) < 2_000
