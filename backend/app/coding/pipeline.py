"""Coding Pipeline — 核心流水线逻辑

从 routes/coding.py 的 auto_pipeline 中抽取的可复用 pipeline。
供 CodingProfile (harness) 和旧 auto-pipeline 路由共用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import traceback
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
    finalize_form_component_dual_workspace,
    validate_form_component_editor_workspace,
)
from app.coding.scenes import SceneType, get_scene
from app.coding.generator import CodingGenerator
from app.coding.workspace import WorkspaceManager, ProjectType
from app.coding.prompts import AGENT_SYSTEM_PROMPT
from app.coding.read_query import classify_coding_intent, run_read_query

logger = logging.getLogger(__name__)


# ── 常量 ──────────────────────────────────────────

IDE_EXCLUDED_GLOBS = [
    "node_modules", ".git", "dist", "build", ".cache",
    ".vscode/.vibe-ide.code-workspace",
]


def normalize_ide_theme(theme: Optional[str]) -> str:
    return "light" if theme == "light" else "dark"


def ide_color_theme(theme: Optional[str]) -> str:
    return "Default Light Modern" if normalize_ide_theme(theme) == "light" else "Default Dark Modern"


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
        app_id: Optional[str] = None,  # 分场景「在应用上定制」绑定的本地 Application.id
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
        self.app_id = app_id
        self.code_server_base_url = code_server_base_url or settings.code_server_base_url or ""
        self.api_base_builder = api_base_builder
        self.ide_token = ide_token
        self.ide_token_payload = ide_token_payload


# ── IDE 工具函数（从 routes/coding.py 搬过来） ──────

def ensure_vibe_workspace_file(ws_path: Path, ide_theme: Optional[str] = None) -> Path:
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
            "workbench.colorTheme": ide_color_theme(ide_theme),
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

    ide_theme = "dark"
    ensure_vibe_workspace_file(ws_path, ide_theme)
    ensure_cursor_rules(ws_path)
    write_ruijing_extension_config(ws_path, ws_id, ide_token, api_base, model, conversation_id=conversation_id)

    query_params: dict[str, str] = {
        "folder": str(ws_path.resolve()),
        "vibe_workspace_id": ws_id,
        "vibe_api_base": api_base,
        "vibe_harness_api_base": derive_harness_api_base(api_base),
        "vibe_ide_token": ide_token,
        "vibe_model": model,
        "vibe_ui_theme": ide_theme,
    }
    if conversation_id:
        query_params["vibe_conversation_id"] = str(conversation_id)
    if vibe_context:
        query_params["vibe_context"] = vibe_context

    return f"{base_url}/?{urlencode(query_params)}"


# ── 场景/项目辅助函数 ──────────────────────────────

class UnsupportedSceneError(Exception):
    """LLM 识别到智能开发模块不支持的场景（脚本/弹窗/样式等），需引导用户改用辅助搭建。"""


def scene_to_project_type(scene_type: SceneType) -> str:
    mapping = {
        SceneType.WEB_COMPONENT_DUAL: "form-component-dual",
        SceneType.WEB_PAGE: "form-page",
        SceneType.WEB_LIST_VIEW: "form-list",
        SceneType.WEB_LAYOUT: "layout",
        SceneType.WEB_PLUGIN: "plugin",
        SceneType.BACKEND_API: "backend-api",
        SceneType.MOBILE_PAGE: "mobile-page",
        SceneType.WEB_LOGIN: "web-login",
    }
    return mapping.get(scene_type, "form-component-dual")


PROJECT_TYPE_TO_SCENE = {
    "form-component": SceneType.WEB_COMPONENT_DUAL,
    "form-component-dual": SceneType.WEB_COMPONENT_DUAL,
    "menu-page": SceneType.WEB_PAGE,
    "form-page": SceneType.WEB_PAGE,
    "form-list": SceneType.WEB_LIST_VIEW,
    "backend-api": SceneType.BACKEND_API,
    "layout": SceneType.WEB_LAYOUT,
    "plugin": SceneType.WEB_PLUGIN,
    "mobile-page": SceneType.MOBILE_PAGE,
    "web-login": SceneType.WEB_LOGIN,
}


async def extract_project_name(generator: CodingGenerator, message: str) -> str:
    """从用户需求中提取项目语义名称（kebab-case 英文）。

    优先使用关键词快速匹配；未命中时用 LLM 提取，确保返回有语义的名称而非 custom-dev。
    """
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
        "手机号": "phone-number", "国际手机": "intl-phone", "电话号码": "phone-number",
        "国际区号": "intl-phone", "区号": "area-code",
        "评价": "rating", "好评": "rating", "打分": "rating",
        "滑块": "slider", "开关": "switch", "单选": "radio", "多选": "checkbox",
        "数字输入": "number-input", "金额": "amount-input", "价格": "price-input",
        "身份证": "id-card", "银行卡": "bank-card", "邮编": "postal-code",
        "邮箱": "email-input", "网址": "url-input", "密码": "password-input",
        "图片上传": "image-upload", "视频上传": "video-upload",
        "附件": "attachment", "文件": "file-upload",
        "人员": "person-select", "部门": "dept-select", "用户": "user-select",
        "时间选择": "time-picker", "时间范围": "time-range",
        "周期": "period-picker", "季度": "quarter-picker", "年份": "year-picker",
        "字典": "dict-select", "数据字典": "dict-select",
        "关联": "relation-select", "关联数据": "relation-select",
    }
    msg_lower = message.lower()
    for keyword, name in keyword_map.items():
        if keyword in msg_lower:
            return name

    # 关键词未命中 → 用 LLM 提取语义名
    try:
        prompt = (
            "根据以下需求描述，提取一个简短的英文组件名（kebab-case，2~4个单词，只返回名称本身，不要解释）。\n"
            "例如：国际手机号码 → intl-phone-number，进度环 → progress-ring，文件预览 → file-preview\n\n"
            f"需求：{message[:200]}"
        )
        resp = await generator.llm_client.chat_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0.1,
        )
        result = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        name = result.strip().lower()
        # 只保留合法的 kebab-case 字符
        name = re.sub(r"[^a-z0-9-]", "-", name).strip("-")
        name = re.sub(r"-{2,}", "-", name)
        if name and len(name) >= 3:
            return name
    except Exception:
        # LLM 提取失败不阻断流程，仍降级返回通用名，但记录原因避免静默
        logger.warning(f"extract_project_name LLM 提取失败，降级为通用名: {traceback.format_exc()}")

    return "custom"


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
        "form-component-dual": "组件",
        "form-page": "页面", "menu-page": "页面", "mobile-page": "页面",
        "form-list": "列表", "layout": "布局", "plugin": "插件", "backend-api": "接口",
    }
    suffix = suffix_map.get(project_type, "")
    if suffix and not any(t in display_name for t in ("组件", "页面", "选择器", "弹窗", "布局", "插件", "接口", "模块", "登录页")):
        display_name = f"{display_name}{suffix}"

    return (display_name or fallback_name)[:48]


async def is_new_component_intent(generator: CodingGenerator, message: str, ws_id: str, ws_mgr: WorkspaceManager) -> bool:
    """判断用户消息是要修改当前组件还是做一个全新的组件。"""
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
    conv = await db.get(Conversation, conversation_id)
    if conv:
        conv.updated_at = datetime.utcnow()
        if role == "user" and conv.title in {"智能开发", "新开发会话", "新对话"}:
            conv.title = content.replace("\n", " ").strip()[:50] or conv.title
    await db.commit()


# ── Brainstorm 需求澄清 ────────────────────────────

BRAINSTORM_PROPOSAL_MARKER = "<!-- BRAINSTORM_PROPOSAL -->"
BRAINSTORM_MAX_REVISIONS = 8  # 仅用于记录多轮修订，不再强制进入代码生成
BRAINSTORM_SCENES = {
    SceneType.WEB_COMPONENT_DUAL,
    SceneType.WEB_PAGE,
    SceneType.WEB_LIST_VIEW,
    SceneType.BACKEND_API,
}

_BRAINSTORM_PROMPT_FORM_COMPONENT = """\
你是一位资深 aPaaS 表单组件架构师。请分析用户需求，输出一份可落地的开发 SPEC 确认单（不超过 700 字，中文）。

