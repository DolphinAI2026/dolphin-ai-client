"""read_query.py — AI Coding 只读应答路径

当用户意图为「读/问」(READ) 时，不建 workspace、不 codegen，
直接用只读 aPaaS 工具 + LLM tool-loop 回答问题，emit 工具 chip + 文字 + done。

主要出口：
  classify_coding_intent(tenant_id, model, message) -> "READ" | "BUILD"
  run_read_query(params, db)                        -> AsyncIterator[dict]
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coding.apaas_tools import (
    APAAS_TOOL_DEFINITIONS,
    APAAS_TOOL_EXECUTORS_PLATFORM,
)
from app.coding.workspace_read_tools import (
    WORKSPACE_TOOL_DEFINITIONS,
    WORKSPACE_TOOL_DISPLAY,
    WORKSPACE_TOOL_NAMES,
    execute_workspace_tool,
)

logger = logging.getLogger(__name__)

# ── 只给读路径暴露的只读工具子集 ──────────────────────
_READ_ONLY_TOOL_NAMES = {
    "list_apaas_apps",
    "list_apaas_app_menus",
    "list_apaas_form_views",
    "list_apaas_form_components",
    "list_apaas_app_models",
    "list_apaas_app_dicts",
    "get_apaas_app_overview",
    "list_apaas_models_in_env",
    "check_app_code_conflict",
}

_CURRENT_WORKSPACE_APP_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_workspace_app_status",
        "description": (
            "查询当前 Coding 工作区绑定的应用状态、aPaaS 绑定信息、以及本地最近成功发布记录。"
            "当用户问“应用是否重新发布/是否上传到应用/是否已接入平台/发布状态”时，"
            "优先调用本工具，不要只从源码或构建产物推断。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_id": {
                    "type": "integer",
                    "description": "可选，本地 ai-builder Application.id。不传时从当前会话或工作区元数据解析。",
                }
            },
            "required": [],
        },
    },
}

_SEARCH_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_tools",
        "description": (
            "搜索当前 Coding 只读问答可用的工具。仅返回只读工具；不会激活部署、发布、写文件等写操作工具。"
            "当你不确定该用哪个工具时，先用关键词搜索，或用 select:工具名 精确选择。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "关键词，或 select:工具名1,工具名2 精确选择。",
                }
            },
            "required": ["query"],
        },
    },
}

_LOCAL_READ_TOOL_DEFINITIONS = [
    _CURRENT_WORKSPACE_APP_STATUS_TOOL,
    _SEARCH_TOOLS_TOOL,
]
_LOCAL_READ_TOOL_NAMES = {
    t["function"]["name"] for t in _LOCAL_READ_TOOL_DEFINITIONS
}

READ_ONLY_TOOL_DEFINITIONS: list[dict] = [
    t for t in APAAS_TOOL_DEFINITIONS
    if t.get("function", {}).get("name") in _READ_ONLY_TOOL_NAMES
]

_READ_TOOL_DEFINITIONS_BY_NAME: dict[str, dict] = {
    t.get("function", {}).get("name"): t
    for t in [*READ_ONLY_TOOL_DEFINITIONS, *_LOCAL_READ_TOOL_DEFINITIONS]
    if t.get("function", {}).get("name")
}

# tool executors 也只暴露只读子集，防止工具名冲突时意外执行写操作
_READ_ONLY_EXECUTORS: dict[str, Any] = {
    k: v for k, v in APAAS_TOOL_EXECUTORS_PLATFORM.items()
    if k in _READ_ONLY_TOOL_NAMES
}

# 读路径 tool-loop 最大轮数（避免 LLM 死循环）
_READ_MAX_TURNS = 8

# 只读工具 → 人话标签（给前端工具卡显示，避免暴露技术工具名）
_TOOL_DISPLAY = {
    "list_apaas_apps": "读取应用列表",
    "list_apaas_app_menus": "读取菜单",
    "list_apaas_form_views": "读取表单视图",
    "list_apaas_form_components": "读取表单组件",
    "list_apaas_app_models": "读取数据模型",
    "list_apaas_app_dicts": "读取数据字典",
    "get_apaas_app_overview": "读取应用概览",
    "list_apaas_models_in_env": "读取环境模型",
    "check_app_code_conflict": "检查应用编码",
    "get_current_workspace_app_status": "查询应用状态",
    "search_tools": "搜索工具",
    **WORKSPACE_TOOL_DISPLAY,
}

# ─────────────────────────── 意图分类 ─────────────────────────────


async def classify_coding_intent(
    tenant_id: Optional[int],
    model: str,
    message: str,
) -> str:
    """轻量 LLM 调用：判断用户意图是「读/问」(READ) 还是「建代码」(BUILD)。

    保守兜底：任何失败或拿不准 → BUILD。
    绝不把"建代码"误判为 READ。
    """
    # 快速关键词判断 — 明确建代码关键词直接 BUILD，避免 LLM 延迟
    msg_lower = message.lower()
    _BUILD_KEYWORDS = {
        "建", "做", "创建", "新建", "写", "生成", "开发", "实现", "搭建", "构建",
        "编写", "制作", "设计", "做一个", "写一个", "建一个", "来一个",
        "组件", "页面", "接口", "api", "控件", "组件", "插件",
        "springboot", "vue", "react", "java", "python",
    }
    for kw in _BUILD_KEYWORDS:
        if kw in msg_lower:
            return "BUILD"

    system_prompt = """你是 AI Coding 模块的意图分类助手。
