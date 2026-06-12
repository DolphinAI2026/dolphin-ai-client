"""MCP 工具公共样板设施 — 信封 / 校验 / 身份解析收口。

mcp_server.py 当前 10k 行 / 114 个 @mcp.tool, 三类逐工具复制的样板:
  ① 身份解析   `tid, uid = _resolve_identity(tenant_id, user_id)`         (~37 处)
  ② 必填校验   `if not (x.strip() and y.strip()): return {"ok": False, ...}` (~51 处)
  ③ ok/error 信封 手写 dict (`{"ok": True/False, "error_code": "...", ...}`)  (~340 处)

本模块把这三类样板收口成可复用设施, 作为后续按域拆包 (dict / model / form /
process / role / workspace …) 的公共地基。**严格不改任何对外行为**:

  - `_ok` / `_err` 返回的 dict 字段名 / 错误文案逐字保持下游 agent 现在解析的样子。
  - `ErrorCode` 常量的字符串值一个都不改 — 下游 agent 在按 error_code 分支 (见
    [[agent_hallucinates_token_expired]]: ok=False 时读 error_code 决定动作), 改值=破坏契约。
  - `@apaas_tool` 装饰器用 functools.wraps 完整保留原函数签名 + 注解, 这样 FastMCP
    (靠 inspect.signature(eval_str=True) + docstring 生成工具 schema) 拿到的
    name / parameters / description 跟未装饰时逐字段相等 (见
    tests/test_mcp_envelope.py::test_decorator_preserves_fastmcp_schema 验证)。

新工具规范见 mcp_server.py 文件头注释。
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any


# ─────────────────────── error_code 常量收口 ───────────────────────
#
# 全量盘点 mcp_server.py 现有 error_code 字面量 (grep 派生, 保字符串值不变)。
# 下游 agent 按 error_code 分支, **任何值都不能改** — 只收口成常量便于引用 + 防拼写漂移。
# 语义相近 / 重复的码在注释里标出 (别合并别改值, 仅提示后续拆包时留意)。


class ErrorCode:
    """mcp_server.py 工具返回的 error_code 字符串常量。

    用法: `_err(ErrorCode.INVALID_PARAMS, "...")`。
    值 = 现有字面量, 逐字不变 (下游 agent 在解析)。
    """

    # ── 通用参数 / 校验 ──────────────────────────────────────
    INVALID_PARAMS = "INVALID_PARAMS"            # 最常见 (~51 处): 必填字段空
    INVALID_UPDATES = "INVALID_UPDATES"
    INVALID_FIELDS = "INVALID_FIELDS"
    INVALID_OPTIONS = "INVALID_OPTIONS"
    INVALID_ROLES = "INVALID_ROLES"
    INVALID_RULES = "INVALID_RULES"
    INVALID_STAGES = "INVALID_STAGES"
    INVALID_STATUS = "INVALID_STATUS"
    INVALID_PATTERN = "INVALID_PATTERN"
    INVALID_PERMISSION = "INVALID_PERMISSION"
    INVALID_ROLE_ITEM = "INVALID_ROLE_ITEM"
    INVALID_RULE_ITEM = "INVALID_RULE_ITEM"
    INVALID_CLASSIFICATION = "INVALID_CLASSIFICATION"
    INVALID_OBJECT_TYPE = "INVALID_OBJECT_TYPE"
    INVALID_RESOURCE_TYPE = "INVALID_RESOURCE_TYPE"
    INVALID_RESOURCE_ID = "INVALID_RESOURCE_ID"
    INVALID_ROLE_ID = "INVALID_ROLE_ID"
    INVALID_RECORD_ID = "INVALID_RECORD_ID"
    INVALID_PROCESS_ID = "INVALID_PROCESS_ID"
    INVALID_ENV_ID = "INVALID_ENV_ID"
    INVALID_MENU_TYPE = "INVALID_MENU_TYPE"
    INVALID_JOB_TYPE = "INVALID_JOB_TYPE"
    INVALID_EVENT_TYPE = "INVALID_EVENT_TYPE"
    INVALID_TRIGGER_TYPE = "INVALID_TRIGGER_TYPE"
    INVALID_CHOOSE_TYPE = "INVALID_CHOOSE_TYPE"
    INVALID_VALIDATOR_LIST = "INVALID_VALIDATOR_LIST"
    INVALID_STYLE_CONFIG = "INVALID_STYLE_CONFIG"
    INVALID_STYLE_PAYLOAD = "INVALID_STYLE_PAYLOAD"        # 近义: 与 INVALID_STYLE_CONFIG 语义相近
    INVALID_COMPONENT_BEHAVIOR = "INVALID_COMPONENT_BEHAVIOR"
    INVALID_DOCUMENT_NUMBER_RULES = "INVALID_DOCUMENT_NUMBER_RULES"
    INVALID_DEFAULT_VALUE = "INVALID_DEFAULT_VALUE"
    INVALID_DEFINITION_JSON = "INVALID_DEFINITION_JSON"
    INVALID_PYTHON_CODE = "INVALID_PYTHON_CODE"
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"               # 近义: 与 NOT_A_ZIP / INVALID_FILE_PATH 同族
    INVALID_FILE_PATH = "INVALID_FILE_PATH"
    INVALID_FILE_NAME = "INVALID_FILE_NAME"

    # ── app / id 标识 ────────────────────────────────────────
    INVALID_APP_ID = "INVALID_APP_ID"                     # 近义: ai-builder 内部 app_id
    INVALID_APAAS_APP_ID = "INVALID_APAAS_APP_ID"         # 近义: apaas 侧 app_id (不同来源, 别合并)
    INVALID_PROJECT_NAME = "INVALID_PROJECT_NAME"
    INVALID_APAAS_USER_ID = "INVALID_APAAS_USER_ID"
    MISSING_ARTIFACT_ID = "MISSING_ARTIFACT_ID"
    MISSING_OBJECT_IDS = "MISSING_OBJECT_IDS"

    # ── not found ────────────────────────────────────────────
    NOT_FOUND = "NOT_FOUND"
    APP_NOT_FOUND = "APP_NOT_FOUND"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    SCENE_NOT_FOUND = "SCENE_NOT_FOUND"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
    FORM_NOT_FOUND = "FORM_NOT_FOUND"
    FORM_TEMPLATE_NOT_FOUND = "FORM_TEMPLATE_NOT_FOUND"
    COMPONENT_NOT_FOUND = "COMPONENT_NOT_FOUND"
    DICT_NOT_FOUND = "DICT_NOT_FOUND"
    PROCESS_NOT_FOUND = "PROCESS_NOT_FOUND"
    PROCESS_DEFINITION_NOT_FOUND = "PROCESS_DEFINITION_NOT_FOUND"
    EDGE_NOT_FOUND = "EDGE_NOT_FOUND"
    APAAS_USER_NOT_FOUND = "APAAS_USER_NOT_FOUND"

    # ── 字典 / 模型字段域 (试点迁移域用到的码) ───────────────
    RESERVED_FIELD_CODE = "RESERVED_FIELD_CODE"
    SELECT_FIELD_NEEDS_DICTIONARY = "SELECT_FIELD_NEEDS_DICTIONARY"
    FIELD_MISSING_NAME_OR_CODE = "FIELD_MISSING_NAME_OR_CODE"
    NO_MODEL_FIELDS = "NO_MODEL_FIELDS"
    NO_BOUND_MODEL = "NO_BOUND_MODEL"
    DATA_SELECTOR_NEEDS_REF = "DATA_SELECTOR_NEEDS_REF"

    # ── apaas 调用失败族 ─────────────────────────────────────
    APAAS_CALL_FAILED = "APAAS_CALL_FAILED"
    APAAS_CLIENT_ERROR = "APAAS_CLIENT_ERROR"
    APAAS_SAVE_FAILED = "APAAS_SAVE_FAILED"
    APAAS_TOOL_ERROR = "APAAS_TOOL_ERROR"
    APAAS_UPLOAD_REJECTED = "APAAS_UPLOAD_REJECTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # ── 流程 (process) 域 ────────────────────────────────────
    PROCESS_EXISTS = "PROCESS_EXISTS"
    PROCESS_EDGES_EMPTY = "PROCESS_EDGES_EMPTY"
    PROCESS_DETAIL_INVALID = "PROCESS_DETAIL_INVALID"
    PROCESS_BINDING_MISSING = "PROCESS_BINDING_MISSING"
    PROCESS_RULE_SAVE_FAILED = "PROCESS_RULE_SAVE_FAILED"
    PROCESS_DEFINITION_TRANSLATE_FAILED = "PROCESS_DEFINITION_TRANSLATE_FAILED"
    RULE_TRANSLATE_FAILED = "RULE_TRANSLATE_FAILED"
    EDGE_RULE_KEY_MISSING = "EDGE_RULE_KEY_MISSING"

    # ── 部署 / 上线 / 构建 域 ────────────────────────────────
    APP_NOT_DEPLOYED = "APP_NOT_DEPLOYED"
    ENV_NOT_READY = "ENV_NOT_READY"
    DEPLOY_FAILED = "DEPLOY_FAILED"
    DEPLOY_RECORDS_QUERY_FAILED = "DEPLOY_RECORDS_QUERY_FAILED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    CREATE_FAILED = "CREATE_FAILED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    WRITE_FAILED = "WRITE_FAILED"
    QUERY_FAILED = "QUERY_FAILED"
    TRANSLATE_FAILED = "TRANSLATE_FAILED"
    LINT_FAILED_BEFORE_PUBLISH = "LINT_FAILED_BEFORE_PUBLISH"
    STILL_GENERATING = "STILL_GENERATING"
    # build/upload 失败按关键词分类 (_classify_publish_failure):
    MVN_AUTH_FAIL = "MVN_AUTH_FAIL"
    MVN_DEPS_RESOLVE_FAIL = "MVN_DEPS_RESOLVE_FAIL"
    MVN_PROFILE_NOT_FOUND = "MVN_PROFILE_NOT_FOUND"
    MVN_JDK_MISMATCH = "MVN_JDK_MISMATCH"
    MVN_COMPILE_FAIL = "MVN_COMPILE_FAIL"
    MVN_BUILD_FAILURE = "MVN_BUILD_FAILURE"
    FE_COMPILE_FAIL = "FE_COMPILE_FAIL"
    BUILD_FAILED = "BUILD_FAILED"

    # ── workspace / 自开发 域 ────────────────────────────────
    WRONG_WS_TYPE = "WRONG_WS_TYPE"
    NOT_A_ZIP = "NOT_A_ZIP"
    ZIP_TOO_LARGE = "ZIP_TOO_LARGE"
    EMPTY_FILES = "EMPTY_FILES"
    EMPTY_EDITS = "EMPTY_EDITS"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    EMPTY_KIT_IDS = "EMPTY_KIT_IDS"
    FILES_CONFLICT = "FILES_CONFLICT"
    FILE_READ_ERROR = "FILE_READ_ERROR"
    GLOB_FAILED = "GLOB_FAILED"
    GREP_FAILED = "GREP_FAILED"
    COMMAND_FAILED = "COMMAND_FAILED"
    B64_DECODE_FAILED = "B64_DECODE_FAILED"
    SELF_DEV_MENU_EXISTS = "SELF_DEV_MENU_EXISTS"
    PARTIAL_ATTACH_FAILED = "PARTIAL_ATTACH_FAILED"

    # ── 菜单 / tab 域 ────────────────────────────────────────
    MENU_NOT_FORM = "MENU_NOT_FORM"
    MENUS_LOAD_FAILED = "MENUS_LOAD_FAILED"
    NO_DEFAULT_TAB = "NO_DEFAULT_TAB"
    TAB_ID_AUTO_RESOLVE_FAILED = "TAB_ID_AUTO_RESOLVE_FAILED"

    # ── 权限 域 ──────────────────────────────────────────────
    FORM_PERMS_LOAD_FAILED = "FORM_PERMS_LOAD_FAILED"
    FORM_PERMS_WRITE_FAILED = "FORM_PERMS_WRITE_FAILED"

    # ── 身份 / 租户 ──────────────────────────────────────────
    USER_MISMATCH = "USER_MISMATCH"
    TENANT_MISMATCH = "TENANT_MISMATCH"

    # ── 杂项 ─────────────────────────────────────────────────
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    SPEC_TOO_SHORT = "SPEC_TOO_SHORT"


# ─────────────────────── ok / error 信封构造器 ───────────────────────


def _ok(**fields: Any) -> dict[str, Any]:
    """成功信封。等价于手写 `{"ok": True, **fields}`。

    用法: `return _ok(env_id=env_id, message="...")`
    `ok` 永远是第一个键, 其余字段按传入顺序跟在后面 (与现有手写 dict 一致, 下游解析无所谓键序)。
    """
    result: dict[str, Any] = {"ok": True}
    result.update(fields)
    return result


def _err(code: str, message: str, **fields: Any) -> dict[str, Any]:
    """错误信封。等价于手写 `{"ok": False, "error_code": code, "message": message, **fields}`。

    用法: `return _err(ErrorCode.INVALID_PARAMS, "apaas_app_id 必填", env_id=env_id)`
    键序: ok → error_code → message → 其余 fields, 与现有手写 dict 一致。
    """
    result: dict[str, Any] = {"ok": False, "error_code": code, "message": message}
    result.update(fields)
    return result


# ─────────────────────── 声明式必填校验 ───────────────────────


def _missing_required(args: dict[str, Any], required: list[str]) -> list[str]:
    """返回 required 里"空字符串/None/strip 后为空"的字段名列表 (按 required 顺序)。

    与现有手写 `if not (x.strip() and y.strip())` 等价: str 走 strip 判空,
    其它类型 (int 等) 走 falsy 判定 (注意: int 0 视为缺失 — 但现有必填校验都是 str 字段,
    env_id 这类 int 从不进 required, 行为对齐)。
    """
    missing: list[str] = []
    for name in required:
        value = args.get(name)
        if value is None:
            missing.append(name)
        elif isinstance(value, str):
            if not value.strip():
                missing.append(name)
        elif not value:
            missing.append(name)
    return missing


def validate_required(
    args: dict[str, Any],
    required: list[str],
    *,
    message: str | None = None,
    code: str = ErrorCode.INVALID_PARAMS,
) -> dict[str, Any] | None:
    """手动调用版必填校验 (装饰器搞不定 FastMCP 兼容时的退化路径)。

    缺必填时返回 `_err(...)` 信封, 全齐时返回 None。

    用法:
        err = validate_required(locals(), ["apaas_app_id", "dict_code"], message="...")
        if err:
            return err

    message 不传时自动拼 `"<a>+<b> 都必填"` — 但现有工具文案各异 (有的 "都必填" 有的
    "必填全填"), 迁移时**显式传 message 保持原文案**, 别依赖默认。
    """
    missing = _missing_required(args, required)
    if not missing:
        return None
    if message is None:
        message = "+".join(required) + " 都必填"
    return _err(code, message)


# ─────────────────────── @apaas_tool 装饰器 ───────────────────────
#
# FastMCP 兼容性: 经验证 (tests/test_mcp_envelope.py) functools.wraps 足以让
# inspect.signature(eval_str=True) 透过 __wrapped__ 拿到原函数签名 + 注解,
# 加上 __doc__ 被 wraps 复制, FastMCP 生成的 name/parameters/description 跟未装饰
# 逐字段相等。无需显式拷 __signature__ (wraps 已设 __wrapped__, signature 默认 follow)。
#
# 装饰器只做"声明式必填校验" (样板②): 校验失败直接返 _err 信封、不进函数体。
# 身份解析 (样板①) 仍走 _resolve_identity helper — 装饰器注入身份会让函数体依赖
# "魔法局部变量", 反而降低可读性, 且本身只是一行换一行, 不收口。


def apaas_tool(
    *,
    required: list[str] | None = None,
    message: str | None = None,
    code: str = ErrorCode.INVALID_PARAMS,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """声明式必填校验装饰器, 用在 @mcp.tool() **下方**(更贴近函数)。

        @mcp.tool()
        @apaas_tool(required=["apaas_app_id", "dict_code", "dict_name"],
                    message="apaas_app_id + dict_code + dict_name 都必填")
        async def create_apaas_app_dict(env_id: int, apaas_app_id: str, ...): ...

    缺必填时直接返回 `_err(code, message)` 信封, 不进函数体 (等价原 `if not (...): return {...}`)。

    **关键约束** (FastMCP schema 不变):
      - functools.wraps 保留 __name__ / __doc__ / __wrapped__ / __module__ / 注解,
        FastMCP 经 inspect.signature(eval_str=True) 看到的仍是原函数签名。
      - 装饰器**不增删参数**, 用 inspect.signature 把 *args/**kwargs 绑回原参数名做校验。

    若哪天 FastMCP 升级破坏兼容 (schema 漂移), 退化用 validate_required(...) 手动调即可。
    """
    required_list = list(required or [])

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if required_list:
                try:
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    call_args = dict(bound.arguments)
                except TypeError:
                    # 绑定失败 (理论上 FastMCP 已按 schema 校验过) — 不挡, 让原函数自己抛
                    call_args = {**kwargs}
                err = validate_required(call_args, required_list, message=message, code=code)
                if err is not None:
                    return err
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
