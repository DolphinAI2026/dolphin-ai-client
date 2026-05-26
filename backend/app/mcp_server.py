"""AI-Builder MCP Server — 把应用领域能力封装成 MCP 工具暴露给得小帆等 agent 平台。

设计：
- FastMCP 实例 mount 到主 FastAPI 进程的 /api/mcp/sse 子路径，复用 :8003 + 现有 nginx
- 每个工具内部用临时 service JWT 调本机 :8003 现有 HTTP API（不复制业务逻辑）
- SSE 流式 endpoint 用 httpx 自己 consume 到 done 事件再返回，对调用方表现为同步
- 鉴权：MCP server 自身要 Bearer API key（防外网随便调）；
  实际操作的租户/用户身份通过得小帆"自定义 Body 字段"配置注入，每个 tool 形参带 _tenant_id / _user_id

环境变量：
- MCP_API_KEYS: 逗号分隔的合法 Bearer token（agent 配置里填其中一个）
- MCP_INTERNAL_BASE: 内部回环 base URL，默认跟随后端 settings.port
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from jose import jwt
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.error_messages import is_apaas_token_error

# pydantic-settings 加载的是 settings.env_var；我们直接读 os.environ 的 MCP_API_KEYS。
# 显式 load .env 兜底（生产 nohup 启动时 source .env 不一定继承环境变量）
try:
    from dotenv import load_dotenv as _load_dotenv
    _backend_dir = Path(__file__).resolve().parent.parent  # backend/
    _env_path = _backend_dir / ".env"
    if _env_path.exists():
        _load_dotenv(str(_env_path), override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)


# ─────────────────────── 配置 ───────────────────────


def _load_api_keys() -> set[str]:
    raw = (os.getenv("MCP_API_KEYS") or "").strip()
    return {k.strip() for k in raw.split(",") if k.strip()}


_INTERNAL_BASE = (
    os.getenv("MCP_INTERNAL_BASE", "").strip()
    or f"http://127.0.0.1:{getattr(settings, 'port', 8000)}/api"
)
_API_KEYS = _load_api_keys()


def is_valid_api_key(key: str | None) -> bool:
    """供 main.py 在 SSE handshake middleware 里调用。空 keys 配置时拒绝所有请求。"""
    if not _API_KEYS:
        return False
    if not key:
        return False
    return key in _API_KEYS


# ─────────────────────── 内部 HTTP 调用 helper ───────────────────────


def _sign_service_token(user_id: int, tenant_id: int, ttl_minutes: int = 15) -> str:
    """签一个短期 JWT 给内部 endpoint 用。复用主 jwt_secret_key。"""
    payload = {
        "sub": str(user_id),
        "tid": tenant_id,
        "type": "mcp_service",
        "exp": datetime.utcnow() + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _build_app_view_url(app_id: int | None) -> str | None:
    """生成应用查看的链接。优先 env APAAS_BUILDER_PUBLIC_URL，未设走相对路径。

    2026-05-19：之前写死 https://agent.dfy.definesys.cn → dev / localhost 跳出去
    撞生产域名空页面。改成 env 控制，未设时返相对 URL，跟着当前域名走。
    """
    if not app_id:
        return None
    base = (os.getenv("APAAS_BUILDER_PUBLIC_URL") or "").strip().rstrip("/")
    return f"{base}/ai-builder/chat?app_id={app_id}"


def _resolve_identity(tenant_id: int | None, user_id: int | None) -> tuple[int, int]:
    """MCP 客户端自定义 Body 字段硬编码 (tenant_id=1, user_id=1)，但 ai-builder
    用户多租户多账号，直接用这俩调内部 API 会跨租户错位（看不到当前用户的应用）。

    从 current_app 反查真实身份覆盖；找不到才用 外部 agent 传的兜底。
    """
    from app.routes.current_app import get_current_app_for_user
    rec = get_current_app_for_user(int(user_id) if user_id else 1)
    if rec:
        real_uid, real_tid, _, _ = rec
        return int(real_tid), int(real_uid)
    if not tenant_id or not user_id:
        raise ValueError(
            "缺少身份信息：agent Body 字段未注入 tenant_id/user_id 且 ai-builder 没有"
            "用户当前应用状态。请在 ai-builder 中打开某个应用页（让前端 sync 状态），"
            "或在得小帆 MCP 配置「自定义 Body 字段」里加上 tenant_id/user_id。"
        )
    return int(tenant_id), int(user_id)


def _resolve_app_id(app_id: int | None, user_id: int) -> tuple[int, str]:
    """工具收到 app_id=None 时，从 current_app 模块拿用户当前编辑的应用。
    返回 (app_id, app_name)。"""
    if app_id and app_id > 0:
        return int(app_id), ""
    from app.routes.current_app import get_current_app_for_user
    rec = get_current_app_for_user(int(user_id) if user_id else 1)
    if not rec:
        raise ValueError(
            "未指定 app_id，且后端没有用户当前编辑应用的状态。"
            "请告诉助手具体的应用 ID（数字），或先在 ai-builder UI 打开某个应用。"
        )
    _, _, real_app_id, real_app_name = rec
    return int(real_app_id), real_app_name


async def _resolve_env_id_for_app(app_id: int, tenant_id: int, user_id: int) -> int | None:
    """token retry 用 — 从 app_id 反查 platform_env_id (不撞 apaas, 无递归风险)."""
    try:
        app_data = await _api_call(
            "GET", f"/applications/{app_id}",
            tenant_id=tenant_id, user_id=user_id,
        )
        return (app_data or {}).get("platform_env_id")
    except Exception as exc:
        logger.warning("token retry: 从 app=%s 反查 env_id 失败: %s", app_id, exc)
        return None


async def _api_call(
    method: str,
    path: str,
    *,
    tenant_id: int,
    user_id: int,
    json_body: dict | None = None,
    params: dict | None = None,
    files: dict | None = None,
    timeout: float = 300.0,
    token_retry_app_id: int | None = None,
    token_retry_env_id: int | None = None,
) -> Any:
    """调本机内部 endpoint。普通 JSON 接口直接返；SSE 由 _api_call_sse 处理。

    2026-05-23 C 方案 B (移植 b33d18e, 用同进程 _refresh_apaas_env_token 替换
    internal HTTP refresh): 传 token_retry_app_id / token_retry_env_id 时,
    撞 APaaS token 过期 (含 is_apaas_token_error markers) 自动刷 token + 重试一次.
    app_id 优先反查 env_id; 只传 env_id 时直接刷指定环境 (auto-create 场景用).
    """
    async def _once() -> Any:
        token = _sign_service_token(user_id, tenant_id)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=_INTERNAL_BASE, headers=headers, timeout=timeout) as cli:
            resp = await cli.request(method, path, json=json_body, params=params, files=files)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"内部接口 {method} {path} 失败 ({resp.status_code}): {resp.text[:500]}"
                )
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" in ct:
                return resp.json()
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}

    try:
        return await _once()
    except RuntimeError as exc:
        if (token_retry_app_id or token_retry_env_id) and is_apaas_token_error(str(exc)):
            env_id = token_retry_env_id
            if env_id is None and token_retry_app_id:
                env_id = await _resolve_env_id_for_app(token_retry_app_id, tenant_id, user_id)
            if env_id and await _refresh_apaas_env_token(env_id):
                logger.info("MCP token 自愈后重试 %s %s", method, path)
                return await _once()
        raise


async def _api_call_sse_collect(
    method: str,
    path: str,
    *,
    tenant_id: int,
    user_id: int,
    json_body: dict | None = None,
    params: dict | None = None,
    files: dict | None = None,
    timeout: float = 600.0,
    token_retry_app_id: int | None = None,
    token_retry_env_id: int | None = None,
) -> dict:
    """专门给 SSE endpoint 用：consume 整个 stream，按事件聚合返回最终状态。

    返回 { events: [...], done: <最终 done payload>, errors: [...] }

    2026-05-23 C 方案 B: token_retry_app_id / token_retry_env_id 同 _api_call.
    SSE 路径 token 过期通常表现为 errors 数组里的 'Token已过期' / 'APaaS平台Token已过期'
    文案 (apaas_client 401 → APAAS_TOKEN_EXPIRED). 检测到后整段 stream 重新执行
    (events 清空重收). 重试只发生一次. 依赖 backend handler 内 'if not existing_apaas_app_id'
    保护防 double create_app (commit b33d18e 已在 prod 跑过 5/7-5/14 验证).
    """
    async def _once() -> dict:
        token = _sign_service_token(user_id, tenant_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
        events: list[dict] = []
        errors: list[str] = []
        done_payload: dict | None = None

        async with httpx.AsyncClient(base_url=_INTERNAL_BASE, headers=headers, timeout=timeout) as cli:
            async with cli.stream(method, path, json=json_body, params=params, files=files) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"内部 SSE {method} {path} 失败 ({resp.status_code}): {body[:500]!r}"
                    )
                current_event = ""
                async for line in resp.aiter_lines():
                    line = (line or "").rstrip()
                    if not line:
                        current_event = ""
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].lstrip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except Exception:
                        data = {"_raw": data_str}
                    ev = {"event": current_event or data.get("type") or "message", "data": data}
                    events.append(ev)
                    if ev["event"] == "done":
                        done_payload = data if isinstance(data, dict) else {"value": data}
                    elif ev["event"] == "error":
                        errors.append(str(data.get("message") or data.get("error") or data))
        return {"events": events, "done": done_payload, "errors": errors}

    result = await _once()
    if (
        (token_retry_app_id or token_retry_env_id)
        and result.get("errors")
        and any(is_apaas_token_error(e) for e in result["errors"])
    ):
        env_id = token_retry_env_id
        if env_id is None and token_retry_app_id:
            env_id = await _resolve_env_id_for_app(token_retry_app_id, tenant_id, user_id)
        if env_id and await _refresh_apaas_env_token(env_id):
            logger.info("MCP token 自愈后重试 SSE %s %s", method, path)
            result = await _once()
            result["_token_auto_refreshed"] = True
    return result


# ─────────────────────── FastMCP 实例 ───────────────────────


# DNS rebinding 保护：默认开启时 allowed_hosts 空会拒所有 Host，必须显式列允许域名。
# MCP_ALLOWED_HOSTS 环境变量逗号分隔；不配则关闭保护（部署在反代后已经有 CSRF/auth 兜底）
_allowed_hosts = [h.strip() for h in (os.getenv("MCP_ALLOWED_HOSTS") or "").split(",") if h.strip()]
if _allowed_hosts:
    _security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    )
else:
    _security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "apaas-builder-ai",
    instructions=(
        "aPaaS Builder AI 应用领域能力工具集。"
        "可基于标准 Markdown 设计文档创建 / 更新 / 上线低代码应用，"
        "查询应用列表与详情，预览 / 执行变更计划。"
        "调用每个工具都要带 tenant_id 和 user_id（由得小帆配置注入到 body 根级）。"
    ),
    transport_security=_security,
    # stateless 模式：server 不跟踪 mcp-session-id，每个 POST 自包含。
    # MCP 客户端等 agent 平台的 streamable HTTP client 不可靠传递 session id，
    # 默认 stateful 会在第二个 request 报 400 Missing session ID。
    stateless_http=True,
    # JSON 响应（非 SSE 流），MCP 客户端解析更稳定
    json_response=True,
)


# ─────────────────────── 工具实现 ───────────────────────


@mcp.tool()
async def parse_design_doc(
    md_content: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """解析一份标准 markdown 设计文档，返回结构化 preview（不创建应用）。

    用法：用户提交 md 后先用这个工具检查解析结果是否符合预期，再决定是否创建应用。

    md_content 必须是 aPaaS Builder 标准 6 章节格式：
        一、应用信息 / 二、角色列表 / 三、数据字典 / 四、数据模型 / 五、表单定义 / 六、权限矩阵

    返回：{ appName, appCode, roles[], dicts[], models[], forms[], permissions[] }
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    res = await _api_call("POST", "/applications/upload-doc", tenant_id=tid, user_id=uid, files=files)
    data = res.get("data") if isinstance(res, dict) else None
    return {
        "ok": True,
        "preview": data or res,
        "document_text_length": len(md_content),
    }


@mcp.tool()
async def list_platform_envs(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出当前租户配置的所有低代码平台环境。

    用法（agent 工作流）：只在需要选择或诊断平台环境时调用。
    普通“查看现有应用 / 查询当前租户应用列表”不要调用本工具，直接用 list_my_applications。
    当前租户通常已经绑定默认环境；generate_app_from_doc / export_apaas_app_design_doc
    可以在 env_id=0 或不传 env_id 时走默认环境。

    返回示例：
        {
          "envs": [
            {
              "id": 1,
              "name": "trial 环境",
              "base_url": "https://apaas-trial.definesys.cn",
              "is_default": true,
              "status": "connected",   # connected | disconnected | unknown
            },
            ...
          ],
          "default_env_id": 1,
          "connected_count": 1,
        }

    Agent 选择策略：
    - connected_count == 0 → 报错给用户："你还没配置可用的低代码平台环境，
      请先去 BuilderDevOps 添加，或检查现有环境登录状态。"
    - connected_count == 1 且唯一 connected 环境 is_default → 后续工具直接用默认环境，不需要再让用户确认
    - connected_count > 1 → 列给用户让其选择，等用户回复后用对应 env_id
      调 generate_app_from_doc(env_id=X)
    """
    tid, _uid = _resolve_identity(tenant_id, user_id)

    # 直接 db 查（绕开 /api/platform-envs 的 require_tenant_admin —— MCP service
    # token 已经验证 tenant_id，且 list 是只读操作，不需要 admin 权限）
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformEnv)
            .where(PlatformEnv.tenant_id == tid)
            .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
        )
        envs = result.scalars().all()

    items = [
        {
            "id": e.id,
            "name": e.env_name,
            "base_url": e.base_url,
            "is_default": bool(e.is_default),
            "status": e.status,
        }
        for e in envs
    ]
    default_id = next((e["id"] for e in items if e["is_default"]), None)
    connected_count = sum(1 for e in items if e["status"] == "connected")
    return {
        "ok": True,
        "envs": items,
        "default_env_id": default_id,
        "connected_count": connected_count,
    }


@mcp.tool()
async def generate_app_from_doc(
    artifact_id: int,
    app_name: str | None = None,
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """根据标准 markdown 设计文档创建一个新的 aPaaS 低代码应用（一步到位）。

    内部分两步：parse → auto-create。md 必须是标准 6 章节格式（参考 parse_design_doc 文档）。

    **2026-05-24 强制 artifact_id 模式** (省 token, 跟 validate/submit 一致 commit 6ba63aa):
    - 之前 `md_content` 参数已删除. 必须先 write_artifact 拿 id, 再用 id 创建.
    - 工作流: write_artifact (返 id) → generate_app_from_doc(artifact_id=id)
    - 漏传 → MISSING_ARTIFACT_ID; id 错 → ARTIFACT_NOT_FOUND

    参数：
    - artifact_id：write_artifact 返的 id, backend 从 ai_chat_artifacts 表读 md content
    - app_name：可选；不填会从 md 「一、应用信息」推断
    - env_id：部署到哪个 PlatformEnv。**强烈建议先调 list_platform_envs
      让用户确认**。0 表示用租户默认环境（fallback：找一个 connected 环境）。

    返回 { app_id, app_name, app_code, status, app_view_url, env: {id, name} }。
    """
    if not artifact_id or artifact_id <= 0:
        return {
            "ok": False,
            "error_code": "MISSING_ARTIFACT_ID",
            "error": "artifact_id 必填. 请先 write_artifact 拿 id 再调本工具 (省 token).",
        }
    md_content = await _load_artifact_content(artifact_id)
    if not md_content:
        return {
            "ok": False,
            "error_code": "ARTIFACT_NOT_FOUND",
            "error": f"找不到 artifact_id={artifact_id} - 请重新 write_artifact 拿新 id.",
        }

    tid, uid = _resolve_identity(tenant_id, user_id)

    # 1) 解析
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    parse_res = await _api_call(
        "POST", "/applications/upload-doc", tenant_id=tid, user_id=uid, files=files
    )
    preview = parse_res.get("data") if isinstance(parse_res, dict) else None
    if not isinstance(preview, dict):
        raise RuntimeError(f"文档解析返回结构异常：{parse_res!r:.300s}")

    final_app_name = (app_name or preview.get("appName") or "").strip() or "未命名应用"

    # 2) auto-create
    create_body: dict = {"app_name": final_app_name, "config_preview": {"data": preview}}
    if env_id and env_id > 0:
        create_body["platform_env_id"] = int(env_id)
    create_res = await _api_call(
        "POST",
        "/applications/auto-create",
        tenant_id=tid,
        user_id=uid,
        json_body=create_body,
    )
    app_id = create_res.get("app_id")
    return {
        "ok": True,
        "app_id": app_id,
        "app_name": create_res.get("app_name"),
        "app_code": create_res.get("app_code"),
        "is_new": create_res.get("is_new"),
        "status": "draft",
        "platform_env_id": create_res.get("platform_env_id"),
        "platform_env_name": create_res.get("platform_env_name"),
        "app_view_url": _build_app_view_url(app_id),
    }


@mcp.tool()
async def list_my_applications(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出当前登录用户在当前租户下能访问的 Builder 应用（分页第 1 页，最多 50 条）。

    直接按注入的 tenant_id 查询应用列表；当前租户已通过 JWT / 切租户确定，
    不需要先调用 list_platform_envs。只有新建/部署/远端 aPaaS 内省需要 env_id 时，
    才考虑查询平台环境。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    res = await _api_call(
        "GET",
        "/applications/page",
        tenant_id=tid,
        user_id=uid,
        params={"page": 1, "size": 50},
    )
    items = (res or {}).get("items") or []
    apps = [
        {
            "id": it.get("id"),
            "app_name": it.get("app_name"),
            "app_code": it.get("app_code"),
            "status": it.get("status"),
            "current_doc_version": it.get("current_doc_version"),
            "updated_at": it.get("updated_at"),
        }
        for it in items
    ]
    return {"ok": True, "applications": apps, "total": (res or {}).get("total", len(apps))}


@mcp.tool()
async def get_application(
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """查看指定应用的完整详情，**包括当前 SPEC 的 markdown 文档**（含所有字段、表单、权限）。

    app_id 可省略（=0）：自动用 ai-builder 中用户当前编辑的应用。

    返回的 spec_markdown 是当前应用的完整结构化设计文档（6 章节标准格式：
    应用信息/角色/数据字典/数据模型/表单/权限）。基于它你可以直接做增量改动
    （加字段/改字段/删字段），不用再问用户'有哪些字段'。

    spec_markdown_source 标识来源：
    - 'doc_version': 用户上传过设计文档，直接用最新版
    - 'config_preview_rendered': 应用没设计文档但有 SPEC 配置，从 config 反向渲染
    - 'empty': 真空白草稿，需要从零写文档
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    # 拉应用 meta
    meta = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)
    # 拉 spec markdown（容错）
    spec_md = ""
    spec_source = "unknown"
    spec_version = None
    try:
        spec = await _api_call("GET", f"/applications/{app_id}/spec-markdown", tenant_id=tid, user_id=uid)
        spec_md = (spec or {}).get("markdown") or ""
        spec_source = (spec or {}).get("source") or "unknown"
        spec_version = (spec or {}).get("version")
    except Exception as exc:
        logger.warning("get_application spec-markdown 拉取失败: %s", exc)
    return {
        "ok": True,
        "app_id": (meta or {}).get("id"),
        "app_name": (meta or {}).get("app_name"),
        "app_code": (meta or {}).get("app_code"),
        "status": (meta or {}).get("status"),
        "current_doc_version": (meta or {}).get("current_doc_version"),
        "platform_env_id": (meta or {}).get("platform_env_id"),
        "apaas_app_id": (meta or {}).get("apaas_app_id"),
        "app_view_url": _build_app_view_url(app_id),
        "spec_markdown": spec_md,
        "spec_markdown_source": spec_source,
        "spec_markdown_version": spec_version,
    }


async def _normalize_md_via_llm(target_md: str, current_spec_md: str) -> str:
    """LLM 兜底：外部 agent 给的 md 若不符合严格 6 章节模板，
    用 LLM 基于 current_spec_md（已知规范）+ target_md（agent 改动后）
    生成规范化的新版 md。

    避免每次都 LLM 调用 — 调用方仅在 strict parse 失败时才用此兜底。
    """
    from app.llm_client import LLMClient
    llm = LLMClient()
    prompt = f"""你是 ai-builder 设计文档规范化助手，输出严格符合 6 章节模板的 markdown。

## 输入
- CURRENT：当前应用规范的 markdown（标准 6 章节，作为格式模板）
- TARGET：AI 助手生成的新版 md（含用户改动，但格式可能错乱）

## 任务
**先 diff 出 TARGET 相对 CURRENT 的实质改动（新增/修改/删除字段、表单、权限等）**，
然后基于 CURRENT 的格式：
1. 完整保留 CURRENT 所有内容
2. **应用 diff 出的所有改动**（必须保住 TARGET 中比 CURRENT 多/改/少的字段）
3. 章节顺序、标题、表格列名 = CURRENT 格式
4. 输出完整的新版 markdown

## ⚠️ 关键原则（违反会导致用户改动丢失）
- **不要丢失** TARGET 中比 CURRENT 多出来的字段、表单、权限行
- 用户最常见的改动是"加一个字段"，diff 出来 TARGET 比 CURRENT 多一行 → 必须**新版里保留这行**
- 不能因为 TARGET 格式乱就把改动一起丢掉
- 如果不确定改动是什么，宁可多保留 TARGET 内容，也不要丢

只输出规范化后的 markdown 全文。不要解释。不要 ```markdown``` 包裹。

=== CURRENT ===
{current_spec_md}

=== TARGET ===
{target_md}

=== 规范化新版 markdown ==="""
    res = await llm.chat_completion(
        [{"role": "user", "content": prompt}],
        max_tokens=12000,
        temperature=0.0,
    )
    msg = (res.get("choices") or [{}])[0].get("message") or {}
    out = (msg.get("content") or "").strip()
    # 去掉可能的 code fence
    if out.startswith("```"):
        lines = out.split("\n")
        out = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return out.strip() or target_md  # LLM 没出东西就用原始 md


