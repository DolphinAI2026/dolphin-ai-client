"""CRITICAL 2 — 验证 compact 后 tool 消息不出现孤儿 (orphan tool_call_id)"""
from app.context_compact import ContextCompactor


def _build_history(n_rounds: int):
    """构造 n_rounds 轮带 tool_calls 的对话历史"""
    msgs = []
    for i in range(n_rounds):
        call_id = f"c{i}"
        msgs.append({
            "role": "user",
            "content": f"user message {i}",
        })
        msgs.append({
            "role": "assistant",
            "content": f"thinking {i}",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }],
        })
        msgs.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": f"tool result {i}",
        })
    return msgs


def test_no_orphan_tool_messages_after_compact():
    """
    compact(mode='coding_with_workspace') 后，每条 tool 消息的 tool_call_id
    必须能在其前面的 assistant 消息的 tool_calls 中找到。
    Bug: assistant 消息被重建为 {"role":"assistant","content":summary} 丢失 tool_calls，
    导致后续 tool 消息成为孤儿。
    """
    history = _build_history(n_rounds=8)  # > max_rounds=6，必然触发压缩

    compactor = ContextCompactor()
    result = compactor.compact(history, mode="coding_with_workspace")

    # 建立 tool_call_id → bool 索引
    declared_ids: set[str] = set()
    for msg in result:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                declared_ids.add(tc["id"])

    orphans = []
    for msg in result:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id", "")
            if tid not in declared_ids:
                orphans.append(tid)

    assert not orphans, (
        f"发现孤儿 tool_call_id: {orphans}。"
        f"result roles: {[m['role'] for m in result]}"
    )
