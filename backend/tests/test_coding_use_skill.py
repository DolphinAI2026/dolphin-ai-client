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


def _make_skill_with_frontmatter_name(
    skills_dir: Path, dirname: str, frontmatter_name: str, extra: dict | None = None
):
    """创建一个目录名 != frontmatter name 的技能(用于测试路径穿越场景)。"""
    import re

    d = skills_dir / "user" / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {frontmatter_name}\ndescription: 路径穿越测试技能\n---\n## 测试技能\n",
        encoding="utf-8",
    )
    for fname, content in (extra or {}).items():
        (d / fname).write_text(content, encoding="utf-8")


async def test_use_skill_path_traversal_stays_inside_workspace(tmp_path, monkeypatch):
    """路径穿越名 '../../../tmp/pwned_<uid>' 经 slug 化后必须落在 workspace 内。"""
    import re

    uid = "abctest"
    malicious_name = f"../../../tmp/pwned_{uid}"
    skills_dir = tmp_path / "skills"
    _make_skill_with_frontmatter_name(
        skills_dir,
        dirname="traversal_skill",
        frontmatter_name=malicious_name,
        extra={"payload.txt": "should land inside ws"},
    )
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(skills_dir))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute(
        {"name": malicious_name}, SimpleNamespace(workspace_id="w1")
    )

    # 计算期望的 slug(与实现保持一致)
    expected_slug = re.sub(r"[^A-Za-z0-9_-]", "_", malicious_name)
    expected_dir = ws / f"skill_{expected_slug}"

    # 无论成功还是被防御拒绝,payload 都不应出现在 ws 外的 /tmp 路径
    assert not Path(f"/tmp/pwned_{uid}").exists(), "文件不应被写到 /tmp 目录外"
    assert not Path(f"/tmp/pwned_{uid}/payload.txt").exists(), "payload 不应逃逸到 /tmp"

    if res.success:
        # 如果 slug 化后的路径仍在 ws 内(即 ws in dest.parents),则文件应落在 ws 下
        assert expected_dir.exists(), f"期望目录 {expected_dir} 存在"
        assert (expected_dir / "payload.txt").exists(), "payload 应在 ws 内的 slug 目录下"
        # 确认 slug 目录确实在 ws 内
        assert ws in expected_dir.resolve().parents or expected_dir.resolve().parent == ws
    else:
        # 防御拒绝:error 字段应明确
        assert res.error in ("BAD_SKILL_NAME",), f"意外 error: {res.error}"
