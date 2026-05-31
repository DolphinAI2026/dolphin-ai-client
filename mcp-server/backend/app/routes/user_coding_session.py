"""user_coding_session — 维护「user → 当前活跃 dolphin coding chat session」映射。

设计目的
========
/ai-coding 页面让 dolphin AI-aPaaS-Coding agent 帮用户做低代码自开发。dolphin
agent 通过 MCP 工具调 ai-builder 内部 `POST /coding/workspace/create` 创建
workspace 时，**MCP 调用上下文里看不到 dolphin session_id**（dolphin streamable
HTTP MCP 客户端目前不传 session header）。

为了让历史列表「跳回会话」功能可工作（用户问"这个自开发是从哪个会话做的"），
需要一条旁路记录 user → 当前活跃 session 的映射：
  - 前端 AICodingAssistantPage mount 时，DolphinAgentEmbed 内部拿到 session_id 后
    emit event，父组件调本路由 POST /api/coding/active-session 写到进程内 map
  - workspace_mgr.create_workspace 兜底从这个 map 拿 session_id 写到 .workspace.json

进程内 map 局限
==============
- backend 重启后丢，重启后第一次进 /ai-coding 用户得手动刷新页面让前端再 POST 一次
- 多 worker 时各 worker 状态独立（trial 单 worker 单实例 OK，生产多实例需换 redis）
- 同一 user 开多 tab 时后开的 tab 抢占 session 关联（当前可接受）

后期方案：dolphin trial 给 streamable HTTP MCP 调用注入 X-Dolphin-Session-Id
header，MCP 工具直接读，不需要这条旁路。
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context

router = APIRouter()


# user_id → {session_id, project_id, app_id (optional), updated_at}
_USER_CODING_SESSION: dict[int, dict] = {}
_USER_CODING_SESSION_LOCK = RLock()


# 2026-05-09：跨 agent 上下文复用 cache
# user_id → {
#   apaas_app_id, app_code, app_name, env_id, web_url, mobile_url, backend_url,
#   tenant_code, current_version,
#   forms: [{form_id, form_code, form_name, default_tab_id}],  # builder 已查过的表单
#   last_action: 'created' | 'updated' | 'attached' | 'published',
#   last_actor: 'builder' | 'coding',  # 哪个 agent 写的
#   updated_at: float,
# }
# 用途：builder agent 部署完应用后写 cache，coding agent 启动时先 get_recent_app_context
# 检测命中可以 prefill 上下文，避免重新查 list_apaas_apps_in_env / list_apaas_app_menus
_USER_RECENT_APP_CONTEXT: dict[int, dict] = {}
_USER_RECENT_APP_CONTEXT_LOCK = RLock()


# 2026-05-09：agent 之间 handoff 状态机
# token → {
#   from_agent: 'builder' | 'coding', to_agent: 'coding' | 'builder',
#   user_id, apaas_app_id, app_name, summary, todo_list, created_at,
# }
# 流程：
# - builder agent 完成应用部署后调 handoff_to_coding 写 token
# - 返 deeplink: /ai-builder/ai-coding?handoff_token=xxx
# - 用户点 link → 前端检测 query → 调 consume-handoff 拿上下文 → 顶部横幅显示
# - 一次性消费（拿过删）
import uuid as _uuid
_PENDING_HANDOFFS: dict[str, dict] = {}
_PENDING_HANDOFFS_LOCK = RLock()


def set_user_recent_app_context(user_id: int, ctx: dict) -> None:
    """builder / coding 工具部署 / 调整成功后调，记录该用户最近操作的 app 元数据。"""
    if not user_id or not ctx or not ctx.get("apaas_app_id"):
        return
    ctx = dict(ctx)
    ctx["updated_at"] = time.time()
    with _USER_RECENT_APP_CONTEXT_LOCK:
        _USER_RECENT_APP_CONTEXT[int(user_id)] = ctx


def get_user_recent_app_context_dict(user_id: int) -> Optional[dict]:
    """coding agent 启动时调，命中就 prefill；找不到返 None。"""
    with _USER_RECENT_APP_CONTEXT_LOCK:
        v = _USER_RECENT_APP_CONTEXT.get(int(user_id))
        return dict(v) if v else None


def create_handoff(
    *, from_agent: str, to_agent: str, user_id: int, apaas_app_id: int,
    app_name: str = "", summary: str = "", todo_list: Optional[list] = None,
) -> str:
    """生成 handoff token + 持久化到 _PENDING_HANDOFFS。返回 token 给 deeplink 用。"""
    token = f"hf_{_uuid.uuid4().hex[:12]}"
    record = {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "user_id": int(user_id),
        "apaas_app_id": int(apaas_app_id),
        "app_name": app_name,
        "summary": summary,
        "todo_list": list(todo_list or []),
        "created_at": time.time(),
    }
    with _PENDING_HANDOFFS_LOCK:
        _PENDING_HANDOFFS[token] = record
    return token


def consume_handoff_token(token: str, user_id: int) -> Optional[dict]:
    """一次性消费 handoff，user_id 鉴权防跨用户读。"""
    with _PENDING_HANDOFFS_LOCK:
        rec = _PENDING_HANDOFFS.get(token)
        if not rec or rec["user_id"] != int(user_id):
            return None
        # 一次性：消费后删除
        del _PENDING_HANDOFFS[token]
        return dict(rec)


def set_user_coding_session(
    user_id: int,
    session_id: str,
    project_id: Optional[int] = None,
    app_id: Optional[int] = None,
) -> None:
    """前端进 /ai-coding 拿到 session_id 后调用记录。"""
    if not session_id:
        return
    with _USER_CODING_SESSION_LOCK:
        _USER_CODING_SESSION[int(user_id)] = {
            "session_id": session_id,
            "project_id": project_id,
            "app_id": app_id,
            "updated_at": time.time(),
        }


def get_user_coding_session(user_id: int) -> Optional[dict]:
    """create_workspace 路由 / 列表 API 调用反查 user 当前活跃 session。

    返回 dict 副本（线程安全），找不到返回 None。
    """
    with _USER_CODING_SESSION_LOCK:
        v = _USER_CODING_SESSION.get(int(user_id))
        return dict(v) if v else None


class ActiveSessionRequest(BaseModel):
    session_id: Optional[str] = None  # 不传时 backend 自生成 marker
    project_id: Optional[int] = None
    app_id: Optional[int] = None


@router.post("/active-session")
async def mark_active_session(
    req: ActiveSessionRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端 /ai-coding mount 时调一次，把当前 user 的活跃会话标记到 backend map。

    2026-05-08 妥协方案：dolphin trial 当前 3 条路全堵死（postMessage 不发
    session 事件 / body 注入不支持 {{session_id}} 模板变量 / sessions API 500），
    没法拿到 dolphin 真实 session_id。改用 backend 自生成时间戳 marker：
        marker = "ai-builder-{user_id}-{round(ts/600)}"  # 10 分钟同 marker
    同一 user 在 10 分钟内多次创建 workspace 共享一个 marker，10 分钟切下一个。

    create_dev_workspace 时写到 .workspace.json `dolphin_session_id` 字段，历史
    页能识别为"非空"显示「↩ 回到对话」按钮（语义跟「跳回会话」不同：不能精确
    resume 当年那个 dolphin chat session，只能进 /ai-coding 让 dolphin 自动 resume
    用户最近 session）。

    后期 dolphin 团队配合后，前端能拿到真 session_id 时这里就走真实路径。
    幂等：重复调没副作用。
    """
    sid = req.session_id
    if not sid:
        # 自生成 marker：10 分钟粒度（同会话期内多 workspace 共享 marker）
        bucket = int(time.time() // 600)
        sid = f"ai-builder-{ctx.user.id}-{bucket}"
    set_user_coding_session(
        user_id=ctx.user.id,
        session_id=sid,
        project_id=req.project_id,
        app_id=req.app_id,
    )
    return {"ok": True, "user_id": ctx.user.id, "session_id": sid}


@router.get("/active-session")
async def get_active_session(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """调试 / 前端展示用：看当前 user 已记录的活跃 session。"""
    cached = get_user_coding_session(ctx.user.id)
    return {
        "ok": True,
        "user_id": ctx.user.id,
        "session": cached,
    }


# 2026-05-09：跨 agent handoff 消费端点 —— /ai-coding 检测 ?handoff_token=xxx 调
@router.get("/consume-handoff")
async def consume_handoff(
    token: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端 AICodingAssistantPage 检测到 ?handoff_token=xxx → 调本端点拿上下文。

    返回 handoff record 含 from_agent / to_agent / app_id / summary / todo_list。
    一次性消费（拿过删，防止刷新页面重复触发）。
    """
    rec = consume_handoff_token(token, ctx.user.id)
    if not rec:
        return {
            "ok": False,
            "error_code": "HANDOFF_NOT_FOUND",
            "message": "handoff token 不存在或已被消费（刷新会清，token 一次性）",
        }
    return {"ok": True, "handoff": rec}


# 2026-05-09：跨 agent app context cache 读取（前端预览 / 调试用）
@router.get("/recent-app-context")
async def get_recent_app_context_endpoint(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端读用户最近操作的 app 上下文。MCP 工具 get_recent_app_context 同源数据。"""
    cached = get_user_recent_app_context_dict(ctx.user.id)
    return {"ok": True, "user_id": ctx.user.id, "context": cached}


# 2026-05-09：dev-spec 预览端点 —— DevSpecPreviewPage 拉 mockup_html + spec_md
# 2026-05-10：改为公开端点（无 Depends(get_auth_context)）。spec_token 自身即凭证：
#   - 8 hex 随机后缀 ≈ 32 bits 熵不可猜
#   - create_dev_workspace 一调即删（一次性）
#   - dolphin chat 链接走 dolphin-trial 域，跨域用户不在 ai-builder 登录，
#     原 ctx.user.id（ai-builder 本地 DB 小整数）和 frontmatter user_id（aPaaS 大整数）
#     ID 空间不同，比对永远失败 → 之前撞「无权访问该 spec」的根因。
@router.get("/dev-spec-preview/{spec_token}")
async def get_dev_spec_preview(spec_token: str):
    """前端预览页拉 spec_token 对应的 SPEC markdown + HTML mockup + 元数据。

    数据源：backend `.pending-dev-specs/{spec_token}.md` 和 `.html`。
    spec.md 顶部含 frontmatter（json）记录 scene_type / project_name / display_name /
    apaas_app_id / apaas_app_name / created_at / user_id。

    安全：spec_token 即 bearer（带 8 hex 随机后缀，create_dev_workspace 后立即消费删盘）。
    """
    from pathlib import Path
    from app.coding.workspace import WORKSPACE_ROOT
    import json as _json
    import re as _re

    # 2026-05-14: 挪进 PVC（原 .parent 在 /app 下，rollout 必丢）；老路径作为 fallback 读
    spec_dir = WORKSPACE_ROOT / ".pending-dev-specs"
    md_path = spec_dir / f"{spec_token}.md"
    html_path = spec_dir / f"{spec_token}.html"
    if not md_path.exists():
        legacy_dir = WORKSPACE_ROOT.parent / ".pending-dev-specs"
        legacy_md = legacy_dir / f"{spec_token}.md"
        if legacy_md.exists():
            md_path = legacy_md
            html_path = legacy_dir / f"{spec_token}.html"

    if not md_path.exists():
        return {
            "ok": False,
            "error_code": "SPEC_NOT_FOUND",
            "message": f"spec_token {spec_token} 不存在或已被消费（用过 create_dev_workspace 后会自动删除）",
        }

    md_content = md_path.read_text(encoding="utf-8")
    # 解析 frontmatter
    meta = {}
    spec_md = md_content
    fm_match = _re.match(r"^---\n(.+?)\n---\n+", md_content, _re.DOTALL)
    if fm_match:
        try:
            meta = _json.loads(fm_match.group(1))
        except Exception:
            pass
        spec_md = md_content[fm_match.end():]

    mockup_html = ""
    if html_path.exists():
        mockup_html = html_path.read_text(encoding="utf-8")

    return {
        "ok": True,
        "spec_token": spec_token,
        "scene_type": meta.get("scene_type"),
        "project_name": meta.get("project_name"),
        "display_name": meta.get("display_name"),
        "apaas_app_id": meta.get("apaas_app_id"),
        "apaas_app_name": meta.get("apaas_app_name"),
        "created_at": meta.get("created_at"),
        "spec_md": spec_md,
        "mockup_html": mockup_html,
        "has_mockup": bool(mockup_html),
    }


# 2026-05-08：dev-coding workspace 历史列表 —— /ai-coding 历史 tab 用
@router.get("/dev-workspaces")
async def list_dev_workspaces(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """列出当前 user + tenant 名下所有 dev-coding workspace（按 created_at 倒序）。

    复用 workspace_mgr.list_accessible_workspaces 的 user/tenant 过滤逻辑，
    返回每条 workspace 的审计字段（apaas_app_id/dolphin_session_id/created_at）
    + 状态 + 项目元数据，前端列表卡片用。
    """
    # workspace_mgr 是 routes/coding.py 顶部 new 的 WorkspaceManager 实例（带磁盘缓存
    # _workspace_path_cache）；从那 import 复用，不要在这另起一个实例。
    from app.routes.coding import workspace_mgr

    items = workspace_mgr.list_accessible_workspaces(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )

    # 精简返回字段（避免 workspace meta 里的 disk_path / files / activity_ts 等内部字段
    # 暴露到前端；前端列表只需要展示用的字段 + dolphin_session_id 跳回会话用）
    def _project(m: dict) -> dict:
        return {
            "id": m.get("id"),
            "project_type": m.get("project_type"),
            "project_name": m.get("project_name"),
            "display_name": m.get("display_name"),
            "status": m.get("status"),
            "tenant_id": m.get("tenant_id"),
            "user_id": m.get("user_id"),
            "apaas_app_id": m.get("apaas_app_id"),
            "apaas_app_name": m.get("apaas_app_name"),
            "dolphin_session_id": m.get("dolphin_session_id"),
            "created_at": m.get("created_at"),
            "updated_at": m.get("updated_at"),
            # activity_ts 是 list_accessible_workspaces 计算出来的最后活跃秒数
            # 前端做相对时间显示用得上（兜底用 mtime）
            "activity_ts": m.get("activity_ts"),
        }

    # 排序：created_at desc 优先（新 workspace），缺失时 fallback activity_ts
    def _sort_key(m: dict) -> float:
        ca = m.get("created_at")
        if ca:
            try:
                from datetime import datetime
                return datetime.fromisoformat(ca).timestamp()
            except Exception:
                pass
        return float(m.get("activity_ts") or 0)

    projected = [_project(m) for m in items]
    projected.sort(key=_sort_key, reverse=True)
    return {"ok": True, "items": projected, "total": len(projected)}
