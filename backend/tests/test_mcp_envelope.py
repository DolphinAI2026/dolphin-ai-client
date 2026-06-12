"""test_mcp_envelope.py — MCP 公共样板设施 (信封 / 校验 / 装饰器) 单测。

锁三件事:
  1) _ok / _err 信封字段名 + 键序与现有手写 dict 等价。
  2) validate_required / @apaas_tool 必填校验语义 == 原 `if not (x.strip() and ...)`。
  3) **FastMCP 兼容性硬验证**: @apaas_tool 装饰前后, 经真实 FastMCP 实例拿到的
     工具 schema (name / parameters / description) 逐字段相等 — 这是装饰器方案
     能不能用的红线。若哪天 FastMCP 升级破坏它, 这个测试先红。
"""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp_envelope import (
    ErrorCode,
    _err,
    _ok,
    apaas_tool,
    validate_required,
)


# ─────────────────────── 1. 信封构造器 ───────────────────────


def test_ok_envelope_shape():
    """_ok 等价手写 {"ok": True, **fields}, ok 在首位。"""
    assert _ok() == {"ok": True}
    res = _ok(env_id=1, message="done")
    assert res == {"ok": True, "env_id": 1, "message": "done"}
    assert list(res.keys())[0] == "ok"


def test_err_envelope_shape():
    """_err 等价手写 {"ok": False, "error_code": code, "message": msg, **fields}。"""
    res = _err(ErrorCode.INVALID_PARAMS, "x 必填")
    assert res == {"ok": False, "error_code": "INVALID_PARAMS", "message": "x 必填"}
    # 键序: ok → error_code → message → 其余
    res2 = _err(ErrorCode.APAAS_CALL_FAILED, "失败", env_id=3)
    assert list(res2.keys()) == ["ok", "error_code", "message", "env_id"]


