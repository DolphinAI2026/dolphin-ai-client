"""代码工作区改动跟踪（git 基线机制）—— git_changes 模块单测。

工作区不是 git 仓库，git_changes 懒初始化一个透明基线仓库：
基线提交后的差异 = 「本轮改动」，喂文件树徽标 / 改动分组 / diff 查看器。
"""
import subprocess

import pytest

from app.coding.git_changes import (
    checkpoint,
    collect_changes,
    ensure_baseline,
    file_diff,
    git_available,
)

pytestmark = pytest.mark.skipif(not git_available(), reason="环境无 git")


@pytest.fixture()
def ws(tmp_path):
    """模拟一个已有脚手架文件的工作区（非 git 仓库）。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("junk\n", encoding="utf-8")
    return tmp_path


def test_ensure_baseline_inits_repo_and_excludes_node_modules(ws):
    assert ensure_baseline(ws)
    assert (ws / ".git").exists()
    # 基线就绪后无任何改动；node_modules 被 exclude 掉
    out = collect_changes(ws)
    assert out["enabled"] is True
    assert out["files"] == []
    # 幂等：重复调用不报错不重复写 exclude
    assert ensure_baseline(ws)
    exclude = (ws / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.count("ai-builder workspace changes") == 1


def test_collect_changes_reports_add_modify_delete_with_counts(ws):
    ensure_baseline(ws)
    (ws / "src" / "app.js").write_text("line1\nCHANGED\nline3\nline4\n", encoding="utf-8")  # M: +2 -1
    (ws / "src" / "new.js").write_text("a\nb\n", encoding="utf-8")  # A: +2
    (ws / "README.md").unlink()  # D

    out = collect_changes(ws)
    assert out["enabled"] is True
    by_path = {f["path"]: f for f in out["files"]}
    assert by_path["src/app.js"]["status"] == "M"
    assert by_path["src/app.js"]["additions"] == 2
    assert by_path["src/app.js"]["deletions"] == 1
    assert by_path["src/new.js"]["status"] == "A"
    assert by_path["src/new.js"]["additions"] == 2
    assert by_path["README.md"]["status"] == "D"
    assert by_path["README.md"]["deletions"] == 1
    assert out["total"] == {"files": 3, "additions": 4, "deletions": 2}


def test_untracked_binary_file_flagged_not_counted(ws):
    ensure_baseline(ws)
    (ws / "logo.png").write_bytes(b"\x89PNG\x00\x00\x01binary")
    out = collect_changes(ws)
    f = next(x for x in out["files"] if x["path"] == "logo.png")
    assert f["status"] == "A"
    assert f["binary"] is True
    assert f["additions"] == 0


def test_checkpoint_folds_changes_into_baseline(ws):
    ensure_baseline(ws)
    (ws / "src" / "new.js").write_text("a\n", encoding="utf-8")
    assert checkpoint(ws) is True
    assert collect_changes(ws)["files"] == []
    # 没有改动时 checkpoint 不空提交
    assert checkpoint(ws) is False


def test_file_diff_modified_added_deleted(ws):
    ensure_baseline(ws)
    (ws / "src" / "app.js").write_text("line1\nCHANGED\nline3\n", encoding="utf-8")
    d = file_diff(ws, "src/app.js")
    assert d["enabled"] and d["status"] == "M"
    assert "-line2" in d["diff"] and "+CHANGED" in d["diff"]

    (ws / "src" / "new.js").write_text("hello\n", encoding="utf-8")
    d = file_diff(ws, "src/new.js")
    assert d["status"] == "A"
    assert "+hello" in d["diff"]

    (ws / "README.md").unlink()
    d = file_diff(ws, "README.md")
    assert d["status"] == "D"
    assert "-# demo" in d["diff"]

    # 没改过的文件：status None, diff 为空
    d = file_diff(ws, "unchanged-probe.js")
    assert d["status"] is None and d["diff"] == ""


def test_legacy_workspace_with_bare_init_gets_baseline(ws):
    """已 git init 但没有任何提交的仓库（半残状态）也能补上基线。"""
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
    assert ensure_baseline(ws)
    assert collect_changes(ws)["files"] == []


def test_non_ascii_filename_roundtrip(ws):
    ensure_baseline(ws)
    (ws / "说明文档.md").write_text("中文\n", encoding="utf-8")
    out = collect_changes(ws)
    paths = [f["path"] for f in out["files"]]
    assert "说明文档.md" in paths
    d = file_diff(ws, "说明文档.md")
    assert d["status"] == "A" and "+中文" in d["diff"]
