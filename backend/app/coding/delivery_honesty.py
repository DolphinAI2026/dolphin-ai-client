"""交付诚实声明 —— 出轮 emit done 之前,对照用户原始请求,显式说明本轮的收窄/未起预览。

背景:coding 流水线的交付校验只看 build/运行时报错(autofix),从不对照原始请求范围。
实测「做两端招聘系统」被静默压成单个 aPaaS 扩展产物(单文件 mock CRUD)还报 clean/done,
用户全程零警示(竞品分析里最伤 credibility 的 overclaim/静默收窄)。

这里不实现「真做两端系统」(那是 ProjectType/Scene/create_workspace 三层的 XL 改动,需先 spec),
只做「边界诚实」:纯函数,只按原始请求里的强信号 + serve 状态触发,保守避免误拦正常单页请求。
挂在 run_coding_pipeline 的 done 之前(调用点之后),用完整 params.message(不截断),
与 _build_agent_completion_summary 的早返路径无关 —— 故常见(LLM 自述)路径也不会被跳过。
"""
from __future__ import annotations

import re

# 强信号才触发,避免把正常单页请求误判成多端(对抗核验点名的 false-positive 风险)
_MULTI_END_EXPLICIT = re.compile(r"两端|双端|多页|前台.*后台|后台.*前台|完整的?(应用|系统|平台|项目)")
_ADMIN_SIDE = re.compile(r"管理端|后台|管理员|HR|admin", re.IGNORECASE)
_USER_SIDE = re.compile(r"用户端|前台|求职者|客户端|C\s*端|用户侧|consumer", re.IGNORECASE)
_WANTS_RUN = re.compile(r"能跑|跑起来|跑通|运行|预览|preview|可运行|本地起", re.IGNORECASE)


def _has_multi_end_signal(requirement: str) -> bool:
    """显式多端词,或同时出现「管理侧 + 用户侧」词 = 强信号。"""
    return bool(
        _MULTI_END_EXPLICIT.search(requirement)
        or (_ADMIN_SIDE.search(requirement) and _USER_SIDE.search(requirement))
    )


def build_delivery_honesty_note(requirement: str, serve_running: bool) -> str:
    """对照原始请求生成交付诚实声明;无可声明项 → 空串(no-op)。

    requirement: 用户本轮完整原始请求(用 params.message,别用截断的 detect_scene 首行)。
    serve_running: 本轮是否真起了本地预览(ws_mgr.is_serve_running)。
    """
    req = requirement or ""
    notes: list[str] = []

    if _has_multi_end_signal(req):
        notes.append(
            "- 本轮产出为**单一自开发扩展产物**,未拆分为独立的管理端/用户端(或多页应用)。"
            "当前 coding 流水线每次生成一个 aPaaS 扩展产物;完整的多端系统需拆成多个页面/组件"
            "分别开发,或改用应用搭建。请勿当作可独立部署的完整系统。"
        )

    if _WANTS_RUN.search(req) and not serve_running:
        notes.append(
            "- 本轮**未启动本地预览**(端口为空),未做运行态验收;"
            "若产物为 aPaaS UMD 包,需接入平台宿主才能跑真实数据。"
        )

    if not notes:
        return ""
    return "**交付说明(请注意)**\n" + "\n".join(notes)
