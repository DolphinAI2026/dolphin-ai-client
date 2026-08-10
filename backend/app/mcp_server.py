"""AI-Builder MCP Server — 把应用领域能力封装成 MCP 工具供同进程 Python 代码消费。

设计：
- 本模块是**进程内 FastMCP 工具库**，由同进程的 mcp_bridge / agent pipeline 直接 import 使用，
  不对外 mount HTTP endpoint，也不做入站 Bearer 鉴权。
- 每个工具内部用临时 service JWT 调本机 HTTP API（不复制业务逻辑）
- SSE 流式 endpoint 用 httpx 自己 consume 到 done 事件再返回，对调用方表现为同步
- MCP_API_KEYS 仅由 mcp_bridge / builder_mcp / admin_mcp 等出站调用时读取，
  用于向外部 MCP 服务鉴权；本模块不读该变量。

环境变量：
- MCP_INTERNAL_BASE: 内部回环 base URL，默认跟随后端 settings.port

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
新工具规范（写新 @mcp.tool 必读 — 为后续按域拆包铺路）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
公共样板设施在 app/mcp_envelope.py（_ok / _err / ErrorCode / apaas_tool / validate_required）。
**新工具一律走这套**，别再逐工具复制信封 / 校验 / 身份样板：

1) 返回信封：成功用 `return _ok(**fields)`，失败用 `return _err(ErrorCode.XXX, "文案", **fields)`。
   - 不要再手写 `{"ok": True/False, ...}` 字面量。
   - error_code 必须用 ErrorCode 常量，不要裸字符串 — 下游 agent 在按 error_code 分支，
     新码也先在 mcp_envelope.ErrorCode 里建常量（值就是字符串本身）。

2) 必填校验：用 `@apaas_tool(required=[...], message="...")` 装饰（放在 @mcp.tool() 下方），
   缺必填自动返 _err(INVALID_PARAMS) 不进函数体。装饰器经 functools.wraps 完整保留签名 /
   注解 / docstring，FastMCP schema 不变（tests/test_mcp_envelope.py 验证）。
   - 嫌装饰器隐式，可改手动调 `validate_required(locals(), [...], message="...")` 同效。

3) 身份解析仍走 `tid, uid = _resolve_identity(tenant_id, user_id)` helper（已是一行，
   装饰器注入反而让函数体依赖魔法局部变量、不收口，刻意不做）。

4) 改任何工具的**返回 dict 字段名 / 错误文案 / error_code 值都属破坏性变更** —
   下游 agent 在解析，CI 有 test_tool_registry.py 锁工具名 + runtime drift check 兜底，
   但字段 / 文案没自动门，靠本规范 + review 守。

试点迁移域：字典 + 模型字段 CRUD（本文件内 create/update/add/disable_apaas_*_dict /
*_dict_option / *_model_field / *_app_model / bind_apaas_form_field_to_dict）已按上述迁移，
可作样板照抄。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import contextlib
import contextvars
import copy
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from jose import jwt
from app.auth import _ISSUER  # 内部服务 token 必须带 iss，否则被 decode_token 的 issuer 白名单拒(401)
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.error_messages import is_apaas_token_error
from app.field_types import select_choose_type_for_component
from app.mcp_envelope import ErrorCode, _err, _ok, apaas_tool
from app.step_executor import _apply_dictionary_binding_to_component
from app.tool_registry import load as _load_tool_registry

# SPEC v2 PR1: 启动时 load tool_registry.yaml, fail-fast 检查 yaml syntax 跟 schema.
# 若 yaml 缺失 / 不合法, 进程拒启 — 比生产环境静默漏工具安全.
_load_tool_registry()

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


_INTERNAL_BASE = (
    os.getenv("MCP_INTERNAL_BASE", "").strip()
    or f"http://127.0.0.1:{getattr(settings, 'port', 8000)}/api"
)


# ─────────────────────── 内部 HTTP 调用 helper ───────────────────────


def _sign_service_token(user_id: int, tenant_id: int, ttl_minutes: int = 15) -> str:
    """签一个短期 JWT 给内部 endpoint 用。复用主 jwt_secret_key。"""
    payload = {
        "sub": str(user_id),
        "tid": tenant_id,
        "type": "mcp_service",
        "iss": _ISSUER,  # 必须带 iss(ai-builder)→ 过 decode_token 的 issuer 白名单, 否则内部调用 401
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


# 进程内可信入口（mcp_bridge / admin 测试台）在调工具前用 trusted_identity() 把
# JWT 派生的真实 (tenant_id, user_id) 塞进这个 contextvar，告诉 _resolve_identity
# “这条调用的身份是服务端背书的、可信的，直接采信，别再用进程内 current_app slot 覆盖”。
# 外部 /api/mcp/mcp（Dolphin）HTTP 路径不经过这些入口、不设此标记，保持原 slot 反查行为。
_TRUSTED_IDENTITY: contextvars.ContextVar[tuple[int, int] | None] = contextvars.ContextVar(
    "_mcp_trusted_identity", default=None
)


@contextlib.contextmanager
def trusted_identity(tenant_id: int | None, user_id: int | None):
    """标记当前（进程内）工具调用携带服务端背书的可信身份。

    仅 mcp_bridge / admin 测试台等进程内入口使用——它们的 tenant_id/user_id 来自已
    鉴权的 JWT 会话(ctx.tenant_id / ctx.user.id)，是“此刻”的真值，必须优先于进程内
    current_app slot（slot 是“上次活跃/默认租户”，多租户切换后可能残留旧租户 → 串租户）。

    外部 HTTP MCP 路径（共享 MCP_API_KEYS、调用方自带 args）**不要**用本上下文，
    否则外部调用方就能凭传入 tenant_id 跨租户读数据（历史泄漏：宝洁经外部 agent 拿到
    admin 租户的全部环境）。
    """
    token = _TRUSTED_IDENTITY.set((int(tenant_id or 0), int(user_id or 0)))
    try:
        yield
    finally:
        _TRUSTED_IDENTITY.reset(token)


def _resolve_identity(tenant_id: int | None, user_id: int | None) -> tuple[int, int]:
    """MCP 客户端自定义 Body 字段硬编码 (tenant_id=1, user_id=1)，但 ai-builder
    用户多租户多账号，直接用这俩调内部 API 会跨租户错位（看不到当前用户的应用）。

    从 current_app 反查真实身份覆盖；找不到才用 外部 agent 传的兜底。

    例外：可信进程内入口已用 trusted_identity() 标记（unified ai-chat / 配置助手 /
    admin 测试台），其 tenant_id/user_id 直接来自当前登录 JWT，直接采信、不被 slot
    覆盖——修复 unified 路径“session 带着正确租户却被进程内 slot 顶成别的租户”的串租户 bug。
    """
    trusted = _TRUSTED_IDENTITY.get()
    if trusted is not None:
        t_tid, t_uid = trusted
        if t_uid and t_tid >= 0:
            return int(t_tid), int(t_uid)
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


# ─────────────────────── 应用生命周期工具已拆到 app.mcp_tools.app_lifecycle ───────────────────────


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




# Batch 1 应用部署工具已拆到 app.mcp_tools.app_deployment


# 流程工具已拆到 app.mcp_tools.process_tools


# 部署历史/回滚工具已拆到 app.mcp_tools.app_deployment


async def _with_client(env_id: int, op: str, fn):
    """统一桥接：按 env_id 拿 apaas_client → 调 fn(client) → 异常包装。

    2026-05-26 (PR3 reviewer P1 #1): 识别 NotImplementedAPaaSError 类型化异常,
    给前端返 error_code=NOT_IMPLEMENTED 让 UI 走友好降级 (替代原字符串子串匹配).
    """
    from app.coding.apaas_tools import call_apaas_with_relogin
    from app.database import AsyncSessionLocal
    from app.apaas_client import NotImplementedAPaaSError
    async with AsyncSessionLocal() as db:
        try:
            # 2026-05-29: 委托 call_apaas_with_relogin — 拿 client + 调 fn, token 过期(401)
            # 自动重登重试。NotImplementedAPaaSError / 其它异常会原样抛出, 下方 except 照常处理。
            return True, await call_apaas_with_relogin(env_id, db, fn)
        except NotImplementedAPaaSError as exc:
            return False, {
                "ok": False, "error_code": "NOT_IMPLEMENTED",
                "message": f"{op}失败：平台无对应接口 ({exc.endpoint})",
                "endpoint": exc.endpoint, "http_status": exc.http_status,
                "env_id": env_id,
            }
        except Exception as exc:
            return False, {
                "ok": False, "error_code": "APAAS_CALL_FAILED",
                "message": f"{op}失败：{exc}", "env_id": env_id,
            }




# 自开发 workspace 管理工具已拆到 app.mcp_tools.app_deployment


# aPaaS 直接配置工具已拆到 app.mcp_tools.apaas_direct_tools


# ─────────────────────── Split tool modules ───────────────────────


from app.mcp_tools.config_skills import register as _register_config_skill_tools
from app.mcp_tools.apaas_app_basics import register as _register_apaas_app_basic_tools
from app.mcp_tools.apaas_config_crud import register as _register_apaas_config_crud_tools
from app.mcp_tools.apaas_direct_tools import (
    _build_perm_payload_from_simple_rules,
    _form_perms_to_rules,
    _invalidate_section_cache_after_write,
    _post_configure_feature_form_quality,
    register as _register_apaas_direct_tools,
)
from app.mcp_tools.app_lifecycle import (
    _consume_requirements_doc,
    _do_validate_builder_doc,
    _load_artifact_content,
    _peek_requirements_doc,
    register as _register_app_lifecycle_tools,
)
from app.mcp_tools.app_deployment import (
    _resolve_workspace_path,
    register as _register_app_deployment_tools,
)
from app.mcp_tools.backend_workspace import register as _register_backend_workspace_tools
from app.mcp_tools.business_events import register as _register_business_event_tools
from app.mcp_tools.app_health_tool import register as _register_app_health_tools
from app.mcp_tools.form_components import (
    _apply_form_component_updates,
    _build_component_behavior_updates,
    _component_snapshot,
    _find_form_component,
    _normalize_select_component_options,
    _validate_component_default_value,
    register as _register_form_component_tools,
)
from app.mcp_tools.issue_assistant import register as _register_issue_assistant_tools
from app.mcp_tools.process_tools import (
    _cached_list_processes,
    _find_process_transition_edge,
    _load_process_role_labels,
    _normalize_apaas_process_edge,
    _resolve_process_binding_from_raw,
    register as _register_process_tools,
)
from app.mcp_tools.self_dev_assets import (
    _normalize_apaas_user_summary,
    register as _register_self_dev_asset_tools,
)
from app.mcp_tools.workspace_core import register as _register_workspace_core_tools
from app.mcp_tools.skill_authoring import register as _register_skill_authoring_tools

_app_lifecycle_tools = _register_app_lifecycle_tools(
    mcp,
    lambda tenant_id, user_id: _resolve_identity(tenant_id, user_id),
    lambda method, path, **kwargs: _api_call(method, path, **kwargs),
    lambda method, path, **kwargs: _api_call_sse_collect(method, path, **kwargs),
    lambda app_id, user_id: _resolve_app_id(app_id, user_id),
    lambda app_id: _build_app_view_url(app_id),
    lambda name, args, env_id: _call_apaas_platform_tool(name, args, env_id),
)
parse_design_doc = _app_lifecycle_tools["parse_design_doc"]
list_platform_envs = _app_lifecycle_tools["list_platform_envs"]
generate_app_from_doc = _app_lifecycle_tools["generate_app_from_doc"]
list_my_applications = _app_lifecycle_tools["list_my_applications"]
get_application = _app_lifecycle_tools["get_application"]
update_app_from_doc = _app_lifecycle_tools["update_app_from_doc"]
get_change_plan = _app_lifecycle_tools["get_change_plan"]
execute_change_plan = _app_lifecycle_tools["execute_change_plan"]
publish_application = _app_lifecycle_tools["publish_application"]
validate_builder_doc = _app_lifecycle_tools["validate_builder_doc"]
submit_design_doc = _app_lifecycle_tools["submit_design_doc"]

_register_config_skill_tools(mcp, _resolve_identity)
_apaas_app_basic_tools = _register_apaas_app_basic_tools(
    mcp,
    lambda name, args, env_id: _call_apaas_platform_tool(name, args, env_id),
    lambda env_id, op, fn: _with_client(env_id, op, fn),
)
list_apaas_apps_in_env = _apaas_app_basic_tools["list_apaas_apps_in_env"]
list_apaas_app_menus = _apaas_app_basic_tools["list_apaas_app_menus"]
list_apaas_form_views = _apaas_app_basic_tools["list_apaas_form_views"]
list_apaas_form_components = _apaas_app_basic_tools["list_apaas_form_components"]
list_apaas_app_models = _apaas_app_basic_tools["list_apaas_app_models"]
list_apaas_app_dicts = _apaas_app_basic_tools["list_apaas_app_dicts"]
get_apaas_app_overview = _apaas_app_basic_tools["get_apaas_app_overview"]
update_apaas_app_info = _apaas_app_basic_tools["update_apaas_app_info"]
list_apaas_models_in_env = _apaas_app_basic_tools["list_apaas_models_in_env"]
check_app_code_conflict = _apaas_app_basic_tools["check_app_code_conflict"]
get_apaas_doc_template_spec = _apaas_app_basic_tools["get_apaas_doc_template_spec"]
validate_apaas_builder_doc = _apaas_app_basic_tools["validate_apaas_builder_doc"]
_workspace_core_tools = _register_workspace_core_tools(
    mcp,
    _resolve_identity,
    _resolve_workspace_path,
    lambda method, path, **kwargs: _api_call(method, path, **kwargs),
)
list_dev_workspaces = _workspace_core_tools["list_dev_workspaces"]
read_workspace_file = _workspace_core_tools["read_workspace_file"]
write_workspace_files = _workspace_core_tools["write_workspace_files"]
edit_workspace_files = _workspace_core_tools["edit_workspace_files"]
glob_workspace = _workspace_core_tools["glob_workspace"]
grep_workspace = _workspace_core_tools["grep_workspace"]
run_workspace_command = _workspace_core_tools["run_workspace_command"]
get_dev_workspace_status = _workspace_core_tools["get_dev_workspace_status"]
_backend_workspace_tools = _register_backend_workspace_tools(mcp, _resolve_identity, _resolve_workspace_path)
lint_apaas_backend_workspace = _backend_workspace_tools["lint_apaas_backend_workspace"]
_app_deployment_tools = _register_app_deployment_tools(
    mcp,
    lambda tenant_id, user_id: _resolve_identity(tenant_id, user_id),
    lambda method, path, **kwargs: _api_call(method, path, **kwargs),
    lambda method, path, **kwargs: _api_call_sse_collect(method, path, **kwargs),
    lambda user_id, tenant_id, ttl_minutes=15: _sign_service_token(user_id, tenant_id, ttl_minutes),
    lambda env_id, op, fn: _with_client(env_id, op, fn),
    lambda *args, **kwargs: lint_apaas_backend_workspace(*args, **kwargs),
)
deploy_application = _app_deployment_tools["deploy_application"]
list_deploy_records = _app_deployment_tools["list_deploy_records"]
rollback_application = _app_deployment_tools["rollback_application"]
create_dev_workspace = _app_deployment_tools["create_dev_workspace"]
save_dev_spec = _app_deployment_tools["save_dev_spec"]
publish_dev_workspace = _app_deployment_tools["publish_dev_workspace"]
_process_tools = _register_process_tools(
    mcp,
    lambda tenant_id, user_id: _resolve_identity(tenant_id, user_id),
    lambda env_id, op, fn: _with_client(env_id, op, fn),
    lambda env_id, apaas_app_id: _cached_list_processes(env_id, apaas_app_id),
    lambda env_id, apaas_app_id: _load_process_role_labels(env_id, apaas_app_id),
)
list_apaas_app_processes = _process_tools["list_apaas_app_processes"]
get_apaas_process_detail = _process_tools["get_apaas_process_detail"]
set_apaas_process_transition_rules = _process_tools["set_apaas_process_transition_rules"]
deploy_process_to_apaas = _process_tools["deploy_process_to_apaas"]
_apaas_direct_tools = _register_apaas_direct_tools(
    mcp,
    lambda env_id, op, fn: _with_client(env_id, op, fn),
    lambda env_id, apaas_app_id: list_apaas_app_menus(env_id, apaas_app_id),
    lambda env_id, apaas_app_id, with_fields=False: list_apaas_app_models(
        env_id, apaas_app_id, with_fields=with_fields,
    ),
    lambda env_id, apaas_app_id, form_id: list_apaas_form_views(env_id, apaas_app_id, form_id),
    lambda env_id, apaas_app_id, form_id: list_apaas_form_components(env_id, apaas_app_id, form_id),
    lambda env_id, apaas_app_id: list_apaas_app_processes(env_id, apaas_app_id),
    lambda env_id, apaas_app_id, keyword="": list_apaas_app_roles(env_id, apaas_app_id, keyword=keyword),
    lambda env_id, apaas_app_id, form_id, include_raw=False: (
        get_apaas_form_detail(env_id, apaas_app_id, form_id, include_raw=True)
        if include_raw
        else get_apaas_form_detail(env_id, apaas_app_id, form_id)
    ),
    lambda env_id, apaas_app_id, form_id: list_apaas_form_permissions(env_id, apaas_app_id, form_id),
    lambda env_id, apaas_app_id, form_id, form_code, rules: set_apaas_form_permissions(
        env_id, apaas_app_id, form_id, form_code, rules,
    ),
    lambda **kwargs: set_apaas_app_process(**kwargs),
)
list_apaas_app_roles = _apaas_direct_tools["list_apaas_app_roles"]
get_role_resource_matrix = _apaas_direct_tools["get_role_resource_matrix"]
set_role_resource_permission = _apaas_direct_tools["set_role_resource_permission"]
delete_apaas_app_form = _apaas_direct_tools["delete_apaas_app_form"]
list_apaas_form_permissions = _apaas_direct_tools["list_apaas_form_permissions"]
get_apaas_form_detail = _apaas_direct_tools["get_apaas_form_detail"]
repair_empty_apaas_form_from_model = _apaas_direct_tools["repair_empty_apaas_form_from_model"]
set_apaas_form_permissions = _apaas_direct_tools["set_apaas_form_permissions"]
set_apaas_app_access = _apaas_direct_tools["set_apaas_app_access"]
query_apaas_business_data = _apaas_direct_tools["query_apaas_business_data"]
set_apaas_app_process = _apaas_direct_tools["set_apaas_app_process"]
build_apaas_feature_from_spec = _apaas_direct_tools["build_apaas_feature_from_spec"]
_register_issue_assistant_tools(mcp, _resolve_identity)
_self_dev_asset_tools = _register_self_dev_asset_tools(
    mcp,
    lambda env_id, op, fn: _with_client(env_id, op, fn),
    lambda apaas_app_id: _invalidate_section_cache_after_write(apaas_app_id),
)
list_dev_scenes = _self_dev_asset_tools["list_dev_scenes"]
get_dev_scene_spec = _self_dev_asset_tools["get_dev_scene_spec"]
get_dev_scene_full_workflow = _self_dev_asset_tools["get_dev_scene_full_workflow"]
get_apaas_user_name = _self_dev_asset_tools["get_apaas_user_name"]
enable_apaas_self_dev_config = _self_dev_asset_tools["enable_apaas_self_dev_config"]
list_apaas_app_dev_kits = _self_dev_asset_tools["list_apaas_app_dev_kits"]
attach_dev_packages_to_apaas_app = _self_dev_asset_tools["attach_dev_packages_to_apaas_app"]
republish_apaas_app = _self_dev_asset_tools["republish_apaas_app"]
create_apaas_self_dev_menu = _self_dev_asset_tools["create_apaas_self_dev_menu"]
list_apaas_resource_pool_kits = _self_dev_asset_tools["list_apaas_resource_pool_kits"]
upload_external_zip_to_apaas = _self_dev_asset_tools["upload_external_zip_to_apaas"]
_app_health_tools = _register_app_health_tools(mcp)
compute_app_health = _app_health_tools["compute_app_health"]
_apaas_config_crud_tools = _register_apaas_config_crud_tools(
    mcp,
    lambda env_id, op, fn: _with_client(env_id, op, fn),
    lambda apaas_app_id: _invalidate_section_cache_after_write(apaas_app_id),
)
create_apaas_app_roles = _apaas_config_crud_tools["create_apaas_app_roles"]
update_apaas_app_role = _apaas_config_crud_tools["update_apaas_app_role"]
delete_apaas_app_role = _apaas_config_crud_tools["delete_apaas_app_role"]
create_apaas_app_dict = _apaas_config_crud_tools["create_apaas_app_dict"]
update_apaas_app_dict = _apaas_config_crud_tools["update_apaas_app_dict"]
add_apaas_dict_option = _apaas_config_crud_tools["add_apaas_dict_option"]
update_apaas_dict_option = _apaas_config_crud_tools["update_apaas_dict_option"]
update_apaas_app_model = _apaas_config_crud_tools["update_apaas_app_model"]
add_apaas_model_field = _apaas_config_crud_tools["add_apaas_model_field"]
update_apaas_model_field = _apaas_config_crud_tools["update_apaas_model_field"]
disable_apaas_model_field = _apaas_config_crud_tools["disable_apaas_model_field"]
create_apaas_form_menu = _apaas_config_crud_tools["create_apaas_form_menu"]
create_apaas_menu_group = _apaas_config_crud_tools["create_apaas_menu_group"]
set_apaas_menu_parent = _apaas_config_crud_tools["set_apaas_menu_parent"]
rename_apaas_menu = _apaas_config_crud_tools["rename_apaas_menu"]
update_apaas_self_dev_menu_link_url = _apaas_config_crud_tools["update_apaas_self_dev_menu_link_url"]
delete_apaas_app_menu = _apaas_config_crud_tools["delete_apaas_app_menu"]
bind_apaas_form_field_to_dict = _apaas_config_crud_tools["bind_apaas_form_field_to_dict"]
disable_apaas_app_dict = _apaas_config_crud_tools["disable_apaas_app_dict"]
disable_apaas_dict_option = _apaas_config_crud_tools["disable_apaas_dict_option"]
_business_event_tools = _register_business_event_tools(
    mcp,
    lambda env_id, op, fn: _with_client(env_id, op, fn),
)
list_apaas_business_events = _business_event_tools["list_apaas_business_events"]
get_apaas_business_event_detail = _business_event_tools["get_apaas_business_event_detail"]
create_apaas_business_event = _business_event_tools["create_apaas_business_event"]
save_apaas_business_event = _business_event_tools["save_apaas_business_event"]
delete_apaas_business_event = _business_event_tools["delete_apaas_business_event"]
list_apaas_form_menus_for_event = _business_event_tools["list_apaas_form_menus_for_event"]
list_apaas_business_events_in_tenant = _business_event_tools["list_apaas_business_events_in_tenant"]
query_apaas_business_event_trees = _business_event_tools["query_apaas_business_event_trees"]
list_apaas_business_event_execution_history = _business_event_tools[
    "list_apaas_business_event_execution_history"
]
create_form_event_with_python_code = _business_event_tools["create_form_event_with_python_code"]
create_time_event_with_python_code = _business_event_tools["create_time_event_with_python_code"]
create_apaas_value_change_assignment_event = _business_event_tools[
    "create_apaas_value_change_assignment_event"
]
_form_component_tools = _register_form_component_tools(
    mcp,
    lambda env_id, op, fn: _with_client(env_id, op, fn),
)
update_apaas_form_component = _form_component_tools["update_apaas_form_component"]
set_apaas_form_component_default = _form_component_tools["set_apaas_form_component_default"]
set_apaas_form_component_behavior = _form_component_tools["set_apaas_form_component_behavior"]
set_apaas_form_component_options = _form_component_tools["set_apaas_form_component_options"]
set_apaas_form_component_document_number_rules = _form_component_tools[
    "set_apaas_form_component_document_number_rules"
]
set_apaas_form_component_validation = _form_component_tools["set_apaas_form_component_validation"]
set_apaas_form_component_style = _form_component_tools["set_apaas_form_component_style"]
_register_skill_authoring_tools(mcp)


# ─────────────────────── Runtime drift detection (SPEC v2 PR1 round2-p2 #4) ───────────────────────


def _assert_yaml_vs_registered_tools() -> tuple[set[str], set[str]]:
    """启动时比 tool_registry.yaml 全量 vs FastMCP 实际 @mcp.tool() 注册的工具.

    PR1 reviewer #4 留: yaml 跟源码 AST 一致 (test_yaml_matches_mcp_server_source)
    只是静态对比, 真正跑起来 FastMCP 注册的工具集 (mcp._tool_manager._tools) 才是
    实际暴露的 set — 比如 @mcp.tool() 装饰但函数被 try-except import 包住静默
    失败, AST 对比看不出, runtime 才能发现.

    返回 (only_in_yaml, only_in_registered) 用于测试 assert. 任一非空 log warning,
    **不 raise** 避免阻断进程启动 — 真有 drift 通过日志看到比硬 fail-fast 安全
    (生产突然挂比少几个工具风险大).
    """
    from app.tool_registry import all_tool_names as _yaml_tool_names

    yaml_tools = _yaml_tool_names()
    try:
        registered_tools = {t.name for t in mcp._tool_manager.list_tools()}
    except AttributeError:
        # FastMCP 内部结构若升级, 用 fallback (不挡启动)
        logger.warning(
            "[tool-registry drift] FastMCP._tool_manager 不可访问, 跳过 runtime drift check"
        )
        return (set(), set())

    only_yaml = yaml_tools - registered_tools
    only_registered = registered_tools - yaml_tools

    if only_yaml:
        logger.warning(
            "[tool-registry drift] yaml 列了但 FastMCP 未注册的工具 (%d): %s — "
            "(yaml 多余 entry 或源码 @mcp.tool() 装饰失败)",
            len(only_yaml),
            sorted(only_yaml),
        )
    if only_registered:
        logger.warning(
            "[tool-registry drift] FastMCP 注册了但 yaml 缺 entry 的工具 (%d): %s — "
            "(请在 backend/tool_registry.yaml 补 entry)",
            len(only_registered),
            sorted(only_registered),
        )
    if not only_yaml and not only_registered:
        logger.info(
            "[tool-registry drift] OK — yaml %d tools == FastMCP %d registered",
            len(yaml_tools),
            len(registered_tools),
        )
    return (only_yaml, only_registered)


# 模块 import 时跑一次 drift check — 这时所有 @mcp.tool() 装饰都已执行
_assert_yaml_vs_registered_tools()
