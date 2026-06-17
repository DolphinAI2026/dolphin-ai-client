import os
import textwrap
from pathlib import Path

import pytest

from app.ai_chat import skills as skmod


def _write_skill(root: Path, source: str, name: str, frontmatter: str, body: str = "做事步骤", files: dict | None = None):
    d = root / source / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    for fn, content in (files or {}).items():
        (d / fn).write_text(content, encoding="utf-8")
    return d


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(root))
    return root


def test_scan_returns_valid_skills(skills_dir):
    _write_skill(skills_dir, "platform", "pptx-brand", "name: pptx-brand\ndescription: 出品牌PPT", files={"helper.py": "print(1)"})
    found = skmod.SkillRegistry().scan()
    assert [s.name for s in found] == ["pptx-brand"]
    s = found[0]
    assert s.description == "出品牌PPT"
    assert s.source == "platform"
    assert "helper.py" in s.files


def test_scan_skips_bad_package_missing_frontmatter(skills_dir):
    _write_skill(skills_dir, "user", "good", "name: good\ndescription: ok")
    bad = skills_dir / "user" / "bad"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("没有 frontmatter 的正文", encoding="utf-8")
    names = [s.name for s in skmod.SkillRegistry().scan()]
    assert names == ["good"]


def test_user_overrides_platform_same_name(skills_dir):
    _write_skill(skills_dir, "platform", "dup", "name: dup\ndescription: 平台版")
    _write_skill(skills_dir, "user", "dup", "name: dup\ndescription: 用户版")
    found = {s.name: s for s in skmod.SkillRegistry().scan()}
    assert found["dup"].source == "user"
    assert found["dup"].description == "用户版"


def test_missing_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "nope"))
    assert skmod.SkillRegistry().scan() == []


def test_get_and_read_skill_md(skills_dir):
    _write_skill(skills_dir, "user", "s1", "name: s1\ndescription: d", body="第一行\n第二行")
    reg = skmod.SkillRegistry()
    assert reg.get("s1").name == "s1"
    assert reg.get("nope") is None
    md = reg.read_skill_md("s1")
    assert "第一行" in md and "---" not in md  # frontmatter 已剥离


def test_manifest_lists_name_and_desc(skills_dir):
    _write_skill(skills_dir, "platform", "a", "name: a\ndescription: 甲")
    manifest = skmod.build_skill_manifest(skmod.SkillRegistry().scan())
    assert "use_skill" in manifest and "a: 甲" in manifest
    assert skmod.build_skill_manifest([]) == ""
