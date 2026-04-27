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
from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.iteration.spec_patch import IterationLevel, PatchOp, SpecPatch
from app.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class Ambiguity:
    """LLM 识别出的、用户消息未明确说清的字段歧义。

    出现在 RefineIntent.ambiguities 里，意味着这次 refine 会触及该字段，但用户没说
    具体值/方案。处理策略：
    - 优先：用 default 兜底，写进新 Spec 的 provenance.open_questions（不打扰用户）
    - 兜底：如果 default 缺失或不安全，发 ask_user 精准反问（必须带 target_path = path）
    """
    path: str
    """歧义字段的 Spec 路径，dot+[index] 语法（与 SpecPatch 一致）"""

    question: str
    """中文问题，**必须只关于这个 path**，禁止跨字段"""

    options: list[str] = field(default_factory=list)
    """候选值（值列表，前端展示给用户选择）"""

    default: Optional[str] = None
    """默认兜底值。非空时可不打扰用户、走 open_question 路径"""


@dataclass
class IterationClassification:
    """classify_iteration 返回 —— 既是分级，也是结构化的"修改意图"（RefineIntent）。

    旧字段（level/rationale/confidence/patch）保留作 backward-compat。新字段
    （target_paths/derived_paths/ambiguities）驱动新的 Refine Strategy Router
    （见 routes/coding_v2.py 的 _run_iterate_dispatch_task）。
    """
    level: IterationLevel
    rationale: str
    """LLM 判断依据，给用户看"""

    confidence: float = 0.0
    """0-1，LLM 对自身判断的信心"""

    patch: Optional[SpecPatch] = None
    """LLM 能精确构造 patch 时附带；否则 None。trivial 级要求必填，minor 级允许填。"""

    # ── Refine Intent（结构化修改意图）—— Phase A 新增 ── #

    target_paths: list[str] = field(default_factory=list)
    """用户消息**直接指向**的 Spec 字段路径（dot+[index] 语法）。

    例：用户说"attachmentFieldCode 应改为组件选择器" →
        ["spec.config_properties[2].ui_editor"]

    后续 brainstorm / ask_user 必须**只能**操作 target_paths ∪ derived_paths 内的字段，
    其它字段由 server 端校验拒绝越界（防止"答非所问"重问已确定字段）。
    """

    derived_paths: list[str] = field(default_factory=list)
    """LLM 推断会被联动影响的字段路径（target_paths 的"涟漪"）。

    例：把 ui_editor 改为自定义 → derived = ["spec.config_properties[2].is_custom_editor",
        "spec.config_properties[2].editor_props"]

    和 target_paths 一起组成本次 refine 的"许可范围"。
    """

    ambiguities: list[Ambiguity] = field(default_factory=list)
    """target_paths/derived_paths 内的字段中，用户没说清楚的那些。

    每条歧义带 (path, question, options, default)。处理策略：
    - default 安全 → 写进 open_questions，不打扰用户
    - default 不安全 → 发 ask_user（必须带 target_path = path）
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "patch": self.patch.to_dict() if self.patch else None,
            "target_paths": list(self.target_paths),
            "derived_paths": list(self.derived_paths),
            "ambiguities": [
                {
                    "path": a.path,
                    "question": a.question,
                    "options": list(a.options),
                    "default": a.default,
                }
                for a in self.ambiguities
            ],
        }

    @property
    def allowed_paths(self) -> list[str]:
        """target_paths ∪ derived_paths，去重保序。后续 brainstorm 的 scope 约束就用这个。"""
        seen: set[str] = set()
        out: list[str] = []
        for p in (*self.target_paths, *self.derived_paths):
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out


# ══════════════════════════════════════════════════════════════
# Prompt
# ══════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """你是 aPaaS 迭代分级助手。用户对**已经签过的 Spec** 提出修改/补充。
你的任务：**精确定位**用户想改哪些字段，输出结构化的"修改意图"。

# 核心心智

用户每次修改 = 对 Spec 树的一次**局部 patch**。你不是要重新理解组件、重新问基础问题，
而是要**像 git diff 一样**精确指出"哪些字段会变"。

# 输出 4 个关键字段

## 1. level（必填）—— 修改的"波及范围"

- **trivial** —— 改动可机械精确表达 + 你能直接构造 SpecPatch + 无任何歧义
  - 例："星数最多改 10" → set spec.config_properties[i].validation.max = 10
- **minor** —— 改动可定位到具体字段，但需要少量补充信息（user 没说清细节）
  - 例："默认值改大一点" → 知道改 default，但具体值要问 / 默认猜
- **major** —— 改动较大，需要起对话明确细节（但**仍限定在 target_paths**）
  - 例："把单选改成多选" → 涉及 ui_editor/editor_props/data_spec 多字段，需要确认细节
- **cross_scene** —— 用户要的事跨越场景（如组件改页面）→ 警告

## 2. target_paths（必填，可空数组）—— 用户消息**直接指向**的 Spec 字段

dot + [index] 语法，必须能精确定位到 Spec envelope 里的字段。

例：
- "attachmentFieldCode 应改为组件选择器" → ["spec.config_properties[2].ui_editor"]
  （要从 config_properties 里找到 key=attachmentFieldCode 的那一项）
- "默认值改成 3 星" → ["spec.config_properties[i].default"]
- "加一个 showLabel 配置" → ["spec.config_properties"]（数组追加）
- "core_purpose 应该是..." → ["intent.core_purpose"]

