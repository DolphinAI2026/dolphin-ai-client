"""SpecPatch —— 对已有 Spec envelope 做增量变更的结构化描述。

设计取舍（架构文档 § 6.6）：
- 用简化 JSON-Patch 风格（RFC 6902 子集）：op / path / value
- 仅支持 set / add / remove（MVP 够用；move/copy/test 留到有需要再加）
- path 用 `.` 分隔属性，`[i]` 索引数组（不用 /）—— 对 LLM 更友好，调试更直观

示例：
    {"op": "set",    "path": "spec.config_properties[0].default", "value": 10}
    {"op": "add",    "path": "spec.config_properties",            "value": {...}}
    {"op": "remove", "path": "spec.config_properties[2]"}

应用策略：
- 不直接 mutate 原 envelope，返回新 dict（deep copy）
- 路径不存在按 op 决定：set/remove → raise；add → 对 parent 为 array 时 append
- 应用后的 envelope 会更新 provenance：version+=1、parent_version=base.version、
  created_by=mixed（用户 iterate 触发，但 patch 由 agent 产生）
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class IterationLevel(str, Enum):
    """架构文档 § 6.6 的 4 档分级"""
    TRIVIAL = "trivial"          # 明确小改 → 直接 patch + coding
    MINOR = "minor"              # 模糊小改 → 1 轮反问 + patch + coding
    MAJOR = "major"              # 重大改动 → 完整 brainstorm
    CROSS_SCENE = "cross_scene"  # 跨场景 → 警告用户新建工作区


# ══════════════════════════════════════════════════════════════
# PatchOp 定义
# ══════════════════════════════════════════════════════════════

OpType = Literal["set", "add", "remove"]


@dataclass
class PatchOp:
    """单个 patch 操作"""
    op: OpType
    path: str
    """dot-notation 路径，例：`identity.display_name` / `spec.config_properties[0].default`"""

    value: Any = None
    """set/add 时的新值；remove 忽略"""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"op": self.op, "path": self.path}
        if self.op != "remove":
            d["value"] = self.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PatchOp":
        op = d.get("op")
        if op not in ("set", "add", "remove"):
            raise ValueError(f"unsupported op: {op}")
        return cls(op=op, path=str(d.get("path", "")), value=d.get("value"))


@dataclass
class SpecPatch:
    """一组 patch 操作 + 元数据"""
    base_spec_id: str
    operations: list[PatchOp] = field(default_factory=list)
    rationale: str = ""
    """LLM 产出时附带的变更说明（给用户看的）"""

    user_instruction: str = ""
    """触发本 patch 的用户原话"""

    iteration_level: IterationLevel = IterationLevel.TRIVIAL
    """分级（trivial/minor/major） —— 记录元信息，非 TRIVIAL 时不应直接走 patch 路径"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_spec_id": self.base_spec_id,
            "operations": [op.to_dict() for op in self.operations],
            "rationale": self.rationale,
            "user_instruction": self.user_instruction,
            "iteration_level": self.iteration_level.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SpecPatch":
        level_raw = d.get("iteration_level") or "trivial"
        try:
            level = IterationLevel(level_raw)
        except ValueError:
            level = IterationLevel.TRIVIAL
        return cls(
            base_spec_id=str(d.get("base_spec_id") or ""),
            operations=[PatchOp.from_dict(o) for o in d.get("operations") or []],
            rationale=str(d.get("rationale") or ""),
            user_instruction=str(d.get("user_instruction") or ""),
            iteration_level=level,
        )


# ══════════════════════════════════════════════════════════════
# 路径解析
# ══════════════════════════════════════════════════════════════

_PATH_PART_RE = re.compile(r"^(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)(?:\[(?P<idx>\d+)\])?$")
_INDEX_RE = re.compile(r"\[(\d+)\]")


def _parse_path(path: str) -> list[tuple[str, list[int]]]:
    """把 'a.b[0].c[2][1]' 解析成 [('a', []), ('b', [0]), ('c', [2, 1])]"""
    if not path:
        raise ValueError("path 不能为空")
    result: list[tuple[str, list[int]]] = []
    parts = path.split(".")
    for raw in parts:
        name_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)", raw)
        if not name_match:
            raise ValueError(f"path 段不合法: {raw!r}")
        name = name_match.group(1)
        # 后面是否跟 [i][j] 等
        rest = raw[len(name):]
        indexes = [int(m) for m in _INDEX_RE.findall(rest)]
        # 校验 rest 是纯 [数字] 的拼接
        reconstructed = "".join(f"[{i}]" for i in indexes)
        if rest != reconstructed:
            raise ValueError(f"path 段后缀不合法: {raw!r}")
        result.append((name, indexes))
    return result