@mcp.tool()
async def update_app_from_doc(
    md_content: str,
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """上传新版 markdown 设计文档作为应用 vN+1 版，自动 diff 出变更计划返回。

    app_id 可省略（=0）：自动用 ai-builder 中用户当前编辑的应用。
    md_content 不严格符合模板时（章节/表格列差异），后端会自动 LLM 规范化重试一次。

    返回 { version, change_plan_id, summary（变更摘要）}。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)

    async def _attempt_upload(md: str) -> dict:
        files = {"file": (f"app-{app_id}-doc.md", md.encode("utf-8"), "text/markdown")}
        return await _api_call_sse_collect(
            "POST",
            f"/applications/{app_id}/upload-doc-version",
            tenant_id=tid, user_id=uid, files=files,
        )

    sse = await _attempt_upload(md_content)
    # strict parse 失败 → 拉 current spec_md 用 LLM 规范化重试一次
    if sse["errors"]:
        first_err = str(sse["errors"][-1])
        if "未按模板规范" in first_err or "DocNotStandardError" in first_err or "解析失败" in first_err:
            logger.info("严格解析失败，启用 LLM 规范化兜底重试")
            try:
                spec = await _api_call("GET", f"/applications/{app_id}/spec-markdown", tenant_id=tid, user_id=uid)
                current_md = (spec or {}).get("markdown") or ""
                if current_md:
                    normalized = await _normalize_md_via_llm(md_content, current_md)
                    if normalized and normalized != md_content:
                        sse = await _attempt_upload(normalized)
            except Exception as exc:
                logger.warning("LLM 规范化兜底失败: %s", exc)

    if sse["errors"]:
        raise RuntimeError(f"上传新版 md 失败：{sse['errors'][-1]}")
    done = sse.get("done") or {}
    return {
        "ok": True,
        "app_id": app_id,
        "version": done.get("version") or done.get("to_version"),
        "change_plan_id": done.get("change_plan_id"),
        "summary": done.get("summary") or done.get("change_summary"),
        "raw_done": done,
    }


@mcp.tool()
async def get_change_plan(
    plan_id: int,
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """查看变更计划详情：包含所有 actions（新增/修改/删除的角色、字典、模型、表单、权限）。

    app_id 可省略（=0）：自动用当前编辑应用。
    用户决策"是否执行"前应该读这个 plan。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    res = await _api_call(
        "GET", f"/applications/{app_id}/change-plans/{plan_id}", tenant_id=tid, user_id=uid
    )
    return {"ok": True, "plan": res}


@mcp.tool()
async def execute_change_plan(
    plan_id: int,
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """执行变更计划：把 plan 里所有 actions 落到底层（创建/修改/删除模型、表单、权限等）。

    app_id 可省略（=0）：自动用当前编辑应用。
    这是真正"动手"的工具，调用前请确认用户已经审过 change plan。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    sse = await _api_call_sse_collect(
        "POST",
        f"/applications/{app_id}/change-plans/{plan_id}/execute",
        tenant_id=tid,
        user_id=uid,
    )
    if sse["errors"]:
        return {"ok": False, "errors": sse["errors"], "events": sse["events"][-10:]}
    return {
        "ok": True,
        "app_id": app_id,
        "plan_id": plan_id,
        "summary": (sse.get("done") or {}).get("summary"),
        "executed_count": len([e for e in sse["events"] if e["event"] in ("step", "step_done")]),
    }


@mcp.tool()
async def publish_application(
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把应用上线：同步当前配置到底层 aPaaS 平台，让真实用户可访问。

    app_id 可省略（=0）：自动用当前编辑应用。"""
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    res = await _api_call("POST", f"/applications/{app_id}/publish", tenant_id=tid, user_id=uid)
    return {"ok": True, "app_id": app_id, "result": res}


async def _load_artifact_content(artifact_id: int) -> str | None:
    """从 ai_chat_artifacts 表读 content. 找不到返 None.

    2026-05-21 新增 — 让 validate_builder_doc / submit_design_doc 支持 artifact_id
    引用模式. LLM write_artifact 拿到 id 后, 后续工具传 id 不重写 5000+ 字 md
    节省 token (每次省 ~5000 token + 30-60s LLM 生成时间).
    """
    if not artifact_id or artifact_id <= 0:
        return None
    try:
        from app.database import AsyncSessionLocal
        from app.models import AIChatArtifact
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(AIChatArtifact.content).where(AIChatArtifact.id == artifact_id)
            )
            row = res.first()
            return row[0] if row else None
    except Exception as exc:
        logger.warning("_load_artifact_content(%s) failed: %s", artifact_id, exc)
        return None


def _do_validate_builder_doc(md_content: str) -> dict:
    """validate_builder_doc 的纯函数实现（无 IO，可单独单测）。"""
    from app.doc_standard_detector import detect
    from app.doc_pipeline import _strip_template_scaffolding

    if not md_content or not md_content.strip():
        return {
            "ok": False,
            "score": 0,
            "level": "freeform",
            "decision": "rewrite_first",
            "passes_strict": False,
            "missing_sections": ["应用信息", "角色列表", "数据模型", "权限定义"],
            "weak_sections": [],
            "signals": {},
            "advice": ["md_content 是空的，先把六章节模板写出来再校验。"],
        }

    cleaned = _strip_template_scaffolding(md_content)
    result = detect(cleaned)
    score = int(result.get("score") or 0)
    missing = result.get("missing_sections") or []
    weak = result.get("weak_sections") or []
    signals = result.get("signals") or {}

    advice: list[str] = []
    if missing:
        advice.append(
            f"缺失必填章节：{', '.join(missing)}。补齐 ## 标题 + 标准表格。"
        )
    for section in weak:
        advice.append(
            f"「{section}」表头不达标：核对该章节表头与 6 章模板（"
            "应用信息=应用编码/应用名称、角色=角色编码/角色名称、字典选项=选项编码/选项名称、"
            "模型/表单=字段编码/字段名称、权限=表单名称/角色编码/可查看/可编辑/可删除/数据范围）。"
        )
    if (signals.get("code_compliance") or 1.0) < 0.9:
        advice.append(
            "编码字段不规范：appCode / 角色编码 / 字段编码 必须英文小写 + 下划线"
            "（首字符字母，其余 [a-zA-Z0-9_-]）。检查所有'编码'列。"
        )
    if (signals.get("ref_integrity") or 1.0) < 0.9:
        advice.append("引用不闭合：字典编码 / 关联模型编码 必须在文档内已声明。检查模型字段引用。")
    if (signals.get("header_format") or 1.0) < 0.9:
        advice.append("章节标题格式：用 ## 一、应用信息 / ## 二、角色列表 ... 的中文数字编号。")
    # 阈值与后端 docs.py:1054 保持一致：>= 90 通过，< 90 后端会 400 拒收
    passes = score >= 90 and not missing
    if passes and score >= 95:
        advice.append("✅ 标准（≥95），可直接调 generate_app_from_doc / update_app_from_doc。")
    elif passes:
        advice.append(
            f"✅ 通过门槛（{score}/100，≥90 后端可解析）；如想更稳，按上面建议小修后重跑可冲到 95+。"
        )
    elif score >= 80:
        advice.append(
            f"未达标（{score}/100，门槛 90）：按上面建议修 1-2 处后重跑 validate_builder_doc。"
        )
    else:
        advice.append(
            f"严重偏离模板（{score}/100，门槛 90）：建议先按 STANDARD_DOC_FORMAT 把六章节骨架补齐再校验。"
        )

    return {
        "ok": True,
        "score": score,
        "level": result.get("level"),
        "decision": result.get("decision"),
        "passes_strict": passes,
        "missing_sections": missing,
        "weak_sections": weak,
        "signals": signals,
        "advice": advice,
    }


@mcp.tool()
async def validate_builder_doc(artifact_id: int) -> dict:
    """校验一份 markdown 设计文档是否符合 aPaaS Builder 标准（不创建应用、不需要身份）。

    **2026-05-23 强制 artifact_id 模式** (省 token, 消除 LLM 重写 5000+ 字 md 浪费):
    - 之前 `md_content` 参数已删除. 必须先 write_artifact 拿 id, 再用 id 校验.
    - 工作流: write_artifact (返 id) → validate_builder_doc(artifact_id=id)
    - 撞 MISSING_ARTIFACT_ID → 说明 agent 漏调 write_artifact, 先写文档拿 id 再校验
    - 撞 ARTIFACT_NOT_FOUND → id 错或 artifact 已被删, 重新 write_artifact 拿新 id

    建议工作流：
      1. 写完 md → write_artifact → 拿 artifact_id
      2. validate_builder_doc(artifact_id=N)
      3. passes_strict=False → 按 missing_sections / weak_sections / signals / advice 自我修补
      4. 重新 write_artifact (同名 filename 自动 version++) 拿新 id → 重 validate
      5. 重复至多 3 轮; 仍不通过把问题原文列给用户决定
      6. passes_strict=True 才把 md 文档输出给用户（或直接 generate_app_from_doc）

    返回：
        {
          "ok": True,
          "score": 0-100,                   # 综合分
          "level": "standard|partial|freeform",
          "decision": "pure_code|hybrid_fallback|rewrite_first",
          "passes_strict": bool,
          "missing_sections": [str],
          "weak_sections": [str],
          "signals": { "section_coverage": ..., "header_format": ..., ... },
          "advice": [str],
        }
    """
    if not artifact_id or artifact_id <= 0:
        return {
            "ok": False,
            "error_code": "MISSING_ARTIFACT_ID",
            "error": "artifact_id 必填. 请先 write_artifact 拿 id 再调本工具 (省 token).",
        }
    content = await _load_artifact_content(artifact_id)
    if not content:
        return {
            "ok": False,
            "error_code": "ARTIFACT_NOT_FOUND",
            "error": f"找不到 artifact_id={artifact_id} - 请重新 write_artifact 拿新 id.",
        }
    return _do_validate_builder_doc(content)


# ─────────────────────── 需求分析助手 → ai-builder 设计文档中转 ───────────────────────
#
# 设计目标：让需求分析助手（外部 agent 81）写完标准 md 后，把文档内容传到 ai-builder
# 后端 cache，前端 RequirementsAssistantPage 的右侧 ArtifactPanel 轮询 cache 拉到展示，
# 并提供「→ Builder」一键跳到 /chat 走应用建立流程。
#
# 用户身份反查：MCP 客户端自定义 Body 字段会注入 user_id（trial 阶段都是 1，但前面的
# _resolve_identity 已经支持从 current_app 反查真实 ai-builder 用户）。我们用反查得到
# 的 (tenant_id, user_id) 作为 cache key，避免多用户互相覆盖。
#
# Cache 是进程内的（单实例 trial 够用，生产换 redis）。

import time as _time
import uuid as _uuid

# user_id → {pending_id, file_name, md_content, score, submitted_at, source}
_REQUIREMENTS_DOC_CACHE: dict[int, dict] = {}


def _peek_requirements_doc(user_id: int) -> dict | None:
    """前端 GET /requirements/latest-doc 的内部实现 — 返回某用户最新提交的设计文档（不删除）。"""
    rec = _REQUIREMENTS_DOC_CACHE.get(int(user_id))
    if not rec:
        return None
    return dict(rec)


def _consume_requirements_doc(user_id: int, pending_id: str) -> dict | None:
    """点 → Builder 之后调一次拿走。pending_id 校验避免老缓存被误用（用户多次写文档时）。"""
    rec = _REQUIREMENTS_DOC_CACHE.get(int(user_id))
    if not rec or rec.get("pending_id") != pending_id:
        return None
    return _REQUIREMENTS_DOC_CACHE.pop(int(user_id), None)


@mcp.tool()
async def submit_design_doc(
    artifact_id: int,
    file_name: str = "design-doc.md",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把当前 md 设计文档推送到 ai-builder cache，并返回一条 deeplink — agent 必须把这条
    deeplink 贴到 chat 里让用户点击，**这是把 md 送到 Builder 的唯一推荐路径**。

    **2026-05-23 强制 artifact_id 模式** (省 token, 消除 LLM 重写 5000+ 字 md 浪费):
    - 之前 `md_content` 参数已删除. 必须先 write_artifact 拿 id, 再用 id 提交.
    - 工作流: write_artifact (返 id) → validate_builder_doc(artifact_id=id) →
      submit_design_doc(artifact_id=id)

    用法：
      1. 写完 md → write_artifact 拿 id → validate_builder_doc(artifact_id=id) 自检
         (passes_strict=true)
      2. **调本工具** submit_design_doc(artifact_id=id) — 把内容写入 ai-builder 用户 cache
      3. **把返回值里的 deeplink 用 markdown 链接格式贴在 chat 回复里**，例如：
         「✅ 已生成 sales-design.md（自检 95/100），[点这里在 Builder 中搭建](deeplink)」

    返回：
        {
            "ok": True,
            "pending_id": "...",         # 30 分钟内有效
            "expires_in_seconds": 1800,
            "score": 95,
            "deeplink": "https://ai-builder.../chat?from=requirements",
            "ui_hint": "请把 deeplink 用 markdown 链接格式贴给用户，让他点击进 Builder。"
        }

    pending_id 30 分钟后自动失效；用户修改 md 重新 write_artifact (拿新 id) 调本工具时会
    覆盖之前的 cache. deeplink 不带 pending_id —— ai-builder 端按当前登录用户从 cache
    读最新 md，避免跨用户串号。
    """
    if not artifact_id or artifact_id <= 0:
        return {
            "ok": False,
            "error_code": "MISSING_ARTIFACT_ID",
            "error": "artifact_id 必填. 请先 write_artifact 拿 id 再调本工具 (省 token).",
        }
    md_content = await _load_artifact_content(artifact_id)
    if not md_content:
        return {
            "ok": False,
            "error_code": "ARTIFACT_NOT_FOUND",
            "error": f"找不到 artifact_id={artifact_id} - 请重新 write_artifact 拿新 id.",
        }

    tid, uid = _resolve_identity(tenant_id, user_id)
    pending_id = _uuid.uuid4().hex[:16]
    score = (_do_validate_builder_doc(md_content) or {}).get("score", 0)
    rec = {
        "pending_id": pending_id,
        "file_name": (file_name or "design-doc.md").strip() or "design-doc.md",
        "md_content": md_content,
        "score": score,
        "submitted_at": _time.time(),
        "source": "agent-requirements-agent",
        "tenant_id": tid,
    }
    _REQUIREMENTS_DOC_CACHE[uid] = rec
    logger.info(
        "submit_design_doc: cached for user %s (tenant %s), file=%s, %d chars, score=%d",
        uid, tid, rec["file_name"], len(md_content), score,
    )

    # 生成 deeplink — base 留空时 deeplink 为空字符串，agent 应在 chat 里直接贴 md 文件名
    # 引导用户去 ai-builder 菜单「AI 需求分析」自己拉，但这是退化路径。生产环境务必配置。
    base = (settings.ai_builder_chat_deeplink_base or "").rstrip("/")
    deeplink = f"{base}/chat?from=requirements" if base else ""

    return {
        "ok": True,
        "pending_id": pending_id,
        "expires_in_seconds": 1800,
        "score": score,
        "deeplink": deeplink,
        "ui_hint": (
            "请把 deeplink 用 markdown 链接格式贴给用户："
            f"[点这里在 Builder 中搭建]({deeplink})。用户点了会在新 tab 进 Builder 页，"
            "自动从 cache 拿到这份 md，弹窗让他选「新建应用」或「更新现有应用」。"
        ) if deeplink else (
            "ai-builder 未配置 deeplink base —— 请告诉用户去 ai-builder 菜单「AI 需求分析」"
            "页面，刷新一下 Builder 跳转面板会自动出现这份 md。"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# aPaaS 平台内省工具集（11 个）— 复用 backend/app/coding/apaas_tools.py 实现
#
# 设计：
# - 工具实现在 coding/apaas_tools.py（双消费方：AI Coding agent 内部 + 本 MCP 外部）
# - 这一层是给外部 agent（外部 agent / Claude / Cursor）的薄壳子
# - 每个工具显式接 env_id 参数（让 caller 自己决定调哪个 aPaaS 环境）
# - workspace 类的 read_attachment / write_artifact 不外暴（caller 没 workspace 上下文）
# ═══════════════════════════════════════════════════════════════════════════


def _looks_like_apaas_401(message: str | None) -> bool:
    """识别 apaas-trial 平台 401 token 过期错误。

    背景：error_messages.is_apaas_token_error 用中文 markers（"Token已过期" 等），
    但 apaas-trial 实际 401 response 不含中文 — httpx raise_for_status 生成
    "Client error '401 ' for url 'https://.../xdap-app/...'"。这里按结构特征兜底。
    """
    if not message:
        return False
    return "401" in message and (
        "apaas" in message.lower() or "xdap-app" in message or ".definesys.cn" in message
    )


async def _refresh_apaas_env_token(env_id: int) -> bool:
    """token 过期自愈 — 用 platform_envs[env_id].username/password_enc 重 login。

    绕开 /platform-envs/{env_id}/login HTTP endpoint（那个需要 tenant_admin auth），
    在同进程内直接调 APaaSClient.login() 写回 env.token。
    """
    from sqlalchemy import select
    from app.crypto import decrypt_password
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv
    from app.apaas_client import APaaSClient

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PlatformEnv).where(PlatformEnv.id == env_id))
        env = res.scalar_one_or_none()
        if not env or not env.username or not env.password_enc:
            return False
        try:
            password = decrypt_password(env.password_enc)
            client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await client.login(env.username, password)
            token = ((login_result or {}).get("token") or "").strip()
            if not token:
                return False
            env.token = token
            env.status = "connected"
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            return False


async def _call_apaas_platform_tool(name: str, args: dict, env_id: int) -> dict:
    """统一桥接平台类 apaas 工具：调 executor → JSON 解析为 dict。

    含 token 自愈两条路径：
    1. **首次自愈** (2026-05-22): platform_envs[env_id].token 是空 (env 创建时只存了
       username/password 没自动 login) → 先 _refresh_apaas_env_token 用 password 登录
       拿 token 再调. 修用户"我都登录了为啥还说 token 为空"的体验.
    2. **过期自愈**: 调用撞 401 → 刷 token retry 一次.
    """
    from sqlalchemy import select
    from app.coding.apaas_tools import APAAS_TOOL_EXECUTORS_PLATFORM
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv

    executor = APAAS_TOOL_EXECUTORS_PLATFORM.get(name)
    if not executor:
        return {"ok": False, "error_code": "UNKNOWN_TOOL", "message": f"未知工具 {name}"}

    # 2026-05-22 首次自愈: env.token 是空 → 先 login 拿 token
    try:
        async with AsyncSessionLocal() as _db:
            _env = (await _db.execute(select(PlatformEnv).where(PlatformEnv.id == env_id))).scalar_one_or_none()
        if _env and not (_env.token or "").strip() and _env.username and _env.password_enc:
            await _refresh_apaas_env_token(env_id)
    except Exception:
        pass  # auto-login 失败不阻断后续调用, 让 executor 自己报真错

    async def _run_once() -> str:
        async with AsyncSessionLocal() as db:
            return await executor(args, env_id, db)

    result_str = await _run_once()

    # token 过期自愈：apaas-trial 401 没中文 markers，按结构识别 → 刷 token retry 一次
    if _looks_like_apaas_401(result_str):
        if await _refresh_apaas_env_token(env_id):
            result_str = await _run_once()

    try:
        return json.loads(result_str)
    except json.JSONDecodeError:
        # apaas_tools 失败约定以 'Error:' 开头返字符串
        return {"ok": False, "error_code": "APAAS_TOOL_ERROR", "message": result_str}


@mcp.tool()
async def list_apaas_apps_in_env(env_id: int) -> dict:
    """列指定 aPaaS 环境下所有应用（含 apaas_app_id / app_code / app_name / status）。

    使用场景：做应用二次开发或数据查询前的入口工具——先调它定位你要操作的应用，
    再用拿到的 apaas_app_id 调下游 list_apaas_app_menus / _app_models 等。

    使用前需要知道 env_id（一般通过 list_platform_envs 拿）。
    """
    return await _call_apaas_platform_tool("list_apaas_apps", {}, env_id)


@mcp.tool()
async def list_apaas_app_menus(env_id: int, apaas_app_id: str) -> dict:
    """列指定应用的菜单树（含每个菜单关联的 form_id / form_code）。

    使用场景：拿到 apaas_app_id 后，要找应用里的表单入口时调用。
    返回的菜单含 form_id —— 下一步可用 list_apaas_form_views 拿 tab_id、
    list_apaas_form_components 拿字段 uuid 映射。

    返回结构含 menu_id / menu_name / path / depth / menu_type / form_id / form_code。
    """
    return await _call_apaas_platform_tool(
        "list_apaas_app_menus", {"apaas_app_id": apaas_app_id}, env_id,
    )


@mcp.tool()
async def list_apaas_form_views(env_id: int, apaas_app_id: str, form_id: str) -> dict:
    """列指定表单的所有视图（拿 tab_id）。

    使用场景：listPageBusinessData 接口必须传 tab_id（一个表单常有多个视图：
    全部数据 / 我的工单 / 待审批 等），所以是查表单数据的**前置必调**步骤。

    返回 views 数组（含 tab_id / tab_name）+ default_tab_id（视图列表第一个）。
    """
    return await _call_apaas_platform_tool(
        "list_apaas_form_views",
        {"apaas_app_id": apaas_app_id, "form_id": form_id},
        env_id,
    )


@mcp.tool()
async def list_apaas_form_components(env_id: int, apaas_app_id: str, form_id: str) -> dict:
    """列指定表单的所有组件（uuid → label 映射 + 下拉选项 + 字典选项）。

    使用场景：listPageBusinessData 返回行数据 key 是 component uuid（不是字段名），
    所以前端 vue 写表头 / 渲染下拉时**必须**用本接口的映射。

    返回 components 数组，每项含 uuid / label / component_type / bo_code / required
    / choose_options（普通下拉）/ dictionary_choose_options（字典下拉）。
    """
    return await _call_apaas_platform_tool(
        "list_apaas_form_components",
        {"apaas_app_id": apaas_app_id, "form_id": form_id},
        env_id,
    )


@mcp.tool()
async def list_apaas_app_models(env_id: int, apaas_app_id: str, with_fields: bool = True) -> dict:
    """列指定应用下所有数据模型 + 字段定义。

    使用场景：做表单/页面开发时需要知道数据结构，比 list_apaas_form_components
    更底层（form 层是组件 uuid，model 层是 modelCode / boCode / dataType）。

    with_fields=False 时只列模型骨架不展开字段（省 token）。
    返回 models 数组，每项含 model_id / model_code / model_name / fields[]。
    """
    return await _call_apaas_platform_tool(
        "list_apaas_app_models",
        {"apaas_app_id": apaas_app_id, "with_fields": with_fields},
        env_id,
    )


@mcp.tool()
async def list_apaas_app_dicts(env_id: int, apaas_app_id: str, with_options: bool = True) -> dict:
    """列指定应用下所有数据字典（下拉/单选选项的来源）。

    使用场景：表单字段引用了 dict_code 时，要拿真实选项列表渲染下拉框。
    with_options=False 时只列字典骨架（dict_code / dict_name），True 时回填 options[]。
    """
    return await _call_apaas_platform_tool(
        "list_apaas_app_dicts",
        {"apaas_app_id": apaas_app_id, "with_options": with_options},
        env_id,
    )


@mcp.tool()
async def get_apaas_app_overview(env_id: int, apaas_app_id: str) -> dict:
    """精简版应用全貌：模型清单 + 字典清单（不带字段/选项详情）。

    使用场景：快速知道应用「有什么」再决定深挖，比 list_apaas_app_models 省 token。
    返回 models / dicts / models_total / dicts_total。
    """
    return await _call_apaas_platform_tool(
        "get_apaas_app_overview", {"apaas_app_id": apaas_app_id}, env_id,
    )


@mcp.tool()
async def list_apaas_models_in_env(env_id: int) -> dict:
    """列指定环境内所有模型（跨应用，含 modelCode + appCode）。

    使用场景：创建新模型前查重避免撞名（aPaaS 平台 modelCode 同租户内唯一）。
    """
    return await _call_apaas_platform_tool("list_apaas_models_in_env", {}, env_id)


@mcp.tool()
async def check_app_code_conflict(env_id: int, app_code: str) -> dict:
    """查 app_code 是否被占用（部署前预检）。

    使用场景：用户决定新应用 app_code 前，先调本工具确认不撞名。
    返回 conflict (bool) + occupants (已用此 code 的应用列表)。
    """
    return await _call_apaas_platform_tool(
        "check_app_code_conflict", {"app_code": app_code}, env_id,
    )


@mcp.tool()
async def get_apaas_doc_template_spec() -> dict:
    """拿 aPaaS Builder 设计文档官方标准（章节 / 表头 / 命名规则 / 字段类型）。

    使用场景：写 md 设计文档前先调它对齐标准 — 避免 ai-builder 解析失败。
    无需 env_id，纯静态返回（schema 是 ai-builder 内置的）。
    """
    return await _call_apaas_platform_tool("get_doc_template_spec", {}, 0)


@mcp.tool()
async def validate_apaas_builder_doc(md_content: str) -> dict:
    """轻量校验 markdown 是否符合 aPaaS Builder 标准（不创建应用、不打远端）。

    使用场景：用户产出 md 后，提交给 ai-builder 前先用本工具自检
    missing_sections / reserved_field_hits，避免反复改。
    无需 env_id，纯逻辑校验。
    """
    return await _call_apaas_platform_tool(
        "validate_builder_doc", {"md_content": md_content}, 0,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Batch 1: 应用部署 + 场景规范（4 工具）
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def deploy_application(
    app_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把 ai-builder 内 draft 应用首次部署到 aPaaS 平台（写入 apaas_app_id）。

    工作流：
      1) 内部调 SSE GET /applications/{app_id}/generate
      2) 触发 apaas_client.create_app 在 apaas 平台创建应用 → 拿 apaas_app_id
      3) 批量推送字段/模型/表单/权限到平台
      4) 完成后 apaas_app_id 已写入 + status=completed

    与 publish_application 区别：
      - 应用刚创建（apaas_app_id=null, status=draft）→ 必须先调 deploy_application
      - 已部署后改了配置 → 调 publish_application 升 version

    SSE generate 超时控制：25s 内拿不到 complete 事件 → 后台 task 继续跑，工具立即
    返 in_progress + polling_hint，避免 LLM gateway 30s timeout 拦截。
    """
    import asyncio as _asyncio
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}

    sse_token = _sign_service_token(uid, tid)
    FAST_RETURN_TIMEOUT = 25.0

    async def _run_full_sse() -> dict:
        # 2026-05-23 C 方案 B: 传 token_retry_app_id 让 SSE 撞 apaas token 过期时
        # 自动刷 token + 整段 stream 重跑. backend /generate handler 内已有
        # 'if not existing_apaas_app_id' 保护防 double create_app.
        return await _api_call_sse_collect(
            "GET",
            f"/applications/{app_id}/generate",
            tenant_id=tid,
            user_id=uid,
            params={"token": sse_token},
            timeout=600.0,
            token_retry_app_id=app_id,
        )

    sse_task = _asyncio.create_task(_run_full_sse())
    try:
        sse = await _asyncio.wait_for(_asyncio.shield(sse_task), timeout=FAST_RETURN_TIMEOUT)
    except _asyncio.TimeoutError:
        logger.info(
            "deploy_application app_id=%s SSE >%.0fs 未完成，后台继续跑，工具立即返 in_progress",
            app_id, FAST_RETURN_TIMEOUT,
        )
        return {
            "ok": True,
            "app_id": app_id,
            "status": "in_progress",
            "summary": (
                f"部署已启动并在后台继续运行（generate 流 >{int(FAST_RETURN_TIMEOUT)}s 还在跑）。"
                f"下一步：等 30-60 秒后用 `get_application(app_id={app_id})` 查 apaas_app_id 是否写入。"
            ),
            "polling_hint": {
                "next_tool": "get_application",
                "next_args": {"app_id": app_id},
                "wait_seconds": 30,
            },
        }

    if sse.get("errors"):
        return {
            "ok": False,
            "error_code": "DEPLOY_FAILED",
            "app_id": app_id,
            "message": sse["errors"][0],
            "all_errors": sse["errors"][:3],
        }

    completed = any(
        (e.get("data") or {}).get("type") == "complete" or e.get("event") == "done"
        for e in (sse.get("events") or [])
    )

    app_now = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)
    apaas_app_id = (app_now or {}).get("apaas_app_id") or (app_now or {}).get("apaasAppId")
    status = (app_now or {}).get("status")
    apaas_admin_url = (app_now or {}).get("apaas_url")

    return {
        "ok": completed and bool(apaas_app_id),
        "app_id": app_id,
        "apaas_app_id": apaas_app_id,
        "status": status,
        "apaas_admin_url": apaas_admin_url,
        "events_count": len(sse.get("events") or []),
        "summary": (
            f"首次部署完成！apaas_app_id={apaas_app_id}。后台管理：{apaas_admin_url}"
            if completed and apaas_app_id
            else "部署未完整完成，请用 get_application 检查 apaas_app_id 和 status。"
        ),
    }


# 2026-05-24 Agent C + 主分支补齐: 部署历史 + 回滚 MCP 工具
@mcp.tool()
async def list_deploy_records(
    app_id: int,
    page: int = 1,
    page_size: int = 20,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列指定 ai-builder 应用的部署历史 (含 deploy / publish / rollback 全周期记录).

    使用场景: 用户问 "这个应用部署过几次?" / "上次失败的部署详情" / 准备 rollback 前先看历史.

    返回结构: { total, page, page_size, items: [{id, version_label, status, deploy_type,
                 snapshot_version, snapshot_summary, error_message, created_at, completed_at}] }

    每条 record 含 snapshot_artifact_id 指向 SPEC 备份, status=success/failed/in_progress/rolled_back.
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}
    try:
        result = await _api_call(
            "GET",
            f"/applications/{app_id}/deploy-records",
            tenant_id=tid,
            user_id=uid,
            params={"page": page, "page_size": page_size},
        )
        return {"ok": True, **(result if isinstance(result, dict) else {"items": result})}
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "DEPLOY_RECORDS_QUERY_FAILED",
            "message": f"查部署历史失败: {exc}",
            "app_id": app_id,
        }


@mcp.tool()
async def rollback_application(
    app_id: int,
    to_record_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """回滚 ai-builder 应用到指定历史部署记录的 SPEC 快照.

    用法:
      1. 先调 list_deploy_records(app_id) 找到要回滚到的那条 record_id
      2. 调本工具 rollback_application(app_id, to_record_id=N)
      3. 工具把那个 record 的 SPEC snapshot 写回 application.config_preview, 并插一条新 record
         deploy_type='rollback'
      4. **不直接重 deploy 到 apaas** (避免长 SSE 阻塞). 工具返 next_action 提示用户接下来要
         手动触发 deploy_application 重 deploy.

    返回 { ok, record_id, snapshot_version, message, next_action }.

    使用场景: 用户发现"刚才的 update 把应用搞坏了, 回到 30 分钟前那版" / 失败部署后回滚.
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}
    if not to_record_id or to_record_id <= 0:
        return {"ok": False, "error_code": "INVALID_RECORD_ID", "message": "to_record_id 必填"}
    try:
        result = await _api_call(
            "POST",
            f"/applications/{app_id}/rollback",
            tenant_id=tid,
            user_id=uid,
            json_body={"to_record_id": to_record_id},
        )
        return {"ok": True, **(result if isinstance(result, dict) else {"result": result})}
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "ROLLBACK_FAILED",
            "message": f"回滚失败: {exc}",
            "app_id": app_id,
            "to_record_id": to_record_id,
        }


@mcp.tool()
async def list_dev_scenes() -> dict:
    """列出 ai-builder 支持的所有自开发场景类型（首次接到自开发需求时**必调**）。

    返回的是"场景索引"——精简版，只含场景识别需要的核心字段。要拿某个场景的
    完整规范（关键警示 / 必问参数 / 输出文件清单）走 `get_dev_scene_spec`。

    用法：
        step 0: list_dev_scenes()                           ← 现在
        step 1: 关键词初筛 + 用户确认场景
        step 2: get_dev_scene_spec(scene_type) 拿详情
        step 3: 用 user_inputs_needed 跟用户对齐参数
        step 4: create_dev_workspace(...)

    返回：{ok, spec_version, scenes: [{scene_type, name, one_liner, category,
    platform, keywords, typical_duration_min}, ... 10 项]}
    """
    from app.dev_scene_spec import list_scene_briefs, SPEC_VERSION
    return {
        "ok": True,
        "spec_version": SPEC_VERSION,
        "scenes": list_scene_briefs(),
    }


@mcp.tool()
async def get_dev_scene_spec(scene_type: str) -> dict:
    """拿到某个自开发场景的**完整规范**（关键警示 / 必问参数 / 输出文件清单 / 部署提示）。

    在 list_dev_scenes 选定 scene_type 后**必调一次**，把 critical_warnings 和
    user_inputs_needed 给用户看一遍——很多场景有静默失效的坑（如表单组件读
    配置必须 this.widget.customComponentConfig 不是 this.customComponentConfig）。

    入参：
        scene_type: list_dev_scenes 返回的某个 scene_type 字符串

    返回完整 scene 详情，含 when_to_use / when_NOT_to_use / user_inputs_needed /
    user_inputs_optional / file_outline / typical_duration_min / critical_warnings /
    publishable / publish_target / build_command_hint。

    scene_type 不存在时返回 ok:false + error_code SCENE_NOT_FOUND。
    """
    from app.dev_scene_spec import get_scene_brief, all_scene_types
    scene = get_scene_brief(scene_type)
    if scene is None:
        return {
            "ok": False,
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知的 scene_type: {scene_type}。可选值：{', '.join(all_scene_types())}",
            "valid_scene_types": all_scene_types(),
        }
    return {"ok": True, "scene": scene}


@mcp.tool()
async def get_dev_scene_full_workflow(scene_type: str) -> dict:
    """拿到某个自开发场景的**完整开发规范**（critical rules / 目录铁则 / mixin 速查
    / mode-specific 规则 / build 命令 / 自检清单）。

    **dev-coding skill V2 工作流第一步必调**——在 list_dev_scenes 选定 scene_type
    后立刻调本工具，把返回的 markdown 注入到当前 chat context（agent 应在写代码前
    完整阅读一遍）。这是给 agent 的 single source of truth。

    返回：{ok, scene_type, has_full_workflow, workflow_markdown(~5KB markdown)}。
    has_full_workflow=false 时返回的是通用兜底。
    """
    from app.dev_scene_workflow import get_full_workflow, has_full_workflow
    from app.dev_scene_spec import all_scene_types
    if scene_type not in all_scene_types():
        return {
            "ok": False,
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知 scene_type: {scene_type}",
            "valid_scene_types": all_scene_types(),
        }
    return {
        "ok": True,
        "scene_type": scene_type,
        "has_full_workflow": has_full_workflow(scene_type),
        "workflow_markdown": get_full_workflow(scene_type),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Batch 2: aPaaS 自开发发布 7 工具
# 全部用 env_id 显式锁定环境（不走 alias 模式）。底层复用 apaas_client。
# ═══════════════════════════════════════════════════════════════════════════


_PLATFORM_FILE_TYPES_V2_6 = {
    "FRONTENGINE": "Web端自开发页面",
    "FRONTCOMPONENT": "Web端自开发组件",
    "FRONTLAYOUT": "Web端自定义布局",
    "FRONTLISTVIEW": "Web端自定义列表视图",
    "MFRONTENGINE": "移动端自开发页面",
    "MFRONTCOMPONENT": "移动端自开发组件",
    "FRONTTENANTCOMPONENT": "平台前端自开发插件",
    "BACKENDENGINE": "后端自开发模版",
    "BACKPROPERTIES": "后端自开发配置文件",
    "BACKENDENGINEPKG": "后端自开发模版包",
    "DEPORTAL_SELF_PACKAGE": "Web端工作台/仪表板自开发组件",
    "DEPORTAL_MOBILE_SELF_PACKAGE": "移动端工作台/仪表板自开发组件",
}


async def _with_client(env_id: int, op: str, fn):
    """统一桥接：按 env_id 拿 apaas_client → 调 fn(client) → 异常包装。"""
    from app.coding.apaas_tools import _get_apaas_client
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            client = await _get_apaas_client(env_id, db)
        except Exception as exc:
            return False, {
                "ok": False, "error_code": "ENV_NOT_READY",
                "message": f"{op}失败：{exc}", "env_id": env_id,
            }
        try:
            return True, await fn(client)
        except Exception as exc:
            return False, {
                "ok": False, "error_code": "APAAS_CALL_FAILED",
                "message": f"{op}失败：{exc}", "env_id": env_id,
            }


@mcp.tool()
async def enable_apaas_self_dev_config(env_id: int, apaas_app_id: str, status: str = "ENABLE") -> dict:
    """开启 / 关闭 aPaaS 应用的「自开发配置」开关（apaas 平台 → 应用 → 高级设置）。

    publish_dev_workspace 把自开发包上传到 apaas 平台后，**必须先调本工具开启**
    应用的自开发配置，再调 attach_dev_packages_to_apaas_app 把 zip 关联到应用，
    最后 republish_apaas_app 重新发布——三步少一步前端用户都看不到组件。

    入参：env_id / apaas_app_id / status (ENABLE | DISABLE，默认 ENABLE)
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    if status not in ("ENABLE", "DISABLE"):
        return {"ok": False, "error_code": "INVALID_STATUS", "message": "status 必须是 ENABLE 或 DISABLE"}
    ok, payload = await _with_client(
        env_id, "开启自开发配置",
        lambda c: c.enable_self_dev_config(apaas_app_id.strip(), status=status),
    )
    if not ok:
        return payload
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "status": status, "message": (payload or {}).get("message", "操作成功"),
    }


@mcp.tool()
async def list_apaas_app_dev_kits(env_id: int, apaas_app_id: str, file_name_filter: str = "") -> dict:
    """列指定 apaas 应用可关联的自开发包（zip）—— 含 id / fileName / fileType。

    publish_dev_workspace 上传的 zip 会进入"自开发资源池"，本工具按 appId
    维度列出来。file_name_filter 留空时返全部；传字串时按 fileName 模糊匹配。

    后续 attach_dev_packages_to_apaas_app 需要 zip 的 **id**，先调本方法做
    fileName → id 反查；调用方按 fileName 精准匹配。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    ok, kits = await _with_client(
        env_id, "列自开发包",
        lambda c: c.query_app_dev_kits(apaas_app_id.strip(), file_name=file_name_filter),
    )
    if not ok:
        return kits
    normalized = [
        {
            "id": str(k.get("id") or ""),
            "fileName": str(k.get("fileName") or ""),
            "fileType": str(k.get("fileType") or ""),
            "size": k.get("size"),
            "userName": k.get("userName"),
            "createTime": k.get("createTime"),
        }
        for k in (kits or []) if isinstance(k, dict)
    ]
    return {"ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "kits": normalized, "total": len(normalized)}


@mcp.tool()
async def attach_dev_packages_to_apaas_app(env_id: int, apaas_app_id: str, kit_ids: list[str]) -> dict:
    """把已上传到 apaas 平台的自开发包（zip）关联到应用的「自开发资源」列表。

    前置：app 必须先开 enable_apaas_self_dev_config(ENABLE)
    后续：要看到组件生效必须 republish_apaas_app 重发版本

    入参：env_id / apaas_app_id / kit_ids（zip 的 id 列表，从 list_apaas_app_dev_kits
    或 list_apaas_resource_pool_kits 拿）
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    if not kit_ids:
        return {"ok": False, "error_code": "EMPTY_KIT_IDS", "message": "kit_ids 不能为空"}
    ok, payload = await _with_client(
        env_id, "关联自开发包",
        lambda c: c.attach_apaas_source_relation(apaas_app_id.strip(), object_ids=kit_ids),
    )
    if not ok:
        return payload
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "attached_count": len(kit_ids),
        "message": f"已关联 {len(kit_ids)} 个自开发包。下一步：republish_apaas_app 重发版本让组件生效。",
    }


