from pathlib import Path
from types import SimpleNamespace

from app.agents.coding import tools as coding_tools


def _make_skill(skills_dir: Path, name: str, body: str, extra: dict | None = None):
    d = skills_dir / "user" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: 测试技能\n---\n{body}\n", encoding="utf-8"
    )
    for fname, content in (extra or {}).items():
        (d / fname).write_text(content, encoding="utf-8")


def _get_tool(name: str):
    for t in coding_tools.build_coding_tools():
        if t.name == name:
            return t
    raise AssertionError(f"tool {name} not found")


async def test_use_skill_copies_files_and_returns_body(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "demo", "## 步骤\n1. 做点事", extra={"helper.py": "print('hi')"})
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(skills_dir))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute({"name": "demo"}, SimpleNamespace(workspace_id="w1"))

    assert res.success
    assert "## 步骤" in res.content
    assert (ws / "skill_demo" / "helper.py").exists()
    assert not (ws / "skill_demo" / "SKILL.md").exists()


async def test_use_skill_unknown_lists_available(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "demo", "x")
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(skills_dir))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute({"name": "nope"}, SimpleNamespace(workspace_id="w1"))

    assert not res.success
    assert "demo" in res.content  # 列出可用技能


async def test_use_skill_no_skills_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "empty"))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute({"name": "demo"}, SimpleNamespace(workspace_id="w1"))

    assert not res.success  # 无技能 → 友好报错,不抛异常
