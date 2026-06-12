"""下拉/单选/多选组件 ↔ 平台字典绑定的共享原子工具。

generator_v2（一把梭 codegen）与 step_executor（分步执行）两条路径都要把表单的
选择类组件绑定到平台字典选项。两边各自维护了一份「按组件解析字典 code」的实现，
且已漂移：

  - generator_v2._bind_dict_on_component 在 b14a434d（下拉绑字典改用 spec 组件权威
    dict 引用）里加了「优先用组件自带 comp.dictCode/dict，经 dict_codes 翻译成平台
    dictionaryCode」的逻辑；
  - step_executor._lookup_component_dict_code 没同步——它读到组件自带 dict code 后
    直接 `lookup.get(direct, direct)` 返回，**不经 dict_codes 翻译**。当组件携带的是
    逻辑 dict code（需 dict_codes → 平台 code 翻译）时，step 路径会返回未翻译的逻辑
    code，落不进 dict_id_map → 下拉漏绑（这正是 b14a434d 想根治、但只修了 generator_v2
    一侧的同一个 bug）。

本模块把「按组件解析平台字典 code」收敛成单一实现 resolve_component_dict_code，
两条路径共用，保证翻译/兜底语义一致。
"""
from __future__ import annotations

from typing import Dict, List, Optional


def _component_lookup_keys(component: dict) -> List[str]:
    """组件可用于在 dict_lookup 中查字典 code 的候选键（去重保序）。

    顺序：modelField → model_field → code → field_code → label → name。
    与 generator_v2._component_dict_lookup_keys / step_executor._component_lookup_keys
    历史实现逐字一致，收敛到此。
    """
    keys: List[str] = []
    for value in (
        component.get("modelField"),
        component.get("model_field"),
        component.get("code"),
        component.get("field_code"),
        component.get("label"),
        component.get("name"),
    ):
        text = str(value or "").strip()
        if text and text not in keys:
            keys.append(text)
    return keys


def _component_own_dict_ref(component: dict) -> str:
    """读取组件自身声明的（逻辑或平台）字典 code 引用。

    覆盖 spec 组件（dict/dictCode/dict_code/dictionaryCode）与已落库组件
    （dictionarySelectConfig.dictionaryCode）两种形态。
    """
    for key in ("dict", "dictCode", "dict_code", "dictionaryCode"):
        value = str(component.get(key) or "").strip()
        if value:
            return value
    select_config = component.get("dictionarySelectConfig")
    if isinstance(select_config, dict):
        return str(select_config.get("dictionaryCode") or "").strip()
    return ""


def resolve_component_dict_code(
    component: dict,
    dict_lookup: Dict[str, str],
    dict_codes: Optional[Dict[str, str]] = None,
    dict_id_map: Optional[Dict[str, str]] = None,
) -> str:
    """解析单个组件应绑定的平台字典 dictionaryCode；解析不到返回 ""。

    优先级（与 generator_v2 b14a434d 修复后的语义一致）：
      1) 组件自带的权威 dict 引用（comp.dict/dictCode/...）—— spec 生成时写在组件上，
         经 dict_codes 翻译成平台 dictionaryCode（dict_codes 缺键/为空时按原值）。
      2) 兜底：按 modelField / code / label 等组件键在 dict_lookup 里查。

    dict_id_map（可选）：若提供，则把它当作「平台已存在字典 code 集合」做有效性闸门——
    第 1 步翻译出的 code 不在其中时，不早返回，而是继续走第 2 步兜底，尽量绑上。
    不提供时只要求非空。这让 step 路径也拿到 generator_v2 的「直绑无效则回落键查」行为，
    严格更优（绑上更多，不会更少）。
    """
    codes = dict_codes or {}

    def _valid(code: str) -> bool:
        if not code:
            return False
        if dict_id_map is None:
            return True
        return code in dict_id_map

    own_ref = _component_own_dict_ref(component)
    if own_ref:
        translated = str(codes.get(own_ref, own_ref) or "").strip()
        if _valid(translated):
            return translated

    for key in _component_lookup_keys(component):
        candidate = str(dict_lookup.get(key, "") or "").strip()
        if _valid(candidate):
            return candidate

    return ""


__all__ = [
    "_component_lookup_keys",
    "_component_own_dict_ref",
    "resolve_component_dict_code",
]
