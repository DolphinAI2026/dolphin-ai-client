"""桌面 Skill 库管理 — /skills list/upload/delete。文件系统层在 ai_chat.skills。"""
from __future__ import annotations

import io
import os
import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.ai_chat.skills import SkillRegistry, _parse_frontmatter, skills_root
from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/skills", tags=["skills"])

# 上传体积上限（解压前/后都设防，兜 zip bomb）。桌面单机用，给得宽松。
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 整包压缩字节上限（桌面单机本地, 放宽以容纳带 jar/模板/资源的 skill）
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024  # 解压累计字节上限


def _is_junk_entry(name: str) -> bool:
    """macOS Finder 打包会塞 __MACOSX/ 资源叉 + ._* / .DS_Store 等垃圾项。

    这些必须在 **选 SKILL.md** 和 **解压** 两处都剔除：否则
    `._SKILL.md` 会被 `endswith('SKILL.md')` 误选去 parse（读到 AppleDouble
    二进制头 → 误报 frontmatter 缺字段），且垃圾文件会被写进 skill 目录。
    """
    if name.startswith("__MACOSX/") or name == "__MACOSX":
        return True
    base = os.path.basename(name.rstrip("/"))
    return base.startswith("._") or base == ".DS_Store"


def _extract_user_skill_zip(data: bytes) -> str:
    """校验+解压用户 skill zip 到 user/<name>/，返回 skill name。非法抛 ValueError。

    原子落盘：先解到临时目录，全量校验通过后才整体替换目标目录。任何中途失败
    都不会在 user/ 下留半个 skill（避免 list/use_skill 拿到残缺技能）。
    """
    root = skills_root()
    if root is None:
        raise ValueError("当前环境不支持 skill 上传（非桌面端）")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件过大")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("文件不是合法 zip")
    with zf as z:
        # 过滤掉 macOS 资源叉/点垃圾，再做 SKILL.md 选择与解压。
        names = [n for n in z.namelist() if not _is_junk_entry(n)]
        # 找 SKILL.md（允许在顶层或单层目录内）
        skill_md = next(
            (n for n in names if n.rstrip("/").endswith("SKILL.md")), None
        )
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
        # 不允许覆盖平台预置技能：skill 脚本在本机执行，同名 shadow = 用任意内容
        # 替换可信平台技能的信任边界问题。
        existing = SkillRegistry(root).get(name)
        if existing is not None and existing.source == "platform":
            raise ValueError(f"技能名与平台预置技能冲突: {name}")
        prefix = skill_md[: -len("SKILL.md")]  # zip 内 skill 根前缀
        # 允许嵌套子目录(references/ scripts/ assets/ 是 Claude skill 常见结构);
        # zip-slip 由下面解压循环的 resolve+parents 守卫拦(.. / 绝对路径)。
        dest = (root / "user" / name).resolve()
        # 原子落盘：解到同级临时目录，成功后再替换。
        tmp = (root / "user" / f".{name}.tmp").resolve()
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            total = 0
            for n in names:
                if n.endswith("/") or not n.startswith(prefix):
                    continue
                rel = n[len(prefix):]
                if not rel:
                    continue
                info = z.getinfo(n)
                total += info.file_size
                if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("解压内容过大")
                out = (tmp / rel).resolve()
                # zip slip 防护：解压目标必须严格落在 tmp 内。
                if out != tmp and tmp not in out.parents:
                    raise ValueError(f"非法路径: {n}")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(n))
            # 全量校验通过 → 原子替换（先清旧版，去除残留旧文件）。
            shutil.rmtree(dest, ignore_errors=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
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


# ── Skill 文件 CRUD（仅 user skill 可写；platform 只读） ──

class _WriteReq(BaseModel):
    path: str
    content: str


class _MetaReq(BaseModel):
    description: str | None = None
    tags: list[str] | None = None
    display_name: str | None = None


class _NameReq(BaseModel):
    name: str


class _CloneReq(BaseModel):
    new_name: str


# 纯函数封装：底层逻辑全在 SkillRegistry（B1 已覆盖），这里只做薄转译便于单测。
def _skill_files(name: str) -> list[str]:
    return SkillRegistry().list_skill_files(name)


def _skill_read(name: str, path: str) -> dict:
    return {"path": path, "content": SkillRegistry().read_skill_file(name, path)}


def _skill_write(name: str, path: str, content: str) -> None:
    SkillRegistry().write_skill_file(name, path, content)


def _skill_delete_file(name: str, path: str) -> None:
    SkillRegistry().delete_skill_file(name, path)


def _skill_update_metadata(name: str, meta: dict) -> None:
    SkillRegistry().update_skill_metadata(
        name, description=meta.get("description"),
        tags=meta.get("tags"), display_name=meta.get("display_name"))


def _skill_create(name: str) -> str:
    return SkillRegistry().create_user_skill(name)


def _skill_clone(src: str, new_name: str) -> str:
    return SkillRegistry().clone_skill(src, new_name)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, PermissionError):
        return HTTPException(status_code=403, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


# 路由顺序：/new 必须在 /{name}/... 之前注册，否则 "new" 会被当成 {name}。
@router.post("/new")
async def skill_new(req: _NameReq, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        return {"name": _skill_create(req.name)}
    except Exception as e:
        raise _err(e)


@router.get("/{name}/files")
async def skill_files(name: str, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        return {"files": _skill_files(name)}
    except Exception as e:
        raise _err(e)


@router.get("/{name}/file")
async def skill_read_file(name: str, path: str, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        return _skill_read(name, path)
    except Exception as e:
        raise _err(e)


@router.post("/{name}/file")
async def skill_write_file(name: str, req: _WriteReq, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        _skill_write(name, req.path, req.content)
        return {"ok": True}
    except Exception as e:
        raise _err(e)


@router.delete("/{name}/file")
async def skill_delete_file_route(name: str, path: str, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        _skill_delete_file(name, path)
        return {"ok": True}
    except Exception as e:
        raise _err(e)


@router.put("/{name}/metadata")
async def skill_metadata(name: str, req: _MetaReq, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        _skill_update_metadata(name, req.model_dump(exclude_none=True))
        return {"ok": True}
    except Exception as e:
        raise _err(e)


@router.post("/{name}/clone")
async def skill_clone(name: str, req: _CloneReq, ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    try:
        return {"name": _skill_clone(name, req.new_name)}
    except Exception as e:
        raise _err(e)