开发类型：aPaaS 自定义表单组件（需生成 widget.config.json 及 edit/read/ide/list/print/search/search-ide 7 个场景文件）

用户需求：{message}

## 元约束（⚠️ 这些是给你的指令，**绝对不要把约束文字本身抄进方案里**）

1. 严格按下面"输出模板"部分的 Markdown 结构输出。模板里 `[方括号]` 或 `...` 占位符必须替换为具体内容，**禁止**出现"视需求而定"等模糊词。
2. "需求覆盖校验"表格必填：把用户原始需求拆成编号列表（按原文顺序），每条标注对应的落地位置（配置项名称 / 交互场景 / 具体行为）。如某条需求未落地，必须在表格同一行的"落地位置"列里显式声明"未实现，原因：..."——不允许静默省略。
3. **组件名必须反映核心功能**：从用户需求提炼 kebab-case 短名（如"日期时间段选择" → `date-time-range`），**严禁**用 `custom` / `demo` / `component` / `custom-dev` 等通用占位词。
4. **配置项表格的"数据类型"列**：只允许填 JS/JSON 基础类型（`String` / `Number` / `Boolean` / `Array` / `Object`）。**禁止**把 UI 组件名（如 `form-custom-select-editor`、`form-custom-field-assign-editor`）填到"数据类型"列里——那是 UI 渲染方式，要填到"UI 渲染"列或在"说明"列里提及。
5. **字段赋值场景识别**：如果用户需求提到"赋值给其他字段 / 输出到某字段 / 字段联动 / 计算结果写到某字段 / 回填到表单字段"等能力，**必须**在"配置项"段新增一条配置项，其：
   - 数据类型 = `Array`（**固定值**，存储格式是 `[{{origin, target}}, ...]` 赋值对列表，用户可配 0 到 N 条）
   - UI 渲染 = `form-custom-field-assign-editor`（**默认选它**，用于主表字段赋值，如时间差→数字字段、合计→金额字段等单一派生值场景）；**仅当**组件产出"整个子表的多行数据"需要映射到目标子表时才用 `form-custom-table-field-assign-editor`（这种场景 `otherFields` 的首层 componentType 是 `FORM_WIDGET_SON_TABLE`）。不要因为组件支持"在子表中使用"就误选 table 版——组件用在子表 ≠ 赋值目标是子表
   - 默认值 = `[]`
   - 说明中明确"用户通过此配置项选择接收赋值的目标字段"
   **不要**把数据类型写成 String（即使组件只有 1 个源字段，底层也是单元素数组，不是字符串）。**不要**靠"aPaaS 字段联动规则"或其他外部机制绕过。
6. 每个章节只输出模板要求的内容，不要把本"元约束"区的文字（包括本条）复制进输出。

## 输出模板（严格照此结构输出）

## 📋 开发 SPEC 确认

**组件名称**：[中文名]（`[kebab-case英文名]`）
**代码标识**：`FORM_CUSTOM_[大写下划线]`

**功能概述**：[一句话描述核心功能]

---

### 数据存储

> **⚠️ 选择铁则**（最容易踩："日期范围/时间段"组件被误选为 DATE，实际应为 STRING/BOF_TEXT）：
> - 单个短字符串（<500 字符）→ `["STRING"]` + `BOF_TEXT`
> - 长字符串/富文本/base64（≥500 字符）→ `["BIG_TEXT"]` + `BOF_TEXT`
> - 纯数字 → `["NUM"]` + `BOF_NUMBER`
> - **单一日期字符串**（如 `"2024-01-01"`）→ `["DATE"]` + `BOF_DATE`
> - **日期范围 / 时间段 / JSON 数组 / 序列化对象**（如 `["2024-01-01","2024-01-02"]`）→ `["STRING"]`（<500）或 `["BIG_TEXT"]`（≥500） + `BOF_TEXT`（**不要选 DATE/BOF_DATE**）

| 字段 | 值 |
|------|----|
| formValue 格式 | `[具体JSON示例或基础类型示例]` |
| componentModelField | `["STRING" / "BIG_TEXT" / "NUM" / "DATE"]`（按上表选一个并说明理由） |
| BOF 类型 | `BOF_TEXT / BOF_NUMBER / BOF_DATE`（与上行对应） |

### 配置项（setting.vue 面板，如无需配置则填"无"）

> - **数据类型**：只填 JS 基础类型（String / Number / Boolean / Array / Object）
> - **UI 渲染**：填 setting.vue 里用于渲染该配置的组件名。选择优先级：
>   1. **优先**从 scaffold 预置原子里选：`form-custom-input-editor`（单行文本）/ `form-custom-select-editor`（下拉）/ `form-custom-textarea-editor`（多行文本）/ `form-custom-switch-editor`（开关）
>   2. 赋值场景用：`form-custom-field-assign-editor` / `form-custom-table-field-assign-editor`
>   3. **只有预置原子语义不匹配时**（如日期/日期范围/颜色/JSON 等），才标注 `form-custom-[业务名]-editor`（codegen 阶段会按 setting-vue.mdc 的"自造业务 editor 铁则"新建）。**示例**：
>     - 日期字段 → `form-custom-date-editor`
>     - 日期时间字段 → `form-custom-date-time-editor`
>     - 颜色字段 → `form-custom-color-editor`
>   4. **禁止**：日期类字段用 `form-custom-input-editor`（用户只能手打字符串体验差）、单个布尔用 `form-custom-select-editor`（应该用 switch）等语义错配

| 属性 | 数据类型 | UI 渲染 | 默认值 | 说明 |
|------|---------|--------|--------|------|
| `propName` | String / Boolean / Number / Array / Object | `form-custom-xxx-editor` | `默认值` | 说明 |

### 各场景交互
- **编辑（edit）**：
- **只读（read）**：
- **列表列（list）**：
- **搜索（search）**：
- **打印（print）**：

