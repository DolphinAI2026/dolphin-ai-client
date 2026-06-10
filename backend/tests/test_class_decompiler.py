"""class_decompiler 单测 — CFR 优先 + javap 兜底。需要本机 JDK(javac/java),没有则跳过。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.coding.class_decompiler import DecompileError, decompile_class_file

pytestmark = pytest.mark.skipif(
    shutil.which("javac") is None or shutil.which("java") is None,
    reason="需要本机 JDK (javac/java)",
)

JAVA_SRC = """
public class Sample {
    private final String name = "world";

    public String greet(int times) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < times; i++) sb.append("hi ").append(name);
        return sb.toString();
    }
}
"""


@pytest.fixture(scope="module")
def sample_class(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work_dir = tmp_path_factory.mktemp("javac")
    src = work_dir / "Sample.java"
    src.write_text(JAVA_SRC, encoding="utf-8")
    subprocess.run(["javac", str(src)], check=True, cwd=work_dir)
    return work_dir / "Sample.class"


def test_cfr_decompile_returns_readable_java(sample_class: Path):
    result = decompile_class_file(sample_class)
    assert result.tool == "cfr"
    assert "class Sample" in result.text
    assert "greet" in result.text


def test_javap_fallback_when_cfr_jar_missing(sample_class: Path, monkeypatch):
    monkeypatch.setenv("CFR_JAR_PATH", "/nonexistent/cfr.jar")
    result = decompile_class_file(sample_class)
    assert result.tool == "javap"
    assert "Sample" in result.text
    assert "greet" in result.text


def test_corrupt_class_raises_friendly_error(tmp_path: Path):
    bad = tmp_path / "Garbage.class"
    bad.write_bytes(b"not a class file")
    with pytest.raises(DecompileError):
        decompile_class_file(bad)
