"""DB 问数 wizard：把反向建模出来的表清单 + 分类结果构造成 SPEC v2 markdown 文档。

入口：`build_spec_markdown(...)`，输出一份 6 章 markdown 字符串，主线 ChatPage 的
SPEC 编辑器可直接打开继续编辑/部署。

策略：
  1. 表 → 中文模型名 / 字段中文名 / 菜单分组 → 优先调 LLM enrich，失败 fallback 规则版。
  2. 平台内置字段（id / tenant_id / created_at 等）一律跳过：平台自动管。
  3. 分类档处理：
     - skip   不出现在 SPEC 任何地方
     - red    出现在「2.1 模型清单」（标 🔴 不建议）但不生成表单/菜单
     - yellow 关联表只生成模型不生成菜单；超宽/大字段表正常出表单
     - green  全配
  4. 字段编码用 `lowcode_standards.safe_field_code` 兜底（避保留字 + 冲突）。

输出与 `doc_spec_standard.py` 描述的 6 章 SPEC 在精神上一致（应用信息 / 角色 /
字典 / 数据模型 / 表单 / 权限），但因为是从 DB schema 反向建模来的，章节标题
按本任务输入契约直接用阿拉伯数字 + 中文（1. 业务概述 / 2. 数据模型 / ...）。
后续 doc_pipeline 兜底解析会把它正规化。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.lowcode_standards import safe_field_code

from .prompts import build_enrich_prompt

logger = logging.getLogger(__name__)

# 平台内置 / 框架管控的字段，反向建模时一律跳过，不写入 SPEC。
_BUILTIN_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "last_updated_by",
        "creation_date",
        "last_update_date",
        "owner",
        "version",
        "deleted",
        "is_deleted",
        "del_flag",
    }
)

# DB DDL 类型片段 → SPEC 中文组件类型（用于「五、表单定义」组件类型列 +
# 「四、数据模型」给运维看的类型）。匹配规则：DDL 字符串 lower 后包含 key 即命中。
_DB_TYPE_TO_CHINESE: list[tuple[str, str]] = [
    # 顺序很重要：先匹配更长/更具体的关键字
    ("mediumtext", "长文本"),
    ("longtext", "长文本"),
    ("tinytext", "长文本"),
    ("text", "长文本"),
    ("varchar", "短文本"),
    ("char", "短文本"),
    ("bigint", "整数"),
    ("smallint", "整数"),
    ("tinyint", "整数"),
    ("mediumint", "整数"),
    ("int", "整数"),
    ("decimal", "金额"),
    ("numeric", "金额"),
    ("float", "数字"),
    ("double", "数字"),
    ("real", "数字"),
    ("datetime", "日期时间"),
    ("timestamp", "日期时间"),
    ("date", "日期"),
    ("time", "时间"),
    ("json", "JSON"),
    ("blob", "附件"),
]

# DB DDL 类型片段 → SPEC「数据库字段类型」（标准 7 取值之一）
_DB_TYPE_TO_STANDARD: list[tuple[str, str]] = [
    ("mediumtext", "text"),
    ("longtext", "text"),
    ("tinytext", "text"),
    ("text", "text"),
    ("varchar", "varchar"),
    ("char", "varchar"),
    ("bigint", "bigint"),
    ("smallint", "int"),
    ("tinyint", "int"),
    ("mediumint", "int"),
    ("int", "int"),
    ("decimal", "decimal"),
    ("numeric", "decimal"),
    ("float", "decimal"),
    ("double", "decimal"),
    ("real", "decimal"),
    ("datetime", "datetime"),
    ("timestamp", "datetime"),
    ("date", "date"),
    ("time", "datetime"),
    ("json", "text"),
    ("blob", "varchar"),
]

# 健康度 → 表清单 badge 前缀（用 emoji 跟 wizard UI 对齐）
_HEALTH_EMOJI = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
    "skip": "⚪",
}


def _ddl_to_chinese_type(ddl: str) -> str:
    """DB DDL 字符串 → SPEC 中文组件类型；找不到默认「短文本」。"""
    low = (ddl or "").lower()
    for key, val in _DB_TYPE_TO_CHINESE:
        if key in low:
            return val
    return "短文本"


def _ddl_to_standard_type(ddl: str) -> str:
    """DB DDL 字符串 → SPEC 数据库字段类型；找不到默认 varchar。"""
    low = (ddl or "").lower()
    for key, val in _DB_TYPE_TO_STANDARD:
        if key in low:
            return val
    return "varchar"


def _is_builtin_field(field_name: str) -> bool:
    """该字段是否属于平台内置字段（应跳过）。"""
    return (field_name or "").strip().lower() in _BUILTIN_FIELD_NAMES


def _slugify_app_code(app_code: str) -> str:
    """把任意 app_code 砍成 kebab-case ≤ 17 字符，做兜底。"""
    raw = re.sub(r"[^a-z0-9-]+", "-", (app_code or "").lower()).strip("-")
    if not raw:
        raw = "qdb-app"
    if not raw[0].isalpha():
        raw = "a-" + raw
    return raw[:17].rstrip("-") or "qdb-app"


def _table_to_model_code(table_name: str) -> str:
    """英文表名 → 平台模型编码（snake_case 兜底）。"""
    raw = re.sub(r"[^a-z0-9_]+", "_", (table_name or "").lower()).strip("_")
    if not raw:
        raw = "model"
    if not raw[0].isalpha():
        raw = "m_" + raw
    return raw


def _humanize_table(table_name: str) -> str:
    """fallback 中文模型名：去掉前缀下划线后用 Title Case。"""
    parts = re.split(r"[_\-]+", table_name)
    parts = [p for p in parts if p]
    if not parts:
        return table_name
    return " ".join(p.capitalize() for p in parts)


def _humanize_field(field_name: str, comment: str | None) -> str:
    """fallback 中文字段名：comment 优先，否则 Title Case 字段名。"""
    if comment and comment.strip():
        return comment.strip()
    parts = re.split(r"[_\-]+", field_name)
    parts = [p for p in parts if p]
    if not parts:
        return field_name
    return " ".join(p.capitalize() for p in parts)


def _group_by_prefix(tables: list[str]) -> list[dict[str, Any]]:
    """fallback 菜单分组：按表名第一个 `_` 之前的前缀归组；单表归「其他」。

    返回 `[{"name": "<中文分组名>", "tables": [...]}]`。
    """
    buckets: dict[str, list[str]] = {}
    for tbl in tables:
        prefix = tbl.split("_", 1)[0] if "_" in tbl else tbl
        buckets.setdefault(prefix, []).append(tbl)

    groups: list[dict[str, Any]] = []
    others: list[str] = []
    for prefix, items in buckets.items():
        if len(items) == 1:
            others.extend(items)
        else:
            groups.append({"name": prefix.capitalize(), "tables": items})
    if others:
        groups.append({"name": "其他", "tables": others})
    return groups


async def _call_llm_enrich(
    *,
    db_label: str,
    hint: str,
    schemas: dict[str, dict],
    selected_tables: list[str],
) -> dict[str, Any] | None:
    """调 LLM enrich：返回 `{"models": {...}, "menu_groups": [...]}` 或 None。

    任何异常（超时 / 解析失败 / 网络）都吞掉返 None，让调用方走 fallback。
    """
    try:
        from app.llm_client import LLMClient
    except Exception as exc:  # pragma: no cover - import 错误兜底
        logger.warning("[spec_builder] LLMClient import failed: %s", exc)
        return None

    # 准备 summary（控长度避免 token 爆炸）。
    tables_summary_lines: list[str] = []
    fields_summary_lines: list[str] = []
    for tbl in selected_tables:
        schema = schemas.get(tbl)
        if not schema:
            continue
        fields = schema.get("fields") or []
        tables_summary_lines.append(f"- {tbl}：{len(fields)} 字段")
        fields_summary_lines.append(f"\n### {tbl}")
        for fld in fields[:50]:  # 每表最多 50 字段避免 prompt 爆
            fname = fld.get("name", "")
            ftype = fld.get("type", "")
            fcom = (fld.get("comment") or "").strip() or "-"
            fields_summary_lines.append(f"  - {fname} | {ftype} | {fcom}")

    prompt = build_enrich_prompt(
        db_label=db_label,
        hint=hint,
        tables_summary="\n".join(tables_summary_lines) or "（无）",
        fields_summary="\n".join(fields_summary_lines) or "（无）",
    )

    try:
        client = LLMClient()
        resp = await client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.2,
            timeout=60.0,
        )
        choices = (resp or {}).get("choices") or []
        if not choices:
            logger.warning("[spec_builder] LLM enrich: empty choices")
            return None
        content = ((choices[0] or {}).get("message") or {}).get("content") or ""
        # 容忍 ```json fence
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```\s*$", "", content)
        data = json.loads(content)
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("models"), dict):
            return None
        if not isinstance(data.get("menu_groups"), list):
            data["menu_groups"] = []
        return data
    except Exception as exc:
        logger.warning("[spec_builder] LLM enrich failed: %s", exc)
        return None


def _model_codes_for(selected_tables: list[str]) -> dict[str, str]:
    """表名 → 模型编码映射（保证唯一）。"""
    used: set[str] = set()
    out: dict[str, str] = {}
    for tbl in selected_tables:
        base = _table_to_model_code(tbl)
        candidate = base
        idx = 2
        while candidate in used:
            candidate = f"{base}_{idx}"
            idx += 1
        used.add(candidate)
        out[tbl] = candidate
    return out


def _resolve_field_meta(
    field: dict[str, Any],
    *,
    model_code: str,
    field_names_zh: dict[str, str],
    used_field_codes: set[str],
) -> dict[str, Any] | None:
    """单字段元数据。返回 None 表示该字段应跳过（内置字段）。"""
    raw_name = (field.get("name") or "").strip()
    if not raw_name or _is_builtin_field(raw_name):
        return None
    comment = (field.get("comment") or "").strip()
    cn_name = field_names_zh.get(raw_name) or _humanize_field(raw_name, comment)
    fc = safe_field_code(
        raw_name,
        model_code=model_code,
        field_name=cn_name,
        used_codes=used_field_codes,
    )
    if not fc:
        return None
    ddl = field.get("type") or ""
    return {
        "raw_name": raw_name,
        "name_zh": cn_name,
        "code": fc,
        "ddl": ddl,
        "ui_type": _ddl_to_chinese_type(ddl),
        "db_type": _ddl_to_standard_type(ddl),
        "nullable": bool(field.get("nullable", True)),
        "comment": comment,
    }


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """渲染一张 markdown table。空行时只渲染表头 + 分割行。"""
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    if not rows:
        return head + "\n" + sep
    body_lines = ["| " + " | ".join(c if c is not None else "" for c in row) + " |" for row in rows]
    return "\n".join([head, sep, *body_lines])


async def build_spec_markdown(
    *,
    db_label: str,
    app_name: str,
    app_code: str,
    hint: str,
    schemas: dict[str, dict],
    classifications: dict[str, dict],
    selected_tables: list[str],
) -> str:
    """把反向建模结果渲染成 SPEC v2 markdown。

    见模块文档对输入/输出的约定。
    """
    app_name = (app_name or "").strip() or "DB 问数应用"
    app_code = _slugify_app_code(app_code)
    db_label = (db_label or "").strip() or "未知数据库"
    hint = (hint or "").strip()

    # 过滤 selected_tables：要求 schema 存在；skip 类不展示。
    skip_count = sum(
        1 for tbl in schemas if (classifications.get(tbl) or {}).get("health") == "skip"
    )
    visible_tables: list[str] = []
    for tbl in selected_tables:
        if tbl not in schemas:
            continue
        health = (classifications.get(tbl) or {}).get("health") or "green"
        if health == "skip":
            continue
        visible_tables.append(tbl)

    model_code_map = _model_codes_for(visible_tables)

    # LLM enrich（失败走 fallback）
    enrich = await _call_llm_enrich(
        db_label=db_label, hint=hint, schemas=schemas, selected_tables=visible_tables,
    )
    llm_status = "llm"
    if not enrich:
        enrich = {"models": {}, "menu_groups": []}
        llm_status = "fallback"

    enrich_models: dict[str, Any] = enrich.get("models") or {}
    enrich_menu_groups: list[dict[str, Any]] = enrich.get("menu_groups") or []

    # 预计算每张表的字段元数据 + 中文模型名
    table_meta: dict[str, dict[str, Any]] = {}
    for tbl in visible_tables:
        schema = schemas.get(tbl) or {}
        m_code = model_code_map[tbl]
        enrich_m = enrich_models.get(tbl) or {}
        cn_name = (enrich_m.get("chinese_name") or "").strip() or _humanize_table(tbl)
        desc = (enrich_m.get("description") or "").strip()
        if not desc:
            cls = classifications.get(tbl) or {}
            desc = (cls.get("reason") or "").strip() or f"来自表 {tbl}"
        field_names_zh = enrich_m.get("field_names") or {}
        if not isinstance(field_names_zh, dict):
            field_names_zh = {}

        used_codes: set[str] = set()
        field_metas: list[dict[str, Any]] = []
        for fld in schema.get("fields") or []:
            meta = _resolve_field_meta(
                fld,
                model_code=m_code,
                field_names_zh=field_names_zh,
                used_field_codes=used_codes,
            )
            if meta is None:
                continue
            field_metas.append(meta)

        table_meta[tbl] = {
            "model_code": m_code,
            "chinese_name": cn_name,
            "description": desc,
            "fields": field_metas,
        }

    # ---------------- markdown 渲染 ----------------
    # 标题格式 `## N、名称` 严格对齐 doc_standard_detector 的 _SECTION_HEADER_RE
    # 章节名严格匹配 doc_section_splitter._SECTION_KEYWORDS（应用信息/角色列表/数据模型/权限定义）
    # 这样 detect_standard 才能给出 ≥90 分，让 ChatPage 的 upload-doc 接受。
    lines: list[str] = []
    lines.append(f"# {app_name}")
    lines.append("")

    # 1. 应用信息（required section: app_info）
    lines.append("## 一、应用信息")
    lines.append("")
    if hint:
        lines.append(hint)
    else:
        lines.append(f"基于数据库 {db_label} 的快速搭建应用。")
    lines.append("")
    lines.append(f"由 DB 问数 wizard 从 `{db_label}` 反向建模生成。")
    lines.append("")
    lines.append(_md_table(
        ["应用编码", "应用名称", "应用描述"],
        [[app_code, app_name, hint or f"基于 {db_label} 反向建模"]],
    ))
    lines.append("")

    # 2. 数据模型（required section: models）
    lines.append("## 二、数据模型")
    lines.append("")
    lines.append("### 2.1 模型清单")
    lines.append("")
    rows: list[list[str]] = []
    for tbl in visible_tables:
        meta = table_meta[tbl]
        cls = classifications.get(tbl) or {}
        health = cls.get("health") or "green"
        badge = cls.get("badge") or ""
        reason = cls.get("reason") or ""
        emoji = _HEALTH_EMOJI.get(health, "")
        badge_cell = f"{emoji} {badge}".strip()
        rows.append([
            meta["chinese_name"],
            meta["model_code"],
            str(len(meta["fields"])),
            badge_cell,
            reason,
        ])
    lines.append(_md_table(
        ["模型名", "模型编码", "字段数", "健康度", "备注"], rows,
    ))
    lines.append("")

    lines.append("### 2.2 详细字段定义")
    lines.append("")
    for tbl in visible_tables:
        meta = table_meta[tbl]
        lines.append(f"#### {meta['chinese_name']}（{meta['model_code']}）")
        lines.append("")
        if meta["description"]:
            lines.append(meta["description"])
            lines.append("")
        frows: list[list[str]] = []
        for f in meta["fields"]:
            # 列顺序要跟表头 [字段编码, 字段名称, 字段类型, 必填, 说明] 一致
            frows.append([
                f["code"],
                f["name_zh"],
                f["ui_type"],
                "否" if f["nullable"] else "是",
                f["comment"] or "",
            ])
        if not frows:
            lines.append("> 该表所有字段均为平台内置字段，已自动跳过。")
            lines.append("")
        else:
            lines.append(_md_table(
                ["字段编码", "字段名称", "字段类型", "必填", "说明"], frows,
            ))
            lines.append("")

    # 3. 表单定义（matches keyword 表单定义 → forms section）
    lines.append("## 三、表单定义")
    lines.append("")
    lines.append("### 3.1 表单列表")
    lines.append("")
    form_tables: list[str] = []
    for tbl in visible_tables:
        cls = classifications.get(tbl) or {}
        health = cls.get("health") or "green"
        flags = cls.get("flags") or []
        if health == "red":
            continue
        # yellow 关联表（m2m 中间表）不生成表单
        if health == "yellow" and "join_table" in flags:
            continue
        form_tables.append(tbl)

    form_rows: list[list[str]] = []
    form_codes: dict[str, str] = {}
    for tbl in form_tables:
        meta = table_meta[tbl]
        form_code = meta["model_code"]  # 表单编码与模型编码同名兜底
        form_codes[tbl] = form_code
        # 取最多 4 个主字段作 "主要字段" 提示
        head_fields = [f["name_zh"] for f in meta["fields"][:4]]
        form_rows.append([
            f"{meta['chinese_name']} CRUD",
            meta["model_code"],
            "模型页面",
            "、".join(head_fields) or "-",
        ])
    lines.append(_md_table(
        ["表单名", "关联模型", "类型", "主要字段"], form_rows,
    ))
    lines.append("")

    # 4. 菜单
    lines.append("## 四、菜单")
    lines.append("")
    lines.append("### 4.1 菜单结构")
    lines.append("")
    # 把 LLM 给的 menu_groups 跟 form_tables 求交集；不在 LLM 给的分组里的兜底走前缀分组
    used_in_groups: set[str] = set()
    rendered_groups: list[tuple[str, list[str]]] = []
    for grp in enrich_menu_groups:
        if not isinstance(grp, dict):
            continue
        gname = (grp.get("name") or "").strip()
        gtables = grp.get("tables")
        if not gname or not isinstance(gtables, list):
            continue
        items = [t for t in gtables if t in form_tables and t not in used_in_groups]
        if not items:
            continue
        rendered_groups.append((gname, items))
        used_in_groups.update(items)
    leftovers = [t for t in form_tables if t not in used_in_groups]
    if leftovers:
        # fallback 前缀分组
        for grp in _group_by_prefix(leftovers):
            rendered_groups.append((grp["name"], grp["tables"]))

    if not rendered_groups:
        lines.append("- 数据管理")
        lines.append("  - （暂无可用菜单）")
    else:
        for gname, items in rendered_groups:
            lines.append(f"- {gname}")
            for tbl in items:
                meta = table_meta[tbl]
                lines.append(f"  - {meta['chinese_name']} CRUD")
    lines.append("")

    # 5. 角色列表（required section: roles，表头必须有 角色编码 + 角色名称）
    lines.append("## 五、角色列表")
    lines.append("")
    lines.append(_md_table(
        ["角色编码", "角色名称", "角色描述"],
        [
            ["admin", "管理员", "应用管理员，可查看/编辑/删除全部数据"],
            ["user",  "业务员", "普通用户，默认只读"],
        ],
    ))
    lines.append("")

    # 6. 权限定义（required section: permissions，表头硬性要求 6 列）
    lines.append("## 六、权限定义")
    lines.append("")
    perm_rows: list[list[str]] = []
    for tbl in form_tables:
        meta = table_meta[tbl]
        form_name = f"{meta['chinese_name']} CRUD"
        perm_rows.append([form_name, "admin", "✓", "✓", "✓", "全部数据"])
        perm_rows.append([form_name, "user",  "✓", "",  "",  "全部数据"])
    if not perm_rows:
        # 兜底一行，让 detector 看到表存在
        perm_rows.append(["（暂无表单）", "admin", "✓", "✓", "✓", "全部数据"])
    lines.append(_md_table(
        ["表单名称", "角色编码", "可查看", "可编辑", "可删除", "数据范围"], perm_rows,
    ))
    lines.append("")

    # 7. 反向建模来源（附加 section，不影响标准度评分）
    lines.append("## 七、反向建模来源")
    lines.append("")
    lines.append(f"数据库：`{db_label}`")
    lines.append("")
    lines.append(f"表总数：{len(schemas)}")
    lines.append("")
    lines.append(f"勾选表数：{len(selected_tables)}")
    lines.append("")
    lines.append(f"跳过表数：{skip_count}（框架表 / 审计表）")
    lines.append("")
    lines.append(f"中文增强：{'LLM' if llm_status == 'llm' else 'fallback 规则版'}")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
