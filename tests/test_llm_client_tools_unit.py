"""LLMClient tools 参数相关的单元测试。

覆盖：
- tools 格式转换（OpenAI → Anthropic）
- tool_choice 转换
- 响应解析（tool_use block → OpenAI tool_calls）
- _prepare_messages 处理 assistant.tool_calls / role=tool
- 现有调用兼容性（不传 tools 时行为不变）
"""
import json
import os
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.llm_client import LLMClient


# ═════════════════════════════════════════════════════════════
# 1. tools 格式转换（OpenAI → Anthropic）
# ═════════════════════════════════════════════════════════════

def test_convert_openai_tools_to_anthropic_basic():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    result = LLMClient._convert_openai_tools_to_anthropic(tools)
    assert result == [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]


def test_convert_openai_tools_to_anthropic_empty():
    assert LLMClient._convert_openai_tools_to_anthropic([]) == []
    assert LLMClient._convert_openai_tools_to_anthropic(None) == []


def test_convert_openai_tools_skip_invalid():
    tools = [
        {"type": "function", "function": {"name": "valid"}},
        "not a dict",   # 跳过
        {"type": "function", "function": {}},  # 无 name 跳过
    ]
    result = LLMClient._convert_openai_tools_to_anthropic(tools)
    assert len(result) == 1
    assert result[0]["name"] == "valid"


def test_convert_openai_tools_flat_format():
    """兼容 Anthropic-like 平铺格式"""
    tools = [{"name": "flat_tool", "description": "desc", "input_schema": {"type": "object"}}]
    result = LLMClient._convert_openai_tools_to_anthropic(tools)
    assert result[0]["name"] == "flat_tool"
    assert result[0]["input_schema"] == {"type": "object"}


# ═════════════════════════════════════════════════════════════
# 2. tool_choice 转换
# ═════════════════════════════════════════════════════════════

def test_tool_choice_auto():
    assert LLMClient._convert_openai_tool_choice_to_anthropic("auto") == {"type": "auto"}


def test_tool_choice_none():
    assert LLMClient._convert_openai_tool_choice_to_anthropic("none") is None


def test_tool_choice_required():
    assert LLMClient._convert_openai_tool_choice_to_anthropic("required") == {"type": "any"}


def test_tool_choice_specific_function():
    result = LLMClient._convert_openai_tool_choice_to_anthropic({
        "type": "function",
        "function": {"name": "my_tool"},
    })
    assert result == {"type": "tool", "name": "my_tool"}


def test_tool_choice_already_anthropic():
    """已经是 Anthropic 格式直接返回"""
    assert LLMClient._convert_openai_tool_choice_to_anthropic({"type": "auto"}) == {"type": "auto"}
    assert LLMClient._convert_openai_tool_choice_to_anthropic({"type": "tool", "name": "x"}) == {
        "type": "tool",
        "name": "x",
    }


def test_tool_choice_none_input():
    assert LLMClient._convert_openai_tool_choice_to_anthropic(None) is None


# ═════════════════════════════════════════════════════════════
# 3. 响应解析（Anthropic content → text + reasoning + tool_uses）
# ═════════════════════════════════════════════════════════════

def test_parse_anthropic_content_text_only():
    data = {"content": [{"type": "text", "text": "hello"}]}
    text, reasoning, tools = LLMClient._parse_anthropic_content(data)
    assert text == "hello"
    assert reasoning == []
    assert tools == []


def test_parse_anthropic_content_with_tool_use():
    data = {
        "content": [
            {"type": "text", "text": "Let me read the file"},
            {
                "type": "tool_use",
                "id": "toolu_01ABC",
                "name": "read_file",
                "input": {"path": "/etc/hosts"},
            },
        ]
    }
    text, reasoning, tools = LLMClient._parse_anthropic_content(data)
    assert text == "Let me read the file"
    assert len(tools) == 1
    assert tools[0] == {
        "id": "toolu_01ABC",
        "name": "read_file",
        "input": {"path": "/etc/hosts"},
    }


def test_parse_anthropic_content_with_thinking():
    data = {
        "content": [
            {"type": "thinking", "thinking": "I need to think..."},
            {"type": "text", "text": "OK"},
        ]
    }
    text, reasoning, tools = LLMClient._parse_anthropic_content(data)
    assert text == "OK"
    assert reasoning == [{"text": "I need to think..."}]


def test_anthropic_tool_uses_to_openai_tool_calls():
    tool_uses = [{"id": "tid_1", "name": "read_file", "input": {"path": "x"}}]
    result = LLMClient._anthropic_tool_uses_to_openai_tool_calls(tool_uses)
    assert len(result) == 1
    assert result[0]["id"] == "tid_1"
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "read_file"
    # arguments 必须是 JSON 字符串（OpenAI 合约）
    assert isinstance(result[0]["function"]["arguments"], str)
    assert json.loads(result[0]["function"]["arguments"]) == {"path": "x"}


def test_tool_use_empty_input():
    """空 input 应变成 {} 而非报错"""
    tool_uses = [{"id": "t1", "name": "noop", "input": None}]
    result = LLMClient._anthropic_tool_uses_to_openai_tool_calls(tool_uses)
    # input=None → input={}，然后 json.dumps({}) = "{}"
    assert json.loads(result[0]["function"]["arguments"]) == {}


# ═════════════════════════════════════════════════════════════
# 4. _normalize_to_openai 整合（含 tool_calls + finish_reason）
# ═════════════════════════════════════════════════════════════

def _make_client():
    """构造不依赖真实 env 的测试 client"""
    c = LLMClient.__new__(LLMClient)
    c.api_key = "test"
    c.model = "test-model"
    c._openai_base_url = None
    c.anthropic_base_url = "https://api.anthropic.com"
    c.anthropic_api_key = "test"
    c.anthropic_model = "test-model"
    c.doc_model = "test-model"
    c.vision_model = "test-model"
    return c


