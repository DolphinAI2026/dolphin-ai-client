import os
import sys
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


def _clear_desktop_env(monkeypatch):
    """清掉所有影响 skills_root() 桌面分支解析的 env，逐项隔离。"""
    monkeypatch.delenv("RUIJING_SKILLS_DIR", raising=False)
    monkeypatch.delenv("SIDECAR_DATA_DIR", raising=False)
    monkeypatch.delenv("APAAS_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DESKTOP_MODE", raising=False)
    monkeypatch.delenv("RUIJING_SERVER_DATA_DIR", raising=False)
    monkeypatch.delenv("RUIJING_SKILLS_DISABLED", raising=False)
    # 桌面判定的 frozen 信号现由 app.runtime 读真实 sys.frozen；确保非冻结态。
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_desktop_skills_root_matches_sidecar_data_dir(tmp_path, monkeypatch):
    """生产路径契约：桌面模式下 skills_root() 必须落在 sidecar 真正使用的 data_dir 下。

    用 desktop_sidecar.build_env 注入 env（与 Tauri 传 --data-dir 后的实际状态一致），
    再断言 skills_root() == <data_dir>/skills。盯住 high 级路径解析 bug 回归。
    """
    from desktop_sidecar import build_env

    _clear_desktop_env(monkeypatch)
    # 模拟 macOS 上 Tauri app_data_dir(bundle id 目录)，绝非 ~/.ruijing-builder。
    data_dir = tmp_path / "Library" / "Application Support" / "com.ruijing.builder"
    # build_env 会写真实环境变量；monkeypatch 不拦 os.environ[...]=...，用 setenv 兜底清理。
    written = build_env(data_dir=data_dir, port=8799)
    for k, v in written.items():
        monkeypatch.setenv(k, v)

    assert skmod.skills_root() == data_dir / "skills"


def test_desktop_skills_root_from_workspace_root_only(tmp_path, monkeypatch):
    """SIDECAR_DATA_DIR 缺失时仍能从 APAAS_WORKSPACE_ROOT 反推（更稳的真相源）。"""
    _clear_desktop_env(monkeypatch)
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APAAS_WORKSPACE_ROOT", str(data_dir / "workspaces"))

    assert skmod.skills_root() == data_dir / "skills"


def test_desktop_skills_root_does_not_use_home_fallback_when_workspace_known(tmp_path, monkeypatch):
    """回归：桌面模式有真实 data_dir 信号时，绝不退回 ~/.ruijing-builder。"""
    _clear_desktop_env(monkeypatch)
    data_dir = tmp_path / "real"
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("SIDECAR_DATA_DIR", str(data_dir))

    root = skmod.skills_root()
    assert root == data_dir / "skills"
    assert ".ruijing-builder" not in str(root)


def test_web_skills_root_defaults_to_backend_data(monkeypatch):
    """非桌面、无显式 skills env → Web 服务端 data/skills。"""
    _clear_desktop_env(monkeypatch)
    assert skmod.skills_root() == Path(skmod.__file__).resolve().parents[2] / "data" / "skills"


def test_web_skills_root_from_server_data_dir(tmp_path, monkeypatch):
    """Web 端服务数据根目录可显式覆盖，skills 落到其下的 skills/。"""
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("RUIJING_SERVER_DATA_DIR", str(tmp_path / "server-data"))
    assert skmod.skills_root() == tmp_path / "server-data" / "skills"


def test_skills_root_can_be_disabled(monkeypatch):
    """显式关闭时返回 None，供共享部署禁用服务端 skill 上传/执行。"""
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("RUIJING_SKILLS_DISABLED", "1")
    assert skmod.skills_root() is None
