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
    # doc_type 区分文档类型，前端据此决定渲染章节统计 (sections) 还是 outline 大纲：
    #   'spec'              — 标准 SPEC 6 章节（数据模型 / 表单 / 流程 / 角色 / 字典）
    #   'self_dev_package'  — 自开发包说明 (package.json / 工程结构 / vue / 组件)
    #   'page_design'       — 页面/看板/布局设计稿（非 SPEC）
    #   'general'           — 兜底，含不到任何 SPEC 关键词的普通文档
    doc_type: str = "spec"
    # 非 spec 文档显示 outline（## 二级标题前 8 条），spec 文档为空 list
    outline: list[str] = []


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


# 文档类型识别关键词（小写匹配）
# 顺序判定：先 spec（最强信号），再 self_dev_package，再 page_design，否则 general
_SPEC_KEYWORDS = [
    "数据模型", "数据表", "实体设计", "业务对象",
    "数据字典", "字典", "角色列表", "角色权限",
    "应用编码", "app_code", "应用编号",
]
_SELF_DEV_PACKAGE_KEYWORDS = [
    "自开发", "package.json", "工程结构", "目录结构",
    "vue.config", "main.ts", "src/components",
    "前端工程", "前端包", "自开发包", "npm install",
    "pnpm install", "yarn install", "df-apaas-cli",
]
_PAGE_DESIGN_KEYWORDS = [
    "看板", "页面布局", "页面设计", "组件布局",
    "首页设计", "原型", "线框", "wireframe",
    "ui 设计", "ui设计", "页面结构", "卡片布局",
]


def _detect_doc_type(md: str) -> str:
    """根据 markdown 内容关键词组识别文档类型。

    返回 'spec' / 'self_dev_package' / 'page_design' / 'general' 之一。
    判定优先级：spec（最强信号，2+ 关键词命中）> self_dev_package > page_design > general。
    """
    if not md:
        return "general"
    low = md.lower()

    spec_hits = sum(1 for k in _SPEC_KEYWORDS if k.lower() in low)
    # 至少命中 2 个 SPEC 关键词才算 SPEC（避免单一"角色"误判）
    if spec_hits >= 2:
        return "spec"

    self_dev_hits = sum(1 for k in _SELF_DEV_PACKAGE_KEYWORDS if k.lower() in low)
    if self_dev_hits >= 1:
        return "self_dev_package"

    page_hits = sum(1 for k in _PAGE_DESIGN_KEYWORDS if k.lower() in low)
    if page_hits >= 1:
        return "page_design"

    return "general"


def _extract_outline(md: str, limit: int = 8) -> list[str]:
    """提取 markdown 二级标题 `^##\\s+...` 前 `limit` 条作为 outline 大纲。

    用于非 SPEC 文档替代 5 章节统计的展示。剥掉 `#` 前缀和序号前缀。
    """
    if not md:
        return []
    out: list[str] = []
    for m in re.finditer(r"^\s*##\s+(.+?)\s*$", md, flags=re.MULTILINE):
        title = m.group(1).strip()
        # 剥掉常见序号前缀：`一、` `1.` `1)` 之类
        title = re.sub(r"^(?:[一二三四五六七八九十]+[、.\)]\s*|\d+[、.\)]\s*)", "", title)
        if title:
            out.append(title)
        if len(out) >= limit:
            break
    return out


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
        md_content = latest_art.content or ""
        doc_type = _detect_doc_type(md_content)
        # SPEC 文档算 6 章节统计；非 SPEC 不算（避免 0/0/0/0/0 误显示丢东西），改给 outline
        if doc_type == "spec":
            sections = _parse_sections(md_content)
            outline: list[str] = []
        else:
            sections = []
            outline = _extract_outline(md_content)
        excerpt = md_content[:1500]

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
            doc_type=doc_type,
            outline=outline,
        ))

    return SpecListResponse(specs=out, total=len(out))


# ============================================================================
# /api/specs-v2/parse-md — structured md → SPEC for AIChatPage blueprint panel
# ============================================================================


class ParseMdReq(BaseModel):
    content: str


class ParsedModel(BaseModel):
    name: str
    code: str
    fields: list[dict]  # [{name, code, type, required?, unique?}]


class ParsedForm(BaseModel):
    name: str
    backing_model: str = ""
    sections: list[dict]


class ParsedFlow(BaseModel):
    name: str
    trigger: str = ""
    nodes: list[dict]


class ParsedRole(BaseModel):
    name: str
    scope: str = ""
    code: str = ""


class ParsedDict(BaseModel):
    name: str
    code: str = ""
    entries: list[dict]  # [{code, label}]


