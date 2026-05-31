"""首次部署前扫描平台已占用的模型 code，生成冲突清单。

定位：和 `config_validator` 的本地去重不同，这里查的是**租户级**冲突
——本地 v2_config 里的模型 code 撞到平台其他应用已有 code 的情况。

只负责扫描 + 求交 + 生成 _Vn 建议。不调用 API、不改 DB，纯计算 + 一次平台查询。
应用 rename 的职责在 apply_model_code_rename()。
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, Iterable, List, Set, Tuple

logger = logging.getLogger(__name__)


# 递归遍历 config 时，遇到这些 key 就把它的值视作"模型 code 引用"进行替换
# 覆盖：跨表字段 ref.model（dict 分支处理）/ 子表 sub_code / 表单绑定 model_code / 组件 ref_model_code
_MODEL_REF_KEYS: Tuple[str, ...] = (
    "model_code",
    "modelCode",
    "ref_model_code",
    "refModelCode",
    "dataModelCode",
    "sub_code",
    "ref",  # 跨表字段：值可能是 str (code) 或 dict {"model": "xxx", "field": "yyy"}
)


async def collect_tenant_model_codes(client) -> Set[str]:
    """从平台拉租户所有模型 code。失败时返回空集合（静默退化，不阻塞部署）。"""
    try:
        rows = await client.query_all_model_codes()
        codes = {str(r.get("code") or "").strip() for r in rows if isinstance(r, dict)}
        codes.discard("")
        return codes
    except Exception as e:
        logger.warning(f"扫描租户模型 code 失败，预检将跳过：{e}")
        return set()


def _extract_model_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 v2_config 里拿出 models 列表，容错各种字段命名。"""
    models = config.get("models") or config.get("data", {}).get("models") or []
    return [m for m in models if isinstance(m, dict)]


def _get_model_code(m: Dict[str, Any]) -> str:
    return str(m.get("code") or m.get("modelCode") or "").strip()


def _get_model_name(m: Dict[str, Any]) -> str:
    return str(m.get("name") or m.get("modelName") or "").strip()


def suggest_v_suffix(code: str, taken: Set[str]) -> str:
    """为 code 生成 _Vn 后缀，避开 taken 里已有的。

    - `status` → `status_V1`；若 `status_V1` 已占，递推 `_V2`…
    - `status_V1` → `status_V2`（识别已有 _Vn 尾巴，从 n+1 起）
    """
    base = code
    start = 1
    m = re.search(r"_V(\d+)$", base)
    if m:
        start = int(m.group(1)) + 1
        base = base[: m.start()]
    for i in range(start, start + 200):
        candidate = f"{base}_V{i}"
        if candidate not in taken:
            return candidate
    # 极端兜底，理论上到不了
    return f"{base}_V{start}"


def find_model_conflicts(
    v2_config: Dict[str, Any],
    existing_codes: Set[str],
) -> List[Dict[str, Any]]:
    """求本地 v2 里 model code 与平台已有 code 的交集，每个冲突附带 _Vn 建议。

    返回：
        [{
            "resource_type": "model",
            "name": "订单",
            "original_code": "order",
            "suggested_code": "order_V1",
        }, ...]
    """
    models = _extract_model_entries(v2_config)
    local_codes = {_get_model_code(m) for m in models}
    local_codes.discard("")
    # suggested_code 可能产生新名字，这些新名字也不能和本地/远端撞
    taken: Set[str] = set(existing_codes) | local_codes
    conflicts: List[Dict[str, Any]] = []
    for m in models:
        code = _get_model_code(m)
        if code and code in existing_codes:
            suggested = suggest_v_suffix(code, taken)
            taken.add(suggested)
            conflicts.append({
                "resource_type": "model",
                "name": _get_model_name(m),
                "original_code": code,
                "suggested_code": suggested,
            })
    return conflicts


def apply_model_code_rename(
    config: Dict[str, Any],
    renames: Dict[str, str],
) -> Tuple[Dict[str, Any], int]:
    """把 {old_code: new_code} 应用到 config 里所有引用模型 code 的地方。

    覆盖：
      - models[i].code / models[i].modelCode
      - models[i].fields[*].ref.model（跨表字段）
      - models[i].fields[*].sub_code（子表）
      - forms[i].model_code / modelCode
      - forms[i].components[*].ref_model_code / refModelCode 等

    返回 (new_config, changed_count)。

    注意：depth-first 递归所有 dict/list，在预定 key 集合上命中即替换——
    字段名来自项目内既有约定，见 _MODEL_REF_KEYS。
    """
    if not renames:
        return config, 0

    new = copy.deepcopy(config)
    changed = 0

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            # models 列表元素自身 code 替换
            for key in ("code", "modelCode"):
                v = node.get(key)
                if isinstance(v, str) and v in renames:
                    node[key] = renames[v]
                    changed += 1
            # 模型引用 key
            for key in _MODEL_REF_KEYS:
                v = node.get(key)
                if isinstance(v, str) and v in renames:
                    node[key] = renames[v]
                    changed += 1
                elif isinstance(v, dict):
                    # ref = {"model": "xxx", "field": "yyy"}
                    m = v.get("model")
                    if isinstance(m, str) and m in renames:
                        v["model"] = renames[m]
                        changed += 1
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(new)
    return new, changed
