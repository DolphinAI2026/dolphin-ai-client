"""aPaaS 表单权限原子操作(operations 层)。

收口 generator_v2 / step_executor 间漂移的权限相关函数,使两条 0-1 生成路径
(一把梭 run_complete_generation / 分步 execute_*)共享单一实现,杜绝"修一侧
漏另一侧"的漂移(历史上权限 payload 修复只落 step_executor 侧)。

逐个函数收口,canonical 取两侧中行为更正确/更鲁棒的一份(见各函数 docstring)。
"""

from __future__ import annotations


def _parse_permission_ops(op: object) -> set[str]:
    """把权限规则的 op 字段解析成操作集合。

    canonical = step_executor 版(严格超集):
    - str(常见情形): 按逗号拆分、去空白、丢空 —— 与旧 generator_v2 版逐字等价。
    - list/tuple/set: 逐项取用 —— 旧 generator_v2 版对非 str 一律返回 {"all"},
      会丢掉真实 ops(bug);本版正确保留。
    - 其它类型: 回退 {"all"}。
    """
    if isinstance(op, str):
        raw_ops = op.replace(" ", "").split(",") if "," in op else [op]
    elif isinstance(op, (list, tuple, set)):
        raw_ops = list(op)
    else:
        raw_ops = ["all"]
    return {str(item).strip() for item in raw_ops if str(item).strip()}
