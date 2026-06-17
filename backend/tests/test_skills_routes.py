import io
import zipfile
import pytest

from app.routes import skills as sk


def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_validate_and_extract_good_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    data = _zip_bytes({"SKILL.md": "---\nname: s1\ndescription: d\n---\n步骤", "helper.py": "print(1)"})
    name = sk._extract_user_skill_zip(data)
    assert name == "s1"
    assert (tmp_path / "skills" / "user" / "s1" / "SKILL.md").is_file()


def test_reject_zip_without_skill_md(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(_zip_bytes({"readme.txt": "x"}))


def test_reject_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(_zip_bytes({"../evil.py": "x", "SKILL.md": "---\nname: e\ndescription: d\n---\n"}))


def test_delete_user_only(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    (tmp_path / "skills" / "platform" / "p1").mkdir(parents=True)
    (tmp_path / "skills" / "platform" / "p1" / "SKILL.md").write_text("---\nname: p1\ndescription: d\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        sk._delete_user_skill("p1")  # platform 只读
