"""Shared low-code application code rules."""
from __future__ import annotations

import re

APP_CODE_MAX_LENGTH = 17
APP_CODE_RULE_TEXT = "应用编码只能输入小写字母、中划线和数字；必须以小写字母开头；最多 17 个字符。"
APP_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,16}$")


def is_valid_app_code(code: str | None) -> bool:
    return bool(APP_CODE_PATTERN.fullmatch(str(code or "").strip()))


def normalize_app_code(candidate: str | None) -> str:
    code = str(candidate or "").strip().lower()
    code = re.sub(r"[_\s]+", "-", code)
    code = re.sub(r"[^a-z0-9-]", "", code)
    code = re.sub(r"-+", "-", code).strip("-")
    if not code:
        return ""
    if not code[0].isalpha():
        code = f"app-{code}"
    code = code[:APP_CODE_MAX_LENGTH].rstrip("-")
    return code if is_valid_app_code(code) else ""


def coerce_app_code(candidate: str | None, fallback: str = "app-builder") -> str:
    return normalize_app_code(candidate) or normalize_app_code(fallback) or "app-builder"
