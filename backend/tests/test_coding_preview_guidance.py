"""档1: coding agent 必须主动一键 run_workspace_preview，不能只口头解释 npm run preview。

根因(2026-06-19): 工具链全通、工作区一键能起，但 agent 在用户要「看效果」时跑去读文件 +
口头讲 npm run preview，不调 run_workspace_preview。因为系统提示词零引导、工具描述偏弱。
本测试把「提示词引导 + 工具描述触发条件」钉死，防回退。
"""
from __future__ import annotations

from app.coding.prompts import AGENT_SYSTEM_PROMPT
from app.agents.coding.tools import RUN_PREVIEW_TOOL_DESC


def test_system_prompt_steers_to_run_workspace_preview():
    # 必须点名工具
    assert "run_workspace_preview" in AGENT_SYSTEM_PROMPT
    # 必须把「禁止只口头解释 npm run preview」写进提示，作为反例
    assert "严禁" in AGENT_SYSTEM_PROMPT
    assert "npm run preview" in AGENT_SYSTEM_PROMPT


def test_tool_description_has_trigger_and_priority():
    # 描述是模型决定该不该一键起预览的唯一认知来源
    assert "预览" in RUN_PREVIEW_TOOL_DESC
    assert ("必须" in RUN_PREVIEW_TOOL_DESC) or ("优先" in RUN_PREVIEW_TOOL_DESC)
    # 明确点出不要让用户自己跑命令
    assert "npm run preview" in RUN_PREVIEW_TOOL_DESC
