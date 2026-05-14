"""AI-Builder MCP Server — 把应用领域能力封装成 MCP 工具暴露给得小帆等 agent 平台。

设计：
- FastMCP 实例 mount 到主 FastAPI 进程的 /api/mcp/sse 子路径，复用 :8003 + 现有 nginx
- 每个工具内部用临时 service JWT 调本机 :8003 现有 HTTP API（不复制业务逻辑）
- SSE 流式 endpoint 用 httpx 自己 consume 到 done 事件再返回，对调用方表现为同步
- 鉴权：MCP server 自身要 Bearer API key（防外网随便调）；
  实际操作的租户/用户身份通过得小帆"自定义 Body 字段"配置注入，每个 tool 形参带 _tenant_id / _user_id

环境变量：
- MCP_API_KEYS: 逗号分隔的合法 Bearer token（dolphin 配置里填其中一个）
- MCP_INTERNAL_BASE: 内部回环 base URL，默认 http://127.0.0.1:8003/api
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


_INTERNAL_BASE = os.getenv("MCP_INTERNAL_BASE", "http://127.0.0.1:8003/api")
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


def _resolve_identity(tenant_id: int | None, user_id: int | None) -> tuple[int, int]:
    """dolphin 自定义 Body 字段硬编码 (tenant_id=1, user_id=1)，但 ai-builder
    用户多租户多账号，直接用这俩调内部 API 会跨租户错位（看不到当前用户的应用）。

    从 current_app 反查真实身份覆盖；找不到才用 dolphin 传的兜底。
    """
    from app.routes.current_app import get_current_app_for_user
    rec = get_current_app_for_user(int(user_id) if user_id else 1)
    if rec:
        real_uid, real_tid, _, _ = rec
        return int(real_tid), int(real_uid)
    if not tenant_id or not user_id:
        raise ValueError(
            "缺少身份信息：dolphin Body 字段未注入 tenant_id/user_id 且 ai-builder 没有"
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
) -> Any:
    """调本机内部 endpoint。普通 JSON 接口直接返；SSE 由 _api_call_sse 处理。"""
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
) -> dict:
    """专门给 SSE endpoint 用：consume 整个 stream，按事件聚合返回最终状态。

    返回 { events: [...], done: <最终 done payload>, errors: [...] }
    """
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
    # dolphin 等 agent 平台的 streamable HTTP client 不可靠传递 session id，
    # 默认 stateful 会在第二个 request 报 400 Missing session ID。
    stateless_http=True,
    # JSON 响应（非 SSE 流），dolphin 解析更稳定
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

    用法（agent 工作流）：用户首次创建应用前**必须**先调本工具拿环境列表，
    再让用户确认要部署到哪个环境。绝不假设"默认环境"用户就接受。

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
    - connected_count == 1 且唯一 connected 环境 is_default → 直接用，
      告诉用户"应用会部署到「{name}」"
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
    md_content: str,
    app_name: str | None = None,
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """根据标准 markdown 设计文档创建一个新的 aPaaS 低代码应用（一步到位）。

    内部分两步：parse → auto-create。md 必须是标准 6 章节格式（参考 parse_design_doc 文档）。

    参数：
    - md_content：标准设计文档全文
    - app_name：可选；不填会从 md 「一、应用信息」推断
    - env_id：部署到哪个 PlatformEnv。**强烈建议先调 list_platform_envs
      让用户确认**。0 表示用租户默认环境（fallback：找一个 connected 环境）。

    返回 { app_id, app_name, app_code, status, app_view_url, env: {id, name} }。
    """
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
        "app_view_url": (
            f"https://agent.dfy.definesys.cn/ai-builder/chat?app_id={app_id}" if app_id else None
        ),
    }


@mcp.tool()
async def list_my_applications(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出当前租户下我能访问的所有 aPaaS 应用（分页第 1 页，最多 50 条）。"""
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
        "app_view_url": f"https://agent.dfy.definesys.cn/ai-builder/chat?app_id={app_id}",
        "spec_markdown": spec_md,
        "spec_markdown_source": spec_source,
        "spec_markdown_version": spec_version,
    }


