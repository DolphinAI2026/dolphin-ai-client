import pytest
from app.ai_chat import skills as sk


def test_validate_skill_name_ok():
    sk.validate_skill_name("my-skill")  # 不抛
    sk.validate_skill_name("good-name_1", require_ascii=True)


def test_validate_skill_name_rejects_path_sep_and_dots():
    for bad in ("a/b", "a\\b", ".", ".."):
        with pytest.raises(ValueError):
            sk.validate_skill_name(bad)


def test_validate_skill_name_rejects_empty():
    with pytest.raises(ValueError):
        sk.validate_skill_name("")
    with pytest.raises(ValueError):
        sk.validate_skill_name("   ")


def test_validate_skill_name_ascii_gate():
    sk.validate_skill_name("中文名")  # 默认不强制 ASCII，不抛
    with pytest.raises(ValueError):
        sk.validate_skill_name("中文名", require_ascii=True)


def test_validate_skill_frontmatter_ok():
    name, desc = sk.validate_skill_frontmatter({"name": "x", "description": "y"})
    assert name == "x" and desc == "y"


def test_validate_skill_frontmatter_missing():
    with pytest.raises(ValueError):
        sk.validate_skill_frontmatter({"name": "x"})
    with pytest.raises(ValueError):
        sk.validate_skill_frontmatter({"description": "y"})
