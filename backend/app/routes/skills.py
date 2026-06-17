"""桌面 Skill 库管理 — /skills list/upload/delete。文件系统层在 ai_chat.skills。"""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.ai_chat.skills import SkillRegistry, _parse_frontmatter, skills_root
from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/skills", tags=["skills"])


def _extract_user_skill_zip(data: bytes) -> str:
    """校验+解压用户 skill zip 到 user/<name>/，返回 skill name。非法抛 ValueError。"""
    root = skills_root()
    if root is None:
        raise ValueError("当前环境不支持 skill 上传（非桌面端）")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        # 找 SKILL.md（允许在顶层或单层目录内）
        skill_md = next((n for n in names if n.rstrip("/").endswith("SKILL.md")), None)
        if not skill_md:
            raise ValueError("zip 内未找到 SKILL.md")
        meta, _ = _parse_frontmatter(z.read(skill_md).decode("utf-8", errors="replace"))
        name = (meta.get("name") or "").strip()
        desc = (meta.get("description") or "").strip()
        if not name or not desc:
            raise ValueError("SKILL.md frontmatter 必须含 name 和 description")
        # name 自身不能含路径分隔（防 frontmatter 注入越界）。
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"非法技能名: {name}")
        prefix = skill_md[: -len("SKILL.md")]  # zip 内 skill 根前缀
        dest = (root / "user" / name).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.endswith("/"):
                continue
            if not n.startswith(prefix):
                continue
            rel = n[len(prefix):]
            if not rel:
                continue
            out = (dest / rel).resolve()
            # zip slip 防护：解压目标必须严格落在 dest 内。
            if out != dest and dest not in out.parents:
                raise ValueError(f"非法路径: {n}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))
    return name


def _delete_user_skill(name: str) -> None:
    reg = SkillRegistry()
    s = reg.get(name)
    if s is None:
        raise ValueError("技能不存在")
    if s.source != "user":
        raise ValueError("平台预置技能不可删除")
    shutil.rmtree(s.dir)


@router.get("")
async def list_skills(ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    return {"skills": [
        {"name": s.name, "description": s.description, "source": s.source, "files": s.files}
        for s in SkillRegistry().scan()
    ]}


@router.post("")
async def upload_skill(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    file: UploadFile = File(...),
):
    data = await file.read()
    try:
        name = _extract_user_skill_zip(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "name": name}


@router.delete("/{name}")
async def delete_skill(
    name: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    try:
        _delete_user_skill(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