根据用户消息，判断用户意图是「读/查询」还是「建代码/开发」，只输出以下之一：
- READ：用户只想查询/了解现有平台信息（如：查看应用列表、读模型字段、了解菜单结构、查看字典等）
- BUILD：用户想开发/创建/修改代码或应用（如：建组件、写页面、开发接口、新建应用等）

**保守原则：不确定时输出 BUILD。**
只有消息明确是纯查询/读取且无任何创建/开发意图时才输出 READ。

示例：
"读一下有哪些应用" → READ
"列出所有应用" → READ
"这个模型有哪些字段" → READ
"查看图书借阅应用的菜单" → READ
"有哪些字典" → READ
"建个图书首页双端组件" → BUILD
"做一个数据查询页面" → BUILD
"写一个后端接口" → BUILD
"帮我创建应用" → BUILD
"上传文件组件" → BUILD"""

    try:
        from app.agents.coding.llm_config import load_coding_llm_config
        from app import llm_transport

        base_url, api_key, llm_model = await load_coding_llm_config(tenant_id, model)

        payload = llm_transport.build_chat_payload(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户消息：{message[:300]}"},
            ],
            temperature=0,
            max_tokens=10,
            base_url=base_url,  # qwen3/dashscope → enable_thinking=False(此前分类器漏了)
        )
        msg = await llm_transport.complete(
            base_url=base_url,
            api_key=api_key,
            payload=payload,
            timeout=httpx.Timeout(connect=8, read=20, write=8, pool=8),
        )
        raw = (msg.get("content") or "").strip()
        # 清理 reasoning tag
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
        label = cleaned.upper().split()[0] if cleaned else "BUILD"
        if label == "READ":
            logger.info("[intent] 分类=READ, message=%r", message[:100])
            return "READ"
    except Exception as exc:
        logger.warning("[intent] 分类失败，兜底 BUILD: %s", exc)

    return "BUILD"


async def classify_iteration_intent(
    tenant_id: Optional[int],
    model: str,
    message: str,
) -> str:
    """迭代轮(已有工作区)的「读/问」vs「改代码」分类。

    与首轮 classify_coding_intent 的差异：
    - 不用关键词快捷路径——迭代轮聊的就是组件/页面/代码，
      "讲讲这个页面" 含 "页面" 不能秒判 BUILD。
    - 拿不准 → READ。误判成 READ 顶多多问一句；误判成 BUILD
      会未经同意重写用户代码（实际发生过的事故），代价不对称。
    - 基础设施异常(LLM 挂了) → BUILD 维持旧行为，反正 codegen
      也会在下游用同一配置报错，错误能露出来。
    """
    system_prompt = """当前会话绑定了一个已有的代码工作区，用户在和一个能读写代码的 AI 开发助手对话。
