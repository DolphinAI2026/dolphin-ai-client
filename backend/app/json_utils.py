"""JSON 工具函数

提供后端常见 JSON 处理模式的统一入口，避免重复代码。
"""

from __future__ import annotations

import json
from typing import Any


def loads_if_str(value: Any, default: Any = None) -> Any:
    """当 value 是字符串时反序列化，否则原样返回。

    用于统一后端常见模式：
        json.loads(x) if isinstance(x, str) else x

    用法：
        config = loads_if_str(app.config_preview)
        actions = loads_if_str(plan.actions, default=[])

    参数：
        value: 可能已是 dict/list 也可能是 JSON 字符串的值。
        default: value 为 None 时返回的兜底值。

    返回：
        - value 为 None 且 default 不为 None 时返回 default
        - value 为 str 时返回 json.loads(value)
        - 其他情况原样返回 value
    """
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value