class ParseMdResp(BaseModel):
    models: list[ParsedModel]
    forms: list[ParsedForm]
    flows: list[ParsedFlow]
    roles: list[ParsedRole]
    dicts: list[ParsedDict]
    fields_total: int


def _extract_section_body(md: str, name_patterns: list[str]) -> str | None:
    """Find the markdown body under a top-level section heading matching name_patterns.

    Only searches for sibling/parent headings (same or higher level) as the section
    terminator — deeper sub-headings (###) under a ## section are part of the body.
    """
    if not md:
        return None
    ordinal = r"(?:[一二三四五六七八九十]+[、.\)]?\s*)?(?:\d+[、.\)]?\s*)?"
    # Capture the # prefix to determine heading level
    pat = r"^\s*(#{1,3})\s*" + ordinal + r"(?:" + "|".join(name_patterns) + r")"
    m = re.search(pat, md, flags=re.MULTILINE)
    if not m:
        return None
    level = len(m.group(1))  # 1, 2, or 3
    start = m.end()
    # Next-heading: same or higher level only (1..level # marks, but not more)
    nxt_pat = r"^\s*#{1," + str(level) + r"}(?!#)\s+\S"
    nxt = re.search(nxt_pat, md[start:], flags=re.MULTILINE)
    return md[start: start + nxt.start()] if nxt else md[start:]


def _parse_md_tables(body: str) -> list[list[list[str]]]:
    """Parse all markdown tables in body. Returns list of tables, each table is list of rows (each row is list of cells)."""
    if not body:
        return []
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for ln in body.split("\n"):
        s = ln.strip()
        if "|" not in s or "===" in s:
            if current:
                tables.append(current)
                current = []
            continue
        # Strip leading/trailing | if present
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        cells = [c.strip() for c in s.split("|")]
        if "---" in "".join(cells) or all(set(c) <= set("- :") for c in cells):
            continue  # divider row
        current.append(cells)
    if current:
        tables.append(current)
    return tables


def _table_to_fields(rows: list[list[str]]) -> list[dict]:
    """Convert a markdown table (rows of cells) to field list. First row is header (字段|类型|...)."""
    if len(rows) < 2:
        return []
    header = [h.lower() for h in rows[0]]
    # Find column indices best-effort
    name_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["字段名", "name", "字段", "名称"])), 0)
    code_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["code", "编码", "标识"])), -1)
    type_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["type", "类型"])), -1)
    req_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["必填", "required", "必"])), -1)
    fields = []
    for row in rows[1:]:
        if len(row) <= name_idx:
            continue
        name = row[name_idx]
        if not name:
            continue
        f = {"name": name}
        if code_idx >= 0 and len(row) > code_idx:
            f["code"] = row[code_idx]
        if type_idx >= 0 and len(row) > type_idx:
            f["type"] = row[type_idx]
        if req_idx >= 0 and len(row) > req_idx:
            v = row[req_idx].strip()
            f["required"] = v in ("是", "Y", "y", "yes", "true", "必填", "✓")
        fields.append(f)
    return fields


def _parse_models(md: str) -> list[ParsedModel]:
    body = _extract_section_body(md, ["数据模型", "数据表", "实体设计", "业务对象"])
    if not body:
        return []
    out: list[ParsedModel] = []
    # Find ### sub-headings as model names; each followed by a fields table
    sub_pattern = re.finditer(r"^\s*#{3}\s*(?:\d+[、.\d\)]*\s*)?(.+?)$", body, flags=re.MULTILINE)
    starts = [(m.start(), m.end(), m.group(1).strip()) for m in sub_pattern]
    if not starts:
        # Fallback: single model, no sub-headings — just one big table
        tables = _parse_md_tables(body)
        if tables:
            fields = _table_to_fields(tables[0])
            if fields:
                out.append(ParsedModel(name="(未命名)", code="model_main", fields=fields))
        return out
    for i, (s_start, s_end, raw_name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        sub_body = body[s_end: end]
        tables = _parse_md_tables(sub_body)
        if not tables:
            continue
        # Extract code from name (e.g., "人员档案 employee_profile" or "人员档案 (employee_profile)")
        name = raw_name
        code = ""
        code_match = re.search(r"[\(（]?\s*([a-z][a-z0-9_]+)\s*[\)）]?\s*$", raw_name)
        if code_match:
            code = code_match.group(1)
            name = raw_name[: code_match.start()].strip(" -—()（）")
        fields = _table_to_fields(tables[0])
        out.append(ParsedModel(name=name or "(未命名)", code=code or f"model_{i}", fields=fields))
    return out


def _parse_roles(md: str) -> list[ParsedRole]:
    body = _extract_section_body(md, ["角色列表", "角色权限", "角色"])
    if not body:
        return []
    tables = _parse_md_tables(body)
    out: list[ParsedRole] = []
    for table in tables:
        if len(table) < 2:
            continue
        header = [h.lower() for h in table[0]]
        name_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["角色名", "name", "名称"])), -1)
        code_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["角色编码", "code", "编码"])), -1)
        scope_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["范围", "scope", "权限"])), -1)
        for row in table[1:]:
            name = row[name_idx] if name_idx >= 0 and len(row) > name_idx else (row[0] if row else "")
            if not name:
                continue
            out.append(ParsedRole(
                name=name,
                code=row[code_idx] if code_idx >= 0 and len(row) > code_idx else "",
                scope=row[scope_idx] if scope_idx >= 0 and len(row) > scope_idx else "",
            ))
    return out


