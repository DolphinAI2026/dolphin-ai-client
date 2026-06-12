"""共享字典绑定解析层 (operations.dict_binding) 单测 + 分步路径漏绑 bug 回归。

背景: 下拉绑字典「优先用组件自带权威 dict 引用、经 dict_codes 翻译成平台 code」的修复
(commit b14a434d) 当时只落到 generator_v2 一侧；step_executor 的平行实现
_lookup_component_dict_code 读到组件自带 dict code 后直接返回, **漏了 dict_codes 翻译**——
组件携带逻辑 dict code(需翻译成平台 code)时返回未翻译值, 落不进 dict_id_map → 下拉漏绑。

本批把解析收敛进 operations.dict_binding.resolve_component_dict_code, 两条路径共用。
下面既测共享原子, 也测 step 路径委托后翻译生效(分步路径补齐同一个 bug)。
"""
from app.operations.dict_binding import (
    _component_lookup_keys,
    _component_own_dict_ref,
    resolve_component_dict_code,
)
from app.step_executor import _lookup_component_dict_code


# --- 共享原子: resolve_component_dict_code ---

def test_resolve_translates_component_dict_ref_via_dict_codes():
    """核心 bug: 组件自带逻辑 dict code, 必须经 dict_codes 翻译成平台 dictionaryCode。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "化学体系", "dict": "LOGICAL_CHEM"}
    dict_codes = {"LOGICAL_CHEM": "PLATFORM_CHEM"}
    dict_id_map = {"PLATFORM_CHEM": "id-1"}

    code = resolve_component_dict_code(comp, {}, dict_codes, dict_id_map)

    assert code == "PLATFORM_CHEM", "组件逻辑 dict code 必须翻译成平台 code, 否则落不进 dict_id_map"


def test_resolve_prefers_own_ref_over_label_lookup():
    """组件自带 dict 引用优先于「字典名==label」兜底(名字不对也能绑)。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "化学体系", "dictCode": "DICT_CHEM"}
    # label 兜底映射故意指向别的 code, 验证 own_ref 优先
    dict_lookup = {"化学体系": "WRONG_CODE", "电池化学体系": "DICT_CHEM"}
    dict_id_map = {"DICT_CHEM": "id-2", "WRONG_CODE": "id-x"}

    code = resolve_component_dict_code(comp, dict_lookup, {}, dict_id_map)

    assert code == "DICT_CHEM"


def test_resolve_falls_back_to_lookup_keys_when_no_own_ref():
    """组件无自带 dict 引用时, 按 modelField/code/label 在 lookup 里查(兜底不回归)。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "状态", "modelField": "customer.status"}
    dict_lookup = {"customer.status": "customer_status", "状态": "order_status"}
    dict_id_map = {"customer_status": "idc", "order_status": "ido"}

    code = resolve_component_dict_code(comp, dict_lookup, {}, dict_id_map)

    assert code == "customer_status", "应按精确键 modelField 命中, 不被同名 label 错绑"


def test_resolve_skips_invalid_own_ref_and_uses_valid_lookup():
    """组件自带 dict 引用翻译后不在 dict_id_map 时, 继续走键查找拿有效 code(不早返回)。"""
    comp = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": "化学体系",
        "modelField": "battery.chemistry",
        "dict": "STALE_REF",  # 平台不存在
    }
    dict_lookup = {"battery.chemistry": "PLATFORM_CHEM"}
    dict_id_map = {"PLATFORM_CHEM": "id-9"}  # STALE_REF 不在

    code = resolve_component_dict_code(comp, dict_lookup, {}, dict_id_map)

    assert code == "PLATFORM_CHEM"


def test_resolve_returns_empty_when_nothing_resolvable():
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "未知字段"}
    assert resolve_component_dict_code(comp, {}, {}, {"X": "i"}) == ""


def test_resolve_without_id_map_is_lenient_but_still_translates():
    """不传 dict_id_map 时退化为「非空即可」, 但翻译仍生效(用于建表前 stamping)。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "化学体系", "dict": "LOGICAL_CHEM"}
    dict_codes = {"LOGICAL_CHEM": "PLATFORM_CHEM"}

    code = resolve_component_dict_code(comp, {}, dict_codes)  # 无 dict_id_map

    assert code == "PLATFORM_CHEM"


# --- 辅助原子 ---

def test_component_lookup_keys_order_and_dedup():
    comp = {"modelField": "m.f", "code": "f", "label": "L", "name": "L"}
    keys = _component_lookup_keys(comp)
    assert keys == ["m.f", "f", "L"]  # 保序去重, name 与 label 重复被去掉


def test_component_own_dict_ref_reads_select_config_fallback():
    comp = {"dictionarySelectConfig": {"dictionaryCode": "from_config"}}
    assert _component_own_dict_ref(comp) == "from_config"


# --- step 路径委托后翻译生效(分步路径补齐 b14a434d) ---

def test_step_lookup_translates_logical_dict_code():
    """step_executor._lookup_component_dict_code 经共享实现后, 逻辑 code 也翻译成平台 code。
    历史本地实现读到组件自带 dict 后 lookup.get(code, code) 直接返回逻辑 code → 漏绑。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "化学体系", "dict": "LOGICAL_CHEM"}
    dict_codes = {"LOGICAL_CHEM": "PLATFORM_CHEM"}
    dict_id_map = {"PLATFORM_CHEM": "id-1"}

    code = _lookup_component_dict_code(comp, {}, dict_codes, dict_id_map)

    assert code == "PLATFORM_CHEM"


def test_step_lookup_backward_compatible_two_arg_call():
    """旧签名(只传 component, lookup)仍可用: 无 dict_codes/dict_id_map 时退化为非空即返回。"""
    comp = {"componentType": "FORM_SELECT_INPUT_SINGLE", "label": "状态", "modelField": "customer.status"}
    lookup = {"customer.status": "customer_status"}

    assert _lookup_component_dict_code(comp, lookup) == "customer_status"
