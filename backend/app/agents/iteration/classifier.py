"""迭代分级 —— 独立轻量 LLM 调用，判定用户在 DONE 后的新消息该怎么处理。

架构文档 § 6.6：
- 独立 LLM 调用（非主 agent 工具）：因为 trivial 场景占 60-70%，走快通道省 2x 时间 + 3x 成本
- 分 4 档：trivial / minor / major / cross_scene
- trivial 级可直接让 LLM 顺便产出 SpecPatch

LLM 不可用（测试、环境变量没配）时，走启发式 fallback。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.agents.iteration.spec_patch import IterationLevel, PatchOp, SpecPatch
from app.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class IterationClassification:
    """classify_iteration 返回"""
    level: IterationLevel
    rationale: str
    """LLM 判断依据，给用户看"""

    confidence: float = 0.0
    """0-1，LLM 对自身判断的信心"""

    patch: Optional[SpecPatch] = None
    """trivial 级时 LLM 会顺便产 SpecPatch；minor/major 为 None"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "patch": self.patch.to_dict() if self.patch else None,
        }


# ══════════════════════════════════════════════════════════════
# Prompt
# ══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """你是 aPaaS 迭代分级助手。用户在**已完成的**智能开发对话里发了新消息，
你要判断该消息属于以下 4 档哪一档：

1. **trivial** —— 明确的小修改，不需要反问、不需要改动结构：
   - 例："主色改成红色" / "最多星数改成 10" / "去掉 print 场景"
   - 你**直接**在响应里给 SpecPatch 操作，CodingAgent 按 patch 重跑

2. **minor** —— 模糊的小修改，需要 1 轮反问才能确定细节：
   - 例："弄漂亮一点" / "能不能再精简一点"
   - 不给 patch，brainstorm 反问后再决定

3. **major** —— 重大改动（新增 / 删除 / 语义重写）：
   - 例："加一个备注字段" / "把组件改成多选"
   - 必须走完整的 brainstorm 反问流程

4. **cross_scene** —— 用户要做的事**跨场景**（从组件变页面、从页面变接口）：
   - 例：当前是 web_component_dual，用户说"把它改成一个管理页面"
   - 警告用户这应该**新建工作区**

# 判断原则

- 能精确指到某字段的改动 → trivial 优先
- 涉及"新增配置项/字段" → major（改配置数组也算，因为影响 UX）
- 用户原话很模糊（"优化"/"更好"/"精简"）→ minor
- scene_type 明显要变 → cross_scene

# 输出

必须返回纯 JSON，结构：
```json
{
  "level": "trivial" | "minor" | "major" | "cross_scene",
  "rationale": "一句话中文说明",
  "confidence": 0.0~1.0,
  "patch": {  // 仅 trivial 必填，其他档填 null
    "operations": [
      {"op": "set", "path": "spec.config_properties[0].default", "value": "red"}
    ],
    "rationale": "改主色"
  }
}
```

