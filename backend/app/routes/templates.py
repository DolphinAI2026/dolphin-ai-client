"""模板管理 API — 基于文件系统的 MD 设计文档模板"""

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

router = APIRouter(prefix="/templates", tags=["模板管理"])

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


def _scan_templates() -> list[dict]:
    """扫描模板目录，返回模板列表"""
    if not TEMPLATES_DIR.exists():
        return []

    templates = []
    for md_file in sorted(TEMPLATES_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        meta, _ = _parse_frontmatter(content)

        if not meta.get("name") or not meta.get("code"):
            continue

        templates.append({
            "code": meta["code"],
            "name": meta["name"],
            "icon": meta.get("icon", "clipboard"),
            "description": meta.get("description", ""),
            "category": meta.get("category", ""),
            "filename": md_file.name,
        })

    return templates


@router.get("")
async def list_templates():
    """获取模板列表"""
    return _scan_templates()


@router.get("/{code}")
async def get_template(code: str):
    """获取指定模板的完整 MD 内容"""
    if not TEMPLATES_DIR.exists():
        raise HTTPException(status_code=404, detail="模板目录不存在")

    for md_file in TEMPLATES_DIR.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(content)

        if meta.get("code") == code:
            return {
                "code": meta["code"],
                "name": meta["name"],
                "icon": meta.get("icon", "clipboard"),
                "description": meta.get("description", ""),
                "category": meta.get("category", ""),
                "filename": md_file.name,
                "content": body,  # 不含 frontmatter 的 MD 正文
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
async def create_template(req: TemplateCreateRequest):
    """创建新模板"""
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
async def update_template(code: str, req: TemplateUpdateRequest):
    """更新模板"""
    if not TEMPLATES_DIR.exists():
        raise HTTPException(status_code=404, detail="模板目录不存在")

    filepath = TEMPLATES_DIR / f"{code}.md"
    if not filepath.exists():
        # 也查找 code 匹配的文件
        filepath = None
        for md_file in TEMPLATES_DIR.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(content)
            if meta.get("code") == code:
                filepath = md_file
                break
        if not filepath:
            raise HTTPException(status_code=404, detail=f"模板 '{code}' 不存在")

    content = filepath.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(content)

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
async def delete_template(code: str):
    """删除模板"""
    if not TEMPLATES_DIR.exists():
        raise HTTPException(status_code=404, detail="模板目录不存在")

    filepath = TEMPLATES_DIR / f"{code}.md"
    if not filepath.exists():
        # 也查找 code 匹配的文件
        for md_file in TEMPLATES_DIR.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(content)
            if meta.get("code") == code:
                filepath = md_file
                break
        else:
            raise HTTPException(status_code=404, detail=f"模板 '{code}' 不存在")

    filepath.unlink()
    return {"code": code, "message": "删除成功"}


@router.post("/upload")
async def upload_template(file: UploadFile = File(...)):
    """上传 MD 文件作为模板"""
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
