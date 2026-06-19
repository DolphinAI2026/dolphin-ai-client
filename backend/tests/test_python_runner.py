import sys
from pathlib import Path

from app.agents import python_runner


def test_build_python_argv_non_frozen(monkeypatch):
    monkeypatch.setattr(python_runner.runtime, "is_frozen", lambda: False)
    argv = python_runner.build_python_argv("print(1)", "/tmp/x.py", exe="/usr/bin/python3")
    assert argv == ["/usr/bin/python3", "-c", "print(1)"]


def test_build_python_argv_frozen(monkeypatch):
    monkeypatch.setattr(python_runner.runtime, "is_frozen", lambda: True)
    argv = python_runner.build_python_argv("print(1)", "/tmp/x.py", exe="/opt/ruijing-sidecar")
    assert argv == ["/opt/ruijing-sidecar", "--run-script", "/tmp/x.py"]


async def test_run_python_in_dir_captures_stdout(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ok, out = await python_runner.run_python_in_dir("print('hello-runner')", ws)
    assert ok
    assert "hello-runner" in out


async def test_run_python_in_dir_runs_in_workspace_cwd(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "marker.txt").write_text("x", encoding="utf-8")
    ok, out = await python_runner.run_python_in_dir(
        "import os; print('marker.txt' in os.listdir('.'))", ws
    )
    assert ok
    assert "True" in out


async def test_run_python_in_dir_reports_failure(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ok, out = await python_runner.run_python_in_dir("raise SystemExit(3)", ws)
    assert not ok
    assert "exit code: 3" in out