**关键**：target_paths 的存在意义是**约束后续 brainstorm 不要越界问其他字段**。
所以一定要精确，不要写 ["spec"] 这种过宽路径。

## 3. derived_paths（必填，可空数组）—— target_paths 的"涟漪"

target_paths 改变后，**根据规范必须联动改的其他字段**。

例：
- target = [".ui_editor"]（改成自定义 editor）
  → derived = [".is_custom_editor", ".editor_props"]（要标 custom + 配 editor 参数）
- target = [".form_value_shape"]（改成 array）
  → derived = [".bof_type", ".component_model_field", ".storage_note"]

如果想不到联动，留空数组。

## 4. ambiguities（必填，可空数组）—— 用户没说清楚的字段

每条 = {path, question, options, default}：
- path：必须在 target_paths ∪ derived_paths 内
- question：中文问题，**只问这一个字段**
- options：候选值列表（让用户选，比让用户打字好）
- default：你的兜底默认值（用户不答时用这个，记 open_question）

例：用户说"加个 selector 选附件" 但没说"是否多选" →
```json
{
  "path": "spec.config_properties[2].editor_props.multiple",
  "question": "附件选择器是否需要支持多选？",
  "options": ["单选", "多选"],
  "default": "单选"
}
```

# patch 字段（可选）

如果你**完全确定改法**且能用 set/add/remove 操作精确表达，附带 patch：
```json
"patch": {
  "operations": [
    {"op": "set", "path": "spec.config_properties[0].default", "value": "red"}
  ],
  "rationale": "改主色"
}
```
- 仅 trivial 强制要求 patch
- minor / major 也可以附带（如果你能构造） → 走快通道
- patch 的 path 必须在 target_paths ∪ derived_paths 内

# 完整输出

```json
{
  "level": "trivial" | "minor" | "major" | "cross_scene",
  "rationale": "一句话中文说明这次修改的本质",
  "confidence": 0.0~1.0,
  "target_paths": ["spec.xxx", ...],
  "derived_paths": ["spec.yyy", ...],
  "ambiguities": [{"path": "...", "question": "...", "options": [...], "default": "..."}, ...],
  "patch": { ... } | null
}
```

# 铁律

- target_paths 必须精确到字段级，不许写 ["spec"] / ["intent"] 这种宽路径
- ambiguities 中每个 path 必须在 target_paths ∪ derived_paths 内
- 严禁把"你想确认一下"的事写成 ambiguity（不是用户没说清的字段就不要列）
- cross_scene 时 target_paths/derived_paths/ambiguities/patch 都给空
- SpecPatch path 使用 dot + [index] 语法（不是 JSON-pointer /）
- 不确定时宁可升级（trivial → minor，minor → major），但**保持 target_paths 精确**"""


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

    # —— Refine Intent 字段（Phase A 新增） —— #
    target_paths = _parse_str_list(raw_obj.get("target_paths"))
    derived_paths = _parse_str_list(raw_obj.get("derived_paths"))
    ambiguities = _parse_ambiguities(
        raw_obj.get("ambiguities"),
        allowed_paths=set(target_paths) | set(derived_paths),
    )

    # —— Patch 解析（trivial / minor / major 都允许带 patch，trivial 强制） —— #
    patch: Optional[SpecPatch] = None
    patch_raw = raw_obj.get("patch")
    if isinstance(patch_raw, dict):
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
                iteration_level=level if level in (IterationLevel.TRIVIAL, IterationLevel.MINOR) else IterationLevel.MINOR,
            )

    # —— trivial 一致性兜底 —— #
    if level == IterationLevel.TRIVIAL:
        if patch is None:
            # trivial 必须有 patch，没有则降级
            level = IterationLevel.MINOR
            rationale += "（LLM 未给出可用 patch，降级到 minor）"
        elif confidence < 0.6:
            # 置信度过低 → 降级 + 丢 patch（不安全直接 apply）
            level = IterationLevel.MINOR
            patch = None
            rationale += "（confidence 过低，降级到 minor）"

    # —— cross_scene：清掉 patch（跨场景不能 patch） —— #
    if level == IterationLevel.CROSS_SCENE:
        patch = None

    return IterationClassification(
        level=level,
        rationale=rationale,
        confidence=confidence,
        patch=patch,
        target_paths=target_paths,
        derived_paths=derived_paths,
        ambiguities=ambiguities,
    )


def _parse_str_list(raw: Any) -> list[str]:
    """容忍各种格式：null / list / str。返回去重保序的字符串列表。"""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _parse_ambiguities(raw: Any, *, allowed_paths: set[str]) -> list["Ambiguity"]:
    """解析 ambiguities 数组。LLM 可能省略 default/options，宽松处理。

    强约束：每条 path 必须落在 allowed_paths 内（target ∪ derived），否则丢弃。
    （这是 Refine Intent 的核心不变量：歧义只能在用户指向的范围内。）
    """
    if not raw or not isinstance(raw, list):
        return []
    out: list[Ambiguity] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        question = str(item.get("question") or "").strip()
        if not path or not question:
            continue
        if allowed_paths and path not in allowed_paths:
            logger.warning(
                "classify: drop ambiguity with path %r outside allowed set %r",
                path, allowed_paths,
            )
            continue
        opts_raw = item.get("options")
        opts: list[str] = []
        if isinstance(opts_raw, list):
            opts = [str(o) for o in opts_raw if o is not None]
        default = item.get("default")
        default_s = str(default).strip() if default is not None else None
        out.append(Ambiguity(path=path, question=question, options=opts, default=default_s))
    return out


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
