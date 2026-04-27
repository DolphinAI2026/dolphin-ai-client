"""Spec → CodingAgent 输入桥接。

架构文档 § 2.1：BrainstormAgent emit 的 Spec envelope 是 CodingAgent 的**契约输入**，
CodingAgent 只从 Spec 读 requirement / scene_type / 配置项 / 验收点，不再做 scene_detection。

本模块两个职责：
1. `build_coding_input_from_spec(envelope)` —— 把 Spec envelope 映射成 CodingAgent 兼容的
   `ctx.input` dict（核心字段：requirement / scene_type / conversation_summary）
2. `render_spec_brief(envelope)` —— 渲染一段**结构化 Spec 摘要**，作为 prompt 段落注入
   CodingAgent 的首条 user message。让 LLM 知道"需求已被 brainstorm 结构化，重点参考 Spec"。

不直接依赖 DB / Pydantic 模型对象 —— 输入统一为 dict（envelope 从 DB JSON 或
emit_spec tool 返回都是 dict），降低耦合。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.config import settings as _settings

# Spec 场景 → project_type 映射（供 CodingAgent 的 WorkspaceManager 用）
_SCENE_TO_PROJECT_TYPE: dict[str, str] = {
    "web_component_dual": "form-component-dual",
    "web_page": "form-page",
    "mobile_page": "mobile-page",
    "backend_api": "backend-api",
    "backend_feign": "backend-api",       # feign 结构与 api 类似，MVP 共用 scaffold
    "backend_scheduled": "backend-api",   # 同上
}


def scene_to_project_type(scene_type: str) -> str:
    """把 Spec scene_type 映射到 WorkspaceManager 的 project_type"""
    return _SCENE_TO_PROJECT_TYPE.get(scene_type, "form-component-dual")


# ══════════════════════════════════════════════════════════════
# 1) Spec → ctx.input
# ══════════════════════════════════════════════════════════════

def build_coding_input_from_spec(
    envelope: dict[str, Any],
    *,
    conversation_summary: str = "",
    max_turns: Optional[int] = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 Spec envelope 翻成 CodingAgent 的 ctx.input dict。

    关键点：
    - `requirement`：用 Spec 的 **渲染摘要**（而非用户原话），让 LLM 直面结构化规格
      旧路径：pipeline 把用户原话传给 CodingAgent，LLM 自己推断。
      新路径：brainstorm 已替 LLM 做完了推断，coding 无需再猜。
    - `scene_type` / `project_type`：从 Spec 来，下游 prompts 层选 workflow 模板时用
    - `spec_envelope`：挂 raw envelope 到 input，agent 内部可进一步使用（如生成后的 validation）

    Args:
        envelope: 完整 Spec envelope dict（含 schema_version / scene_type / identity / ... / spec）
        conversation_summary: 可选历史摘要（一般空 —— brainstorm 已把对话浓缩成 Spec）
        max_turns: None 时读取 settings.coding_max_turns（默认 30）；显式传入时覆盖
        extra: 透传额外字段（如 system_prompt override）

    Returns:
        CodingAgent 构造 AgentContext 时 ctx.input 的值。
    """
    if max_turns is None:
        max_turns = _settings.coding_max_turns
    if not isinstance(envelope, dict):
        raise TypeError(f"envelope must be dict, got {type(envelope).__name__}")
    scene_type = envelope.get("scene_type") or "web_component_dual"
    intent = envelope.get("intent") or {}

    # requirement 保留"用户原话"（让 ## Task 段落聚焦用户意图，不被 Spec 内部结构掩盖）
    # Spec 的结构化细节通过 spec_brief 单独注入 prompt
    requirement_text = (
        intent.get("core_purpose")
        or intent.get("original_requirement")
        or "(missing requirement)"
    )

    result: dict[str, Any] = {
        "requirement": requirement_text,
        "conversation_summary": conversation_summary,
        "max_turns": max_turns,
        # Spec 扩展字段：CodingAgent.build_initial_user_message 检测到这些就走 Spec-驱动路径
        "scene_type": scene_type,
        "project_type": scene_to_project_type(scene_type),
        "spec_envelope": envelope,
        "spec_brief": render_spec_brief(envelope),
    }
    if extra:
        result.update({k: v for k, v in extra.items() if k not in result})
    return result


# ══════════════════════════════════════════════════════════════
# 2) Spec → Markdown 摘要（注入 prompt）
# ══════════════════════════════════════════════════════════════

