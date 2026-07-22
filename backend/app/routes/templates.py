"""模板管理 API — 基于文件系统的 MD 设计文档模板。

权限：
- 模板是平台级共享资源（所有租户可读），所以读操作仅要求登录态
- 写操作（create/update/delete/upload）限 platform_admin
"""

from datetime import datetime
import re
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel

from app.deps import AuthContext, get_platform_auth_context

router = APIRouter(prefix="/templates", tags=["模板管理"])


def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.tenant_role == "platform_admin" or ctx.user.is_platform_admin:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="仅平台管理员可管理模板",
    )

# 模板目录
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 MD 文件的 YAML frontmatter，返回 (metadata, body)"""
    if not content.startswith("---"):
        return {}, content

    end = content.find("---", 3)
    if end == -1:
        return {}, content

    frontmatter = content[3:end].strip()
    body = content[end + 3:].strip()

    # 简单的 YAML 解析（避免引入 pyyaml 依赖）
    meta = {}
    for line in frontmatter.split("\n"):
        line = line.strip()
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()

    return meta, body


def _safe_read_template(md_file: Path) -> tuple[dict, str] | None:
    """安全读取模板文件，遇到坏文件时返回 None，避免整个接口 500。"""
    try:
        content = md_file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    meta, body = _parse_frontmatter(content)
    return meta, body


def _find_template_file(code: str) -> tuple[Path, dict, str] | None:
    """按 code 查找模板文件，优先命中文件名，再回退扫描 frontmatter。"""
    if not TEMPLATES_DIR.exists():
        return None

    direct_file = TEMPLATES_DIR / f"{code}.md"
    if direct_file.exists():
        loaded = _safe_read_template(direct_file)
        if loaded:
            meta, body = loaded
            if not meta.get("code") or meta.get("code") == code:
                return direct_file, meta, body

    for md_file in TEMPLATES_DIR.glob("*.md"):
        loaded = _safe_read_template(md_file)
        if not loaded:
            continue
        meta, body = loaded
        if meta.get("code") == code:
            return md_file, meta, body

    return None


def _scan_templates() -> list[dict]:
    """扫描模板目录，返回模板列表"""
    if not TEMPLATES_DIR.exists():
        return []

    templates = []
    for md_file in TEMPLATES_DIR.glob("*.md"):
        loaded = _safe_read_template(md_file)
        if not loaded:
            continue
        meta, _ = loaded

        if not meta.get("name") or not meta.get("code"):
            continue

        templates.append({
            "code": meta["code"],
            "name": meta["name"],
            "icon": meta.get("icon", "clipboard"),
            "description": meta.get("description", ""),
            "category": meta.get("category", ""),
            "filename": md_file.name,
            "updated_at": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
        })

    return sorted(
        templates,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )


@router.get("")
async def list_templates(
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
):
    """获取模板列表（仅登录用户）"""
    return _scan_templates()


@router.get("/{code}")
async def get_template(
    code: str,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
):
    """获取指定模板的完整 MD 内容（仅登录用户）"""
    if not TEMPLATES_DIR.exists():
        raise HTTPException(status_code=404, detail="模板目录不存在")

    found = _find_template_file(code)
    if found:
        md_file, meta, body = found
        return {
            "code": meta.get("code", code),
            "name": meta.get("name", md_file.stem),
            "icon": meta.get("icon", "clipboard"),
            "description": meta.get("description", ""),
            "category": meta.get("category", ""),
            "filename": md_file.name,
            "updated_at": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
            "content": body,
        }

    raise HTTPException(status_code=404, detail=f"模板 '{code}' 不存在")


def _build_frontmatter(meta: dict) -> str:
    """构建 YAML frontmatter"""
    lines = ["---"]
    for key in ["name", "code", "icon", "description", "category"]:
        if key in meta:
            lines.append(f"{key}: {meta[key]}")
    lines.append("---")
    return "\n".join(lines)


def _sanitize_code(code: str) -> str:
    """将 code 转为合法文件名（英文、数字、连字符）"""
    code = re.sub(r'[^a-zA-Z0-9\-_]', '-', code.lower())
    return re.sub(r'-+', '-', code).strip('-')


class TemplateCreateRequest(BaseModel):
    name: str
    code: str
    icon: str = "clipboard"
    description: str = ""
    category: str = ""
    content: str  # MD 正文（不含 frontmatter）


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None


@router.post("")
async def create_template(
    req: TemplateCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
):
    """创建新模板（仅平台管理员）"""
    _require_platform_admin(ctx)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    code = _sanitize_code(req.code)
    if not code:
        raise HTTPException(status_code=400, detail="code 不合法")

    filepath = TEMPLATES_DIR / f"{code}.md"
    if filepath.exists():
        raise HTTPException(status_code=409, detail=f"模板 '{code}' 已存在")

    meta = {"name": req.name, "code": code, "icon": req.icon, "description": req.description, "category": req.category}
    full_content = _build_frontmatter(meta) + "\n\n" + req.content
    filepath.write_text(full_content, encoding="utf-8")

    return {"code": code, "name": req.name, "message": "创建成功"}


@router.put("/{code}")
async def update_template(
    code: str,
    req: TemplateUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
):
    """更新模板（仅平台管理员）"""
    _require_platform_admin(ctx)
    if not TEMPLATES_DIR.exists():
        raise HTTPException(status_code=404, detail="模板目录不存在")

    found = _find_template_file(code)
    if not found:
        raise HTTPException(status_code=404, detail=f"模板 '{code}' 不存在")
    filepath, meta, body = found

    # 更新元数据
    if req.name is not None:
        meta["name"] = req.name
    if req.icon is not None:
        meta["icon"] = req.icon
    if req.description is not None:
        meta["description"] = req.description
    if req.category is not None:
        meta["category"] = req.category
    if req.content is not None:
        body = req.content

    full_content = _build_frontmatter(meta) + "\n\n" + body
    filepath.write_text(full_content, encoding="utf-8")

    return {"code": code, "name": meta.get("name", ""), "message": "更新成功"}


@router.delete("/{code}")
async def delete_template(
    code: str,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
):
    """删除模板（仅平台管理员）"""
    _require_platform_admin(ctx)
    if not TEMPLATES_DIR.exists():
        raise HTTPException(status_code=404, detail="模板目录不存在")

    found = _find_template_file(code)
    if not found:
        raise HTTPException(status_code=404, detail=f"模板 '{code}' 不存在")
    filepath, _, _ = found

    filepath.unlink()
    return {"code": code, "message": "删除成功"}


@router.post("/upload")
async def upload_template(
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    file: UploadFile = File(...),
):
    """上传 MD 文件作为模板（仅平台管理员）"""
    _require_platform_admin(ctx)
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    content = (await file.read()).decode("utf-8")
    meta, body = _parse_frontmatter(content)

    if not meta.get("name") or not meta.get("code"):
        # 没有 frontmatter，用文件名作为 code
        code = _sanitize_code(file.filename.replace('.md', ''))
        name = file.filename.replace('.md', '')
        meta = {"name": name, "code": code, "icon": "clipboard", "description": "", "category": ""}
        full_content = _build_frontmatter(meta) + "\n\n" + content
    else:
        code = meta["code"]
        full_content = content

    filepath = TEMPLATES_DIR / f"{code}.md"
    filepath.write_text(full_content, encoding="utf-8")

    return {"code": code, "name": meta.get("name", ""), "message": "上传成功", "is_new": not filepath.exists()}
