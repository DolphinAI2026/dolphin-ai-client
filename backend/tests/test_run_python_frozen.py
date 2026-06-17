import sys
from pathlib import Path

import pytest

from app.ai_chat import tools as t
import desktop_sidecar as ds


def test_build_argv_non_frozen_uses_dash_c(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    argv = t._build_python_argv("print(1)", "/tmp/x.py", exe="/usr/bin/python3")
    assert argv == ["/usr/bin/python3", "-c", "print(1)"]


def test_build_argv_frozen_uses_run_script(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    argv = t._build_python_argv("print(1)", "/tmp/x.py", exe="/opt/ruijing-sidecar")
    assert argv == ["/opt/ruijing-sidecar", "--run-script", "/tmp/x.py"]


def test_sidecar_run_script_executes_file(tmp_path):
    out = tmp_path / "out.txt"
    script = tmp_path / "s.py"
    script.write_text(f"open(r'{out}', 'w').write('hello-skill')\n", encoding="utf-8")
    rc = ds.run_script(str(script))
    assert rc == 0
    assert out.read_text() == "hello-skill"


def test_sidecar_run_script_nonzero_on_error(tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("raise SystemExit(3)\n", encoding="utf-8")
    assert ds.run_script(str(script)) == 3