def test_err_matches_handwritten_legacy_dict():
    """_err 产出与迁移前手写 dict byte-equal (下游 agent 解析的就是这个)。"""
    legacy = {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id + dict_code + dict_name 都必填"}
    new = _err(ErrorCode.INVALID_PARAMS, "apaas_app_id + dict_code + dict_name 都必填")
    assert new == legacy


# ─────────────────────── 2. error_code 常量值不变 ───────────────────────


def test_error_code_values_are_strings_unchanged():
    """常量值 == 字符串字面量自身 (防有人手贱改成 enum 数字或换文案)。"""
    # 抽样几个下游在分支的关键码
    assert ErrorCode.INVALID_PARAMS == "INVALID_PARAMS"
    assert ErrorCode.NOT_IMPLEMENTED == "NOT_IMPLEMENTED"
    assert ErrorCode.APAAS_CALL_FAILED == "APAAS_CALL_FAILED"
    assert ErrorCode.RESERVED_FIELD_CODE == "RESERVED_FIELD_CODE"
    assert ErrorCode.DICT_NOT_FOUND == "DICT_NOT_FOUND"


def test_error_codes_cover_mcp_server_literals():
    """ErrorCode 常量集 ⊇ mcp_server.py 现有 error_code 字面量 — 没遗漏。

    防"加了新 error_code 字面量却忘进常量类"漂移 (拆包时其它域引用会拿不到)。
    """
    import re
    from pathlib import Path

    src = (Path(__file__).parent.parent / "app" / "mcp_server.py").read_text(encoding="utf-8")
    literals = set(re.findall(r'"error_code":\s*"([A-Z0-9_]+)"', src))
    literals |= set(re.findall(r'\berror_code\s*=\s*"([A-Z0-9_]+)"', src))
    literals |= {"FORM_PERMS_WRITE_FAILED"}  # fallback 字面量

    const_values = {
        v for k, v in vars(ErrorCode).items()
        if not k.startswith("_") and isinstance(v, str)
    }
    missing = literals - const_values
    assert not missing, f"mcp_server.py 有 error_code 字面量未进 ErrorCode 常量类: {sorted(missing)}"


# ─────────────────────── 3. 必填校验语义 ───────────────────────


def test_validate_required_all_present_returns_none():
    args = {"apaas_app_id": "app1", "dict_code": "c", "dict_name": "n"}
    assert validate_required(args, ["apaas_app_id", "dict_code", "dict_name"]) is None


def test_validate_required_blank_string_is_missing():
    """空串 / 纯空格 strip 后为空 == 缺失 (对齐原 .strip() 判空)。"""
    args = {"apaas_app_id": "  ", "dict_code": "", "dict_name": "n"}
    err = validate_required(
        args, ["apaas_app_id", "dict_code", "dict_name"],
        message="apaas_app_id + dict_code + dict_name 都必填",
    )
    assert err == {
        "ok": False,
        "error_code": "INVALID_PARAMS",
        "message": "apaas_app_id + dict_code + dict_name 都必填",
    }


def test_validate_required_none_is_missing():
    args = {"a": None, "b": "x"}
    err = validate_required(args, ["a", "b"], message="a+b 都必填")
    assert err is not None
    assert err["error_code"] == "INVALID_PARAMS"


def test_validate_required_custom_code():
    args = {"x": ""}
    err = validate_required(args, ["x"], message="x 必填", code=ErrorCode.INVALID_FIELDS)
    assert err["error_code"] == "INVALID_FIELDS"


# ─────────────────────── 4. @apaas_tool 运行时语义 ───────────────────────


def _run(coro):
    return asyncio.run(coro)


def test_apaas_tool_blocks_on_missing_required():
    """缺必填 → 装饰器直接返 _err, 不进函数体。"""
    called = {"body": False}

    @apaas_tool(required=["apaas_app_id", "dict_code"], message="apaas_app_id+dict_code 都必填")
    async def tool(env_id: int, apaas_app_id: str, dict_code: str = "") -> dict:
        called["body"] = True
        return {"ok": True}

    res = _run(tool(env_id=1, apaas_app_id="", dict_code="c"))
    assert res == {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+dict_code 都必填"}
    assert called["body"] is False, "缺必填时不应进函数体"


def test_apaas_tool_passes_when_all_present():
    @apaas_tool(required=["apaas_app_id"], message="必填")
    async def tool(env_id: int, apaas_app_id: str) -> dict:
        return {"ok": True, "got": apaas_app_id}

    res = _run(tool(env_id=1, apaas_app_id="app1"))
    assert res == {"ok": True, "got": "app1"}


def test_apaas_tool_works_with_positional_args():
    """*args/**kwargs 都能正确绑回参数名做校验。"""
    @apaas_tool(required=["apaas_app_id"], message="必填")
    async def tool(env_id: int, apaas_app_id: str) -> dict:
        return {"ok": True}

    # 位置传 — apaas_app_id 是空
    res = _run(tool(1, ""))
    assert res["ok"] is False
    # 位置传 — 齐
    res2 = _run(tool(1, "app1"))
    assert res2["ok"] is True


# ─────────────────────── 5. FastMCP schema 等价 (装饰器红线) ───────────────────────


def _fresh_mcp(name: str) -> FastMCP:
    return FastMCP(
        name,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
        json_response=True,
    )


def test_decorator_preserves_fastmcp_schema():
    """**核心验证**: 同一函数, 装饰 @apaas_tool 前后, 经 FastMCP 注册拿到的
    工具 schema (name / description / parameters) 必须逐字段相等。

    FastMCP 靠 inspect.signature(eval_str=True) + __doc__ 生成 schema;
    functools.wraps 设了 __wrapped__/__doc__, 所以装饰透明。这是装饰器方案的命脉。
    """
    mcp_base = _fresh_mcp("base")
    mcp_deco = _fresh_mcp("deco")

    @mcp_base.tool()
    async def sample_tool(
        env_id: int,
        apaas_app_id: str,
        dict_id: str,
        value_code: str,
        value_name: str,
        display_order: int = 0,
        describe: str = "",
    ) -> dict:
        """更新字典选项（改 code / name / 排序 / 颜色）。

        多行 docstring 描述, 用来确认 description 也逐字保留。
        """
        return {"ok": True}

    @mcp_deco.tool()
    @apaas_tool(
        required=["apaas_app_id", "dict_id", "value_code", "value_name"],
        message="apaas_app_id+dict_id+value_code+value_name 都必填",
    )
    async def sample_tool(  # noqa: F811 — 故意同名验证 title 也相等
        env_id: int,
        apaas_app_id: str,
        dict_id: str,
        value_code: str,
        value_name: str,
        display_order: int = 0,
        describe: str = "",
    ) -> dict:
        """更新字典选项（改 code / name / 排序 / 颜色）。

        多行 docstring 描述, 用来确认 description 也逐字保留。
        """
        return {"ok": True}

    base = mcp_base._tool_manager.list_tools()[0]
    deco = mcp_deco._tool_manager.list_tools()[0]

    assert base.name == deco.name == "sample_tool"
    assert base.description == deco.description, "docstring 描述必须逐字保留"
    assert base.parameters == deco.parameters, (
        "参数 schema (类型 / 默认 / required / title) 必须 byte-equal"
        f"\nbase={base.parameters}\ndeco={deco.parameters}"
    )


def test_decorated_tool_still_runs_through_fastmcp():
    """装饰后的工具经 FastMCP tool.run 仍能执行 (校验通过 + 函数体跑)。"""
    mcp = _fresh_mcp("run")

    @mcp.tool()
    @apaas_tool(required=["apaas_app_id"], message="apaas_app_id 必填")
    async def runnable(env_id: int, apaas_app_id: str) -> dict:
        return {"ok": True, "echo": apaas_app_id}

    tool = mcp._tool_manager.list_tools()[0]
    # 缺必填: 走装饰器短路
    blocked = asyncio.run(tool.run({"env_id": 1, "apaas_app_id": ""}, convert_result=False))
    assert blocked == {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
    # 齐: 进函数体
    okres = asyncio.run(tool.run({"env_id": 1, "apaas_app_id": "app9"}, convert_result=False))
    assert okres == {"ok": True, "echo": "app9"}
