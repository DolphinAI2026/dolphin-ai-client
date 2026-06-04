"""aPaaS 原生编辑器 URL 路径构建（纯函数）。

从 platform_proxy._build_menu_redirect_path 的 config 分支抽出，给「打开低代码后台」深链用。
返回相对路径 `/platform/{tid}/...`；调用方（editor-url 接口）拼上真主机 host 成 host-absolute。
**不带 embed=1/hideClose=1** —— 那是内嵌剥壳用的，真标签页要完整编辑器。
"""
from __future__ import annotations

# 菜单类型 → 平台 editor sub-path（跟 super-agents-dev openLowCodeEditorDirectly 对齐）
_MENU_TYPE_TO_EDITOR_PATH = {
    "MODEL": "data-model-fn-config",
    "MENU_TYPE_MODEL": "data-model-fn-config",
    "QUOTE": "quote-fn-config",
    "MENU_TYPE_QUOTE": "quote-fn-config",
}


def build_editor_path(
    menu_type: str,
    *,
    apaas_app_id: str,
    menu_id: str = "",
    form_id: str = "",
    tid: str,
    step_index: int = 0,
) -> str:
    """返回 aPaaS 编辑器相对路径。

    - 不传 menu_id → 应用编辑总览（currentStepIndex=step_index）。
    - 传 menu_id  → 该菜单的表单/模型编辑器。
    """
    if not (menu_id or "").strip():
        idx = step_index if 0 <= step_index <= 9 else 0
        return f"/platform/{tid}/admin/app-store/edit-app?appId={apaas_app_id}&currentStepIndex={idx}"

    sub_path = _MENU_TYPE_TO_EDITOR_PATH.get((menu_type or "").upper(), "fn-config")
    qs_parts = [f"appId={apaas_app_id}", f"menuId={menu_id}"]
    if (form_id or "").strip():
        qs_parts.append(f"formId={form_id}")
    qs_parts.append("processVersion=false")
    return f"/platform/{tid}/default/{sub_path}?{'&'.join(qs_parts)}"