@mcp.tool()
async def republish_apaas_app(env_id: int, apaas_app_id: str, abstract: str = "自开发资源更新自动重发", version: str = "") -> dict:
    """重新发布 aPaaS 应用版本（自开发变更必须 redeploy 才生效）。

    版本号策略：
      - version 留空 → 用 apaas detail.currentVersion 发（apaas 平台前端逻辑）
      - 发布报"版本错误"→ 自动 patch+1 重试一次
      - version 显式传 → 直接用

    入参：env_id / apaas_app_id / abstract（版本摘要）/ version（可选）
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}

    def _bump_patch(v: str) -> str:
        try:
            parts = [int(p) for p in v.split(".")]
            parts[-1] += 1
            return ".".join(str(p) for p in parts)
        except (ValueError, IndexError):
            return v

    async def _run(client):
        target = version.strip()
        strategy = "explicit"
        if not target:
            detail = await client.query_app_detail(apaas_app_id.strip())
            target = detail.get("currentVersion") or detail.get("appVersion") or detail.get("version") or "1.0.0"
            strategy = "currentVersion"
        try:
            result = await client.deploy_app(apaas_app_id.strip(), target, abstract=abstract)
            return {"version": target, "strategy": strategy, "raw": result}
        except Exception as e1:
            if "版本" in str(e1) or "version" in str(e1).lower():
                bumped = _bump_patch(target)
                if bumped != target:
                    result = await client.deploy_app(apaas_app_id.strip(), bumped, abstract=abstract)
                    return {"version": bumped, "strategy": f"{strategy}+bump", "raw": result,
                            "fallback_note": f"{target} 失败，patch+1 到 {bumped} 成功"}
            raise

    ok, result = await _with_client(env_id, "重新发布应用", _run)
    if not ok:
        return result
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "version": (result or {}).get("version"),
        "strategy": (result or {}).get("strategy"),
        "fallback_note": (result or {}).get("fallback_note"),
        "message": f"应用已发布到版本 {(result or {}).get('version')}",
    }


@mcp.tool()
async def create_apaas_self_dev_menu(
    env_id: int,
    apaas_app_id: str,
    menu_name: str,
    link_url: str,
    parent_id: str = "",
    menu_icon: str = "userInfo",
    icon_color: str = "#027AFF",
    menu_display: str = "PC",
) -> dict:
    """在 aPaaS 应用菜单里创建一个自开发页面菜单（menuType=CUSTOM）。

    跟普通表单菜单区别：
      - menuType: CUSTOM（非 MENU/MODEL）
      - linkUrl: 自开发组件注册名（如 'apaas-custom-form-page-xxx'）

    流程位置：自开发组件包 attach 到应用 + republish 后，要让用户**点菜单进得去**
    必须创建一个 CUSTOM 菜单链到组件 linkUrl。

    入参：env_id / apaas_app_id / menu_name / link_url / parent_id（可选）/
          menu_icon / icon_color / menu_display (PC | MOBILE | ALL)
    """
    if not apaas_app_id.strip() or not menu_name.strip() or not link_url.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id / menu_name / link_url 都不能为空"}
    ok, payload = await _with_client(
        env_id, "创建自开发菜单",
        lambda c: c.create_self_dev_menu(
            apaas_app_id.strip(),
            menu_name.strip(),
            link_url.strip(),
            parent_id=parent_id,
            menu_icon=menu_icon,
            icon_color=icon_color,
            menu_display=menu_display,
        ),
    )
    if not ok:
        return payload
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "menu_name": menu_name.strip(), "link_url": link_url.strip(),
        "message": f"自开发菜单「{menu_name.strip()}」已创建",
    }


@mcp.tool()
async def list_apaas_resource_pool_kits(
    env_id: int,
    file_type_filter: str = "",
    key_word: str = "",
    page_size: int = 50,
) -> dict:
    """**全资源池**列 apaas 平台上所有自开发包（跨应用、跨 fileType）。

    跟 list_apaas_app_dev_kits 区别：那个是**单应用**视角（只列绑到指定 app 的 zip），
    本工具是**全租户资源池**视角（跨应用）。

    用途：
      - "更新一下我之前那个评分组件" → key_word="form-component-rating" 查命中
      - 看有哪些仪表板组件 → file_type_filter="DEPORTAL_SELF_PACKAGE"
    """
    valid_filter = (file_type_filter or "").strip().upper()
    if valid_filter and valid_filter not in _PLATFORM_FILE_TYPES_V2_6:
        return {
            "ok": False, "error_code": "INVALID_FILE_TYPE",
            "message": f"file_type_filter '{file_type_filter}' 不在 V2.6 全 12 类里",
            "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
        }
    # 用 query_app_dev_kits(app_id=任意有效 id 兜底? 实际平台允许空 app_id 查全资源池)
    # 简化：app_id 用空串，apaas 平台返全租户。如果不行，agent 可改用 list_apaas_app_dev_kits 指定 app
    ok, kits = await _with_client(
        env_id, "列全资源池",
        lambda c: c.query_app_dev_kits("", file_name=key_word, page_size=page_size),
    )
    if not ok:
        return kits
    normalized = []
    for k in (kits or []):
        if not isinstance(k, dict):
            continue
        ft = str(k.get("fileType") or "")
        if valid_filter and ft.upper() != valid_filter:
            continue
        normalized.append({
            "id": str(k.get("id") or ""),
            "fileName": str(k.get("fileName") or ""),
            "fileType": ft,
            "fileTypeLabel": _PLATFORM_FILE_TYPES_V2_6.get(ft.upper(), ""),
            "version": str(k.get("version") or ""),
            "userName": k.get("userName"),
            "createTime": k.get("createTime"),
        })
    return {
        "ok": True, "env_id": env_id, "kits": normalized, "total": len(normalized),
        "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
    }


@mcp.tool()
async def upload_external_zip_to_apaas(
    env_id: int,
    file_name: str,
    file_content_b64: str,
    file_type: str,
    description: str = "",
    apaas_app_id: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """直接上传一个外部 zip 到 apaas 平台 — 内部走 multipart upload + 智能查重 update/create。

    用例：用户已经在别处 build 好一个 zip，让 agent 直接上传，不必先解压到 workspace。

    流程（一次完成）：
      1. base64 解码 zip
      2. 调 apaas selfdevelopment/query/allDevelopmentKit 按 fileName 查重
      3. 命中 → /selfdevelopment/update/developmentKit（替换同名）；
         没命中 → /selfdevelopment/add/developmentKit（新建）
      4. 可选：传 apaas_app_id 时自动 attach 到应用 + 提示需要 republish

    入参：
      env_id            平台环境 ID
      file_name         zip 文件名（含 .zip 后缀），平台拿来做查重 + 显示
      file_content_b64  zip base64 编码内容（不带 data: 前缀，建议 < 8MB）
      file_type         V2.6 全 12 类（FRONTENGINE / FRONTCOMPONENT / DEPORTAL_SELF_PACKAGE 等）
      description       可选平台侧描述
      apaas_app_id      可选 — 传则上传后自动 attach 到应用

    返回 {ok, action: 'update'|'create', kit_id, file_name, attached_to_app, message}
    """
    import base64 as _b64

    valid_ft = (file_type or "").strip().upper()
    if valid_ft not in _PLATFORM_FILE_TYPES_V2_6:
        return {"ok": False, "error_code": "INVALID_FILE_TYPE",
                "message": f"file_type '{file_type}' 不在 V2.6 全 12 类里",
                "supported_file_types": _PLATFORM_FILE_TYPES_V2_6}
    fname = file_name.strip()
    if not fname or "/" in fname or "\\" in fname:
        return {"ok": False, "error_code": "INVALID_FILE_NAME",
                "message": "file_name 只能是文件名，不能含路径分隔符"}
    if not file_content_b64.strip():
        return {"ok": False, "error_code": "EMPTY_CONTENT", "message": "file_content_b64 不能为空"}
    try:
        zip_bytes = _b64.b64decode(file_content_b64, validate=False)
    except Exception as exc:
        return {"ok": False, "error_code": "B64_DECODE_FAILED", "message": str(exc)}
    if not zip_bytes.startswith(b"PK"):
        return {"ok": False, "error_code": "NOT_A_ZIP", "message": "解码后内容不是 zip（缺 PK 头）"}
    if len(zip_bytes) > 20 * 1024 * 1024:
        return {"ok": False, "error_code": "ZIP_TOO_LARGE", "message": f"zip {len(zip_bytes)} bytes > 20MB"}

    # 拿 apaas client + token
    from app.coding.apaas_tools import _get_apaas_client
    from app.database import AsyncSessionLocal
    import httpx
    async with AsyncSessionLocal() as db:
        try:
            client = await _get_apaas_client(env_id, db)
        except Exception as exc:
            return {"ok": False, "error_code": "ENV_NOT_READY", "message": str(exc), "env_id": env_id}

        # Step 1: 查重
        try:
            kits = await client.query_app_dev_kits("", file_name=fname.replace(".zip", ""))
        except Exception as exc:
            return {"ok": False, "error_code": "QUERY_FAILED", "message": str(exc)}
        existing = next((k for k in (kits or [])
                         if isinstance(k, dict) and (k.get("fileName") == fname)), None)
        action = "update" if existing else "create"
        existing_id = (existing or {}).get("id")

        # Step 2: multipart upload
        ts = client._get_timestamp()
        upload_path = (
            "/xdap-app/selfdevelopment/update/developmentKit" if action == "update"
            else "/xdap-app/selfdevelopment/add/developmentKit"
        )
        url = f"{client.base_url}{upload_path}"
        form_data = {
            "fileName": fname,
            "fileType": valid_ft,
            "description": description or "",
        }
        if action == "update" and existing_id:
            form_data["id"] = str(existing_id)
        files = {"file": (fname, zip_bytes, "application/zip")}
        try:
            async with httpx.AsyncClient(verify=False, timeout=120.0) as h:
                resp = await h.post(
                    url,
                    headers={k: v for k, v in client._get_headers().items() if k != "Content-Type"},
                    params={"timestamp": ts},
                    data=form_data,
                    files=files,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return {"ok": False, "error_code": "UPLOAD_FAILED",
                    "message": str(exc), "action": action}
        if data.get("code") not in ("ok", 200):
            return {"ok": False, "error_code": "APAAS_UPLOAD_REJECTED",
                    "message": data.get("message", "apaas 拒绝上传"), "raw": data}
        # apaas 不同接口返结构略有差异
        result = data.get("data") or {}
        new_kit_id = str(result.get("id") or existing_id or "")

        # Step 3: 可选 auto-attach to app
        attached = False
        if apaas_app_id and new_kit_id:
            try:
                await client.attach_apaas_source_relation(apaas_app_id, object_ids=[new_kit_id])
                attached = True
            except Exception as exc:
                logger.warning("auto attach failed: %s", exc)

    return {
        "ok": True,
        "env_id": env_id,
        "action": action,
        "kit_id": new_kit_id,
        "file_name": fname,
        "file_type": valid_ft,
        "size_bytes": len(zip_bytes),
        "attached_to_app": attached,
        "apaas_app_id": apaas_app_id or None,
        "message": (
            f"{'更新' if action == 'update' else '新建'} {fname} 成功"
            + (f"，已自动关联到应用 {apaas_app_id}（记得 republish_apaas_app 让组件生效）" if attached else "")
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Batch 3: Workspace 自开发 11 工具
# 6 个 file/IDE 工具薄壳子（复用 coding/tools.py 已有 _read_file 等 executor）
# + 2 个 workspace 管理（create/status，调 internal /api/coding/workspace/* endpoint）
# + 3 个复杂 stub（save_dev_spec / import_zip / publish — 用 ai-builder UI 触发更稳）
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_workspace_path(ws_id: str, tid: int, uid: int):
    """返回 (ws_path: Path, error_dict: None) 或 (None, error_dict)。

    严格校验：meta.tenant_id 必须匹配；个人 workspace（无 project_id）user_id
    也必须匹配，防止 li.l.77 操作 admin 的 workspace。
    """
    import json as _json
    from app.coding.workspace import WorkspaceManager
    ws_mgr = WorkspaceManager()
    try:
        ws_path = ws_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        return None, {
            "ok": False, "error_code": "WORKSPACE_NOT_FOUND",
            "message": f"工作区 {ws_id} 不存在",
        }
    meta_path = ws_path / ".workspace.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta_tid = meta.get("tenant_id")
    meta_uid = meta.get("user_id")
    project_id = meta.get("project_id")
    if meta_tid is not None and int(meta_tid) != int(tid):
        return None, {
            "ok": False, "error_code": "TENANT_MISMATCH",
            "message": f"工作区 {ws_id} 不属于当前租户（meta tenant_id={meta_tid}，your tenant_id={tid}）",
        }
    if project_id is None and meta_uid is not None and int(meta_uid) != int(uid):
        return None, {
            "ok": False, "error_code": "USER_MISMATCH",
            "message": f"工作区 {ws_id} 不属于当前用户",
        }
    return ws_path, None


@mcp.tool()
async def read_workspace_file(ws_id: str, file_path: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """读取 workspace 内某个文件（vibe_agent.read_file 的 MCP 等价物）。

    file_path 是工作区根目录的相对路径（如 "src/page.vue"）。
    超过 10000 字符的文件会被截断（带 truncation 提示）。
    """
    if not file_path:
        return {"ok": False, "error_code": "INVALID_FILE_PATH", "message": "file_path 不能为空"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _read_file
    text = await _read_file({"file_path": file_path}, ws_path)
    if isinstance(text, str) and text.startswith("Error:"):
        return {"ok": False, "error_code": "FILE_READ_ERROR", "message": text}
    truncated = "(truncated," in (text or "")
    return {"ok": True, "ws_id": ws_id, "file_path": file_path, "content": text or "", "truncated": truncated}


@mcp.tool()
async def write_workspace_files(ws_id: str, files: list[dict], tenant_id: int = 0, user_id: int = 0) -> dict:
    """批量写入多个文件到 workspace（一次 RPC 解决 30+ 文件场景）。

    files 数组每项含 {"file_path": str, "content": str}。
    会自动创建中间目录。已有文件会被完整覆盖。
    """
    if not files:
        return {"ok": False, "error_code": "EMPTY_FILES", "message": "files 不能为空"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _write_file
    results = []
    failed = 0
    for f in files:
        if not isinstance(f, dict):
            results.append({"file_path": str(f), "ok": False, "error": "not a dict"})
            failed += 1
            continue
        fp = f.get("file_path") or ""
        content = f.get("content", "")
        if not fp:
            results.append({"ok": False, "error": "file_path 缺失"})
            failed += 1
            continue
        text = await _write_file({"file_path": fp, "content": content}, ws_path)
        ok = not (isinstance(text, str) and text.startswith("Error:"))
        results.append({"file_path": fp, "ok": ok, "result": text if not ok else "written"})
        if not ok:
            failed += 1
    return {
        "ok": failed == 0, "ws_id": ws_id,
        "total": len(files), "succeeded": len(files) - failed, "failed": failed,
        "results": results,
    }


@mcp.tool()
async def edit_workspace_files(ws_id: str, edits: list[dict], tenant_id: int = 0, user_id: int = 0) -> dict:
    """批量对多个文件做精确字符串替换（vibe_agent.edit_file 的 batch MCP 等价）。

    edits 数组每项含 {"file_path": str, "old_str": str, "new_str": str}。
    old_str 必须**唯一**匹配文件中一段，否则报错（防止误改）。
    """
    if not edits:
        return {"ok": False, "error_code": "EMPTY_EDITS", "message": "edits 不能为空"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _edit_file
    results = []
    failed = 0
    for e in edits:
        if not isinstance(e, dict):
            results.append({"ok": False, "error": "not a dict"})
            failed += 1
            continue
        text = await _edit_file(e, ws_path)
        ok = not (isinstance(text, str) and text.startswith("Error:"))
        results.append({"file_path": e.get("file_path"), "ok": ok, "result": text})
        if not ok:
            failed += 1
    return {
        "ok": failed == 0, "ws_id": ws_id,
        "total": len(edits), "succeeded": len(edits) - failed, "failed": failed,
        "results": results,
    }


@mcp.tool()
async def glob_workspace(ws_id: str, pattern: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """按 glob pattern 列工作区文件（vibe_agent.glob_files 等价）。

    示例：pattern="src/**/*.vue" / "**/*.json"。
    """
    if not pattern:
        return {"ok": False, "error_code": "INVALID_PATTERN", "message": "pattern 不能为空"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _glob_files
    result = await _glob_files({"pattern": pattern}, ws_path)
    if isinstance(result, str) and result.startswith("Error:"):
        return {"ok": False, "error_code": "GLOB_FAILED", "message": result}
    return {"ok": True, "ws_id": ws_id, "pattern": pattern, "result": result}


@mcp.tool()
async def grep_workspace(ws_id: str, pattern: str, file_pattern: str = "", tenant_id: int = 0, user_id: int = 0) -> dict:
    """在工作区内 grep 正则搜索（vibe_agent.grep_search 等价）。

    file_pattern 可选，限定搜索文件类型（如 "*.vue" / "*.js"）。
    """
    if not pattern:
        return {"ok": False, "error_code": "INVALID_PATTERN", "message": "pattern 不能为空"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _grep_search
    args = {"pattern": pattern}
    if file_pattern:
        args["file_pattern"] = file_pattern
    result = await _grep_search(args, ws_path)
    if isinstance(result, str) and result.startswith("Error:"):
        return {"ok": False, "error_code": "GREP_FAILED", "message": result}
    return {"ok": True, "ws_id": ws_id, "pattern": pattern, "result": result}


@mcp.tool()
async def run_workspace_command(ws_id: str, command: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """在 workspace 根目录跑 shell 命令（vibe_agent.run_command 等价）。

    常用：`npm install` / `npm run build` / `ls -la`。
    长输出会被截断。失败时返回 stderr + exit code。
    """
    if not command:
        return {"ok": False, "error_code": "INVALID_COMMAND", "message": "command 不能为空"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _run_command
    text = await _run_command({"command": command}, ws_path, None)
    if isinstance(text, str) and text.startswith("Error:"):
        return {"ok": False, "error_code": "COMMAND_FAILED", "message": text}
    return {"ok": True, "ws_id": ws_id, "command": command, "output": text}


@mcp.tool()
async def get_dev_workspace_status(ws_id: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """查询自开发 workspace 的当前状态（文件列表 / build 状态 / 关联对话 / 后台命令）。

    用于 agent 在调过 create_dev_workspace 后跟进，或者 publish 前确认 build 完成。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    res = await _api_call("GET", f"/coding/workspace/{ws_id}", tenant_id=tid, user_id=uid)
    return res if isinstance(res, dict) else {"ok": False, "raw": res}


@mcp.tool()
async def create_dev_workspace(
    scene_type: str,
    project_name: str,
    display_name: str = "",
    initial_requirement: str = "",
    apaas_app_id: str = "",
    apaas_app_name: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在 ai-builder /coding 下创建一个自开发 workspace（脚手架已就位、可以开始写代码）。

    内部调本机 POST /api/coding/workspace/create — 脚手架由 df-apaas-cli 拉模板，
    所有 .cursor/rules/*.mdc 默认规则文件已经被复制到工作区。

    入参：
        scene_type           list_dev_scenes 返回的 scene_type
        project_name         英文短名（kebab-case），如 "form-page-home-dashboard"
        display_name         中文名（用户看得到的标题）
        initial_requirement  跟用户对齐好的需求 brief（200-2000 字），自动喂给 vibe_agent

    返回：{ok, ws_id, scene_type, project_name, display_name}
    """
    from app.dev_scene_spec import all_scene_types
    if scene_type not in all_scene_types():
        return {
            "ok": False, "error_code": "SCENE_NOT_FOUND",
            "message": f"未知 scene_type: {scene_type}",
            "valid_scene_types": all_scene_types(),
        }
    if not project_name.strip():
        return {"ok": False, "error_code": "INVALID_PROJECT_NAME", "message": "project_name 不能为空"}

    tid, uid = _resolve_identity(tenant_id, user_id)
    # /coding/workspace/create 实际签名 (CreateWorkspaceRequest):
    #   project_type / project_name / display_name (可选) / project_id (可选)
    # 不接 initial_requirement / apaas_app_id / apaas_app_name —— 这些是工具层语义参数，
    # 拿不到对应字段就先丢弃（后续如果加 application 关联可走 POST /applications/...）
    payload = {
        "project_type": scene_type,  # scene_type 跟 ProjectType 枚举值一致
        "project_name": project_name.strip(),
        "display_name": (display_name or "").strip() or project_name.strip(),
    }
    res = await _api_call("POST", "/coding/workspace/create", tenant_id=tid, user_id=uid, json_body=payload)
    ws_id = (res or {}).get("ws_id") or (res or {}).get("id") or (res or {}).get("workspace_id")
    if isinstance(res, dict) and ws_id:
        return {
            "ok": True,
            "ws_id": ws_id,
            "scene_type": scene_type,
            "project_name": project_name.strip(),
            "display_name": display_name or project_name,
            "tenant_id": tid,
            "user_id": uid,
            "next_steps": [
                f"用 get_dev_workspace_status('{ws_id}') 查工作区状态",
                "用 read_workspace_file / write_workspace_files / edit_workspace_files 写代码",
                "完成后 run_workspace_command('npm run build') + publish_dev_workspace",
            ],
            "note_unused_args": (
                "initial_requirement / apaas_app_id / apaas_app_name 这次未传给底层 endpoint"
                "（当前 /coding/workspace/create 不接这些字段）；如需要让 vibe_agent "
                "拿到 brief，请 workspace 创建后用 write_workspace_files 写 .coding-pending-requirement.txt"
                if (initial_requirement or apaas_app_id or apaas_app_name) else None
            ),
        }
    return {"ok": False, "error_code": "CREATE_FAILED", "message": "create_workspace 返回异常", "raw": res}


@mcp.tool()
async def save_dev_spec(
    ws_id: str,
    project_name: str,
    spec_md: str,
    mockup_html: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """Phase 1 必调：落盘双产物（技术 SPEC + 业务可视 HTML mockup）到 workspace。

    落到 workspace `.dev-spec/<project_name>/` 目录：
      spec.md      技术 SPEC（给 LLM 看，含 form_id / tab_id / uuid 真值）
      mockup.html  业务可视 HTML mockup（给用户审，单文件 CDN 引 echarts/element-ui）

    流程：
      1. 调元数据工具拿完 form_views / form_components 等
      2. 写 spec_md（技术）和 mockup_html（业务，看板/列表场景必填）
      3. 调本工具一次落两份盘
      4. 给用户业务摘要 + spec_md 关键片段（用 markdown 代码块展示）
      5. 等用户表态 OK 后继续 write_workspace_files 写代码

    入参：
      ws_id         workspace ID（AI Coding 'X_xxx' 或 Vibe 'oc_xxx' 都行）
      project_name  英文短名（kebab-case），决定 .dev-spec 子目录
      spec_md       技术 SPEC markdown（至少 100 字符）
      mockup_html   业务 HTML（可选；看板类强烈建议）

    返回 {ok, ws_id, project_name, spec_path, mockup_path?, preview_path}
    """
    import re as _re
    from pathlib import Path
    if not _re.match(r"^[a-zA-Z0-9_\-]+$", project_name):
        return {"ok": False, "error_code": "INVALID_PROJECT_NAME",
                "message": "project_name 只能含 字母/数字/_/-"}
    if not spec_md or len(spec_md.strip()) < 100:
        return {"ok": False, "error_code": "SPEC_TOO_SHORT",
                "message": f"spec_md 太短 ({len(spec_md.strip())} 字符)，至少 100 字符"}
    tid, uid = _resolve_identity(tenant_id, user_id)

    # 同时支持 AI Coding workspace 和 Vibe Coding workspace
    if ws_id.startswith("oc_"):
        # Vibe workspace: 走 online_coding._find_workspace_dir
        from app.routes.online_coding import _find_workspace_dir
        try:
            ws_dir, _meta = _find_workspace_dir(ws_id)
            repo_dir = ws_dir / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"ok": False, "error_code": "WORKSPACE_NOT_FOUND",
                    "message": f"vibe workspace {ws_id} 找不到: {exc}"}
    else:
        # AI Coding workspace: WorkspaceManager
        from app.coding.workspace import WorkspaceManager
        try:
            repo_dir = WorkspaceManager().get_workspace_path(ws_id)
        except FileNotFoundError:
            return {"ok": False, "error_code": "WORKSPACE_NOT_FOUND",
                    "message": f"workspace {ws_id} 找不到"}

    spec_root = repo_dir / ".dev-spec" / project_name
    spec_root.mkdir(parents=True, exist_ok=True)
    spec_path = spec_root / "spec.md"
    spec_path.write_text(spec_md, encoding="utf-8")

    out: dict[str, Any] = {
        "ok": True,
        "ws_id": ws_id,
        "project_name": project_name,
        "spec_path": f".dev-spec/{project_name}/spec.md",
        "spec_bytes": len(spec_md.encode("utf-8")),
        "preview_path": f".dev-spec/{project_name}/",
        "next_steps": [
            "用 read_workspace_file 读 .dev-spec/<project>/spec.md 拿回内容（供下次迭代）",
            "在 chat 里给用户业务摘要 + 等用户确认",
            "确认后 → write_workspace_files / vibe_write_file 开始写代码",
        ],
    }
    if mockup_html.strip():
        mockup_path = spec_root / "mockup.html"
        mockup_path.write_text(mockup_html, encoding="utf-8")
        out["mockup_path"] = f".dev-spec/{project_name}/mockup.html"
        out["mockup_bytes"] = len(mockup_html.encode("utf-8"))
        out["has_mockup"] = True
    return out


@mcp.tool()
async def import_zip_to_workspace(
    task: str,
    zip_b64: str,
    project_name: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把外部 zip（base64）解压成新的 Vibe Coding workspace（不绑 aPaaS）。

    用例：二次开发场景接现有项目，用户提供项目 zip。

    入参：
      task         workspace 一句话任务（写到 meta）
      zip_b64      zip 文件 base64 编码（不带 data: 前缀，建议 < 8MB）
      project_name 可选 — 解压后的根目录名

    返回 {ok, ws_id, file_count, files_sample, task}
    """
    import base64 as _b64
    import io
    import zipfile

    if not zip_b64.strip():
        return {"ok": False, "error_code": "EMPTY_ZIP", "message": "zip_b64 不能为空"}

    # 解码 base64
    try:
        raw = _b64.b64decode(zip_b64, validate=False)
    except Exception as exc:
        return {"ok": False, "error_code": "B64_DECODE_FAILED", "message": str(exc)}
    if len(raw) > 20 * 1024 * 1024:
        return {"ok": False, "error_code": "ZIP_TOO_LARGE",
                "message": f"zip 解码后 {len(raw)} bytes > 20MB"}

    # 解析 zip 结构（先校验合法 + 列文件）
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
        names = zf.namelist()
    except zipfile.BadZipFile:
        return {"ok": False, "error_code": "BAD_ZIP", "message": "不是合法的 zip 文件"}

    # 先建一个新 vibe workspace
    tid, uid = _resolve_identity(tenant_id, user_id)
    create_payload = {"task": task or "导入 zip 项目", "repo_url": None}
    res = await _api_call("POST", "/online-coding/workspaces",
                          tenant_id=tid, user_id=uid, json_body=create_payload)
    if not isinstance(res, dict) or not (res.get("id") or "").startswith("oc_"):
        return {"ok": False, "error_code": "WS_CREATE_FAILED",
                "message": "创建 workspace 失败", "raw": res}
    ws_id = res["id"]

    # 解压到 workspace/repo
    from app.routes.online_coding import _find_workspace_dir
    try:
        ws_dir, _meta = _find_workspace_dir(ws_id)
        repo_dir = ws_dir / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"ok": False, "error_code": "WS_RESOLVE_FAILED", "message": str(exc), "ws_id": ws_id}

    # 安全解压（防 zip slip）
    safe_count = 0
    for member in zf.namelist():
        # 拒绝绝对路径 / 包含 ..
        if member.startswith("/") or ".." in member.split("/"):
            continue
        # 拒绝以 / 开头的成员
        target = (repo_dir / member).resolve()
        try:
            target.relative_to(repo_dir.resolve())
        except ValueError:
            continue  # 越界
        if member.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as dst:
            dst.write(src.read())
        safe_count += 1

    return {
        "ok": True,
        "ws_id": ws_id,
        "task": task,
        "file_count": safe_count,
        "files_sample": names[:10],
        "next_steps": [
            f"vibe_get_workspace_status('{ws_id}') 看完整状态",
            f"vibe_glob('{ws_id}', 'package.json') 找入口配置",
            "看完代码后用 vibe_run_command('npm install') 装依赖",
        ],
    }


@mcp.tool()
async def publish_dev_workspace(
    ws_id: str,
    env_id: int,
    skip_lint: bool = False,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把 AI Coding workspace build 产物部署到 aPaaS 平台。

    内部调 POST /coding/workspace/{ws_id}/upload-to-platform，
    后端自动：build → 打 zip → upload to apaas → 查重判 update/create。
    上传成功后再用 attach_dev_packages_to_apaas_app + republish_apaas_app 让组件生效。

    ⚠️ 仅支持 AI Coding workspace（'X_xxx' 格式）。Vibe Coding workspace ('oc_xxx') 不绑
    aPaaS 平台，无需 publish；如需上传到 apaas 应自己用 vibe_run_command 打 zip
    再用 upload_external_zip_to_apaas（实现中）。

    入参：
      ws_id     AI Coding workspace ID (不以 'oc_' 开头)
      env_id    平台环境 ID（apaas 部署目标）
      skip_lint 默认 false — publish 前先 lint，发现 fatal 问题就拒绝上传；
                改 true 跳过 lint 强发（不推荐）

    返回 internal endpoint 原样响应 — 含 uploaded_kits / errors 等
    """
    if ws_id.startswith("oc_"):
        return {"ok": False, "error_code": "WRONG_WS_TYPE",
                "message": "publish_dev_workspace 只支持 AI Coding workspace（非 oc_ 前缀）。"
                           "Vibe workspace 请自己 zip + 用 upload_external_zip_to_apaas"}
    if not env_id:
        return {"ok": False, "error_code": "INVALID_ENV_ID", "message": "env_id 必填"}

    tid, uid = _resolve_identity(tenant_id, user_id)

    # 上传前 lint 预检 — 防止把含 fatal 坑的代码发出去
    if not skip_lint:
        try:
            lint_res = await lint_apaas_backend_workspace.fn(
                ws_id=ws_id, tenant_id=tid, user_id=uid,
            )
        except Exception as exc:
            # lint 自身崩了 — 提示但不拦截
            lint_res = {
                "ok": False, "files_scanned": -1,
                "lint_internal_error": str(exc),
            }
        if lint_res.get("files_scanned", 0) > 0 and lint_res.get("fatal_count", 0) > 0:
            return {
                "ok": False, "error_code": "LINT_FAILED_BEFORE_PUBLISH",
                "message": (f"lint 发现 {lint_res['fatal_count']} 个 fatal 问题，"
                            f"先修了再发；想强发请传 skip_lint=true（不推荐）"),
                "lint_findings": [f for f in lint_res.get("findings", [])
                                  if f.get("severity") == "fatal"][:20],
                "hint": "调 lint_apaas_backend_workspace 看全部 findings 详情",
            }

    try:
        res = await _api_call(
            "POST", f"/coding/workspace/{ws_id}/upload-to-platform",
            tenant_id=tid, user_id=uid, json_body={"env_id": env_id},
            timeout=600.0,  # build + upload 可能耗时
        )
    except Exception as exc:
        # _api_call HTTP 4xx/5xx 时 raise — detail 里可能含 build / upload 失败原因，
        # 按关键词分类成 error_code 让 agent 知道下一步做什么。
        detail = str(exc)
        return _classify_publish_failure(ws_id, env_id, detail)

    if isinstance(res, dict):
        return {"ok": True, "ws_id": ws_id, "env_id": env_id, **res}
    return {"ok": False, "error_code": "UPLOAD_FAILED", "raw": res}


def _classify_publish_failure(ws_id: str, env_id: int, detail: str) -> dict:
    """publish 失败时按 detail 字符串里的 keyword 分类。

    跟 workspace.diagnose_build_failure 的 error_code 对齐 — agent 拿到同一套码可
    决定动作（去查 settings.xml / 改 JDK / 调 doctor / 调 lint 等）。
    """
    d = detail or ""
    error_code, hint = "UPLOAD_FAILED", None

    if "401 Unauthorized" in d or "Authentication failed" in d:
        error_code = "MVN_AUTH_FAIL"
        hint = "Maven Nexus 认证失败 — 调 doctor_apaas_backend_workspace 看 settings.xml 配置"
    elif "Could not resolve dependencies" in d or "Could not find artifact" in d:
        error_code = "MVN_DEPS_RESOLVE_FAIL"
        hint = "依赖拉不到 — 调 doctor_apaas_backend_workspace 排查 pom <repositories> + settings.xml"
    elif "The requested profile" in d and "could not be activated" in d:
        error_code = "MVN_PROFILE_NOT_FOUND"
        hint = "-P lib profile 不存在 — 调 init_apaas_backend_workspace 重写 pom"
    elif "source release" in d and "requires target release" in d:
        error_code = "MVN_JDK_MISMATCH"
        hint = "JDK 版本不匹配 — JAVA_HOME 切 JDK 8"
    elif ("COMPILATION ERROR" in d or "cannot find symbol" in d
            or "package does not exist" in d):
        error_code = "MVN_COMPILE_FAIL"
        hint = "Java 编译错 — 先调 lint_apaas_backend_workspace 看代码问题"
    elif "BUILD FAILURE" in d or "Failed to execute goal" in d:
        error_code = "MVN_BUILD_FAILURE"
        hint = "Maven BUILD FAILURE — 调 doctor_apaas_backend_workspace 排查环境配置"
    elif "Failed to compile" in d or "[eslint]" in d:
        error_code = "FE_COMPILE_FAIL"
        hint = "前端编译失败 — 看 eslint / TS 错"
    elif "构建失败" in d:
        error_code = "BUILD_FAILED"
        hint = "构建失败但未识别具体原因 — 调 doctor 体检 + 看 backend log 完整错"

    return {
        "ok": False,
        "error_code": error_code,
        "ws_id": ws_id,
        "env_id": env_id,
        "message": detail[:1000],
        "hint": hint,
        "next_step": (
            "调 doctor_apaas_backend_workspace 看打包前置问题；"
            "调 lint_apaas_backend_workspace 看代码问题；"
            "都没问题再看 backend log /tmp/apaas-backend.log 完整错"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Vibe Coding 工具集（11 个）— 平行于 layer 2 的 11 个 workspace 工具
# 操作 Vibe Coding workspace（id 格式 oc_xxx，跟 layer 2 的 1_xxx 完全独立）
#
# 用途：让外部 agent / Claude 等外部 agent 能接入 vibe-coding 的"从零搭独立项目"能力，
# 跟 aPaaS 无关，纯通用 IDE 开发。
# ═══════════════════════════════════════════════════════════════════════════


async def _resolve_vibe_thread(ws_id: str, tid: int, uid: int):
    """从 ws_id 解析出 VibeCodingThread + 已开的 db session。

    返回 (thread, db_session_ctx, error_dict)；ctx 失败时为 None。
    调用方负责把 ctx 用 async with 包起来，结束时 close。

    实际用法（避免泄漏）：
        gen = _resolve_vibe_thread_ctx(...)
        async for thread, db in gen:
            ...
    """
    # 这版直接返回构造好的 thread + new db session — 调用方走完 release
    from app.database import AsyncSessionLocal
    from app.models import VibeCodingThread
    from app.vibe_coding.workspace import find_workspace
    from sqlalchemy import select

    found = find_workspace(ws_id)
    if not found:
        return None, None, {"ok": False, "error_code": "WORKSPACE_NOT_FOUND",
                            "message": f"Vibe Coding workspace {ws_id} 不存在"}
    _, meta = found
    meta_tid = meta.get("tenant_id")
    if meta_tid is not None and int(meta_tid) != int(tid):
        return None, None, {"ok": False, "error_code": "TENANT_MISMATCH",
                            "message": f"workspace 不属于当前租户"}
    db = AsyncSessionLocal()
    res = await db.execute(select(VibeCodingThread).where(VibeCodingThread.workspace_id == ws_id))
    thread = res.scalar_one_or_none()
    if not thread:
        # 用户没进过 chat → 没建 thread → 临时建一条（owner=uid，title 用 task 兜底）
        thread = VibeCodingThread(
            workspace_id=ws_id,
            tenant_id=int(meta_tid or tid),
            owner_user_id=int(meta.get("user_id") or uid),
            title=(meta.get("task") or "MCP 接入"),
            status="active",
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return thread, db, None


async def _call_vibe_executor(executor_name: str, args: dict, ws_id: str, tenant_id: int, user_id: int) -> dict:
    """统一桥接 — 拿 thread + db → 调 vibe_coding.tools 的 execute_* → 包装 ok/error。"""
    from app.vibe_coding import tools as _vibe_tools
    executor = getattr(_vibe_tools, executor_name, None)
    if not executor:
        return {"ok": False, "error_code": "UNKNOWN_EXECUTOR", "message": f"未知 executor {executor_name}"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    thread, db, err = await _resolve_vibe_thread(ws_id, tid, uid)
    if err:
        return err
    try:
        result_text = await executor(args or {}, thread, db)
    except Exception as exc:
        logger.exception("vibe tool %s failed", executor_name)
        try: await db.close()
        except Exception: pass
        return {"ok": False, "error_code": "VIBE_TOOL_ERROR", "message": str(exc)}
    try: await db.close()
    except Exception: pass
    if isinstance(result_text, str) and result_text.startswith("Error:"):
        return {"ok": False, "error_code": "VIBE_TOOL_FAILED", "message": result_text, "ws_id": ws_id}
    return {"ok": True, "ws_id": ws_id, "result": result_text}


@mcp.tool()
async def vibe_create_workspace(
    task: str,
    repo_url: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在 Vibe Coding（纯自开发 / 通用 IDE）下创建一个新工作区。

    跟 create_dev_workspace 区别：
      - 这是 layer 3 vibe-coding（从零搭独立项目，跟 aPaaS 无关）
      - create_dev_workspace 是 layer 2 aPaaS 二开（必须绑 platform_env + scene_type）

    入参：
      task     开发任务一句话描述（写到 workspace meta，agent 用作开场理解）
      repo_url 可选 — 传则从 Git clone 进 workspace；不传则建空目录让 agent 脚手架

    返回 {ok, ws_id, task, repo_url, next_steps[]}；ws_id 格式 'oc_xxxxxx'。
    """
    if not task.strip() and not repo_url.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "task 和 repo_url 至少传一个"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    payload = {"task": task.strip(), "repo_url": repo_url.strip() or None}
    res = await _api_call("POST", "/online-coding/workspaces",
                          tenant_id=tid, user_id=uid, json_body=payload)
    if isinstance(res, dict) and (res.get("id") or "").startswith("oc_"):
        ws_id = res["id"]
        return {
            "ok": True,
            "ws_id": ws_id,
            "task": task.strip(),
            "repo_url": repo_url.strip() or None,
            "status": res.get("status"),
            "next_steps": [
                f"vibe_get_workspace_status('{ws_id}') 查状态",
                f"vibe_read_file / vibe_write_file / vibe_run_command 操作文件",
                f"vibe_todo_write 维护 TODO；vibe_http_check 起服务后健康检查",
            ],
        }
    return {"ok": False, "error_code": "CREATE_FAILED", "message": "创建 vibe workspace 失败",
            "raw": res}


@mcp.tool()
async def vibe_get_workspace_status(ws_id: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """查询 Vibe Coding workspace 状态（status / file_count / files / 沙箱状态等）。

    入参：ws_id 必须以 'oc_' 开头（vibe-coding workspace ID 格式）
    """
    if not ws_id.startswith("oc_"):
        return {"ok": False, "error_code": "INVALID_WS_ID",
                "message": f"ws_id 必须以 'oc_' 开头（这是 vibe-coding workspace 格式）"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    res = await _api_call("GET", f"/online-coding/workspaces/{ws_id}",
                          tenant_id=tid, user_id=uid)
    return res if isinstance(res, dict) else {"ok": False, "raw": res}


@mcp.tool()
async def vibe_read_file(
    ws_id: str, path: str, offset: int = 0, limit: int = 0,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """读 Vibe Coding workspace 内某个文件的文本内容。

    入参：
      ws_id   workspace ID（oc_xxx）
      path    相对路径（如 'src/page.vue'）
      offset  起始行（1-based，0=从头）
      limit   读取行数上限（0=全部）
    """
    args = {"path": path}
    if offset > 0: args["offset"] = offset
    if limit > 0: args["limit"] = limit
    return await _call_vibe_executor("execute_read_file", args, ws_id, tenant_id, user_id)


@mcp.tool()
async def vibe_write_file(
    ws_id: str, path: str, content: str,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """把文本完整写入 Vibe Coding workspace 内某个文件（覆盖式）。目录不存在自动建。"""
    return await _call_vibe_executor(
        "execute_write_file", {"path": path, "content": content},
        ws_id, tenant_id, user_id,
    )


@mcp.tool()
async def vibe_edit_file(
    ws_id: str, path: str, old_string: str, new_string: str,
    replace_all: bool = False,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """精确字符串替换 Vibe Coding workspace 内某个文件。old_string 必须唯一匹配，
    除非 replace_all=true。比 write_file 更安全（不会误覆盖未读部分）。"""
    return await _call_vibe_executor(
        "execute_edit_file",
        {"path": path, "old_string": old_string, "new_string": new_string, "replace_all": replace_all},
        ws_id, tenant_id, user_id,
    )


@mcp.tool()
async def vibe_glob(ws_id: str, pattern: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """按 glob pattern 列 Vibe Coding workspace 文件（如 '**/*.vue' / 'src/**/*.ts'）。
    结果按修改时间倒序，最多 200 条。"""
    return await _call_vibe_executor("execute_glob", {"pattern": pattern},
                                     ws_id, tenant_id, user_id)


@mcp.tool()
async def vibe_grep(
    ws_id: str, pattern: str, path: str = "", glob: str = "",
    ignore_case: bool = False,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """在 Vibe Coding workspace 内 grep 搜索（Python re 语法）。

    入参：
      pattern      正则表达式
      path         限定子目录（可选）
      glob         限定文件类型 glob（如 '*.py'，可选）
      ignore_case  大小写不敏感
    """
    args = {"pattern": pattern, "ignore_case": ignore_case}
    if path: args["path"] = path
    if glob: args["glob"] = glob
    return await _call_vibe_executor("execute_grep", args, ws_id, tenant_id, user_id)


@mcp.tool()
async def vibe_run_command(
    ws_id: str, command: str,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """在 Vibe Coding workspace 内跑 shell 命令（如 'npm install' / 'npm run dev'）。

    跑在 docker 沙箱里（端口段：6173 前端 / 6300 后端 / 6400 / 6500 备用）；
    跑后台服务用 run_in_background。
    """
    return await _call_vibe_executor("execute_run_command", {"command": command},
                                     ws_id, tenant_id, user_id)


@mcp.tool()
async def vibe_todo_write(
    ws_id: str, todos: list,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """更新 Vibe Coding workspace 的 TODO 列表（agent 拆任务用）。

    todos 数组每项 {id: str, content: str, status: 'pending'|'in_progress'|'completed'}。
    同时只能有一个 in_progress；前端会渲染成 checklist。
    """
    return await _call_vibe_executor("execute_todo_write", {"todos": todos},
                                     ws_id, tenant_id, user_id)


@mcp.tool()
async def vibe_http_check(
    ws_id: str, url: str,
    tenant_id: int = 0, user_id: int = 0,
) -> dict:
    """HTTP 检查 Vibe Coding workspace 内服务的健康状态（agent 起 dev server 后用）。

    入参：
      url    完整 URL（如 'http://localhost:6173' / 'http://localhost:6300/api/health'）

    返回 status_code / body 前 1000 字 / 错误信息（连不上 / 超时等）。
    """
    return await _call_vibe_executor("execute_http_check", {"url": url},
                                     ws_id, tenant_id, user_id)


# ═══════════════════════════════════════════════════════════════════════════
# aPaaS 应用配置精细操作（角色 CRUD）
#
# 跟 SPEC 文档流程（update_app_from_doc → execute_change_plan）的区别：
# 这些工具是**直接对话式精细操作**，agent 可以在跟用户聊天时直接增删改查应用元素，
# 不必走"写新版 md → diff → 执行"流程。适合用户说"加个 XX 角色"这种增量需求。
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_apaas_app_roles(env_id: int, apaas_app_id: str, keyword: str = "") -> dict:
    """列指定 aPaaS 应用的角色清单（含 roleId / roleCode / roleName / 启用状态）。

    可选 keyword 模糊过滤。返回的 roleId 给后续 update / delete / 加成员用。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 必填"}
    ok, raw = await _with_client(
        env_id, "列角色",
        lambda c: c.query_roles(apaas_app_id.strip(), keyword=keyword or ""),
    )
    if not ok:
        return raw
    roles = []
    for r in (raw or []):
        if not isinstance(r, dict):
            continue
        roles.append({
            "role_id": str(r.get("id") or r.get("roleId") or ""),
            "role_code": str(r.get("roleCode") or r.get("code") or ""),
            "role_name": str(r.get("roleName") or r.get("name") or ""),
            "use_scope": str(r.get("useScope") or ""),
            "internal_resource": bool(r.get("internalResource", False)),
            "enable_group_param": str(r.get("enableGroupParam") or "DISABLE"),
        })
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "roles": roles, "total": len(roles),
    }


