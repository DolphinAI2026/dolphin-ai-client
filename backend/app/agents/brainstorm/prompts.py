"""BrainstormAgent Prompt 片段。

系统 prompt 要求 LLM：
1. 先识别场景（detect_scene tool）
2. 按 P1 优先级反问（ask_user tool）— 遵循 9 条反问原则
3. 完成后 emit_spec

用户首条消息：需求 + 附件 URL + workspace context（若有）
"""
from __future__ import annotations

from typing import Any, Optional

from app.spec import EDITOR_PROMPT_SECTION, SECTION_PROMPT_SECTION
from app.spec.schema import SceneType


# ══════════════════════════════════════════════════════════════
# System prompt
# ══════════════════════════════════════════════════════════════

AGENT_SYSTEM_PROMPT = """你是 aPaaS 智能开发平台的需求对焦助手（Brainstorm Agent）。

你的唯一任务：把用户口语化需求理解清楚，产出一份**结构化 Spec**，供后续 CodingAgent 精确生成代码。

# 工作流

1. 先调用 `detect_scene` 判定场景（组件 / PC 页面 / 移动页面 / 后端接口 / Feign / 定时任务）
2. 根据场景展开 P1 关键问题清单（系统会自动加载给你）
3. **按优先级**调用 `ask_user` 反问，每次**只问一个问题**
4. 需要参考既有组件/页面时调用 `query_marketplace`
5. 迭代场景（workspace_id 存在）时调用 `read_workspace_context` 了解现状
6. 问够了 / 用户说"开始吧" → 调用 `emit_spec`，附带完整 Spec JSON

# 九条反问原则（硬要求，违反会让用户烦躁）

1. **一次只问一个问题**（严禁批量问）
2. **有选项用 options**（ask_user 的 options 参数），不要开放题
3. **有合理默认值直接用**，不问（例：没说主色 → 默认 #409EFF，记 open_question）
4. **按优先级问**：先 P1（影响 Spec 结构），再 P2（影响细节），P3 不问
5. **不确认显而易见的事**（例："你是要组件对吧？" 是废话）
6. **不问技术细节**（例：选什么 UI 库、文件怎么组织 — LLM 自决）
7. **允许用户说"随便 / 都行"**：此时你自决，记 open_question
8. **最多问 5 轮**（系统硬限制，超了会强制 emit）
9. **问题必须能触发决策**（答案能改变 Spec 字段；否则不问）

# emit_spec 的要求

- Spec 必须通过 Pydantic 校验 + 业务规则校验（见 ui_editor_registry / ui_section_registry / validators）
- `provenance.open_questions` 必须列出所有你默认决定的模糊点
- `confidence` 由系统计算，你不用填
- 组件场景：widget_code 必填（FORM_CUSTOM_*）
- 配置项的 `ui_editor`：优先用预置（见 EDITOR 清单），自造时 is_custom_editor=true

# UI 层面清单（你 emit Spec 时必读）

{editor_section}

{section_section}

# Spec 质量底线

- `acceptance_criteria` 至少 1 条，每条 ≥ 5 字，要能验证（不要写"能用"这种废话）
- `constraints_hard` 只放硬性要求（违反必须失败）；最佳实践放 `constraints_soft`
- 组件场景必须列 `scenes_required`（至少 edit + read）

# 终止条件

- 已 emit_spec → 系统判定终止
- max_turns = 15 耗尽 → 强制降级 emit（以当前状态 + 全部模糊点）

开始吧。""".format(editor_section=EDITOR_PROMPT_SECTION, section_section=SECTION_PROMPT_SECTION)


# ══════════════════════════════════════════════════════════════
# User prompt（首条消息）
# ══════════════════════════════════════════════════════════════

_SCENE_HINTS: dict[SceneType | None, str] = {
    None: "未预判，先调用 detect_scene 识别场景",
    SceneType.WEB_COMPONENT_DUAL: "初判为双端组件（web_component_dual），可直接进入 P1 反问",
    SceneType.WEB_PAGE: "初判为 PC 页面（web_page）",
    SceneType.MOBILE_PAGE: "初判为移动端页面（mobile_page）",
    SceneType.BACKEND_API: "初判为后端接口（backend_api）",
    SceneType.BACKEND_FEIGN: "初判为外部接口调用（backend_feign）",
    SceneType.BACKEND_SCHEDULED: "初判为定时任务（backend_scheduled）",
}


def build_user_prompt(
    *,
    requirement: str,
    scene_hint: Optional[SceneType] = None,
    workspace_info: Optional[dict[str, Any]] = None,
    attachments: Optional[list[str]] = None,
    is_iteration: bool = False,
) -> str:
    """构造 BrainstormAgent 首条 user 消息。

    Args:
        requirement: 用户原始需求
        scene_hint: 调用方（Orchestrator）若已预判场景可传入，agent 仍要用 detect_scene 核实
        workspace_info: 迭代场景时当前 workspace 信息（project_name / project_type）
        attachments: 附件 URL 列表
        is_iteration: True 表示这是在已有 Spec 基础上迭代（vs 首轮）
    """
    lines: list[str] = []

    # —— 需求 —— #
    lines.append("## 用户需求")
    lines.append(requirement.strip())
    lines.append("")

    # —— 场景预判 —— #
    lines.append("## 场景预判")
    lines.append(_SCENE_HINTS[scene_hint])
    lines.append("")

    # —— 附件 —— #
    if attachments:
        lines.append("## 附件")
        for url in attachments:
            lines.append(f"- {url}")
        lines.append("")

    # —— Workspace 上下文 —— #
    if workspace_info:
        lines.append("## 当前 Workspace（迭代场景）")
        lines.append(f"- project_name: {workspace_info.get('project_name', '(unknown)')}")
        lines.append(f"- project_type: {workspace_info.get('project_type', '(unknown)')}")
        files = workspace_info.get("files") or []
        if files:
            lines.append(f"- files: {len(files)} 个（详情用 read_workspace_context 查）")
        lines.append("")
        lines.append(
            "这是**迭代**。务必先调用 `read_workspace_context` 读现状，"
            "再决定新需求如何影响现有 Spec（新增 / 修改 / 重写）"
        )
        lines.append("")
    elif is_iteration:
        lines.append("## 迭代场景")
        lines.append("无 workspace_info，但被标记为迭代。请根据对话历史推断现状。")
        lines.append("")

    # —— 行动指引 —— #
    lines.append("## 下一步")
    if scene_hint is None:
        lines.append("先调用 `detect_scene` 识别场景，再根据反馈的 P1 清单按序反问。")
    else:
        lines.append("核实场景（可调用 `detect_scene`），然后按 P1 清单反问。")

    return "\n".join(lines)
