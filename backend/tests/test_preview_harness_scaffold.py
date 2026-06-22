"""CLI 模板脚手架必须带可运行的 preview harness(真 mount 组件),否则 serve 起来白屏。

根因(2026-06-22): form-page 等前端产物走 `_scaffold_via_cli_template`(拷 backend/templates/
cli-generated/* 静态模板),这些模板只有 serve→UMD 库入口 src/index.js(只 export {install} 不
mount)、没有 preview 脚本 → `#app` 空 → 白屏。已验证可用的 harness 只存在于几乎用不到的
`_scaffold_form_page`(MOBILE_PAGE 兜底)。本测试钉死:CLI 模板路径也产出真挂载的 preview harness。
"""
from __future__ import annotations

import json
import shutil

import pytest

from app.coding.workspace import ProjectType, WorkspaceManager


def _strip_harness(ws):
    """模拟白屏修复前建的老工作区:去掉 preview harness。"""
    shutil.rmtree(ws / "preview")
    pkg = json.loads((ws / "package.json").read_text("utf-8"))
    pkg["scripts"].pop("preview", None)
    (ws / "package.json").write_text(json.dumps(pkg), encoding="utf-8")


def test_ensure_preview_harness_backfills_old_workspace(tmp_path):
    ws = tmp_path / "ws"
    mgr = WorkspaceManager()
    mgr._scaffold_via_cli_template(ws, "foo", ProjectType.FORM_PAGE)
    _strip_harness(ws)
    (ws / ".workspace.json").write_text(json.dumps({"project_type": "form-page"}), encoding="utf-8")

    assert mgr._ensure_preview_harness(ws) is True
    assert (ws / "preview" / "main.js").exists()
    assert "preview" in json.loads((ws / "package.json").read_text("utf-8"))["scripts"]
    # 幂等:已有 harness → 不再注入
    assert mgr._ensure_preview_harness(ws) is False


def test_ensure_preview_harness_picks_index_entry_not_alpha_first(tmp_path):
    # 多组件工作区:必须按 src/index.js 实际 import 的入口,不能取字母序第一个
    ws = tmp_path / "ws"
    mgr = WorkspaceManager()
    mgr._scaffold_via_cli_template(ws, "foo", ProjectType.FORM_PAGE)
    (ws / "src" / "form-page" / "apaas-custom-zzz.vue").write_text("<template><div/></template>", encoding="utf-8")
    (ws / "src" / "index.js").write_text(
        'import X from "./form-page/apaas-custom-zzz.vue";\n', encoding="utf-8")
    _strip_harness(ws)
    (ws / ".workspace.json").write_text(json.dumps({"project_type": "form-page"}), encoding="utf-8")

    mgr._ensure_preview_harness(ws)
    main = (ws / "preview" / "main.js").read_text("utf-8")
    assert "apaas-custom-zzz.vue" in main  # index.js 入口,而非 glob 字母序的 apaas-custom-foo

# 页面类三模板形态一致:单一 src/{dir}/apaas-custom-*.vue + apaas.json outputName
PAGE_LIKE = [
    (ProjectType.FORM_PAGE, "form-page"),
    (ProjectType.FORM_LIST, "form-view"),
    (ProjectType.LAYOUT, "form-layout"),
]


@pytest.mark.parametrize("ptype,comp_dir", PAGE_LIKE)
def test_page_like_scaffold_has_mounting_preview_harness(tmp_path, ptype, comp_dir):
    ws = tmp_path / "ws"
    WorkspaceManager()._scaffold_via_cli_template(ws, "rating-star", ptype)

    pkg = json.loads((ws / "package.json").read_text("utf-8"))
    assert "preview" in pkg["scripts"], "package.json 必须暴露 preview 脚本"
    # UMD build/serve 路径不能被破坏(发布仍走 src/index.js UMD)
    assert "build" in pkg["scripts"]
    assert "src/index.js" in pkg["scripts"]["serve"]

    main = (ws / "preview" / "main.js").read_text("utf-8")
    assert "new Vue(" in main, "preview/main.js 必须真正实例化 Vue"
    assert ("$mount('#app')" in main) or ("el: '#app'" in main), "必须挂载到 #app"
    # 必须 import 真实业务组件,生成的 .vue 才会被渲染
    assert f"src/{comp_dir}/apaas-custom-rating-star.vue" in main
    # 必须安装平台全局组件桩,否则用了 x-ag-grid 等平台组件的页面仍白屏
    assert "installApaasShim" in main, "main.js 必须安装平台组件桩"

    shim = (ws / "preview" / "apaas-shim.js").read_text("utf-8")
    assert "x-ag-grid" in shim, "apaas-shim 必须桩掉平台表格组件 x-ag-grid"

    html = (ws / "preview" / "index.html").read_text("utf-8")
    assert 'id="app"' in html

    vcfg = (ws / "vue.config.js").read_text("utf-8")
    assert "VUE_APP_PREVIEW" in vcfg, "vue.config.js 必须有 isPreview 分支"

    cmd = WorkspaceManager._resolve_serve_command(str(ws), 8090)
    assert cmd == ["npm", "run", "preview", "--", "--port", "8090"]