def _walk_to_parent(envelope: dict[str, Any], path: str) -> tuple[Any, Any]:
    """走到 path 指向的"parent, key"。

    返回 (parent_container, last_key)：
    - parent_container: dict 或 list
    - last_key: str（parent 是 dict）或 int（parent 是 list）

    若中间节点不存在，抛 KeyError。
    """
    parts = _parse_path(path)
    node: Any = envelope
    for i, (name, indexes) in enumerate(parts):
        is_last = (i == len(parts) - 1) and not indexes
        # 先拿到 name 对应的值
        if not isinstance(node, dict):
            raise KeyError(f"无法在非 dict 上访问 .{name}（当前类型 {type(node).__name__}）")
        if is_last:
            return node, name
        if name not in node:
            raise KeyError(f"路径 {path} 中 `{name}` 不存在")
        node = node[name]
        # 再应用 index 链
        for j, idx in enumerate(indexes):
            is_last_idx = (i == len(parts) - 1) and (j == len(indexes) - 1)
            if not isinstance(node, list):
                raise KeyError(f"路径 {path}：`{name}` 不是数组，无法 [{idx}]")
            if idx < 0 or idx >= len(node):
                raise KeyError(f"路径 {path}：index {idx} 越界（长度 {len(node)}）")
            if is_last_idx:
                return node, idx
            node = node[idx]
    raise KeyError(f"路径 {path} 解析异常")


# ══════════════════════════════════════════════════════════════
# 应用逻辑
# ══════════════════════════════════════════════════════════════

class PatchApplyError(ValueError):
    """patch 应用失败"""


def _apply_one(envelope: dict[str, Any], op: PatchOp) -> None:
    """就地应用单个 op（调用方 deepcopy 后传入）"""
    if op.op == "set":
        try:
            parent, key = _walk_to_parent(envelope, op.path)
        except KeyError as e:
            raise PatchApplyError(f"set {op.path}: {e}")
        if isinstance(parent, list):
            parent[key] = op.value  # type: ignore[index]
        else:
            parent[key] = op.value  # type: ignore[index]
        return

    if op.op == "add":
        # add 的语义：
        # - 若 path 指向 array：append value（value 也可以是单值；插入末尾）
        # - 若 path 指向 dict 的不存在 key：插入
        # - 若 path 指向 dict 的已存在 key：报错（用 set）
        try:
            parent, key = _walk_to_parent(envelope, op.path)
        except KeyError as e:
            raise PatchApplyError(f"add {op.path}: {e}")
        if isinstance(parent, dict):
            target = parent.get(key)
            if isinstance(target, list):
                target.append(op.value)
                return
            if key in parent:
                raise PatchApplyError(
                    f"add {op.path}: 目标已存在且非数组（用 set 替代 add）"
                )
            parent[key] = op.value
            return
        # parent 是 list、key 是 int：在该索引处插入
        if isinstance(parent, list) and isinstance(key, int):
            parent.insert(key, op.value)
            return
        raise PatchApplyError(f"add {op.path}: 无法处理")

    if op.op == "remove":
        try:
            parent, key = _walk_to_parent(envelope, op.path)
        except KeyError as e:
            raise PatchApplyError(f"remove {op.path}: {e}")
        if isinstance(parent, list):
            del parent[key]  # type: ignore[arg-type]
        else:
            if key not in parent:
                raise PatchApplyError(f"remove {op.path}: key 不存在")
            del parent[key]
        return

    raise PatchApplyError(f"未知 op: {op.op}")


def apply_patch(
    envelope: dict[str, Any],
    patch: SpecPatch,
    *,
    bump_version: bool = True,
) -> dict[str, Any]:
    """把 SpecPatch 应用到 envelope，返回新 envelope（deepcopy）。

    Args:
        bump_version: True 时更新 provenance.version / parent_version / created_by
    """
    if patch.iteration_level not in (IterationLevel.TRIVIAL, IterationLevel.MINOR):
        raise PatchApplyError(
            f"iteration_level={patch.iteration_level.value} 的 patch 不应直接 apply —— "
            "major 和 cross_scene 必须走完整 brainstorm"
        )

    result = copy.deepcopy(envelope)
    for i, op in enumerate(patch.operations):
        try:
            _apply_one(result, op)
        except PatchApplyError as e:
            raise PatchApplyError(f"op #{i} ({op.op} {op.path}) 失败: {e}")

    if bump_version:
        prov = result.setdefault("provenance", {})
        base_version = int(prov.get("version") or 1)
        prov["parent_version"] = base_version
        prov["version"] = base_version + 1
        # 用户触发的 patch —— 记录为 mixed（agent 产 patch + 用户指令驱动）
        prov["created_by"] = "mixed"
        # spec_id 交由持久化层生成新 id；这里清掉旧的避免混淆
        result["spec_id"] = ""

    return result


def validate_path(path: str) -> bool:
    """供 LLM 调试 —— 判断 path 语法合法（不检查是否存在）"""
    try:
        _parse_path(path)
        return True
    except ValueError:
        return False