def test_normalize_with_tool_use():
    client = _make_client()
    data = {
        "id": "msg_01",
        "model": "test-model",
        "content": [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.txt"}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    result = client._normalize_to_openai(data, model="test-model")
    msg = result["choices"][0]["message"]
    assert msg["content"] == "thinking..."
    assert "tool_calls" in msg
    assert msg["tool_calls"][0]["function"]["name"] == "read_file"
    # tool_use → tool_calls 映射
    assert result["choices"][0]["finish_reason"] == "tool_calls"


def test_normalize_without_tool_use_backward_compat():
    """不带 tool_use 时行为与旧版一致（无 tool_calls 字段）"""
    client = _make_client()
    data = {
        "id": "msg_01",
        "model": "test-model",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = client._normalize_to_openai(data, model="test-model")
    msg = result["choices"][0]["message"]
    assert msg["content"] == "hello"
    assert "tool_calls" not in msg
    assert result["choices"][0]["finish_reason"] == "stop"


def test_normalize_finish_reason_max_tokens():
    client = _make_client()
    data = {
        "content": [{"type": "text", "text": "..."}],
        "stop_reason": "max_tokens",
        "usage": {},
    }
    result = client._normalize_to_openai(data, model="x")
    assert result["choices"][0]["finish_reason"] == "length"


# ═════════════════════════════════════════════════════════════
# 5. _prepare_messages（assistant.tool_calls + role=tool）
# ═════════════════════════════════════════════════════════════

def test_prepare_messages_system_only():
    client = _make_client()
    msgs = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "hi"},
    ]
    system_text, api_msgs = client._prepare_messages(msgs)
    assert system_text == "You are helpful"
    assert len(api_msgs) == 1
    assert api_msgs[0]["role"] == "user"


def test_prepare_messages_assistant_with_tool_calls():
    """OpenAI 风格的 assistant.tool_calls → Anthropic tool_use block"""
    client = _make_client()
    msgs = [
        {"role": "user", "content": "read file"},
        {
            "role": "assistant",
            "content": "Let me do that",
            "tool_calls": [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "/tmp/x"}',
                    },
                }
            ],
        },
    ]
    _system, api_msgs = client._prepare_messages(msgs)
    assert len(api_msgs) == 2
    assistant_msg = api_msgs[1]
    assert assistant_msg["role"] == "assistant"
    blocks = assistant_msg["content"]
    assert isinstance(blocks, list)
    # 应包含 text block + tool_use block
    assert any(b.get("type") == "text" for b in blocks)
    tool_use = next(b for b in blocks if b.get("type") == "tool_use")
    assert tool_use["id"] == "t1"
    assert tool_use["name"] == "read_file"
    assert tool_use["input"] == {"path": "/tmp/x"}


def test_prepare_messages_tool_role_as_user_tool_result():
    """role=tool → 合并到 user message 的 tool_result block"""
    client = _make_client()
    msgs = [
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "result text"},
    ]
    _system, api_msgs = client._prepare_messages(msgs)
    # [user, assistant(tool_use), user(tool_result)]
    assert len(api_msgs) == 3
    last = api_msgs[-1]
    assert last["role"] == "user"
    assert isinstance(last["content"], list)
    assert last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "t1"
    assert last["content"][0]["content"] == "result text"


def test_prepare_messages_multiple_tool_results_merged():
    """连续多条 role=tool 应合并到同一个 user message"""
    client = _make_client()
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                {"id": "t2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "r1"},
        {"role": "tool", "tool_call_id": "t2", "content": "r2"},
    ]
    _system, api_msgs = client._prepare_messages(msgs)
    # [assistant, user(含两个 tool_result)]
    assert len(api_msgs) == 2
    last = api_msgs[-1]
    assert last["role"] == "user"
    assert len(last["content"]) == 2
    assert last["content"][0]["tool_use_id"] == "t1"
    assert last["content"][1]["tool_use_id"] == "t2"


def test_prepare_messages_tool_invalid_json_arguments():
    """tool_calls.arguments 不是合法 JSON 时降级为空 dict"""
    client = _make_client()
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "bad", "arguments": "not valid json {"},
                }
            ],
        }
    ]
    _system, api_msgs = client._prepare_messages(msgs)
    tool_use = api_msgs[0]["content"][0]
    assert tool_use["type"] == "tool_use"
    assert tool_use["input"] == {}


# ═════════════════════════════════════════════════════════════
# 6. 向后兼容性：老格式 messages 不受影响
# ═════════════════════════════════════════════════════════════

def test_backward_compat_plain_messages():
    """不带 tools 的普通对话 - 与老版行为一致"""
    client = _make_client()
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    system_text, api_msgs = client._prepare_messages(msgs)
    assert system_text == "sys"
    assert len(api_msgs) == 2
    # content 是字符串（原逻辑），不是 list
    assert api_msgs[0]["content"] == "hello"
    assert api_msgs[1]["content"] == "hi"


def test_backward_compat_collect_text_wrapper():
    """_collect_text_from_response 保留向后兼容"""
    data = {"content": [{"type": "text", "text": "ok"}]}
    text, reasoning = LLMClient._collect_text_from_response(data)
    assert text == "ok"
    assert reasoning == []


if __name__ == "__main__":
    # 手动运行所有测试
    import inspect
    current = sys.modules[__name__]
    tests = [
        (n, f) for n, f in inspect.getmembers(current, inspect.isfunction)
        if n.startswith("test_")
    ]
    passed = failed = 0
    for name, func in tests:
        try:
            func()
            print(f"✓ {name}")
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
