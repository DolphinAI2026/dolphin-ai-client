from types import SimpleNamespace

from app.agents.coding import tools as coding_tools


def _get_tool(name: str):
    for t in coding_tools.build_coding_tools():
        if t.name == name:
            return t
    raise AssertionError(f"tool {name} not found")


async def test_run_python_tool_executes_and_captures_stdout(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("run_python").execute(
        {"code": "print('hello-skill')"}, SimpleNamespace(workspace_id="w1")
    )

    assert res.success
    assert "hello-skill" in res.content


async def test_run_python_tool_missing_code(tmp_path, monkeypatch):
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: tmp_path)
    res = await _get_tool("run_python").execute({"code": "  "}, SimpleNamespace(workspace_id="w1"))
    assert not res.success


def test_build_coding_tools_has_skill_tools_and_no_dupes():
    names = [t.name for t in coding_tools.build_coding_tools()]
    assert "use_skill" in names
    assert "run_python" in names
    assert len(names) == len(set(names))  # 无重名
