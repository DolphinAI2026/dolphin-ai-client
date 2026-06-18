"""start_serve 命令解析：有 preview 脚本(可运行预览 harness)就用它，否则回退。

根因(2026-06-18): 旧逻辑硬跑 `vue-cli-service serve src/index.js`，而 src/index.js 是
UMD 组件库入口(只 export {install}，不 mount)→ 服务起来但页面空白。带 preview harness
的工程(preview/main.js 真正 mount 组件)应走其 `npm run preview`。
"""
from __future__ import annotations

import json

from app.coding.workspace import WorkspaceManager


def test_prefers_preview_script(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"preview": "VUE_APP_PREVIEW=true vue-cli-service serve preview/main.js", "serve": "x"}}),
        encoding="utf-8",
    )
    cmd = WorkspaceManager._resolve_serve_command(str(tmp_path), 8084)
    assert cmd == ["npm", "run", "preview", "--", "--port", "8084"]


def test_fallback_when_no_preview_script(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"serve": "node vibe-serve.js src/index.js"}}), encoding="utf-8",
    )
    cmd = WorkspaceManager._resolve_serve_command(str(tmp_path), 8084)
    assert cmd == ["npx", "vue-cli-service", "serve", "src/index.js", "--port", "8084"]


def test_fallback_when_no_package_json(tmp_path):
    cmd = WorkspaceManager._resolve_serve_command(str(tmp_path), 8084)
    assert cmd[0] == "npx" and "src/index.js" in cmd