async def _normalize_md_via_llm(target_md: str, current_spec_md: str) -> str:
    """LLM 兜底：dolphin agent 给的 md 若不符合严格 6 章节模板，
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
async def validate_builder_doc(md_content: str) -> dict:
    """校验一份 markdown 设计文档是否符合 aPaaS Builder 标准（不创建应用、不需要身份）。

    用法：写完 / 改完 md 之后，先调这个工具自检。建议工作流：
      1. 写完 md → 调 validate_builder_doc
      2. passes_strict=False → 按 missing_sections / weak_sections / signals / advice 自我修补
      3. 重复至多 3 轮；仍不通过把问题原文列给用户决定
      4. passes_strict=True 才把 md 文档输出给用户（或直接用 generate_app_from_doc）

    返回：
        {
          "ok": True,
          "score": 0-100,                   # 综合分
          "level": "standard|partial|freeform",
          "decision": "pure_code|hybrid_fallback|rewrite_first",  # 后端会按此走解析路径
          "passes_strict": bool,            # score >= 95 且无 missing_sections，可直接送 strict 解析
          "missing_sections": [str],        # 缺的必填章节中文名
          "weak_sections": [str],           # 表头不达标的章节中文名
          "signals": {                       # 5 维子项打分（0~1）
              "section_coverage": ...,       # 必填章节覆盖率（30 分权重）
              "header_format": ...,          # ## N、名称 标题格式（15 分）
              "table_header_match": ...,     # 表头与标准 6 章模板匹配率（25 分）
              "code_compliance": ...,        # 编码字段全英文小写下划线（15 分）
              "ref_integrity": ...           # 字典/模型引用闭合（15 分）
          },
          "advice": [str],                  # 给 agent 的下一步修补建议（人话）
        }
    """
    return _do_validate_builder_doc(md_content)


# ─────────────────────── 需求分析助手 → ai-builder 设计文档中转 ───────────────────────
#
# 设计目标：让需求分析助手（dolphin agent 81）写完标准 md 后，把文档内容传到 ai-builder
# 后端 cache，前端 RequirementsAssistantPage 的右侧 ArtifactPanel 轮询 cache 拉到展示，
# 并提供「→ Builder」一键跳到 /chat 走应用建立流程。
#
# 用户身份反查：dolphin 自定义 Body 字段会注入 user_id（trial 阶段都是 1，但前面的
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
    md_content: str,
    file_name: str = "design-doc.md",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把当前 md 设计文档推送到 ai-builder cache，并返回一条 deeplink — agent 必须把这条
    deeplink 贴到 chat 里让用户点击，**这是把 md 送到 Builder 的唯一推荐路径**。

    用法（在 prompt 工作流里）：
      1. 写完 md → 调 validate_builder_doc 自检（passes_strict=true）
      2. 沙箱 Python 写 .md 文件让 dolphin chat UI 自然渲染附件下载（标准 UX）
      3. **调本工具** submit_design_doc(md_content) — 把内容写入 ai-builder 用户 cache
      4. **把返回值里的 deeplink 用 markdown 链接格式贴在 chat 回复里**，例如：
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

    pending_id 30 分钟后自动失效；用户在 dolphin 修改 md 重新调本工具时会覆盖之前的 cache。
    deeplink 不带 pending_id —— ai-builder 端按当前登录用户从 cache 读最新 md，避免跨用户串号。
    """
    if not md_content or not md_content.strip():
        return {"ok": False, "error": "md_content 是空的，无法提交"}

    tid, uid = _resolve_identity(tenant_id, user_id)
    pending_id = _uuid.uuid4().hex[:16]
    score = (_do_validate_builder_doc(md_content) or {}).get("score", 0)
    rec = {
        "pending_id": pending_id,
        "file_name": (file_name or "design-doc.md").strip() or "design-doc.md",
        "md_content": md_content,
        "score": score,
        "submitted_at": _time.time(),
        "source": "dolphin-requirements-agent",
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
# - 这一层是给外部 agent（dolphin / Claude / Cursor）的薄壳子
# - 每个工具显式接 env_id 参数（让 caller 自己决定调哪个 aPaaS 环境）
# - workspace 类的 read_attachment / write_artifact 不外暴（caller 没 workspace 上下文）
# ═══════════════════════════════════════════════════════════════════════════


async def _call_apaas_platform_tool(name: str, args: dict, env_id: int) -> dict:
    """统一桥接平台类 apaas 工具：调 executor → JSON 解析为 dict。"""
    from app.coding.apaas_tools import APAAS_TOOL_EXECUTORS_PLATFORM
    from app.database import AsyncSessionLocal
    executor = APAAS_TOOL_EXECUTORS_PLATFORM.get(name)
    if not executor:
        return {"ok": False, "error_code": "UNKNOWN_TOOL", "message": f"未知工具 {name}"}
    async with AsyncSessionLocal() as db:
        result_str = await executor(args, env_id, db)
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
    返 in_progress + polling_hint，避免 dolphin omnigate 30s timeout 拦截。
    """
    import asyncio as _asyncio
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}

    sse_token = _sign_service_token(uid, tid)
    FAST_RETURN_TIMEOUT = 25.0

    async def _run_full_sse() -> dict:
        return await _api_call_sse_collect(
            "GET",
            f"/applications/{app_id}/generate",
            tenant_id=tid,
            user_id=uid,
            params={"token": sse_token},
            timeout=600.0,
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
      ws_id  AI Coding workspace ID (不以 'oc_' 开头)
      env_id 平台环境 ID（apaas 部署目标）

    返回 internal endpoint 原样响应 — 含 uploaded_kits / errors 等
    """
    if ws_id.startswith("oc_"):
        return {"ok": False, "error_code": "WRONG_WS_TYPE",
                "message": "publish_dev_workspace 只支持 AI Coding workspace（非 oc_ 前缀）。"
                           "Vibe workspace 请自己 zip + 用 upload_external_zip_to_apaas"}
    if not env_id:
        return {"ok": False, "error_code": "INVALID_ENV_ID", "message": "env_id 必填"}
    tid, uid = _resolve_identity(tenant_id, user_id)
    res = await _api_call(
        "POST", f"/coding/workspace/{ws_id}/upload-to-platform",
        tenant_id=tid, user_id=uid, json_body={"env_id": env_id},
        timeout=600.0,  # build + upload 可能耗时
    )
    if isinstance(res, dict):
        return {"ok": True, "ws_id": ws_id, "env_id": env_id, **res}
    return {"ok": False, "error_code": "UPLOAD_FAILED", "raw": res}


# ═══════════════════════════════════════════════════════════════════════════
# Vibe Coding 工具集（11 个）— 平行于 layer 2 的 11 个 workspace 工具
# 操作 Vibe Coding workspace（id 格式 oc_xxx，跟 layer 2 的 1_xxx 完全独立）
#
# 用途：让 dolphin / Claude 等外部 agent 能接入 vibe-coding 的"从零搭独立项目"能力，
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
    payload = [{
        "dictionaryCode": dict_code.strip(),
        "dictionaryName": dict_name.strip(),
        "dictionaryDescribe": describe or "",
        "dictionaryStatus": "ENABLE",
        "dictionaryMulticolorStatus": "ENABLE",
        "internalResource": True,
    }]
    ok, raw = await _with_client(env_id, "建字典", lambda c: c.create_dicts(apaas_app_id.strip(), payload))
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
    """
    if not (apaas_app_id.strip() and menu_name.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+menu_name+form_id 都必填"}
    ok, raw = await _with_client(env_id, "建表单菜单",
        lambda c: c.create_menu(apaas_app_id.strip(), menu_name.strip(), form_id.strip(),
                                menu_order=menu_order, datasource_id="", datasource_code=""))
    if not ok:
        return raw
    return {"ok": True, "message": f"表单菜单「{menu_name}」已创建（form_id={form_id}）"}


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
