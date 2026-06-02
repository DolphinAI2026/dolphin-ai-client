"""df-apaas-cli 私有源 + 失败大声报错 测试（mcp-server twin）。

根因：@x-apaas/df-apaas-cli 是 scoped 私有包，只发布在得帆 apaas-npm-group；
公共源（npmmirror/npmjs）必然 404，裸名 df-apaas-cli 在任何源都 404。
本测试钉住三条修复（镜像主后端 commit 2ca347a）：
  ① _ensure_df_apaas_cli 从私有源装 scoped 包
  ② _ensure_workspace_npmrc 把 @x-apaas scope 钉到私有源（公共依赖仍走默认源）
  ③ 装不上时大声 raise（而非静默 warn），并经 build_project 变成 build error
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.coding import workspace as ws_mod

PRIVATE = "https://registry.dfy.definesys.cn/repository/apaas-npm-group/"


def _bare_manager():
    # 跳过 __init__（不在仓库里建 workspaces 目录）；方法只用 self + 参数
    return ws_mod.WorkspaceManager.__new__(ws_mod.WorkspaceManager)


# ── ① 私有源解析 ────────────────────────────────────────────

def test_apaas_private_registry_defaults_to_group(monkeypatch):
    monkeypatch.delenv("APAAS_PRIVATE_NPM_REGISTRY", raising=False)
    assert ws_mod._resolve_apaas_private_npm_registry() == PRIVATE


def test_apaas_private_registry_env_override(monkeypatch):
    monkeypatch.setenv("APAAS_PRIVATE_NPM_REGISTRY", "https://nexus.internal/repository/npm/")
    assert ws_mod._resolve_apaas_private_npm_registry() == "https://nexus.internal/repository/npm/"


# ── ② .npmrc 把 @x-apaas scope 钉到私有源 ────────────────────

def test_ensure_workspace_npmrc_pins_x_apaas_scope_to_private(tmp_path):
    mgr = _bare_manager()
    mgr._ensure_workspace_npmrc(tmp_path)

    content = (tmp_path / ".npmrc").read_text(encoding="utf-8")
    # @x-apaas scope 走私有源
    assert f"@x-apaas:registry={ws_mod.APAAS_PRIVATE_NPM_REGISTRY}" in content
    # 默认源（公共依赖）仍在，保证 vue/sass 等走快源
    assert f"registry={ws_mod.DEFAULT_NPM_REGISTRY}" in content


def test_ensure_workspace_npmrc_upgrades_legacy_single_line(tmp_path):
    # 老 .npmrc 只有默认源一行 → 必须被升级补上 scoped 行
    (tmp_path / ".npmrc").write_text(f"registry={ws_mod.DEFAULT_NPM_REGISTRY}\n", encoding="utf-8")
    mgr = _bare_manager()
    mgr._ensure_workspace_npmrc(tmp_path)
    content = (tmp_path / ".npmrc").read_text(encoding="utf-8")
    assert f"@x-apaas:registry={ws_mod.APAAS_PRIVATE_NPM_REGISTRY}" in content


# ── ③ _ensure_df_apaas_cli：私有源 + 失败大声报错 ────────────

async def test_ensure_df_apaas_cli_skips_when_already_available(monkeypatch):
    mgr = _bare_manager()
    monkeypatch.setattr(mgr, "_build_npm_env", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(ws_mod, "resolve_executable",
                        lambda name, env=None: "/x/bin/df-apaas-cli")
    spawn = AsyncMock()
    monkeypatch.setattr(ws_mod.asyncio, "create_subprocess_exec", spawn)

    await mgr._ensure_df_apaas_cli()
    spawn.assert_not_called()  # 已可用 → 不该再装


async def test_ensure_df_apaas_cli_installs_from_private_and_raises_on_failure(monkeypatch):
    mgr = _bare_manager()
    monkeypatch.setattr(mgr, "_build_npm_env", lambda: {"PATH": "/usr/bin"})
    # df-apaas-cli 始终找不到（装前装后都 None），npm 在
    monkeypatch.setattr(ws_mod, "resolve_executable",
                        lambda name, env=None: "/usr/bin/npm" if name == "npm" else None)

    proc = MagicMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(
        b"npm error code E404\nnpm error 404 Not Found - GET "
        b"https://registry.npmmirror.com/@x-apaas%2fdf-apaas-cli - Not found", b"",
    ))
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(ws_mod.asyncio, "create_subprocess_exec", spawn)

    with pytest.raises(RuntimeError) as ei:
        await mgr._ensure_df_apaas_cli()

    # 装的是 scoped 包，且用私有源
    call_args = list(spawn.call_args.args)
    assert "@x-apaas/df-apaas-cli" in call_args
    assert ws_mod.APAAS_PRIVATE_NPM_REGISTRY in call_args
    # 报错文案点出 scoped / 私有源（给人话，不再静默 warn）
    msg = str(ei.value)
    assert "df-apaas-cli" in msg
    assert ws_mod.APAAS_PRIVATE_NPM_REGISTRY in msg


# ── ③' 失败经 build_project 变成 build error（status=error，不是裸异常） ──

async def test_build_project_surfaces_df_apaas_cli_failure_as_build_error(tmp_path, monkeypatch):
    mgr = _bare_manager()
    (tmp_path / ".workspace.json").write_text(
        json.dumps({"id": "w1", "project_type": "form-page", "project_name": "announce"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mgr, "get_workspace_path", lambda ws_id: tmp_path)
    monkeypatch.setattr(mgr, "_run_workspace_compat_handlers", lambda p: None)
    monkeypatch.setattr(mgr, "install_deps", AsyncMock(return_value={"status": "ok"}))
    monkeypatch.setattr(mgr, "_uses_df_apaas_cli_build", lambda p: True)
    monkeypatch.setattr(mgr, "_ensure_df_apaas_cli",
                        AsyncMock(side_effect=RuntimeError("无法安装 df-apaas-cli 脚手架（@x-apaas/df-apaas-cli）")))

    result = await mgr.build_project("w1")

    assert result["status"] == "error"
    assert "df-apaas-cli" in result["message"]
