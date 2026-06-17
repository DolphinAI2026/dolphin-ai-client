import pytest
from app.ai_chat import skills as sk
from app.mcp_tools import skill_authoring as sa


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    for source, name in (("user", "u1"), ("platform", "p1")):
        d = tmp_path / "skills" / source / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n正文", encoding="utf-8")
    return sk.SkillRegistry()


def test_author_user_skill_writes_skill_md_and_helpers(reg):
    res = sa.author_user_skill(
        "weekly-report",
        "Use when 用户要生成周报",
        "## 步骤\n1. 收集数据\n2. 渲染",
        helpers=[{"path": "helper.py", "content": "print('hi')"}],
        registry=reg,
    )
    assert res["name"] == "weekly-report"
    assert "SKILL.md" in res["files"] and "helper.py" in res["files"]
    md = reg.read_skill_file("weekly-report", "SKILL.md")
    assert "name: weekly-report" in md and "Use when 用户要生成周报" in md
    assert "## 步骤" in md and "1. 收集数据" in md
    assert reg.read_skill_file("weekly-report", "helper.py") == "print('hi')"
    assert reg.get("weekly-report").source == "user"


def test_author_user_skill_dup_raises(reg):
    with pytest.raises(ValueError):  # u1 已存在
        sa.author_user_skill("u1", "d", "x", registry=reg)


def test_author_user_skill_non_ascii_name_raises(reg):
    with pytest.raises(ValueError):
        sa.author_user_skill("中文技能", "d", "x", registry=reg)


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
