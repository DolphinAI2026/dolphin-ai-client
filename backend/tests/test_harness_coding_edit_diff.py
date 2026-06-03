"""harness coding 路径:edit_file/write_file 富参数(old/new/content)要流到前端(2026-06)。

背景(② live 跑挖出的 bug):a3f31bf 在 CodingAgent.before_tool_call 把 write_file/edit_file
的 file_path/old_string/new_string/content 放进事件的 `input` 字段(前端 FileCard 据此渲染红绿
diff + 行号)。但**用户实际走的 harness 路径**:
  profiles/coding.py 把 pipeline agent_tool 事件转成 harness item 时,曾读 `event.get("args")`
  (空)而非 `event.get("input")`(富数据)→ 富数据被丢 → 前端 parsed.input||parsed.args 全空
  → edit 红绿 diff 没数据。

本测试锁两段契约:
1. CodingSSEAdapter 把 harness item 的 tool_call(带 args=富数据)透传成 agent_tool 事件,args 保留。
2. (回归)前端读取口径:agent_tool 事件的 args 里要有 old_string/new_string(edit)/content(write)。
profile 那半(input→args)由 live 端到端验证。
"""
from __future__ import annotations

from app.harness.sse_adapter import CodingSSEAdapter
from app.harness.events import ITEM_STARTED


def _item_started(data: dict) -> dict:
    return {"event_type": ITEM_STARTED, "data": data}


def test_coding_sse_adapter_forwards_edit_file_old_new():
    """harness item(tool_call, args 含 old/new)→ agent_tool 事件,args 保留 old/new(红绿 diff 数据)。"""
    out = CodingSSEAdapter().translate(_item_started({
        "kind": "tool_call",
        "tool": "edit_file",
        "tool_display": "✏️ Edit",
        "preview": "src/x.vue: <div> -> ...",
        "args": {"file_path": "src/x.vue", "old_string": "<div>旧</div>", "new_string": "<div>新</div>"},
    }))
    assert out["type"] == "agent_tool"
    assert out["tool"] == "edit_file"
    assert out["args"]["old_string"] == "<div>旧</div>"
    assert out["args"]["new_string"] == "<div>新</div>"
    assert out["args"]["file_path"] == "src/x.vue"


def test_coding_sse_adapter_forwards_write_file_content():
    """write_file 的 content 也要透传(前端文件卡 + 行号)。"""
    out = CodingSSEAdapter().translate(_item_started({
        "kind": "tool_call",
        "tool": "write_file",
        "tool_display": "📝 Write",
        "preview": "src/y.vue (12 lines)",
        "args": {"file_path": "src/y.vue", "content": "line1\nline2\n"},
    }))
    assert out["type"] == "agent_tool"
    assert out["args"]["content"] == "line1\nline2\n"
    assert out["args"]["file_path"] == "src/y.vue"