### 第三方依赖
- [列出需要额外安装的 npm 包，若无则填"无"]

## ✅ 需求覆盖校验

| # | 原始需求 | 落地位置 |
|---|---|---|
| 1 | [简述第 1 条需求] | [具体配置项 / 交互 / 行为] |
| 2 | ... | ... |

---
以上是我对需求的理解，请确认是否准确？如有需要调整的地方请告知，确认后将立即开始生成代码。\
"""

_BRAINSTORM_PROMPT_PAGE = """\
你是一位资深 aPaaS 前端页面架构师。请分析用户需求，输出一份结构化的开发 SPEC 确认单（中文）。

开发类型：aPaaS 自定义菜单页面（Vue 2.7 + Element UI，不可使用 Vue Router）

用户需求：{message}

## 元约束（这些是给你的指令，禁止抄进输出）
1. 这是进入代码生成前的开发 SPEC，不是概念设计稿。每个章节都必须可指导后续代码实现。
2. 优先复用 aPaaS 低代码已有能力：模型、表单、字典、权限、流程、平台 `$request` 服务。只有低代码配置覆盖不了的 UI、交互、聚合查询、可视化才进入自开发。
3. 数据接口必须说明数据来源：`复用低代码表单服务 / 新增自开发接口 / 暂用 mock` 三选一，不允许只写 `/api/...`。
4. 若用户需求缺少关键输入，不要假装完整；在"待确认问题"中列出，但仍给出默认建议。
5. 输出总长度控制在 900 字内，表格优先，禁止长篇解释。

请严格按以下 Markdown 格式输出，每个字段都必须给出具体值：

## 📋 开发 SPEC 确认

**页面名称**：[中文名]（`[kebab-case英文名]`）
**自开发类型**：自定义菜单页面
**实现范围**：[页面/组件/接口/依赖的边界]

**功能概述**：[一句话描述核心功能]

---

### 1. 需求拆解与边界
| 项 | 内容 |
|----|------|
| 核心目标 | [用户真正要解决的问题] |
| 低代码复用 | [可直接复用的模型/表单/字典/权限/流程，没有则填"无"] |
| 自开发范围 | [必须写代码实现的部分] |
| 不做范围 | [本次明确不做的内容，没有则填"无"] |

### 页面结构
```
[用 ASCII 画出主要区域布局，如搜索栏/表格/弹窗等]
```

### 2. 数据与接口策略
| 数据/接口 | 来源 | 方法与路径 | 入参 | 出参 | 说明 |
|-----------|------|------------|------|------|------|
| [名称] | 复用低代码表单服务 / 新增自开发接口 / 暂用 mock | `GET /xxx` | [关键入参] | [关键出参] | [用途] |

### 3. 状态与交互
1. [步骤 1]
2. [步骤 2]

### 4. 验收标准
- [可验证标准 1]
- [可验证标准 2]
- [可验证标准 3]

### 5. 第三方依赖
- [列出需要额外安装的 npm 包，若无则填"无"]

### 6. 待确认问题
- [没有则填"无"]

---
以上是我整理的开发 SPEC，请确认是否准确；如需调整数据来源、接口或交互，请直接补充，确认后再开始生成代码。\
"""

_BRAINSTORM_PROMPT_LIST = """\
你是一位资深 aPaaS 前端架构师。请分析用户需求，输出一份结构化的开发 SPEC 确认单（不超过 800 字，中文）。

开发类型：aPaaS 自定义列表视图（Vue 2.7 + Element UI）

用户需求：{message}

请严格按以下 Markdown 格式输出，每个字段都必须给出具体值：

## 📋 开发 SPEC 确认

**列表名称**：[中文名]（`[kebab-case英文名]`）
**自开发类型**：自定义列表视图

**功能概述**：[一句话描述]

---

### 1. 需求拆解与边界
| 项 | 内容 |
|----|------|
| 低代码复用 | [可复用列表/模型/权限，没有则填"无"] |
| 自开发范围 | [必须写代码的展示、筛选、操作等] |

### 2. 列表结构
| 列名 | 字段 | 说明 |
|------|------|------|
| 名称 | `name` | ... |

### 3. 操作与功能
- **行操作**：[查看/编辑/删除等]
- **批量操作**：[如有]
- **搜索/筛选**：[支持哪些条件]

### 4. 数据接口
| 数据/接口 | 来源 | 方法与路径 | 入参 | 出参 | 说明 |
|-----------|------|------------|------|------|------|
| 列表查询 | 复用低代码表单服务 / 新增自开发接口 / 暂用 mock | `GET /xxx` | [关键入参] | [关键出参] | [用途] |

### 5. 验收标准
- [可验证标准 1]
- [可验证标准 2]

---
以上是我整理的开发 SPEC，请确认是否准确；如需调整数据来源、接口或交互，请直接补充，确认后再开始生成代码。\
"""

_BRAINSTORM_PROMPT_BACKEND_API = """\
你是一位资深 aPaaS 后端架构师。请分析用户需求，输出一份结构化的开发 SPEC 确认单（中文）。

开发类型：aPaaS 后端自开发接口（SpringBoot Java，接口路径以 /custom 开头，包名 com.xdap）

用户需求：{message}

请严格按以下 Markdown 格式输出，每个字段都必须给出具体值，禁止出现"视需求而定"：

## 📋 开发 SPEC 确认

**接口名称**：[中文名]（`[camelCase英文名]`）
**接口路径**：`/custom/[资源路径]`
**请求方式**：`GET / POST`
**实现范围**：[接口、服务、DAO、DTO、权限校验边界]

**功能概述**：[一句话描述核心功能]

---

### 1. 数据来源与边界
| 表名 | 说明 |
|------|------|
| `t_xxx` | ... |

### 2. 请求参数
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `keyword` | String | 否 | 模糊搜索关键词 |
| `pageNum` | Integer | 是 | 页码，从 1 开始 |
| `pageSize` | Integer | 是 | 每页条数 |

### 3. 响应结构
```json
{{
  "total": 100,
  "list": [
    {{ "id": 1, "fieldA": "...", "fieldB": "..." }}
  ]
}}
```

### 4. 业务逻辑要点
1. [数据查询逻辑、关联表处理、字段转换等]
2. [如有状态映射、JSON解析等特殊处理，逐条说明]

### 5. 验收标准
- [可验证标准 1]
- [可验证标准 2]

---
以上是我整理的开发 SPEC，请确认是否准确；如需调整参数、数据来源或业务规则，请直接补充，确认后再开始生成代码。\
"""

_BRAINSTORM_PROMPTS = {
    SceneType.WEB_COMPONENT_DUAL: _BRAINSTORM_PROMPT_FORM_COMPONENT,
    SceneType.WEB_PAGE: _BRAINSTORM_PROMPT_PAGE,
    SceneType.WEB_LIST_VIEW: _BRAINSTORM_PROMPT_LIST,
    SceneType.BACKEND_API: _BRAINSTORM_PROMPT_BACKEND_API,
}


_BRAINSTORM_REVISION_PROMPT = """\
你是一位资深 aPaaS 架构师，正在根据用户反馈**修改**一份已有的开发 SPEC（不是重新设计）。

