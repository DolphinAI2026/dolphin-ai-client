"""项目级记忆文件(.ruijing/PROJECT.md)—— 对标 CLAUDE.md,沉淀本工作区的配置约定/二开惯例,
注入 coding 系统提示末尾。低代码场景同一应用反复迭代,项目记忆尤其值。"""
from pathlib import Path

import pytest

from app.coding.project_memory import (
    MEMORY_REL,
    MAX_MEMORY_CHARS,
    read_project_memory,
    project_memory_suffix,
    write_project_memory,
)


def test_read_returns_empty_when_absent(tmp_path: Path):
    assert read_project_memory(tmp_path) == ""


def test_read_returns_content_when_present(tmp_path: Path):
    mem = tmp_path / MEMORY_REL
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text("字典 order_status 已绑定;表单提交走 afterFormData。", encoding="utf-8")
    assert "order_status" in read_project_memory(tmp_path)


def test_read_caps_oversized(tmp_path: Path):
    mem = tmp_path / MEMORY_REL
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text("x" * (MAX_MEMORY_CHARS + 5000), encoding="utf-8")
    out = read_project_memory(tmp_path)
    assert len(out) <= MAX_MEMORY_CHARS + 100  # 容截断尾注
    assert "截断" in out


def test_suffix_empty_when_no_memory(tmp_path: Path):
    assert project_memory_suffix(tmp_path) == ""


def test_suffix_wraps_content_with_header(tmp_path: Path):
    write_project_memory(tmp_path, "本应用销售阶段字典固定为 5 级。")
    suffix = project_memory_suffix(tmp_path)
    assert "项目记忆" in suffix
    assert "销售阶段字典" in suffix
    assert MEMORY_REL in suffix  # 提示 agent 文件位置,可更新


def test_write_creates_dir_and_roundtrips(tmp_path: Path):
    assert not (tmp_path / ".ruijing").exists()
    write_project_memory(tmp_path, "约定 A")
    assert (tmp_path / MEMORY_REL).is_file()
    assert "约定 A" in read_project_memory(tmp_path)


def test_write_overwrites(tmp_path: Path):
    write_project_memory(tmp_path, "旧内容")
    write_project_memory(tmp_path, "新内容")
    out = read_project_memory(tmp_path)
    assert "新内容" in out and "旧内容" not in out


def test_pipeline_suffix_helper_passthrough(tmp_path: Path):
    from app.coding.pipeline import _coding_project_memory_suffix

    assert _coding_project_memory_suffix(tmp_path) == ""
    write_project_memory(tmp_path, "本应用字段权限走 advancedPermissionGroups。")
    assert "advancedPermissionGroups" in _coding_project_memory_suffix(tmp_path)


def test_pipeline_suffix_helper_is_noop_on_error(tmp_path: Path, monkeypatch):
    """项目记忆读出错绝不中断 codegen —— 包成空串。"""
    import app.coding.project_memory as pm

    def _boom(_ws):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(pm, "project_memory_suffix", _boom)
    from app.coding.pipeline import _coding_project_memory_suffix

    assert _coding_project_memory_suffix(tmp_path) == ""
