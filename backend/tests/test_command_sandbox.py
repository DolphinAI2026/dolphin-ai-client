"""run_command 桌面态 OS 级沙箱(macOS sandbox-exec)——把文件写入限制在工作区,
挡住 AI 生成命令写出工作区 / rm 掉别的项目。读与网络放行。只在桌面态(客户机)生效。"""
import platform
import subprocess
from pathlib import Path

import pytest

from app.coding.command_sandbox import (
    build_profile,
    wrap_command,
    should_sandbox,
    sandbox_exec_available,
)

_MAC = platform.system() == "Darwin"


def test_profile_denies_writes_then_reallows_workspace(tmp_path: Path):
    prof = build_profile(tmp_path)
    assert "(deny file-write*)" in prof
    assert str(tmp_path.resolve()) in prof
    assert '(regex #"^/dev/")' in prof  # /dev/null 重定向放行


def test_wrap_command_shape(tmp_path: Path):
    argv = wrap_command("echo hi", tmp_path)
    assert argv[0].endswith("sandbox-exec")
    assert argv[-3:] == ["/bin/bash", "-c", "echo hi"]
    assert "-p" in argv  # profile 经 -p 内联


def test_should_sandbox_off_when_not_desktop(monkeypatch):
    import app.runtime as rt
    monkeypatch.setattr(rt, "is_desktop", lambda: False)
    monkeypatch.setattr(
        "app.coding.command_sandbox.sandbox_exec_available", lambda: True
    )
    assert should_sandbox() is False


def test_should_sandbox_off_when_unavailable(monkeypatch):
    import app.runtime as rt
    monkeypatch.setattr(rt, "is_desktop", lambda: True)
    monkeypatch.setattr(
        "app.coding.command_sandbox.sandbox_exec_available", lambda: False
    )
    assert should_sandbox() is False


def test_should_sandbox_on_when_desktop_and_available(monkeypatch):
    import app.runtime as rt
    monkeypatch.setattr(rt, "is_desktop", lambda: True)
    monkeypatch.setattr(
        "app.coding.command_sandbox.sandbox_exec_available", lambda: True
    )
    assert should_sandbox() is True


@pytest.mark.skipif(not _MAC, reason="sandbox-exec 仅 macOS")
def test_real_sandbox_allows_inside_blocks_outside(tmp_path: Path):
    if not sandbox_exec_available():
        pytest.skip("sandbox-exec 不可用")
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = Path.home() / f"sb_pytest_out_{ws.name}.txt"
    if outside.exists():
        outside.unlink()

    # 写工作区内 → 成功
    r_in = subprocess.run(
        wrap_command(f"echo hi > {ws}/inside.txt", ws), capture_output=True
    )
    assert r_in.returncode == 0
    assert (ws / "inside.txt").read_text().strip() == "hi"

    # 写家目录(工作区外)→ 被拒, 文件不存在
    r_out = subprocess.run(
        wrap_command(f"echo hi > {outside}", ws), capture_output=True
    )
    assert r_out.returncode != 0
    assert not outside.exists()

    # 读系统文件 + /dev/null 重定向 → 放行
    r_read = subprocess.run(
        wrap_command("head -1 /etc/hosts >/dev/null && echo ok", ws),
        capture_output=True,
        text=True,
    )
    assert r_read.returncode == 0 and "ok" in r_read.stdout


@pytest.mark.skipif(not _MAC, reason="sandbox-exec 仅 macOS")
async def test_run_command_confines_writes_when_sandboxed(tmp_path: Path, monkeypatch):
    """_run_command 接线:沙箱开启时,写出工作区被挡,工作区内写正常。"""
    from app.coding import tools

    monkeypatch.setattr(tools, "should_sandbox", lambda: True)
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = Path.home() / f"sb_runcmd_out_{ws.name}.txt"
    if outside.exists():
        outside.unlink()

    await tools._run_command({"command": f"echo hi > {outside}"}, ws)
    assert not outside.exists()  # 写出工作区被沙箱挡住

    await tools._run_command({"command": "echo ok > inside.txt"}, ws)
    assert (ws / "inside.txt").read_text().strip() == "ok"
