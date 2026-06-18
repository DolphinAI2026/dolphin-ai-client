"""AI 生成 Skill —— skill 创作（落盘原语复用 SkillRegistry）。

core create_skill 让 agent 把可复用做法沉淀成一个 user skill（SKILL.md + 可选 helper）。
（MCP 工具 register 在 Task 3 加，本文件本阶段先放纯函数 author_user_skill。）
"""
from __future__ import annotations

from app.ai_chat.skills import (
    SkillRegistry,
    skills_root,
    validate_skill_frontmatter,
    validate_skill_name,
)
from app.mcp_envelope import ErrorCode, _err, _ok, apaas_tool


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


_registered_mcp_ids: set[int] = set()


def register(mcp):
    """把 skill 创作工具注册进给定的 FastMCP 实例（幂等）。"""
    marker = id(mcp)
    if marker in _registered_mcp_ids:
        return
    _registered_mcp_ids.add(marker)

    @mcp.tool()
    @apaas_tool(
        required=["name", "description", "instructions"],
        message="create_skill 需要 name / description / instructions",
    )
    async def create_skill(
        name: str,
        description: str,
        instructions: str,
        helpers: list | None = None,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """Use when 用户想把一段可复用做法沉淀成新技能（存成技能 / AI 创建 skill / 沉淀做法）。在技能库创建一个 user skill（SKILL.md + 可选 helper 文件）。

        写好一个 skill 的要点：
        - name：英文 kebab-case（如 weekly-report），ASCII、唯一。
        - description：第三人称、触发导向的一句『Use when …』——决定以后 use_skill 触发准不准，必须写清『什么时候该用』并含可被关键词命中的场景词。
        - instructions：SKILL.md 正文，写具体编号步骤（命令式）、单一职责、精简；细节用引用文件而非堆正文。
        - helpers：确定性逻辑（解析/转换/调用）优先写成 helper 脚本（如 helper.py，用 run_python 跑），而非让模型每次重做。每项 {path, content}。
        """
        if skills_root() is None:
            return _err(ErrorCode.SKILLS_UNSUPPORTED, "当前环境未启用技能库")
        reg = SkillRegistry()
        if reg.get(name) is not None:
            return _err(ErrorCode.SKILL_EXISTS, f"技能已存在: {name}")
        try:
            res = author_user_skill(name, description, instructions, helpers, registry=reg)
        except ValueError as e:
            return _err(ErrorCode.SKILL_NAME_INVALID, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(ErrorCode.SKILL_WRITE_FAILED, str(e))
        return _ok(**res)

    @mcp.tool()
    async def list_skills(tenant_id: int = 0, user_id: int = 0) -> dict:
        """列出技能库里的全部技能（name/description/source）。创建前可用它查重名。"""
        if skills_root() is None:
            return _err(ErrorCode.SKILLS_UNSUPPORTED, "当前环境未启用技能库")
        items = [
            {"name": s.name, "description": s.description, "source": s.source}
            for s in SkillRegistry().scan()
        ]
        return _ok(skills=items)

    @mcp.tool()
    @apaas_tool(required=["name", "path"], message="read_skill_file 需要 name / path")
    async def read_skill_file(name: str, path: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """读某个技能内一个文件的内容（如 SKILL.md / helper.py），用于回看与迭代。"""
        try:
            content = SkillRegistry().read_skill_file(name, path)
        except FileNotFoundError as e:
            return _err(ErrorCode.NOT_FOUND, str(e))
        except ValueError as e:
            return _err(ErrorCode.INVALID_PARAMS, str(e))
        return _ok(name=name, path=path, content=content)

    @mcp.tool()
    @apaas_tool(required=["name", "path", "content"], message="write_skill_file 需要 name / path / content")
    async def write_skill_file(name: str, path: str, content: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """往一个 user 技能写/覆盖一个文件（仅 user skill，越界与 platform 只读由底层拦）。"""
        try:
            SkillRegistry().write_skill_file(name, path, content)
        except FileNotFoundError as e:
            return _err(ErrorCode.NOT_FOUND, str(e))
        except PermissionError as e:
            return _err(ErrorCode.SKILL_READONLY, str(e))
        except ValueError as e:
            return _err(ErrorCode.INVALID_PARAMS, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(ErrorCode.SKILL_WRITE_FAILED, str(e))
        return _ok(name=name, path=path)

    @mcp.tool()
    @apaas_tool(required=["name"], message="update_skill_metadata 需要 name")
    async def update_skill_metadata(
        name: str,
        description: str | None = None,
        tags: list | None = None,
        display_name: str | None = None,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """改写一个 user 技能 SKILL.md 的 frontmatter（保留正文）。"""
        try:
            SkillRegistry().update_skill_metadata(
                name, description=description, tags=tags, display_name=display_name
            )
        except FileNotFoundError as e:
            return _err(ErrorCode.NOT_FOUND, str(e))
        except PermissionError as e:
            return _err(ErrorCode.SKILL_READONLY, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(ErrorCode.SKILL_WRITE_FAILED, str(e))
        return _ok(name=name)

    return {
        "create_skill": create_skill,
        "list_skills": list_skills,
        "read_skill_file": read_skill_file,
        "write_skill_file": write_skill_file,
        "update_skill_metadata": update_skill_metadata,
    }
