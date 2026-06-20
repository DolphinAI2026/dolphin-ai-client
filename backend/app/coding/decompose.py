"""多端请求分解为 N 个 aPaaS 单扩展产物的计划解析 + LLM 调用。

源自招聘系统 dogfood:多端/多页请求不该塞单页或拒绝,而是分解成多个独立产物。
parse_decomposition 纯函数(可单测);decompose 加一次 LLM 调用 + 失败回落 None(永不更糟)。
"""
from __future__ import annotations

import json
from typing import Optional, TypedDict


class Artifact(TypedDict):
    name: str
    side: str          # "admin" | "user"
    scene: str         # 单产物 scene 值
    sub_request: str   # 聚焦自然语言, 喂给一次首轮 run_coding_pipeline


def parse_decomposition(
    raw_json: str, available_scenes: set[str], max_artifacts: int = 4
) -> Optional[list[Artifact]]:
    """解析/校验 LLM 分解输出。非法/不值得分解(<2 有效项)→ None。"""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    raw_arts = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(raw_arts, list):
        return None
    out: list[Artifact] = []
    for a in raw_arts:
        if not isinstance(a, dict):
            continue
        scene = str(a.get("scene") or "").strip()
        sub = str(a.get("sub_request") or "").strip()
        if scene not in available_scenes or not sub:
            continue
        out.append(Artifact(
            name=str(a.get("name") or sub[:20]).strip(),
            side=str(a.get("side") or "admin").strip(),
            scene=scene, sub_request=sub,
        ))
        if len(out) >= max_artifacts:
            break
    return out if len(out) >= 2 else None
