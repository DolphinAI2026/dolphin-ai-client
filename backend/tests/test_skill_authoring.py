import pytest
from mcp.server.fastmcp import FastMCP

from app.ai_chat import skills as sk
from app.mcp_envelope import ErrorCode
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


# ─────────────── MCP 包装层（register 注册的 5 个工具）───────────────

def _mk_tools(tmp_path, monkeypatch, *, with_root=True):
    if with_root:
        monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
        d = tmp_path / "skills" / "platform" / "p1"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: p1\ndescription: d\n---\n正文", encoding="utf-8")
        (d / "helper.py").write_text("print(1)", encoding="utf-8")
    else:
        monkeypatch.delenv("RUIJING_SKILLS_DIR", raising=False)
        monkeypatch.delenv("DESKTOP_MODE", raising=False)
        monkeypatch.delenv("APAAS_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("SIDECAR_DATA_DIR", raising=False)
        monkeypatch.delenv("RUIJING_SERVER_DATA_DIR", raising=False)
        monkeypatch.setenv("RUIJING_SKILLS_DISABLED", "1")
    sa._registered_mcp_ids.clear()
    m = FastMCP("test")
    return sa.register(m), m


@pytest.mark.asyncio
async def test_create_skill_ok(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["create_skill"](
        name="weekly-report", description="Use when 生成周报",
        instructions="## 步骤\n1. x", helpers=[{"path": "helper.py", "content": "print(1)"}],
    )
    assert res["ok"] is True and res["name"] == "weekly-report"
    assert "SKILL.md" in res["files"] and "helper.py" in res["files"]


@pytest.mark.asyncio
async def test_create_skill_dup_returns_skill_exists(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    await tools["create_skill"](name="dupe", description="d", instructions="x")
    res = await tools["create_skill"](name="dupe", description="d", instructions="x")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILL_EXISTS


@pytest.mark.asyncio
async def test_create_skill_non_ascii_returns_name_invalid(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["create_skill"](name="中文技能", description="d", instructions="x")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILL_NAME_INVALID


@pytest.mark.asyncio
async def test_create_skill_unsupported_when_disabled(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch, with_root=False)
    res = await tools["create_skill"](name="x", description="d", instructions="y")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILLS_UNSUPPORTED


@pytest.mark.asyncio
async def test_write_platform_skill_returns_readonly(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["write_skill_file"](name="p1", path="helper.py", content="evil")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILL_READONLY


@pytest.mark.asyncio
async def test_read_missing_skill_returns_not_found(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["read_skill_file"](name="nope", path="SKILL.md")
    assert res["ok"] is False and res["error_code"] == ErrorCode.NOT_FOUND


def test_create_skill_description_non_empty(tmp_path, monkeypatch):
    """防 docstring 拼接坑：FastMCP 工具 description 必须非空且含触发词。"""
    _, m = _mk_tools(tmp_path, monkeypatch)
    tool = next(t for t in m._tool_manager.list_tools() if t.name == "create_skill")
    assert tool.description and "Use when" in tool.description