def _parse_dicts(md: str) -> list[ParsedDict]:
    body = _extract_section_body(md, ["数据字典", "字典"])
    if not body:
        return []
    out: list[ParsedDict] = []
    # Find ### sub-headings as dict names; each followed by an entries table
    sub_pattern = re.finditer(r"^\s*#{3}\s*(?:\d+[、.\d\)]*\s*)?(.+?)$", body, flags=re.MULTILINE)
    starts = [(m.start(), m.end(), m.group(1).strip()) for m in sub_pattern]
    if not starts:
        # No sub-headings — try treating each table as a dict
        tables = _parse_md_tables(body)
        for i, table in enumerate(tables):
            entries = []
            for row in table[1:]:
                if len(row) >= 2:
                    entries.append({"code": row[0], "label": row[1]})
            if entries:
                out.append(ParsedDict(name=f"字典 {i+1}", entries=entries))
        return out
    for i, (s_start, s_end, raw_name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        sub_body = body[s_end: end]
        tables = _parse_md_tables(sub_body)
        if not tables:
            continue
        entries = []
        table = tables[0]
        if len(table) < 2:
            continue
        header = [h.lower() for h in table[0]]
        code_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["选项编码", "code", "编码", "字典编码"])), 0)
        label_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["选项名称", "name", "名称", "字典名"])), 1 if len(header) > 1 else 0)
        for row in table[1:]:
            if len(row) <= max(code_idx, label_idx):
                continue
            entries.append({"code": row[code_idx], "label": row[label_idx]})
        # Extract code from raw_name
        name = raw_name
        code = ""
        code_match = re.search(r"[\(（]?\s*([a-z][a-z0-9_]+_dict)\s*[\)）]?\s*$", raw_name)
        if code_match:
            code = code_match.group(1)
            name = raw_name[: code_match.start()].strip(" -—()（）")
        out.append(ParsedDict(name=name, code=code, entries=entries))
    return out


def _parse_forms(md: str) -> list[ParsedForm]:
    body = _extract_section_body(md, ["表单", "表单配置"])
    if not body:
        return []
    out: list[ParsedForm] = []
    sub_pattern = re.finditer(r"^\s*#{3}\s*(?:\d+[、.\d\)]*\s*)?(.+?)$", body, flags=re.MULTILINE)
    starts = [(m.start(), m.end(), m.group(1).strip()) for m in sub_pattern]
    for i, (s_start, s_end, raw_name) in enumerate(starts):
        out.append(ParsedForm(name=raw_name, backing_model="", sections=[]))
    return out


def _parse_flows(md: str) -> list[ParsedFlow]:
    body = _extract_section_body(md, ["流程", "工作流", "审批"])
    if not body:
        return []
    out: list[ParsedFlow] = []
    sub_pattern = re.finditer(r"^\s*#{3}\s*(?:\d+[、.\d\)]*\s*)?(.+?)$", body, flags=re.MULTILINE)
    starts = [(m.start(), m.end(), m.group(1).strip()) for m in sub_pattern]
    for i, (s_start, s_end, raw_name) in enumerate(starts):
        out.append(ParsedFlow(name=raw_name, trigger="", nodes=[]))
    return out


@router.post("/parse-md", response_model=ParseMdResp)
async def parse_markdown(
    payload: ParseMdReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    md = payload.content or ""
    models = _parse_models(md)
    forms = _parse_forms(md)
    flows = _parse_flows(md)
    roles = _parse_roles(md)
    dicts = _parse_dicts(md)
    fields_total = sum(len(m.fields) for m in models)
    return ParseMdResp(
        models=models,
        forms=forms,
        flows=flows,
        roles=roles,
        dicts=dicts,
        fields_total=fields_total,
    )
