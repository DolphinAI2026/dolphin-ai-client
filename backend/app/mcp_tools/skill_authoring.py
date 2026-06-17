"""AI 生成 Skill —— skill 创作（落盘原语复用 SkillRegistry）。

core create_skill 让 agent 把可复用做法沉淀成一个 user skill（SKILL.md + 可选 helper）。
（MCP 工具 register 在 Task 3 加，本文件本阶段先放纯函数 author_user_skill。）
"""
from __future__ import annotations

from app.ai_chat.skills import (
    SkillRegistry,
    validate_skill_frontmatter,
    validate_skill_name,
)


def author_user_skill(
    name: str,
    description: str,
    instructions: str,
    helpers: list[dict] | None = None,
    *,
    registry: SkillRegistry | None = None,
) -> dict:
    """建一个 user skill：建骨架 → 覆盖 SKILL.md（frontmatter+正文）→ 写 helper。

    纯同步、可单测。校验失败 / 重名 / 写失败抛 ValueError（由 create_skill 包装映射 error_code）。
    """
    reg = registry or SkillRegistry()
    validate_skill_name(name, require_ascii=True)
    validate_skill_frontmatter({"name": name, "description": description})
    reg.create_user_skill(name)  # 重名 / 环境不支持 → ValueError
    content = f"---\nname: {name}\ndescription: {description}\n---\n{instructions}\n"
    reg.write_skill_file(name, "SKILL.md", content)
    for h in (helpers or []):
        if not isinstance(h, dict):
            continue  # agent 可能误传字符串等，跳过非法项（防 AttributeError）
        path = str(h.get("path") or "").strip()
        if not path:
            continue
        reg.write_skill_file(name, path, str(h.get("content") or ""))  # 越界 path 由 _resolve_file 拦 ValueError
    s = reg.get(name)
    return {"name": name, "files": reg.list_skill_files(name), "dir": str(s.dir) if s else ""}
