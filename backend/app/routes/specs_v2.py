"""
/api/specs-v2 — SPEC 列表（v2 SpecsPage 视图）

聚合真实产物：扫 `ai_chat_artifacts` 表里 format='md' 的设计文档，按 filename
分组（同名文档多次写入 → version 递增），取最新版本作为 list item，老版本进
versions 时间线。章节数从 markdown 内容用正则抽（## 数据模型 / ## 数据字典
等 heading）。excerpt 是文档前 ~1500 字符。
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models.ai_chat import AIChatArtifact, AIChatSession

router = APIRouter(prefix="/specs-v2", tags=["specs-v2"])


class SpecVersionItem(BaseModel):
    v: int
    status: str  # draft / test / prod / archived
    note: str
    author: str
    date: str


class SpecSection(BaseModel):
    name: str
    count: int


class SpecListItem(BaseModel):
    id: str
    app_id: int
    app_name: str
    latest: int
    diff_add: int
    diff_mod: int
    origin: str
    versions: list[SpecVersionItem]
    sections: list[SpecSection]
    excerpt: str = ""


class SpecListResponse(BaseModel):
    specs: list[SpecListItem]
    total: int


# 章节匹配规则 — 标题（## / ### 后跟章节名）+ 兼容"应用信息 / 角色列表 / 数据字典"等常见命名变体
SECTION_PATTERNS: dict[str, list[str]] = {
    "需求摘要": [r"需求摘要", r"应用信息", r"业务概述", r"目标"],
    "数据模型": [r"数据模型", r"数据表", r"实体设计", r"业务对象"],
    "表单": [r"表单(?!设计器)", r"表单配置", r"输入表单"],
    "流程": [r"流程", r"工作流", r"审批"],
    "角色权限": [r"角色列表", r"角色权限", r"权限", r"角色"],
    "字典": [r"数据字典", r"字典"],
}


def _count_section_items(md: str, section_name: str, patterns: list[str]) -> int:
    """估算章节下条目数 — 找 ## section heading，统计随后 markdown 表格行（不含分隔行）。

    匹配第一个 # 级 heading 是 section 起始，到下一个 # 级 heading 是结束。
    在区间内 count `| ... |` 行减去分隔行 `|---|`。如果没表格，count `### ` 子 heading 数。
    section_name 没找到时返回 0。
    """
    if not md:
        return 0
    # Match: ## 一、数据模型 / ## 1.数据模型 / ## 数据模型 / ### 3.1 字典名 / 数据模型(无 # 前缀的有时也用)
    # Chinese ordinal prefix: 一二三四五六七八九十 / Arabic 1.2.3 / no prefix
    ordinal = r"(?:[一二三四五六七八九十]+[、.\)]?\s*)?(?:\d+[、.\)]?\s*)?"
    pat = r"^\s*#{1,3}\s*" + ordinal + r"(?:" + "|".join(patterns) + r")"
    matches = list(re.finditer(pat, md, flags=re.MULTILINE))
    if not matches:
        return 0
    start = matches[0].end()
    # find next # / ## / ### heading after start
    nxt = re.search(r"^\s*#{1,3}\s+\S", md[start:], flags=re.MULTILINE)
    section_body = md[start: start + nxt.start()] if nxt else md[start:]

    # Strategy 1: count markdown tables. A row is "non-divider" if it has `|` and not all-dash content.
    # Accept rows with or without leading `|` (AI often emits `col1|col2|col3` without bookend pipes).
    table_rows: list[str] = []
    for ln in section_body.split("\n"):
        s = ln.strip()
        if "|" not in s:
            continue
        if "---" in s or "===" in s:
            continue  # divider row
        # Ignore single-pipe lines that are clearly not tables (e.g., 'foo | bar | baz' in prose — accept anyway)
        table_rows.append(s)
    if table_rows:
        # Exclude header row (assume first row is header for table-style sections)
        count = max(0, len(table_rows) - 1) if len(table_rows) >= 2 else len(table_rows)
        if count > 0:
            return count

    # Strategy 2: count ### sub-headings
    sub_headings = len(re.findall(r"^\s*###\s+\S", section_body, flags=re.MULTILINE))
    if sub_headings > 0:
        return sub_headings

    # Strategy 3: count bullet points `- ` or `* `
    bullets = len(re.findall(r"^\s*[-*]\s+\S", section_body, flags=re.MULTILINE))
    return bullets


def _parse_sections(md: str) -> list[SpecSection]:
    return [
        SpecSection(name=name, count=_count_section_items(md, name, patterns))
        for name, patterns in SECTION_PATTERNS.items()
    ]


def _strip_app_name(filename: str) -> str:
    """`人才管理系统设计文档.md` → `人才管理系统` (best-effort)."""
    base = re.sub(r"\.md$", "", filename, flags=re.IGNORECASE)
    base = re.sub(r"设计文档$|说明$|spec$", "", base, flags=re.IGNORECASE).strip()
    return base or filename


@router.get("", response_model=SpecListResponse)
async def list_specs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SpecListResponse:
    """列出当前租户所有 AI 产出的 .md 设计文档，按 filename 分组。

    数据来源：ai_chat_artifacts 表（write_artifact 工具产出，存进 AIChatPage 对话）。
    同名文档多次写入 → 取 latest version 作为 list item，老版本进 versions 时间线。
    """
    # Join artifacts with sessions to filter by tenant
    result = await db.execute(
        select(AIChatArtifact, AIChatSession)
        .join(AIChatSession, AIChatArtifact.session_id == AIChatSession.id)
        .where(
            AIChatSession.tenant_id == ctx.tenant_id,
            AIChatArtifact.format == "md",
        )
        .order_by(AIChatArtifact.updated_at.desc())
    )
    rows = result.all()

    # Group by filename, collect all versions
    grouped: dict[str, list[tuple[AIChatArtifact, AIChatSession]]] = {}
    for art, sess in rows:
        grouped.setdefault(art.filename, []).append((art, sess))

    author_name = getattr(ctx.user, "username", "—") or "—"
    out: list[SpecListItem] = []

    for filename, items in grouped.items():
        # Sort by version desc (latest first)
        items.sort(key=lambda t: t[0].version, reverse=True)
        latest_art, latest_sess = items[0]

        app_name = _strip_app_name(filename)
        sections = _parse_sections(latest_art.content)
        excerpt = (latest_art.content or "")[:1500]

        versions: list[SpecVersionItem] = []
        for i, (art, sess) in enumerate(items):
            date_str = "—"
            if art.updated_at:
                try:
                    date_str = art.updated_at.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            status = "draft" if i == 0 else "archived"
            versions.append(SpecVersionItem(
                v=art.version,
                status=status,
                note=f"会话「{sess.title}」",
                author=author_name,
                date=date_str,
            ))

        out.append(SpecListItem(
            id=f"art-{latest_art.id}",
            app_id=latest_art.session_id,  # session_id as ref (no real Application binding yet)
            app_name=app_name,
            latest=latest_art.version,
            diff_add=0,  # TODO: real diff when version compare backend lands
            diff_mod=0,
            origin=f"AI Chat · {latest_sess.title}",
            versions=versions,
            sections=sections,
            excerpt=excerpt,
        ))

    return SpecListResponse(specs=out, total=len(out))