## 原始需求
{original_requirement}

## 上一版开发 SPEC
{previous_proposal}

## 用户反馈
{user_feedback}

## 修改规则（⚠️ 给你的元指令，**严禁把规则文字本身复制到输出里**）

1. **最小修改**：只改用户明确要求改的部分，**不要动**用户没提到的其他字段/命名/结构，上一版其他地方原样保留。
2. **歧义反问优先**：如用户反馈含 "没 X / 没有 X / 缺 X / 少 X / 漏 X / 还是没 X" 或 "X 不对 / X 不好" 等模糊表述，**不要猜**，只输出下面"澄清输出格式"段就停止，不要输出修改后方案。
3. **单组件优先**：用户追加能力默认加到当前同一个组件上，仅在用户明确说"拆分/独立组件/新组件"时才新建；模糊时走规则 2。
4. **字段赋值场景识别**：如果用户要求涉及"给其他字段赋值/输出到某字段/字段联动/计算结果写到某字段/回填到表单字段"等，对应配置项必须满足：**数据类型固定是 `Array`**（不管用户配几条赋值对，底层存储都是 `[{{origin, target}}, ...]`；子表版 table-field-assign-editor 也是 `Array`，元素多一个 `assignmentList`），**UI 渲染**用 `form-custom-field-assign-editor` 或 `form-custom-table-field-assign-editor`。默认值 `[]`。注意：editor 名是 UI 组件名、不是数据类型名，**不要**把它填到"数据类型"列里；也**不要**把数据类型写成 String。不要靠 aPaaS 字段联动规则等外部机制绕过。
5. **UI 渲染选择优先级**：配置项的 UI 渲染优先从预置原子选（input/select/textarea/switch + 两个 assign editor）；预置原子语义不匹配时（如**日期/日期时间/颜色/范围**等），标注为 `form-custom-[业务名]-editor`（codegen 会按铁则新建业务 editor）。禁止语义错配（如日期字段用 input-editor 让用户手打字符串）。
5. **需求覆盖校验表格必填**：修改后方案末尾的"需求覆盖校验"段需把原始需求逐条编号，每条在表格里标注落地位置；未落地的条款在表格同一行直接写"未实现，原因：..."，不要静默省略。
6. **本次变更 diff**：修改后方案**开头**列出 "## 🔄 本次变更"，用 `[新增] / [删除] / [修改]` 三类条目概括。

## 澄清输出格式（仅规则 2 触发时使用）

```
## ⚠️ 需要澄清
你说的"[引用原话]"，我理解为以下两种可能：
- A. [解释 A]
- B. [解释 B]
请告诉我是 A 还是 B，我再修改方案。
```

## 开发 SPEC 输出格式（其他情况使用）

严格按上一版 Markdown 结构输出修改后开发 SPEC，保持章节顺序/表格列名一致，开头带"本次变更"段。**不要**把"修改规则"章节的文字复制到输出。
"""


async def _brainstorm_llm_call(
    tenant_id: Optional[int],
    model: str,
    messages: list,
    *,
    max_tokens: int = 1000,
    temperature: float = 0.3,
) -> str:
    """
    使用租户的 coding LLM 配置发起调用（走 Dashscope/MiniMax 等，非通用 settings LLM）。
    """
    from app.agents.coding.llm_config import load_coding_llm_config
    import httpx

    base_url, api_key, llm_model = await load_coding_llm_config(tenant_id, model)

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10)) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": llm_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


async def _detect_scene_llm_call(
    tenant_id: Optional[int],
    model: str,
    user_input: str,
) -> "SceneType":
    """使用租户 LLM 配置识别开发场景（走 Dashscope，不走 Anthropic）。"""
    system_prompt = """你是aPaaS低代码平台的场景分类助手。根据用户的开发需求，从以下场景中选择最匹配的一个，**只输出场景代码，不要任何解释**。

## 场景定义

### 前端 Web 类
- **web_page**：在应用菜单中独立访问的完整业务页面。
  典型形态：数据查询页面、图表分析页面、报表页面、管理列表页、看板、大屏、仪表盘、自开发菜单页面。
  技术特征：有独立路由、完整页面结构（Vue 页面组件 + index.js + apaas.json），可使用 this.$request 调接口。

- **web_component_dual**：嵌入在低代码表单字段中的可复用 UI 控件，同时支持 PC 端和移动端（**所有组件类需求统一走此场景**）。
  典型形态：自定义选择器、日期范围组件、文件上传控件、富文本编辑器、自定义输入框、数据关联选择控件、移动端表单控件。
  技术特征：shared/ 层共享 widget.config 和业务逻辑，web/ 使用 element-ui，mobile/ 使用 cube-ui，各自独立打包。
  **使用时机：凡是"组件/控件/选择器/输入框/表单组件"类的需求，不论用户是否强调"只要 PC 端"，一律使用此场景（不再提供仅 PC 端变体）。**

- **web_list_view**：自定义列表视图，嵌入在列表页中替换默认展示方式（基于 ListEngine），不是独立页面。

- **web_layout**：自定义应用整体布局结构（基于 LayoutEngine），如自定义顶导、侧边栏。

- **web_login**：自定义登录页，替换平台默认登录界面。

- **web_plugin**：平台扩展插件，通过 ExtensionEngine/HookManager 扩展平台能力。

### 移动端类
- **mobile_page**：移动端独立页面（使用 cube-ui 组件库）。

### 后端 Java 类
- **backend_api**：开发后端 REST 接口服务（SpringBoot/Java Controller + Service），接口路径以 /custom 开头，包名以 com.xdap 开头。只要主体是"开发接口/API/数据接口"，无论是否提及 SpringBoot，都属于此类。注意：前端页面"调用接口"不属于此类。
- **backend_feign**：用 FeignClient 调用外部 HTTP 服务，含接口定义、DTO、FeignConfig。
- **backend_scheduled**：Spring @Scheduled 定时任务，含 ScheduledTask.java + Dao + Service。

## 不支持的场景（必须引导用户改用辅助搭建）

本智能开发模块**不支持**以下场景，遇到这类需求必须输出 `unsupported_script`，由上层流程提示用户改用"辅助搭建"模块完成：
- 业务事件中的 JavaScript / Python / Groovy **脚本**
- 业务事件提交时的**自定义弹窗**
- 仅调整 **CSS 样式**的场景
- 列表页面中嵌入的**自定义模块**

## 关键区分原则

**组件类（统一用 web_component_dual）**：
- "做一个组件/控件/选择器/输入框/表单组件"（未说明端） → **web_component_dual**
- "移动端组件/手机端控件/mobile组件" → **web_component_dual**
- "同时支持PC和移动端的组件" → **web_component_dual**
- "只需PC端组件/仅PC端/不需要移动端" → **web_component_dual**（仍用双端模板，只是 mobile/ 可以留空或简化）