def render_spec_brief(envelope: dict[str, Any]) -> str:
    """渲染 Spec envelope 为 **markdown 形式的结构化需求摘要**。

    排列优先级（LLM 先看重要字段）：
      1. 场景 + 标识（scene_type / code_name / widget_code / display_name）
      2. 核心目的 + 原始需求
      3. 验收点（acceptance_criteria）
      4. 场景特定 spec（data / config_properties / ui_sections / endpoints 等）
      5. 约束（constraints_hard / constraints_soft）
      6. 默认假设（provenance.open_questions）—— 提示 LLM "这些是 brainstorm 替用户做的默认决定"
    """
    identity = envelope.get("identity") or {}
    intent = envelope.get("intent") or {}
    spec = envelope.get("spec") or {}
    provenance = envelope.get("provenance") or {}
    scene_type = envelope.get("scene_type") or "web_component_dual"

    lines: list[str] = ["# 结构化需求（Spec v{})".format(provenance.get("version") or 1)]
    lines.append("")

    # 1. Identity
    lines.append("## 标识")
    lines.append(f"- **场景**：`{scene_type}`")
    if identity.get("code_name"):
        lines.append(f"- **code_name**：`{identity['code_name']}`")
    if identity.get("widget_code"):
        lines.append(f"- **widget_code**：`{identity['widget_code']}`")
    if identity.get("display_name"):
        lines.append(f"- **显示名**：{identity['display_name']}")
    if identity.get("description_cn"):
        lines.append(f"- **描述**：{identity['description_cn']}")
    lines.append("")

    # 2. Intent
    lines.append("## 意图")
    if intent.get("core_purpose"):
        lines.append(f"**核心目的**：{intent['core_purpose']}")
        lines.append("")
    if intent.get("original_requirement"):
        lines.append(f"**用户原话**：{intent['original_requirement']}")
        lines.append("")

    # 3. Acceptance Criteria
    acs = intent.get("acceptance_criteria") or []
    if acs:
        lines.append("## 验收点（Acceptance Criteria）")
        for i, ac in enumerate(acs, 1):
            lines.append(f"{i}. {ac}")
        lines.append("")

    # 4. 场景特定 spec
    if scene_type == "web_component_dual":
        lines.append(_render_component_spec(spec))
    elif scene_type in ("web_page", "mobile_page"):
        lines.append(_render_page_spec(spec))
    elif scene_type in ("backend_api", "backend_feign", "backend_scheduled"):
        lines.append(_render_backend_spec(spec))
    else:
        lines.append("## 场景规格")
        lines.append("```json")
        lines.append(json.dumps(spec, ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")

    # 5. Constraints
    hard = spec.get("constraints_hard") or []
    soft = spec.get("constraints_soft") or []
    if hard or soft:
        lines.append("## 约束")
        if hard:
            lines.append("**硬约束（违反必须修）**：")
            for c in hard:
                lines.append(f"- {c}")
            lines.append("")
        if soft:
            lines.append("**软约束（违反仅 warning）**：")
            for c in soft:
                lines.append(f"- {c}")
            lines.append("")

    # 6. Open Questions
    oqs = provenance.get("open_questions") or []
    if oqs:
        lines.append("## 默认假设（brainstorm 未与用户对齐的点）")
        for oq in oqs:
            q = (oq.get("question") or "").strip()
            a = (oq.get("assumed_answer") or "").strip()
            lines.append(f"- **{q}** → 假设：{a}")
        lines.append("")
        lines.append(
            "> 这些是 brainstorm agent 在没有用户明确答案时做的默认决定。"
            "实现时请尊重这些假设；如果代码层面发现假设不可行，在注释中明确说明。"
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── 分场景渲染子函数 ──

def _render_prop_validation(v: dict[str, Any] | None) -> str:
    """把 PropValidation dict 渲染为紧凑单行字符串，用于 Spec 摘要表格"""
    if not v:
        return "—"
    parts: list[str] = []
    for field, label in [
        ("min", "min"), ("max", "max"), ("step", "step"),
        ("min_length", "minLen"), ("max_length", "maxLen"),
        ("min_items", "minItems"), ("max_items", "maxItems"),
    ]:
        if v.get(field) is not None:
            parts.append(f"{label}={v[field]}")
    if v.get("pattern"):
        parts.append(f"pattern=`{v['pattern'][:30]}`")
    return ", ".join(parts) if parts else "—"


def _render_component_spec(spec: dict[str, Any]) -> str:
    """渲染 ComponentSpec 为 markdown 段落"""
    out: list[str] = ["## 组件规格"]

    data = spec.get("data") or {}
    if data:
        out.append("### 数据")
        out.append(f"- **bof_type**：`{data.get('bof_type', '?')}`")
        out.append(f"- **component_model_field**：{data.get('component_model_field') or []}")
        out.append(f"- **form_value_shape**：`{data.get('form_value_shape', '?')}`")
        if data.get("default_value") is not None:
            out.append(f"- **默认值**：`{data['default_value']}`")
        if data.get("storage_note"):
            out.append(f"- **存储说明**：{data['storage_note']}")
        out.append("")

    props = spec.get("config_properties") or []
    if props:
        out.append("### 配置项（setting.vue）")
        out.append("| key | type | label | default | required | ui_editor | is_custom | 校验 | 说明 |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for p in props:
            out.append(
                f"| `{p.get('key')}` | `{p.get('type')}` | {p.get('label', '')} | "
                f"`{p.get('default')}` | {'是' if p.get('required') else '否'} | "
                f"`{p.get('ui_editor')}` | {'是' if p.get('is_custom_editor') else '否'} | "
                f"{_render_prop_validation(p.get('validation'))} | "
                f"{(p.get('description') or '').replace('|', '\\|')} |"
            )
        out.append("")

    sr = spec.get("scenes_required") or []
    so = spec.get("scenes_optional") or []
    if sr or so:
        out.append("### 🔴 本次只生成以下 scene（未列出的 scene 一个字都别动）")
        if sr:
            out.append(f"- **必需（本次必须写业务代码的 scene）**：{', '.join(sr)}")
        if so:
            out.append(f"- **可选（可写可不写，用户未明确要求）**：{', '.join(so)}")
        not_in = [
            s for s in ("edit", "read", "ide", "list", "print", "search", "search-ide")
            if s not in sr and s not in so
        ]
        if not_in:
            out.append(
                f"- **未选（保持 scaffold 默认的 `form-component-demo-{{scene}}.vue` 原样，"
                f"对应目录的 index.js 不要改）**：{', '.join(not_in)}"
            )
        out.append("")
        out.append(
            "> ⚠️ 上面【未选】的 scene 在 scaffold 里已经有完整的 demo vue + index.js 占位，"
            "`npm run build` 可以直接跑通。你只需为【必需】scene 写新的 "
            "`form-component-{name}-{scene}.vue` 并改对应目录的 `index.js` 把 demo 改成新组件。"
            "任何未列出的 scene 文件（包括 web/ 和 mobile/ 两端）都不要 write/edit。"
        )
        out.append("")

    hooks = spec.get("platform_hooks") or {}
    if hooks:
        out.append("### 平台钩子")
        out.append(f"- in_table_supported: {hooks.get('in_table_supported', True)}")
        out.append(f"- search_enabled: {hooks.get('search_enabled', False)}")
        out.append(f"- print_enabled: {hooks.get('print_enabled', False)}")
        out.append("")

    deps = spec.get("third_party_deps") or []
    if deps:
        out.append("### 三方依赖")
        for d in deps:
            out.append(f"- {d}")
        out.append("")

    return "\n".join(out).rstrip()


def _render_page_spec(spec: dict[str, Any]) -> str:
    """渲染 PageSpec（web_page / mobile_page）"""
    out: list[str] = ["## 页面规格"]

    route = spec.get("route") or {}
    if route:
        out.append("### 路由")
        out.append(f"- router_name: `{route.get('router_name')}`")
        out.append(f"- menu_title: {route.get('menu_title')}")
        out.append("")

    if spec.get("layout"):
        out.append(f"**布局**：`{spec['layout']}`")
        out.append("")

    ds = spec.get("data_sources") or []
    if ds:
        out.append("### 数据源")
        for d in ds:
            type_ = d.get("type")
            if type_ == "api":
                out.append(
                    f"- **{d.get('name')}** (api, {d.get('method', 'GET')}) "
                    f"→ `{d.get('endpoint', '?')}`"
                )
            else:
                out.append(f"- **{d.get('name')}** ({type_})")
        out.append("")

    sections = spec.get("ui_sections") or []
    if sections:
        out.append("### UI 区块")
        for s in sections:
            custom = "（自定义）" if s.get("is_custom_type") else ""
            out.append(f"- **{s.get('name')}** — 类型 `{s.get('type')}` {custom}")
            cfg = s.get("config") or {}
            if cfg:
                out.append(f"  - config: `{json.dumps(cfg, ensure_ascii=False)[:200]}`")
        out.append("")

    deps = spec.get("third_party_deps") or []
    if deps:
        out.append("### 三方依赖")
        for d in deps:
            out.append(f"- {d}")
        out.append("")

    return "\n".join(out).rstrip()


def _render_backend_spec(spec: dict[str, Any]) -> str:
    """渲染 BackendApiSpec（api / feign / scheduled）"""
    out: list[str] = ["## 后端规格"]

    if spec.get("package_name"):
        out.append(f"**package_name**：`{spec['package_name']}`")
        out.append("")

    eps = spec.get("endpoints") or []
    if eps:
        out.append("### 接口")
        for ep in eps:
            out.append(f"- `{ep.get('method', 'GET')} {ep.get('path', '')}` — {ep.get('description', '')}")
            req = ep.get("request") or {}
            if req:
                req_txt = ", ".join(
                    f"{k}({v.get('type')}{'*' if v.get('required') else ''})"
                    for k, v in req.items()
                )
                out.append(f"  - request: {req_txt}")
        out.append("")

    tables = spec.get("mpaas_tables") or []
    if tables:
        out.append("### MpaaS 表使用")
        for t in tables:
            out.append(f"- `{t.get('name')}` ({t.get('access', 'read')})")
        out.append("")

    perms = spec.get("permissions") or []
    if perms:
        out.append("### 权限")
        for p in perms:
            out.append(f"- {p}")
        out.append("")

    return "\n".join(out).rstrip()
