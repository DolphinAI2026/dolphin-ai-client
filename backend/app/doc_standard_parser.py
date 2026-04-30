"""纯代码标准文档解析器 — 主入口

链路：
  split_sections → 各模块解析器 → 汇总 config
  失败模块记录在 failed_modules，由上层决定是否触发 LLM 修复
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.app_code import APP_CODE_RULE_TEXT, is_valid_app_code, normalize_app_code
from app.doc_section_splitter import split_sections
from app.doc_table_parser import parse_table
from app.doc_parsers import roles as roles_parser
from app.doc_parsers import dicts as dicts_parser
from app.doc_parsers import models as models_parser
from app.doc_parsers import forms as forms_parser
from app.doc_parsers import permissions as permissions_parser

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """纯代码解析结果"""
    config: Dict[str, Any] = field(default_factory=dict)
    failed_modules: set = field(default_factory=set)           # 解析失败、需 LLM 兜底的模块
    errors: List[str] = field(default_factory=list)           # 所有错误/警告
    sections_found: List[str] = field(default_factory=list)   # 检测到的章节 key

    @property
    def has_critical_failure(self) -> bool:
        """关键模块（模型）解析失败"""
        return "models" in self.failed_modules

    def to_preview(self) -> Dict[str, Any]:
        """包装成 preview 格式"""
        return {"type": "preview", "data": self.config}


def parse(text: str) -> ParseResult:
    """纯代码解析标准格式 markdown 文档

    Args:
        text: markdown 原文

    Returns:
        ParseResult
    """
    result = ParseResult()
    sections = split_sections(text)
    result.sections_found = list(sections.keys())

    # ── 1. 应用信息 ──────────────────────────────────────────
    app_name, app_code = _parse_app_info(sections.get("app_info", ""), result)

    # ── 2. 角色列表 ──────────────────────────────────────────
    roles: List[dict] = []
    if "roles" in sections:
        roles, errs = roles_parser.parse(sections["roles"])
        result.errors.extend(errs)
        if not roles:
            result.failed_modules.add("roles")
            logger.warning("角色列表解析失败")
    else:
        result.errors.append('缺少"二、角色列表"章节')
        result.failed_modules.add("roles")

    role_codes = {r["code"] for r in roles}

    # ── 3. 数据字典 ──────────────────────────────────────────
    dicts: List[dict] = []
    if "dicts" in sections:
        dicts, errs = dicts_parser.parse(sections["dicts"])
        result.errors.extend(errs)
        if not dicts:
            result.failed_modules.add("dicts")
            logger.warning("数据字典解析失败")

    # ── 4. 数据模型 ──────────────────────────────────────────
    models: List[dict] = []
    if "models" in sections:
        models, errs = models_parser.parse(sections["models"])
        result.errors.extend(errs)
        if not models:
            result.failed_modules.add("models")
            logger.warning("数据模型解析失败")
    else:
        result.errors.append('缺少"四、数据模型"章节')
        result.failed_modules.add("models")

    # ── 5. 表单配置 ──────────────────────────────────────────
    forms: List[dict] = []
    if "forms" in sections:
        forms, errs = forms_parser.parse(sections["forms"], models)
        result.errors.extend(errs)
        if not forms:
            result.failed_modules.add("forms")
            logger.warning("表单配置解析失败，保留失败状态，等待后续修复")
    else:
        # 没有表单章节，全部从模型推导
        forms = forms_parser.derive_default_forms(models)

    # ── 6. 权限配置 ──────────────────────────────────────────
    permissions: List[dict] = []
    if "permissions" in sections:
        permissions, errs = permissions_parser.parse(sections["permissions"], role_codes)
        result.errors.extend(errs)
        if not permissions:
            result.failed_modules.add("permissions")
            logger.warning("权限配置解析失败")
    else:
        result.errors.append('缺少"六、权限配置"章节')
        result.failed_modules.add("permissions")

    # ── 组装 config ───────────────────────────────────────────
    result.config = {
        "appName": app_name,
        "appCode": app_code,
        "roles": roles,
        "dicts": dicts,
        "models": models,
        "forms": forms,
        "workflows": [],
        "permissions": permissions,
    }

    return result


def _parse_app_info(section_text: str, result: ParseResult) -> tuple[str, str]:
    """解析应用信息，返回 (app_name, app_code)"""
    if not section_text:
        result.errors.append('缺少"一、应用信息"章节')
        result.failed_modules.add("app_info")
        return "未命名应用", ""

    rows = parse_table(section_text)
    if not rows:
        result.errors.append("应用信息：未找到表格")
        result.failed_modules.add("app_info")
        return "未命名应用", ""

    row = rows[0]
    app_code = row.get("应用编码", "").strip()
    app_name = row.get("应用名称", "").strip()

    # 竖排格式：| 项目 | 值 | 或 | 字段 | 内容 | 等
    # 第一列是字段名，第二列是值
    if not app_code and not app_name:
        kv: dict = {}
        headers = list(rows[0].keys())
        if len(headers) >= 2:
            key_col, val_col = headers[0], headers[1]
            for r in rows:
                k = r.get(key_col, "").strip()
                v = r.get(val_col, "").strip()
                if "编码" in k:
                    kv["应用编码"] = v
                elif "名称" in k:
                    kv["应用名称"] = v
        app_code = kv.get("应用编码", "")
        app_name = kv.get("应用名称", "")

    if not app_name:
        result.errors.append("应用信息：缺少应用名称")
        app_name = "未命名应用"
    if not app_code:
        result.errors.append("应用信息：缺少应用编码")
        return app_name, app_code

    # 规范化 appCode：AI 经常写成 snake_case 或超长，这里自动清洗成平台合法值
    if not is_valid_app_code(app_code):
        normalized = normalize_app_code(app_code)
        if normalized and normalized != app_code:
            result.errors.append(
                f"应用编码 '{app_code}' 不合规，已自动规范为 '{normalized}'。{APP_CODE_RULE_TEXT}"
            )
            app_code = normalized
        elif not normalized:
            result.errors.append(
                f"应用编码 '{app_code}' 不合规且无法自动规范化。{APP_CODE_RULE_TEXT}"
            )

    return app_name, app_code
