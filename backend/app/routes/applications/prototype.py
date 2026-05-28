"""AI Coding 主工作台 — HTML 原型生成。读需求基线 → LLM → 单文件 HTML → 存 app_prototypes。"""
from __future__ import annotations
import json
from app.mcp_spec_sections import read_spec_section

# 需求基线里要喂给原型的 section — 按 spec_chat.py _section_key_for 真实约定:
#   data_model chapter → section_type="data_model", section_key="main"
#   dict       chapter → section_type="data_model", section_key="dict"
#   roles      chapter → section_type="permission", section_key="global"
#   menus      chapter → section_type="page",       section_key="global"
#
# 注意: VALID_SECTION_TYPES = ("form","list","process","page","permission","data_model")
# 基线代码里的 section_type="spec" 是无效的, 实际约定用上述 4 对组合.
_BASELINE_SECTIONS: list[tuple[str, str, str]] = [
    # (label_for_prompt, section_type, section_key)
    ("数据模型 (models)", "data_model", "main"),
    ("数据字典 (dicts)",   "data_model", "dict"),
    ("角色权限 (roles)",   "permission", "global"),
    ("菜单结构 (menus)",   "page",       "global"),
]

_PROMPT_HEADER = """你是 AI Coding 的 UI 原型设计师。基于下面的应用需求基线，生成一个**单文件 HTML 原型**，供业务用户确认 UI。

硬性要求：
1. 输出**完整单文件 HTML**（<!DOCTYPE html> 开头），不依赖任何本地资源。
2. 只用 CDN 引 Element Plus + ECharts；其余内联 <style>/<script>。
3. 内置**mock 数据**，不调用任何真实接口、不写任何 token/key/真实地址。
4. 企业级后台风格，清晰稳重，信息密度适中。
5. 每个可点选的功能区块（卡片/表格行/图表/按钮）加属性 `data-block="<简短中文标签>"`，供点选交互使用。
6. HTML 必须能在 iframe 中独立预览。

应用需求基线：
"""


async def build_prototype_prompt(db, app_id: int) -> str:
    """读 app 的需求基线 spec sections → 拼成 LLM prompt。

    读 4 个 section (数据模型/字典/角色/菜单)，有数据就拼入，没初始化的跳过。
    本函数不调 LLM、不落库 (那是 Task 3 的职责)。
    """
    parts: list[str] = [_PROMPT_HEADER]
    for label, section_type, section_key in _BASELINE_SECTIONS:
        res = await read_spec_section(db, app_id, section_type, section_key)
        if res.get("ok") and res.get("exists"):
            spec_json = res["section"].get("spec_json", {})
            parts.append(f"\n## {label}\n{json.dumps(spec_json, ensure_ascii=False, indent=2)}")
    parts.append("\n\n现在输出完整单文件 HTML（只输出 HTML，不要解释）：")
    return "".join(parts)
