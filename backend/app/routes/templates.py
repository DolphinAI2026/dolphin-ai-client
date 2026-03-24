"""模板管理 API — 基于文件系统的 MD 设计文档模板"""

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

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
        content = md_file.read_text(encoding="utf-8")
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