**重要**：
- SpecPatch 的 path 使用 **dot + [index]** 语法（不是 JSON-pointer /）
- op 只允许 set / add / remove
- trivial 且给 patch 时：confidence 应 ≥ 0.75，否则降为 minor
- 不确定时宁可升级（trivial → minor，minor → major）"""


def _build_user_prompt(user_message: str, spec_envelope: dict[str, Any]) -> str:
    scene = spec_envelope.get("scene_type") or "?"
    identity = spec_envelope.get("identity") or {}
    intent = spec_envelope.get("intent") or {}
    spec = spec_envelope.get("spec") or {}

    # 简化的 spec 摘要给 LLM（避免 context 太大）
    summary_parts = [
        f"scene_type: {scene}",
        f"code_name: {identity.get('code_name', '')}",
        f"display_name: {identity.get('display_name', '')}",
        f"core_purpose: {intent.get('core_purpose', '')}",
    ]
    # 列出配置项 key+default
    cps = spec.get("config_properties") or []
    if cps:
        cp_lines = [
            f"  - {cp.get('key')}({cp.get('type', '?')}): {cp.get('default')}"
            for cp in cps
        ]
        summary_parts.append("config_properties:\n" + "\n".join(cp_lines))
    # 场景相关字段（简化）
    if "scenes_required" in spec:
        summary_parts.append(f"scenes_required: {spec['scenes_required']}")
    if "route" in spec:
        summary_parts.append(f"route: {spec['route']}")
    if "endpoints" in spec:
        summary_parts.append(f"endpoints: {[e.get('path') for e in spec['endpoints']]}")

    return (
        f"## 当前 Spec 摘要\n{chr(10).join(summary_parts)}\n\n"
        f"## 用户新消息\n{user_message.strip()}\n\n"
        "请判断级别并输出纯 JSON。"
    )


# ══════════════════════════════════════════════════════════════
# 启发式 fallback（LLM 不可用或出错时）
# ══════════════════════════════════════════════════════════════

_TRIVIAL_HINTS = [
    r"改\s*(?:成|为)", r"换\s*(?:成|为)", r"调\s*(?:到|成)",
    r"最(大|多|小|少)", r"默认值", r"默认颜色", r"默认星数",
]
_CROSS_SCENE_HINTS_COMPONENT = ["改成页面", "变成页面", "改成接口", "变成接口"]
_CROSS_SCENE_HINTS_PAGE = ["改成组件", "变成组件"]
_MAJOR_HINTS = ["加一个", "增加", "新增", "再加", "删除", "不要了"]
_MINOR_HINTS = ["漂亮", "好看", "精简", "优化", "体验", "美观", "好用"]


def classify_heuristic(user_message: str, spec_envelope: dict[str, Any]) -> IterationClassification:
    """纯规则分级。用于 LLM 不可用或单测场景。"""
    msg = user_message.strip()
    scene = spec_envelope.get("scene_type") or ""

    if scene.startswith("web_component") and any(h in msg for h in _CROSS_SCENE_HINTS_COMPONENT):
        return IterationClassification(
            IterationLevel.CROSS_SCENE,
            "启发式：组件场景但要改成页面/接口",
            confidence=0.6,
        )
    if scene.startswith("web_page") and any(h in msg for h in _CROSS_SCENE_HINTS_PAGE):
        return IterationClassification(
            IterationLevel.CROSS_SCENE,
            "启发式：页面场景但要改成组件",
            confidence=0.6,
        )
    if any(h in msg for h in _MAJOR_HINTS):
        return IterationClassification(
            IterationLevel.MAJOR, "启发式：有新增/删除关键词", confidence=0.5,
        )
    if any(h in msg for h in _MINOR_HINTS):
        return IterationClassification(
            IterationLevel.MINOR, "启发式：模糊修饰词，需反问确认", confidence=0.5,
        )
    if any(re.search(h, msg) for h in _TRIVIAL_HINTS):
        # 启发式无法产出 patch —— 还是返回 minor 让 brainstorm 收紧细节
        return IterationClassification(
            IterationLevel.MINOR,
            "启发式：看起来是小改，但无法自动产 patch，降为 minor 让 brainstorm 确认",
            confidence=0.4,
        )
    # 兜底
    return IterationClassification(
        IterationLevel.MAJOR,
        "启发式：无法分类，保守走 major",
        confidence=0.3,
    )


# ══════════════════════════════════════════════════════════════
# LLM 分级
# ══════════════════════════════════════════════════════════════

def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """从 LLM 返回的文本里抽取第一段 JSON（容忍代码块）"""
    if not text:
        return None
    # 去掉常见 markdown 代码块包装
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    # 找第一个 { 到最后一个 }
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(candidate[start: end + 1])
    except Exception:
        return None


def _parse_classification(
    raw_obj: dict[str, Any],
    *,
    base_spec_id: str,
    user_message: str,
) -> IterationClassification:
    level_raw = str(raw_obj.get("level") or "").strip()
    try:
        level = IterationLevel(level_raw)
    except ValueError:
        # LLM 返回了未知级别，保守升级到 major
        level = IterationLevel.MAJOR

    rationale = str(raw_obj.get("rationale") or "").strip() or "(LLM 未提供理由)"
    try:
        confidence = float(raw_obj.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    patch: Optional[SpecPatch] = None
    patch_raw = raw_obj.get("patch")
    if level == IterationLevel.TRIVIAL and isinstance(patch_raw, dict):
        ops_raw = patch_raw.get("operations") or []
        parsed_ops: list[PatchOp] = []
        for op_obj in ops_raw:
            if not isinstance(op_obj, dict):
                continue
            try:
                parsed_ops.append(PatchOp.from_dict(op_obj))
            except Exception as e:
                logger.warning("classify: skip bad patch op %r: %s", op_obj, e)
        if parsed_ops:
            patch = SpecPatch(
                base_spec_id=base_spec_id,
                operations=parsed_ops,
                rationale=str(patch_raw.get("rationale") or rationale),
                user_instruction=user_message,
                iteration_level=IterationLevel.TRIVIAL,
            )
        else:
            # trivial 但没 patch → 降为 minor（LLM 没完成职责，让 brainstorm 接手）
            level = IterationLevel.MINOR
            rationale += "（LLM 未给出可用 patch，降级到 minor）"

    # trivial 但 LLM 没给 patch（patch_raw 是 None 或不是 dict）→ 降级
    if level == IterationLevel.TRIVIAL and patch is None:
        level = IterationLevel.MINOR
        rationale += "（LLM 未给出可用 patch，降级到 minor）"

    # 置信度过低的 trivial → 降级
    if level == IterationLevel.TRIVIAL and confidence < 0.6:
        level = IterationLevel.MINOR
        patch = None
        rationale += "（confidence 过低，降级到 minor）"

    return IterationClassification(
        level=level,
        rationale=rationale,
        confidence=confidence,
        patch=patch,
    )


async def classify_iteration(
    *,
    user_message: str,
    spec_envelope: dict[str, Any],
    llm_client: Optional[LLMClient] = None,
    model: Optional[str] = None,
) -> IterationClassification:
    """主入口 —— 调 LLM 做分级。LLM 不可用或解析失败 → 启发式 fallback。

    Args:
        llm_client: 可选；不传或调用失败时走 heuristic
        model: 覆盖 llm_client 的默认 model
    """
    if llm_client is None:
        return classify_heuristic(user_message, spec_envelope)

    try:
        raw = await llm_client.chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(user_message, spec_envelope)},
            ],
            model=model or llm_client.model,
            max_tokens=2000,
            temperature=0.1,
        )
    except Exception as e:
        logger.warning("classify_iteration LLM call failed, fallback heuristic: %s", e)
        fallback = classify_heuristic(user_message, spec_envelope)
        fallback.rationale = f"(LLM 调用失败，走启发式): {fallback.rationale}"
        return fallback

    # 解析
    content = ""
    try:
        content = raw["choices"][0]["message"]["content"] or ""
    except Exception:
        content = ""
    obj = _extract_json(content)
    if not obj:
        logger.warning("classify_iteration: LLM 返回无 JSON，走启发式: %r", content[:200])
        fallback = classify_heuristic(user_message, spec_envelope)
        fallback.rationale = f"(LLM 返回无 JSON，走启发式): {fallback.rationale}"
        return fallback

    return _parse_classification(
        obj,
        base_spec_id=str(spec_envelope.get("spec_id") or ""),
        user_message=user_message,
    )
