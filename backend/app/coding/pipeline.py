"""Coding Pipeline — 核心流水线逻辑

从 routes/coding.py 的 auto_pipeline 中抽取的可复用 pipeline。
供 CodingProfile (harness) 和旧 auto-pipeline 路由共用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any, AsyncIterator
from urllib.parse import urlencode, urlparse

from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User, Conversation, Message, Project
from app.coding.form_component_editor import (
    normalize_form_component_editor_artifacts,
    validate_form_component_editor_workspace,
)
from app.coding.scenes import SceneType, get_scene
from app.coding.generator import CodingGenerator
from app.coding.workspace import WorkspaceManager, ProjectType
from app.coding.prompts import AGENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ── 常量 ──────────────────────────────────────────

IDE_EXCLUDED_GLOBS = [
    "node_modules", ".git", "dist", "build", ".cache",
    ".vscode/.vibe-ide.code-workspace",
]


# ── Pipeline 参数 ──────────────────────────────────

class PipelineParams:
    """Pipeline 执行所需的全部参数（不依赖 FastAPI Request/AuthContext）。"""

    def __init__(
        self,
        *,
        message: str,
        user_id: int,
        tenant_id: int,
        workspace_id: Optional[str] = None,
        conversation_id: Optional[int] = None,
        selected_model: Optional[str] = None,
        project_id: Optional[int] = None,
        project_type: Optional[str] = None,
        quick_create: bool = False,
        # 预计算的 request-scoped 值
        code_server_base_url: str = "",
        api_base_builder: Optional[str] = None,  # 用于构建 IDE proxy URL 的函数
        ide_token: Optional[str] = None,  # 预生成的 IDE token（或延迟生成）
        ide_token_payload: Optional[dict] = None,  # 用于生成 token 的数据
    ):
        self.message = message
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.conversation_id = conversation_id
        self.selected_model = selected_model
        self.project_id = project_id
        self.project_type = project_type
        self.quick_create = quick_create
        self.code_server_base_url = code_server_base_url or settings.code_server_base_url or ""
        self.api_base_builder = api_base_builder
        self.ide_token = ide_token
        self.ide_token_payload = ide_token_payload


# ── IDE 工具函数（从 routes/coding.py 搬过来） ──────

def ensure_vibe_workspace_file(ws_path: Path) -> Path:
    """为 Web IDE 生成轻量 workspace 文件。"""
    workspace_file = ws_path / ".vibe-ide.code-workspace"
    workspace_payload = {
        "folders": [{"path": str(ws_path.resolve())}],
        "settings": {
            "files.exclude": {p: True for p in IDE_EXCLUDED_GLOBS},
            "search.exclude": {p: True for p in IDE_EXCLUDED_GLOBS},
            "files.watcherExclude": {p: True for p in IDE_EXCLUDED_GLOBS},
            "explorer.autoReveal": False,
            "git.autoRepositoryDetection": "openEditors",
        },
    }
    serialized = json.dumps(workspace_payload, ensure_ascii=False, indent=2)
    if not workspace_file.exists() or workspace_file.read_text(encoding="utf-8") != serialized:
        workspace_file.write_text(serialized, encoding="utf-8")
    return workspace_file


def ensure_cursor_rules(ws_path: Path):
    """确保工作区包含 cursor rules。"""
    rules_dir = ws_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    template_dir = Path(__file__).parent.parent / "templates" / "cursor-rules"
    if template_dir.exists():
        import shutil
        for rule_file in template_dir.glob("*.mdc"):
            target = rules_dir / rule_file.name
            if not target.exists() or target.stat().st_size < rule_file.stat().st_size:
                shutil.copy2(rule_file, target)


def write_ruijing_extension_config(
    ws_path: Path,
    ws_id: str,
    ide_token: str,
    api_base: str,
    model: str,
    conversation_id: Optional[int] = None,
):
    """为睿鲸AI VS Code 扩展生成配置文件。"""
    vscode_dir = ws_path / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    config_file = vscode_dir / "ruijing-ai.json"
    harness_api_base = derive_harness_api_base(api_base)
    config_payload = {
        "workspaceId": ws_id,
        "ideToken": ide_token,
        "apiBase": api_base.split(f"/workspace/{ws_id}")[0] if f"/workspace/{ws_id}" in api_base else api_base,
        "harnessApiBase": harness_api_base.split(f"/workspace/{ws_id}")[0] if f"/workspace/{ws_id}" in harness_api_base else harness_api_base,
        "model": model or "MiniMax-M2.7",
    }
    if conversation_id:
        config_payload["conversationId"] = conversation_id
    config_file.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_workspace_chat_payload(
    ws_path: Path,
    filename: str,
    messages: list[dict],
    *,
    conversation_id: Optional[int] = None,
    max_content_len: int = 3000,
    stream_messages: Optional[list[dict[str, Any]]] = None,
):
    vscode_dir = ws_path / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    history_file = vscode_dir / filename
    recent = messages[-20:] if len(messages) > 20 else messages
    payload = {
        "version": 2 if stream_messages else 1,
        "conversation_id": conversation_id,
        "messages": [
            {"role": m.get("role", "user"), "content": (m.get("content", "") or "")[:max_content_len]}
            for m in recent
        ],
    }
    if stream_messages:
        payload["stream_messages"] = stream_messages[-200:]
    history_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_chat_history_to_workspace(ws_path: Path, messages: list[dict], *, conversation_id: Optional[int] = None):
    """把精简对话历史写入工作区 .vscode/chat-history.json，供 IDE 扩展作为上下文读取。"""
    _write_workspace_chat_payload(
        ws_path,
        "chat-history.json",
        messages,
        conversation_id=conversation_id,
        max_content_len=3000,
    )


def write_chat_replay_to_workspace(
    ws_path: Path,
    messages: list[dict],
    *,
    conversation_id: Optional[int] = None,
    stream_messages: Optional[list[dict[str, Any]]] = None,
):
    """把富回放历史写入工作区 .vscode/chat-replay.json，供 Web Chat 重开时还原近似实时流。"""
    _write_workspace_chat_payload(
        ws_path,
        "chat-replay.json",
        messages,
        conversation_id=conversation_id,
        max_content_len=20000,
        stream_messages=stream_messages,
    )


def create_ide_access_token(user_id: int, tenant_id: int, ws_id: str) -> str:
    """创建 IDE 访问令牌。"""
    payload = {
        "sub": str(user_id),
        "tid": tenant_id,
        "type": "ide_access",
        "ws": ws_id,
        "exp": datetime.utcnow() + timedelta(hours=8),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def derive_harness_api_base(api_base: str) -> str:
    """把 coding IDE API base 映射成 harness IDE API base。"""
    return (api_base or "").replace("/api/coding/", "/api/harness/coding/")


def build_ide_url(
    ws_path: Path,
    ws_id: str,
    ide_token: str,
    api_base: str,
    model: str,
    code_server_base_url: str,
    conversation_id: Optional[int] = None,
    vibe_context: Optional[str] = None,
) -> Optional[str]:
    """生成完整的 IDE URL。"""
    base_url = code_server_base_url.rstrip("/") if code_server_base_url else ""
    if not base_url:
        return None

    ensure_vibe_workspace_file(ws_path)
    ensure_cursor_rules(ws_path)
    write_ruijing_extension_config(ws_path, ws_id, ide_token, api_base, model, conversation_id=conversation_id)

    query_params: dict[str, str] = {
        "folder": str(ws_path.resolve()),
        "vibe_workspace_id": ws_id,
        "vibe_api_base": api_base,
        "vibe_harness_api_base": derive_harness_api_base(api_base),
        "vibe_ide_token": ide_token,
        "vibe_model": model,
    }
    if conversation_id:
        query_params["vibe_conversation_id"] = str(conversation_id)
    if vibe_context:
        query_params["vibe_context"] = vibe_context

    return f"{base_url}/?{urlencode(query_params)}"


# ── 场景/项目辅助函数 ──────────────────────────────

def scene_to_project_type(scene_type: SceneType) -> str:
    mapping = {
        SceneType.WEB_COMPONENT: "form-component",
        SceneType.WEB_PAGE: "form-page",
        SceneType.WEB_LIST_VIEW: "form-list",
        SceneType.WEB_LAYOUT: "layout",
        SceneType.WEB_PLUGIN: "plugin",
        SceneType.BACKEND_API: "backend-api",
        SceneType.MOBILE_COMPONENT: "mobile-component",
        SceneType.MOBILE_PAGE: "mobile-page",
        SceneType.SCRIPT_JS: "script",
        SceneType.SCRIPT_PYTHON: "script",
        SceneType.SCRIPT_GROOVY: "script",
        SceneType.BUSINESS_DIALOG: "script",
        SceneType.WEB_LOGIN: "web-login",
        SceneType.UI_STYLE: "ui-style",
        SceneType.LIST_CUSTOM_MODULE: "list-custom-module",
    }
    return mapping.get(scene_type, "form-component")


PROJECT_TYPE_TO_SCENE = {
    "form-component": SceneType.WEB_COMPONENT,
    "menu-page": SceneType.WEB_PAGE,
    "form-page": SceneType.WEB_PAGE,
    "form-list": SceneType.WEB_LIST_VIEW,
    "backend-api": SceneType.BACKEND_API,
    "layout": SceneType.WEB_LAYOUT,
    "plugin": SceneType.WEB_PLUGIN,
    "mobile-component": SceneType.MOBILE_COMPONENT,
    "mobile-page": SceneType.MOBILE_PAGE,
    "script-js": SceneType.SCRIPT_JS,
    "script-python": SceneType.SCRIPT_PYTHON,
    "script-groovy": SceneType.SCRIPT_GROOVY,
    "business-dialog": SceneType.BUSINESS_DIALOG,
    "ui-style": SceneType.UI_STYLE,
    "list-custom-module": SceneType.LIST_CUSTOM_MODULE,
    "web-login": SceneType.WEB_LOGIN,
}


async def extract_project_name(generator: CodingGenerator, message: str) -> str:
    """从用户需求中提取项目名称。"""
    keyword_map = {
        "甘特图": "gantt-chart", "审批流程": "approval-flow", "审批": "approval",
        "进度条": "progress-bar", "评分": "star-rating", "颜色选择": "color-picker",
        "颜色选择器": "color-picker", "标签": "tag-input", "图表分析": "chart-analysis",
        "图表": "chart", "日期选择": "date-picker", "日期范围": "date-range",
        "文件上传": "file-upload", "上传": "upload", "头像": "avatar",
        "签名": "signature", "二维码": "qrcode", "地图": "map-view",
        "富文本": "rich-text", "树形": "tree-select", "组织树": "org-tree",
        "组织架构树": "org-tree", "组织架构": "org-tree", "部门树": "dept-tree",
        "级联": "cascader", "数据表格": "data-table", "表格": "data-table",
        "看板": "kanban", "数据查询": "data-query", "弹窗选择": "popup-select",
        "人员选择": "person-select", "图片识别": "image-recognition",
        "截图": "screenshot", "AI分析": "ai-analysis", "拍照": "camera",
        "水印": "watermark", "倒计时": "countdown", "步骤条": "steps",
        "时间轴": "timeline", "轮播": "carousel", "抽屉": "drawer",
        "物料选择": "material-select", "地图选点": "map-picker",
        "供应商管理": "supplier-mgmt", "供应商": "supplier",
        "采购管理": "purchase-mgmt", "采购": "purchase",
        "客户管理": "customer-mgmt", "客户": "customer",
        "订单管理": "order-mgmt", "订单": "order",
        "库存管理": "inventory-mgmt", "库存": "inventory",
        "登录": "login", "注册": "register",
    }
    msg_lower = message.lower()
    for keyword, name in keyword_map.items():
        if keyword in msg_lower:
            return name
    return "custom-dev"


def extract_display_name(message: str, project_type: str, fallback_name: str) -> str:
    """提取适合在工作区列表中展示的名称。"""
    cleaned = re.sub(r"\s+", " ", (message or "").strip())
    if not cleaned:
        return fallback_name

    patterns = [
        r'(?:做|开发|创建|实现|搭建|写|生成|补一个|新增|增加|搞一个|搞个)\s*(?:一|1)?个?\s*(.+?)(?:组件|页面|模块|系统|功能|弹窗|选择器|面板)',
        r'(.+?)(?:组件|页面|模块|系统|功能|弹窗|选择器|面板)',
    ]
    display_name = ""
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            display_name = match.group(1).strip("，。,.!！?？：: ")
            break

    if not display_name:
        display_name = cleaned.split("，", 1)[0].split("。", 1)[0].strip()

    display_name = re.sub(
        r'^(请|帮我|帮忙|我想|我要|想要|需要|帮我做|帮我开发|做一个|做个|开发一个|开发个|实现一个|实现个|创建一个|创建个|生成一个|生成个)\s*',
        '', display_name,
    ).strip("，。,.!！?？：: ")

    suffix_map = {
        "form-component": "组件", "mobile-component": "组件",
        "form-page": "页面", "menu-page": "页面", "mobile-page": "页面",
        "form-list": "列表", "layout": "布局", "plugin": "插件", "backend-api": "接口",
    }
    suffix = suffix_map.get(project_type, "")
    if suffix and not any(t in display_name for t in ("组件", "页面", "选择器", "弹窗", "布局", "插件", "接口", "模块", "登录页")):
        display_name = f"{display_name}{suffix}"

    return (display_name or fallback_name)[:48]


async def is_new_component_intent(generator: CodingGenerator, message: str, ws_id: str, ws_mgr: WorkspaceManager) -> bool:
    """判断用户消息是要修改当前组件还是做一个全新的组件。"""
    msg_lower = message.lower()
    new_keywords = ["做一个新", "创建一个新", "新建一个", "开发一个新", "新组件", "新工作区", "另一个组件"]
    modify_keywords = ["修改", "改一下", "调整", "优化", "加个", "删掉", "改成", "换个", "bug", "fix",
                       "空白", "渲染", "不对", "报错", "完善", "补充", "实现", "请用", "改为", "更新"]

    has_new = any(kw in msg_lower for kw in new_keywords)
    has_modify = any(kw in msg_lower for kw in modify_keywords)

    if has_new and not has_modify:
        return True
    if has_modify and not has_new:
        return False

    try:
        from app.llm_client import LLMClient
        info = ws_mgr.get_workspace_info(ws_id)
        project_name = info.get("project_name", "")
        llm = LLMClient()
        resp = await llm.chat_completion([
            {"role": "system", "content": f"当前工作区的组件是 '{project_name}'。判断用户的消息是想【修改当前组件】还是想【做一个全新的、不同的组件】。回答中必须包含 MODIFY 或 NEW 这个词。"},
            {"role": "user", "content": message}
        ], max_tokens=50)
        answer = resp.get("choices", [{}])[0].get("message", {}).get("content", "").upper()
        return "NEW" in answer
    except Exception as e:
        logger.warning(f"意图判断失败: {e}")
        return False


def append_agent_event_to_history(history_parts: list[str], event: dict[str, Any]):
    """将 Agent 的关键执行输出整理成可持久化的文本记录。"""
    event_type = event.get("type")
    if event_type == "content":
        content = event.get("content")
        if isinstance(content, str) and content:
            history_parts.append(content)
    elif event_type == "agent_tool":
        tool_name = event.get("tool_display") or event.get("tool") or "工具"
        preview = event.get("input_preview") or ""
        history_parts.append(f"\n🔧 **{tool_name}** `{preview}`\n" if preview else f"\n🔧 **{tool_name}**\n")
    elif event_type == "agent_result":
        preview = event.get("output_preview")
        if event.get("is_error"):
            history_parts.append(f"> ❌ {preview or '执行失败'}\n\n")
        elif isinstance(preview, str) and preview and preview != "(empty)":
            clipped = preview[:300] + "..." if len(preview) > 300 else preview
            history_parts.append(f"> ✅ {clipped}\n\n")
        else:
            history_parts.append("> ✅ 完成\n\n")
    elif event_type == "agent_done":
        turns = event.get("num_turns") or "?"
        history_parts.append(f"\n---\n✨ **Agent 完成** ({turns} 轮对话)\n")
    elif event_type == "agent_error":
        message = event.get("message") or "发生未知错误"
        history_parts.append(f"\n❌ **Agent 错误**: {message}\n")


def _push_replay_message(
    stream_messages: list[dict[str, Any]],
    msg_type: str,
    content: str = "",
    **extra: Any,
):
    payload: dict[str, Any] = {
        "type": msg_type,
        "content": content,
        "timestamp": int(datetime.now().timestamp() * 1000),
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    stream_messages.append(payload)


def _append_replay_thinking_delta(stream_messages: list[dict[str, Any]], delta: str):
    if not delta:
        return
    if stream_messages and stream_messages[-1].get("type") == "thinking":
        stream_messages[-1]["content"] = f"{stream_messages[-1].get('content', '')}{delta}"
        return
    _push_replay_message(stream_messages, "thinking", delta)


def _append_replay_command_output(stream_messages: list[dict[str, Any]], chunk: str):
    if not chunk:
        return
    if stream_messages and stream_messages[-1].get("type") == "command":
        existing = str(stream_messages[-1].get("content") or "")
        stream_messages[-1]["content"] = f"{existing}{chunk}"
        return
    _push_replay_message(stream_messages, "command", chunk)


def append_event_to_stream_replay(stream_messages: list[dict[str, Any]], event: dict[str, Any]):
    event_type = event.get("type")

    if event_type == "step":
        step_key = str(event.get("step") or "")
        step_status = str(event.get("status") or "")
        data = event.get("data") or {}

        if step_key == "detect_scene" and step_status == "done":
            _push_replay_message(
                stream_messages,
                "status",
                f"✓ 识别为 {data.get('scene_type') or 'component'}",
            )
        elif step_key == "create_workspace" and step_status == "running":
            _push_replay_message(stream_messages, "status", "正在初始化工程脚手架...")
        elif step_key == "create_workspace" and step_status == "done":
            _push_replay_message(stream_messages, "status", "✓ 工程脚手架已初始化")
        elif step_key == "generate" and step_status == "running":
            _push_replay_message(stream_messages, "status", "AI 开始编写代码...")
        elif step_key == "generate" and step_status == "done":
            _push_replay_message(stream_messages, "status", "✓ 代码生成完成")
        elif step_key == "build" and step_status == "running":
            _push_replay_message(stream_messages, "status", "🏗️ 正在构建打包...")
        elif step_key == "build" and step_status == "done":
            _push_replay_message(stream_messages, "status", "✅ 构建完成")
        elif step_key == "debug" and step_status == "running":
            _push_replay_message(stream_messages, "status", "🧪 正在启动调试环境...")
        elif step_key == "debug" and step_status == "done":
            _push_replay_message(stream_messages, "status", "✅ 调试环境已启动")
        return

    if event_type == "content":
        content = str(event.get("content") or "").strip()
        if content:
            # 跳过与最后一条 thinking 重复的内容
            if stream_messages and stream_messages[-1].get("type") == "thinking":
                last_content = str(stream_messages[-1].get("content") or "")
                if content[:50] in last_content or last_content in content:
                    return
            _push_replay_message(stream_messages, "thinking", content)
        return

    if event_type == "agent_thinking":
        # agent_thinking 是完整思考块，但 agent_thinking_delta 已经流式追加了同样内容
        # 只在没有活跃的 thinking 消息时才新增（避免重复）
        content = str(event.get("content") or "")
        if content.strip():
            if stream_messages and stream_messages[-1].get("type") == "thinking":
                last_content = str(stream_messages[-1].get("content") or "")
                if content[:50] in last_content or last_content in content:
                    # 已经通过 delta 追加了，跳过
                    return
            _push_replay_message(stream_messages, "thinking", content)
        return

    if event_type == "agent_thinking_delta":
        _append_replay_thinking_delta(stream_messages, str(event.get("content") or ""))
        return

    if event_type == "agent_tool":
        tool_name = str(event.get("tool") or "")
        args = event.get("args") or {}
        preview = str(event.get("input_preview") or "").strip()

        if tool_name == "write_file":
            file_path = str(args.get("file_path") or "")
            _push_replay_message(
                stream_messages,
                "file_write",
                "",
                fileName=(Path(file_path).name if file_path else preview),
                fileContent=str(args.get("content") or "") or None,
                collapsed=True,
            )
        elif tool_name == "edit_file":
            file_path = str(args.get("file_path") or "")
            _push_replay_message(
                stream_messages,
                "file_edit",
                "",
                fileName=(Path(file_path).name if file_path else preview),
                fileContent=str(args.get("new_string") or "") or None,
                collapsed=True,
            )
        elif tool_name == "run_command":
            command = str(args.get("command") or preview or "")
            if command:
                _push_replay_message(stream_messages, "command", command)
        elif tool_name == "read_file":
            _push_replay_message(stream_messages, "tool", f"📄 读取 {preview}")
        elif tool_name == "glob_files":
            _push_replay_message(stream_messages, "tool", f"📂 扫描 {preview or '项目文件'}")
        elif tool_name == "grep_search":
            _push_replay_message(stream_messages, "tool", f"🔍 搜索 {preview}")
        return

    if event_type == "agent_command_output":
        _append_replay_command_output(stream_messages, str(event.get("chunk") or ""))
        return

    if event_type == "agent_result":
        preview = str(event.get("output_preview") or "").strip()
        if event.get("is_error"):
            _push_replay_message(stream_messages, "error", preview or "执行失败")
        elif preview:
            _push_replay_message(stream_messages, "status", f"✅ {preview}")
        return

    if event_type == "agent_done":
        _push_replay_message(stream_messages, "status", "✅ 代码生成完成")
        return

    if event_type in {"agent_error", "error"}:
        _push_replay_message(stream_messages, "error", str(event.get("message") or "发生未知错误"))


def _extract_tool_target(event: dict[str, Any]) -> str:
    args = event.get("args") or {}
    if isinstance(args, dict):
        if args.get("file_path"):
            return str(args["file_path"])
        if args.get("command"):
            return str(args["command"])
    preview = str(event.get("input_preview") or "").strip()
    return preview


def _build_agent_completion_summary(
    final_agent_text: str,
    tool_events: list[dict[str, Any]],
) -> str:
    cleaned_final = (final_agent_text or "").strip()
    if cleaned_final and cleaned_final.lower() != "completed":
        return cleaned_final

    changed_files: list[str] = []
    inspected_files: list[str] = []
    successful_commands: list[str] = []
    failed_tools: list[str] = []

    for event in tool_events:
        event_type = event.get("type")
        if event_type == "agent_tool":
            tool_name = str(event.get("tool") or "")
            target = _extract_tool_target(event)
            if tool_name in {"write_file", "edit_file"} and target:
                changed_files.append(target)
            elif tool_name == "read_file" and target:
                inspected_files.append(target)
        elif event_type == "agent_result":
            preview = str(event.get("output_preview") or "").strip()
            tool_name = str(event.get("tool_display") or event.get("tool") or "工具")
            if event.get("is_error"):
                failed_tools.append(f"{tool_name}: {preview or '执行失败'}")
            elif preview:
                lowered = preview.lower()
                if "构建成功" in preview or "compiled successfully" in lowered:
                    successful_commands.append("构建验证通过")
                elif "依赖已就绪" in preview or "依赖安装完成" in preview or "共享缓存" in preview:
                    successful_commands.append("依赖检查通过")

    changed_files = list(dict.fromkeys(changed_files))[:5]
    inspected_files = list(dict.fromkeys(inspected_files))[:5]
    successful_commands = list(dict.fromkeys(successful_commands))
    failed_tools = list(dict.fromkeys(failed_tools))[:3]

    lines: list[str] = []
    if changed_files:
        lines.append("已完成本轮代码修改。")
        lines.append("修改文件：" + "、".join(f"`{path}`" for path in changed_files))
    elif inspected_files:
        lines.append("已检查当前工程，未修改代码。")
        lines.append("检查文件：" + "、".join(f"`{path}`" for path in inspected_files))

    if successful_commands:
        lines.append("校验结果：" + "、".join(successful_commands))

    if failed_tools and not lines:
        lines.append("本轮执行未能完整完成。")
    if failed_tools:
        lines.append("异常信息：" + "；".join(failed_tools))

    return "\n\n".join(lines).strip()


# ── 模型解析（从 routes/coding.py 搬过来） ──────────

CODING_LLM_CONFIG_PREFIX = "llmcfg:"


def _parse_coding_llm_config_id(model_value: Optional[str]) -> Optional[int]:
    if not model_value or not model_value.startswith(CODING_LLM_CONFIG_PREFIX):
        return None
    try:
        return int(model_value[len(CODING_LLM_CONFIG_PREFIX):])
    except (ValueError, TypeError):
        return None


async def resolve_effective_coding_model(
    db: AsyncSession,
    tenant_id: int | None,
    *,
    requested_model: str | None = None,
    selected_llm_config_id: int | None = None,
) -> tuple[str, Optional[int]]:
    """解析实际使用的 coding 模型。优先级：请求指定 > 会话已选 > 租户默认 > 环境变量。"""
    from app.routes.coding import _resolve_effective_coding_model as _resolve
    return await _resolve(db, tenant_id, requested_model=requested_model, selected_llm_config_id=selected_llm_config_id)


# ── 对话历史工具 ──────────────────────────────────

async def get_conversation_history(db: AsyncSession, conversation_id: int) -> list:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        {"role": m.role, "content": m.content}
        for m in messages
        if m.role in ("user", "assistant")
    ]


async def save_coding_message(db: AsyncSession, conversation_id: int, role: str, content: str):
    msg = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(msg)
    await db.commit()


# ── Pipeline 核心 ──────────────────────────────────

async def run_coding_pipeline(
    params: PipelineParams,
    db: AsyncSession,
) -> AsyncIterator[dict]:
    """
    核心 Pipeline 异步生成器 — yield 事件 dict。

    这是 auto-pipeline 的业务逻辑抽取版本，
    不依赖 FastAPI Request/AuthContext，所有需要的值通过 PipelineParams 传入。
    """
    from app.coding.vibe_agent import VibeCodingAgent

    generator = CodingGenerator()
    ws_mgr = WorkspaceManager()

    ws_id = params.workspace_id
    conversation_id = params.conversation_id
    is_iteration = ws_id is not None
    replay_stream_messages: list[dict[str, Any]] = []

    def _record_event(event: dict[str, Any]) -> dict[str, Any]:
        append_event_to_stream_replay(replay_stream_messages, event)
        return event

    # 解析模型
    effective_model, effective_model_config_id = await resolve_effective_coding_model(
        db, params.tenant_id, requested_model=params.selected_model,
    )

    # 如果有已有对话，恢复模型配置
    coding_conversation: Optional[Conversation] = None
    if conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == params.user_id,
                Conversation.tenant_id == params.tenant_id,
                Conversation.agent_type == "coding",
            )
        )
        coding_conversation = result.scalar_one_or_none()
        if coding_conversation:
            if params.selected_model is None:
                effective_model, effective_model_config_id = await resolve_effective_coding_model(
                    db, params.tenant_id,
                    selected_llm_config_id=coding_conversation.selected_llm_config_id,
                )
        else:
            conversation_id = None

    # 加载项目配置
    project = None
    project_id = params.project_id
    if project_id:
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == params.user_id)
        )
        project = result.scalar_one_or_none()
    elif ws_id:
        try:
            ws_info = ws_mgr.get_workspace_info(ws_id)
            _ws_project_id = ws_info.get("project_id")
            if _ws_project_id:
                project_id = _ws_project_id
                result = await db.execute(
                    select(Project).where(Project.id == project_id, Project.user_id == params.user_id)
                )
                project = result.scalar_one_or_none()
        except Exception:
            pass

    try:
        # ---- 意图检测 ----
        msg_lower = params.message.strip().lower()
        # 调试功能已禁用，所有请求直接进入代码生成流程
        is_debug_intent = False
        is_publish_intent = any(kw in msg_lower for kw in ['帮我发布', '立即发布', '打包发布', '打包上传', '帮我打包', '发布到平台', 'publish', '帮我build', '帮我构建'])

        # Publish 模式处理
        if is_publish_intent and ws_id:
            _push_replay_message(replay_stream_messages, "user", params.message)
            yield _record_event({"type": "step", "step": "build", "status": "running", "data": {"message": "正在构建打包..."}})
            try:
                await ws_mgr.build_and_package(ws_id)
                yield _record_event({"type": "step", "step": "build", "status": "done"})
                yield _record_event({"type": "content", "content": "✅ 构建完成！\n\n请点击顶部的「打包发布」按钮下载 zip 文件，然后上传到 aPaaS 平台。"})
            except Exception as e:
                yield _record_event({"type": "step", "step": "build", "status": "error"})
                yield _record_event({"type": "content", "content": f"❌ 构建失败: {str(e)}"})
            yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id})
            return

        # ---- 迭代意图判断 ----
        if is_iteration:
            if await is_new_component_intent(generator, params.message, ws_id, ws_mgr):
                is_iteration = False
                ws_id = None
                yield _record_event({"type": "content", "content": "💡 检测到你想做一个新组件，正在为你创建新的工作区...\n\n"})

        # ---- Step 1: 场景检测 ----
        if not replay_stream_messages:
            _push_replay_message(replay_stream_messages, "user", params.message)

        if not is_iteration:
            yield _record_event({"type": "step", "step": "detect_scene", "status": "running"})
            if params.project_type:
                if params.project_type in ("script",):
                    try:
                        scene_type = await generator.detect_scene(params.message)
                    except Exception:
                        scene_type = SceneType.SCRIPT_JS
                else:
                    scene_type = PROJECT_TYPE_TO_SCENE.get(params.project_type, SceneType.WEB_COMPONENT)
            else:
                try:
                    scene_type = await generator.detect_scene(params.message)
                except Exception:
                    scene_type = SceneType.WEB_COMPONENT
            yield _record_event({"type": "step", "step": "detect_scene", "status": "done", "data": {"scene_type": scene_type.value}})
            # 通知前端 scene_detected + conversation_id（如果已有）
            yield _record_event({"type": "scene_detected", "conversation_id": conversation_id})
        else:
            info = ws_mgr.get_workspace_info(ws_id)
            pt = info.get("project_type", "form-component")
            scene_type = PROJECT_TYPE_TO_SCENE.get(pt, SceneType.WEB_COMPONENT)

        # ---- Step 2: 创建工作区 ----
        if not is_iteration:
            yield _record_event({"type": "step", "step": "create_workspace", "status": "running"})
            try:
                project_name = await extract_project_name(generator, params.message)
            except Exception:
                project_name = "custom-dev"
            project_type_str = params.project_type or scene_to_project_type(scene_type)
            project_type_enum = ProjectType(project_type_str)
            display_name = extract_display_name(params.message, project_type_str, project_name)
            meta = ws_mgr.create_workspace(
                project_type_enum, project_name, params.user_id,
                project_id=project_id, display_name=display_name,
            )
            ws_id = meta["id"]
            yield _record_event({"type": "step", "step": "create_workspace", "status": "done", "data": {
                "workspace_id": ws_id,
                "project_name": meta["project_name"],
                "display_name": meta.get("display_name", meta["project_name"]),
            }})

        # ---- quick_create 快速模式 ----
        if params.quick_create:
            if not conversation_id:
                coding_conversation = Conversation(
                    title=params.message[:50], user_id=params.user_id,
                    tenant_id=params.tenant_id, agent_type="coding",
                    workspace_id=ws_id, selected_llm_config_id=effective_model_config_id,
                )
                db.add(coding_conversation)
                await db.commit()
                await db.refresh(coding_conversation)
                conversation_id = coding_conversation.id
            elif coding_conversation and params.selected_model is not None:
                coding_conversation.selected_llm_config_id = effective_model_config_id
                await db.commit()
            await save_coding_message(db, conversation_id, "user", params.message)

            ide_url = _build_ide_url_for_pipeline(params, ws_id, conversation_id, effective_model)
            yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id, "ide_url": ide_url})
            return

        # ---- Step 3: Agent 代码生成 ----
        yield _record_event({"type": "step", "step": "generate", "status": "running"})

        # 创建或更新对话
        if not conversation_id:
            coding_conversation = Conversation(
                title=params.message[:50], user_id=params.user_id,
                tenant_id=params.tenant_id, agent_type="coding",
                workspace_id=ws_id, selected_llm_config_id=effective_model_config_id,
            )
            db.add(coding_conversation)
            await db.commit()
            await db.refresh(coding_conversation)
            conversation_id = coding_conversation.id
        elif coding_conversation and params.selected_model is not None:
            coding_conversation.selected_llm_config_id = effective_model_config_id
            await db.commit()
            await db.refresh(coding_conversation)

        await save_coding_message(db, conversation_id, "user", params.message)

        # 对话历史
        conversation_summary = ""
        if conversation_id:
            history = await get_conversation_history(db, conversation_id)
            if history:
                conversation_summary = "\n".join(
                    f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')[:200]}"
                    for m in history[-6:]
                )

        # 运行 Agent
        agent = VibeCodingAgent(ws_id, system_prompt=AGENT_SYSTEM_PROMPT, tenant_id=params.tenant_id)
        agent_result_text = ""
        persisted_agent_output: list[str] = []
        tool_events_for_summary: list[dict[str, Any]] = []
        final_agent_summary = ""
        streamed_narration = False
        assistant_history_saved = False

        async def _persist_output():
            nonlocal assistant_history_saved
            if assistant_history_saved:
                return
            saved_output = (
                final_agent_summary.strip()
                or agent_result_text.strip()
                or "".join(persisted_agent_output).strip()
            )
            if not saved_output:
                return
            try:
                await save_coding_message(db, conversation_id, "assistant", saved_output)
                assistant_history_saved = True
            except Exception:
                logger.exception("保存 Agent 历史失败")

        try:
            async for event in agent.run(
                requirement=params.message,
                conversation_summary=conversation_summary,
                model=effective_model,
                max_turns=30,
            ):
                append_event_to_stream_replay(replay_stream_messages, event)
                yield event
                append_agent_event_to_history(persisted_agent_output, event)
                if event.get("type") in {"agent_tool", "agent_result"}:
                    tool_events_for_summary.append(event)
                if event.get("type") == "agent_thinking":
                    content = str(event.get("content") or "").strip()
                    if content:
                        streamed_narration = True
                        final_agent_summary = content
                        agent_result_text += content + "\n"
                elif event.get("type") == "agent_thinking_delta":
                    content = str(event.get("content") or "").strip()
                    if content:
                        streamed_narration = True
                elif event.get("type") == "agent_done":
                    result = str(event.get("result") or "").strip()
                    if result and result.lower() != "completed":
                        final_agent_summary = result
                        agent_result_text += "\n" + result
        except (asyncio.CancelledError, Exception):
            await _persist_output()
            raise

        synthesized_summary = _build_agent_completion_summary(final_agent_summary, tool_events_for_summary)
        if synthesized_summary:
            final_agent_summary = synthesized_summary
            if not streamed_narration:
                yield _record_event({"type": "content", "content": synthesized_summary})

        workspace_path = ws_mgr.get_workspace_path(ws_id)
        normalized_files = normalize_form_component_editor_artifacts(workspace_path)
        if normalized_files:
            logger.info("Normalized form-component editor artifacts for %s: %s", ws_id, normalized_files)
        contract_errors = validate_form_component_editor_workspace(workspace_path)
        if contract_errors:
            raise RuntimeError("；".join(contract_errors))

        await _persist_output()

        yield _record_event({"type": "step", "step": "generate", "status": "done",
               "data": {"files": normalized_files, "file_count": len(normalized_files), "agent_mode": True}})

        # 写对话历史到工作区供 IDE 扩展读取
        await _write_history_for_ide(
            ws_mgr,
            ws_id,
            conversation_id,
            db,
            rich_assistant_output="".join(persisted_agent_output).strip(),
            stream_messages=replay_stream_messages,
        )

        # 迭代模式完成
        if is_iteration:
            serve_status = ws_mgr.is_serve_running(ws_id)
            yield _record_event({"type": "step", "step": "hot_reload", "status": "done",
                   "data": {"serve_running": serve_status["running"], "port": serve_status.get("port")}})
            yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id})
            return

        # 新建模式：生成 IDE URL
        ide_url = _build_ide_url_for_pipeline(params, ws_id, conversation_id, effective_model)
        yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id, "ide_url": ide_url})

    except Exception as e:
        logger.exception("coding pipeline 错误")
        yield _record_event({"type": "error", "message": str(e)})


# ── 内部辅助 ──────────────────────────────────────

def _get_platform_url(project: Optional[Any]) -> str:
    """从项目配置推导平台前端 URL。"""
    if project and getattr(project, 'platform_url', None):
        base = project.platform_url or ""
        if "/backend" in base:
            return base.replace("/backend", "/platform/")
        if base and not base.endswith("/"):
            return base + "/platform/"
        return base + "platform/" if base else ""
    base = settings.apaas_base_url or ""
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else "https://apaas-dev8.dfy.definesys.cn/platform/"


async def _write_history_for_ide(
    ws_mgr: WorkspaceManager,
    ws_id: str,
    conversation_id: Optional[int],
    db: AsyncSession,
    *,
    rich_assistant_output: str = "",
    stream_messages: Optional[list[dict[str, Any]]] = None,
):
    """在 pipeline 完成时写入 IDE 精简历史和 Web Chat 富回放历史。"""
    if not conversation_id or not ws_id:
        return
    try:
        ws_path = ws_mgr.get_workspace_path(ws_id)
        history = await get_conversation_history(db, conversation_id)
        if history:
            write_chat_history_to_workspace(ws_path, history, conversation_id=conversation_id)

            replay_history = [dict(item) for item in history]
            rich_output = rich_assistant_output.strip()
            if rich_output:
                for idx in range(len(replay_history) - 1, -1, -1):
                    if replay_history[idx].get("role") == "assistant":
                        replay_history[idx]["content"] = rich_output
                        break
                else:
                    replay_history.append({"role": "assistant", "content": rich_output})
            merged_stream_messages: list[dict[str, Any]] = []
            if stream_messages:
                replay_file = ws_path / ".vscode" / "chat-replay.json"
                if replay_file.exists():
                    try:
                        existing = json.loads(replay_file.read_text(encoding="utf-8"))
                        if existing.get("conversation_id") in (None, conversation_id):
                            existing_stream_messages = existing.get("stream_messages") or []
                            if isinstance(existing_stream_messages, list):
                                merged_stream_messages.extend(
                                    item for item in existing_stream_messages if isinstance(item, dict)
                                )
                    except Exception:
                        logger.debug("读取历史 chat-replay.json 失败，改为覆盖写入", exc_info=True)

                if merged_stream_messages:
                    merged_stream_messages.append({
                        "type": "status",
                        "content": "───",
                        "timestamp": int(datetime.now().timestamp() * 1000),
                    })
                merged_stream_messages.extend(stream_messages)

            write_chat_replay_to_workspace(
                ws_path,
                replay_history,
                conversation_id=conversation_id,
                stream_messages=merged_stream_messages or None,
            )
    except Exception:
        logger.warning("写入 IDE 对话历史失败", exc_info=True)


def _build_ide_url_for_pipeline(
    params: PipelineParams, ws_id: str, conversation_id: Optional[int], model: str
) -> Optional[str]:
    """Pipeline 内部生成 IDE URL。"""
    ws_mgr = WorkspaceManager()
    try:
        ws_path = ws_mgr.get_workspace_path(ws_id)
        ide_token = params.ide_token or create_ide_access_token(params.user_id, params.tenant_id, ws_id)
        # api_base_builder 可能包含 {ws_id} 占位符
        api_base = params.api_base_builder or ""
        if api_base and "{ws_id}" in api_base:
            api_base = api_base.replace("{ws_id}", ws_id)
        elif not api_base:
            api_base = f"/api/coding/workspace/{ws_id}/ide"
        return build_ide_url(
            ws_path=ws_path,
            ws_id=ws_id,
            ide_token=ide_token,
            api_base=api_base,
            model=model,
            code_server_base_url=params.code_server_base_url,
            conversation_id=conversation_id,
            vibe_context=f"用户: {params.message[:500]}",
        )
    except Exception as e:
        logger.warning(f"生成 IDE URL 失败: {e}")
        return None
