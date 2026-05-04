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
    if not tenant_id or not user_id:
        raise ValueError(
            "缺少 tenant_id / user_id —— 请在得小帆 MCP 配置「自定义 Body 字段」里加上 "
            '{"tenant_id": <num>, "user_id": <num>}'
        )
    return int(tenant_id), int(user_id)


def _resolve_app_id(app_id: int | None, user_id: int) -> tuple[int, str]:
    """工具收到 app_id=None 时，从 current_app 模块拿用户当前编辑的应用。
    返回 (app_id, app_name)。"""
    if app_id and app_id > 0:
        return int(app_id), ""
    # 延迟 import，避免循环依赖
    from app.routes.current_app import get_current_app_for_user
    rec = get_current_app_for_user(int(user_id))
    if not rec:
        raise ValueError(
            "未指定 app_id，且后端没有用户当前编辑应用的状态。"
            "请告诉助手具体的应用 ID（数字），或先在 ai-builder UI 打开某个应用。"
        )
    return rec


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
async def generate_app_from_doc(
    md_content: str,
    app_name: str | None = None,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """根据标准 markdown 设计文档创建一个新的 aPaaS 低代码应用（一步到位）。

    内部分两步：parse → auto-create。md 必须是标准 6 章节格式（参考 parse_design_doc 文档）。

    参数：
    - md_content：标准设计文档全文
    - app_name：可选；不填会从 md 「一、应用信息」推断

    返回 { app_id, app_name, app_code, status, app_view_url }。app_view_url 是用户在
    AI-Builder UI 里查看该应用的链接。
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
    create_res = await _api_call(
        "POST",
        "/applications/auto-create",
        tenant_id=tid,
        user_id=uid,
        json_body={"app_name": final_app_name, "config_preview": {"data": preview}},
    )
    app_id = create_res.get("app_id")
    return {
        "ok": True,
        "app_id": app_id,
        "app_name": create_res.get("app_name"),
        "app_code": create_res.get("app_code"),
        "is_new": create_res.get("is_new"),
        "status": "draft",
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
