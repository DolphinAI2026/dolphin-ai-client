import pytest
from app.routes import skills as r


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    d = tmp_path / "skills" / "user" / "u1"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: u1\ndescription: d\n---\n正文", encoding="utf-8")
    (d / "helper.py").write_text("print(1)", encoding="utf-8")
    return tmp_path


def test_list_and_read(setup):
    files = r._skill_files("u1")
    assert "helper.py" in files
    assert r._skill_read("u1", "helper.py")["content"] == "print(1)"


def test_write_and_metadata(setup):
    r._skill_write("u1", "helper.py", "print(2)")
    assert r._skill_read("u1", "helper.py")["content"] == "print(2)"
    r._skill_update_metadata("u1", {"description": "新", "tags": ["x"]})
    from app.ai_chat.skills import SkillRegistry
    assert SkillRegistry().get("u1").description == "新"


def test_new_and_clone_and_delete(setup):
    assert r._skill_create("blank") == "blank"
    assert r._skill_clone("u1", "u1-copy") == "u1-copy"
    r._skill_delete_file("u1", "helper.py")
    assert "helper.py" not in r._skill_files("u1")
