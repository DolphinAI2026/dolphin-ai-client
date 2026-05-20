"""DB 问数 wizard 用到的 LLM prompt 模板。

注意：所有 prompt 输出格式都是 JSON，调用方负责解析 + fallback。
"""

from __future__ import annotations

# enrich：把反向建模的英文表 → 中文模型名 + 中文字段名 + 菜单分组
ENRICH_PROMPT = """\
你是一个低代码平台的 SPEC 文档助手。下面是从客户 MySQL 数据库反向建模出来的表清单：

业务背景：{hint}
数据库：{db_label}

表清单（英文表名 - 字段数）：
{tables_summary}

每张表的字段（英文字段名 - 数据库类型 - DB comment）：
{fields_summary}

请基于业务背景和字段名/comment 推断每张表的中文模型名、模型描述（不超过 30 字）、
以及每个字段的中文字段名（comment 已是中文就直接用 comment）。同时把语义相近的表
分组成菜单（如 `agent_*` 一组、`knowledge_*` 一组、单独表归 "其他"）。

请严格输出 JSON（不要 markdown 代码块，不要额外说明）：
{{
  "models": {{
    "<英文表名>": {{
      "chinese_name": "<中文模型名>",
      "description": "<中文描述，不超过 30 字>",
      "field_names": {{
        "<英文字段名>": "<中文字段名>"
      }}
    }}
  }},
  "menu_groups": [
    {{"name": "<分组中文名>", "tables": ["<英文表名>", ...]}}
  ]
}}
"""


def build_enrich_prompt(
    *,
    db_label: str,
    hint: str,
    tables_summary: str,
    fields_summary: str,
) -> str:
    """渲染 enrich prompt。fields_summary 太长时调用方应自行截断。"""
    return ENRICH_PROMPT.format(
        db_label=db_label,
        hint=hint or "（无）",
        tables_summary=tables_summary,
        fields_summary=fields_summary,
    )