判断这条消息的意图，只输出以下之一：
- READ：只想看/问/解释/分析/评审代码或项目，不要求改动任何文件
- BUILD：要求修改/新增/修复/重构/优化/删除代码，或要求构建/打包/部署/上传

**拿不准时输出 READ（宁可先回答，绝不未经同意改代码）。**
只有消息明确要求动手改代码或执行构建动作时才输出 BUILD。

示例：
"读一下工作区的代码" → READ
"讲讲这个页面的逻辑" → READ
"src/page.vue 是干嘛的" → READ
"现在的实现有什么问题" → READ
"评审一下这次的改动" → READ
"这个接口为什么这么写" → READ
"把按钮改成红色" → BUILD
"加一个导出功能" → BUILD
"修复刚才那个报错" → BUILD
"重构 page.vue" → BUILD
"按你说的优化一下" → BUILD
"重新打包上传" → BUILD"""

    try:
        from app.agents.coding.llm_config import load_coding_llm_config
        from app import llm_transport

        base_url, api_key, llm_model = await load_coding_llm_config(tenant_id, model)
        payload = llm_transport.build_chat_payload(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户消息：{message[:300]}"},
            ],
            temperature=0,
            max_tokens=10,
            base_url=base_url,  # qwen3/dashscope → enable_thinking=False(此前分类器漏了)
        )
        msg = await llm_transport.complete(
            base_url=base_url,
            api_key=api_key,
            payload=payload,
            timeout=httpx.Timeout(connect=8, read=20, write=8, pool=8),
        )
        raw = (msg.get("content") or "").strip()
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
        label = cleaned.upper().split()[0] if cleaned else "BUILD"
        logger.info("[intent] 迭代轮分类=%s, message=%r", label, message[:100])
        return "READ" if label == "READ" else "BUILD"
    except Exception as exc:
        logger.warning("[intent] 迭代轮分类失败，兜底 BUILD: %s", exc)
        return "BUILD"


# ─────────────────────────── platform_env_id 解析 ──────────────────────────


async def _resolve_read_platform_env_id(
    tenant_id: Optional[int],
    db: AsyncSession,
) -> Optional[int]:
    """从租户默认 PlatformEnv 拿 platform_env_id（给读路径用）。"""
    if not tenant_id:
        return None
    try:
        from app.models import PlatformEnv

        res = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == tenant_id,
                PlatformEnv.is_default == True,  # noqa: E712
            ).limit(1)
        )
        env = res.scalar_one_or_none()
        if env:
            return int(env.id)
    except Exception as exc:
        logger.warning("[read_query] 解析 platform_env_id 失败: %s", exc)
    return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _read_workspace_meta(ws_path: Optional[Path]) -> dict:
    if not ws_path:
        return {}
    meta_path = ws_path / ".workspace.json"
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("[read_query] 读取 workspace meta 失败: %s", exc)
        return {}


async def _load_bound_application(
    *,
    params: "PipelineParams",
    args: dict,
    db: AsyncSession,
    ws_path: Optional[Path],
) -> tuple[Any | None, dict[str, Any]]:
    """从 tool 参数、会话绑定和 workspace meta 中解析当前工作区所属 Application。"""
    from app.models import Application, Conversation

    evidence: dict[str, Any] = {
        "requested_app_id": args.get("app_id"),
        "params_app_id": getattr(params, "app_id", None),
        "conversation_id": getattr(params, "conversation_id", None),
        "workspace_id": getattr(params, "workspace_id", None),
        "workspace_project_id": None,
        "resolution": None,
    }

    candidates: list[tuple[str, int]] = []
    for source, value in (
        ("args.app_id", args.get("app_id")),
        ("params.app_id", getattr(params, "app_id", None)),
    ):
        app_id = _safe_int(value)
        if app_id is not None:
            candidates.append((source, app_id))

    conv_id = _safe_int(getattr(params, "conversation_id", None))
    if conv_id is not None:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.tenant_id == params.tenant_id,
            )
        )
        conv = result.scalar_one_or_none()
        conv_app_id = _safe_int(getattr(conv, "coding_app_id", None))
        if conv_app_id is not None:
            candidates.append(("conversation.coding_app_id", conv_app_id))

    workspace_meta = _read_workspace_meta(ws_path)
    workspace_project_id = _safe_int(workspace_meta.get("project_id"))
    evidence["workspace_project_id"] = workspace_project_id
    if workspace_project_id is not None:
        # 这里的 project_id 在自开发资产上下文中被复用为 Application.id。
        candidates.append(("workspace.project_id", workspace_project_id))

    seen: set[int] = set()
    for source, app_id in candidates:
        if app_id in seen:
            continue
        seen.add(app_id)
        result = await db.execute(
            select(Application).where(
                Application.id == app_id,
                Application.tenant_id == params.tenant_id,
            )
        )
        app = result.scalar_one_or_none()
        if app is not None:
            evidence["resolution"] = source
            return app, evidence

    ws_id = str(getattr(params, "workspace_id", "") or "")
    if ws_id:
        result = await db.execute(
            select(Application).where(
                Application.tenant_id == params.tenant_id,
                Application.source_workspace_id == ws_id,
            )
        )
        app = result.scalar_one_or_none()
        if app is not None:
            evidence["resolution"] = "application.source_workspace_id"
            return app, evidence

    return None, evidence


def _build_publish_status(app: Any, latest: Any | None) -> dict[str, Any]:
    last_modified = getattr(app, "updated_at", None) or getattr(app, "created_at", None)
    app_status = str(getattr(app, "status", "") or "").lower()

    if latest is None:
        if app_status == "completed" and getattr(app, "apaas_app_id", None):
            status = "published"
        elif app_status == "failed":
            status = "failed"
        elif app_status in ("generating", "updating"):
            status = "generating"
        else:
            status = "draft"
        return {
            "status": status,
            "latest_deploy": None,
            "pending_changes_count": 0 if status == "published" else (1 if last_modified else 0),
            "last_modified_at": _iso(last_modified),
            "app_status": getattr(app, "status", None),
            "local_deploy_record_found": False,
            "can_confirm_republish_from_local_record": False,
        }

    completed_at = getattr(latest, "completed_at", None)
    has_pending = bool(last_modified and completed_at and last_modified > completed_at)
    return {
        "status": "draft_on_published" if has_pending else "published",
        "latest_deploy": {
            "deploy_id": getattr(latest, "id", None),
            "version": getattr(latest, "version_label", None) or f"v{getattr(latest, 'id', '')}",
            "completed_at": _iso(completed_at),
            "user_id": getattr(latest, "user_id", None),
            "deploy_type": getattr(latest, "deploy_type", None),
        },
        "pending_changes_count": 1 if has_pending else 0,
        "last_modified_at": _iso(last_modified),
        "app_status": getattr(app, "status", None),
        "local_deploy_record_found": True,
        "can_confirm_republish_from_local_record": True,
    }


async def _get_current_workspace_app_status(
    params: "PipelineParams",
    db: AsyncSession,
    ws_path: Optional[Path],
    platform_env_id: Optional[int],
    args: dict,
) -> str:
    """只读查询当前 Coding 工作区绑定应用与发布状态。"""
    app, evidence = await _load_bound_application(
        params=params,
        args=args or {},
        db=db,
        ws_path=ws_path,
    )
    if app is None:
        return json.dumps({
            "ok": False,
            "error_code": "NO_BOUND_APPLICATION",
            "message": "当前 Coding 工作区未解析到绑定应用，无法判断是否已重新发布到 aPaaS。",
            "evidence": evidence,
        }, ensure_ascii=False)

    from app.models.deploy_history import DeployRecord

    result = await db.execute(
        select(DeployRecord)
        .where(DeployRecord.app_id == int(app.id), DeployRecord.status == "success")
        .order_by(DeployRecord.completed_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    remote_detail: dict[str, Any] | None = None
    remote_error: str | None = None
    env_id = _safe_int(getattr(app, "platform_env_id", None)) or platform_env_id
    apaas_app_id = str(getattr(app, "apaas_app_id", "") or "")
    if env_id and apaas_app_id:
        try:
            from app.coding.apaas_tools import call_apaas_with_relogin

            detail = await call_apaas_with_relogin(
                int(env_id),
                db,
                lambda client: client.query_app_detail(apaas_app_id),
            )
            if isinstance(detail, dict):
                remote_detail = {
                    "currentVersion": detail.get("currentVersion"),
                    "appVersion": detail.get("appVersion"),
                    "version": detail.get("version"),
                    "status": detail.get("status"),
                    "isSelfDev": detail.get("isSelfDev"),
                }
        except Exception as exc:
            remote_error = str(exc)

    return json.dumps({
        "ok": True,
        "app": {
            "local_app_id": int(app.id),
            "app_name": getattr(app, "app_name", None),
            "app_code": getattr(app, "app_code", None),
            "app_status": getattr(app, "status", None),
            "platform_env_id": env_id,
            "apaas_app_id": apaas_app_id or None,
            "updated_at": _iso(getattr(app, "updated_at", None)),
        },
        "publish_status": _build_publish_status(app, latest),
        "remote_app_detail": remote_detail,
        "remote_error": remote_error,
        "evidence": evidence,
        "note": (
            "local_deploy_record_found=false 时，只能确认本地应用已绑定/平台应用存在，"
            "不能仅凭工作区源码证明刚刚执行过重新发布。"
        ),
    }, ensure_ascii=False)


def _tokenize_tool_text(text: str) -> list[str]:
    return [p for p in re.split(r"[\s,_\-:;/，。！？、]+", text.lower()) if p]


def _search_read_tools(query: str, ws_path: Optional[Path]) -> str:
    q = (query or "").strip()
    candidates = dict(_READ_TOOL_DEFINITIONS_BY_NAME)
    if ws_path is not None:
        for schema in WORKSPACE_TOOL_DEFINITIONS:
            name = schema.get("function", {}).get("name")
            if name:
                candidates[name] = schema
    candidates.pop("search_tools", None)

    if q.lower().startswith("select:"):
        want = [x.strip() for x in q[len("select:"):].split(",") if x.strip()]
        activated = [name for name in want if name in candidates]
    else:
        terms = _tokenize_tool_text(q)
        scored: list[tuple[int, str]] = []
        for name, schema in candidates.items():
            fn = schema.get("function", {}) or {}
            desc = str(fn.get("description") or "")
            text = f"{name} {desc}".lower()
            name_tokens = set(_tokenize_tool_text(name))
            score = 0
            for term in terms:
                if term in name_tokens:
                    score += 3
                elif term and term in text:
                    score += 1
            if score:
                scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        activated = [name for _, name in scored[:8]]

    return json.dumps({
        "ok": True,
        "activated": activated,
        "message": (
            f"已匹配 {len(activated)} 个只读工具: {', '.join(activated)}"
            if activated else "无匹配只读工具；换个关键词或用 select:工具名"
        ),
        "read_only": True,
    }, ensure_ascii=False)


# ─────────────────────────── 流式 LLM 调用 ─────────────────────────────────

# OpenAI 流式 tool_calls 增量合并收口到 app.llm_transport.merge_tool_call_delta
# (单一来源)。read_query 这个名字仍对外暴露(test_read_query_streaming 直接 import),
# 故保留为别名,逻辑不分叉。
from app.llm_transport import merge_tool_call_delta as merge_stream_tool_call_delta  # noqa: E402


async def _stream_llm(
    base_url: str, api_key: str, payload: dict, sink: dict,
) -> AsyncIterator[str]:
    """流式 chat/completions: 逐段 yield content 增量, 完整 content/tool_calls 落 sink。

    READ 路径以前整轮非流式, 一个回答 1-2 分钟前端只有工具 chip 没有文字;
    流式后最终回答打字机直出。

    SSE 传输收口到 app.llm_transport.stream_raw_sse_lines(与 ai_chat / builder_spec
    同一 httpx 栈); 这里只保留 content/tool_calls 落 sink 的累积语义(逐字不变)。
    enable_thinking 兼容由调用方在 payload 里设(run_read_query 已对 qwen3/dashscope 设)。
    """
    from app import llm_transport

    sink.setdefault("content", "")
    sink.setdefault("tool_calls", [])
    async for raw_line in llm_transport.stream_raw_sse_lines(
        base_url=base_url,
        api_key=api_key,
        payload={**payload, "stream": True},
        timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
    ):
        line = (raw_line or "").strip()
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        delta = (choices[0] or {}).get("delta") or {} if choices else {}
        piece = delta.get("content")
        if piece:
            sink["content"] += piece
            yield piece
        if delta.get("tool_calls"):
            merge_stream_tool_call_delta(sink["tool_calls"], delta["tool_calls"])


# ─────────────────────────── 只读 tool-loop ────────────────────────────────

_READ_SYSTEM_PROMPT = """你是 aPaaS 平台的 AI 助手，帮用户查询和了解平台现有应用、模型、菜单、字典等信息。

