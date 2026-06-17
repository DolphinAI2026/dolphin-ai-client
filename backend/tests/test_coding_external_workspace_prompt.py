"""回归: 打开本地文件夹(external 工作区)的 coding agent prompt 必须能构建。

历史 bug: build_user_prompt 的 project_type if/elif 链漏了 'external'(打开本地文件夹
合成的类型), 落到 else 显式 raise → 真机上 agent 一跑就「发生错误」。
"""
from pathlib import Path

import pytest

from app.agents.coding import prompts


def _build(project_type: str) -> str:
    return prompts.build_user_prompt(
        requirement="讲讲这个项目的结构和入口文件",
        conversation_summary="",
        workspace_info={
            "project_type": project_type,
            "project_name": "form-page-factory-twin-dashboard-src",
            "files": ["src/api/index.js", "apaas.json"],
        },
        workspace_path=Path("/tmp/external-proj"),
    )


def test_external_project_type_does_not_raise():
    out = _build("external")
    assert out and "已有的本地项目" in out  # 走通用 external workflow, 不是脚手架模板


def test_known_project_types_still_build():
    for pt in ("form-page", "backend-api", "form-component-dual", "layout"):
        out = _build(pt)
        assert out and len(out) > 0


def test_unregistered_project_type_still_raises():
    # 防回归: 真正未登记的类型仍应显式 raise(不静默兜底), external 不在此列
    with pytest.raises(Exception):
        _build("totally-unknown-type-xyz")