**web_page vs web_component_dual**（最常见混淆）：
- "页面/菜单页面/自开发页面/查询页面/分析页面/报表/看板/大屏" → **web_page**
- "组件/控件/选择器/输入框/自开发组件/表单组件" → **web_component_dual**
- 图表、表格出现在"页面"语境中 → **web_page**（图表页面是完整页面，不是组件）

**backend_api vs web_page**：
- 用户要"开发接口/写后端/SpringBoot/Java Controller" → **backend_api**
- 用户要"做一个页面，页面里调用接口" → **web_page**（接口调用是前端行为）

**backend_api vs web_component_dual**（"自定义接口"易混淆）：
- 主体是"接口/API/数据接口/查询接口/REST接口" → **backend_api**（"自定义数据查询接口"是后端接口）
- 主体是"组件/控件/选择器/输入框" → **web_component_dual**

## 示例

用户需求 → 场景代码
"创建一个项目分析图表自开发页面" → web_page
"做一个数据看板页面" → web_page
"开发一个员工查询菜单页面" → web_page
"做一个自定义日期范围选择器" → web_component_dual
"开发一个关联数据选择组件" → web_component_dual
"写一个员工信息展示的富文本输入框" → web_component_dual
"开发一个移动端的评分组件" → web_component_dual
"做一个手机端表单控件" → web_component_dual
"创建一个只需要PC端的表单组件" → web_component_dual
"开发一个仅PC端使用的自定义输入框" → web_component_dual
"开发一个 SpringBoot 接口查询订单数据" → backend_api
"开发一个自定义数据查询接口" → backend_api
"写一个查询用户信息的后端接口" → backend_api
"用 FeignClient 调用外部天气 API" → backend_feign
"每天凌晨同步一次数据，定时任务" → backend_scheduled
"写一段 JS 脚本校验表单" → unsupported_script
"表单提交前弹窗让用户二次确认" → unsupported_script
"调整表单里某个字段的背景色" → unsupported_script"""

    raw = await _brainstorm_llm_call(
        tenant_id, model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户需求：{user_input}"},
        ],
        max_tokens=20,
        temperature=0,
    )
    # 调试：记录原始响应前 500 字符
    logger.info(f"[detect_scene] LLM RAW (first 500): {raw[:500]!r}")
    # 清理 LLM reasoning tag（MiniMax 等推理模型会返回 <think>...</think> 前缀）
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    # 降级：如果只有开标签没闭合，取 </think> 之后的内容；若完全没闭合也没外部正文，从 think 内尝试提取最后一个场景代码
    if not cleaned:
        # 没外部正文 — 尝试从原始 raw 里捡最后一个合法 scene_code
        for candidate in re.findall(r"\b(web_component_dual|web_page|mobile_page|backend_api|backend_feign|backend_scheduled|web_component|web_list_view|web_layout|web_login|web_plugin|unsupported_script)\b", raw, flags=re.IGNORECASE):
            cleaned = candidate
        logger.warning(f"[detect_scene] 清洗后为空，从 raw 提取: {cleaned!r}")
    scene_code = cleaned.lower().split("\n")[-1].strip().strip("`").strip('"').strip("'")
    logger.info(f"[detect_scene] LLM 返回（清洗后）: {scene_code!r}")
    if scene_code == "unsupported_script":
        raise UnsupportedSceneError(
            "当前需求属于业务事件脚本 / 弹窗 / CSS 样式 / 列表自定义模块类场景，"
            "本智能开发模块暂不支持。请改用【辅助搭建】模块完成。"
        )
    try:
        return SceneType(scene_code)
    except ValueError:
        logger.warning(f"[detect_scene] 无法识别场景 '{scene_code}'，使用默认 web_component_dual")
        return SceneType.WEB_COMPONENT_DUAL


async def _generate_brainstorm_proposal(
    tenant_id: Optional[int],
    model: str,
    scene_type: SceneType,
    *,
    requirement: str,
    previous_proposal: Optional[str] = None,
    user_feedback: Optional[str] = None,
) -> str:
    """LLM 生成结构化开发 SPEC 确认单（使用租户 coding LLM 配置）。

    首轮调用：只传 requirement（用户原始消息），走场景首轮 prompt 模板。
    修改轮调用：同时传 previous_proposal（上一版开发 SPEC）+ user_feedback（用户新反馈），
    走 _BRAINSTORM_REVISION_PROMPT，强制 LLM 做最小修改、歧义反问、需求覆盖校验。
    """
    if previous_proposal and user_feedback:
        prompt = _BRAINSTORM_REVISION_PROMPT.format(
            original_requirement=requirement[:1000],
            previous_proposal=previous_proposal[:2500],
            user_feedback=user_feedback[:500],
        )
        max_tokens = 1500  # 修改轮需要输出变更 diff + 需求覆盖校验，稍放宽
    else:
        prompt_tpl = _BRAINSTORM_PROMPTS.get(scene_type, _BRAINSTORM_PROMPT_PAGE)
        prompt = prompt_tpl.format(message=requirement[:1000])
        max_tokens = 1400
    try:
        return await _brainstorm_llm_call(
            tenant_id, model,
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning(f"Brainstorm generation failed: {e}")
        return ""


async def _classify_brainstorm_response(
    tenant_id: Optional[int],
    model: str,
    user_message: str,
) -> str:
    """
    LLM 分类用户对开发 SPEC 的回复意图。
    Returns: 'confirm' | 'revise' | 'abort'
    """
    # 快速关键词判断，避免 LLM 分类不稳定
    msg = user_message.strip()
    msg_lower = msg.lower()
    _CONFIRM_KEYWORDS = {"好的", "可以", "没问题", "确认", "开始", "生成", "同意", "ok", "yes", "对", "行", "好"}
    _ABORT_KEYWORDS = {"取消", "不做了", "算了", "放弃", "abort"}
    _REVISE_KEYWORDS = {
        "改", "修改", "不对", "应该", "加", "删", "换", "调整", "需要", "要",
        "接口", "api", "调用", "服务", "数据源", "数据来源", "低代码", "表单", "模型",
        "权限", "字段", "筛选", "过滤", "图表", "页面", "验收", "依赖",
    }
    _QUESTION_KEYWORDS = {"？", "?", "吗", "如何", "怎么", "为什么", "能否", "是否", "可否", "能不能", "可不可以", "是不是", "有没有"}
    if any(kw in msg_lower for kw in _ABORT_KEYWORDS):
        return "abort"

    # 只有非常短的纯确认才进入代码生成；任何追问或新增约束都回到 SPEC 修订。
    if any(kw in msg_lower for kw in _QUESTION_KEYWORDS):
        return "revise"
    if any(kw in msg_lower for kw in _REVISE_KEYWORDS):
        return "revise"

    compact_msg = re.sub(r"[\s，,。.!！]+", "", msg_lower)
    confirm_patterns = {
        "好的", "可以", "没问题", "确认", "开始", "生成", "同意", "ok", "yes", "对", "行", "好",
        "确认开始", "可以开始", "开始生成", "按这个来", "就这样", "没问题开始",
    }
    if compact_msg in confirm_patterns or (len(compact_msg) <= 12 and any(kw in compact_msg for kw in _CONFIRM_KEYWORDS)):
        return "confirm"

    prompt = (
        "判断用户对开发 SPEC 的回复意图，只回复 CONFIRM、REVISE 或 ABORT，不要其他内容。\n\n"
        "- CONFIRM：只包含确认方案、同意、开始生成（如：好的、没问题、确认、开始、ok）\n"
        "- REVISE：要求修改、补充约束、追问是否可行、讨论接口/数据源/服务/低代码复用（如：接口能否...、可以通过...吗、应该是...、加个...）\n"
        "- ABORT：取消、不做了\n\n"
        f"用户回复：{user_message}"
    )
    try:
        answer = await _brainstorm_llm_call(
            tenant_id, model,
            [{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        answer = answer.upper()
        if "ABORT" in answer:
            return "abort"
        if "REVISE" in answer:
            return "revise"
        if "CONFIRM" in answer:
            return "confirm"
        return "revise"
    except Exception:
        return "revise"  # 分类失败时保守留在 SPEC 修订阶段，避免误触发代码生成


_BRAINSTORM_KEBAB_RE = re.compile(r"\*\*组件名称\*\*[：:]\s*([^（(]+?)\s*[（(]\s*`([a-z][a-z0-9-]*)`\s*[）)]")
_BRAINSTORM_CODE_RE = re.compile(r"\*\*代码标识\*\*[：:]\s*`(FORM_CUSTOM_[A-Z0-9_]+)`")


def _parse_brainstorm_metadata(proposal: str) -> dict:
    """从 brainstorm proposal markdown 中提取 form-component 命名 metadata。

    匹配 _BRAINSTORM_PROMPT_FORM_COMPONENT 的输出格式：
        **组件名称**：[中文名]（`kebab-case英文名`）
        **代码标识**：`FORM_CUSTOM_XXX`

    返回 dict（任一字段缺失则为 None）：
        {"display_name": "...", "short_kebab": "...", "widget_code": "FORM_CUSTOM_..."}

    用于"延迟到 T4 创建工作区"模式：用户确认 brainstorm 后，从 proposal 提取
    final 命名直接传给 create_workspace，避免事后 rename。
    """
    result: dict = {"display_name": None, "short_kebab": None, "widget_code": None}
    if not proposal:
        return result
    m = _BRAINSTORM_KEBAB_RE.search(proposal)
    if not m:
        m = re.search(r"\*\*(?:页面名称|列表名称)\*\*[：:]\s*([^（(]+?)\s*[（(]\s*`([a-z][a-z0-9-]*)`\s*[）)]", proposal)
    if not m:
        m = re.search(r"\*\*接口名称\*\*[：:]\s*([^（(]+?)\s*[（(]\s*`([a-z][A-Za-z0-9]*)`\s*[）)]", proposal)
    if m:
        result["display_name"] = m.group(1).strip()
        result["short_kebab"] = m.group(2).strip()
    m = _BRAINSTORM_CODE_RE.search(proposal)
    if m:
        result["widget_code"] = m.group(1).strip()
    return result


def _get_brainstorm_state(history: list) -> tuple:
    """
    检查对话是否处于等待 brainstorm 确认状态。
    Returns: (proposal_text, original_requirement, revision_count) or (None, None, 0)

    revision_count = 历史中 brainstorm 提案的总数（用于限制最大修改次数）
    """
    revision_count = 0
    last_proposal: Optional[str] = None
    original_req = ""

    for i, msg in enumerate(history):
        if msg["role"] == "assistant":
            content = msg.get("content", "")
            if content.startswith(BRAINSTORM_PROPOSAL_MARKER):
                revision_count += 1
                last_proposal = content[len(BRAINSTORM_PROPOSAL_MARKER):].strip()
                # 找此提案前最近的用户消息作为"原始需求"
                for j in range(i - 1, -1, -1):
                    if history[j]["role"] == "user":
                        original_req = history[j].get("content", "")
                        break

    # 只有最后一条 assistant 消息是 brainstorm 提案时才算"等待确认"
    for msg in reversed(history):
        if msg["role"] == "assistant":
            if msg.get("content", "").startswith(BRAINSTORM_PROPOSAL_MARKER):
                return last_proposal, original_req, revision_count
            break

    return None, None, 0


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
        # ---- 迭代意图判断 ----
        if is_iteration:
            if await is_new_component_intent(generator, params.message, ws_id, ws_mgr):
                is_iteration = False
                ws_id = None
                yield _record_event({"type": "content", "content": "💡 检测到你想做一个新组件，正在为你创建新的工作区...\n\n"})

        # ---- 意图门：仅对首轮(not is_iteration)生效 ----
        # BUILD(保守兜底): 走原 codegen 流程，完全不变。
        # READ: 用只读 aPaaS 工具直接答问题，不建 workspace、不 codegen。
        if not is_iteration:
            _intent = await classify_coding_intent(
                params.tenant_id, effective_model,
                params.message.split("\n")[0][:300],  # 只取首行，与 detect_scene 对齐
            )
            if _intent == "READ":
                logger.info("[intent_gate] READ 路径，跳过 codegen")
                # 读路径也要存会话历史(否则刷新/回看时 Q&A 丢失)。
                if not conversation_id:
                    _read_conv = Conversation(
                        title=params.message[:50], user_id=params.user_id,
                        tenant_id=params.tenant_id, agent_type="coding",
                        workspace_id=None, selected_llm_config_id=effective_model_config_id,
                    )
                    db.add(_read_conv)
                    await db.commit()
                    await db.refresh(_read_conv)
                    conversation_id = _read_conv.id
                await save_coding_message(db, conversation_id, "user", params.message)
                _answer_parts: list[str] = []
                async for _ev in run_read_query(params, db):
                    if _ev.get("type") == "content":
                        _answer_parts.append(str(_ev.get("content") or ""))
                    if _ev.get("type") == "done":
                        _ev["conversation_id"] = conversation_id
                    yield _record_event(_ev)
                _read_answer = "\n\n".join(p for p in _answer_parts if p.strip()).strip()
                if _read_answer:
                    await save_coding_message(db, conversation_id, "assistant", _read_answer)
                return

        # 预加载对话历史（不含本轮 user message）。用途：
        # 1) 判断是否处于 brainstorm 续轮：若上一条 assistant 是 brainstorm 提案，
        #    本轮 user message 是 confirm/revise/abort 回复，**不能**用它做场景识别
        #    （否则"确认"两个字会被识别成业务事件弹窗）
        # 2) brainstorm 续轮时用 original_requirement（首条用户消息）重做场景识别
        # 3) 提供给 brainstorm 决策与 agent 上下文使用，避免重复 fetch
        prior_history: list = []
        if conversation_id and not is_iteration:
            try:
                prior_history = await get_conversation_history(db, conversation_id)
            except Exception:
                prior_history = []
        prior_brainstorm_proposal, prior_original_requirement, prior_revision_count = _get_brainstorm_state(prior_history)

        # ---- Step 1: 场景检测 ----
        if not replay_stream_messages:
            _push_replay_message(replay_stream_messages, "user", params.message)

        if not is_iteration:
            # brainstorm 续轮（用户回复"确认/再改一下"）：场景已在首轮识别并通知过前端，
            # 本轮只做静默识别（scene_type 下游还要用，例如选 brainstorm 模板、生成 project_type），
            # 不再 emit detect_scene step / scene_detected，避免前端出现两张 "识别为..." badge
            is_brainstorm_continuation = bool(prior_brainstorm_proposal)
            if not is_brainstorm_continuation:
                yield _record_event({"type": "step", "step": "detect_scene", "status": "running"})
            # brainstorm 续轮：必须用 original_requirement 而非 params.message
            detection_message = prior_original_requirement if prior_brainstorm_proposal else params.message
            # 始终用 AI 从 message 识别场景，project_type 仅作降级兜底
            # 只取第一行（用户的直接意图），避免后面附带的 API 文档等内容干扰识别
            intent_snippet = detection_message.split("\n")[0][:300]
            fallback = SceneType.WEB_COMPONENT_DUAL
            scene_detection_failed = False
            try:
                scene_type = await _detect_scene_llm_call(params.tenant_id, effective_model, intent_snippet)
            except UnsupportedSceneError as exc:
                yield _record_event({
                    "type": "step", "step": "detect_scene", "status": "done",
                    "data": {"scene_type": "unsupported_script"},
                })
                yield _record_event({"type": "message", "content": str(exc)})
                yield _record_event({"type": "done", "ws_id": None, "ide_url": None, "conversation_id": conversation_id})
                return
            except Exception:
                logger.warning(f"场景识别失败，使用兜底场景 {fallback}: {traceback.format_exc()}")
                scene_type = fallback
                scene_detection_failed = True
            # data 里带 fallback 标记（识别失败兜底时为 True），让前端可感知降级；
            # 正常路径不带该 key，保持原有结构兼容
            scene_done_data: dict = {"scene_type": scene_type.value}
            if scene_detection_failed:
                scene_done_data["fallback"] = True
            yield _record_event({"type": "step", "step": "detect_scene", "status": "done", "data": scene_done_data})
            # 通知前端 scene_detected + conversation_id（如果已有）
            yield _record_event({"type": "scene_detected", "conversation_id": conversation_id})
        else:
            info = ws_mgr.get_workspace_info(ws_id)
            pt = info.get("project_type", "form-component-dual")
            scene_type = PROJECT_TYPE_TO_SCENE.get(pt, SceneType.WEB_COMPONENT_DUAL)

        # ---- Step 2: 创建/恢复对话（不创建工作区，workspace_id 此时可为 None）----
        # 工作区创建延迟到"用户确认 brainstorm 后"或"非 brainstorm 场景的首次进入"。
        # brainstorm 阶段（abort / revise）若工作区还未创建，磁盘零落地、无 stale 残留。
        # 2026-05-19 不管是新建还是迭代（is_iteration=True 也算），conversation_id 为空时
        # 必须创建一条 Conversation，否则下面 save_coding_message 撞 NULL constraint。
        # 之前 `if not is_iteration` 包住创建逻辑导致 ws_id 存在但 conv 为 None 时直接挂。
        if not conversation_id:
            coding_conversation = Conversation(
                title=params.message[:50], user_id=params.user_id,
                tenant_id=params.tenant_id, agent_type="coding",
                workspace_id=ws_id if is_iteration else None,
                selected_llm_config_id=effective_model_config_id,
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

        # 对话历史：复用 step 1 之前预加载的 prior_history（不含本轮 user message，
        # 但 brainstorm 状态判断与场景识别都基于"上一轮结束后的状态"，对就该这样）。
        # iteration 模式 prior_history 是空的，需要补加载一次。
        if is_iteration and conversation_id:
            try:
                prior_history = await get_conversation_history(db, conversation_id)
            except Exception:
                prior_history = []
            prior_brainstorm_proposal, prior_original_requirement, prior_revision_count = _get_brainstorm_state(prior_history)
        history = prior_history
        conversation_summary = ""
        if history:
            conversation_summary = "\n".join(
                f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')[:200]}"
                for m in history[-6:]
            )

        # ── 创建工作区的本地辅助（必要时调用）──────────────
        # 优先用 brainstorm proposal 提取的 short_kebab / display_name 命名（form-component
        # 类，folder 一次定型不再 rename）；缺失时回退 extract_project_name。
        # 创建后立即把 conversation.workspace_id 关联上，event yield create_workspace step。
        async def _create_workspace_now(brainstorm_for_naming: Optional[str]) -> tuple[str, dict]:
            """创建工作区并关联 conversation。返回 (ws_id, done_event_data)。

            优先使用 brainstorm proposal 提取的 short_kebab/display_name 给工作区命名；
            缺失时回退到 extract_project_name。folder name 一旦创建后不再变化。
            """
            nonlocal coding_conversation
            project_type_str = scene_to_project_type(scene_type) or "form-component-dual"
            project_type_enum_local = ProjectType(project_type_str)

            project_name: Optional[str] = None
            display_name_value: Optional[str] = None
            if brainstorm_for_naming:
                bs = _parse_brainstorm_metadata(brainstorm_for_naming)
                if bs.get("short_kebab"):
                    project_name = bs["short_kebab"]
                if bs.get("display_name"):
                    display_name_value = bs.get("display_name")

            if not project_name:
                try:
                    project_name = await extract_project_name(generator, params.message)
                except Exception:
                    project_name = "custom-dev"

            if not display_name_value:
                display_name_value = extract_display_name(params.message, project_type_str, project_name)

            meta_local = ws_mgr.create_workspace(
                project_type_enum_local, project_name, params.user_id,
                project_id=project_id, display_name=display_name_value,
            )
            new_ws_id = meta_local["id"]
            if coding_conversation is not None:
                coding_conversation.workspace_id = new_ws_id
                await db.commit()
                await db.refresh(coding_conversation)
            return new_ws_id, {
                "workspace_id": new_ws_id,
                "project_name": meta_local["project_name"],
                "display_name": meta_local.get("display_name", meta_local["project_name"]),
            }

        # ── Brainstorm 需求澄清 ──────────────────────────
        effective_requirement = params.message
        # 直接复用 step 1 之前已经从 prior_history 提取的 brainstorm 状态
        brainstorm_proposal, original_requirement, revision_count = (
            prior_brainstorm_proposal, prior_original_requirement, prior_revision_count
        )

        if brainstorm_proposal:
            # 已有 brainstorm 提案：处理 abort/revise/confirm
            intent = await _classify_brainstorm_response(params.tenant_id, effective_model, params.message)
            if revision_count >= BRAINSTORM_MAX_REVISIONS and intent == "revise":
                logger.info(f"Brainstorm has {revision_count} revisions; continue revising instead of forcing confirm")

            if intent == "abort":
                yield _record_event({"type": "content", "content": "已取消。如需重新开始请描述新需求。"})
                # brainstorm 阶段工作区还未创建 → ws_id=None, ide_url=None；
                # 前端依据 ide_url 决定 IDE 标签是否可点（None 时禁用）。
                yield _record_event({"type": "done", "workspace_id": None,
                                     "conversation_id": conversation_id, "ide_url": None})
                return

            elif intent == "revise":
                new_proposal = await _generate_brainstorm_proposal(
                    params.tenant_id, effective_model, scene_type,
                    requirement=original_requirement,
                    previous_proposal=brainstorm_proposal,
                    user_feedback=params.message,
                )
                if new_proposal:
                    await save_coding_message(db, conversation_id, "assistant",
                                              BRAINSTORM_PROPOSAL_MARKER + new_proposal)
                    yield _record_event({"type": "content", "content": new_proposal})
                yield _record_event({
                    "type": "done", "workspace_id": None,
                    "conversation_id": conversation_id, "ide_url": None,
                    "waiting_confirmation": True,
                })
                return

            else:
                # 用户明确确认：用原始需求 + 确认的开发 SPEC 作为 Agent 完整上下文
                effective_requirement = (
                    f"{original_requirement}\n\n"
                    f"[开发 SPEC 已确认，请严格按以下 SPEC 生成代码，无需再向用户确认]\n"
                    f"{brainstorm_proposal}"
                )
                # ★ 此处才创建工作区，按 brainstorm 提取的 final 命名定型
                yield _record_event({"type": "step", "step": "create_workspace", "status": "running"})
                ws_id, _data = await _create_workspace_now(brainstorm_for_naming=brainstorm_proposal)
                yield _record_event({"type": "step", "step": "create_workspace", "status": "done", "data": _data})

        elif not is_iteration and scene_type in BRAINSTORM_SCENES:
            # 首次发起 brainstorm：生成开发 SPEC 作为 inline 提示后直接继续开发流程，
            # 不再强制等待用户确认（B3: 去掉两段式确认门）。
            # proposal 仍然输出，供用户阅读；workspace 在下方按需创建。
            _inline_brainstorm_proposal: str = ""
            yield _record_event({"type": "step", "step": "brainstorm", "status": "running"})
            proposal = await _generate_brainstorm_proposal(
                params.tenant_id, effective_model, scene_type,
                requirement=params.message,
            )
            if proposal:
                _inline_brainstorm_proposal = proposal
                await save_coding_message(db, conversation_id, "assistant",
                                          BRAINSTORM_PROPOSAL_MARKER + proposal)
                yield _record_event({"type": "step", "step": "brainstorm", "status": "done"})
                yield _record_event({"type": "content", "content": proposal})
                # 用 SPEC 丰富代码生成上下文
                effective_requirement = (
                    f"{params.message}\n\n"
                    f"[开发 SPEC 已生成，请严格按以下 SPEC 生成代码]\n"
                    f"{proposal}"
                )
            else:
                # proposal 失败：降级直接走 codegen，无 SPEC 上下文
                yield _record_event({"type": "step", "step": "brainstorm", "status": "done"})
                logger.warning("Brainstorm proposal generation failed, falling back to direct codegen")

        # 走到这里有四种情况，且 ws_id 可能仍是 None：
        #   1. iteration 模式（ws_id 已存在，跳过）
        #   2. 非 brainstorm 场景
        #   3. brainstorm 首轮（B3 去门：inline 输出提案后继续，_inline_brainstorm_proposal 有值）
        #   4. brainstorm proposal 失败降级
        # 情况 2/3/4 ws_id 仍是 None → 按 inline proposal（若有）或原始消息命名创建工作区。
        if not ws_id:
            _naming_proposal = locals().get("_inline_brainstorm_proposal") or None
            yield _record_event({"type": "step", "step": "create_workspace", "status": "running"})
            ws_id, _data = await _create_workspace_now(brainstorm_for_naming=_naming_proposal)
            yield _record_event({"type": "step", "step": "create_workspace", "status": "done", "data": _data})

        # ---- Agent 代码生成 ----
        yield _record_event({"type": "step", "step": "generate", "status": "running"})

        # 运行 Agent（CodingAgent + Stream Adapter）
        from app.agents.coding import CodingAgent, CodingAgentStreamAdapter
        from app.agents.coding.llm_config import load_coding_llm_config
        from app.agents.publisher import InMemoryEventPublisher
        from app.agents.trace_writer import InMemoryTraceWriter
        from app.agents.types import AgentContext
        from app.llm_client import LLMClient

        _base_url, _api_key, _cfg_model = await load_coding_llm_config(
            params.tenant_id, effective_model,
        )
        _coding_llm = LLMClient(api_key=_api_key, base_url=_base_url, model=_cfg_model)

        # Phase D: prefer DB-stored prompt for agent_id='whale' (Coding), fall
        # back to AGENT_SYSTEM_PROMPT when the row is missing (lazy seed inside
        # resolve_prompt will populate on first call per tenant).
        from app.services.prompt_resolver import resolve_prompt
        _coding_system_prompt = await resolve_prompt(
            db, params.tenant_id,
            agent_id="whale", phase="default",
            fallback=AGENT_SYSTEM_PROMPT,
        )

        _coding_ctx = AgentContext(
            session_id=f"cs_{ws_id}",
            conversation_id=conversation_id or 0,
            user_id=params.user_id,
            tenant_id=params.tenant_id,
            model=_cfg_model,
            workspace_id=ws_id,
            input={"system_prompt": _coding_system_prompt},
            publisher=InMemoryEventPublisher(),   # adapter 会 wrap 成 queue publisher
            trace_writer=InMemoryTraceWriter(),   # Stage 4 后接 DB
            llm_client=_coding_llm,
        )
        _coding_agent = CodingAgent(_coding_ctx)
        agent = CodingAgentStreamAdapter(_coding_agent)
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
                requirement=effective_requirement,
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
        # 双端工程 scene 目录归一化只能在 agent 全部跑完后做一次。
        # 不能内嵌进 _write_file 后置链路——LLM 写实现 vue 与写 widget.config.json
        # 之间存在 semantic 不一致的中间窗口，期间归一化会把刚写入的真实业务
        # 文件当 stray 误删。
        finalize_changed = finalize_form_component_dual_workspace(workspace_path)
        if finalize_changed:
            normalized_files.extend(finalize_changed)
            logger.info("Finalized form-component-dual scene dirs for %s: %s", ws_id, finalize_changed)
        # 工作区 folder name 一旦创建即永久不变（避免 .vibe-ide.code-workspace 绝对路径
        # 失效、IDE URL 缓存失效、agent 持有的 ws_path 失效等连锁问题）。
        # 包名走 apaas.json 的 outputName，与 folder name 解耦。
        # form-component-dual 的命名定型在创建工作区时一次性完成（见 _create_workspace_now，
        # 调用时机是用户确认 brainstorm 后；首次 brainstorm 提案阶段工作区还未创建）。
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
            # 迭代时也带上 ide_url，防止 outputName 变化导致文件夹改名后前端路径失效
            iter_ide_url = _build_ide_url_for_pipeline(params, ws_id, conversation_id, effective_model)
            yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id,
                                  "ide_url": iter_ide_url})
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
    return base + "platform/" if base else ""


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