工作指引：
- 只调用只读工具查询信息，不创建、不修改任何内容
- 如果用户问当前应用是否已发布/重新发布/接入平台，优先调用 get_current_workspace_app_status
- 如果不确定该用哪个工具，先调用 search_tools 搜索只读工具；search_tools 不会提供任何写入/部署工具
- 调用 list_apaas_apps 先了解有哪些应用，再根据用户需求深入查询
- 用清晰的中文回答用户问题，用 markdown 表格/列表整理信息
- **列出应用时固定用 4 列 markdown 表：序号 | 应用名称 | 应用编码 | 状态**
  （"应用编码"即 app_code；不要输出 apaas_app_id 这类长数字 ID，太占地方、对用户无意义）
  查询模型 / 菜单 / 字典等其它信息时，按内容选用合适的表格列。
- 如果没有可用的平台环境，直接说明并建议用户在「平台管理」中配置环境
- 回答简洁、结构清晰
"""

_READ_WS_SYSTEM_PROMPT = """你是代码工作区的 AI 助手，帮用户阅读、解释、分析当前工作区的代码。

工作指引：
- **本轮只读：只调用只读工具，绝不修改任何文件**（你也没有写工具）
- 如果用户问应用是否已上传/接入/发布/重新发布，先调用 get_current_workspace_app_status；不要只看源码或 zip 产物后下结论
- 如果不确定该用哪个工具，先调用 search_tools 搜索只读工具；search_tools 不会提供任何写入/部署工具
- 先 list_workspace_files 了解项目结构，再用 read_workspace_file / search_workspace_code 深入
- 回答里引用代码位置用 `相对路径:行号` 格式，方便用户点击查看
- 用清晰的中文回答，必要时用代码块/列表整理
- 如果用户的问题其实是要改代码，直接说明"本轮是只读分析，如需修改请明确说出要改什么"，不要试图绕过
- 回答简洁、结构清晰
"""


async def run_read_query(
    params: "PipelineParams",
    db: AsyncSession,
) -> AsyncIterator[dict]:
    """只读应答回路 — tool-calling loop + emit 事件。

    emit 事件类型：
      {"type": "tool", "name": ..., "status": "running"|"done", "result": ...}
      {"type": "content", "content": "..."}
      {"type": "done", "workspace_id": None, "conversation_id": None}

    不创建 workspace，不调 codegen。
    """
    # ── 解析 LLM 配置 ──────────────────────────────────────────────────────
    from app.agents.coding.llm_config import load_coding_llm_config

    try:
        base_url, api_key, llm_model = await load_coding_llm_config(
            params.tenant_id, params.selected_model or ""
        )
    except Exception as exc:
        yield {"type": "content", "content": f"LLM 配置加载失败：{exc}"}
        yield {"type": "done", "workspace_id": None, "conversation_id": None}
        return

    # ── 解析工作区(迭代轮带 workspace_id → 加工作区只读文件工具) ──────────
    ws_path: Optional[Path] = None
    if getattr(params, "workspace_id", None):
        try:
            from app.coding.workspace import WorkspaceManager

            _p = WorkspaceManager().get_workspace_path(params.workspace_id)
            if _p.exists():
                ws_path = _p
        except Exception as exc:
            logger.warning("[read_query] 解析工作区路径失败: %s", exc)

    # ── 解析 platform_env_id ───────────────────────────────────────────────
    platform_env_id = await _resolve_read_platform_env_id(params.tenant_id, db)

    if not platform_env_id and not ws_path:
        # 既没环境也没工作区 → 没有任何工具可用
        yield {"type": "content", "content": "当前租户未配置可用的 aPaaS 平台环境，无法查询应用数据。\n请先在「平台管理 → aPaaS 租户」中配置并连接平台环境。"}
        yield {"type": "done", "workspace_id": None, "conversation_id": None}
        return

    # ── 工具集按上下文拼装: 平台只读工具(有环境) + 工作区文件工具(有工作区) ──
    tool_definitions: list[dict] = []
    if platform_env_id:
        tool_definitions += READ_ONLY_TOOL_DEFINITIONS
    if ws_path:
        tool_definitions += WORKSPACE_TOOL_DEFINITIONS
    tool_definitions += _LOCAL_READ_TOOL_DEFINITIONS

    system_prompt = _READ_WS_SYSTEM_PROMPT if ws_path else _READ_SYSTEM_PROMPT

    # ── tool-loop ──────────────────────────────────────────────────────────
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": params.message},
    ]

    async def _exec_tool(fn_name: str, args: dict, is_ws_tool: bool, is_local_tool: bool) -> str:
        """执行单个只读工具:
        - 工作区文件工具 → 本地只读执行(线程池, 不碰平台)
        - 本地状态/搜索工具 → 只读查询本地 DB 或工具白名单
        - aPaaS 只读工具 → _call_apaas_platform_tool 复用 token 自愈
          (首次空 token→用 env 账号密码登录 + 撞 401→刷 token 重试一次)。
        """
        try:
            if is_local_tool:
                if fn_name == "search_tools":
                    return _search_read_tools(str((args or {}).get("query") or ""), ws_path)
                if fn_name == "get_current_workspace_app_status":
                    return await _get_current_workspace_app_status(params, db, ws_path, platform_env_id, args or {})
                return f"Error: 未知本地只读工具 {fn_name!r}"
            if is_ws_tool:
                return await asyncio.to_thread(execute_workspace_tool, ws_path, fn_name, args)
            from app.mcp_server import _call_apaas_platform_tool
            _result_dict = await _call_apaas_platform_tool(fn_name, args, platform_env_id)
            return json.dumps(_result_dict, ensure_ascii=False)
        except Exception as exc:
            return f"Error: {exc}"

    turn_texts: list[str] = []  # 各轮 content, 收口成完整答案给持久化

    for _turn in range(_READ_MAX_TURNS):
        payload: dict = {
            "model": llm_model,
            "messages": messages,
            "tools": tool_definitions,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 1200,
        }
        # 兼容 qwen3 / dashscope — disable thinking
        if "qwen3" in llm_model.lower() or "dashscope.aliyuncs.com" in base_url.lower():
            payload["enable_thinking"] = False

        sink: dict = {"content": "", "tool_calls": []}
        try:
            async for piece in _stream_llm(base_url, api_key, payload, sink):
                yield {"type": "content", "content": piece, "delta": True}
        except Exception as exc:
            logger.warning("[read_query] LLM 调用失败 turn=%d: %s", _turn, exc)
            yield {"type": "content", "content": f"查询时出现错误：{exc}"}
            break

        content: str = str(sink["content"]).strip()
        tool_calls: list[dict] = [tc for tc in sink["tool_calls"] if tc.get("function", {}).get("name")]
        if content:
            turn_texts.append(content)

        # 把 assistant 消息加进历史（不管有没有 tool_calls）
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        # 没有工具调用 → 最终答案(增量已流式发完, 这里不再重发)
        if not tool_calls:
            break

        # 有工具调用 → 同轮并行执行(全是只读, 无相互依赖; 先齐发 running chip 再 gather)
        tool_result_messages: list[dict] = []
        runnable: list[tuple[str, str, dict, bool, bool]] = []  # (tc_id, fn_name, args, is_ws_tool, is_local_tool)
        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name", "")
            tc_id = tc.get("id") or fn_name

            # 只允许只读工具（aPaaS 只读子集 + 工作区文件只读工具）
            _is_ws_tool = fn_name in WORKSPACE_TOOL_NAMES and ws_path is not None
            _is_local_tool = fn_name in _LOCAL_READ_TOOL_NAMES
            if not _is_ws_tool and fn_name not in _READ_ONLY_EXECUTORS and not _is_local_tool:
                tool_result_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": f"Error: 工具 {fn_name!r} 不在只读工具列表中，不予执行。",
                })
                continue

            try:
                args_raw = tc.get("function", {}).get("arguments") or "{}"
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError:
                args = {}

            yield {
                "type": "tool",
                "name": fn_name,
                "display": _TOOL_DISPLAY.get(fn_name, fn_name),
                "status": "running",
                "args": args,
            }
            runnable.append((tc_id, fn_name, args, _is_ws_tool, _is_local_tool))

        results = (
            await asyncio.gather(*[_exec_tool(f, a, w, l) for (_t, f, a, w, l) in runnable])
            if runnable else []
        )
        for (tc_id, fn_name, _args, _w, _l), result_str in zip(runnable, results):
            yield {
                "type": "tool",
                "name": fn_name,
                "status": "done",
                "result": result_str[:2000],  # 截断避免过长
            }
            tool_result_messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_str,
            })

        messages.extend(tool_result_messages)

    # 兜底：loop 因 MAX_TURNS 耗尽退出(最后还是 tool result, 模型一直在读没收口)
    # → 强制一次无工具收尾, 把已读到的信息总结成真实回答, 而不是一句套话。
    if messages and messages[-1].get("role") == "tool":
        messages.append({
            "role": "user",
            "content": "(系统提示) 工具调用轮数已用完。请基于以上已获取的信息，直接回答用户最初的问题；信息不全就说明哪些没来得及看。不要再调用工具。",
        })
        _final_sink: dict = {"content": "", "tool_calls": []}
        try:
            async for piece in _stream_llm(base_url, api_key, {
                "model": llm_model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1200,
            }, _final_sink):
                yield {"type": "content", "content": piece, "delta": True}
            _final = str(_final_sink["content"]).strip()
            if _final:
                turn_texts.append(_final)
            else:
                yield {"type": "content", "content": "查询完成，如需了解更多请继续提问。"}
                turn_texts.append("查询完成，如需了解更多请继续提问。")
        except Exception as exc:
            logger.warning("[read_query] 收尾回答失败: %s", exc)
            yield {"type": "content", "content": "查询完成，如需了解更多请继续提问。"}
            turn_texts.append("查询完成，如需了解更多请继续提问。")

    # 完整答案(各轮 content 拼接)给调用方持久化用 —— 内部事件, pipeline 消费后不下发前端
    yield {"type": "read_answer", "content": "\n\n".join(t for t in turn_texts if t.strip()).strip()}

    yield {
        "type": "done",
        "workspace_id": None,
        "conversation_id": None,
    }


# ── 延迟引用避免循环 import ────────────────────────────────────────────────
# run_read_query 签名里用了 "PipelineParams" 字符串，在运行时不需要 import
# （PipelineParams 由调用方 pipeline.py 传入实例即可）
