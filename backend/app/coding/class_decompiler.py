"""反编译 .class 文件供预览(CFR 优先, javap 兜底)。

CFR jar vendor 在 backend/vendor/(随仓库提交);本机与部署镜像都自带 JDK
(deploy/docker/Dockerfile 打了 jdk8+jdk17),两个环境都能直接跑。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app import runtime

_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
DEFAULT_CFR_JAR = _BACKEND_ROOT / "vendor" / "cfr-0.152.jar"
_TIMEOUT_SECONDS = 20
# CFR 对损坏文件也 exit 0,只能靠成功输出必带的头部注释判断成败
_CFR_SUCCESS_MARKER = "Decompiled with CFR"


class DecompileError(Exception):
    """反编译失败,message 直接展示给用户。"""


@dataclass
class DecompileResult:
    text: str
    tool: str  # "cfr" | "javap"


def _find_java_executable(name: str) -> Optional[str]:
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / name
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_TIMEOUT_SECONDS,
        **runtime.subprocess_window_kwargs(),
    )


def decompile_class_file(class_path: Path) -> DecompileResult:
    java = _find_java_executable("java")
    cfr_jar = Path(os.environ.get("CFR_JAR_PATH") or DEFAULT_CFR_JAR)
    if java and cfr_jar.exists():
        try:
            proc = _run([java, "-jar", str(cfr_jar), str(class_path)])
            if proc.returncode == 0 and _CFR_SUCCESS_MARKER in proc.stdout:
                return DecompileResult(text=proc.stdout, tool="cfr")
        except subprocess.TimeoutExpired:
            pass  # 退 javap

    javap = _find_java_executable("javap")
    if javap:
        try:
            proc = _run([javap, "-p", "-c", "-constants", str(class_path)])
            if proc.returncode == 0 and proc.stdout.strip():
                return DecompileResult(text=proc.stdout, tool="javap")
        except subprocess.TimeoutExpired as e:
            raise DecompileError("反编译超时,文件可能过大") from e

    if not java and not javap:
        raise DecompileError("服务器缺少 JDK(找不到 java/javap),无法反编译 .class 文件")
    raise DecompileError("反编译失败:文件可能已损坏或不是有效的 .class 文件")
