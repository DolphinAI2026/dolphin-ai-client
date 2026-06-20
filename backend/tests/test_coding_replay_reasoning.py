"""
Tests for the replay-path reasoning/thinking split fix.
Ensures append_event_to_stream_replay correctly separates reasoning (chain-of-thought)
from regular thinking cards, mirroring the live-stream behaviour.
"""
from app.coding.pipeline import append_event_to_stream_replay


# ---------------------------------------------------------------------------
# agent_thinking events
# ---------------------------------------------------------------------------

def test_agent_thinking_reasoning_true_creates_reasoning_card():
    msgs: list = []
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking",
        "content": "Let me reason through this step by step.",
        "reasoning": True,
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "reasoning"
    assert msgs[0]["collapsed"] is True
    assert "reason" in msgs[0]["content"]


def test_agent_thinking_reasoning_false_creates_thinking_card():
    msgs: list = []
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking",
        "content": "Thinking about the task.",
        "reasoning": False,
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "thinking"
    assert msgs[0].get("collapsed") is None or msgs[0].get("collapsed") is not True


def test_agent_thinking_no_reasoning_key_creates_thinking_card():
    msgs: list = []
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking",
        "content": "Plain thinking block.",
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "thinking"


def test_agent_thinking_reasoning_does_not_merge_into_thinking_card():
    """A reasoning event must NOT dedup/merge into an existing thinking card."""
    msgs: list = []
    # First push a regular thinking card
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking",
        "content": "First thinking block.",
    })
    assert msgs[-1]["type"] == "thinking"

    # Now a reasoning event with a completely different content → separate card
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking",
        "content": "Separate reasoning block.",
        "reasoning": True,
    })
    assert len(msgs) == 2
    assert msgs[1]["type"] == "reasoning"
    assert msgs[1]["collapsed"] is True


# ---------------------------------------------------------------------------
# agent_thinking_delta events
# ---------------------------------------------------------------------------

def test_agent_thinking_delta_reasoning_creates_reasoning_card():
    msgs: list = []
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking_delta",
        "content": "First chunk",
        "reasoning": True,
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "reasoning"
    assert msgs[0]["collapsed"] is True
    assert msgs[0]["content"] == "First chunk"


def test_agent_thinking_delta_reasoning_accumulates():
    """Consecutive reasoning deltas accumulate into a single reasoning card."""
    msgs: list = []
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking_delta",
        "content": "Part one. ",
        "reasoning": True,
    })
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking_delta",
        "content": "Part two.",
        "reasoning": True,
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "reasoning"
    assert msgs[0]["content"] == "Part one. Part two."
    assert msgs[0]["collapsed"] is True


def test_agent_thinking_delta_no_reasoning_uses_thinking():
    msgs: list = []
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking_delta",
        "content": "delta chunk",
    })
    assert len(msgs) == 1
    assert msgs[0]["type"] == "thinking"


def test_agent_thinking_delta_reasoning_does_not_merge_into_thinking_card():
    """reasoning delta must not append to an existing thinking card."""
    msgs: list = []
    # Prime a thinking card
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking_delta",
        "content": "thinking delta",
    })
    assert msgs[-1]["type"] == "thinking"

    # Reasoning delta must create a new reasoning card
    append_event_to_stream_replay(msgs, {
        "type": "agent_thinking_delta",
        "content": "reasoning delta",
        "reasoning": True,
    })
    assert len(msgs) == 2
    assert msgs[1]["type"] == "reasoning"
    assert msgs[1]["collapsed"] is True
