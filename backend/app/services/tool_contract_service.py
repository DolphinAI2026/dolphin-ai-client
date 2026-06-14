"""
tool_contract_service.py — Phase 2C: 工具副作用契约元数据服务.

读 tool_registry.yaml, 为每个工具派生副作用契约:
  read_only           bool  — 不产生任何写副作用
  writes_workspace    bool  — 改本地工作区文件
  writes_apaas        bool  — 写 aPaaS 平台 (建/改模型/表单/流程/字典/权限等)
  deploys_or_publishes bool — 触发部署/上传资产库/发布/republish
  requires_confirmation bool — 执行前需用户显式确认

设计原则:
- yaml 优先: yaml 明确设的副作用字段覆盖 category 派生值
- category 派生: 无显式字段时按 category→profile 映射推导
- 铁律: deploys_or_publishes=True → requires_confirmation=True

唯一事实源仍是 backend/tool_registry.yaml; 本服务只读 + 派生, 零行为变化.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.tool_registry import load, all_tool_names

# ---------------------------------------------------------------------------
# category → 默认副作用 profile
# ---------------------------------------------------------------------------
# 每个 profile 是 (read_only, writes_workspace, writes_apaas, deploys_or_publishes)
# requires_confirmation 不在此静态表 — 用铁律 + yaml 显式字段推导
#
# 未列 category 兜底: read_only=False, 其余 False (安全侧偏保守).
_CATEGORY_PROFILES: dict[str, tuple[bool, bool, bool, bool]] = {
    # (read_only, writes_workspace, writes_apaas, deploys_or_publishes)
    "introspection":   (True,  False, False, False),
    "dev_scene":       (True,  False, False, False),
    # doc_pipeline 默认读 (parse/validate/get_template 均无写副作用)
    # 有写副作用的 execute_change_plan / generate_app_from_doc 走显式覆盖
    "doc_pipeline":    (True,  False, False, False),
    # 写 aPaaS 类
    "create":          (False, False, True,  False),
    "update":          (False, False, True,  False),
    "delete":          (False, False, True,  False),
    "configure":       (False, False, True,  False),
    "process":         (False, False, True,  False),
    # lifecycle 默认写 aPaaS; 发布/部署类有显式覆盖
    "lifecycle":       (False, False, True,  False),
    # business_event: 含读(list/get)和写(create/save/delete)
    # 读类工具用 yaml 显式 read_only=true 覆盖
    "business_event":  (False, False, True,  False),
    # skill_learning: 写本地 DB skill 库, 不写 apaas 也不写 workspace
    "skill_learning":  (False, False, False, False),
    # other / dev_workspace: 全用 yaml 显式字段, 无可靠 category 默认
    # 兜底保守: 不读 + 不写 (等 yaml 显式值覆盖)
    "other":           (False, False, False, False),
    "dev_workspace":   (False, False, False, False),
}

# 已知合法的 yaml 副作用字段 (便于测试 + 未来扩展)
SIDE_EFFECT_FIELDS = frozenset({
    "read_only",
    "writes_workspace",
    "writes_apaas",
    "deploys_or_publishes",
    "requires_confirmation",
})


def _derive_contract(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    """对单工具 meta dict 派生完整副作用契约.

    优先级: yaml 显式字段 > category 默认 profile > 兜底 False.

    铁律: deploys_or_publishes=True → requires_confirmation=True.
    """
    cat = meta.get("category", "")
    defaults = _CATEGORY_PROFILES.get(cat, (False, False, False, False))
    cat_read_only, cat_writes_ws, cat_writes_apaas, cat_deploys = defaults

    # yaml 显式副作用字段 (None = 未在 yaml 中设置)
    yaml_read_only = meta.get("read_only")          # bool | None
    yaml_writes_ws = meta.get("writes_workspace")   # bool | None
    yaml_writes_apaas = meta.get("writes_apaas")    # bool | None
    yaml_deploys = meta.get("deploys_or_publishes") # bool | None

    # 优先级规则:
    #   1. 若 yaml 显式设 read_only=true 且 yaml 未设任何写副作用字段 → 完全只读 (忽略 category 写默认)
    #   2. 若 yaml 显式设任意写副作用字段为 true → 不是 read_only
    #   3. 否则按各字段 yaml 覆盖 + category 默认合并, read_only 由是否有写副作用推导

    has_yaml_write = (
        (yaml_writes_ws is True) or
        (yaml_writes_apaas is True) or
        (yaml_deploys is True)
    )

    if yaml_read_only is True and not has_yaml_write:
        # 规则 1: yaml 明确标只读 且无写字段覆盖 → 完全只读, category 写默认清零
        read_only = True
        writes_workspace = False
        writes_apaas = False
        deploys_or_publishes = False
    else:
        # 规则 2/3: 先合并写副作用字段, 再推导 read_only
        writes_workspace = bool(yaml_writes_ws if yaml_writes_ws is not None else cat_writes_ws)
        writes_apaas = bool(yaml_writes_apaas if yaml_writes_apaas is not None else cat_writes_apaas)
        deploys_or_publishes = bool(yaml_deploys if yaml_deploys is not None else cat_deploys)

        if yaml_read_only is not None:
            # yaml 显式设了 read_only (可能 False, 也可能 True 但有写字段冲突 → 写字段优先)
            read_only = bool(yaml_read_only) and not (writes_workspace or writes_apaas or deploys_or_publishes)
        else:
            # 无 yaml read_only: 由写副作用推导
            read_only = not (writes_workspace or writes_apaas or deploys_or_publishes) and cat_read_only

    # 铁律: 部署/发布 → 必须确认
    if deploys_or_publishes:
        requires_confirmation = True
    else:
        # yaml 显式值; 无则根据 read_only 推导
        yaml_confirm = meta.get("requires_confirmation")
        if yaml_confirm is not None:
            requires_confirmation = bool(yaml_confirm)
        else:
            # read_only 不需要确认; 其余保守 False (单次细粒度写不强制)
            requires_confirmation = False

    return {
        "name": name,
        "category": cat,
        "read_only": read_only,
        "writes_workspace": writes_workspace,
        "writes_apaas": writes_apaas,
        "deploys_or_publishes": deploys_or_publishes,
        "requires_confirmation": requires_confirmation,
    }


@lru_cache(maxsize=1)
def _all_contracts() -> dict[str, dict[str, Any]]:
    """全量工具契约缓存 (跟 tool_registry.load() 生命周期同步).

    返回 {tool_name: contract_dict} 普通 dict (只读使用, 不暴露给外部 mutate).
    """
    tools = load()["tools"]
    return {name: _derive_contract(name, dict(meta)) for name, meta in tools.items()}


def clear_cache() -> None:
    """清契约缓存 (测试 / 热替场景 — 对应 tool_registry.reload())."""
    _all_contracts.cache_clear()


def tool_contract(name: str) -> dict[str, Any]:
    """返回指定工具的副作用契约 dict.

    返回字段:
        name, category, read_only, writes_workspace, writes_apaas,
        deploys_or_publishes, requires_confirmation

    若工具名不存在, 抛 KeyError (与 tool_registry.tool_meta 行为一致).
    """
    contracts = _all_contracts()
    if name not in contracts:
        raise KeyError(f"工具 {name!r} 不在 tool_registry.yaml 中")
    return contracts[name]


def requires_confirmation(name: str) -> bool:
    """快捷查询: 工具是否需要用户确认.

    agent 执行前门禁: if requires_confirmation(tool_name): ask_user_confirm(...)
    """
    return tool_contract(name)["requires_confirmation"]


def is_read_only(name: str) -> bool:
    """快捷查询: 工具是否只读."""
    return tool_contract(name)["read_only"]


def all_contracts() -> dict[str, dict[str, Any]]:
    """返回全量工具契约 {tool_name: contract_dict}.

    调用方不应 mutate 返回值 (dict 非只读 proxy, 但语义上只读).
    """
    return dict(_all_contracts())


def contracts_by_flag(
    *,
    read_only: bool | None = None,
    writes_workspace: bool | None = None,
    writes_apaas: bool | None = None,
    deploys_or_publishes: bool | None = None,
    requires_confirmation: bool | None = None,
) -> list[str]:
    """按副作用标志过滤工具名列表 (None = 不过滤该字段).

    用法示例:
        deploy_tools = contracts_by_flag(deploys_or_publishes=True)
        read_tools   = contracts_by_flag(read_only=True)
    """
    filters: dict[str, bool] = {}
    if read_only is not None:
        filters["read_only"] = read_only
    if writes_workspace is not None:
        filters["writes_workspace"] = writes_workspace
    if writes_apaas is not None:
        filters["writes_apaas"] = writes_apaas
    if deploys_or_publishes is not None:
        filters["deploys_or_publishes"] = deploys_or_publishes
    if requires_confirmation is not None:
        filters["requires_confirmation"] = requires_confirmation

    result = []
    for name, c in _all_contracts().items():
        if all(c[k] == v for k, v in filters.items()):
            result.append(name)
    return sorted(result)
