"""项目级记忆文件 —— 对标 Claude Code 的 CLAUDE.md。

低代码场景里同一应用反复迭代,字典绑定 / 表单提交契约 / 二开惯例这些项目约定值得跨会话沉淀。
存在工作区内 `.ruijing/PROJECT.md`(命名空间 dotdir,不与用户文件冲突),由 agent 经
update_project_memory 工具写,运行时经 project_memory_suffix 注入 coding 系统提示末尾
(纯函数 suffix,绕开 DB-first 陈旧,与 _coding_skill_manifest_suffix 同一注入模式)。
"""
from __future__ import annotations

from pathlib import Path

MEMORY_REL = ".ruijing/PROJECT.md"
MAX_MEMORY_CHARS = 8000


def _memory_path(ws_path: Path) -> Path:
    return Path(ws_path) / MEMORY_REL


def read_project_memory(ws_path: Path) -> str:
    """返回项目记忆正文(截断到 MAX_MEMORY_CHARS),文件不存在/不可读 → 空串。"""
    mem = _memory_path(ws_path)
    try:
        if not mem.is_file():
            return ""
        text = mem.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if len(text) > MAX_MEMORY_CHARS:
        text = text[:MAX_MEMORY_CHARS] + "\n…(项目记忆过长已截断)"
    return text


def project_memory_suffix(ws_path: Path) -> str:
    """把项目记忆包成系统提示后缀;无记忆 → 空串(no-op)。"""
    content = read_project_memory(ws_path)
    if not content:
        return ""
    return (
        f"\n\n## 本项目记忆({MEMORY_REL})\n"
        "以下是本工作区沉淀的项目约定与上下文,优先遵循;"
        f"如发现新的持久约定(字典绑定/接口契约/二开惯例),用 write_file 写 {MEMORY_REL} 更新它。\n"
        f"{content}\n"
    )


def write_project_memory(ws_path: Path, content: str) -> None:
    """覆盖式写入项目记忆(创建 .ruijing 目录)。截断到 MAX_MEMORY_CHARS。"""
    mem = _memory_path(ws_path)
    mem.parent.mkdir(parents=True, exist_ok=True)
    text = (content or "").strip()
    if len(text) > MAX_MEMORY_CHARS:
        text = text[:MAX_MEMORY_CHARS]
    mem.write_text(text, encoding="utf-8")
