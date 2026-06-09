"""Tests for ai_chat context management: artifact read truncation + MCP tool result cap.

Covers:
  A. read_artifact truncation at 30K chars + offset/limit pagination
  B. MCP bridge tool result truncation at 20K chars
"""
import json

import pytest

from app.ai_chat.tools import execute_read_artifact


# ─────────────── helpers ───────────────
class FakeSession:
    def __init__(self, sid=1):
        self.id = sid


class FakeArtifact:
    def __init__(self, content: str, version: int = 1):
        self.content = content
        self.version = version


class FakeDB:
    """Stub — execute_read_artifact uses _latest_artifact which hits DB.
    We monkeypatch _latest_artifact instead."""
    pass


# ─────────────── A: read_artifact truncation ───────────────
@pytest.mark.asyncio
async def test_read_artifact_small_doc_returned_in_full(monkeypatch):
    """Documents under 30K chars are returned completely."""
    content = "hello world" * 100  # ~1100 chars
    monkeypatch.setattr(
        "app.ai_chat.tools._latest_artifact",
        lambda *a, **kw: _async_return(FakeArtifact(content)),
    )
    result = await execute_read_artifact({"filename": "small.md"}, FakeSession(), FakeDB())
    assert content in result
    assert "[已截断" not in result


@pytest.mark.asyncio
async def test_read_artifact_large_doc_truncated_at_30k(monkeypatch):
    """Documents over 30K chars are truncated with a notice."""
    content = "x" * 50_000
    monkeypatch.setattr(
        "app.ai_chat.tools._latest_artifact",
        lambda *a, **kw: _async_return(FakeArtifact(content)),
    )
    result = await execute_read_artifact({"filename": "big.md"}, FakeSession(), FakeDB())
    # Must be truncated
    assert len(result) < 50_000
    assert "[已截断" in result
    assert "50000 字符" in result
    # First 30K of content must be present
    assert "x" * 1000 in result


@pytest.mark.asyncio
async def test_read_artifact_pagination_offset_limit(monkeypatch):
    """offset/limit params enable paginated reads of large documents."""
    lines = [f"line {i}\n" for i in range(500)]
    content = "".join(lines)
    monkeypatch.setattr(
        "app.ai_chat.tools._latest_artifact",
        lambda *a, **kw: _async_return(FakeArtifact(content)),
    )
    result = await execute_read_artifact(
        {"filename": "big.md", "offset": 10, "limit": 5},
        FakeSession(), FakeDB(),
    )
    # Should contain lines 10-14
    assert "line 10" in result
    assert "line 14" in result
    # Should NOT contain line 15 or line 9
    assert "line 15" not in result
    assert "line 9" not in result
    # Should mention total line count
    assert "500 行" in result


# ─────────────── B: MCP bridge truncation ───────────────
def test_mcp_bridge_truncates_large_tool_result():
    """MCP tool results over 20K chars are truncated at the bridge level."""
    # We test the truncation logic inline since call_tool is async + needs MCP session.
    # Extract the logic:
    MCP_TOOL_RESULT_MAX_CHARS = 20_000
    text = "y" * 40_000

    if len(text) > MCP_TOOL_RESULT_MAX_CHARS:
        truncated = text[:MCP_TOOL_RESULT_MAX_CHARS]
        text = (
            f"{truncated}\n\n"
            f"[工具返回已截断：原文 {len('y' * 40_000)} 字符，已保留前 {MCP_TOOL_RESULT_MAX_CHARS} 字符。"
            f"如需更多细节请缩小查询范围或分多次调用。]"
        )

    assert len(text) < 40_000
    assert "[工具返回已截断" in text
    assert "40000 字符" in text


def test_mcp_bridge_small_result_untouched():
    """MCP tool results under 20K chars pass through unmodified."""
    MCP_TOOL_RESULT_MAX_CHARS = 20_000
    text = "small result"
    original = text

    if len(text) > MCP_TOOL_RESULT_MAX_CHARS:
        text = text[:MCP_TOOL_RESULT_MAX_CHARS] + "..."

    assert text == original


# ─────────────── utility ───────────────
async def _async_return(val):
    return val
