"""Draft 流程统一 structured error 格式。

所有暴露给 agent 的 draft 工具失败时都返回这个结构：

    {
      "ok": false,
      "level": "freeform" | "partial" | "platform_error" | "conflict" | "invalid_patch" | "not_found",
      "errors": [{"code": "...", "msg": "...", "fix": "...", ...}],
      "retriable": bool
    }

agent 直接把 errors[].msg 转述给用户，不自己判断格式问题，不自己重试。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List


# ── 错误等级 ──────────────────────────────────────────────────
LEVEL_FREEFORM = "freeform"            # 文档完全不符合 6 章节标准，拒收
LEVEL_PARTIAL = "partial"              # 章节齐但有警告，落 draft 但提示
LEVEL_PLATFORM_ERROR = "platform_error"  # 调 aPaaS 失败
LEVEL_CONFLICT = "conflict"            # app_code / model_code 冲突
LEVEL_INVALID_PATCH = "invalid_patch"  # patch action 不合法（目标不存在/类型错误）
LEVEL_NOT_FOUND = "not_found"          # draft_id / app_id 不存在


# ── 错误码（常用） ────────────────────────────────────────────
class ErrorCode:
    # 文档格式
    MISSING_SECTION = "MISSING_SECTION"
    TABLE_COLUMN_MISMATCH = "TABLE_COLUMN_MISMATCH"
    DOC_MODULE_PARSE_FAILED = "DOC_MODULE_PARSE_FAILED"
    INVALID_APP_CODE = "INVALID_APP_CODE"
    INVALID_MODEL_CODE = "INVALID_MODEL_CODE"
    INVALID_FIELD_CODE = "INVALID_FIELD_CODE"
    DUPLICATE_CODE = "DUPLICATE_CODE"

    # 资源冲突
    APP_CODE_TAKEN = "APP_CODE_TAKEN"
    MODEL_CODE_TAKEN = "MODEL_CODE_TAKEN"

    # patch
    PATCH_TARGET_NOT_FOUND = "PATCH_TARGET_NOT_FOUND"
    PATCH_OP_UNSUPPORTED = "PATCH_OP_UNSUPPORTED"
    PATCH_FIELD_INVALID = "PATCH_FIELD_INVALID"

    # 平台
    PLATFORM_API_FAILED = "PLATFORM_API_FAILED"
    DEPLOY_FAILED = "DEPLOY_FAILED"

    # 资源不存在
    DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
    APP_NOT_FOUND = "APP_NOT_FOUND"


@dataclass
class StructuredError:
    code: str
    msg: str
    fix: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"code": self.code, "msg": self.msg}
        if self.fix:
            d["fix"] = self.fix
        if self.extra:
            d.update(self.extra)
        return d


def err_response(
    level: str,
    errors: List[StructuredError],
    retriable: bool = False,
    **extra,
) -> dict:
    """构造统一的失败返回值。"""
    return {
        "ok": False,
        "level": level,
        "errors": [e.to_dict() for e in errors],
        "retriable": retriable,
        **extra,
    }


def single_err(
    level: str,
    code: str,
    msg: str,
    fix: Optional[str] = None,
    retriable: bool = False,
    **extra,
) -> dict:
    """单条错误的快捷方式。"""
    return err_response(
        level,
        [StructuredError(code=code, msg=msg, fix=fix)],
        retriable=retriable,
        **extra,
    )
