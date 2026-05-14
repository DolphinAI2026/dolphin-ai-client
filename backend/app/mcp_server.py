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
) -> dict:
    """直接上传一个外部 zip 到 apaas 平台（不走 workspace），覆盖 V2.6 全 12 类 fileType。

    ⚠️ 当前版本是简化 stub — 完整流程（base64 解码 + multipart upload + 自动判断
    update/create + auto-attach to app）正在迁移中。建议先用 publish_dev_workspace。

    入参：env_id / file_name / file_content_b64 / file_type / description / apaas_app_id（可选）
    """
    valid_ft = (file_type or "").strip().upper()
    if valid_ft not in _PLATFORM_FILE_TYPES_V2_6:
        return {
            "ok": False, "error_code": "INVALID_FILE_TYPE",
            "message": f"file_type '{file_type}' 不在 V2.6 全 12 类里",
            "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
        }
    if not file_name.strip() or "/" in file_name or "\\" in file_name:
        return {"ok": False, "error_code": "INVALID_FILE_NAME",
                "message": "file_name 只能是文件名，不能含路径分隔符"}
    if not file_content_b64.strip():
        return {"ok": False, "error_code": "EMPTY_CONTENT", "message": "file_content_b64 不能为空"}

    return {
        "ok": False,
        "error_code": "NOT_IMPLEMENTED",
        "message": (
            "upload_external_zip_to_apaas 暂未在本分支实现（需要 multipart upload + "
            "智能 update/create 切换 + auto-attach）。"
            "建议改用 publish_dev_workspace，或先 attach_dev_packages_to_apaas_app + "
            "republish_apaas_app 替代。"
        ),
        "env_id": env_id,
        "file_name": file_name.strip(),
        "file_type": valid_ft,
        "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
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
    payload = {
        "scene_type": scene_type,
        "project_name": project_name.strip(),
        "display_name": display_name.strip() or project_name.strip(),
        "initial_requirement": initial_requirement or "",
        "apaas_app_id": apaas_app_id or "",
        "apaas_app_name": apaas_app_name or "",
    }
    res = await _api_call("POST", "/coding/workspace/create", tenant_id=tid, user_id=uid, json=payload)
    if isinstance(res, dict) and res.get("ws_id"):
        return {
            "ok": True,
            "ws_id": res["ws_id"],
            "scene_type": scene_type,
            "project_name": project_name.strip(),
            "display_name": display_name or project_name,
            "tenant_id": tid,
            "user_id": uid,
            "next_steps": [
                f"用 get_dev_workspace_status('{res['ws_id']}') 查工作区状态",
                "用 read_workspace_file / write_workspace_files / edit_workspace_files 写代码",
                "完成后 run_workspace_command('npm run build') + publish_dev_workspace",
            ],
        }
    return {"ok": False, "error_code": "CREATE_FAILED", "message": "create_workspace 返回异常", "raw": res}


@mcp.tool()
async def save_dev_spec(ws_id: str, spec_md: str, mockup_html: str = "", tenant_id: int = 0, user_id: int = 0) -> dict:
    """Phase 1 必调：落盘双产物（技术 SPEC + 业务可视 HTML mockup），返回 spec_token + preview_url。

    ⚠️ 当前版本是 stub — 完整实现涉及 ai-builder 的 spec_token 系统 + dev-spec
    preview 链路。先用 write_workspace_files 把 spec.md 写到 workspace 根目录。
    """
    return {
        "ok": False, "error_code": "NOT_IMPLEMENTED",
        "message": (
            "save_dev_spec 暂未在本分支实现。临时方案："
            "用 write_workspace_files 把 spec.md 写到 workspace 根目录，"
            "用户可在 ai-builder /coding 页面手动预览。"
        ),
        "ws_id": ws_id,
    }


@mcp.tool()
async def import_zip_to_workspace(scene_type: str, project_name: str, zip_b64: str, tenant_id: int = 0, user_id: int = 0) -> dict:
    """把外部 zip（base64）解压成新 workspace，给二次开发场景用。

    ⚠️ 当前版本是 stub — 完整实现涉及 base64 解码 + zip 安全解压 + 脚手架合并。
    建议改用 create_dev_workspace + write_workspace_files。
    """
    return {
        "ok": False, "error_code": "NOT_IMPLEMENTED",
        "message": (
            "import_zip_to_workspace 暂未在本分支实现。临时方案："
            "用 create_dev_workspace 起新 workspace，然后 write_workspace_files 批量写入。"
        ),
    }


@mcp.tool()
async def publish_dev_workspace(ws_id: str, env_id: int = 0, tenant_id: int = 0, user_id: int = 0) -> dict:
    """把自开发 workspace build 产物部署到 aPaaS 平台。

    ⚠️ 当前版本是 stub — 完整链路：build → 打 zip → upload_zip → attach_to_app → republish。
    临时方案：分步调 run_workspace_command('npm run build') → 用户在 ai-builder UI
    点"上传组件包"按钮（CodingPage.vue 有这个），后端走 codingApi.uploadToPlatform。
    """
    return {
        "ok": False, "error_code": "NOT_IMPLEMENTED",
        "message": (
            "publish_dev_workspace 暂未在本分支实现。完整链路较长，临时方案："
            "1) run_workspace_command('npm run build')  "
            "2) 用户在 ai-builder /coding 页面点'上传组件包'按钮（自动 enable_self_dev_config + attach + republish）  "
            "或者：3) 手工调 attach_dev_packages_to_apaas_app + republish_apaas_app"
        ),
        "ws_id": ws_id,
        "next_tools": ["run_workspace_command", "attach_dev_packages_to_apaas_app", "republish_apaas_app"],
    }