@mcp.tool()
async def create_apaas_app_roles(env_id: int, apaas_app_id: str, roles: list) -> dict:
    """批量创建 aPaaS 应用角色（不走 SPEC 文档流程，直接调 apaas 平台）。

    入参 roles 数组每项至少含 {role_code: str, role_name: str}，可选：
      use_scope (str)         角色作用域，默认应用名
      internal_resource (bool) 是否系统资源，默认 true
      enable_group_param (str) DISABLE / ENABLE，默认 DISABLE
      role_params (list)       角色参数定义（高级，一般留空）

    示例：roles=[{"role_code":"reviewer","role_name":"审批人"},
                {"role_code":"admin","role_name":"管理员"}]

    跟"走 SPEC 文档 update_app_from_doc + execute_change_plan"的区别：
      - 这个：直接对话场景"加 X 角色"，一步建好
      - SPEC 流程：用户给完整新版 md，自动 diff 出所有变更（适合大改）

    创建后调 publish_application 或 republish_apaas_app 让用户能看到。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 必填"}
    if not roles or not isinstance(roles, list):
        return {"ok": False, "error_code": "INVALID_ROLES", "message": "roles 必须是非空数组"}
    # 规整 payload 到 apaas 平台需要的字段（驼峰）
    # 2026-05-24 修 silent-fail bug: 每项 role 必须含 appId 字段,
    # 跟 step_executor.py:236 (generator_v2 真成功路径) 一致.
    # 之前漏 appId 导致 apaas 平台返 200 ok 但角色不创建 (实测 ops_admin 案例).
    apaas_app_id_clean = apaas_app_id.strip()
    payload_roles = []
    for r in roles:
        if not isinstance(r, dict):
            continue
        code = (r.get("role_code") or r.get("roleCode") or "").strip()
        name = (r.get("role_name") or r.get("roleName") or "").strip()
        if not code or not name:
            return {"ok": False, "error_code": "INVALID_ROLE_ITEM",
                    "message": f"每个 role 必须有 role_code + role_name；问题项：{r}"}
        payload_roles.append({
            "appId": apaas_app_id_clean,    # ← 必填, 漏了 apaas silent fail
            "roleCode": code,
            "roleName": name,
            "useScope": r.get("use_scope") or r.get("useScope") or "",
            "internalResource": bool(r.get("internal_resource", r.get("internalResource", True))),
            "enableGroupParam": r.get("enable_group_param") or r.get("enableGroupParam") or "DISABLE",
            "roleParams": r.get("role_params") or r.get("roleParams") or [],
        })

    ok, raw = await _with_client(
        env_id, "批量建角色",
        lambda c: c.create_roles(apaas_app_id.strip(), payload_roles),
    )
    if not ok:
        return raw
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "created_count": len(payload_roles),
        "roles_summary": [{"role_code": r["roleCode"], "role_name": r["roleName"]} for r in payload_roles],
        "next_step": "调 publish_application(app_id) 或 republish_apaas_app(env_id, apaas_app_id) 让角色生效",
    }


@mcp.tool()
async def update_apaas_app_role(
    env_id: int, apaas_app_id: str, role_id: str,
    role_code: str = "", role_name: str = "",
    app_name: str = "", enable_group_param: str = "DISABLE",
    role_params: list | None = None,
) -> dict:
    """更新单个 aPaaS 角色（不走 SPEC，直接对话改）。

    先调 list_apaas_app_roles 拿到 role_id，再调本工具改 role_code / role_name 等。
    role_code / role_name 留空时不强制改但 apaas 要求每次 edit 都传全字段 — 留空会拿现值不便。
    建议：先 list 找到要改的角色 → 把 role_code/role_name/role_id 一起传入。
    """
    if not (apaas_app_id.strip() and role_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + role_id 必填"}
    if not (role_code.strip() and role_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "role_code + role_name 必填（apaas edit 接口要求全字段）— 先 list 拿现值"}

    ok, raw = await _with_client(
        env_id, "更新角色",
        lambda c: c.update_role(
            apaas_app_id.strip(), role_id.strip(),
            role_code.strip(), role_name.strip(),
            app_name=app_name,
            enable_group_param=enable_group_param,
            role_params=role_params or [],
        ),
    )
    if not ok:
        return raw
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "role_id": role_id.strip(), "role_code": role_code, "role_name": role_name,
        "message": f"角色「{role_name}」({role_code}) 已更新",
        "next_step": "调 republish_apaas_app 让变更生效",
    }


@mcp.tool()
async def delete_apaas_app_role(env_id: int, apaas_app_id: str, role_id: str) -> dict:
    """删除单个 aPaaS 角色（不走 SPEC 直接删）。

    ⚠️ 慎用：删除前用 list_apaas_app_roles 确认 role_id 对的；删除后已绑该角色的成员
    在 apaas 平台上的访问会受影响。
    """
    if not (apaas_app_id.strip() and role_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + role_id 必填"}
    ok, raw = await _with_client(
        env_id, "删除角色",
        lambda c: c.delete_role(apaas_app_id.strip(), role_id.strip()),
    )
    if not ok:
        return raw
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "role_id": role_id.strip(),
        "message": f"角色 role_id={role_id} 已删除",
        "next_step": "调 republish_apaas_app 让变更生效",
    }


# ───── 字典 CRUD（精细操作） ─────

@mcp.tool()
async def create_apaas_app_dict(env_id: int, apaas_app_id: str, dict_code: str, dict_name: str, describe: str = "") -> dict:
    """新建一个字典到 aPaaS 应用（不走 SPEC 文档流，直接对话场景）。

    后续添加选项用 add_apaas_dict_option（先调本工具拿 dict_id）。
    """
    if not (apaas_app_id.strip() and dict_code.strip() and dict_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id + dict_code + dict_name 都必填"}
    # 2026-05-24 同 create_apaas_app_roles fix: 每项必须含 appId, 漏了 apaas silent ignore
    apaas_app_id_clean = apaas_app_id.strip()
    payload = [{
        "appId": apaas_app_id_clean,
        "dictionaryCode": dict_code.strip(),
        "dictionaryName": dict_name.strip(),
        "dictionaryDescribe": describe or "",
        "dictionaryStatus": "ENABLE",
        "dictionaryMulticolorStatus": "ENABLE",
        "internalResource": True,
    }]
    ok, raw = await _with_client(env_id, "建字典", lambda c: c.create_dicts(apaas_app_id_clean, payload))
    if not ok:
        return raw
    return {"ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "dict_code": dict_code.strip(), "dict_name": dict_name.strip(),
            "next_step": "用 list_apaas_app_dicts 拿回 dict_id 再调 add_apaas_dict_option 加选项"}


@mcp.tool()
async def update_apaas_app_dict(env_id: int, apaas_app_id: str, dict_id: str, dict_code: str, dict_name: str, describe: str = "") -> dict:
    """更新字典基本信息（不改选项，选项走 update_apaas_dict_option）。

    先 list_apaas_app_dicts 拿 dict_id；dict_code/dict_name 必填（apaas edit 接口要全字段）。
    """
    if not (apaas_app_id.strip() and dict_id.strip() and dict_code.strip() and dict_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+dict_id+dict_code+dict_name 都必填"}
    ok, raw = await _with_client(env_id, "改字典",
        lambda c: c.update_dict(apaas_app_id.strip(), dict_id.strip(), dict_code.strip(), dict_name.strip(), describe=describe))
    if not ok:
        return raw
    return {"ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "dict_id": dict_id.strip(), "message": f"字典「{dict_name}」({dict_code}) 已更新",
            "next_step": "调 republish_apaas_app 让变更生效"}


@mcp.tool()
async def add_apaas_dict_option(env_id: int, apaas_app_id: str, dict_id: str,
                                value_code: str, value_name: str, display_order: int = 0) -> dict:
    """给字典加一个选项。

    例：给"业务状态"字典加"已驳回" → add_apaas_dict_option(env_id, app_id, dict_id, "rejected", "已驳回")
    """
    if not (apaas_app_id.strip() and dict_id.strip() and value_code.strip() and value_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+dict_id+value_code+value_name 都必填"}
    ok, raw = await _with_client(env_id, "加字典选项",
        lambda c: c.add_dict_option(apaas_app_id.strip(), dict_id.strip(), value_code.strip(), value_name.strip(), display_order))
    if not ok:
        return raw
    return {"ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "dict_id": dict_id.strip(),
            "value_code": value_code.strip(), "value_name": value_name.strip(),
            "message": f"已给字典 {dict_id} 加选项「{value_name}」({value_code})"}


@mcp.tool()
async def update_apaas_dict_option(env_id: int, apaas_app_id: str, dict_id: str, option_id: str,
                                   value_code: str, value_name: str,
                                   display_order: int = 0, describe: str = "", multicolor: str = "#027AFF") -> dict:
    """更新字典选项（改 code / name / 排序 / 颜色）。先 list_apaas_app_dicts(with_options=true) 拿 option_id。"""
    if not (apaas_app_id.strip() and dict_id.strip() and option_id.strip() and value_code.strip() and value_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+dict_id+option_id+value_code+value_name 都必填"}
    ok, raw = await _with_client(env_id, "改字典选项",
        lambda c: c.update_dict_option(apaas_app_id.strip(), dict_id.strip(), option_id.strip(),
                                       value_code.strip(), value_name.strip(),
                                       display_order=display_order, describe=describe, multicolor=multicolor))
    if not ok:
        return raw
    return {"ok": True, "message": f"字典选项「{value_name}」({value_code}) 已更新"}


# ───── 模型 + 字段 CRUD（精细操作） ─────

@mcp.tool()
async def update_apaas_app_model(env_id: int, apaas_app_id: str, model_id: str,
                                 model_code: str, model_name: str,
                                 app_name: str = "", model_data_source: str = "") -> dict:
    """更新模型基本信息（改名/改 code）。不能改字段 — 字段走 add/update_apaas_model_field。

    先 list_apaas_app_models 拿 model_id。
    """
    if not (apaas_app_id.strip() and model_id.strip() and model_code.strip() and model_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "必填全填"}
    ok, raw = await _with_client(env_id, "改模型",
        lambda c: c.update_model(apaas_app_id.strip(), model_id.strip(), model_code.strip(), model_name.strip(),
                                 app_name=app_name, model_data_source=model_data_source))
    if not ok:
        return raw
    return {"ok": True, "message": f"模型「{model_name}」({model_code}) 已更新",
            "next_step": "调 republish_apaas_app 让变更生效"}


@mcp.tool()
async def add_apaas_model_field(env_id: int, apaas_app_id: str, model_id: str, model_code: str,
                                field_code: str, field_name: str,
                                field_type: str = "STRING", max_length: int = 255,
                                comment: str = "") -> dict:
    """给已有模型加一个字段。

    field_type 常用：STRING / NUM / DATE / DATETIME / BOOLEAN / TEXT / BIG_TEXT
    ⚠️ 慎用 application_id / approver_id / approval_* 等 apaas 保留字。
    """
    if not (apaas_app_id.strip() and model_id.strip() and model_code.strip() and field_code.strip() and field_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "必填全填"}
    # 简易保留字预检
    reserved = {"application_id", "approver_id", "id", "tenant_id"}
    if field_code.strip().lower() in reserved or field_code.strip().lower().startswith("approval_"):
        return {"ok": False, "error_code": "RESERVED_FIELD_CODE",
                "message": f"field_code '{field_code}' 命中 apaas 保留字 — 建议改成 {model_code}_{field_code}"}
    ok, raw = await _with_client(env_id, "加字段",
        lambda c: c.add_model_field(apaas_app_id.strip(), model_id.strip(), model_code.strip(),
                                    field_code.strip(), field_name.strip(),
                                    field_type=field_type, max_length=max_length, comment=comment))
    if not ok:
        return raw
    return {"ok": True, "message": f"模型 {model_code} 已加字段「{field_name}」({field_code} / {field_type})"}


@mcp.tool()
async def update_apaas_model_field(env_id: int, apaas_app_id: str, model_id: str, field_id: str,
                                   field_code: str, field_name: str,
                                   field_type: str = "", max_length: int = 0, comment: str = "") -> dict:
    """更新字段属性（改名 / 改类型 / 改最大长度）。

    ⚠️ 改 field_type 可能影响存量数据，建议先 disable_apaas_model_field 旧字段 + add_apaas_model_field 新字段。
    本工具不强制，由 agent 决策。

    先 list_apaas_app_models(with_fields=true) 拿 field_id。
    """
    if not (apaas_app_id.strip() and model_id.strip() and field_id.strip() and field_code.strip() and field_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "必填全填"}
    ok, raw = await _with_client(env_id, "改字段",
        lambda c: c.update_model_field(apaas_app_id.strip(), model_id.strip(), field_id.strip(),
                                       field_code.strip(), field_name.strip(),
                                       field_type=field_type or None,
                                       max_length=max_length if max_length > 0 else None,
                                       field_status="ENABLE",
                                       comment=comment or None))
    if not ok:
        return raw
    return {"ok": True, "message": f"字段「{field_name}」({field_code}) 已更新"}


@mcp.tool()
async def disable_apaas_model_field(env_id: int, apaas_app_id: str, model_id: str, field_id: str,
                                    field_code: str, field_name: str) -> dict:
    """禁用模型字段（apaas 不能真删字段，只能 status=DISABLE）。

    禁用后字段在表单/列表里不可见，但底层数据保留。重新启用调 update_apaas_model_field(field_status=ENABLE)。
    """
    if not (apaas_app_id.strip() and model_id.strip() and field_id.strip() and field_code.strip() and field_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "必填全填"}
    ok, raw = await _with_client(env_id, "禁用字段",
        lambda c: c.update_model_field(apaas_app_id.strip(), model_id.strip(), field_id.strip(),
                                       field_code.strip(), field_name.strip(),
                                       field_status="DISABLE"))
    if not ok:
        return raw
    return {"ok": True, "message": f"字段「{field_name}」({field_code}) 已禁用",
            "note": "apaas 字段不能真删只能 DISABLE。重新启用调 update_apaas_model_field(field_status='ENABLE')"}


# ───── 菜单 / 表单（精细操作） ─────

@mcp.tool()
async def create_apaas_form_menu(env_id: int, apaas_app_id: str, menu_name: str, form_id: str,
                                 menu_order: int = 0, parent_id: str = "") -> dict:
    """创建普通表单菜单（menuType=MENU/MODEL，关联到表单的 formId）。

    跟 create_apaas_self_dev_menu 区别：那个是 CUSTOM 自开发菜单（linkUrl=组件名），
    这个是普通表单菜单（formId=表单 ID）。

    parent_id 可选: 传了挂到对应 group 下; 不传放根级。
    """
    if not (apaas_app_id.strip() and menu_name.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+menu_name+form_id 都必填"}
    pid = parent_id.strip()
    # 2026-05-25: create_menu 不直接接 parent_id, 先创建再 update_menu_parent 挂载
    ok, raw = await _with_client(env_id, "建表单菜单",
        lambda c: c.create_menu(apaas_app_id.strip(), menu_name.strip(), form_id.strip(),
                                menu_order=menu_order, datasource_id="", datasource_code=""))
    if not ok:
        return raw
    new_menu = raw if isinstance(raw, dict) else {}
    new_menu_id = str(new_menu.get("id") or new_menu.get("menuId") or "")
    if pid and new_menu_id:
        ok2, raw2 = await _with_client(env_id, "挂菜单到分组",
            lambda c: c.update_menu_parent(apaas_app_id.strip(), new_menu_id, parent_id=pid,
                                            menu_order=menu_order))
        if not ok2:
            return {"ok": True, "warning": "菜单已建但挂到分组失败 — 可手动调 set_apaas_menu_parent",
                    "menu_id": new_menu_id, "parent_id_attempted": pid, "parent_error": raw2}
    return {"ok": True,
            "menu_id": new_menu_id,
            "parent_id": pid or None,
            "message": f"表单菜单「{menu_name}」已创建"
                       + (f"（挂到分组 {pid} 下）" if pid else "（根级）")}


@mcp.tool()
async def create_apaas_menu_group(
    env_id: int,
    apaas_app_id: str,
    group_name: str,
    menu_order: int = 0,
    parent_id: str = "",
) -> dict:
    """创建菜单分组 (menuType=GROUP, 用来归类菜单).

    分组本身没 form_id, 不关联表单. 创建后可用 set_apaas_menu_parent 把已有菜单
    挂到这个分组下, 或 create_apaas_form_menu(parent_id=<group_id>) 直接在
    分组下创建表单菜单。

    parent_id 可选: 嵌套分组用 (group 套 group).
    """
    if not (apaas_app_id.strip() and group_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id+group_name 都必填"}
    ok, raw = await _with_client(env_id, "建菜单分组",
        lambda c: c.create_menu_group(
            apaas_app_id.strip(), group_name.strip(),
            menu_order=menu_order, parent_id=parent_id,
        ))
    if not ok:
        return raw
    new_group = raw if isinstance(raw, dict) else {}
    return {
        "ok": True,
        "group_id": str(new_group.get("id") or new_group.get("menuId") or ""),
        "group_name": group_name,
        "message": f"菜单分组「{group_name}」已创建"
                   + (f"（嵌套在 {parent_id} 下）" if parent_id else "（根级）"),
    }


@mcp.tool()
async def set_apaas_menu_parent(
    env_id: int,
    apaas_app_id: str,
    menu_id: str,
    parent_id: str = "",
    menu_order: int = 0,
) -> dict:
    """改菜单的父分组 — 把现有菜单移到某个 group 下, 或移出回根级.

    parent_id="" → 移到根 (脱离任何 group)
    parent_id=<group_menu_id> → 挂到那个 group 下

    ⚠️ 实现是 save/menu 覆盖式更新, 会查现有 menu 完整字段后 merge 改 parentId,
    其他业务字段 (menuName/formId/linkUrl 等) 都保留不动。
    """
    if not (apaas_app_id.strip() and menu_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id+menu_id 都必填"}
    ok, raw = await _with_client(env_id, "改菜单父分组",
        lambda c: c.update_menu_parent(
            apaas_app_id.strip(), menu_id.strip(),
            parent_id=parent_id, menu_order=menu_order,
        ))
    if not ok:
        return raw
    return {
        "ok": True,
        "menu_id": menu_id,
        "parent_id": parent_id or None,
        "message": (f"菜单 {menu_id} 已挂到分组 {parent_id} 下"
                    if parent_id else f"菜单 {menu_id} 已移出分组到根级"),
    }


@mcp.tool()
async def rename_apaas_menu(
    env_id: int,
    apaas_app_id: str,
    menu_id: str,
    new_name: str,
) -> dict:
    """改菜单名 — 普通菜单 / 分组 / 自开发菜单 都用这个.

    例: 把分组"测试"改成"业务核心":
        rename_apaas_menu(env_id=49, apaas_app_id="846...",
                          menu_id="846743128927895552", new_name="业务核心")

    实现: GET 菜单完整字段 → POST /xdap-app/menu/save/menu 改 menuName → verify.
    平台 save/menu 接受 menuName 更新 (跟改 parentId 不一样, menuName 正常持久化).
    """
    if not (apaas_app_id.strip() and menu_id.strip() and new_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + menu_id + new_name 都必填"}
    ok, raw = await _with_client(env_id, "改菜单名",
        lambda c: c.rename_menu(apaas_app_id.strip(), menu_id.strip(), new_name.strip()))
    if not ok:
        return raw
    return {
        "ok": True,
        "menu_id": menu_id,
        "menu_name": new_name.strip(),
        "message": f"菜单 {menu_id} 已改名为「{new_name}」",
    }


@mcp.tool()
async def delete_apaas_app_menu(env_id: int, apaas_app_id: str, menu_id: str, menu_name: str = "") -> dict:
    """删除应用菜单（普通菜单 / 表单菜单 / 自开发菜单都用这个）。

    ⚠️ 删除表单菜单会联动删表单本身（apaas 内部行为）。删除前确认 menu_id 对的。
    """
    if not (apaas_app_id.strip() and menu_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+menu_id 都必填"}
    ok, raw = await _with_client(env_id, "删菜单",
        lambda c: c.delete_menu(apaas_app_id.strip(), menu_id.strip(), menu_name=menu_name))
    if not ok:
        return raw
    return {"ok": True, "message": f"菜单 {menu_id} 已删除（如果是表单菜单，关联表单也被删了）"}


# ═══════════════════════════════════════════════════════════════════════════
# 业务事件 (BPM Engine) — 6 个低层工具
# 详 docs/research-business-event-api.md (770 行实证 API 笔记).
#
# 典型工作流 (建一个"字段值改变 → 自动赋值"事件):
#   1. list_form_menus_for_event(env_id, apaas_app_id) — 列表单菜单, 选 triggerFormId
#   2. list_apaas_form_components(env_id, apaas_app_id, form_id) — 拿字段 uuid/boCode
#   3. create_apaas_business_event(env_id, apaas_app_id, event_name="...", event_type="EVENT_VALUE_CHANGE")
#      → 返 event_id (24hex MongoDB ObjectId)
#   4. get_apaas_business_event_detail(env_id, apaas_app_id, event_id)
#      → 拿到 stub DAG (含平台自动填的 boCodeBORelationProperties 元数据)
#   5. agent 改 trigger node (设 boCode/componentUuid/triggerType=VALUE_CHANGE)
#      + 在 eventNodeNdList 加 ASSIGNMENT_NODE
#   6. save_apaas_business_event(env_id, apaas_app_id, event_data) — 持久化整树
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_apaas_business_events(
    env_id: int,
    apaas_app_id: str,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """列指定应用的所有业务事件（字段值改变 / 表单提交触发 / 定时 / 审批节点等）。

    返回每个事件的 eventId / eventName / eventType / status / lastUpdateDate.
    给 agent 看已有事件防重复创建. 跨应用聚合用平台租户中心 UI, 本工具仅限单 app.
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
    ok, raw = await _with_client(env_id, "查业务事件",
        lambda c: c.list_business_events(apaas_app_id.strip(), keyword=keyword,
                                          page=page, page_size=page_size))
    if not ok:
        return raw
    return {"ok": True, "apaas_app_id": apaas_app_id, "data": raw}


