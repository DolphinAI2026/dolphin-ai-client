import os
import pytest
from app.ai_chat import skills as sk


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    # 一个 user skill + 一个 platform skill
    for source, name in (("user", "u1"), ("platform", "p1")):
        d = tmp_path / "skills" / source / name
        (d / "sub").mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n正文", encoding="utf-8")
        (d / "helper.py").write_text("print(1)", encoding="utf-8")
        (d / "sub" / "nested.txt").write_text("x", encoding="utf-8")
    return sk.SkillRegistry()


def test_list_files_tree(reg):
    paths = reg.list_skill_files("u1")  # 相对路径列表(含 SKILL.md + 嵌套)
    assert "SKILL.md" in paths and "helper.py" in paths and "sub/nested.txt" in paths


def test_read_file(reg):
    assert reg.read_skill_file("u1", "helper.py") == "print(1)"


def test_write_file_user_ok(reg):
    reg.write_skill_file("u1", "helper.py", "print(2)")
    assert reg.read_skill_file("u1", "helper.py") == "print(2)"


def test_write_file_creates_nested(reg):
    reg.write_skill_file("u1", "scripts/new.py", "x=1")
    assert reg.read_skill_file("u1", "scripts/new.py") == "x=1"


def test_write_platform_rejected(reg):
    with pytest.raises(PermissionError):
        reg.write_skill_file("p1", "helper.py", "evil")


def test_path_traversal_rejected(reg):
    with pytest.raises(ValueError):
        reg.read_skill_file("u1", "../../etc/passwd")
    with pytest.raises(ValueError):
        reg.write_skill_file("u1", "../escape.py", "x")


def test_delete_file_user(reg):
    reg.delete_skill_file("u1", "helper.py")
    assert "helper.py" not in reg.list_skill_files("u1")


def test_update_metadata(reg):
    reg.update_skill_metadata("u1", description="新描述", tags=["a", "b"])
    md = (reg.get("u1").dir / "SKILL.md").read_text(encoding="utf-8")
    assert "新描述" in md and "正文" in md  # frontmatter 改了, 正文保留
    assert reg.get("u1").description == "新描述"


def test_create_user_skill(reg):
    name = reg.create_user_skill("brand-new")
    assert name == "brand-new"
    assert reg.get("brand-new") is not None
    assert "SKILL.md" in reg.list_skill_files("brand-new")


def test_clone_platform_to_user(reg):
    new_name = reg.clone_skill("p1", "p1-copy")
    assert new_name == "p1-copy"
    s = reg.get("p1-copy")
    assert s is not None and s.source == "user"
    assert "helper.py" in reg.list_skill_files("p1-copy")