@mcp.tool()
async def get_apaas_business_event_detail(
    env_id: int,
    apaas_app_id: str,
    event_id: str,
) -> dict:
    """查业务事件完整详情 — 含 triggerNodeNd + eventNodeNdList + endNode + 完整 boCodeBORelationProperties.

    平台 stub 创建后调这个拿到完整结构 (含元数据), agent 改完调 save_apaas_business_event 持久化.

    event_id 是 24 字符 MongoDB ObjectId (从 list 或 create 的返回里取).
    """
    if not (apaas_app_id.strip() and event_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_id 都必填"}
    ok, raw = await _with_client(env_id, "查业务事件详情",
        lambda c: c.get_business_event_detail(event_id.strip(), apaas_app_id.strip()))
    if not ok:
        return raw
    return {"ok": True, "event_id": event_id, "data": raw}


@mcp.tool()
async def create_apaas_business_event(
    env_id: int,
    apaas_app_id: str,
    event_name: str,
    event_type: str = "EVENT_OPERATION",
) -> dict:
    """创建业务事件 stub (仅 metadata, DAG 留空) — 返 event_id (24hex MongoDB ObjectId).

    event_type 真值集 (从 prod 160 事件实证):
      - EVENT_OPERATION    表单操作触发 (提交/保存/修改/删除) — 最高频
      - EVENT_BUTTON       按钮触发 (自定义按钮点击)
      - EVENT_VALUE_CHANGE 字段值改变触发 (用户截图场景)
      - EVENT_PROCESS      审批流程触发 (审批环节自动化)
      - EVENT_TIME         定时触发 (Quartz cron)
      - EVENT_EXT          外部触发 (API 暴露给外部)
      - EVENT_WORKFLOW     标准工作流

    建完调 get_apaas_business_event_detail 拿 stub 完整结构, 改完 save 持久化.
    """
    if not (apaas_app_id.strip() and event_name.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_name 都必填"}
    valid_types = {"EVENT_OPERATION", "EVENT_BUTTON", "EVENT_VALUE_CHANGE",
                   "EVENT_PROCESS", "EVENT_TIME", "EVENT_EXT", "EVENT_WORKFLOW"}
    if event_type not in valid_types:
        return {"ok": False, "error_code": "INVALID_EVENT_TYPE",
                "message": f"event_type 必须是 {valid_types} 之一, 当前={event_type}"}
    ok, raw = await _with_client(env_id, "建业务事件",
        lambda c: c.create_business_event(apaas_app_id.strip(), event_name.strip(),
                                           event_type=event_type))
    if not ok:
        return raw
    event_id = (raw.get("id") or raw.get("eventId") or "") if isinstance(raw, dict) else ""
    return {
        "ok": True,
        "event_id": event_id,
        "event_name": event_name,
        "event_type": event_type,
        "message": f"事件「{event_name}」stub 已建 (id={event_id}); "
                   f"下一步 get_apaas_business_event_detail 拿 stub 完整 DAG, 改 trigger + 加节点后 save",
    }


@mcp.tool()
async def save_apaas_business_event(
    env_id: int,
    apaas_app_id: str,
    event_data: dict,
) -> dict:
    """保存业务事件完整 DAG (覆盖式) — agent 改完 get_detail 拿的结构后调这个持久化.

    event_data 是完整顶层结构, 含:
      - id (eventId 24hex), eventName, eventType, appId, version:"v3.0", status:"ENABLE"
      - triggerNodeNd (1 个触发节点)
      - eventNodeNdList (中间节点数组, 含 ASSIGNMENT_NODE / UPDATE_NODE / CUSTOM_CODE_NODE 等)
      - endNode (1 个结束节点)
      - eventCode (32hex), objectVersionNumber (乐观锁)

    ⚠️ 覆盖式: event_data 里的字段会**整体替换**平台上的, 别漏关键字段 (尤其
    boCodeBORelationProperties — 用 get_detail 返回的原值, 不要清空).
    """
    if not (apaas_app_id.strip() and isinstance(event_data, dict)):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_data dict 都必填"}
    ok, raw = await _with_client(env_id, "存业务事件",
        lambda c: c.save_business_event(event_data, apaas_app_id.strip()))
    if not ok:
        return raw
    return {
        "ok": True,
        "event_id": event_data.get("id"),
        "event_name": event_data.get("eventName"),
        "message": f"事件「{event_data.get('eventName')}」DAG 已保存",
    }


@mcp.tool()
async def delete_apaas_business_event(
    env_id: int,
    apaas_app_id: str,
    event_id: str,
) -> dict:
    """删除业务事件 — ⚠️ 平台 endpoint 是 GET 不是 DELETE, 客户端已封装."""
    if not (apaas_app_id.strip() and event_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_id 都必填"}
    ok, raw = await _with_client(env_id, "删业务事件",
        lambda c: c.delete_business_event(event_id.strip(), apaas_app_id.strip()))
    if not ok:
        return raw
    return {"ok": True, "event_id": event_id, "message": f"事件 {event_id} 已删除"}


@mcp.tool()
async def list_apaas_form_menus_for_event(
    env_id: int,
    apaas_app_id: str,
) -> dict:
    """列应用所有"可作为事件触发源的表单菜单" — 给 agent 选 triggerFormId / triggerBocCode 用.

    每项含 menu_id / menu_name / form_id / boc_code. 跟 list_apaas_app_menus 区别:
    本接口专为业务事件配置场景, 平台用 ?eventFlag=true 过滤了不能挂事件的菜单.
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
    ok, raw = await _with_client(env_id, "查可挂事件表单菜单",
        lambda c: c.list_form_menus_for_event(apaas_app_id.strip()))
    if not ok:
        return raw
    return {"ok": True, "apaas_app_id": apaas_app_id, "form_menus": raw, "count": len(raw)}


# ─── 业务事件 补 3 个低层 ─────────────────────────────────────────────────────


@mcp.tool()
async def list_apaas_business_events_in_tenant(
    env_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
) -> dict:
    """列租户业务事件中心（跨应用聚合，只读运维视图）— POST /xdap-app/event/query/allEventList.

    返回 {table: [{eventId, eventName, appId, appName, intactFlag, eventCode, callbackUrl, creationDate}], total}.
    给 agent 跨应用看事件分布用；单 app 内事件用 list_apaas_business_events.
    """
    ok, raw = await _with_client(env_id, "查租户业务事件",
        lambda c: c.list_business_events_in_tenant(page=page, page_size=page_size, keyword=keyword))
    if not ok:
        return raw
    return {"ok": True, **raw}


@mcp.tool()
async def query_apaas_business_event_trees(
    env_id: int,
    apaas_app_id: str,
) -> dict:
    """查应用业务事件分类树 — GET /xdap-app/event/queryTrees.

    返左侧分类菜单 tree（外部触发 / 定时触发 / 表单触发 / 标准工作流 分组），
    给 agent 按 eventType 浏览事件用。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
    ok, raw = await _with_client(env_id, "查事件分类树",
        lambda c: c.query_business_event_trees(apaas_app_id.strip()))
    if not ok:
        return raw
    return {"ok": True, "apaas_app_id": apaas_app_id, "trees": raw}


@mcp.tool()
async def list_apaas_business_event_execution_history(
    env_id: int,
    apaas_app_id: str,
    event_id: str,
    page: int = 1,
    page_size: int = 10,
    status: str = "",
    before_time: str = "",
    end_time: str = "",
) -> dict:
    """查业务事件执行历史 — POST /xdap-app/event/query/exeHistory/list.

    返 {table: [{triggerTime, costTime, triggerWay, triggerUser, status, ...}], total}.
    用来 debug 事件是否真在跑 / 跑成功 / 跑失败原因.

    status (可选): ENABLE / DISABLE 过滤；
    before_time/end_time (可选): "YYYY-MM-DD HH:mm:ss" 时间区间。
    """
    if not (apaas_app_id.strip() and event_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_id 都必填"}
    ok, raw = await _with_client(env_id, "查事件执行历史",
        lambda c: c.list_business_event_execution_history(
            event_id.strip(), apaas_app_id.strip(),
            page=page, page_size=page_size,
            status=status, before_time=before_time, end_time=end_time))
    if not ok:
        return raw
    return {"ok": True, "event_id": event_id, **raw}


# ─── 业务事件 3 个高层封装（按 ai-builder MVP 3 条路线分）─────────────────────


@mcp.tool()
async def create_form_event_with_python_code(
    env_id: int,
    apaas_app_id: str,
    event_name: str,
    trigger_form_id: str,
    trigger_boc_code: str,
    python_code: str,
    trigger_type: str = "SUBMIT_DONE",
) -> dict:
    """🅰️ 路线 A: 一键创建"表单触发 + Python3 自定义节点"业务事件.

    生成 3 节点 DAG: TRIGGER_NODE → CUSTOM_CODE_NODE(PYTHON3) → END_NODE.
    业务逻辑全在 python_code 里（自定义节点的代码字段）, schema 复杂度最低.

    入参:
      - apaas_app_id: 应用 ID (snowflake)
      - event_name: 事件名
      - trigger_form_id: 触发表单 ID (24hex MongoDB ObjectId, 用 list_apaas_form_menus_for_event 拿)
      - trigger_boc_code: 触发业务对象 code (boc_code_<formId>)
      - python_code: Python3 代码, 必含 `import definesys` + `def invoke(): ...`
      - trigger_type: SUBMIT_DONE (默认成功后) / SUBMIT_BEFORE / SUBMIT_OR_SAVE_BEFORE / SUBMIT_OR_SAVE_DONE

    工作流:
      1. add/event 拿 eventId
      2. get/detail 拿 stub (含平台填的 boCodeBORelationProperties 元数据)
      3. 改 triggerNodeNd + 加 CUSTOM_CODE_NODE + endNode
      4. save/event 持久化
    """
    if not (apaas_app_id.strip() and event_name.strip() and trigger_form_id.strip() and python_code.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_name + trigger_form_id + python_code 都必填"}
    valid_trigger_types = {"SUBMIT_DONE", "SUBMIT_BEFORE", "SUBMIT_OR_SAVE_BEFORE",
                            "SUBMIT_OR_SAVE_DONE", "SAVE_BEFORE", "SAVE_DONE",
                            "SUBMIT", "SAVE", "SUBMIT_OR_SAVE"}
    if trigger_type not in valid_trigger_types:
        return {"ok": False, "error_code": "INVALID_TRIGGER_TYPE",
                "message": f"trigger_type 必须是 {valid_trigger_types} 之一, 当前={trigger_type}"}
    if "definesys" not in python_code or "invoke" not in python_code:
        return {"ok": False, "error_code": "INVALID_PYTHON_CODE",
                "message": "python_code 必须含 `import definesys` + `def invoke(): ...` (aPaaS SDK contract)"}

    # 计算 triggerWay (映射表实证: docs v2 第 7 节)
    trigger_way_map = {
        "SUBMIT_BEFORE": "FORM_OPT_BEFORE",
        "SUBMIT_OR_SAVE_BEFORE": "FORM_OPT_BEFORE",
        "SAVE_BEFORE": "FORM_OPT_BEFORE",
        "SUBMIT": "FORM_OPT_AFTER",
        "SAVE": "FORM_OPT_AFTER",
        "SUBMIT_OR_SAVE": "FORM_OPT_AFTER",
        "SUBMIT_DONE": "FORM_OPT_AFTER_DONE",
        "SAVE_DONE": "FORM_OPT_AFTER_DONE",
        "SUBMIT_OR_SAVE_DONE": "FORM_OPT_AFTER_DONE",
    }
    trigger_way = trigger_way_map.get(trigger_type, "FORM_OPT_AFTER_DONE")

    async def _do(c):
        from uuid import uuid4
        # 1. 创建 stub
        create_resp = await c.create_business_event(
            apaas_app_id.strip(), event_name.strip(), event_type="EVENT_OPERATION",
        )
        event_id = create_resp.get("id") or create_resp.get("eventId")
        if not event_id:
            raise Exception(f"创建事件 stub 失败: 没拿到 event_id, raw={create_resp}")

        # 2. 拿 stub detail (含平台填的元数据)
        data = await c.get_business_event_detail(event_id, apaas_app_id.strip())
        if not isinstance(data, dict):
            raise Exception(f"detail 不是 dict: {type(data)}")

        # 3. 构造 3 节点 DAG (节点 ID 用 UUID hex 32 字符)
        trigger_node_id = uuid4().hex
        custom_node_id = uuid4().hex
        end_node_id = uuid4().hex

        data["triggerNodeNd"] = {
            "nodeId": trigger_node_id,
            "nodeName": "表单操作触发",
            "nextNodeId": [custom_node_id],
            "nodeType": "TRIGGER_NODE",
            "triggerType": trigger_type,
            "triggerTypeName": "",
            "triggerWay": trigger_way,
            "triggerWayName": "",
            "triggerEnv": "EVENT_FRONT",
            "triggerFormId": trigger_form_id.strip(),
            "triggerBocCode": trigger_boc_code.strip(),
            "triggerFormName": "",
            "filterConditionGroupList": [],
            "fieldChangeRange": [],
            "beforeAndAfterDataFlag": False,
            "buttonName": "",
            "excelTemplateId": [],
            "triggerBuriedPoint": "DISABLE",
            "useTableData": True,
            "validateStatus": "success",
            "boCodeBORelationProperties": (data.get("triggerNodeNd") or {}).get("boCodeBORelationProperties") or {},
        }

        data["eventNodeNdList"] = [{
            "nodeId": custom_node_id,
            "nodeName": "AI 业务逻辑",
            "nodeType": "CUSTOM_CODE_NODE",
            "nextNodeId": [end_node_id],
            "validateStatus": "success",
            "nodeDesc": "",
            "extResponse": "",
            "customCode": python_code.strip(),
            "customNodeEnv": "PYTHON3",
            "relatedDataNodeId": trigger_node_id,
            "firstRules": [],
            "secondRules": [],
            "targetBocName": "",
            "tableConfigs": [],
            "filterConditionGroup": [],
            "boCodeBORelationProperties": {},
        }]

        data["endNode"] = {
            "nodeId": end_node_id,
            "nodeName": "结束节点",
            "nextNodeId": [],
            "nodeType": "END_NODE",
            "dataStatus": "COMPLETED",
        }

        # 4. 保存
        saved = await c.save_business_event(data, apaas_app_id.strip())
        return {
            "event_id": event_id,
            "intact_flag": saved.get("intactFlag") if isinstance(saved, dict) else None,
            "status": saved.get("status") if isinstance(saved, dict) else "ENABLE",
        }

    ok, raw = await _with_client(env_id, "建 Python 自定义事件", _do)
    if not ok:
        return raw
    return {
        "ok": True,
        "route": "A_PYTHON_CUSTOM_CODE",
        "event_id": raw["event_id"],
        "event_name": event_name,
        "trigger_type": trigger_type,
        "intact_flag": raw.get("intact_flag"),
        "message": f"事件「{event_name}」已建 (Python 自定义节点) — id={raw['event_id']} intactFlag={raw.get('intact_flag')}",
    }


@mcp.tool()
async def create_time_event_with_python_code(
    env_id: int,
    apaas_app_id: str,
    event_name: str,
    cron_expression: str,
    python_code: str,
    job_trigger_type: str = "REPEAT_EXECUTE",
    start_time: str = "",
    end_time: str = "2159-12-31 00:00:00",
) -> dict:
    """🅲️ 定时触发 + Python3 自定义节点 (路线 A 在 EVENT_TIME 上的应用).

    生成 3 节点 DAG: TRIGGER_NODE(EVENT_TIME, eventJobConfig.cronList=[cron_expression])
      → CUSTOM_CODE_NODE(PYTHON3) → END_NODE.

    入参:
      - cron_expression: Quartz cron 标准 7 段 (秒 分 时 日 月 周 年), 例 "0 00 20 ? * FRI"
      - python_code: 同 create_form_event_with_python_code
      - job_trigger_type: ONCE_EXECUTE (一次) / REPEAT_EXECUTE (重复, 默认)
      - start_time: "YYYY-MM-DD HH:mm:ss", 留空用当前时间
      - end_time: 同上, 默认 2159-12-31

    ⚠️ EVENT_TIME 触发节点没 triggerType / triggerWay / triggerEnv / triggerFormId.
    """
    if not (apaas_app_id.strip() and event_name.strip() and cron_expression.strip() and python_code.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + event_name + cron_expression + python_code 都必填"}
    if job_trigger_type not in ("ONCE_EXECUTE", "REPEAT_EXECUTE"):
        return {"ok": False, "error_code": "INVALID_JOB_TYPE",
                "message": "job_trigger_type 必须 ONCE_EXECUTE 或 REPEAT_EXECUTE"}
    if "definesys" not in python_code or "invoke" not in python_code:
        return {"ok": False, "error_code": "INVALID_PYTHON_CODE",
                "message": "python_code 必须含 `import definesys` + `def invoke(): ...`"}

    import datetime as _dt
    if not start_time.strip():
        start_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async def _do(c):
        from uuid import uuid4
        create_resp = await c.create_business_event(
            apaas_app_id.strip(), event_name.strip(), event_type="EVENT_TIME",
        )
        event_id = create_resp.get("id") or create_resp.get("eventId")
        if not event_id:
            raise Exception(f"创建事件 stub 失败: {create_resp}")

        data = await c.get_business_event_detail(event_id, apaas_app_id.strip())
        if not isinstance(data, dict):
            raise Exception(f"detail 不是 dict: {type(data)}")

        trigger_node_id = uuid4().hex
        custom_node_id = uuid4().hex
        end_node_id = uuid4().hex

        data["triggerNodeNd"] = {
            "nodeId": trigger_node_id,
            "nodeName": "定时触发",
            "nextNodeId": [custom_node_id],
            "nodeType": "TRIGGER_NODE",
            "triggerTypeName": "",
            "triggerBocCode": "",
            "triggerFormName": "",
            "buttonName": "",
            "beforeAndAfterDataFlag": False,
            "triggerBuriedPoint": "DISABLE",
            "boCodeBORelationProperties": {},
            "eventJobConfig": {
                "jobTriggerType": job_trigger_type,
                "cycleNumber": 1,
                "cycleType": "",
                "jobTriggerTime": "",
                "startTime": start_time,
                "endTime": end_time,
                "cronList": [cron_expression.strip()],
                "apaasTaskIds": [],
                "syncUpdateTable": False,
            },
        }

        data["eventNodeNdList"] = [{
            "nodeId": custom_node_id,
            "nodeName": "AI 业务逻辑",
            "nodeType": "CUSTOM_CODE_NODE",
            "nextNodeId": [end_node_id],
            "relatedDataNodeId": trigger_node_id,
            "validateStatus": "success",
            "nodeDesc": "",
            "extResponse": "",
            "customCode": python_code.strip(),
            "customNodeEnv": "PYTHON3",
            "firstRules": [],
            "secondRules": [],
            "targetBocName": "",
            "tableConfigs": [],
            "filterConditionGroup": [],
            "boCodeBORelationProperties": {},
        }]

        data["endNode"] = {
            "nodeId": end_node_id,
            "nodeName": "结束节点",
            "nextNodeId": [],
            "nodeType": "END_NODE",
            "dataStatus": "COMPLETED",
        }

        saved = await c.save_business_event(data, apaas_app_id.strip())
        return {
            "event_id": event_id,
            "intact_flag": saved.get("intactFlag") if isinstance(saved, dict) else None,
            "cron": cron_expression,
        }

    ok, raw = await _with_client(env_id, "建定时 Python 事件", _do)
    if not ok:
        return raw
    return {
        "ok": True,
        "route": "TIME_PYTHON",
        "event_id": raw["event_id"],
        "event_name": event_name,
        "cron_expression": raw["cron"],
        "job_trigger_type": job_trigger_type,
        "intact_flag": raw.get("intact_flag"),
        "message": f"定时事件「{event_name}」已建 — id={raw['event_id']} cron={raw['cron']}",
    }


_VALUE_CHANGE_CAPTURE_PATH = (
    "/Users/mars/Vibe Coding/apaas-builder-ai/"
    "docs/captures/business-event-save-captured-1779695560.json"
)
_VALUE_CHANGE_CAPTURE_FORM_ID = "6a1272e174cfbc26cbf1e15c"   # 借阅记录 form (capture 来源)
_VALUE_CHANGE_CACHED_TEMPLATE: dict | None = None


def _load_value_change_template() -> dict:
    """读 capture template (lazy, 缓存). 2026-05-25 用户手动建事件抓的真 schema."""
    global _VALUE_CHANGE_CACHED_TEMPLATE
    if _VALUE_CHANGE_CACHED_TEMPLATE is None:
        import json as _j
        with open(_VALUE_CHANGE_CAPTURE_PATH, encoding="utf-8") as f:
            _VALUE_CHANGE_CACHED_TEMPLATE = _j.load(f)
    return _VALUE_CHANGE_CACHED_TEMPLATE


@mcp.tool()
async def create_apaas_value_change_assignment_event(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    event_name: str,
    trigger_field_label: str,
    trigger_value: str,
    target_field_label: str,
    value_expression: str,
) -> dict:
    """🅳 一键建"字段值改变 → 自动赋值"事件 — 用户最高频的"X 改成 Y 时填 Z" 场景.

    例: 借阅状态=已归还 时, 自动填归还日期=当前时间
        create_apaas_value_change_assignment_event(
          env_id=49, apaas_app_id="846...", form_id="6a1...",
          event_name="归还时自动填归还日期",
          trigger_field_label="借阅状态",   trigger_value="已归还",
          target_field_label="归还日期",   value_expression="${dateNow}",
        )

    内部实现 (2026-05-25 v3, capture-as-template):
      1. 加载用户手抓的真实 save body 当 template (含完整 boCodeBORelationProperties 19 字段)
      2. list_apaas_form_components 拿字段 (label → uuid + bocCode + 字典选项)
      3. 解析字典 (借阅状态='已归还' → returned_)
      4. create_business_event stub → 拿 event_id
      5. 深拷 template + 替换: id/eventName/eventCode/3 nodeId + trigger 字段 + assignment 字段 + value
      6. save → 立刻 get_detail 验证持久化, 失败回滚

    value_expression 支持:
      - "${dateNow}"   当前时间 (用 capture 的 formula record verbatim)
      - 字面值如 "已审批"  (filterType=COMMON, filterDisplayValue={})
      - 其他公式 (${userName} 等) 暂不支持 — 需要先创建对应 formula record

    ⚠️ 限制: 当前 template 绑死借阅记录 form_id `6a1272e174cfbc26cbf1e15c`,
       因为 boCodeBORelationProperties 含该 form 全 19 字段元数据 (含 boId 等不可造的字段).
       其他 form 用户先在平台 UI 配一个事件 + 我抓 capture 后再加 template.
    """
    import uuid as _uuid
    import copy as _copy

    if not all([apaas_app_id.strip(), form_id.strip(), event_name.strip(),
                trigger_field_label.strip(), trigger_value.strip(),
                target_field_label.strip(), value_expression.strip()]):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "8 个参数都必填"}

    # 限制: 仅借阅记录 form 有 template
    if form_id.strip() != _VALUE_CHANGE_CAPTURE_FORM_ID:
        return {
            "ok": False,
            "error_code": "FORM_TEMPLATE_NOT_FOUND",
            "message": (
                f"目前仅借阅记录 form_id={_VALUE_CHANGE_CAPTURE_FORM_ID} 有 schema template "
                f"(2026-05-25 用户手动建事件抓的). 你给的 form_id={form_id} 还没采集 template. "
                "解决方案: 在平台 UI 给该 form 手动建一个 VALUE_CHANGE 事件后我能抓 capture 加 template."
            ),
        }

    async def _do(c):
        # 1. 拿表单字段 — label → uuid + bocCode + 字典选项
        comps = await c.query_form_components(apaas_app_id.strip(), form_id.strip())
        if not isinstance(comps, list):
            raise Exception(f"表单 {form_id} 没返字段列表")

        def _find(label):
            for cc in comps:
                if not isinstance(cc, dict):
                    continue
                if (cc.get("label") or cc.get("componentName") or "") == label:
                    return cc
            return None

        trig = _find(trigger_field_label)
        if not trig:
            raise Exception(
                f"表单里找不到名为「{trigger_field_label}」的字段; "
                f"可选: {[c.get('label') for c in comps if isinstance(c, dict)]}"
            )
        tgt = _find(target_field_label)
        if not tgt:
            raise Exception(f"表单里找不到名为「{target_field_label}」的字段")

        trig_uuid = trig.get("uuid") or ""
        trig_boc = trig.get("bocCode") or trig.get("boCode") or ""
        trig_bo_type = trig.get("businessObjectComponentType") or "BOF_TEXT"
        tgt_boc = tgt.get("bocCode") or tgt.get("boCode") or ""
        tgt_bo_type = tgt.get("businessObjectComponentType") or "BOF_DATE"

        # 2. 触发字段是字典/下拉时, 解析 trigger_value 到 dict code (如 "已归还" → "returned_")
        actual_trigger_value = trigger_value.strip()
        dict_opts = (trig.get("dictionaryChooseOptions")
                      or trig.get("dictionary_choose_options")
                      or trig.get("chooseOptions")
                      or [])
        if dict_opts and isinstance(dict_opts, list):
            for opt in dict_opts:
                if not isinstance(opt, dict):
                    continue
                lbl = str(opt.get("label") or opt.get("name") or "")
                # 平台字典选项实证字段优先级: id > value > code (id 是 dict code 真值, 如 returned_)
                val = str(opt.get("id") or opt.get("value") or opt.get("code") or "")
                if not val:
                    continue
                if lbl == trigger_value or val == trigger_value:
                    actual_trigger_value = val
                    break

        # 3. 拷 capture template 当蓝本
        body = _copy.deepcopy(_load_value_change_template())

        # 4. create stub event 拿 event_id
        stub = await c.create_business_event(
            apaas_app_id.strip(), event_name.strip(), event_type="EVENT_VALUE_CHANGE",
        )
        event_id = (stub.get("id") or stub.get("eventId") or "") if isinstance(stub, dict) else ""
        if not event_id:
            raise Exception(f"stub 创建没拿到 event_id: {stub}")

        # 5. 在 template 上做替换
        # 顶层
        body["id"] = event_id
        body["eventName"] = event_name.strip()
        body["eventCode"] = _uuid.uuid4().hex
        body["objectVersionNumber"] = 1
        # 删 audit (服务端重填)
        for k in ("createdBy", "creationDate", "lastUpdatedBy", "lastUpdateDate",
                  "owner", "tenantId", "editLockDto"):
            body.pop(k, None)

        # 3 个新 nodeId 避免冲突
        new_trig_id = _uuid.uuid4().hex
        new_assign_id = _uuid.uuid4().hex
        new_end_id = _uuid.uuid4().hex

        # triggerNodeNd 改 nodeId + 监听字段 + 触发条件
        trig_node = body["triggerNodeNd"]
        trig_node["nodeId"] = new_trig_id
        trig_node["nextNodeId"] = [new_assign_id]
        trig_node["componentUuid"] = trig_uuid
        trig_node["boCode"] = trig_boc
        # filterConditionGroupList 嵌套结构: selectorFilterConditionList[0].filterInputs[0].filterParams[0].filterValue
        try:
            cond = trig_node["filterConditionGroupList"][0]["selectorFilterConditionList"][0]
            cond["uuid"] = trig_uuid
            cond["boCode"] = trig_boc
            cond["businessObjectComponentType"] = trig_bo_type
            cond["filterInputs"][0]["filterParams"][0]["filterValue"] = actual_trigger_value
        except (KeyError, IndexError) as e:
            raise Exception(f"template filterConditionGroupList 结构异常: {e}")

        # eventNodeNdList[0] (ASSIGNMENT_NODE) 改 nodeId + target 字段 + 值
        assign_node = body["eventNodeNdList"][0]
        assign_node["nodeId"] = new_assign_id
        assign_node["nextNodeId"] = [new_end_id]
        assign_node["relatedDataNodeId"] = new_trig_id
        try:
            rule = assign_node["firstRules"][0]
            rule["uuid"] = tgt_boc
            rule["boCode"] = tgt_boc
            rule["businessObjectComponentType"] = tgt_bo_type
            fparam = rule["filterInputs"][0]["filterParams"][0]
            ve = value_expression.strip()
            if ve == "${dateNow}":
                # 公式: 保留 template 里捕获的 formula record id + filterDisplayValue verbatim
                # (filterValue 是 formula record 24hex id, filterDisplayValue 是 formula 内容缓存)
                pass  # 不改, template 里就是这个
            else:
                # 字面值: filterType=COMMON, filterDisplayValue={}, filterValue=ve
                fparam["filterType"] = "COMMON"
                fparam["filterValue"] = ve
                fparam["filterDisplayValue"] = {}
                fparam["filterBoComponentType"] = tgt_bo_type
        except (KeyError, IndexError) as e:
            raise Exception(f"template ASSIGNMENT_NODE.firstRules 结构异常: {e}")

        # endNode 只改 nodeId
        body["endNode"]["nodeId"] = new_end_id

        # 6. save + 立刻验证
        try:
            saved = await c.save_business_event(body, apaas_app_id.strip())
        except Exception as save_exc:
            try:
                await c.delete_business_event(event_id, apaas_app_id.strip())
            except Exception:
                pass
            raise Exception(f"save 失败已回滚 stub: {save_exc}")

        try:
            verify = await c.get_business_event_detail(event_id, apaas_app_id.strip())
            verify_trig = (verify or {}).get("triggerNodeNd") or {}
            verify_nodes = (verify or {}).get("eventNodeNdList") or []
            verified = (
                verify_trig.get("nodeType") == "TRIGGER_NODE"
                and verify_trig.get("triggerType") == "VALUE_CHANGE"
                and len(verify_nodes) >= 1
                and verify_nodes[0].get("nodeType") == "ASSIGNMENT_NODE"
            )
        except Exception:
            verified = False
            verify_trig = {}
            verify_nodes = []

        if not verified:
            try:
                await c.delete_business_event(event_id, apaas_app_id.strip())
            except Exception:
                pass
            raise Exception(
                "save 返 ok 但 get_detail 验证不匹配 (stub 已回滚). "
                "可能 template 结构跟当前 form/字段不兼容."
            )

        return {
            "event_id": event_id,
            "intact_flag": saved.get("intactFlag") if isinstance(saved, dict) else True,
            "actual_trigger_value": actual_trigger_value,
            "verified_trigger_type": verify_trig.get("triggerType"),
            "verified_nodes_count": len(verify_nodes),
        }

    ok, raw = await _with_client(env_id, "建字段改变赋值事件", _do)
    if not ok:
        return raw
    return {
        "ok": True,
        "route": "D_VALUE_CHANGE_ASSIGNMENT",
        "event_id": raw["event_id"],
        "event_name": event_name,
        "trigger_field": trigger_field_label,
        "trigger_value": raw["actual_trigger_value"],
        "target_field": target_field_label,
        "value_expression": value_expression,
        "intact_flag": raw.get("intact_flag"),
        "message": (f"事件「{event_name}」已创建: "
                    f"当「{trigger_field_label}」=「{raw['actual_trigger_value']}」时, "
                    f"自动设「{target_field_label}」=「{value_expression}」"),
    }


@mcp.tool()
async def delete_apaas_app_form(env_id: int, apaas_app_id: str, form_menu_id: str, form_name: str = "") -> dict:
    """删除应用表单 — 实际走"删菜单"，apaas 内部联动删表单。

    先 list_apaas_app_menus 找到 menu_id（form_id 那个菜单的 menu_id）。
    """
    if not (apaas_app_id.strip() and form_menu_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_menu_id 都必填"}
    ok, raw = await _with_client(env_id, "删表单",
        lambda c: c.delete_menu(apaas_app_id.strip(), form_menu_id.strip(), menu_name=form_name))
    if not ok:
        return raw
    return {"ok": True, "message": f"表单「{form_name}」(menu_id={form_menu_id}) 已删除",
            "next_step": "调 republish_apaas_app 让变更生效"}


# ─── 权限矩阵 CRUD ──────────────────────────────────────────────────────────
# apaas 平台只有两条权限 API：
#   读：GET /xdap-app/formConfig/query/detailPageConfigById  → 含 advanced/operation Groups
#   写：POST /common/resource/formPermission                  → 全量覆盖该 form 的权限
# 所以不存在 update_one / delete_one 单条权限，只有"列出 + 覆盖式 set"两个语义。

def _simplify_perm_object(perm_obj: dict) -> dict:
    """精简 advanced/operation Group 里 permissionObjects[0]，给 list 工具的 output。"""
    if not perm_obj:
        return {}
    return {
        "subject_type": perm_obj.get("permissionObjectType"),  # ROLE / ALL_USER / USER / DEPT
        "subject_value": perm_obj.get("permissionObjectValue"),  # role_id / "" / user_id / dept_id
        "subject_name": perm_obj.get("permissionObjectDisplayName"),
        "range_type": (perm_obj.get("permissionRange") or {}).get("rangeType"),
    }


@mcp.tool()
async def list_apaas_form_permissions(env_id: int, apaas_app_id: str, form_id: str) -> dict:
    """列出某个表单的权限矩阵（含数据权限组 + 操作权限组）。

    底层调 query_detail_page_config，返回简化后的权限视图：
      - data_permissions: 数据权限组（查看 / 编辑 / 删除），每组一个 subject
      - operation_permissions: 操作权限组（新增 / 导入 / 暂存 / 批量等），每组一个 subject

    用法：先 list_apaas_app_forms 拿 form_id，再调本工具读现状，最后调
    set_apaas_form_permissions 覆盖式写入。
    """
    if not (apaas_app_id.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}
    ok, raw = await _with_client(env_id, "查表单权限",
        lambda c: c.query_detail_page_config(apaas_app_id.strip(), form_id.strip()))
    if not ok:
        return raw

    advanced = raw.get("advancedPermissionGroups") or []
    operation = raw.get("operationPermissionGroups") or []

    data_perms = []
    for g in advanced:
        op_type = g.get("permissionOperationType") or {}
        subj = (g.get("permissionObjects") or [{}])[0]
        data_perms.append({
            "permission_name": g.get("permissionName"),
            "subject": _simplify_perm_object(subj),
            "can_view": bool(op_type.get("queryPermission")),
            "can_edit": bool(op_type.get("updatePermission")),
            "can_delete": bool(op_type.get("deletePermission")),
        })

    op_perms = []
    for g in operation:
        op_type = g.get("permissionOperationType") or {}
        subj = (g.get("permissionObjects") or [{}])[0]
        op_perms.append({
            "permission_name": g.get("permissionName"),
            "subject": _simplify_perm_object(subj),
            "can_add": bool(op_type.get("addPermission")),
            "can_import": bool(op_type.get("importPermission")),
            "can_draft": bool(op_type.get("temporaryStoragePermission")),
            "can_copy_add": bool(op_type.get("copyAddPermission")),
            "can_batch_delete": bool(op_type.get("batchDeletePermission")),
            "can_batch_reject": bool(op_type.get("batchRejectPermission")),
            "can_batch_agree": bool(op_type.get("batchAgreePermission")),
            "can_share_form": bool(op_type.get("shareFormPermission")),
        })

    return {
        "ok": True,
        "form_id": form_id,
        "data_permissions": data_perms,
        "operation_permissions": op_perms,
        "data_count": len(data_perms),
        "operation_count": len(op_perms),
        "hint": "改权限调 set_apaas_form_permissions（覆盖式写入，传完整 rules）",
    }


def _build_perm_payload_from_simple_rules(
    app_id: str,
    form_code: str,
    form_id: str,
    rules: list,
) -> dict:
    """把 LLM 友好的 rules 数组转成 formPermission API 的标准 payload。

    rules item 示例：
        {
          "subject_type": "ROLE" | "ALL_USER",
          "subject_value": "<role_id>",     # ROLE 时必填；ALL_USER 时忽略
          "subject_name": "管理员",          # 仅用于 permissionName 显示
          "actions": ["view","add","edit","delete","import","draft"],
          "range_type": "ALL"               # 可选，默认 ALL；其他：SELF/DEPT/SUB_DEPT
        }
    """
    data_groups = []
    operation_groups = []

    for rule in rules:
        # 2026-05-14 实测纠正：apaas 平台 advancedPermissionGroups 返回的角色类型是
        # "ROLE_USER"，写入用 "ROLE" 平台会接受但读回是 "ROLE_USER"，导致下次 set
        # 时白名单不匹配。统一用 "ROLE_USER"，并把 "ROLE" 当 alias 自动 normalize。
        subj_type = str(rule.get("subject_type") or "").strip().upper()
        if subj_type == "ROLE":
            subj_type = "ROLE_USER"  # alias normalize
        if subj_type not in ("ROLE_USER", "ALL_USER", "USER", "DEPT"):
            subj_type = "ROLE_USER"

        if subj_type == "ALL_USER":
            subj_value = ""  # 平台规定：ALL_USER 时 permissionObjectValue 必须空串
            subj_name = rule.get("subject_name") or "全部人员"
        else:
            subj_value = str(rule.get("subject_value") or "").strip()
            subj_name = rule.get("subject_name") or subj_value

        actions = [a.strip().lower() for a in (rule.get("actions") or []) if a]
        all_ = "all" in actions
        can_view = all_ or "view" in actions
        can_add = all_ or "add" in actions
        can_edit = all_ or "edit" in actions or "update" in actions
        can_delete = all_ or "delete" in actions
        can_import = all_ or "import" in actions
        can_draft = all_ or "draft" in actions or "temporary" in actions

        range_type = str(rule.get("range_type") or "ALL").strip().upper()

        data_groups.append({
            "permissionName": f"{subj_name}权限",
            "permissionDescribe": "",
            "permissionOperationType": {
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
            },
            "permissionObjects": [{
                "permissionObjectType": subj_type,
                "permissionObjectValue": subj_value,
                "permissionObjectDisplayName": subj_name,
                "permissionRange": {"rangeType": range_type},
            }],
        })

        if any((can_add, can_import, can_draft)):
            operation_groups.append({
                "permissionName": f"{subj_name}操作权限",
                "permissionDescribe": "",
                "permissionOperationType": {
                    "temporaryStoragePermission": can_draft,
                    "addPermission": can_add,
                    "importPermission": can_import,
                    "copyAddPermission": False,
                    "batchDeletePermission": False,
                    "batchRejectPermission": False,
                    "batchAgreePermission": False,
                    "shareFormPermission": False,
                },
                "permissionObjects": [{
                    "permissionObjectType": subj_type,
                    "permissionObjectValue": subj_value,
                    "permissionObjectDisplayName": subj_name,
                    "permissionRange": {"rangeType": range_type},
                }],
            })

    return {
        "formCode": form_code,
        "appId": app_id,
        "tenantId": "",
        "formId": form_id,
        "operationPermissionGroups": operation_groups,
        "dataPermissionGroups": data_groups,
    }


@mcp.tool()
async def set_apaas_form_permissions(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    form_code: str,
    rules: list,
) -> dict:
    """覆盖式设置某个表单的权限矩阵（一次调用替换该表单的所有权限）。

    ⚠️ 覆盖式 — apaas 平台 formPermission API 是按 form_id 全量替换的：
      - rules 里没列的 subject（角色 / ALL_USER），权限会被清空
      - 想增量改：先 list_apaas_form_permissions 读现状，合并后再 set

    rules 数组示例：
        [
          {
            "subject_type": "ROLE_USER",
            "subject_value": "<role_id>",
            "subject_name": "管理员",
            "actions": ["view","add","edit","delete","import","draft"],
            "range_type": "ALL"
          },
          {
            "subject_type": "ALL_USER",
            "actions": ["view"],
            "range_type": "SELF"
          }
        ]

    subject_type 取值（apaas 平台实测）：
      - "ROLE_USER" — 角色（"ROLE" 也接受，会 alias 成 "ROLE_USER"）
      - "ALL_USER"  — 全部人员（subject_value 留空）
      - "USER"      — 具体用户
      - "DEPT"      — 具体部门

    actions 取值：view / add / edit / delete / import / draft，或者 ["all"] 表示全开

    range_type 常见取值（透传给 apaas，不做白名单限制）：
      - "ALL"                         — 全部数据
      - "SELF"                        — 本人
      - "CURRENT_USER_DEPT"           — 本部门
      - "CURRENT_USER_DEPT_LOW_LEVEL" — 本部门及下级
      - 其他高级取值参考 apaas 平台文档

    role_id 怎么拿：先调 list_apaas_app_roles 拿 role.id 字段。
    """
    if not (apaas_app_id.strip() and form_id.strip() and form_code.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id+form_id+form_code 都必填（form_code 从 list_apaas_app_forms 拿）"}
    if not isinstance(rules, list) or not rules:
        return {"ok": False, "error_code": "INVALID_RULES",
                "message": "rules 必须是非空数组；想清空所有权限请显式传 [{subject_type:'ALL_USER',actions:[]}]"}

    payload = _build_perm_payload_from_simple_rules(
        app_id=apaas_app_id.strip(),
        form_code=form_code.strip(),
        form_id=form_id.strip(),
        rules=rules,
    )
    ok, raw = await _with_client(env_id, "设表单权限",
        lambda c: c.create_form_permissions(apaas_app_id.strip(), [payload]))
    if not ok:
        return raw
    return {
        "ok": True,
        "form_id": form_id,
        "data_groups_count": len(payload["dataPermissionGroups"]),
        "operation_groups_count": len(payload["operationPermissionGroups"]),
        "message": "表单权限已覆盖写入（apaas 平台运行时立即生效，不需要 republish）",
    }


# ─── 应用访问授权 ──────────────────────────────────────────────────────────
# 应用层"谁能看到这个应用"的开关，跟表单 / 数据权限独立：
#   ALL  — 开放给租户内全员（最常用，部署完不开就所有人看不见）
#   ROLE — 只给指定角色（object_ids = role_id 列表）
#   USER — 只给指定用户（object_ids = user_id 列表）
#   DEPT — 只给指定部门（object_ids = dept_id 列表）
# 平台没有 query 接口，只能 set；一次只能一种 type（混合得调多次）。

@mcp.tool()
async def set_apaas_app_access(
    env_id: int,
    apaas_app_id: str,
    object_type: str = "ALL",
    object_ids: list = None,
) -> dict:
    """设置应用访问授权（控制"谁能进这个应用"，覆盖式）。

    ⚠️ 应用部署完默认**不开放访问**，所有人都看不见 — 必须显式调一次本工具。

    object_type:
      - "ALL"  — 开放给租户内全部用户（推荐；object_ids 留空 / 留 []）
      - "ROLE" — 只给指定角色（object_ids = list_apaas_app_roles 拿到的 role.id 列表）
      - "USER" — 只给指定用户（object_ids = user_id 列表）
      - "DEPT" — 只给指定部门（object_ids = dept_id 列表）

    覆盖式：本调用替换该应用之前的所有访问授权。

    平台限制：一次调用只能传一种 object_type；想混合（如管理员 ROLE + 几个具体 USER）
    得分两次调用，但实际上 apaas 后调会覆盖先调 — 这种场景没法实现，建议用 ROLE。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}

    obj_type = (object_type or "ALL").strip().upper()
    if obj_type not in ("ALL", "ROLE", "USER", "DEPT"):
        return {
            "ok": False, "error_code": "INVALID_OBJECT_TYPE",
            "message": f"object_type 必须是 ALL/ROLE/USER/DEPT 之一，收到 {object_type}",
        }

    ids = [str(x).strip() for x in (object_ids or []) if str(x).strip()]
    if obj_type != "ALL" and not ids:
        return {
            "ok": False, "error_code": "MISSING_OBJECT_IDS",
            "message": f"object_type={obj_type} 时 object_ids 必填，至少传 1 个 id",
        }

    ok, raw = await _with_client(env_id, "设应用访问授权",
        lambda c: c.save_app_access(apaas_app_id.strip(), obj_type, ids))
    if not ok:
        return raw
    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "object_type": obj_type,
        "object_ids_count": len(ids),
        "message": f"应用访问授权已设为 {obj_type}"
                   + (f"（{len(ids)} 个对象）" if ids else "（全员可见）"),
    }


# ─── 表单单组件 update ─────────────────────────────────────────────────────
# 微调单个字段的 label / required / placeholder / defaultValue / 选项之类，
# 不用走 SPEC 文档流。底层走 query_form_config → 改 → save_form_config 全量回写。

# 常用 updates 字段（白名单提示给 LLM，但不强制 — apaas 组件 schema 字段还有不少）
_FORM_COMPONENT_COMMON_FIELDS = (
    "label", "required", "placeholder", "defaultValue",
    "chooseOptions", "dictionaryChooseOptions", "multicolor",
    "readonly", "hidden", "description", "tooltip",
    "minValue", "maxValue", "maxLength",
)


@mcp.tool()
async def update_apaas_form_component(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    component_label: str,
    updates: dict,
) -> dict:
    """微调表单中某个组件的属性（按 label 精确匹配，单组件 update）。

    底层：query_form_config → 找 label == component_label 的组件 → updates dict
    merge 进去 → save_form_config 全量回写。

    component_label 必须**精确匹配**组件当前的 label（区分大小写、空格敏感）；
    匹配不上会 NOT_FOUND，不模糊匹配。

    常用 updates 字段：
      - label: 改组件标题（"申请人" → "提单人"）
      - required: bool，是否必填
      - placeholder: str，占位提示
      - defaultValue: 默认值
      - readonly: bool
      - hidden: bool（隐藏字段，apaas 运行时不显示）
      - description / tooltip: 提示文案
      - chooseOptions: list，单选/多选/复选框选项
      - dictionaryChooseOptions: list，字典选项（{value, label, code}）
      - multicolor: bool，字典选项是否多色
      - maxLength / minValue / maxValue: 输入限制

    注意：
      - componentType（组件类型）一般不要改 — 改了往往导致数据迁移问题
      - modelField（绑定的模型字段 code）也别动 — 跟模型 field 强关联
      - 不需要 republish，apaas 平台实时生效
    """
    if not (apaas_app_id.strip() and form_id.strip() and component_label.strip()):
        return {
            "ok": False, "error_code": "INVALID_PARAMS",
            "message": "apaas_app_id+form_id+component_label 都必填",
        }
    if not isinstance(updates, dict) or not updates:
        return {
            "ok": False, "error_code": "INVALID_UPDATES",
            "message": "updates 必须是非空 dict",
        }

    # 软提示：updates 里如果有不常见字段，提醒 LLM
    unknown_fields = [k for k in updates.keys() if k not in _FORM_COMPONENT_COMMON_FIELDS]

    ok, raw = await _with_client(env_id, "改表单组件",
        lambda c: c.update_form_component(
            apaas_app_id.strip(), form_id.strip(), component_label.strip(), updates,
        ))
    if not ok:
        # apaas_client 找不到组件时 raise，被 _with_client 包装成 APAAS_CALL_FAILED
        # 这里把 message 改成更精确的提示
        if "未找到标签为" in str(raw.get("message", "")):
            return {
                "ok": False, "error_code": "COMPONENT_NOT_FOUND",
                "message": f"表单 {form_id} 没有 label='{component_label}' 的组件；"
                           f"先调 list_apaas_form_components 看现有 label",
                "hint": "label 必须精确匹配（区分空格 / 标点 / 大小写）",
            }
        return raw

    result = {
        "ok": True,
        "form_id": form_id,
        "component_label": component_label,
        "updated_fields": list(updates.keys()),
        "message": f"组件「{component_label}」已更新 {len(updates)} 个字段（实时生效）",
    }
    if unknown_fields:
        result["warning"] = (
            f"updates 里有 {len(unknown_fields)} 个非常见字段：{unknown_fields}；"
            f"已传给 apaas 但不保证生效，常见字段见 docstring"
        )
    return result


# ─── 字典 disable（补 CRUD 的 D）─────────────────────────────────────────
# apaas 平台没真 delete，"禁用"是终态（运行时不再可选，但历史数据保留引用）。
# 配套 incremental_executor._disable_dict / _disable_dict_option 用的 GET 接口。

@mcp.tool()
async def disable_apaas_app_dict(env_id: int, apaas_app_id: str, dict_id: str, dict_name: str = "") -> dict:
    """禁用应用字典（apaas 没真 delete，禁用是终态）。

    ⚠️ 禁用后：
      - 运行时表单上该字典作为下拉选项不再可选
      - 已存在的业务数据里引用此字典的字段保留原值不动
      - 不可逆 — apaas 没暴露"重新启用"接口（如果有需求再单独加 enable）

    dict_id 怎么拿：先调 list_apaas_app_dicts 看现有字典 + id。
    """
    if not (apaas_app_id.strip() and dict_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+dict_id 都必填"}
    ok, raw = await _with_client(env_id, "禁用字典",
        lambda c: c.disable_dict(apaas_app_id.strip(), dict_id.strip()))
    if not ok:
        return raw
    return {
        "ok": True,
        "dict_id": dict_id,
        "message": f"字典「{dict_name or dict_id}」已禁用（运行时不可选，历史数据保留）",
    }


@mcp.tool()
async def disable_apaas_dict_option(
    env_id: int,
    apaas_app_id: str,
    option_id: str,
    option_name: str = "",
) -> dict:
    """禁用字典里某个选项（apaas 没真 delete，禁用是终态）。

    用法：先调 list_apaas_app_dicts 拿字典 → 看 options 列表 → 拿到要禁用的
    option.id 传进来。

    禁用后选项不再出现在新建表单下拉里，已选过此值的历史数据保留。
    """
    if not (apaas_app_id.strip() and option_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+option_id 都必填"}
    ok, raw = await _with_client(env_id, "禁用字典选项",
        lambda c: c.disable_dict_option(apaas_app_id.strip(), option_id.strip()))
    if not ok:
        return raw
    return {
        "ok": True,
        "option_id": option_id,
        "message": f"字典选项「{option_name or option_id}」已禁用",
    }


# ─── 业务数据查询（运行时 data，外部 agent 看数据）──────────────────────
# 之前所有 apaas 工具都在搭建层（角色 / 字典 / 模型 / 表单 / 权限 / 菜单），
# 没工具能看运行时数据 — 用户在「请假申请」表单提交的具体请假记录。
# 这是 外部 agent 「我帮你查上周的请假情况」类对话的前置能力。
#
# 现阶段只暴露**只读**。写入（saveFormData）暂搁 — 风险高，得单独权限设计。

@mcp.tool()
async def query_apaas_business_data(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    tab_id: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询某表单的运行时业务数据（用户提交的数据行，分页）。

    底层调 POST /xdap-app/business/v2/query/listPageBusinessData — 跟 apaas
    平台表单"列表页"页面背后的真接口一致。

    tab_id（表单视图 id）必填：tab_id="" 时本工具会自动调 list_apaas_form_views
    拿默认 tab，省一步；想指定特定视图请显式传 tab_id。

    返回：
      - items: 数据行数组（每行 dict，key 是字段 uuid，value 是字段值）
      - total: 总行数
      - page / page_size: 当前页
      - raw_keys: apaas 平台返回的原始 dict keys（调试用）

    ⚠️ 只读，不支持写入。
    ⚠️ page_size 上限 200。
    ⚠️ 不支持 filter / sort — 想筛过滤拿到一页后客户端 in-memory 筛。
    """
    if not (apaas_app_id.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}

    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))

    # 1) tab_id 没传时自动拿默认 tab
    resolved_tab = (tab_id or "").strip()
    if not resolved_tab:
        ok_v, views_raw = await _with_client(env_id, "拿表单默认 tab",
            lambda c: c.query_form_views(apaas_app_id.strip(), form_id.strip()))
        if not ok_v:
            return {
                "ok": False, "error_code": "TAB_ID_AUTO_RESOLVE_FAILED",
                "message": f"未传 tab_id 且自动拿默认 tab 失败：{views_raw.get('message')}",
                "hint": "显式传 tab_id（先调 list_apaas_form_views 拿）",
            }
        views = views_raw if isinstance(views_raw, list) else (views_raw or {}).get("views") or []
        # 找 isDefault / 取第一个
        default_tab = next((v for v in views if v.get("isDefault") or v.get("default")), None) or (views[0] if views else None)
        if not default_tab:
            return {
                "ok": False, "error_code": "NO_DEFAULT_TAB",
                "message": f"表单 {form_id} 没有视图（tab），无法查业务数据",
            }
        resolved_tab = str(default_tab.get("id") or default_tab.get("tabId") or "").strip()
        if not resolved_tab:
            return {
                "ok": False, "error_code": "NO_DEFAULT_TAB",
                "message": "默认视图缺 id 字段",
                "hint": f"raw default_tab keys: {list(default_tab.keys()) if isinstance(default_tab, dict) else 'not dict'}",
            }

    # 2) 真查
    ok, raw = await _with_client(env_id, "查业务数据",
        lambda c: c.query_business_data(
            apaas_app_id.strip(), form_id.strip(), resolved_tab,
            page=page, page_size=page_size,
        ))
    if not ok:
        return raw

    # apaas v2 接口返回 schema：{code, message, total, table:[...]}
    # `table` 才是数据数组（不是 data / items / records，2026-05-14 实测）
    items = raw.get("table") or raw.get("data") or raw.get("records") or raw.get("items") or []
    total = raw.get("total") or raw.get("totalCount") or len(items)
    return {
        "ok": True,
        "form_id": form_id,
        "tab_id": resolved_tab,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items_count": len(items),
        "items": items,
        "raw_keys": list(raw.keys()),
    }


# ─── 流程 BPMN（写入式）─────────────────────────────────────────────────
# apaas 平台没暴露按 app 维度 list 流程的 endpoint（实测 6 个候选 path 全 404
# / 405），所以本块只做 write — 按 menu_id 维度覆盖式 set。每个 form 菜单
# 最多 1 个流程，所以"覆盖"不会误伤别的流程。
#
# 抽自 step_executor.py:2200-2300 的 BPMN 构造逻辑，保留 LLM 友好 stages 数组
# 输入 → 平台 nodes/edges/bpmn 输出。

# 最小 BPMN XML 骨架（apaas 平台自己根据 nodes/edges 重建完整 BPMN）
_BPMN_MIN_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
    'xmlns:activiti="http://activiti.org/bpmn" '
    'id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">'
    '<process id="Process_1" isExecutable="true">'
    '<startEvent id="START" name="开始"/>'
    '<endEvent id="END" name="结束"/>'
    '</process></definitions>'
)

# 节点用的固定按钮模板
_APPROVE_BUTTONS = [
    {"buttonCode": "APPROVE", "buttonName": "同意", "buttonLabel": "同意",
     "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "REJECT", "buttonName": "拒绝", "buttonLabel": "拒绝",
     "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
]
_START_BUTTONS = [
    {"buttonCode": "NORMAL_TERMINATE", "buttonName": "终止", "buttonLabel": "终止",
     "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "RESTART", "buttonName": "重新提交", "buttonLabel": "重新提交",
     "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "WITHDRAW", "buttonName": "撤回", "buttonLabel": "撤回",
     "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False,
     "withdrawalType": "NEXT_NODE", "withdrawalList": []},
]
_COMMENT_CONFIG = {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True}
_PHRASE_CONFIG = {"handleType": "INPUT_TYPE", "phrase": "", "status": False}


def _make_bpmn_node(node_id: str, title: str, ntype: str, y: float, approvers=None) -> dict:
    """构造单个 BPMN node — 同 step_executor._make_node 的逻辑。"""
    n = {
        "id": node_id, "nodeId": node_id, "timeBoudries": [],
        "width": "64.0" if ntype in ("START", "END") else "122.0",
        "height": "64.0" if ntype in ("START", "END") else "48.0",
        "x": 372.0, "y": y,
        "data": {
            "nodeId": node_id, "title": title, "type": ntype,
            "enableComponentPermission": True, "titleI18nAssociated": False,
            "approveCommentConfig": _COMMENT_CONFIG, "approvePhraseConfig": _PHRASE_CONFIG,
            "remindList": [], "processEventStatus": False, "saveFlag": True,
        },
    }
    if ntype == "START":
        n["data"]["formButtons"] = _START_BUTTONS
    elif ntype == "APPROVE":
        n["data"]["approveType"] = "SINGLE"
        n["data"]["approveButtons"] = _APPROVE_BUTTONS
        n["data"]["approvers"] = approvers or []
    return n


def _bpmn_random_id() -> str:
    """生成平台风格的 BPMN_xxx id (16 hex chars)."""
    import secrets
    return "BPMN_" + secrets.token_hex(8)


# 2026-05-25: 平台审批节点完整 data 模板 — 抓包 docs/captures/process-* 实证.
# data.title / data.approvers / data.nodeId 需要每节点 swap, 其他默认.
def _approve_node_data_template(title: str, bpmn_id: str, approvers: list) -> dict:
    """返一个 APPROVE 节点的完整 data 字段 (含 10 个默认 button + voteConfig 等)."""
    return {
        "type": "APPROVE",
        "title": title,
        "approveType": "SINGLE",
        "chooseApprovalMethod": "STAY_AT_THE_NODE",
        "voteConfig": {
            "passMode": "PASS_NUMBER",
            "passNumber": 100,
            "passRate": "100",
            "passRateCalcMode": "INCLUDE_ABSTAIN",
            "oneVoteVeto": False,
            "flowMode": "ALL",
        },
        "sequentialApprover": {
            "approverSource": "", "approverValue": "", "appointType": "",
            "approverType": "APPROVER", "personType": "", "roleId": [],
            "approvalSequenceType": "",
        },
        "approvers": approvers,
        "enableComponentPermission": True,
        "icon": "approve-icon",
        "remindList": [], "nodeRemindList": [], "approveRemindList": [],
        "approveRemindStatus": False, "nodeTriggerRemindStatus": False,
        "processEventStatus": False, "rejectRemindList": [],
        "rejectRemindStatus": False, "approveIsApplicantSkip": False,
        "approveButtons": [
            {"buttonCode": "APPROVE", "buttonName": "同意", "buttonLabel": "同意", "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
            {"buttonCode": "REJECT", "buttonName": "拒绝", "buttonLabel": "拒绝", "buttonStatus": True, "buttonLabelI18nAssociated": False},
            {"buttonCode": "INQUIRE", "buttonName": "征询", "buttonLabel": "征询", "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
            {"buttonCode": "REASSIGN", "buttonName": "转交", "buttonLabel": "转交", "buttonStyle": "primary", "buttonLabelI18nAssociated": False, "operatorScope": [], "index": 3},
            {"buttonCode": "ADDONE", "buttonName": "加签", "buttonLabel": "加签", "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
            {"buttonCode": "FRONTADDONE", "buttonName": "前加签", "buttonLabel": "前加签", "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
            {"buttonCode": "ANDCOUNTERSIGN", "buttonName": "并加签", "buttonLabel": "并加签", "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
            {"buttonCode": "OVERRULE", "buttonName": "驳回", "buttonLabel": "驳回", "buttonStyle": "primary", "buttonLabelI18nAssociated": False, "approveButtonConfigList": [], "overruleType": "any_node", "overruleReapprovalMethodAppoint": "DEFAULT", "overruleReapprovalMethod": "LEVEL_BY_LEVEL_APPROVAL", "modified": False},
            {"buttonCode": "WITHDRAW", "buttonName": "撤回", "buttonLabel": "撤回", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False, "withdrawalType": "NEXT_NODE", "withdrawalList": []},
            {"buttonCode": "ABSTAIN", "buttonName": "保留意见", "buttonLabel": "保留意见", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
        ],
        "initiatorButtons": [
            {"buttonCode": "INITIATOR_TERMINATE", "buttonName": "终止", "buttonLabel": "终止", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
        ],
        "operationButtons": [
            {"buttonCode": "INFORM", "buttonName": "知会", "buttonLabel": "知会", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
            {"buttonCode": "STAGING", "buttonName": "暂存", "buttonLabel": "暂存", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
        ],
        "overtimeHandleConfig": {"status": False, "handleType": "RECOMMEND_DEAL_TIME", "timeUnit": "H"},
        "approveSkipConfig": False,
        "approvePhraseConfig": {"handleType": "INPUT_TYPE", "phrase": "", "status": False},
        "approveCommentConfig": {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True},
        "signatureConfig": {"required": False},
        "externalSystemApproval": {"status": False, "linkUrl": "", "linkMobileUrl": ""},
        "nodeId": bpmn_id,
        "timeoutRemindList": [],
        "saveFlag": True,
        "supportBatchApprove": True,
        "supportBatchReject": True,
        "titleI18nAssociated": False,
    }


def _process_edge_template(edge_cell_id: str, source: str, target: str) -> dict:
    """返一条 edge — 平台 BPMN 渲染必填一堆视觉配置."""
    return {
        "id": edge_cell_id,
        "data": {
            "title": "\\\\", "type": "EDGE", "defaultFlow": True,
            "id": _bpmn_random_id(), "titleI18nAssociated": False,
        },
        "align": "center", "bendable": True, "editable": False, "endArrow": "classic",
        "fontColor": "rgba(0, 0, 0, 1)", "labelBackgroundColor": "#f8f9fa",
        "movable": True, "orthogonal": True, "rounded": True, "shape": "connector",
        "sourceAnchorDx": "0", "stroke": "#313133", "edge": "orth",
        "sourceAnchorX": "0.5", "sourceAnchorY": "1",
        "targetAnchorX": "0.5", "targetAnchorY": "0",
        "label": "\\\\", "x": 0, "y": 0, "width": 0, "height": 0,
        "relative": True, "translateControlPoints": True, "labelI18nAssociated": False,
        "schema": {
            "configurators": ["BpmnConfigTitle", "BpmnConfigDefaultFlow"], "hooks": {},
        },
        "visible": True, "source": source, "target": target,
    }


_MIN_BPMN_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<definitions xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
    'xmlns:omgdc="http://www.omg.org/spec/DD/20100524/DC" '
    'xmlns:omgdi="http://www.omg.org/spec/DD/20100524/DI" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" typeLanguage="http://www.w3.org/2001/XMLSchema" '
    'expressionLanguage="http://www.w3.org/1999/XPath" targetNamespace="http://www.activiti.org/processdef"/>'
)


def _build_process_payload_v2(
    app_id: str, form_id: str, menu_id: str,
    process_name: str, process_code: str,
    stages_with_role: list,  # [{name, approver_type, approver_id_or_submitter, approver_label}]
) -> dict:
    """用 capture 实证 schema 构建平台流程 payload.

    每个 stage 期望:
      - name: 节点显示标题
      - approver_type: ROLE | SUBMITTER
      - approver_value: ROLE 时是 role_id (snowflake, 用 query_roles 反查 role_code 拿到的 id); SUBMITTER 时填 "SUBMITTER"
      - approver_label: 显示名 (角色名 / "申请人")
    """
    # START / END 节点 (位置固定, 跟平台 UI 默认对齐)
    nodes = [
        {"id": "START", "x": 372, "y": 32},
        {"id": "END", "x": 372, "y": 32 + 96 * (len(stages_with_role) + 1)},
    ]
    edges = []
    prev_node_id = "START"
    cell_idx = 1  # cell-N (cell-2 / cell-3 / ...) 从 2 起避免跟 START 冲突
    edge_idx = len(stages_with_role) + 2  # edges 从 cell-N+2 起
    y_pos = 160
    for stage_idx, stage in enumerate(stages_with_role, start=1):
        cell_idx += 1
        cell_id = f"cell-{cell_idx}"
        bpmn_id = _bpmn_random_id()
        approver_type = (stage.get("approver_type") or "ROLE").upper()
        if approver_type == "SUBMITTER":
            approvers = [{
                "type": "SUBMITTER", "value": "SUBMITTER",
                "displayData": {"id": "SUBMITTER", "label": "申请人"},
            }]
        else:
            value = str(stage.get("approver_value") or "")
            label = stage.get("approver_label") or "审批人"
            approvers = [{
                "type": approver_type, "value": value,
                "displayData": {"id": value, "label": label},
            }]
        nodes.append({
            "id": cell_id, "x": 348, "y": y_pos, "height": 48, "width": 112,
            "timeBoudries": [],
            "data": _approve_node_data_template(
                title=stage.get("name") or f"审批 {stage_idx}",
                bpmn_id=bpmn_id,
                approvers=approvers,
            ),
            "nodeId": bpmn_id,
        })
        edge_idx += 1
        edges.append(_process_edge_template(
            edge_cell_id=f"cell-{edge_idx}",
            source=prev_node_id, target=cell_id,
        ))
        prev_node_id = cell_id
        y_pos += 96
    # 最后一条 edge 接 END
    edge_idx += 1
    edges.append(_process_edge_template(
        edge_cell_id=f"cell-{edge_idx}",
        source=prev_node_id, target="END",
    ))

    # 2026-05-26 修 500: 平台必须有 processDataSource.objectId = boc_code_<form_id>
    # 否则不知道流程绑哪张表 → 500. capture 实证.
    process_data_source = {
        "sourceType": "SOURCE_TYPE_BO",
        "objectId": f"boc_code_{form_id}",
    }
    # processGlobalConfig 平台 UI 默认填的流程标题模板 (capture 实证)
    process_global_config = {
        "titleConfigList": [
            {"componentId": "submitter", "name": "发起人", "type": "COMPONENT"},
            {"value": "创建的", "type": "TEXT"},
            {"componentId": "formName", "name": "表单名称", "type": "COMPONENT"},
            {"value": "流程\\n\n", "type": "TEXT"},
        ],
        "processDisplayFieldList": [],
    }
    return {
        "appId": app_id,
        "formId": form_id,
        "menuId": menu_id,
        "tenantId": "",
        "processName": process_name,
        "processCode": process_code,
        "bpmn": _MIN_BPMN_XML,
        "status": "ENABLE",
        "engine": "VERSION_1.1",
        "nodes": nodes,
        "edges": edges,
        "processRule": {},
        "globalSettings": {},
        "processGlobalConfig": process_global_config,
        "processDataSource": process_data_source,
        "openProcessVersion": False,
        "boExist": True,
        "boRemindExist": True,
        "predictionFlag": False,
    }


def _build_bpmn_payload_from_stages(menu_id: str, name: str, code: str, stages: list) -> dict:
    """把 LLM 友好的 stages 数组转成 apaas processConfig API 的 payload。

    stages: [{name, approver_type ROLE|SUBMITTER|USER, approver_code, approver_name?}]
    """
    nodes = [
        _make_bpmn_node("START", "开始", "START", 32.0),
        _make_bpmn_node("START_HIDDEN", "发起申请", "APPROVE", 128.0,
                        [{"approverType": "SUBMITTER",
                          "approverName": "表单提交人",
                          "approverCode": "SUBMITTER"}]),
    ]

    y_pos = 224.0
    for idx, stage in enumerate(stages, start=1):
        approver_type = (stage.get("approver_type") or "ROLE").strip().upper()
        approver_code = str(stage.get("approver_code") or "").strip()
        approver_name = (stage.get("approver_name") or stage.get("name")
                         or approver_code).strip()

        if approver_type == "SUBMITTER":
            approvers = [{"approverType": "SUBMITTER",
                          "approverName": "表单提交人", "approverCode": "SUBMITTER"}]
        elif approver_type in ("ROLE", "ROLE_USER"):
            approvers = [{"approverType": "ROLE",
                          "approverName": approver_name,
                          "approverCode": approver_code}]
        elif approver_type == "USER":
            approvers = [{"approverType": "USER",
                          "approverName": approver_name,
                          "approverCode": approver_code}]
        else:
            # 兜底
            approvers = [{"approverType": "ROLE",
                          "approverName": approver_name,
                          "approverCode": approver_code or "default"}]

        stage_name = stage.get("name") or f"审批 {idx}"
        nodes.append(_make_bpmn_node(f"UserTask_{idx}", stage_name, "APPROVE", y_pos, approvers))
        y_pos += 96.0

    nodes.append(_make_bpmn_node("END", "结束", "END", y_pos))

    # 顺序连边
    edges = []
    for i in range(len(nodes) - 1):
        edges.append({
            "id": f"SequenceFlow_{nodes[i+1]['id']}",
            "source": nodes[i]["id"],
            "target": nodes[i+1]["id"],
            "data": {"titleI18nAssociated": False},
        })

    return {
        "appId": "",  # client 会从 header xdapappid 拿
        "menuId": menu_id,
        "processCode": code,
        "processName": name,
        "bpmn": _BPMN_MIN_XML,
        "nodes": nodes,
        "edges": edges,
    }


@mcp.tool()
async def set_apaas_app_process(
    env_id: int,
    apaas_app_id: str,
    menu_id: str,
    process_name: str,
    process_code: str,
    stages: list,
) -> dict:
    """给某个表单菜单设置审批流程 (用 /common/resource/processConfig 管理 API).

    ⚠️ 2026-05-25 修: 老版调 /xdap-app/process/save/processConfig (BPMN XML), 实测
    返 ok=true 但 平台 UI 流程设计页空白 — 那是个不同的 process 存储, 现代 UI 不读.
    切到 super-agents-dev build-system.py 实证 work 的 /common/resource/processConfig
    简单 schema (nodes+edges+approvers, 没 BPMN).

    覆盖式: 每个表单最多 1 个流程, 重复调会覆盖.

    stages 数组每项:
      - name: 阶段名 ("部门主管审批")
      - approver_type: ROLE / SUBMITTER / USER (最常 ROLE)
      - approver_code: 审批人 code (ROLE 时是 roleCode; USER 时是 userId)
      - approver_name: 显示名 (可选, 默认用 stage.name)

    工具自动加 "开始" + "结束" 2 个固定节点, stages 串成顺序审批节点.

    示例 — 请假 2 级审批:
        stages=[
            {"name":"部门主管审批","approver_type":"ROLE","approver_code":"manager"},
            {"name":"HR 审批","approver_type":"ROLE","approver_code":"hr"}
        ]

    前置:
      - menu_id 从 list_apaas_app_menus 拿 (form_id 不空那行) — 工具会反查 form_code/form_name
      - approver_code 从 list_apaas_app_roles 拿 role.roleCode (是 code 不是 id)
    """
    if not (apaas_app_id.strip() and menu_id.strip() and
            process_name.strip() and process_code.strip()):
        return {
            "ok": False, "error_code": "INVALID_PARAMS",
            "message": "apaas_app_id+menu_id+process_name+process_code 都必填",
        }
    if not isinstance(stages, list) or not stages:
        return {
            "ok": False, "error_code": "INVALID_STAGES",
            "message": "stages 必须是非空数组(至少 1 个审批阶段)",
        }

    # 反查 form_code + form_name (管理 API 用 form_code 关联表单, 不是 menu_id)
    # ⚠️ query_menus 返的菜单只有 formId 没 formCode, 必须二级反查 form/query/formContext
    # 拿 formCode + formName.
    ok_menus, menus_raw = await _with_client(env_id, "查菜单",
        lambda c: c.query_menus(apaas_app_id.strip()))
    if not ok_menus:
        return menus_raw
    form_id = None
    # query_menus 返回平 list (含 submenus 嵌套) — 按 id 字段找
    def _find(nodes):
        for n in (nodes or []):
            if not isinstance(n, dict):
                continue
            if str(n.get("id") or "") == menu_id.strip():
                return n
            sub = _find(n.get("submenus") or n.get("children") or [])
            if sub:
                return sub
        return None
    target_menu = _find(menus_raw if isinstance(menus_raw, list) else [])
    if target_menu:
        form_id = str(target_menu.get("formId") or "").strip()
    if not form_id:
        return {
            "ok": False, "error_code": "MENU_NOT_FORM",
            "message": f"menu_id={menu_id} 不是表单菜单 (formId 空) 或菜单不存在. "
                       f"先调 list_apaas_app_menus 找 form_id 不空那行 menu_id",
        }

    # 反查角色 — 把 stages 里的 approver_code 映射到 role_id (snowflake), 平台
    # 接受的是 role_id 不是 role_code.
    ok_roles, roles_list = await _with_client(env_id, "查角色",
        lambda c: c.query_roles(apaas_app_id.strip()))
    if not ok_roles:
        return roles_list
    role_by_code = {}
    role_by_id = {}
    for r in (roles_list or []):
        if isinstance(r, dict):
            rcode = str(r.get("roleCode") or "").strip()
            rid = str(r.get("id") or "").strip()
            rname = str(r.get("roleName") or rcode).strip()
            if rcode: role_by_code[rcode] = {"id": rid, "name": rname}
            if rid: role_by_id[rid] = {"code": rcode, "name": rname}

    # 转 stages → stages_with_role (含 role_id + label)
    stages_with_role = []
    for stage_idx, stage in enumerate(stages, start=1):
        approver_type = (stage.get("approver_type") or "ROLE").strip().upper()
        if approver_type == "SUBMITTER":
            stages_with_role.append({
                "name": stage.get("name") or f"审批 {stage_idx}",
                "approver_type": "SUBMITTER",
                "approver_value": "SUBMITTER",
                "approver_label": "申请人",
            })
            continue
        # ROLE — code 或 id 都接, 缺哪个用反查表补齐
        raw_code = str(stage.get("approver_code") or "").strip()
        role_id = ""
        role_label = stage.get("approver_name") or ""
        if raw_code:
            # 1) 当作 role_code 查
            hit = role_by_code.get(raw_code)
            if hit:
                role_id = hit["id"]
                role_label = role_label or hit["name"]
            # 2) 当作 role_id 查 (AI 可能直接传 id 进来)
            elif raw_code in role_by_id:
                role_id = raw_code
                role_label = role_label or role_by_id[raw_code]["name"]
        if not role_id:
            return {
                "ok": False, "error_code": "ROLE_NOT_FOUND",
                "message": f"stage 「{stage.get('name')}」的 approver_code="
                           f"'{raw_code}' 在应用角色列表里找不到. "
                           f"先调 list_apaas_app_roles 看真实 roleCode/id",
                "available_role_codes": list(role_by_code.keys()),
            }
        stages_with_role.append({
            "name": stage.get("name") or f"审批 {stage_idx}",
            "approver_type": "ROLE",
            "approver_value": role_id,
            "approver_label": role_label or "审批人",
        })

    # 用 capture 实证 schema 构建 payload (BPMN nodes/edges + 10 button + voteConfig 等)
    payload = _build_process_payload_v2(
        app_id=apaas_app_id.strip(),
        form_id=form_id,
        menu_id=menu_id.strip(),
        process_name=process_name.strip(),
        process_code=process_code.strip(),
        stages_with_role=stages_with_role,
    )

    ok, raw = await _with_client(env_id, "存流程",
        lambda c: c.save_process_config(apaas_app_id.strip(), payload))
    if not ok:
        return raw

    return {
        "ok": True,
        "menu_id": menu_id,
        "form_id": form_id,
        "process_name": process_name,
        "process_code": process_code,
        "stages_count": len(stages),
        "nodes_count": len(payload["nodes"]),
        "platform_response": raw if isinstance(raw, dict) else {"raw": raw},
        "message": (f"流程「{process_name}」已设到表单菜单 (menu_id={menu_id}): "
                    f"START → {len(stages)} 个审批节点 → END"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2026-05-25: SPEC 驱动的"加新表单+流程"一键工具.
# 借鉴 super-agents-dev AIAssistantService.formDesign — AI 先生 SPEC 给用户审,
# 用户同意后调本工具一把建好 模型+表单+菜单+(可选)流程. 不走全量 SPEC 重新部署,
# 只增量加这一个 feature.
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_field_type(field: dict) -> tuple[str, str]:
    """从字段规格里反推 (component_type, data_model_type).

    走 app.field_types 单一真相源 — 跟 Builder 创建应用同款 SPEC 规范.
    返回值:
      - component_type: FORM_TEXT_INPUT / FORM_TEXTAREA_INPUT / FORM_NUMBER_INPUT / ...
      - data_model_type: STRING / BIG_TEXT / NUM / DATE / ... (平台 fieldType 字段)

    支持的输入形式:
      - {"type": "单行输入" | "多行输入" | "数字" | ... } — 标准中文 (FIELD_TYPES key)
      - {"type": "长文本" | "备注" | ... } — 别名 (_TYPE_ALIASES) 自动规范化
      - {"componentType": "FORM_TEXT_INPUT"} — 直给组件类型
      - {"database_field_type": "varchar" | "text" | ...} — DB 类型兜底 (_DB_TYPE_MAP)
      - 默认 单行输入 (FORM_TEXT_INPUT + STRING)
    """
    from app.field_types import (
        FIELD_TYPES, get_all_types, get_type_aliases, get_db_type_map,
    )
    all_types = get_all_types()  # FIELD_TYPES + _COMPAT_TYPES
    aliases = get_type_aliases()
    db_map = get_db_type_map()

    # 1. 显式中文 type — 最常用
    t = (field.get("type") or "").strip()
    if t:
        # 直接命中
        if t in all_types:
            info = all_types[t]
            return info.component_type, info.data_model_type
        # 别名表 → 规范化
        if t in aliases:
            std = aliases[t]
            if std in all_types:
                info = all_types[std]
                return info.component_type, info.data_model_type
        # DB 类型兜底 (varchar / int / etc)
        tl = t.lower()
        if tl in db_map:
            std = db_map[tl]
            if std in all_types:
                info = all_types[std]
                return info.component_type, info.data_model_type

    # 2. componentType 反查
    comp = (field.get("componentType") or field.get("component_type") or "").strip()
    if comp:
        for info in all_types.values():
            if info.component_type == comp:
                return comp, info.data_model_type

    # 3. database_field_type DB 类型 (varchar / longtext / int / ...)
    dbt = (field.get("database_field_type") or field.get("databaseFieldType") or "").strip().lower()
    if dbt and dbt in db_map:
        std = db_map[dbt]
        if std in all_types:
            info = all_types[std]
            return info.component_type, info.data_model_type

    # fallback 单行输入
    info = FIELD_TYPES["单行输入"]
    return info.component_type, info.data_model_type


@mcp.tool()
async def build_apaas_feature_from_spec(
    env_id: int,
    apaas_app_id: str,
    feature_name: str,
    feature_code: str,
    fields: list,
    process_stages: list | None = None,
    parent_menu_id: str = "",
) -> dict:
    """⭐ 一键建新表单+流程 (走 SPEC 驱动). 用户最高频"加新功能"场景.

    AI 先生 SPEC 给用户看 → 用户同意 → AI 调本工具 → 一次性串
    建模型 → 建表单 → 建菜单 → (可选) 配审批流程. 不走全量重新部署.

    Args:
      feature_name: 功能/表单显示名, 譬如 "借书申请"
      feature_code: 英文标识 (modelCode + formCode 用), snake_case, 譬如 "borrow_apply"
      fields: 字段数组. 每项:
        {"name": "申请人", "code": "applicant",
         "type": "单行输入" | "数字" | "日期" | "人员选择" | "多行输入" | ...
                 (或 "componentType": "FORM_TEXT_INPUT")
                 (或 "database_field_type": "BOF_TEXT"),
         "required": true | false (默认 false),
         "max_length": 200 (单行/多行用),
         "show_in_list": true | false (默认 true),
         "searchable": true | false (默认 false)}
      process_stages: 可选审批流程节点 [{"name":"管理员审批","approver_type":"ROLE","approver_code":"admin"}]
      parent_menu_id: 可选父分组 id (从 list_apaas_app_menus 拿). 不传挂根级.

    返回: {ok, model_id, form_id, menu_id, process_id?, urls{}}
    """
    if not (apaas_app_id.strip() and feature_name.strip() and feature_code.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + feature_name + feature_code 必填"}
    if not isinstance(fields, list) or not fields:
        return {"ok": False, "error_code": "INVALID_FIELDS",
                "message": "fields 必须非空数组 (至少 1 个字段)"}

    feature_code = feature_code.strip()
    feature_name = feature_name.strip()

    # ─── Step 1: 建模型 (含字段) ─────────────────────────────
    # 字段类型映射用 field_types.py 单一真相 (Builder 创建应用同款 SPEC):
    #   STRING (varchar) — 单行输入/手机/邮箱/单据号/超链接/身份证/字典选项/人员/部门
    #   BIG_TEXT (longtext) — 多行输入/富文本
    #   NUM (decimal) — 数字/金额
    #   DATE (datetime) — 日期时间
    model_fields = []
    form_components = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        fname = (f.get("name") or "").strip()
        fcode = (f.get("code") or "").strip()
        if not fname or not fcode:
            return {"ok": False, "error_code": "FIELD_MISSING_NAME_OR_CODE",
                    "message": f"字段缺 name/code: {f}"}
        comp_type, data_model_type = _normalize_field_type(f)
        max_length = int(f.get("max_length") or f.get("maxLength") or 200)
        required = bool(f.get("required", False))
        # 模型字段 — fieldType 用平台 data_model_type (STRING/BIG_TEXT/NUM/DATE)
        mf = {
            "fieldName": fname, "fieldCode": fcode,
            "fieldType": data_model_type, "required": required,
        }
        # 仅 STRING 类型加 maxLength (BIG_TEXT/NUM/DATE 无意义)
        if data_model_type == "STRING":
            mf["maxLength"] = max_length
        model_fields.append(mf)
        # 表单组件
        comp = {
            "componentType": comp_type, "label": fname,
            "modelField": f"{feature_code}.{fcode}",
            "required": required, "hidden": False, "readOnly": False,
            "showInList": bool(f.get("show_in_list", f.get("showInList", True))),
            "searchable": bool(f.get("searchable", False)),
        }
        if comp_type == "FORM_TEXT_INPUT" and max_length:
            comp["lengthLimit"] = max_length
        form_components.append(comp)

    model_payload = {
        "appId": apaas_app_id.strip(),
        "dataModels": [{
            "modelName": feature_name, "modelCode": feature_code,
            "modelDescription": f"{feature_name} 数据模型",
            "fields": model_fields,
        }],
    }
    ok_m, model_result = await _with_client(env_id, "建模型",
        lambda c: c.create_models(apaas_app_id.strip(), model_payload))
    if not ok_m:
        return {**model_result, "step": "create_models",
                "rollback_hint": "模型建失败, 后续 form/menu/process 都没建"}

    # 拿 modelCode (平台可能加 _ 后缀去重)
    actual_model_code = feature_code
    if isinstance(model_result, list) and model_result:
        first = model_result[0] if isinstance(model_result[0], dict) else {}
        actual_model_code = first.get("modelCode") or feature_code

    # ─── Step 2: 建表单 config (会自动创建关联菜单) ──────────
    # 如果平台加了 _ 后缀, 表单组件 modelField 也要更新
    if actual_model_code != feature_code:
        for comp in form_components:
            if comp.get("modelField", "").startswith(f"{feature_code}."):
                comp["modelField"] = comp["modelField"].replace(
                    f"{feature_code}.", f"{actual_model_code}.", 1)

    form_payload = [{
        "formName": feature_name,
        "formCode": f"{feature_code}_form",
        "allModelCodes": [actual_model_code],
        "formComponents": form_components,
    }]
    ok_f, form_result = await _with_client(env_id, "建表单",
        lambda c: c.create_form_config(apaas_app_id.strip(), form_payload))
    if not ok_f:
        return {**form_result, "step": "create_form_config",
                "partial_built": {"model_code": actual_model_code},
                "rollback_hint": "表单建失败, 模型已建但表单/菜单/流程没建"}

    form_id = ""
    menu_id = ""
    if isinstance(form_result, list) and form_result:
        first = form_result[0] if isinstance(form_result[0], dict) else {}
        form_id = str(first.get("id") or first.get("formId") or "")
        menu_id = str(first.get("menuId") or "")

    # ─── Step 3: (可选) 移到 parent_menu_id 分组下 ──────────
    moved_to_parent = False
    if parent_menu_id.strip() and menu_id:
        try:
            ok_mv, _ = await _with_client(env_id, "移菜单",
                lambda c: c.update_menu_parent(
                    apaas_app_id.strip(), menu_id, parent_menu_id.strip()))
            moved_to_parent = ok_mv
        except Exception:
            pass  # 移分组失败不阻断主流程

    # ─── Step 4: (可选) 配审批流程 ──────────────────────────
    process_result = None
    if process_stages and isinstance(process_stages, list) and menu_id:
        try:
            process_result = await set_apaas_app_process(
                env_id=env_id, apaas_app_id=apaas_app_id.strip(),
                menu_id=menu_id,
                process_name=f"{feature_name}审批流程",
                process_code=f"{feature_code}_process",
                stages=process_stages,
            )
        except Exception as exc:
            process_result = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "feature_name": feature_name,
        "feature_code": feature_code,
        "actual_model_code": actual_model_code,
        "model_id": (model_result[0].get("id") if isinstance(model_result, list)
                     and model_result and isinstance(model_result[0], dict) else None),
        "form_id": form_id,
        "menu_id": menu_id,
        "fields_count": len(model_fields),
        "moved_to_parent": moved_to_parent,
        "process_result": process_result,
        "message": (f"功能「{feature_name}」已建好: "
                    f"模型 {actual_model_code} ({len(model_fields)} 字段) → 表单 → "
                    f"菜单 (menu_id={menu_id})"
                    + (f" → 流程 ({len(process_stages)} 节点)"
                       if process_stages else "")),
        "next_step": "刷新平台 iframe 看新菜单, 或调 republish_apaas_app 让运行时生效",
    }


# ═══════════════════════════════════════════════════════════════════════════
# aPaaS 后端自开发模版包（papaas 4.1.1-rc）相关工具
# 源自 docs/skills/apaas-backend-dev.md + 同事踩坑总结 16 坑
#
# - init_apaas_backend_workspace  一键脚手架（防坑 5/6/7/15/16）
# - lint_apaas_backend_workspace  静态扫码找 16 坑里能静态检测的
# - （publish_dev_workspace 内嵌 lint 预检见同名 enhance）
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def init_apaas_backend_workspace(
    ws_id: str,
    project_name: str,
    apaas_tenant_id: str = "",
    apaas_app_id: str = "",
    sample_form_id: str = "",
    overwrite: bool = False,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """给 AI Coding workspace 写入 aPaaS 后端自开发模版包标准骨架（10 个文件）。

    一次性写入：pom.xml + BasePojo + BaseDao + URL 白名单 + 示例 Service /
    Controller / Entity + 启动类（test 路径下）+ application.properties + README。

    直接绕过 5 大死亡坑：
      - 坑 5/6: 启动配置缺 autoconfigure exclude
      - 坑 7: @SpringBootApplication 误放 src/main 让 aPaaS 发布卡死
      - 坑 15: INSERT 必须 POJO + doInsert (示例 Service 内已演示)
      - 坑 16: BasePojo + initInsertIdentity (避免详情页空白)

    入参：
      ws_id        AI Coding workspace ID（不能是 vibe oc_ 前缀）
      project_name 项目名（kebab-case，会用作 Java 包名 + URL 前缀 +
                   artifactId，例如 'leave-passport'）
      apaas_tenant_id / apaas_app_id / sample_form_id
                   application.properties 占位值（可空，agent 后续手填）
      overwrite    是否覆盖已存在的文件（默认 false — 已有任一目标文件就拒绝，
                   防止误覆盖 agent 手写的代码）

    返回：{ok, files_written, files_skipped, files_conflict}
    """
    if ws_id.startswith("oc_"):
        return {
            "ok": False, "error_code": "WRONG_WS_TYPE",
            "message": "init_apaas_backend_workspace 只支持 AI Coding workspace；"
                       "Vibe Coding (oc_ 前缀) 是纯全栈代码，跟 aPaaS 后端自开发模版包无关",
        }
    if not project_name.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "project_name 必填（kebab-case，如 leave-passport）"}

    import re as _re
    if not _re.match(r"^[a-z][a-z0-9\-]*[a-z0-9]$", project_name.strip()):
        return {
            "ok": False, "error_code": "INVALID_PROJECT_NAME",
            "message": (f"project_name '{project_name}' 不合法：必须全小写字母 / 数字 / -，"
                        f"首尾不能是 - 或数字开头"),
        }

    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err

    from app.apaas_backend_templates import render_all_templates
    files = render_all_templates(
        project_pkg=project_name.strip(),
        tenant_id=apaas_tenant_id.strip(),
        app_id=apaas_app_id.strip(),
        form_id=sample_form_id.strip(),
    )

    # 冲突检测
    conflicts = []
    for rel_path in files.keys():
        target = ws_path / rel_path
        if target.exists():
            conflicts.append(rel_path)
    if conflicts and not overwrite:
        return {
            "ok": False, "error_code": "FILES_CONFLICT",
            "message": (f"{len(conflicts)} 个目标文件已存在，拒绝覆盖；"
                        f"想强制覆盖请传 overwrite=true"),
            "conflicts": conflicts,
        }

    from app.coding.tools import _write_file
    written = []
    failed = []
    for rel_path, content in files.items():
        text = await _write_file({"file_path": rel_path, "content": content}, ws_path)
        if isinstance(text, str) and text.startswith("Error:"):
            failed.append({"file_path": rel_path, "error": text})
        else:
            written.append(rel_path)

    return {
        "ok": len(failed) == 0,
        "ws_id": ws_id,
        "project_name": project_name.strip(),
        "files_written": written,
        "files_failed": failed,
        "files_count": len(files),
        "overwrote_existing": len(conflicts) if overwrite else 0,
        "next_step": (
            "1. 编辑 src/main/java/.../sample/* 把示例 Service/Controller "
            "改成你的业务；2. 改 application.properties 里的 tenantId/appId/formId；"
            "3. 调 lint_apaas_backend_workspace 自查；4. publish_dev_workspace 上传"
        ),
    }


# ─── lint_apaas_backend_workspace ───────────────────────────────────────
# 静态扫描 workspace 里的 Java 代码，找 16 个坑里能 grep 出来的写法。

import re as _re_lint  # 模块级 import 避免重复 import


def _scan_java_files(ws_path) -> list:
    """收集 workspace 里所有 .java 文件路径（相对 workspace root）。"""
    out = []
    for path in ws_path.rglob("*.java"):
        # 跳 target / build / .git 目录
        rel = path.relative_to(ws_path)
        parts = rel.parts
        if any(p in ("target", "build", "node_modules", ".git") for p in parts):
            continue
        out.append((str(rel), path))
    return out


def _lint_one_java(rel_path: str, content: str) -> list[dict]:
    """对单个 Java 文件查坑。返回 [{line, severity, pit, message, hint}]。"""
    findings = []
    lines = content.split("\n")
    in_main = rel_path.startswith("src/main/")
    in_test = rel_path.startswith("src/test/")

    for i, ln in enumerate(lines, start=1):
        # 坑 7：src/main 下有 @SpringBootApplication —— 死亡坑（发布卡死）
        if in_main and "@SpringBootApplication" in ln:
            findings.append({
                "line": i, "severity": "fatal", "pit": "P7",
                "message": "@SpringBootApplication 出现在 src/main/java 下",
                "hint": "移到 src/test/java/...Application.java；否则 aPaaS 发布卡在「上线中」无报错",
            })

        # 坑 9：doQuery(Map.class) / doQuery(HashMap.class)
        if _re_lint.search(r"\.doQuery\s*\(\s*(?:Map|HashMap|LinkedHashMap|TreeMap)\.class\s*\)", ln):
            findings.append({
                "line": i, "severity": "fatal", "pit": "P9",
                "message": "doQuery 传了 Map.class / HashMap.class",
                "hint": "用无参 doQuery() / doQueryFirst() 返回 List<Map> — Java 17 JPMS 拒绝反射 java.util 内部字段",
            })

        # 坑 10：setVar(...)（不是 setOriginVar / setVariable）
        if _re_lint.search(r"\.setVar\s*\(", ln) and ".setVariable(" not in ln:
            findings.append({
                "line": i, "severity": "warn", "pit": "P10",
                "message": "用了 setVar（会自动加 va_ 前缀，导致 SQL 占位符 :xxx 匹配不上）",
                "hint": "改用 setOriginVar(name, value)，除非 SQL 占位符本身就写的 :va_xxx",
            })

        # 坑 11：WHERE parent_id / main_id / master_id —— 子表关联应该是 tab_doc_id
        if _re_lint.search(r"WHERE\s+(parent_id|main_id|master_id|f_main_id)\b", ln, _re_lint.IGNORECASE):
            findings.append({
                "line": i, "severity": "warn", "pit": "P11",
                "message": "用了 parent_id / main_id 之类做子表关联查询",
                "hint": "aPaaS 子表关联主表用 tab_doc_id（值 = 主表 document_id），不是 parent_id / main_id",
            })

        # 坑 14：INSERT INTO 用了 doUpdate()
        # 简单启发：同一行包含 "INSERT INTO" 和 "doUpdate" 或上下文里
        if _re_lint.search(r"INSERT\s+INTO", ln, _re_lint.IGNORECASE):
            # 看接下来 3 行有没有 .doUpdate()
            tail = "\n".join(lines[i-1:i+3])
            if ".doUpdate(" in tail:
                findings.append({
                    "line": i, "severity": "fatal", "pit": "P14",
                    "message": "INSERT 用了 doUpdate() — 抛 SW-180227 (update 必须带 WHERE)",
                    "hint": "INSERT 应造 POJO + doInsert(entity)，不是 .sql(INSERT) + doUpdate()",
                })
            elif ".doInsert(" in tail:
                # 坑 15: 原生 INSERT SQL + doInsert(无 POJO) 也会失败 (SW-180228)
                # 仅 .doInsert() 而非 .doInsert(entity) 时报 — 简单启发：括号内为空
                if _re_lint.search(r"\.doInsert\s*\(\s*\)", tail):
                    findings.append({
                        "line": i, "severity": "fatal", "pit": "P15",
                        "message": "原生 INSERT SQL + doInsert() 无 POJO — 抛 SW-180228",
                        "hint": "造 Entity 类继承 BasePojo 后调 doInsert(entity)",
                    })

        # 坑 13：setOriginVar(_, null) — null 直接当字面量
        if _re_lint.search(r"\.setOriginVar\s*\([^,]+,\s*null\s*\)", ln):
            findings.append({
                "line": i, "severity": "fatal", "pit": "P13",
                "message": "setOriginVar 第二参传了字面 null — 必崩",
                "hint": "改成 v == null ? \"\" : v；想入 SQL NULL 用 NULLIF 或原生 Sql2o addParameter",
            })

        # 坑 1：下拉字段用 `= 'code_xxx'` 直接比较（粗启发）
        # 这条噪音大，只 warn
        if _re_lint.search(r"=\s*'[a-z][a-z_]+_g\d+'", ln):
            findings.append({
                "line": i, "severity": "warn", "pit": "P1",
                "message": "可能拿下拉/单选字段做 = 'code' 比较 — apaas 下拉字段存的是 JSON 数组",
                "hint": "改用 JSON_UNQUOTE(JSON_EXTRACT(f,'$[0]')) = 'code' 或 LIKE '%code%'",
            })

    # 整文件级检测：坑 16 — Entity 类没继承 BasePojo
    # 例外：BasePojo.java 自己就是 extends MpaasBasePojo（项目里的封装基类），不是真问题
    if in_main and _re_lint.search(r"class\s+\w+\s+extends\s+MpaasBasePojo\b", content):
        for i, ln in enumerate(lines, start=1):
            m = _re_lint.search(r"class\s+(\w+)\s+extends\s+MpaasBasePojo\b", ln)
            if m:
                class_name = m.group(1)
                if class_name == "BasePojo":
                    break  # 项目 BasePojo 封装基类，预期就这么继承
                findings.append({
                    "line": i, "severity": "warn", "pit": "P16",
                    "message": f"{class_name} 直接继承 MpaasBasePojo — 缺 documentId/status/tenantId/formId 字段",
                    "hint": "改继承 BasePojo（项目内的封装基类）；INSERT 前调 initInsertIdentity()，否则 aPaaS 详情页空白",
                })
                break

    return findings


@mcp.tool()
async def lint_apaas_backend_workspace(
    ws_id: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """静态扫描 workspace 里的 Java 代码，找 16 坑里能 grep 出来的写法。

    检测能力（覆盖 16 坑里的 P1/P7/P9/P10/P11/P13/P14/P15/P16）：
      P7  @SpringBootApplication 在 src/main → 发布卡死（fatal）
      P9  doQuery(Map.class)              → JPMS 反射拒绝（fatal）
      P10 setVar(...)                     → va_ 前缀坑（warn）
      P11 WHERE parent_id / main_id        → 子表应用 tab_doc_id（warn）
      P13 setOriginVar(_, null)           → 必崩（fatal）
      P14 INSERT INTO + doUpdate()         → SW-180227（fatal）
      P15 INSERT SQL + doInsert() 无 POJO  → SW-180228（fatal）
      P16 extends MpaasBasePojo            → 应继承 BasePojo（warn）
      P1  field = 'xxx_gN'                 → 下拉字段是 JSON 数组（warn）

    不能静态检测的（需要 publish 后跑或者 review）：
      P2/3 数据字典 / 用户 ID 翻译、P5/6 application.yml 配置、P8 历史脏数据、
      P12 业务字段列名运行时检测

    返回：{ok, files_scanned, findings_count, fatal_count, findings:[...]}
    """
    if ws_id.startswith("oc_"):
        return {"ok": False, "error_code": "WRONG_WS_TYPE",
                "message": "lint_apaas_backend_workspace 只用于 AI Coding workspace；"
                           "Vibe Coding workspace 走 vibe_run_command 自己跑 lint"}

    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err

    java_files = _scan_java_files(ws_path)
    if not java_files:
        return {
            "ok": True, "ws_id": ws_id, "files_scanned": 0,
            "findings_count": 0, "fatal_count": 0, "findings": [],
            "hint": "workspace 里没找到 .java 文件 — 调 init_apaas_backend_workspace 先建骨架",
        }

    all_findings = []
    for rel, abs_path in java_files:
        try:
            content = abs_path.read_text(encoding="utf-8")
        except Exception as e:
            all_findings.append({
                "file": rel, "line": 0, "severity": "warn", "pit": "lint",
                "message": f"读文件失败: {e}",
            })
            continue
        for f in _lint_one_java(rel, content):
            f["file"] = rel
            all_findings.append(f)

    fatal = [f for f in all_findings if f.get("severity") == "fatal"]
    return {
        "ok": True,  # ok 表示 lint 跑完了，不是"没有问题"
        "ws_id": ws_id,
        "files_scanned": len(java_files),
        "findings_count": len(all_findings),
        "fatal_count": len(fatal),
        "findings": all_findings[:200],  # 防 LLM payload 爆
        "passed": len(fatal) == 0,
        "next_step": (
            "全部通过 — 可以 publish_dev_workspace"
            if len(fatal) == 0
            else f"有 {len(fatal)} 个 fatal 问题必须修；其他 warn 看情况"
        ),
    }


# ─── doctor_apaas_backend_workspace ───────────────────────────────────────
# 打包前置体检 — 不实际跑 mvn，只做静态环境/配置检查，3 秒内出结果。
# 治"我同事打包不成功" — 各种原因（mvn 没装 / settings.xml 没配 / pom 缺
# repositories / 用了旧 papaas 版本 / JDK 不对）一次性查清。

import os as _os_doctor
import shutil as _shutil_doctor
import subprocess as _sp_doctor
from pathlib import Path as _Path_doctor


def _doctor_check_mvn() -> dict:
    """检查 mvn 是否在 PATH + 拿版本。"""
    mvn = _shutil_doctor.which("mvn")
    if not mvn:
        return {
            "ok": False, "severity": "fatal", "check": "mvn",
            "message": "mvn 不在 PATH",
            "hint": "装 Maven 或者把 mvn 加到 PATH。Mac 用 brew install maven。",
        }
    try:
        result = _sp_doctor.run([mvn, "-v"], capture_output=True, text=True, timeout=10)
        ver_line = (result.stdout or result.stderr).split("\n")[0]
        return {
            "ok": True, "severity": "info", "check": "mvn",
            "message": f"mvn 可用：{ver_line.strip()}",
            "mvn_path": mvn,
        }
    except Exception as e:
        return {
            "ok": False, "severity": "warn", "check": "mvn",
            "message": f"mvn 找到但执行失败：{e}",
        }


def _doctor_check_java() -> dict:
    """检查 java -version 拿 JDK 主版本。aPaaS 模版包推荐 Java 8。"""
    java = _shutil_doctor.which("java")
    if not java:
        return {
            "ok": False, "severity": "fatal", "check": "java",
            "message": "java 不在 PATH",
            "hint": "装 JDK 8 (推荐) — Mac: brew install openjdk@8",
        }
    try:
        result = _sp_doctor.run([java, "-version"], capture_output=True, text=True, timeout=10)
        ver_str = result.stderr or result.stdout
        # 解析 "openjdk version \"1.8.0_xxx\"" 或 "openjdk version \"17.0.x\""
        import re as _re_d
        m = _re_d.search(r'version\s+"([\d._]+)"', ver_str)
        if not m:
            return {
                "ok": False, "severity": "warn", "check": "java",
                "message": f"无法解析 java 版本：{ver_str[:200]}",
            }
        v = m.group(1)
        major = v.split(".")[0]
        if major == "1":
            major = v.split(".")[1]  # 1.8.0 → 8
        major_int = int(major)
        if major_int == 8:
            return {"ok": True, "severity": "info", "check": "java",
                    "message": f"Java 8 ✓ ({v})"}
        if major_int <= 17:
            return {
                "ok": True, "severity": "warn", "check": "java",
                "message": f"Java {major_int} ({v}) — 模版包推荐 Java 8，{major_int} 可能跑通但有兼容风险",
                "hint": "建议 JAVA_HOME 切到 JDK 8 跑 mvn package",
            }
        return {
            "ok": False, "severity": "fatal", "check": "java",
            "message": f"Java {major_int} ({v}) — 不支持，aPaaS 模版包要求 Java 8",
            "hint": "JAVA_HOME 切 JDK 8 (brew install openjdk@8)",
        }
    except Exception as e:
        return {
            "ok": False, "severity": "warn", "check": "java",
            "message": f"java 找到但执行失败：{e}",
        }


def _doctor_check_settings_xml() -> dict:
    """检查 ~/.m2/settings.xml 是否配 dcloud-public 认证。"""
    settings = _Path_doctor.home() / ".m2" / "settings.xml"
    if not settings.exists():
        return {
            "ok": False, "severity": "fatal", "check": "settings.xml",
            "message": "~/.m2/settings.xml 不存在",
            "hint": (
                "建文件加上 dcloud-public server 认证 + mirror。模版见 "
                "docs/skills/apaas-backend-dev.md 或 aPaaS-后端自开发模版包打包规范.md 第五节"
            ),
        }
    try:
        content = settings.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "ok": False, "severity": "warn", "check": "settings.xml",
            "message": f"~/.m2/settings.xml 存在但读不了：{e}",
        }

    has_server = "dcloud-public" in content
    has_mirror = "registry.dfy.definesys.cn" in content
    if not has_server:
        return {
            "ok": False, "severity": "fatal", "check": "settings.xml",
            "message": "~/.m2/settings.xml 里没找到 dcloud-public server 配置",
            "hint": (
                "<servers><server><id>dcloud-public</id>"
                "<username>dcloud-public</username><password>dcloud-public</password>"
                "</server></servers>"
            ),
        }
    if not has_mirror:
        return {
            "ok": True, "severity": "warn", "check": "settings.xml",
            "message": "有 dcloud-public server，但没找到 mirrorOf 配置（可能依赖 pom 里的 <repositories>）",
            "hint": (
                "推荐加 <mirror><id>dcloud-public</id><mirrorOf>*,!central</mirrorOf>"
                "<url>https://registry.dfy.definesys.cn/repository/maven-public/</url></mirror>"
            ),
        }
    return {
        "ok": True, "severity": "info", "check": "settings.xml",
        "message": "~/.m2/settings.xml 配 dcloud-public server + mirror ✓",
    }


def _doctor_check_pom(ws_path) -> dict:
    """检查 pom.xml 关键字段：repositories / lib profile / papaas.version / motor-spring-boot-starter。"""
    pom = ws_path / "pom.xml"
    if not pom.exists():
        return {
            "ok": False, "severity": "fatal", "check": "pom.xml",
            "message": "workspace 下没有 pom.xml",
            "hint": "调 init_apaas_backend_workspace 生成标准 pom",
        }
    try:
        content = pom.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "ok": False, "severity": "fatal", "check": "pom.xml",
            "message": f"pom.xml 读不了：{e}",
        }

    issues = []
    if "registry.dfy.definesys.cn" not in content:
        issues.append({
            "severity": "warn", "field": "<repositories>",
            "message": "pom 没配 <repositories> 指向 dcloud-public Nexus；"
                       "如果 settings.xml 里有 mirror 也能拿到，否则会失败",
        })
    if "<id>lib</id>" not in content:
        issues.append({
            "severity": "fatal", "field": "lib profile",
            "message": "pom 缺 lib profile — `mvn -P lib` 必报 The requested profile "
                       "\"lib\" could not be activated",
            "hint": "调 init_apaas_backend_workspace 重写 pom",
        })
    if "<papaas.version>" not in content:
        issues.append({
            "severity": "warn", "field": "papaas.version",
            "message": "pom 没定义 <papaas.version> property",
        })
    elif "4.1.1-rc" not in content and "<papaas.version>" in content:
        # 提示版本可能旧
        issues.append({
            "severity": "warn", "field": "papaas.version",
            "message": "papaas 版本不是 4.1.1-rc — 旧版本 (3.2.x) 上传后 404",
            "hint": "改 <papaas.version>4.1.1-rc</papaas.version>",
        })
    if "motor-spring-boot-starter" not in content:
        issues.append({
            "severity": "fatal", "field": "motor-spring-boot-starter",
            "message": "pom 缺 motor-spring-boot-starter — 4.1.1-rc 模版包必备",
        })

    if not issues:
        return {
            "ok": True, "severity": "info", "check": "pom.xml",
            "message": "pom.xml 关键字段齐全 ✓ (repositories / lib profile / papaas 4.1.1-rc / motor)",
        }

    fatal_issues = [i for i in issues if i["severity"] == "fatal"]
    return {
        "ok": len(fatal_issues) == 0,
        "severity": "fatal" if fatal_issues else "warn",
        "check": "pom.xml",
        "message": f"pom.xml {len(issues)} 个问题（{len(fatal_issues)} fatal）",
        "issues": issues,
    }


def _doctor_check_app_class_location(ws_path) -> dict:
    """检查 @SpringBootApplication 是否误放 src/main（坑 7 死亡坑）。"""
    main_dir = ws_path / "src" / "main" / "java"
    if not main_dir.exists():
        return {
            "ok": True, "severity": "info", "check": "app_class_location",
            "message": "src/main/java 不存在 — 跳过此检查",
        }
    offenders = []
    for path in main_dir.rglob("*.java"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "@SpringBootApplication" in text:
            offenders.append(str(path.relative_to(ws_path)))
    if offenders:
        return {
            "ok": False, "severity": "fatal", "check": "app_class_location",
            "message": f"src/main/java 下有 {len(offenders)} 个 @SpringBootApplication（坑 7）",
            "offenders": offenders,
            "hint": "移到 src/test/java，否则 aPaaS 发布卡死「上线中」无报错",
        }
    return {
        "ok": True, "severity": "info", "check": "app_class_location",
        "message": "启动类位置 ✓ (src/main 下无 @SpringBootApplication)",
    }


@mcp.tool()
async def doctor_apaas_backend_workspace(
    ws_id: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """打包前置体检 — 不实际跑 mvn，3 秒内出结果。

    治"我同事打包不成功"系列问题。一次性检查 5 项：
      1. mvn 在不在 PATH（mvn）
      2. java 版本是否兼容（推荐 Java 8）
      3. ~/.m2/settings.xml 是否配 dcloud-public Nexus 认证
      4. pom.xml 关键字段（repositories / lib profile / papaas 4.1.1-rc / motor）
      5. @SpringBootApplication 没误放 src/main（防坑 7 发布卡死）

    返回 {ok, fatal_count, warn_count, checks: [...]}
    - ok=true 才能安全打包；fatal_count>0 必修
    - 每条 check 含 hint，告诉怎么修
    """
    if ws_id.startswith("oc_"):
        return {"ok": False, "error_code": "WRONG_WS_TYPE",
                "message": "doctor_apaas_backend_workspace 只用于 AI Coding workspace"}

    tid, uid = _resolve_identity(tenant_id, user_id)
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err

    checks = [
        _doctor_check_mvn(),
        _doctor_check_java(),
        _doctor_check_settings_xml(),
        _doctor_check_pom(ws_path),
        _doctor_check_app_class_location(ws_path),
    ]

    fatal = [c for c in checks if c.get("severity") == "fatal"]
    warn = [c for c in checks if c.get("severity") == "warn"]

    return {
        "ok": len(fatal) == 0,
        "ws_id": ws_id,
        "fatal_count": len(fatal),
        "warn_count": len(warn),
        "info_count": sum(1 for c in checks if c.get("severity") == "info"),
        "checks": checks,
        "next_step": (
            "✓ 全 fatal 检查通过，可以 publish_dev_workspace"
            if len(fatal) == 0
            else f"先修 {len(fatal)} 个 fatal 问题（看每个 check 的 hint）"
        ),
    }



# ─────────────────────────── Browser control (chrome-devtools-mcp) ───────────────────────────
# 2026-05-19 image #41 — 配置助手浏览器控制 POC。给 AI 装上 take_snapshot/click/
# type/screenshot 4 个工具，让它能在 apaas designer 上做 MCP API 够不到的操作
# （加表单组件 / 拖拽 / 改流程拓扑 etc）。
#
# 用户必须先开 Chrome remote debug:
#   mac: open -a "Google Chrome" --args --remote-debugging-port=9222
#   win: chrome.exe --remote-debugging-port=9222
#
# 详细架构 + 风险：docs/rfc-2026-05-19-browser-control-poc.md


async def _browser_tool_via_ext_or_cdm(cmd: str, args: dict) -> dict | None:
    """优先用 chrome extension（操作用户真主 Chrome），未连接返 None 让调用方走 chrome-devtools-mcp fallback。"""
    from app.routes.browser_ext_ws import ext_router
    if not ext_router.is_connected:
        return None
    return await ext_router.call(cmd, args, timeout=30.0)


async def _browser_tool_via_ext_or_cdm_with_timeout(
    cmd: str, args: dict, timeout: float = 30.0,
) -> dict | None:
    """同 _browser_tool_via_ext_or_cdm, 但允许自定 RPC timeout (wait_for_text 用)。"""
    from app.routes.browser_ext_ws import ext_router
    if not ext_router.is_connected:
        return None
    return await ext_router.call(cmd, args, timeout=timeout)


# 2026-05-25: frame 分类规则跟 chrome-extension/background.js classifyFrame 对齐。
# 拿到 ext 给的 frames[] 后, backend 再独立兜一次, 避免老 extension 没填 role 时
# 完全没分类 (回退兼容).
_PLATFORM_FRAME_HINT = ("/platform/", "/api/platform-proxy/entry")


def _classify_frame_url(url: str, is_top: bool) -> str:
    u = url or ""
    if any(h in u for h in _PLATFORM_FRAME_HINT):
        return "platform"
    return "host" if is_top else "other"


def _normalize_ext_snapshot(ext_result: dict | None) -> dict:
    """把 extension 返的 snapshot 规整成统一的 frames[] schema.

    新版 extension (>=0.2.0): {ok, tab_id, tab_url, tab_title, frame_count, frames:[{frame_id,url,role,tree,...}]}
    老版 extension (0.1.0):   {url, title, root}  ← 没 frames 数组, 单 top frame
    """
    if not isinstance(ext_result, dict):
        return {"ok": False, "error_code": "EXT_BAD_SHAPE", "message": "extension snapshot 返回非 dict"}

    frames = ext_result.get("frames")
    if isinstance(frames, list):
        # 新版协议 — 规整 role 兜底
        norm_frames = []
        for f in frames:
            if not isinstance(f, dict):
                continue
            fid = f.get("frame_id") if isinstance(f.get("frame_id"), int) else 0
            role = f.get("role") or _classify_frame_url(f.get("url", ""), fid == 0)
            norm_frames.append({
                "frame_id": fid,
                "parent_frame_id": f.get("parent_frame_id", -1),
                "url": f.get("url", ""),
                "title": f.get("title", ""),
                "role": role,
                "tree": f.get("tree"),
                **({"error": f["error"]} if f.get("error") else {}),
            })
        return {
            "ok": True,
            "source": "extension",
            "tab_id": ext_result.get("tab_id"),
            "tab_url": ext_result.get("tab_url"),
            "tab_title": ext_result.get("tab_title"),
            "frame_count": len(norm_frames),
            "frames": norm_frames,
        }

    # 老协议: 单 frame, 包成新 schema 保持向后兼容
    url = ext_result.get("url", "")
    return {
        "ok": True,
        "source": "extension",
        "frame_count": 1,
        "frames": [{
            "frame_id": 0,
            "parent_frame_id": -1,
            "url": url,
            "title": ext_result.get("title", ""),
            "role": _classify_frame_url(url, True),
            "tree": ext_result.get("root"),
        }],
        "legacy_extension": True,
    }


@mcp.tool()
async def browser_snapshot(tenant_id: int = 0, user_id: int = 0) -> dict:
    """拿当前浏览器活动 tab 的 accessibility tree 快照, 按 frame 聚合返回。

    返回 schema (2026-05-25 升级):
      {ok, source, tab_id, tab_url, tab_title, frame_count,
       frames: [
         {frame_id, parent_frame_id, url, title, role, tree}
       ]}

    role 取值:
      - "host":     ChatPage 自身 (顶层 frame, 一般是 localhost:5173/ai-builder/...)
      - "platform": 平台 iframe (URL 含 /platform/ 或 /api/platform-proxy/entry)
      - "other":    其他第三方 iframe

    操作 apaas 应用 UI 时 **必须** 选 role="platform" 的 frame_id, 把它传给后续
    browser_click / browser_type / browser_wait_for_text / browser_press_key。

    优先走 Chrome extension (apaas-builder-helper) → 操作用户真主 Chrome 所有 tab,
    枚举全部 frame (webNavigation.getAllFrames) 后逐帧拿 a11y tree。
    extension 没装时降级到 chrome-devtools-mcp (单 page 视图, frame_count=1)。
    """
    via_ext = await _browser_tool_via_ext_or_cdm("snapshot", {})
    if via_ext is not None:
        if via_ext.get("ok"):
            return _normalize_ext_snapshot(via_ext.get("result"))
        return via_ext

    # fallback chrome-devtools-mcp — 只能拿 active page 的扁平 snapshot, 没 frame 路由
    from app.browser_mcp_bridge import browser_bridge
    raw = await browser_bridge.call_tool("take_snapshot", {})
    try:
        import json as _j
        parsed = _j.loads(raw)
        if isinstance(parsed, dict):
            url = parsed.get("url", "")
            return {
                "ok": True,
                "source": "cdm",
                "frame_count": 1,
                "frames": [{
                    "frame_id": 0,
                    "parent_frame_id": -1,
                    "url": url,
                    "title": parsed.get("title", ""),
                    "role": _classify_frame_url(url, True),
                    "tree": parsed.get("root") or parsed.get("tree"),
                }],
                "raw_cdm": parsed,
            }
    except Exception:
        pass
    return {
        "ok": True,
        "source": "cdm",
        "frame_count": 1,
        "frames": [{
            "frame_id": 0,
            "parent_frame_id": -1,
            "url": "",
            "role": "host",
            "tree": None,
        }],
        "raw_cdm_text": raw[:8000] if isinstance(raw, str) else "",
    }


def _merge_self_heal_fields(res: dict, fallback_frame_id: int) -> dict:
    """从 extension result 抽自愈字段, response 里附 frame_id_used + self_healed 让 agent 知道
    它传的 frame_id 是不是被 extension 现场重新解析过(iframe 重建场景)。"""
    used = res.get("frame_id_used") if isinstance(res, dict) else None
    return {
        "frame_id": int(used) if isinstance(used, int) else int(fallback_frame_id),
        **({"frame_id_was_stale": res["frame_id_was_stale"]} if isinstance(res, dict) and res.get("frame_id_was_stale") is not None else {}),
        **({"self_healed": True} if isinstance(res, dict) and res.get("self_healed") else {}),
        **({"retried_after_load": True} if isinstance(res, dict) and res.get("retried_after_load") else {}),
    }


@mcp.tool()
async def browser_click(
    uid: str,
    frame_id: int = 0,
    frame_role: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """点击 a11y tree 里的某个元素（uid 由 browser_snapshot 返回）。

    寻址 (二选一, 推荐 frame_role 更鲁棒):
      - **frame_role**="platform" — extension 现场枚举找当前匹配 role 的 frame, 抗 iframe
        重建 (Vue :key 刷新场景). 用户的 ChatPage 里 platform iframe 会被 Vue 重建,
        老 frame_id 会过期; 用 role 寻址永远命中当前的 platform iframe.
      - frame_id  显式 frame id, 从 browser_snapshot 返的 frames[] 里取. 适合一次 snapshot
        立刻跟一次 click 的短链路; 中间有 1+ 秒间隔强烈建议改用 frame_role.

    自愈: 老 frame_id 失效时 extension 自动按 role 重新找 platform frame retry,
    response 里 self_healed=true + frame_id_was_stale=<旧 id> + frame_id=<新 id>。
    优先 chrome extension, fallback CDM (没 frame 路由)。
    """
    if not uid.strip():
        return {"ok": False, "error_code": "INVALID_UID", "message": "uid 不能为空"}
    args = {"uid": uid.strip(), "frame_id": int(frame_id)}
    if frame_role.strip():
        args["frame_role"] = frame_role.strip()
    via_ext = await _browser_tool_via_ext_or_cdm("click", args)
    if via_ext is not None:
        if not via_ext.get("ok"):
            return {**via_ext, "source": "extension"}
        res = via_ext.get("result") or {}
        # 自愈失败 (PLATFORM_FRAME_LOST 等) 也走这条路, ok=false 透传
        return {
            "ok": bool(res.get("ok", True)),
            "source": "extension",
            "frame_url": res.get("frame_url"),
            "clicked": res.get("clicked"),
            **_merge_self_heal_fields(res, frame_id),
            **({"error_code": res["error_code"]} if isinstance(res, dict) and res.get("error_code") else {}),
            **({"message": res["message"]} if isinstance(res, dict) and res.get("message") else {}),
            **({"original_error": res["original_error"]} if isinstance(res, dict) and res.get("original_error") else {}),
        }

    from app.browser_mcp_bridge import browser_bridge
    raw = await browser_bridge.call_tool("click", {"uid": uid.strip()})
    try:
        import json as _j
        return {**_j.loads(raw), "source": "cdm", "frame_id": int(frame_id)}
    except Exception:
        return {"ok": True, "source": "cdm", "raw": raw, "frame_id": int(frame_id)}


@mcp.tool()
async def browser_type(
    uid: str,
    text: str,
    frame_id: int = 0,
    frame_role: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """往 a11y tree 里某个 input 元素填文本。先 browser_snapshot 拿 uid。

    寻址同 browser_click — 推荐 frame_role="platform", 抗 iframe 重建。
    自愈语义同 browser_click。
    """
    if not uid.strip():
        return {"ok": False, "error_code": "INVALID_UID", "message": "uid 不能为空"}
    args = {"uid": uid.strip(), "text": text, "frame_id": int(frame_id)}
    if frame_role.strip():
        args["frame_role"] = frame_role.strip()
    via_ext = await _browser_tool_via_ext_or_cdm("type", args)
    if via_ext is not None:
        if not via_ext.get("ok"):
            return {**via_ext, "source": "extension"}
        res = via_ext.get("result") or {}
        return {
            "ok": bool(res.get("ok", True)),
            "source": "extension",
            "frame_url": res.get("frame_url"),
            "typed": res.get("typed"),
            "target": res.get("target"),
            **_merge_self_heal_fields(res, frame_id),
            **({"error_code": res["error_code"]} if isinstance(res, dict) and res.get("error_code") else {}),
            **({"message": res["message"]} if isinstance(res, dict) and res.get("message") else {}),
            **({"original_error": res["original_error"]} if isinstance(res, dict) and res.get("original_error") else {}),
        }

    from app.browser_mcp_bridge import browser_bridge
    raw = await browser_bridge.call_tool("fill", {"uid": uid.strip(), "value": text})
    try:
        import json as _j
        return {**_j.loads(raw), "source": "cdm", "frame_id": int(frame_id)}
    except Exception:
        return {"ok": True, "source": "cdm", "raw": raw, "frame_id": int(frame_id)}


@mcp.tool()
async def browser_wait_for_text(
    text: str,
    frame_id: int = 0,
    frame_role: str = "",
    timeout_ms: int = 5000,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在指定 frame 内等某段文字出现, 命中即返。常用来确认平台 iframe 已渲染完上一步操作的结果。

    入参:
      text       要等的文本子串（substring 匹配 body.innerText, 大小写敏感）
      frame_role 推荐: "platform" / "host" — 现场解析当前匹配 role 的 frame, 抗 iframe 重建
      frame_id   备选: 显式 frame id (短链路场景可用, 长链路推荐 frame_role)
      timeout_ms 最长等多久, 默认 5000ms; 后端 RPC timeout 自动比这个长 2s

    返回:
      ok=True  → {ok, text, elapsed_ms, frame_id, [self_healed]}
      ok=False → {ok, error_code:"WAIT_TIMEOUT"|"PLATFORM_FRAME_LOST"|..., ...}

    用途: click 一个菜单后, 等"角色与权限"这种 panel header 出现再下一步; 比固定 sleep
    精确, 不会因为网慢漏判。仅走 chrome extension; fallback CDM 没等价工具直接报错。
    """
    if not text:
        return {"ok": False, "error_code": "INVALID_TEXT", "message": "text 必填"}
    timeout_ms = max(100, min(30000, int(timeout_ms or 5000)))
    args = {"text": text, "timeout_ms": timeout_ms, "frame_id": int(frame_id)}
    if frame_role.strip():
        args["frame_role"] = frame_role.strip()
    rpc_timeout = (timeout_ms / 1000.0) + 2.0
    via_ext = await _browser_tool_via_ext_or_cdm_with_timeout("wait_for_text", args, timeout=rpc_timeout)
    if via_ext is not None:
        if not via_ext.get("ok"):
            return {**via_ext, "source": "extension"}
        res = via_ext.get("result") or {}
        return {
            "ok": bool(res.get("ok")),
            "source": "extension",
            "frame_url": res.get("frame_url"),
            "text": res.get("text"),
            "elapsed_ms": res.get("elapsed_ms"),
            **_merge_self_heal_fields(res, frame_id),
            **({"error_code": res["error_code"]} if isinstance(res, dict) and res.get("error_code") else {}),
            **({"message": res["message"]} if isinstance(res, dict) and res.get("message") else {}),
            **({"original_error": res["original_error"]} if isinstance(res, dict) and res.get("original_error") else {}),
        }
    return {
        "ok": False,
        "error_code": "EXTENSION_NOT_CONNECTED",
        "message": "browser_wait_for_text 仅走 chrome extension; 请装 apaas-builder-helper",
    }


@mcp.tool()
async def browser_press_key(
    key: str,
    frame_id: int = 0,
    frame_role: str = "",
    uid: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在指定 frame 内按一个键 (Enter/Tab/Escape/ArrowDown/...).

    入参:
      key        键名: "Enter" / "Tab" / "Escape" / "ArrowDown" / "ArrowUp" /
                 "ArrowLeft" / "ArrowRight" / "Backspace" / "Delete" / "Space"
      frame_role 推荐: "platform" / "host"
      frame_id   备选: 显式 frame id
      uid        可选, 传了就先 focus 这个元素再按键

    仅走 chrome extension; fallback CDM 没等价工具直接报错。
    """
    if not key or not key.strip():
        return {"ok": False, "error_code": "INVALID_KEY", "message": "key 必填"}
    args = {"key": key.strip(), "frame_id": int(frame_id), "uid": uid.strip()}
    if frame_role.strip():
        args["frame_role"] = frame_role.strip()
    via_ext = await _browser_tool_via_ext_or_cdm("press_key", args)
    if via_ext is not None:
        if not via_ext.get("ok"):
            return {**via_ext, "source": "extension"}
        res = via_ext.get("result") or {}
        return {
            "ok": bool(res.get("ok", True)),
            "source": "extension",
            "frame_url": res.get("frame_url"),
            "key": res.get("key"),
            "target_tag": res.get("target_tag"),
            **_merge_self_heal_fields(res, frame_id),
            **({"error_code": res["error_code"]} if isinstance(res, dict) and res.get("error_code") else {}),
            **({"message": res["message"]} if isinstance(res, dict) and res.get("message") else {}),
            **({"original_error": res["original_error"]} if isinstance(res, dict) and res.get("original_error") else {}),
        }
    return {
        "ok": False,
        "error_code": "EXTENSION_NOT_CONNECTED",
        "message": "browser_press_key 仅走 chrome extension; 请装 apaas-builder-helper",
    }


@mcp.tool()
async def browser_navigate(url: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """让当前活动 tab 跳到指定 URL。等页面加载完返回。"""
    if not url.strip():
        return {"ok": False, "error_code": "INVALID_URL", "message": "url 不能为空"}
    via_ext = await _browser_tool_via_ext_or_cdm("navigate", {"url": url.strip()})
    if via_ext is not None:
        return {**via_ext, "source": "extension"}
    from app.browser_mcp_bridge import browser_bridge
    raw = await browser_bridge.call_tool("navigate_page", {"url": url.strip()})
    try:
        import json as _j
        return {**_j.loads(raw), "source": "cdm"}
    except Exception:
        return {"ok": True, "source": "cdm", "raw": raw}


@mcp.tool()
async def browser_screenshot(tenant_id: int = 0, user_id: int = 0) -> dict:
    """截当前 tab 视口（PNG），返 base64 data URL，前端 <img> 可直显示。

    比 browser_snapshot 信息更全（视觉布局、颜色、错误提示等），token 成本更高。
    建议：先 snapshot 看 a11y 结构，找不到元素再 screenshot 用视觉定位。

    优先 Chrome extension (用 chrome.tabs.captureVisibleTab, 走用户真 Chrome)，
    fallback chrome-devtools-mcp (:9222 独立 profile).
    """
    import base64 as _b64
    import os as _os
    import tempfile as _tmp
    import time as _t

    # 2026-05-21: ext 优先 — extension 用 chrome.tabs.captureVisibleTab 直接返 data URL
    via_ext = await _browser_tool_via_ext_or_cdm("screenshot", {})
    if via_ext is not None:
        if via_ext.get("ok"):
            res = via_ext.get("result") or {}
            return {
                "ok": True,
                "source": "extension",
                "image_data_url": res.get("image_data_url") or res.get("dataUrl"),
                "mime_type": res.get("mime_type") or "image/png",
                "data_size": res.get("data_size"),
            }
        return via_ext

    from app.browser_mcp_bridge import browser_bridge
    # chrome-devtools-mcp take_screenshot 默认不返 base64，得指定 filePath 落盘
    tmp_path = _os.path.join(_tmp.gettempdir(), f"apaas_browser_shot_{int(_t.time()*1000)}.png")
    raw = await browser_bridge.call_tool(
        "take_screenshot",
        {"format": "png", "filePath": tmp_path},
    )
    try:
        if not _os.path.exists(tmp_path):
            return {"ok": False, "error_code": "SCREENSHOT_FAILED", "raw": raw}
        with open(tmp_path, "rb") as f:
            data = f.read()
        _os.unlink(tmp_path)
        b64 = _b64.b64encode(data).decode("ascii")
        return {
            "ok": True,
            "image_data_url": f"data:image/png;base64,{b64}",
            "mime_type": "image/png",
            "data_size": len(data),
        }
    except Exception as exc:
        return {"ok": False, "error_code": "SCREENSHOT_READ_FAILED", "message": str(exc)}


# ─────────────────────────── Config Assistant 自学习 skills ───────────────────────────
# image #46 — 用户教过 AI 一次操作后，AI 把流程总结成 skill 存起来，下次同类
# 指令自动 follow。system_prompt 注入相关 skills，遇到 trigger 关键词 AI 自己读
# steps_md 复现。
#
# 数据存 config_assistant_skills 表 (见 backend/app/models/config_assistant_skill.py)。


@mcp.tool()
async def save_config_skill(
    name: str,
    intent_keywords: str,
    steps_md: str,
    app_id: int = 0,
    notes: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把刚做完的一类操作存成 skill。下次用户说类似话，AI 能直接 follow 这个 skill 不用从零摸索。

    入参：
      name             skill 名（10-40 字，譬如"加报销单备注字段并挂表单"）
      intent_keywords  匹配关键词，逗号分隔（"加字段,新增字段,挂表单"）— SYSTEM_PROMPT 拼 prompt 时按 token 匹配
      steps_md         markdown 步骤（含 browser_snapshot/click 序列 + apaas MCP 调用，要写清"先 list X 拿 id 再 update"）
      app_id           可选，0 = 全局 skill（适用所有应用），>0 = 仅当前应用
      notes            可选备注（"小心 X 字段会触发审批" 之类）

    返回：{ok, skill_id, message}
    """
    if not name.strip() or not steps_md.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "name 和 steps_md 必填"}
    from app.database import AsyncSessionLocal
    from app.models import ConfigAssistantSkill
    tid, uid = _resolve_identity(tenant_id, user_id)
    async with AsyncSessionLocal() as db:
        row = ConfigAssistantSkill(
            tenant_id=tid,
            app_id=app_id if app_id > 0 else None,
            name=name.strip()[:120],
            intent_keywords=intent_keywords.strip()[:500],
            steps_md=steps_md.strip(),
            notes=notes.strip() if notes.strip() else None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return {
            "ok": True,
            "skill_id": row.id,
            "message": f"已保存 skill「{row.name}」(id={row.id})，下次说{intent_keywords.split(',')[0] if intent_keywords else '类似'}时我会复用。",
        }


@mcp.tool()
async def list_config_skills(
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出当前 tenant 的可用 skills（app_id=0 时列全局+所有 app 的；指定 app_id 列全局+该 app 的）。

    返回 [{id, name, intent_keywords, steps_md (前 500 字摘要), notes, scope}]
    """
    from app.database import AsyncSessionLocal
    from app.models import ConfigAssistantSkill
    from sqlalchemy import select, or_
    tid, _ = _resolve_identity(tenant_id, user_id)
    async with AsyncSessionLocal() as db:
        stmt = select(ConfigAssistantSkill).where(ConfigAssistantSkill.tenant_id == tid)
        if app_id > 0:
            stmt = stmt.where(or_(
                ConfigAssistantSkill.app_id.is_(None),
                ConfigAssistantSkill.app_id == app_id,
            ))
        stmt = stmt.order_by(ConfigAssistantSkill.created_at.desc()).limit(50)
        rows = (await db.execute(stmt)).scalars().all()
        return {
            "ok": True,
            "count": len(rows),
            "skills": [
                {
                    "id": r.id,
                    "name": r.name,
                    "intent_keywords": r.intent_keywords,
                    "steps_md_excerpt": (r.steps_md or "")[:500],
                    "notes": r.notes,
                    "scope": "app" if r.app_id else "global",
                    "use_count": r.use_count,
                }
                for r in rows
            ],
        }


@mcp.tool()
async def get_config_skill(
    skill_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """读完整 skill 的 steps_md（list 只返摘要，要细节得调它）。

    会自动 +1 use_count + 更新 last_used_at，统计哪些 skill 被复用最多。
    """
    from app.database import AsyncSessionLocal
    from app.models import ConfigAssistantSkill
    from sqlalchemy import select
    from datetime import datetime
    tid, _ = _resolve_identity(tenant_id, user_id)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(ConfigAssistantSkill).where(
                ConfigAssistantSkill.id == skill_id,
                ConfigAssistantSkill.tenant_id == tid,
            )
        )).scalar_one_or_none()
        if not row:
            return {"ok": False, "error_code": "NOT_FOUND", "message": f"skill_id={skill_id} 不存在"}
        row.use_count += 1
        row.last_used_at = datetime.utcnow()
        await db.commit()
        return {
            "ok": True,
            "skill": {
                "id": row.id,
                "name": row.name,
                "intent_keywords": row.intent_keywords,
                "steps_md": row.steps_md,
                "notes": row.notes,
                "scope": "app" if row.app_id else "global",
                "use_count": row.use_count,
            },
        }


@mcp.tool()
async def delete_config_skill(
    skill_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """删除一个 skill — 用户说"忘了这个流程"/"以后不要这么干"时调。"""
    from app.database import AsyncSessionLocal
    from app.models import ConfigAssistantSkill
    from sqlalchemy import select, delete
    tid, _ = _resolve_identity(tenant_id, user_id)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(ConfigAssistantSkill).where(
                ConfigAssistantSkill.id == skill_id,
                ConfigAssistantSkill.tenant_id == tid,
            )
        )).scalar_one_or_none()
        if not row:
            return {"ok": False, "error_code": "NOT_FOUND", "message": f"skill_id={skill_id} 不存在"}
        name = row.name
        await db.execute(delete(ConfigAssistantSkill).where(ConfigAssistantSkill.id == skill_id))
        await db.commit()
        return {"ok": True, "message": f"已删除 skill「{name}」"}


# ─────────────────────────── Demonstration-based skill recording ───────────────────────────
# image #46 follow-up: 用户说"我也讲不清楚那么细致的工具调用，能不能我点一遍他自己补?"
# 流程: AI 调 browser_start_recording 注入 JS 监听 → 用户在浏览器里点点点 →
# AI 调 browser_stop_recording 拿 event log → AI 自己总结成 steps_md → save_config_skill


@mcp.tool()
async def browser_start_recording(tenant_id: int = 0, user_id: int = 0) -> dict:
    """开始录制用户在浏览器里的操作。

    注入全局 click/input/change 监听器到当前页面。返回后让用户去点击，完了再调
    browser_stop_recording 拿事件列表。AI 用拿到的事件 + 当前 snapshot 总结成
    steps_md 调 save_config_skill 存。

    注意：刷新页面会丢录制（监听器挂在 window 对象上）。

    2026-05-25: 改走扩展 — extension content.js 早就有原生 startRecording 实现
    (chrome-extension/content.js:376), 不再用 chrome-devtools-mcp 的 evaluate_script
    路径 (那条路要 Chrome 跑 --remote-debugging-port=9222, 默认用户没这么开).
    """
    via_ext = await _browser_tool_via_ext_or_cdm("start_recording", {})
    if via_ext is not None:
        if via_ext.get("ok"):
            res = via_ext.get("result") or {}
            return {"ok": True, **(res if isinstance(res, dict) else {"result": res})}
        return via_ext

    # Fallback: 老 cdm 路径 (用户没装扩展时降级, 需要 Chrome 开远程调试)
    from app.browser_mcp_bridge import browser_bridge
    js = r"""
() => {
  if (window.__apaasRec) {
    window.__apaasRec.length = 0;
    return { status: 'reset', count: 0 };
  }
  window.__apaasRec = [];
  const summarize = (el) => {
    if (!el) return null;
    return {
      tag: el.tagName,
      text: (el.innerText || el.value || '').slice(0, 60),
      id: el.id || null,
      cls: (el.className || '').slice(0, 80),
      role: el.getAttribute && el.getAttribute('role'),
      type: el.getAttribute && el.getAttribute('type'),
      placeholder: el.getAttribute && el.getAttribute('placeholder'),
      ariaLabel: el.getAttribute && el.getAttribute('aria-label'),
    };
  };
  document.addEventListener('click', (e) => { try { window.__apaasRec.push({ type: 'click', time: Date.now(), target: summarize(e.target), url: location.href }); } catch (_) {} }, true);
  document.addEventListener('change', (e) => { try { window.__apaasRec.push({ type: 'change', time: Date.now(), target: summarize(e.target), value: (e.target.value || '').slice(0, 80), url: location.href }); } catch (_) {} }, true);
  document.addEventListener('input', (e) => {
    try {
      const t = e.target;
      const key = (t.id || t.name || t.placeholder || 'anon') + '@' + location.href;
      if (!window.__apaasInputDebounce) window.__apaasInputDebounce = {};
      if (window.__apaasInputDebounce[key]) clearTimeout(window.__apaasInputDebounce[key]);
      window.__apaasInputDebounce[key] = setTimeout(() => {
        window.__apaasRec.push({ type: 'input', time: Date.now(), target: summarize(t), value: (t.value || '').slice(0, 80), url: location.href });
      }, 500);
    } catch (_) {}
  }, true);
  return { status: 'started', count: 0 };
}
"""
    raw = await browser_bridge.call_tool("evaluate_script", {"function": js})
    try:
        import json as _j
        return _j.loads(raw)
    except Exception:
        return {"ok": True, "raw": raw}


@mcp.tool()
async def browser_stop_recording(tenant_id: int = 0, user_id: int = 0) -> dict:
    """停止录制 + 返回所有录到的事件。AI 拿到后总结成 steps_md。

    返回 events 数组：[{type:'click'|'input'|'change', time, target:{tag,text,id,cls,...}, value?, url}]

    2026-05-25: 改走扩展, 跟 browser_start_recording 配对.
    """
    via_ext = await _browser_tool_via_ext_or_cdm("stop_recording", {})
    if via_ext is not None:
        if via_ext.get("ok"):
            res = via_ext.get("result") or {}
            return {"ok": True, **(res if isinstance(res, dict) else {"result": res})}
        return via_ext

    # Fallback: 老 cdm 路径
    from app.browser_mcp_bridge import browser_bridge
    js = r"""
() => {
  const events = window.__apaasRec || [];
  window.__apaasRec = null;
  return { events: events, count: events.length };
}
"""
    raw = await browser_bridge.call_tool("evaluate_script", {"function": js})
    try:
        import json as _j
        parsed = _j.loads(raw)
        if isinstance(parsed, dict) and 'raw' in parsed:
            raw_text = parsed['raw']
            import re
            m = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if m:
                try:
                    return _j.loads(m.group(0))
                except Exception:
                    pass
        return parsed
    except Exception:
        return {"ok": True, "raw": raw}


@mcp.tool()
async def browser_list_pages(tenant_id: int = 0, user_id: int = 0) -> dict:
    """列出浏览器里所有打开的 tabs。优先 Chrome extension (chrome.tabs.query 拿全 tab,
    含 cookies + 真 user profile), fallback chrome-devtools-mcp HTTP /json/list (:9222).

    返回 pages: [{id, url, title, type}]。AI 撞 'No page selected' 时用它定位 tab，
    再 browser_navigate 跳过去（navigate 会自动 select 那个 tab）。
    """
    # 2026-05-21: ext 优先 — extension list_tabs 命令返完整 chrome.tabs.query 结果
    via_ext = await _browser_tool_via_ext_or_cdm("list_tabs", {})
    if via_ext is not None:
        if via_ext.get("ok"):
            res = via_ext.get("result") or {}
            return {
                "ok": True,
                "source": "extension",
                "count": res.get("count", 0),
                "pages": res.get("tabs", []),
            }
        return via_ext

    import httpx as _httpx
    import os as _os
    base = _os.getenv("CHROME_DEVTOOLS_BROWSER_URL", "http://127.0.0.1:9222")
    try:
        async with _httpx.AsyncClient(timeout=5.0) as cli:
            r = await cli.get(f"{base}/json/list")
            if r.status_code != 200:
                return {"ok": False, "error_code": "CDP_HTTP", "message": f"HTTP {r.status_code}"}
            data = r.json()
            pages = [
                {
                    "id": p.get("id"),
                    "url": p.get("url"),
                    "title": p.get("title"),
                    "type": p.get("type"),
                }
                for p in data
                if p.get("type") in ("page", "tab", "background_page", None)
            ]
            return {"ok": True, "source": "cdm", "count": len(pages), "pages": pages}
    except Exception as exc:
        return {"ok": False, "error_code": "CDP_FAIL", "message": f"{exc}. 提示: 安装 apaas-builder-helper Chrome extension 走用户真 Chrome 路径, 不用开 --remote-debugging-port=9222"}


@mcp.tool()
async def browser_select_page(page_id: int, bring_to_front: bool = True, tenant_id: int = 0, user_id: int = 0) -> dict:
    """切换到指定 tab 当作"活动 page" — 后续 snapshot/click/type 都作用在它上。

    先 browser_list_pages 拿 pageId。bring_to_front=true 会让那个 tab 浮到前面。
    优先 Chrome extension (chrome.tabs.update active=true), fallback chrome-devtools-mcp.
    """
    # 2026-05-21: ext 优先 — extension select_tab cmd 用 chrome.tabs.update 激活
    via_ext = await _browser_tool_via_ext_or_cdm("select_tab", {"tabId": page_id, "bringToFront": bring_to_front})
    if via_ext is not None:
        return {**via_ext, "source": "extension"}

    from app.browser_mcp_bridge import browser_bridge
    raw = await browser_bridge.call_tool(
        "select_page",
        {"pageId": page_id, "bringToFront": bring_to_front},
    )
    try:
        import json as _j
        return _j.loads(raw)
    except Exception:
        return {"ok": True, "source": "cdm", "raw": raw}
