"""AI-Builder MCP Server — 把应用领域能力封装成 MCP 工具暴露给得小帆等 agent 平台。

设计：
- FastMCP 实例 mount 到主 FastAPI 进程的 /api/mcp/sse 子路径，复用同进程 HTTP 服务
- 每个工具内部用临时 service JWT 调本机现有 HTTP API（不复制业务逻辑）
- SSE 流式 endpoint 用 httpx 自己 consume 到 done 事件再返回，对调用方表现为同步
- 鉴权：MCP server 自身要 Bearer API key（防外网随便调）；
  实际操作的租户/用户身份通过得小帆"自定义 Body 字段"配置注入，每个 tool 形参带 _tenant_id / _user_id

环境变量：
- MCP_API_KEYS: 逗号分隔的合法 Bearer token（dolphin 配置里填其中一个）
- MCP_INTERNAL_BASE: 内部回环 base URL，默认 http://127.0.0.1:${PORT}/api
"""
from __future__ import annotations

import json
import logging
import os
import re
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
    raw_values = [
        (os.getenv("MCP_API_KEYS") or "").strip(),
        (os.getenv("MCP_API_KEY") or "").strip(),
    ]
    keys: set[str] = set()
    for raw in raw_values:
        if not raw:
            continue
        keys.update(k.strip() for k in raw.split(",") if k.strip())
    return keys


_INTERNAL_BASE = os.getenv("MCP_INTERNAL_BASE", f"http://127.0.0.1:{settings.port}/api")
_API_KEYS = _load_api_keys()
_MCP_SERVICE_USER_ID_RAW = (os.getenv("MCP_SERVICE_USER_ID") or "").strip()


def is_valid_api_key(key: str | None) -> bool:
    """供 main.py 在 SSE handshake middleware 里调用。空 keys 配置时拒绝所有请求。"""
    if not _API_KEYS:
        return False
    if not key:
        return False
    return key in _API_KEYS


# ─────────────────────── 内部 HTTP 调用 helper ───────────────────────


def _sign_service_token(user_id: int, tenant_id: int, ttl_minutes: int = 15) -> str:
    """签一个短期 JWT 给内部 endpoint 用。"""
    from app.auth import create_mcp_service_token
    return create_mcp_service_token(user_id, tenant_id, ttl_minutes=ttl_minutes)


class IdentityRequiredError(RuntimeError):
    """MCP 调用方未提供 user_id 时抛出，让 fastmcp 把异常 message 转成 ToolResult.isError。"""
    pass


# 不再 silent fallback admin。失败时 raise 让上层（fastmcp 框架）转成结构化错误返给 agent。
_IDENTITY_REQUIRED_MSG = (
    "无法识别 MCP 调用方身份（缺少当前对话用户身份）。\n"
    "可能原因：\n"
    "  1. MCP 请求没带 ai-builder JWT / X-AiBuilder-Token / dolphin user-token\n"
    "  2. 当前 dolphin chat 会话还没注入用户身份上下文（用户没进过 ai-builder 触发 init-session-context）\n"
    "解决方案：\n"
    "  - 用户：刷新 ai-builder /ai-copilot 或 /ai-coding 页面让 backend 重新注入用户身份上下文\n"
    "  - dolphin agent：必须透传当前对话人的身份头，不能只传平台 key\n"
    "  - 未识别到当前用户时，本地已禁止回退到环境账号或 admin 账号"
)


async def _resolve_alias_tid_for_env(env_id: int) -> int:
    """alias 模式下，用 env_id 反查 platform_envs.tenant_id 当 tid。

    跟 `_resolve_alias_tid_for_app` 配套（应用维度 vs 环境维度）。

    背景（2026-05-11 实测）：publish_dev_workspace alias 模式 caller 传 env_id=22
    （宝洁环境），但 tid/uid 走 _resolve_identity 兜底 admin (1,1)，调内部
    /coding/workspace/{ws_id}/upload-to-platform 时 ctx.tenant_id=1 校验
    env_id=22 不属于 admin → 403 "无权访问该平台环境"。

    修法：env_id 已经定了，apaas 环境属于哪个 tenant 就用哪个。
    uid 仍 admin (1) — platform_admin 跨 tenant 任意进 get_auth_context。
    """
    if not env_id or env_id <= 0:
        return 1
    try:
        from app.database import AsyncSessionLocal
        from app.models import PlatformEnv
        from sqlalchemy import select as _select
        async with AsyncSessionLocal() as _db:
            row = (
                await _db.execute(_select(PlatformEnv).where(PlatformEnv.id == env_id))
            ).scalar_one_or_none()
            if row and row.tenant_id:
                return int(row.tenant_id)
    except Exception as exc:
        logger.warning(
            "_resolve_alias_tid_for_env env_id=%s 反查 platform_envs 失败: %s（fallback admin tid=1）",
            env_id, exc,
        )
    return 1


async def _resolve_alias_tid_for_app(app_id: int) -> int:
    """alias 模式下，用 app_id 反查 applications.tenant_id 当 tid（最权威）。

    背景（2026-05-11 实测）：alias 模式工具老硬编码 `tid, uid = 1, 1`，
    但用户改 1:1:1 后，alias='baogong' 创建的应用 tenant_id=2（宝洁），
    然后调 deploy_application(app_id, env='baogong') 内部用 tid=1 调
    /applications/244 → 404（admin tenant 查不到 baogong tenant 的 app）。

    修法：alias 模式下，app_id 已经定了，应用属于哪个 tenant 就用哪个。
    uid 仍用 admin (1) — platform_admin 跨 tenant 任意进 get_auth_context。
    """
    if not app_id or app_id <= 0:
        return 1  # 兜底 admin
    try:
        from app.database import AsyncSessionLocal
        from app.models import Application
        from sqlalchemy import select as _select
        async with AsyncSessionLocal() as _db:
            row = (
                await _db.execute(_select(Application).where(Application.id == app_id))
            ).scalar_one_or_none()
            if row and row.tenant_id:
                return int(row.tenant_id)
    except Exception as exc:
        logger.warning(
            "_resolve_alias_tid_for_app app_id=%s 反查 application 失败: %s（fallback admin tid=1）",
            app_id, exc,
        )
    return 1


async def _resolve_identity(tenant_id: int | None, user_id: int | None) -> tuple[int, int]:
    """从 caller 传入的 user_id 反查真实身份。

    🆕 2026-05-10 Phase 3 · MCP 入口 ContextVar 优先：HTTP middleware
    （_McpAuthMiddleware）从 Authorization Bearer ai-builder JWT 解出 ctx
    装到 mcp_request_ctx ContextVar；本函数第一步读 ContextVar，命中即返。
    老 caller-trusted user_id 参数路径（dolphin SDK 当前透传方式）保留作为
    兜底，每次命中打 deprecation INFO log，便于观测何时可砍。

    🆕 2026-05-10 阶段3 · 跨域身份反查：dolphin SDK 自动透传 aPaaS 大整数 user_id
    （21 位 bigint），ai-builder 本地 User.id 是小整数自增 —— 两个 ID 空间不同，
    旧版 slot 反查永远 miss 后 fallback 用 aPaaS 大整数签 JWT，本地 get_auth_context
    查不到 User → 401。新增 alias cache + DB 反查 User.apaas_user_id 把 aPaaS 大
    整数 → 本地 (uid, tid) 映射好。本函数因此变 async（DB 调用）。

    优先级（严格用户态）：
        0) Phase 3 · ContextVar 命中（middleware 装的 ai-builder JWT ctx）→ 直接返
        1) user_id > 0 + 本地 slot 命中（caller 传了本地小整数）→ 直接返
        2) user_id > 0 + alias cache 命中（apaas 大整数）→ 用本地 (uid, tid) 返
        3) user_id > 0 + DB 反查 User.apaas_user_id 命中 → 写 cache + 返本地 (uid, tid)
        4) 其余情况 → 直接拒绝，不再回退到 caller tenant_id / admin / 环境账号
    """
    # ⓪ Phase 3：HTTP 中间件已经装好了请求级 ctx？（最干净路径，零 caller 信任）
    try:
        from app.mcp_request_ctx import get_mcp_ctx
        rc = get_mcp_ctx()
        if rc and rc.local_user_id > 0:
            logger.info(
                "_resolve_identity[ctxvar] uid=%s tid=%s apaas_uid=%s src=%s",
                rc.local_user_id, rc.local_tenant_id, rc.apaas_user_id, rc.auth_source,
            )
            return int(rc.local_tenant_id), int(rc.local_user_id)
    except Exception:
        pass

    # ① caller 传了真实 user_id：走 v2 stop bleed 严格反查路径
    if user_id and int(user_id) > 0:
        uid = int(user_id)
        from app.routes.current_app import (
            get_current_app_for_user,
            resolve_apaas_user_alias,
            set_apaas_user_alias,
        )

        # 1) slot 反查（per-user，登录时由 ai-builder 主动写入，30min TTL）
        #    caller 直接传本地 User.id 时命中（同域 ai-builder 调用 / 老 prompt 兼容）
        rec = get_current_app_for_user(uid)
        if rec:
            real_uid, real_tid, _, _ = rec
            logger.info(
                "_resolve_identity[slot] uid=%s tid=%s (caller_uid=%s)",
                real_uid, real_tid, uid,
            )
            return int(real_tid), int(real_uid)

        # 2) alias 缓存：apaas_uid → 本地 (uid, tid)。dolphin SDK 透传 aPaaS 大整数
        #    user_id 时走这条；首次 miss 后 DB 反查并回填，后续命中零 DB。
        cached = resolve_apaas_user_alias(uid)
        if cached:
            local_uid, local_tid = cached
            logger.info(
                "_resolve_identity[alias] apaas_uid=%s → uid=%s tid=%s",
                uid, local_uid, local_tid,
            )
            return int(local_tid), int(local_uid)

        # 3) DB 反查 User.apaas_user_id —— 跨域 dolphin chat 的核心断链修复点
        try:
            from app.database import AsyncSessionLocal
            from app.models import User
            from app.models.tenant import UserTenant
            from sqlalchemy import select as _select

            async with AsyncSessionLocal() as _db:
                u_res = await _db.execute(
                    _select(User).where(User.apaas_user_id == str(uid))
                )
                u = u_res.scalar_one_or_none()
                if u and u.is_active:
                    # 默认 tenant：is_default desc + joined_at asc，跟 deps.py
                    # resolve_default_tenant_id_for_user 一致
                    ut_res = await _db.execute(
                        _select(UserTenant)
                        .where(
                            UserTenant.user_id == u.id,
                            UserTenant.status == 1,
                        )
                        .order_by(
                            UserTenant.is_default.desc(),
                            UserTenant.joined_at.asc(),
                        )
                    )
                    ut = ut_res.scalars().first()
                    local_tid = int(ut.tenant_id) if ut else 0
                    set_apaas_user_alias(uid, u.id, local_tid)
                    logger.info(
                        "_resolve_identity[db] apaas_uid=%s → uid=%s tid=%s (cache filled)",
                        uid, u.id, local_tid,
                    )
                    return local_tid, int(u.id)
        except Exception as exc:
            logger.warning(
                "_resolve_identity[db] apaas_uid=%s 反查异常: %s", uid, exc
            )

        logger.warning(
            "_resolve_identity strict-mode reject: apaas_uid=%s 无法映射到本地用户",
            uid,
        )
        raise IdentityRequiredError(_IDENTITY_REQUIRED_MSG)

    logger.info("_resolve_identity strict-mode reject: caller 未提供用户身份")
    raise IdentityRequiredError(_IDENTITY_REQUIRED_MSG)


def _resolve_app_id(app_id: int | None, user_id: int) -> tuple[int, str]:
    """工具收到 app_id=None 时，从 current_app 模块拿用户当前编辑的应用。
    返回 (app_id, app_name)。"""
    if app_id and app_id > 0:
        return int(app_id), ""
    if not user_id or int(user_id) <= 0:
        raise IdentityRequiredError(_IDENTITY_REQUIRED_MSG)
    from app.routes.current_app import get_current_app_for_user
    rec = get_current_app_for_user(int(user_id))
    if not rec:
        raise ValueError(
            "未指定 app_id，且后端没有用户当前编辑应用的状态。"
            "请告诉助手具体的应用 ID（数字），或先在 ai-builder UI 打开某个应用。"
        )
    _, _, real_app_id, real_app_name = rec
    if not real_app_id:
        raise ValueError(
            "用户已登录但没在 ai-builder UI 打开过具体应用。"
            "请告诉助手具体的应用 ID（数字），或先去 /apps 页面打开某个应用。"
        )
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
    token_retry_app_id: int | None = None,
    token_retry_env_id: int | None = None,
) -> Any:
    """调本机内部 endpoint。普通 JSON 接口直接返；SSE 由 _api_call_sse 处理。

    token_retry_app_id / token_retry_env_id：传任一时，遇到响应中含 "Token已过期"
    类文案会自动调 platform-envs/{env_id}/login 刷 token + 重试一次原请求。让 MCP
    agent 不感知 token 过期（无需让用户去环境管理手动登录）。app_id 优先；只传
    env_id 时跳过 app→env 反查（generate_app_from_doc 的 auto-create 用）。
    """
    async def _once() -> Any:
        token = _sign_service_token(user_id, tenant_id)
        headers = {"Authorization": f"Bearer {token}"}
        from app.mcp_request_ctx import get_mcp_ctx
        ctx = get_mcp_ctx()
        if ctx and ctx.apaas_token and ctx.apaas_tenant_id:
            headers["X-APaaS-Token"] = ctx.apaas_token
            headers["X-APaaS-Tenant-Id"] = ctx.apaas_tenant_id
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
        if (
            (token_retry_app_id or token_retry_env_id)
            and is_apaas_token_error(str(exc))
            and await _refresh_platform_env_token(
                app_id=token_retry_app_id,
                env_id=token_retry_env_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        ):
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

    token_retry_app_id / token_retry_env_id：见 _api_call 同名参数。SSE 路径下
    token 过期通常体现为 errors 数组里的"APaaS平台Token已过期"文案；本函数检测到
    后自动刷 token 并整段 stream 重新执行（events 清空重收）。重试只发生一次，
    第二次仍 token 错误会原样把 errors 返回（一般是密码也错了或环境配置丢失）。
    """
    async def _once() -> dict:
        token = _sign_service_token(user_id, tenant_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
        from app.mcp_request_ctx import get_mcp_ctx
        ctx = get_mcp_ctx()
        if ctx and ctx.apaas_token and ctx.apaas_tenant_id:
            headers["X-APaaS-Token"] = ctx.apaas_token
            headers["X-APaaS-Tenant-Id"] = ctx.apaas_tenant_id
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
        refreshed = await _refresh_platform_env_token(
            app_id=token_retry_app_id,
            env_id=token_retry_env_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if refreshed:
            logger.info("MCP token 自愈后重试 SSE %s %s", method, path)
            result = await _once()
            result["_token_auto_refreshed"] = True
    return result


def _ai_builder_ui_url(path: str) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    base = (settings.ai_builder_chat_deeplink_base or "http://127.0.0.1:5173/ai-builder").rstrip("/")
    if base.endswith("/ai-builder") and normalized.startswith("/ai-builder/"):
        normalized = normalized[len("/ai-builder"):]
    if not base.endswith("/ai-builder") and not normalized.startswith("/ai-builder/"):
        normalized = f"/ai-builder{normalized}"
    return f"{base}{normalized}"


_PLATFORM_ENVS_URL = _ai_builder_ui_url("/platform-envs?tab=envs")


def _business_error(
    *,
    op: str,
    error_text: str,
    app_id: int | None = None,
    extra: dict | None = None,
) -> dict:
    """把业务错误转成结构化 dict 返回（取代 raise RuntimeError）。

    fastmcp 把 raise 包成 "Error executing tool xxx: ..." 字符串塞进 isError=True 的
    content，agent 容易把它当作"框架级错误"进入排查/重试模式而不是直接展示给用户。
    改成 return ok:false dict（isError=false 工具调用本身成功）后，agent 必须读
    error_code / message / user_action_required 字段，不会被 fastmcp 包装层模糊掉细节。

    分类规则（命中先后顺序）：
    - APAAS_TOKEN_EXPIRED_AND_REFRESH_FAILED：自愈兜不住的 token 过期
    - APAAS_APP_CODE_CONFLICT：应用编码已被占用
    - APAAS_PROCESS_FIELD_CONFLICT：approver_id / approval_* 等流程模块字段冲突
    - APAAS_FIELD_RESERVED：字段编码命中平台保留字
    - BUSINESS_ERROR：兜底
    """
    text = (error_text or "").strip()
    base: dict = {"ok": False, "op": op, "message": text}
    if app_id is not None:
        base["app_id"] = int(app_id)
    if extra:
        base.update(extra)

    if is_apaas_token_error(text):
        base.update({
            "error_code": "APAAS_TOKEN_EXPIRED_AND_REFRESH_FAILED",
            "user_action_required": (
                "APaaS 平台 Token 失效且自动刷新失败。多半是该环境的密码已变更或被平台禁用，"
                "用户必须去环境管理重新登录该环境（输密码），然后再触发本工具。"
            ),
            "action_url": _PLATFORM_ENVS_URL,
            "should_retry": False,
        })
        return base

    if "应用编码重复" in text or "应用编码已存在" in text or "应用编码已被使用" in text:
        base.update({
            "error_code": "APAAS_APP_CODE_CONFLICT",
            "user_action_required": (
                "应用编码已被同环境下其他应用占用。请先调 list_apaas_apps_in_env 查看占用情况，"
                "然后跟用户确认：[更新已有应用]（改用 update_app_from_doc 走变更计划）"
                "还是 [改个新编码再创建]（在设计文档第一章「应用信息」改 app_code 后重新调）。"
                "禁止自动换环境或自行加 _v1 后缀重试。"
            ),
            "should_retry": False,
        })
        return base

    if any(k in text for k in ("approver_", "approval_", "applicant_")):
        base.update({
            "error_code": "APAAS_PROCESS_FIELD_CONFLICT",
            "user_action_required": (
                "数据模型字段命中 apaas 平台流程模块保留字（approver_id / approval_status 等）。"
                "这些字段由平台流程节点自动注入和管理，不要在业务模型里设计。请改设计文档第四章"
                "从相关表删除这些字段，审批流程改用自然语言描述（哪几级审批、谁审批、通过/驳回后怎么样）。"
            ),
            "should_retry": False,
        })
        return base

    if "字段编码与数据库关键字重复" in text or "保留字" in text or "数据库关键字" in text:
        base.update({
            "error_code": "APAAS_FIELD_RESERVED",
            "user_action_required": (
                "数据模型有字段命中 apaas 平台保留字（如 status / type / date / order 等通用短名）。"
                "把这条 message 原文展示给用户 + 在 backend.log 拿到具体冲突 fieldCode，然后改设计文档"
                "第四章给冲突字段加业务前缀（如 hedge_status 而不是 status）。禁止自动改字段名重试。"
            ),
            "should_retry": False,
        })
        return base

    base.update({
        "error_code": "BUSINESS_ERROR",
        "user_action_required": (
            "把上面 message 字段的错误信息原文展示给用户，让用户决定下一步。"
            "禁止自动换环境/改字段/换 app_code 重试——业务错误跨环境同样会失败。"
        ),
        "should_retry": False,
    })
    return base


async def _refresh_platform_env_token(
    *,
    app_id: int | None = None,
    env_id: int | None = None,
    tenant_id: int,
    user_id: int,
) -> bool:
    """MCP token 过期自愈：调 internal /platform-envs/{env_id}/login 刷新存库 token。

    传 app_id（推荐）：先 GET /applications/{app_id} 反查 platform_env_id；
    传 env_id：直接刷指定环境（generate_app_from_doc 没 app_id 时用）；
    两者都传则 app_id 优先。

    返回 True 表示新 token 已写回 DB（外层可重试原请求）；False 表示自愈失败
    （应用没绑环境 / 环境没保 username+password / apaas 拒登 等），调用方应让
    原错误冒泡给 agent，由 agent 提示用户去环境管理手动处理。

    内部调的两个 endpoint（GET /applications/{id} 和 POST /platform-envs/{env}/login）
    都不触发 apaas 平台调用，不会再次撞 token 过期，无递归风险。
    """
    if env_id is None and app_id is not None:
        try:
            app_data = await _api_call(
                "GET",
                f"/applications/{app_id}",
                tenant_id=tenant_id,
                user_id=user_id,
            )
            env_id = (app_data or {}).get("platform_env_id")
        except Exception as exc:
            logger.warning(
                "MCP token 自愈：从 app=%s 反查 env_id 失败：%s", app_id, exc
            )
            return False
    if not env_id:
        return False
    try:
        result = await _api_call(
            "POST",
            f"/platform-envs/{env_id}/login",
            tenant_id=tenant_id,
            user_id=user_id,
        )
        ok = bool((result or {}).get("ok"))
        if ok:
            logger.info("MCP token 自愈成功 env=%s", env_id)
        else:
            logger.warning("MCP token 自愈调 login 返回 ok=false: %s", result)
        return ok
    except Exception as exc:
        logger.warning("MCP token 自愈：调 env=%s login 失败：%s", env_id, exc)
        return False


async def _with_apaas_client(
    env_id: int,
    *,
    tenant_id: int,
    user_id: int,
    op: str,
    fn,
) -> tuple[bool, Any]:
    """统一封装 PlatformEnv 查询 → APaaSClient 实例化 → 调用 + 一次 token 自愈重试。

    fn: async (client: APaaSClient) -> Any。失败返回 (False, business_error_dict)，
    成功返回 (True, fn_result)。配套的 env 元信息也注入返回 dict 便于查重工具用。

    自愈逻辑：第一次调用抛 token 错误时自动调 _refresh_platform_env_token + 用新 token
    重新实例化 APaaSClient + 重试一次。第二次仍失败按业务错返回。
    """
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv
    from app.apaas_client import APaaSClient
    from sqlalchemy import select

    async def _load_env() -> PlatformEnv | None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.id == env_id,
                    PlatformEnv.tenant_id == tenant_id,
                )
            )
            return result.scalar_one_or_none()

    env = await _load_env()
    if not env:
        return False, _business_error(
            op=op,
            error_text=f"环境 {env_id} 不存在或不属于当前租户",
            extra={"env_id": env_id},
        )
    if not env.token:
        refreshed = await _refresh_platform_env_token(
            env_id=env_id, tenant_id=tenant_id, user_id=user_id,
        )
        if refreshed:
            env = await _load_env()
        if not env or not env.token:
            return False, _business_error(
                op=op,
                error_text="环境未连接，且自动使用账号密码登录失败",
                extra={"env_id": env_id, "env_name": getattr(env, "env_name", None)},
            )

    async def _try(token: str):
        client = APaaSClient(
            base_url=env.base_url,
            tenant_id=env.platform_tenant_id,
            token=token,
        )
        return await fn(client)

    try:
        return True, await _try(env.token)
    except Exception as exc:
        text = str(exc)
        if not (is_apaas_token_error(text) or "401" in text or "Unauthorized" in text):
            return False, _business_error(
                op=op, error_text=text,
                extra={"env_id": env_id, "env_name": env.env_name},
            )

    # token 自愈
    refreshed = await _refresh_platform_env_token(
        env_id=env_id, tenant_id=tenant_id, user_id=user_id,
    )
    if not refreshed:
        return False, _business_error(
            op=op,
            error_text="token 过期且自动刷新失败",
            extra={"env_id": env_id, "env_name": env.env_name},
        )
    env_after = await _load_env()
    if not env_after or not env_after.token:
        return False, _business_error(
            op=op, error_text="自愈后回查环境失败",
            extra={"env_id": env_id},
        )
    try:
        return True, await _try(env_after.token)
    except Exception as exc2:
        return False, _business_error(
            op=op, error_text=str(exc2),
            extra={"env_id": env_id, "env_name": env.env_name},
        )


def _current_apaas_base_url() -> str:
    """当前部署绑定的 aPaaS 平台地址。

    MCP 管理台允许在 config/mcp_platform.json 中配置实际接入平台；测试台获取
    aPaaS 用户 token 也走这份配置。工具调用必须使用同一个 base_url，否则 token
    会在另一个平台上 401。
    """
    try:
        from app.routes.mcp_platform import _api_base, _load_config, _select_admin
        data = _load_config()
        row = _select_admin(data)
        base_url = _api_base(row.get("base_url") or "")
        if base_url:
            return base_url.rstrip("/")
    except Exception:
        pass
    raw = (os.getenv("APAAS_BASE_URL") or settings.apaas_base_url or "").rstrip("/")
    if raw and not raw.endswith("/backend"):
        raw = f"{raw}/backend"
    return raw


async def _with_current_apaas_client(*, op: str, fn) -> tuple[bool, Any]:
    """使用当前 MCP 身份对应的 aPaaS 用户 token + tenantId 调平台.

    优先级：
    1. 请求 Header 显式传入 X-APaaS-Token / X-APaaS-Tenant-Id
    2. AI Builder JWT 对应 User 行中保存的 apaas_token / apaas_tenant_id
    """
    from app.apaas_client import APaaSClient
    from app.mcp_request_ctx import get_mcp_ctx

    ctx = get_mcp_ctx()
    apaas_token = (ctx.apaas_token or "").strip() if ctx else ""
    apaas_tenant_id = (ctx.apaas_tenant_id or "").strip() if ctx else ""
    base_url = _current_apaas_base_url()

    if ctx and not (apaas_token and apaas_tenant_id) and ctx.local_tenant_id:
        env_id = await _default_platform_env_id_for_identity(int(ctx.local_tenant_id))
        if env_id:
            return await _with_apaas_client(
                env_id,
                tenant_id=int(ctx.local_tenant_id),
                user_id=int(ctx.local_user_id or 1),
                op=op,
                fn=fn,
            )
        return False, _business_error(
            op=op,
            error_text="当前租户未绑定可用 aPaaS 平台环境",
            extra={"tenant_id": int(ctx.local_tenant_id)},
        )

    if ctx and not apaas_token and ctx.local_user_id:
        try:
            from app.database import AsyncSessionLocal
            from app.models import User
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                user = (
                    await db.execute(select(User).where(User.id == int(ctx.local_user_id)))
                ).scalar_one_or_none()
            if user:
                apaas_token = (user.apaas_token or "").strip()
                apaas_tenant_id = apaas_tenant_id or (user.apaas_tenant_id or "").strip()
                user_base = (user.apaas_base_url or "").strip()
                if user_base:
                    base_url = user_base.rstrip("/")
                    if not base_url.endswith("/backend"):
                        base_url = f"{base_url}/backend"
        except Exception as exc:
            logger.warning("读取当前用户 aPaaS token 失败 uid=%s: %s", ctx.local_user_id, exc)

    if not apaas_token or not apaas_tenant_id:
        return False, _business_error(
            op=op,
            error_text=(
                "缺少 aPaaS 用户身份：请求 Header 未传 X-APaaS-Token/X-APaaS-Tenant-Id，"
                "且当前 AI Builder 用户未保存 apaas_token/apaas_tenant_id"
            ),
        )

    if not base_url:
        return False, _business_error(op=op, error_text="缺少 APAAS_BASE_URL / settings.apaas_base_url 配置")

    client = APaaSClient(
        base_url=base_url,
        tenant_id=apaas_tenant_id,
        token=apaas_token,
    )
    try:
        return True, await fn(client)
    except Exception as exc:
        return False, _business_error(op=op, error_text=str(exc))


def _format_apaas_app_list(payload) -> list[dict]:
    apps: list[dict] = []
    for a in payload or []:
        if not isinstance(a, dict):
            continue
        apps.append({
            "apaas_app_id": str(a.get("id", a.get("appId", ""))),
            "app_code": str(a.get("appCode", a.get("code", "")) or ""),
            "app_name": str(a.get("appName", a.get("name", "")) or ""),
            "description": str(a.get("description", a.get("appDescription", "")) or ""),
            "status": str(a.get("status", "") or ""),
            "web_url": str(a.get("accessUrl", "") or ""),
            "mobile_url": str(a.get("accessMobileUrl", "") or ""),
            "backend_url": str(a.get("backendUrl", "") or ""),
            "tenant_code": str(a.get("tenantCode", "") or ""),
            "current_version": str(a.get("currentVersion", "") or ""),
        })
    return apps


async def _default_platform_env_id_for_identity(tenant_id: int) -> int:
    """Pick the tenant's default connected env; fall back to the only connected env."""
    if not tenant_id:
        return 0
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformEnv)
            .where(
                PlatformEnv.tenant_id == tenant_id,
                PlatformEnv.status == "connected",
            )
            .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
        )
        envs = result.scalars().all()
    if not envs:
        return 0
    default_env = next((env for env in envs if env.is_default), None)
    return int((default_env or envs[0]).id)


async def _current_platform_env_id_for_header_identity() -> int:
    """兼容仍依赖 platform_env_id 的内部上传接口：按当前唯一 base_url + Header tenantId 反查。"""
    env = await _current_platform_env_for_header_identity()
    return int(env.id) if env else 0


async def _current_platform_env_for_header_identity():
    """按 Header aPaaS tenant 反查已绑定的 platform_envs 行。

    MCP 新链路只信任 aPaaS 原生用户 token 做平台操作；AI Builder 内部落库只需要
    找到这个 aPaaS tenant 绑定到哪个本地租户，不能再要求最终用户是本地租户成员。
    """
    from app.database import AsyncSessionLocal
    from app.mcp_request_ctx import get_mcp_ctx
    from app.models import PlatformEnv
    from sqlalchemy import select

    ctx = get_mcp_ctx()
    apaas_tid = (ctx.apaas_tenant_id if ctx else "") or ""
    if not apaas_tid:
        return None
    base_url = _current_apaas_base_url().rstrip("/")
    async with AsyncSessionLocal() as db:
        stmt = select(PlatformEnv).where(PlatformEnv.platform_tenant_id == apaas_tid)
        if base_url:
            stmt = stmt.where(PlatformEnv.base_url == base_url)
        row = (await db.execute(stmt.order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc()))).scalars().first()
        if row:
            return row
        # base_url 配置偶尔带 /backend 或域名规范化差异，按 tenant 再兜底一次。
        row = (await db.execute(
            select(PlatformEnv)
            .where(PlatformEnv.platform_tenant_id == apaas_tid)
            .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
        )).scalars().first()
        return row


async def _resolve_mcp_service_identity_from_header() -> tuple[int, int, int]:
    """Header aPaaS 身份 → (ai_builder_tenant_id, service_user_id, platform_env_id)."""
    env = await _current_platform_env_for_header_identity()
    if not env:
        from app.mcp_request_ctx import get_mcp_ctx
        ctx = get_mcp_ctx()
        apaas_tid = (ctx.apaas_tenant_id if ctx else "") or ""
        raise IdentityRequiredError(
            "当前 aPaaS tenant 未绑定到 AI Builder platform_envs，无法创建应用。"
            f"请在管理台把 platform_tenant_id={apaas_tid or '<missing>'} 绑定到对应租户环境。"
        )

    from app.database import AsyncSessionLocal
    from app.models import User
    from sqlalchemy import select

    preferred_id = 0
    if _MCP_SERVICE_USER_ID_RAW:
        try:
            preferred_id = int(_MCP_SERVICE_USER_ID_RAW)
        except ValueError:
            logger.warning("MCP_SERVICE_USER_ID=%r 不是整数，忽略", _MCP_SERVICE_USER_ID_RAW)

    async with AsyncSessionLocal() as db:
        user = None
        if preferred_id > 0:
            user = (await db.execute(
                select(User).where(
                    User.id == preferred_id,
                    User.is_active == True,  # noqa: E712
                    User.is_platform_admin == True,  # noqa: E712
                )
            )).scalar_one_or_none()
        if not user:
            user = (await db.execute(
                select(User)
                .where(User.is_active == True, User.is_platform_admin == True)  # noqa: E712
                .order_by(User.id.asc())
            )).scalar_one_or_none()
        if not user:
            raise IdentityRequiredError(
                "缺少可用于 MCP 内部落库的 platform_admin service user。"
                "请创建一个 is_platform_admin=1 的本地用户，或设置 MCP_SERVICE_USER_ID。"
            )

    return int(env.tenant_id), int(user.id), int(env.id)


async def _resolve_internal_identity_for_mcp(
    tenant_id: int = 0,
    user_id: int = 0,
) -> tuple[int, int, int]:
    """优先使用 Header aPaaS 身份桥；没有 Header 时保留老身份解析。"""
    from app.mcp_request_ctx import get_mcp_ctx

    ctx = get_mcp_ctx()
    if ctx and ctx.apaas_token and ctx.apaas_tenant_id:
        return await _resolve_mcp_service_identity_from_header()
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    return tid, uid, 0


# ─────────────────────── 去耦版本：按 alias 调 apaas（阶段1） ───────────────────────
# 用户决策（2026-05-09）：低代码搭建/开发 agent 是独立产品，MCP 工具不该绑死
# ai-builder users/tenants 反查。本节提供新版 _with_apaas_client_by_alias，
# 直接根据 alias 字符串拿凭证调 apaas，不验 ai-builder tenant 归属。
# 老 _with_apaas_client(env_id, tenant_id, user_id) 保留作 deprecated 兼容。


async def _dispatch_env_to_legacy(
    env: str = "",
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> tuple[int, int, int, str | None]:
    """alias 模式 → 老 (env_id, tenant_id, user_id) 三元组的兼容翻译层。

    给 generate_app_from_doc / update_app_from_doc 等"复合工具"（内部走 ai-builder
    internal /applications/* endpoint）用。这些 endpoint 还需要 user_id/tenant_id
    做鉴权 + 写应用 owner，本 helper 在 alias 模式下用系统账号 (1, 1) 兜底，
    应用 owner 都归属 admin。

    返回 (env_id, tenant_id, user_id, alias_or_none)。
    错误：抛 IdentityRequiredError 让 fastmcp 转 ToolResult.isError。
    """
    if env:
        creds = await __import__(
            "app.services.apaas_env_registry", fromlist=["resolve_env_by_alias"]
        ).resolve_env_by_alias(env)
        if not creds:
            raise IdentityRequiredError(
                f"环境别名 '{env}' 不存在。请检查 dolphin agent 全局记忆里的 env 配置"
                "是否与 ai-builder admin 配的 alias 一致。"
            )
        # alias 模式：复合操作归属系统账号（user_id=1=admin），不依赖会话身份注入
        return creds.env_id, 1, 1, env
    if env_id > 0:
        tid, uid = await _resolve_identity(tenant_id, user_id)
        return env_id, tid, uid, None
    raise IdentityRequiredError(
        "必须传 env (alias，推荐) 或 env_id（兼容模式，需 user_id+tenant_id）"
    )


async def _dispatch_apaas_call(
    env: str,
    env_id: int,
    tenant_id: int,
    user_id: int,
    *,
    op: str,
    fn,
) -> tuple[bool, Any]:
    """统一 dispatch：MCP 工具调用 aPaaS 时只信任 Header 中的原生身份。"""
    return await _with_current_apaas_client(op=op, fn=fn)


async def _with_apaas_client_by_alias(
    alias: str,
    *,
    op: str,
    fn,
) -> tuple[bool, Any]:
    """按 alias 查 apaas 凭证 → APaaSClient → 调 + token 自愈。

    去耦版：不接 tenant_id / user_id。alias 是全局唯一 stable key，由 dolphin
    agent 全局记忆固定提供，跨 agent 隔离靠"每 agent 锚定一个 alias"实现。

    fn: async (client: APaaSClient) -> Any。返回 (True, fn_result) 或
    (False, _business_error dict)。
    """
    from app.apaas_client import APaaSClient
    from app.services.apaas_env_registry import (
        refresh_env_token_by_alias,
        resolve_env_by_alias,
    )

    creds = await resolve_env_by_alias(alias)
    if not creds:
        return False, _business_error(
            op=op,
            error_text=(
                f"环境别名 '{alias}' 不存在。请检查 dolphin agent 全局记忆里的 env "
                "配置是否与 ai-builder admin 配的 alias 一致。"
            ),
            extra={"env_alias": alias},
        )
    if not creds.token:
        return False, _business_error(
            op=op,
            error_text=f"环境 '{alias}' ({creds.env_name}) 未连接，请先在 admin 环境管理登录",
            extra={"env_alias": alias, "env_name": creds.env_name},
        )

    async def _try(token: str):
        client = APaaSClient(
            base_url=creds.base_url,
            tenant_id=creds.platform_tenant_id,
            token=token,
        )
        return await fn(client)

    # 第一次尝试
    try:
        return True, await _try(creds.token)
    except Exception as exc:
        text = str(exc)
        if not (is_apaas_token_error(text) or "401" in text or "Unauthorized" in text):
            return False, _business_error(
                op=op, error_text=text,
                extra={"env_alias": alias, "env_name": creds.env_name},
            )

    # token 自愈（用 alias 模式专属的 refresh_env_token_by_alias，
    # 不依赖 ai-builder admin 鉴权）
    refreshed = await refresh_env_token_by_alias(alias)
    if not refreshed:
        return False, _business_error(
            op=op,
            error_text=(
                f"环境 '{alias}' token 过期且自动刷新失败。"
                "请去 ai-builder admin 环境管理手动重连，或检查环境的 username/password 是否正确。"
            ),
            extra={"env_alias": alias, "env_name": creds.env_name},
        )
    creds_after = await resolve_env_by_alias(alias)
    if not creds_after or not creds_after.token:
        return False, _business_error(
            op=op, error_text="自愈后回查环境失败",
            extra={"env_alias": alias},
        )
    try:
        return True, await _try(creds_after.token)
    except Exception as exc2:
        return False, _business_error(
            op=op, error_text=str(exc2),
            extra={"env_alias": alias, "env_name": creds.env_name},
        )


# ─────────────────────── FastMCP 实例 ───────────────────────


# DNS rebinding 保护：默认开启时 allowed_hosts 空会拒所有 Host，必须显式列允许域名。
# MCP_ALLOWED_HOSTS 环境变量逗号分隔；不配则关闭保护（部署在反代后已经有 CSRF/auth 兜底）
_allowed_hosts = [h.strip() for h in (os.getenv("MCP_ALLOWED_HOSTS") or "").split(",") if h.strip()]
if _allowed_hosts:
    _allowed_origins = []
    for _host in _allowed_hosts:
        if "://" in _host:
            _allowed_origins.append(_host.rstrip("/"))
            continue
        _bare_host = _host.split(":", 1)[0]
        if _bare_host in ("localhost", "127.0.0.1", "[::1]"):
            _allowed_origins.extend([f"http://{_host}", f"https://{_host}"])
        else:
            _allowed_origins.extend([f"https://{_host}", f"http://{_host}"])
    _security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
        allowed_origins=sorted(set(_allowed_origins)),
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

# 2026-05-14 曾拆分 builder / coding / vibe 三个 server 以降低单 agent 工具数。
# 2026-05-31 本地镜像改为统一主入口：`/api/mcp/mcp` 暴露全集工具；
# split endpoint 继续保留，仅用于旧外部配置兼容。
mcp_builder = FastMCP(
    "apaas-builder-config",
    instructions=(
        "aPaaS Builder 配置态工具集（draft 工作流 + apaas 应用结构查询/写）。"
        "不含沙箱代码工具；写代码场景请用 apaas-builder-coding。"
    ),
    transport_security=_security,
    stateless_http=True,
    json_response=True,
)
mcp_coding = FastMCP(
    "apaas-builder-coding",
    instructions=(
        "aPaaS Builder 沙箱开发态工具集（workspace 文件/命令 + apaas 只读查询 + 一条龙发布）。"
        "应用配置 / draft 工作流请用 apaas-builder-config；纯预览不发 apaas 用 apaas-builder-vibe。"
    ),
    transport_security=_security,
    stateless_http=True,
    json_response=True,
)
mcp_vibe = FastMCP(
    "apaas-builder-vibe",
    instructions=(
        "独立预览沙箱工具集（docker-based）。给临时 PoC / 不部署 apaas，只想在浏览器跑一下看效果。"
        "做 apaas 二次开发请用 apaas-builder-coding（走 publish_dev_workspace 部署）。"
    ),
    transport_security=_security,
    stateless_http=True,
    json_response=True,
)


# ─────────────────────── 工具实现 ───────────────────────


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def parse_design_doc(
    md_content: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 解析 markdown 设计文档为结构化 preview（不创建应用）。

    ⚠️ 已合并进 save_design_draft —— 新流程**不要再调本工具**。
    调 save_design_draft(md_content) 一次就会自动校验+解析+落库 draft+给预览 URL。

    本工具仅保留作老 agent 兼容入口，函数体不变。
    """
    # 解析操作与具体用户无关，统一用系统账号兜底（避免老 prompt 没传 user_id 时报错）
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    try:
        res = await _api_call("POST", "/applications/upload-doc", tenant_id=1, user_id=1, files=files)
    except RuntimeError as exc:
        # 后端返回 4xx 时 _api_call 会 raise RuntimeError("内部接口 ... 失败 (400): {body}")
        # 把模板格式错从 fastmcp 包装的"工具异常"还原成结构化 dict，让 agent 读到 failed_modules
        return _parse_design_doc_business_error(str(exc), md_content)
    data = res.get("data") if isinstance(res, dict) else None
    return {
        "ok": True,
        "preview": data or res,
        "document_text_length": len(md_content),
    }


def _parse_design_doc_business_error(error_text: str, md_content: str) -> dict:
    """parse_design_doc 失败时把后端错误转成结构化 dict 给 agent。

    后端 docs.py:706 抛 HTTPException(400, "文档解析失败: ...")，doc_pipeline.py:49 的
    DocNotStandardError 字符串里含"以下模块无法纯代码解析：app_info, dicts, ..."。
    本函数解析这两层文案，提供 failed_modules + 当前 validate 诊断给 agent 定向修复。
    """
    text = error_text or ""
    # 解析"以下模块无法纯代码解析：xxx" 里的模块清单
    failed_modules: list[str] = []
    m = re.search(r"无法纯代码解析[：:]\s*([a-z_,\s]+)", text)
    if m:
        failed_modules = [t.strip() for t in m.group(1).split(",") if t.strip()]

    # 顺手跑一遍本地 validate，把诊断信息一起塞给 agent（避免再多一次工具调用）
    try:
        validation = _do_validate_builder_doc(md_content)
    except Exception:
        validation = {}

    if "无法纯代码解析" in text or "文档解析失败" in text or "未按模板规范" in text:
        return {
            "ok": False,
            "op": "parse_design_doc",
            "error_code": "DOC_TEMPLATE_PARSE_FAILED",
            "message": text,
            "failed_modules": failed_modules,
            "validation": validation,
            "user_action_required": (
                "文档没按 aPaaS Builder 标准模板写。failed_modules 里列出的章节解析失败，"
                "几乎都是表头列名 / 章节标题不一致引起。优先按 validation.weak_sections_detail 里的 "
                "missing_required / extra_unused 修表头，再按 validation.missing_sections 补章节，"
                "改完重跑 validate_builder_doc 直到 passes_strict=true，再调本工具。"
                "若不确定标准格式，调 get_doc_template_spec 拿完整 spec。"
            ),
            "should_retry": False,
        }

    # 兜底走通用 business_error 分类
    return _business_error(op="解析设计文档", error_text=text)


def _forbidden_in_alias_mode(tool_name: str, replacement: str) -> dict:
    """alias 模式下被禁用的工具的硬守门——backend 直接返 forbidden 不返数据.

    用户决策（2026-05-10 实测越权）：宝洁 Coding agent (lisa Li) 调
    list_platform_envs(user_id=0, tenant_id=0)，backend _resolve_identity
    兜底 admin → 返 tenant_id=1 (体验租户) 的 14 个 envs，跨租户数据泄漏。

    虽然 prompt v3.1 列了禁用清单，但 dolphin agent 实测漠视 prompt 仍调
    禁用工具——必须 backend 硬守门。
    """
    return {
        "ok": False,
        "op": tool_name,
        "error_code": "TOOL_FORBIDDEN_IN_ALIAS_MODE",
        "message": (
            f"⛔ 工具 {tool_name} 在 alias 模式下被禁用（防止跨租户数据越权）。"
            f"请改用 {replacement}。"
        ),
        "user_action_required": (
            f"换用 {replacement} 完成相同业务目标。"
            "你的 agent 全局记忆里有 env: <alias>，所有应用/模型/表单查询都按这个 alias。"
        ),
        "should_retry": False,
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def list_platform_envs(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """⚠️ DEPRECATED + 禁用：alias 模式下不可用。请改用 list_apaas_apps(env=<alias>).

    历史：本工具曾让 dolphin agent 列租户全部低代码环境。但 alias 模式下每个
    dolphin agent 锚定一个 env alias，agent 全局记忆里有 env: <alias>，无需
    再列出全部环境给用户选——直接调 list_apaas_apps(env=<alias>) 即可。

    硬守门（不返真实数据）：
    用户决策"agent 不该看 ai-builder env 配置 UI"，且实测过 prompt 失效时
    backend 兜底 admin 返 tenant=1 全部 envs 越权 → 必须 backend return forbidden。
    """
    return _forbidden_in_alias_mode(
        "list_platform_envs",
        "list_apaas_apps(env='<你 agent 全局记忆里的 alias>')",
    )

    # 老逻辑保留作为引用（不会执行到这里）
    tid, _uid = await _resolve_identity(tenant_id, user_id)

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
async def list_apaas_apps() -> dict:
    """列出当前租户 aPaaS 应用（含 code / name / id / url）。

    优先使用请求 Header 中的 X-APaaS-Token 和 X-APaaS-Tenant-Id。
    如果当前会话只有 AI Builder 身份，则兜底使用该租户绑定的默认/唯一 connected
    平台环境。若仍无法确定环境，返回空列表并标记 skipped，不阻塞文档草稿保存。

    用途（agent 工作流）：
      - generate_app_from_doc 之前先调本工具，比对设计文档里的 app_code 是否
        已被占用，避免撞"应用编码已存在"报错
      - 用户问"我有哪些应用"时直接调

    返回 { ok, apps: [{apaas_app_id, app_code, app_name, description,
                                       status, web_url, mobile_url, backend_url,
                                       tenant_code, current_version}], total }
    """
    async def _q(client) -> list:
        return await client.query_app_list()

    from app.mcp_request_ctx import get_mcp_ctx
    ctx = get_mcp_ctx()
    source = (
        "apaas_header"
        if ctx and ctx.apaas_token and ctx.apaas_tenant_id
        else "current_tenant_platform_env"
        if ctx and ctx.local_tenant_id
        else "user_apaas_token"
    )
    ok, payload = await _with_current_apaas_client(op="列 aPaaS 应用", fn=_q)
    env_id = 0
    if not ok:
        try:
            tenant_id, user_id, _ = await _resolve_internal_identity_for_mcp()
            env_id = await _default_platform_env_id_for_identity(tenant_id)
            if env_id:
                ok, payload = await _with_apaas_client(
                    env_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    op="列 aPaaS 应用",
                    fn=_q,
                )
                source = "default_platform_env"
        except Exception as exc:
            logger.info("list_apaas_apps fallback skipped: %s", exc)
            ok = False

    if not ok:
        return {
            "ok": True,
            "apps": [],
            "total": 0,
            "skipped": True,
            "source": "none",
            "message": (
                "当前请求没有 aPaaS 原生用户 Header，且未找到可用默认平台环境，"
                "已跳过应用列表查重；这不影响读取 Markdown 或保存设计文档。"
            ),
            "next_action": "若只是保存设计文档，请继续调用 save_design_draft；若要查询线上应用，请先绑定/连接平台环境。",
        }

    apps = _format_apaas_app_list(payload)

    return {
        "ok": True,
        "apps": apps,
        "total": len(apps),
        "source": source,
        "env_id": env_id or None,
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def list_apaas_apps_in_env(
    env_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """⚠️ DEPRECATED（2026-05-09 阶段1）：请改用 list_apaas_apps(env: str)。

    本工具仅为兼容线上老 dolphin agent prompt 保留，下个 release 周期删除。
    新 agent 配置请用 alias 版本（无需 user_id/tenant_id 反查）。

    ── 历史功能 ──
    列出某 PlatformEnv 在 aPaaS 平台上**已存在**的所有应用（含 code / name / id）。
    返回 { env_id, env_name, apps: [...], total }
    """
    tid, uid = await _resolve_identity(tenant_id, user_id)

    async def _q(client) -> list:
        return await client.query_app_list()

    ok, payload = await _with_apaas_client(
        env_id, tenant_id=tid, user_id=uid, op="列环境应用", fn=_q,
    )
    if not ok:
        return payload  # _business_error dict

    apps: list[dict] = []
    for a in payload or []:
        if not isinstance(a, dict):
            continue
        apps.append({
            "apaas_app_id": str(a.get("id", a.get("appId", ""))),
            "app_code": str(a.get("appCode", a.get("code", "")) or ""),
            "app_name": str(a.get("appName", a.get("name", "")) or ""),
            "description": str(a.get("description", a.get("appDescription", "")) or ""),
            "status": str(a.get("status", "") or ""),
            # 2026-05-09 补：apaas 平台直接返回的访问地址，agent 给用户回链接时用，
            # 不要自己推导/拼路径（容易拼错 tenant_code/前缀/移动端 m vs app）。
            "web_url": str(a.get("accessUrl", "") or ""),           # 电脑端访问首页
            "mobile_url": str(a.get("accessMobileUrl", "") or ""),  # 移动端访问首页
            "backend_url": str(a.get("backendUrl", "") or ""),      # 应用 backend API 前缀（自开发 axios 拼对接 api 用）
            "tenant_code": str(a.get("tenantCode", "") or ""),      # apaas 平台租户编码（如 bj），自开发 url 拼接用
            "current_version": str(a.get("currentVersion", "") or ""),  # 当前发布版本（republish 决策用）
        })

    # 顺手回一次 env 元信息（_with_apaas_client 内部已 load 过）
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        env = (await db.execute(
            select(PlatformEnv).where(PlatformEnv.id == env_id, PlatformEnv.tenant_id == tid)
        )).scalar_one_or_none()
    return {
        "ok": True,
        "env_id": env_id,
        "env_name": env.env_name if env else None,
        "apps": apps,
        "total": len(apps),
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def check_app_code_conflict(
    app_code: str,
    env: str = "",
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 检查 app_code 是否已被占用。

    ⚠️ 已合并进 promote_draft_to_app 内部前置 —— 新流程**不要再调本工具**。
    本工具仅保留作老 agent 兼容入口，函数体不变。
    """
    code = (app_code or "").strip()
    if not code:
        return _business_error(op="查重应用编码", error_text="app_code 为空")
    if not env and env_id <= 0:
        return _business_error(op="查重应用编码", error_text="必须传 env (alias，推荐) 或 env_id")

    # 复用 list_apaas_apps（alias 模式）或老 list_apaas_apps_in_env（env_id 兼容模式）
    if env:
        listing = await list_apaas_apps(env=env)
        env_id_out = listing.get("env_id") if listing.get("ok") else 0
    else:
        listing = await list_apaas_apps_in_env(
            env_id=env_id, tenant_id=tenant_id, user_id=user_id,
        )
        env_id_out = env_id
    if not listing.get("ok"):
        return listing  # 直接透传 business_error

    apps = listing.get("apps") or []
    used_codes = {(a.get("app_code") or "").strip().lower() for a in apps if a.get("app_code")}
    code_lower = code.lower()
    conflicting = next((a for a in apps if (a.get("app_code") or "").strip().lower() == code_lower), None)

    if not conflicting:
        return {
            "ok": True,
            "conflict": False,
            "env": env or None,
            "env_id": env_id_out,
            "env_name": listing.get("env_name"),
            "checked_code": code,
            "summary": f"app_code「{code}」在「{listing.get('env_name')}」环境下未被占用，可以使用。",
        }

    # 给候选后缀（跳过同样占用的）
    suggested: list[str] = []
    for i in range(1, 10):
        candidate = f"{code}_v{i}".lower()
        if candidate not in used_codes:
            suggested.append(f"{code}_v{i}")
        if len(suggested) >= 3:
            break

    return {
        "ok": True,
        "conflict": True,
        "env": env or None,
        "env_id": env_id_out,
        "env_name": listing.get("env_name"),
        "checked_code": code,
        "conflicting_app": {
            "apaas_app_id": conflicting.get("apaas_app_id"),
            "app_code": conflicting.get("app_code"),
            "app_name": conflicting.get("app_name"),
            "status": conflicting.get("status"),
        },
        "suggested_codes": suggested,
        "summary": (
            f"app_code「{code}」已被「{conflicting.get('app_name')}」（apaas_app_id={conflicting.get('apaas_app_id')}）占用。"
            f"建议改用 {suggested[0] if suggested else '其他编码'}，或者跟用户确认要不要"
            f"用 update_app_from_doc 更新已有应用。禁止自动加后缀重试，必须让用户决定。"
        ),
        "user_action_required": (
            "把 conflicting_app 信息和 suggested_codes 展示给用户，让用户选："
            "[更新已有应用]（用 update_app_from_doc）还是 [改个新编码再创建]（在设计文档第一章改 app_code）。"
        ),
    }


# 已知 apaas 平台保留 modelCode（基于历史 _ 后缀现象反推 + 持续维护）
# 命中这些 modelCode 即使租户内没冲突，apaas 创建时也会主动加 _ 后缀
# → SPEC 写的 code 跟实际部署的 code 不一致 → 表单 modelField 引用 / API 调用全错
#
# 分两套（实测发现单 word 也会被加 _ 后缀，不只是 word_ 前缀模式）：
#  1) PREFIX 集合：startswith 匹配（如 `candidate_info` 撞 `candidate_`）
#  2) EXACT 集合：完全相等匹配（如 `candidate` 单 word 也撞）
#
# 维护：每次发现新 _ 后缀现象时补对应集合
_APAAS_RESERVED_MODEL_PREFIXES = {
    "org_", "employee_", "employment_", "attendance_",
    "recruitment_", "headcount_", "candidate_", "movement_",
    "user_", "role_", "dept_", "position_",
}
_APAAS_RESERVED_MODEL_EXACT = {
    # 5/11 晚实测：candidate 单 word 被 apaas 加 _ → candidate_
    "candidate", "employee", "employment", "attendance",
    "recruitment", "headcount", "movement", "position",
    "org", "user", "role", "dept",
    # 经验性扩充（高风险业务 namespace 单 word）
    "company", "department", "staff", "manager",
    "approver", "applicant", "status", "type",
    "form", "menu", "field", "model", "table",
}


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def check_model_codes(
    env: str,
    model_codes: list[str],
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 预检 modelCode 是否撞 apaas 租户内已有模型 / 平台保留前缀。

    ⚠️ 已合并进 promote_draft_to_app 内部前置 —— 新流程**不要再调本工具**。
    本工具仅保留作老 agent 兼容入口。下面是原 docstring：

    🆕 设计阶段预检 modelCode 是否撞 apaas 租户内已有模型 / 撞平台保留前缀。

    **必须在 generate_app_from_doc 之前调**。冲突时不要硬上 generate，否则 apaas
    平台会主动给冲突 modelCode 加 `_` 后缀（如 `org_dept` → `org_dept_`），导致
    SPEC 跟实际部署不一致，下游表单 modelField 引用全错。

    检查 2 层：
      1. **租户内冲突**：调 list_apaas_models_in_env(env) 拿当前 env 跨应用全部
         modelCode，对比 spec 里 model_codes 找重复
      2. **平台保留前缀**：维护一份已知保留前缀清单（org_/employee_/attendance_
         /recruitment_/headcount_/candidate_/movement_/employment_ 等），命中即标记

    冲突处理协议（agent 必须遵守）：
      1. 收到 conflicts 非空 → **不要重试 generate_app_from_doc**
      2. 用 LLM 重写 md spec 里冲突的 modelCode（选语义相近的，**避开**
         conflicts.suggestions_avoid 列出的所有 code）。命名建议加业务前缀
         （hr_/sales_/fin_）保持语义可读，**禁止**简单加 `_` / `t_` 前后缀
      3. 调 validate_builder_doc 验证新 md
      4. 再次调本工具 check_model_codes 确认新 modelCode 无冲突
      5. 全部无冲突才进 generate_app_from_doc
      6. **必须把改后的完整 SPEC 重新展示给用户审过**才能 generate

    参数：
      - env: apaas 环境 alias（如 "baogong"）
      - model_codes: spec 里所有 modelCode 列表（含子表）

    返回：
      {
        ok: True,                               # 工具调用本身是否成功
        no_conflict: bool,                      # 全部 code 都没冲突？True 才能进 generate
        conflicts: [
          {code, reason, conflict_type: "tenant_existing" | "reserved_prefix",
           conflicts_with: <已存在的 app/model 信息> | "前缀 org_ 是 apaas 内置保留"},
          ...
        ],
        suggestions_avoid: [所有已被占用的 modelCode 清单，agent 重写时要全部避开],
        reserved_prefixes: [...],
        env, env_id, env_name,
      }
    """
    if not env:
        return _business_error(
            op="check_model_codes",
            error_text="必须传 env (alias)",
            extra={"error_code": "VIBE_BAD_ENV"},
        )
    if not isinstance(model_codes, list) or not model_codes:
        return _business_error(
            op="check_model_codes",
            error_text="model_codes 必须是非空 list[str]",
        )

    # 复用 list_apaas_models_in_env 拉租户级全部 modelCode
    listing = await list_apaas_models_in_env(env=env, tenant_id=tenant_id, user_id=user_id)
    if not listing.get("ok"):
        return listing  # 透传 business_error

    existing = listing.get("models") or []
    existing_codes_map: dict[str, dict] = {}
    for m in existing:
        c = (m.get("code") or "").strip().lower()
        if c:
            existing_codes_map[c] = m

    conflicts: list[dict] = []
    for raw_code in model_codes:
        c = (raw_code or "").strip()
        if not c:
            continue
        c_lower = c.lower()

        # 0) **catch-all 铁律**：modelCode 末尾不允许带 _
        # 这是 apaas 平台保留字保护机制自动产生的格式，agent 主动写 _ 后缀
        # 几乎总是错的（用户拍板的命名铁律）。无论字面如何，一律拦
        if c_lower.endswith("_"):
            conflicts.append({
                "code": c,
                "conflict_type": "trailing_underscore",
                "reason": (
                    f"⚠️ modelCode `{c}` 末尾带 `_` — 这是 apaas 平台保留字保护机制"
                    f"自动产生的格式，agent 不能主动写。改用业务前缀命名："
                    f"`hr_{c_lower.rstrip('_')}` / `staff_{c_lower.rstrip('_')}` / "
                    f"`recruit_{c_lower.rstrip('_')}` 等。"
                ),
                "conflicts_with": "trailing_underscore_forbidden",
            })
            continue

        # 1) 租户内冲突
        if c_lower in existing_codes_map:
            existing_m = existing_codes_map[c_lower]
            conflicts.append({
                "code": c,
                "conflict_type": "tenant_existing",
                "reason": (
                    f"租户内已有同 modelCode：「{existing_m.get('name')}」"
                    f"（在应用 {existing_m.get('app_name')} / app_id={existing_m.get('app_id')}）"
                ),
                "conflicts_with": existing_m,
            })
            continue

        # 2a) 平台保留前缀 startswith 匹配
        prefix_hit = None
        for pfx in _APAAS_RESERVED_MODEL_PREFIXES:
            if c_lower.startswith(pfx):
                prefix_hit = pfx
                break
        # 2b) 平台保留 modelCode 整词匹配（candidate / employee 单 word 也会被加 _）
        exact_hit = c_lower if c_lower in _APAAS_RESERVED_MODEL_EXACT else None

        if prefix_hit:
            conflicts.append({
                "code": c,
                "conflict_type": "reserved_prefix",
                "reason": (
                    f"撞 apaas 平台保留前缀 `{prefix_hit}` — "
                    f"创建时平台会主动加 `_` 后缀（如 `{c}` → `{c}_`），"
                    f"导致 SPEC 跟实际部署不一致。建议换业务前缀（hr_/sales_/fin_）。"
                ),
                "conflicts_with": f"reserved_prefix: {prefix_hit}",
            })
        elif exact_hit:
            conflicts.append({
                "code": c,
                "conflict_type": "reserved_exact",
                "reason": (
                    f"撞 apaas 平台保留 modelCode `{exact_hit}` — "
                    f"创建时平台会主动加 `_` 后缀（如 `{c}` → `{c}_`），"
                    f"导致 SPEC 跟实际部署不一致。"
                    f"建议换业务命名（hr_{c} / staff_{c}_master 等）。"
                ),
                "conflicts_with": f"reserved_exact: {exact_hit}",
            })

    no_conflict = len(conflicts) == 0
    return {
        "ok": True,
        "no_conflict": no_conflict,
        "conflicts": conflicts,
        "suggestions_avoid": sorted(existing_codes_map.keys()),
        "reserved_prefixes": sorted(_APAAS_RESERVED_MODEL_PREFIXES),
        "reserved_exact_codes": sorted(_APAAS_RESERVED_MODEL_EXACT),
        "env": listing.get("env"),
        "env_id": listing.get("env_id"),
        "env_name": listing.get("env_name"),
        "checked_count": len(model_codes),
        "summary": (
            f"全部 {len(model_codes)} 个 modelCode 无冲突，可以进 generate_app_from_doc"
            if no_conflict else
            f"⚠️ 发现 {len(conflicts)} 个冲突 modelCode。**不要**硬上 generate，"
            f"先用 LLM 重写 md 改这些 code（避开 suggestions_avoid + reserved_prefixes），"
            f"重新 validate + check_model_codes 确认后再 generate，并把改后 SPEC 重新展示给用户审。"
        ),
        "user_action_required": (
            "agent 自己用 LLM 重选语义相近的 modelCode，**禁止简单加 _/t_ 前后缀**。"
            "改完 md 重新调 validate_builder_doc → check_model_codes 验证 → "
            "展示给用户审完整新 SPEC → 用户 OK 才 generate_app_from_doc。"
        ) if not no_conflict else None,
    }


# @mcp.tool()  # [MERGED] -> get_apaas_app_overview(include=["models"]) | tenant-scope 已废
async def list_apaas_models_in_env(
    env: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出某 apaas 环境下数据模型（含 modelCode）。

    🆕 推荐：传 env="<alias>"（如 "dev8"），无需 user_id/tenant_id
    ⚠️ env_id/tenant_id/user_id 仅为兼容老 prompt 保留，下个 release 移除

    参数：
      - apaas_app_id 给了 → 列指定应用下的所有模型（含详情字段）
      - apaas_app_id 留空 → 列租户级全部模型 code（跨应用 modelCode 冲突预检）

    用途（agent 工作流）：
      - update_app_from_doc 前预检，确认要新增的 modelCode 没冲突
      - deploy 前跨应用扫描 modelCode 是否已被同租户其他应用占用

    返回 { env, env_id, env_name, scope: 'app' | 'tenant', apaas_app_id, models, total }
    """
    apaas_app_id = (apaas_app_id or "").strip()

    if apaas_app_id:
        async def _q(client) -> list:
            raw = await client.query_models(apaas_app_id)
            return raw or []
        scope = "app"
    else:
        async def _q(client) -> list:
            raw = await client.query_all_model_codes()
            return raw or []
        scope = "tenant"

    # alias 优先 → env_id 兼容
    if env:
        ok, payload = await _with_apaas_client_by_alias(env, op="列环境模型", fn=_q)
    elif env_id > 0:
        tid, uid = await _resolve_identity(tenant_id, user_id)
        ok, payload = await _with_apaas_client(
            env_id, tenant_id=tid, user_id=uid, op="列环境模型", fn=_q,
        )
    else:
        return _business_error(op="列环境模型", error_text="必须传 env (alias，推荐) 或 env_id")

    if not ok:
        return payload

    models: list[dict] = []
    for m in payload or []:
        if not isinstance(m, dict):
            continue
        models.append({
            "code": str(m.get("code", m.get("modelCode", "")) or ""),
            "name": str(m.get("name", m.get("modelName", "")) or ""),
            "app_id": str(m.get("app_id", m.get("appId", "")) or ""),
            "app_name": str(m.get("app_name", m.get("appName", "")) or ""),
        })
    models = [m for m in models if m["code"]]

    # env metadata
    if env:
        from app.services.apaas_env_registry import resolve_env_by_alias
        creds = await resolve_env_by_alias(env)
        env_name = creds.env_name if creds else None
        env_id_out = creds.env_id if creds else 0
    else:
        from app.database import AsyncSessionLocal
        from app.models import PlatformEnv
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(PlatformEnv).where(PlatformEnv.id == env_id)
            )).scalar_one_or_none()
        env_name = row.env_name if row else None
        env_id_out = env_id

    return {
        "ok": True,
        "env": env or None,
        "env_id": env_id_out,
        "env_name": env_name,
        "scope": scope,
        "apaas_app_id": apaas_app_id or None,
        "models": models,
        "total": len(models),
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def save_app_design_doc(
    md_content: str,
    app_name: str = "",
    env: str = "",
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """**Builder 长 SPEC 必调** —— 落盘应用设计文档，返回 doc_token + 解析摘要。

    🚨 **必走条件**：md_content 长度 > 8000 字符（约 2k token）必走本工具拿
    doc_token 再调 generate_app_from_doc(doc_token=...)，**禁止**直接传 md_content
    给 generate —— 否则 dolphin agent 容器 LLM context 撞 token 限制，agent 报
    「Agent 服务异常」（2026-05-12 SAIC 缺件车应用 23k 字 SPEC 实测翻车）。

    与 generate_app_from_doc 对比：
    | 调用 | LLM 经手 payload | dolphin context 压力 |
    |------|----------------|--------------------|
    | save_app_design_doc(md=23k) 一次 | 23k 输出 | 1 次 23k 输出 |
    | 之后 generate_app_from_doc(doc_token=32字) | 32 字 | 几乎零 |
    | retry / 用户改字段 → 重调 save | 重写 md | 不需 LLM 再吐整篇 |

    内部做 3 件事：
    1. 落盘 md 到 backend `.pending-app-design-docs/<doc_token>.md`
    2. 调 /applications/upload-doc 解析（同 generate 第 1 步），把角色/字典/模型/
       表单/权限数量摘要返回 → agent 在 chat 给用户展示**业务摘要**让用户审
    3. 顺带做 modelCode 跨应用预检（如传了 env）—— 撞冲突直接 fail 防 generate 撞

    用户改 X 改 Y 时：**重写整篇 md_content 后重新调本工具**（覆盖前一份 doc_token）。

    参数：
    - md_content：标准设计文档全文（应用信息/角色/字典/模型/表单/流程配置/权限）
    - app_name：可选；从 md 「一、应用信息」推断
    - env / env_id：apaas 环境别名 / id，用于 modelCode 预检（强烈建议传）

    返回（成功）：
        {
          "ok": True,
          "doc_token": "appdoc_<uid>_<8hex>",
          "doc_md_length": 23456,
          "summary": {"roles": 8, "dicts": 7, "models": 17, "forms": 20, "perms": 20},
          "validation": {"score": 100, "warnings": [...]},
          "next_action": "在 chat 给用户展示业务摘要 + 等用户 OK → 调
                          generate_app_from_doc(doc_token='...', env='...')"
        }
    返回（解析失败 / modelCode 冲突）：业务错 dict，含 error_code + user_action_required
    """
    import uuid as _uuid
    from pathlib import Path
    from datetime import datetime, timezone
    import json as _json
    from app.coding.workspace import WORKSPACE_ROOT

    # 1) 基本校验
    if not md_content or len(md_content.strip()) < 100:
        return {
            "ok": False, "op": "save_app_design_doc",
            "error_code": "DOC_TOO_SHORT",
            "message": f"md_content 太短 ({len(md_content.strip())} 字符)，至少 100 字符。",
            "should_retry": True,
        }

    # 2) 解析 env → env_id（同 generate 逻辑，便于 modelCode 预检）
    resolved_env_id = int(env_id) if env_id else 0
    env_owner_tid = None
    if env:
        from app.services.apaas_env_registry import resolve_env_by_alias
        creds = await resolve_env_by_alias(env)
        if not creds:
            return _business_error(
                op="落盘设计文档",
                error_text=f"环境别名 '{env}' 不存在",
                extra={"env_alias": env},
            )
        resolved_env_id = creds.env_id
        from app.database import AsyncSessionLocal
        from app.models import PlatformEnv
        from sqlalchemy import select as _select
        async with AsyncSessionLocal() as _db:
            env_row = (await _db.execute(
                _select(PlatformEnv).where(PlatformEnv.id == resolved_env_id)
            )).scalar_one_or_none()
            if env_row:
                env_owner_tid = int(env_row.tenant_id)

    if env_owner_tid is not None:
        tid, uid = env_owner_tid, 1
    else:
        tid, uid, resolved_env_id_from_header = await _resolve_internal_identity_for_mcp(
            tenant_id,
            user_id,
        )
        if not resolved_env_id:
            resolved_env_id = resolved_env_id_from_header

    # 3) 调 backend 解析（撞 md 格式问题第一时间在这暴露）
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    try:
        parse_res = await _api_call(
            "POST", "/applications/upload-doc", tenant_id=tid, user_id=uid, files=files
        )
    except RuntimeError as exc:
        return _business_error(op="解析设计文档", error_text=str(exc))
    preview = parse_res.get("data") if isinstance(parse_res, dict) else None
    if not isinstance(preview, dict):
        return _business_error(
            op="解析设计文档",
            error_text=f"文档解析返回结构异常：{parse_res!r:.300s}",
        )

    final_app_name = (app_name or preview.get("appName") or "").strip() or "未命名应用"

    # 4) 落盘到 .pending-app-design-docs/<doc_token>.md
    doc_dir = WORKSPACE_ROOT.parent / ".pending-app-design-docs"
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_token = f"appdoc_{uid}_{_uuid.uuid4().hex[:8]}"
    doc_path = doc_dir / f"{doc_token}.md"
    metadata = {
        "doc_token": doc_token,
        "app_name": final_app_name,
        "app_code": (preview.get("appCode") or preview.get("app_code") or "").strip() or None,
        "env": env or None,
        "env_id": resolved_env_id or None,
        "tenant_id": tid,
        "user_id": uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    frontmatter = "---\n" + _json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n\n"
    doc_path.write_text(frontmatter + md_content, encoding="utf-8")

    # 5) 解析摘要
    summary = {
        "roles": len(preview.get("roles") or []),
        "dicts": len(preview.get("dicts") or preview.get("dictionaries") or []),
        "models": len(preview.get("models") or []),
        "forms": len(preview.get("forms") or []),
        "flows": len(preview.get("flows") or preview.get("workflows") or preview.get("processes") or []),
        "perms": len(preview.get("permissions") or preview.get("perms") or []),
    }

    return {
        "ok": True,
        "op": "save_app_design_doc",
        "doc_token": doc_token,
        "app_name": final_app_name,
        "app_code": metadata["app_code"],
        "doc_md_length": len(md_content),
        "summary": summary,
        "env": env or None,
        "env_id": resolved_env_id or None,
        "next_action": (
            f"✅ 文档已落盘，doc_token='{doc_token}'。\n"
            f"现在在 chat 给用户展示**业务摘要**（中文表达）：\n"
            f"  「已生成《{final_app_name}》设计：角色 {summary['roles']} 项 / "
            f"字典 {summary['dicts']} 项 / 模型 {summary['models']} 项 / "
            f"表单 {summary['forms']} 项 / 审批流 {summary['flows']} 项 / "
            f"权限 {summary['perms']} 项」\n"
            f"明确询问用户：「这样设计可以开始建应用了吗？同意请回复 OK」\n"
            f"用户同意后**只调** generate_app_from_doc(doc_token='{doc_token}', env='{env}') ——\n"
            f"**禁止**再传整篇 md_content，避免 dolphin agent 容器 token 撞限。\n"
            f"用户说改 X 改 Y 时：**重写完整 md_content 重新调本工具**（拿新 doc_token 覆盖旧）。"
        ),
    }


async def _load_ai_chat_artifact_content(artifact_id: int) -> str | None:
    """Read a design artifact created in the current AI Chat session.

    The standalone MCP service shares the main AI Builder database in local mirror
    mode, so artifact IDs from the right-side panel are valid here too.
    """
    if not artifact_id or artifact_id <= 0:
        return None
    try:
        from app.database import AsyncSessionLocal
        from app.models import AIChatArtifact
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(AIChatArtifact.content).where(AIChatArtifact.id == int(artifact_id))
            )
            row = res.first()
            return row[0] if row else None
    except Exception as exc:
        logger.warning("_load_ai_chat_artifact_content(%s) failed: %s", artifact_id, exc)
        return None


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def generate_app_from_doc(
    md_content: str = "",
    doc_token: str = "",
    artifact_id: int = 0,
    app_name: str | None = None,
    env: str = "",
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 根据 md 文档一步到位创建+部署应用。

    ⚠️ 新流程：用 save_design_draft(md) → promote_draft_to_app(draft_id)，
    分两步既能给用户一个预览页确认，又能保护 agent 上下文。
    本工具保留作老 agent 兼容入口。下面是原 docstring：

    🚨 **2026-05-12 改造**：长 SPEC (> 8000 字) **必须**先调 `save_app_design_doc`
    拿 `doc_token` 再调本工具传 `doc_token=...`，**禁止**直接传 md_content（否则
    dolphin agent 容器 LLM context 撞 token 限制，agent 报「Agent 服务异常」）。

    🆕 推荐：传 env="<alias>"（如 "dev8"）。alias 模式下应用 owner 归属系统账号。
    ⚠️ env_id/tenant_id/user_id 仅为兼容老 prompt 保留

    内部分两步：parse → auto-create。md 必须是 Builder 标准格式。

    参数：
    - artifact_id：AI Chat 右侧设计文档 artifact id；当前账号/当前租户场景优先用它，省 token。
    - doc_token：**长 SPEC 必传**。来自 save_app_design_doc 返回值，本工具读盘拿 md。
    - md_content：短 SPEC (< 8000 字)可直传；传了 doc_token 时**忽略**本字段。
    - app_name：可选；不填会从 md 「一、应用信息」推断
    - env：apaas 环境别名（推荐）。env 和 env_id 都不传 → 用 backend 默认环境

    返回 { app_id, app_name, app_code, status, app_view_url, env: {id, name} }。
    """
    # artifact_id 优先：AI Chat 右侧设计文档已经落库，dispatcher 会按当前会话
    # 最新 .md artifact 纠正 LLM 传错/漏传的 id。doc_token 只保留给老客户端兜底。
    if artifact_id:
        loaded = await _load_ai_chat_artifact_content(int(artifact_id))
        if not loaded:
            return _business_error(
                op="读取 artifact",
                error_text=(
                    f"artifact_id={artifact_id} 不存在或不可读。"
                    "请确认使用当前 AI Chat 右侧设计文档产物 ID。"
                ),
                extra={"error_code": "ARTIFACT_NOT_FOUND", "artifact_id": artifact_id},
            )
        md_content = loaded
    elif doc_token:
        from pathlib import Path
        from app.coding.workspace import WORKSPACE_ROOT
        doc_dir = WORKSPACE_ROOT.parent / ".pending-app-design-docs"
        doc_path = doc_dir / f"{doc_token}.md"
        if not doc_path.exists():
            return _business_error(
                op="读取 doc_token",
                error_text=(
                    f"doc_token '{doc_token}' 不存在（可能已过期或写错）。"
                    f"重新调 save_app_design_doc(md_content=...) 拿新 token。"
                ),
                extra={"error_code": "DOC_TOKEN_NOT_FOUND", "doc_token": doc_token,
                       "should_retry": False},
            )
        raw = doc_path.read_text(encoding="utf-8")
        # 剥掉 frontmatter（save 工具落盘加的 metadata，platform 解析不认这段）
        if raw.startswith("---\n"):
            end_idx = raw.find("\n---\n", 4)
            if end_idx > 0:
                raw = raw[end_idx + 5:].lstrip("\n")
        md_content = raw

    if not md_content or len(md_content.strip()) < 100:
        return {
            "ok": False, "op": "generate_app_from_doc",
            "error_code": "DOC_TOO_SHORT",
            "message": (
                f"md_content 太短 ({len((md_content or '').strip())} 字符)。"
                f"长 SPEC 应先调 save_app_design_doc 拿 doc_token 再传本工具。"
            ),
            "should_retry": False,
        }
    # env (alias) → env_id 反查；env_id 模式走老 _resolve_identity
    if env:
        from app.services.apaas_env_registry import resolve_env_by_alias
        creds = await resolve_env_by_alias(env)
        if not creds:
            return _business_error(
                op="创建应用",
                error_text=f"环境别名 '{env}' 不存在",
                extra={"env_alias": env},
            )
        env_id = creds.env_id
        # 🛡️ 2026-05-10 防御性 assertion #1：alias 模式下 env_id 必须是正整数。
        # 历史 BUG（已修，commit b5f6d3c）：yaml 来源 alias 命中时 env_id 被硬编码 -1，
        # 后续 `if env_id > 0` 判断 fail → backend 用 user 默认 env → 应用建错租户
        # （pg 用 baogong alias 误建到新豪轩 owner=xhx 的 apaas tenant）。
        # 这层 assertion 不允许 alias 模式下 env_id ≤ 0 默默 fallback —— fail-fast。
        if not isinstance(env_id, int) or env_id <= 0:
            return _business_error(
                op="创建应用",
                error_text=(
                    f"环境别名 '{env}' 解析出的 env_id={env_id!r} 无效 "
                    f"(应为 platform_envs.id 正整数)。检查 yaml + DB alias 同步状态。"
                ),
                extra={"env_alias": env, "resolved_env_id": env_id,
                       "platform_tenant_id": creds.platform_tenant_id},
            )
        # 🛡️ 2026-05-10 防御性 #2：用 platform_env 真所属 tenant 当 ctx，
        # 不是固定 admin tenant=1。否则 auto-create 第一层校验
        # `platform_env_id 必须属于 ctx.tenant_id` 会 fail → 降级 fallback
        # 用 user 默认 env → 又建错租户。admin (is_platform_admin=True) 任意
        # tenant 都通过 get_auth_context，所以 tenant_id 切到 env 真所属即可。
        from app.database import AsyncSessionLocal
        from app.models import PlatformEnv
        from sqlalchemy import select as _select
        async with AsyncSessionLocal() as _db:
            env_row = (await _db.execute(
                _select(PlatformEnv).where(PlatformEnv.id == env_id)
            )).scalar_one_or_none()
            if not env_row:
                return _business_error(
                    op="创建应用",
                    error_text=(
                        f"alias '{env}' 解析的 env_id={env_id} 在 platform_envs 表查不到。"
                        "数据不一致，可能 yaml 配了但 DB 没建对应行。"
                    ),
                    extra={"env_alias": env, "resolved_env_id": env_id},
                )
            env_owner_tid = int(env_row.tenant_id)
        # alias 模式：用 admin user_id=1（任意租户都能进，is_platform_admin=True），
        # tenant_id 切到 env 真所属，确保 auto-create 校验通过。
        tid, uid = env_owner_tid, 1
    elif env_id and env_id > 0:
        from app.mcp_request_ctx import get_mcp_ctx
        ctx = get_mcp_ctx()
        if ctx and ctx.apaas_token and ctx.apaas_tenant_id:
            tid, uid, header_env_id = await _resolve_mcp_service_identity_from_header()
            if int(env_id) != int(header_env_id):
                return _business_error(
                    op="创建应用",
                    error_text=(
                        f"请求 env_id={env_id} 与 Header aPaaS tenant 绑定环境 env_id={header_env_id} 不一致，"
                        "拒绝创建以避免串租户。"
                    ),
                    extra={"requested_env_id": int(env_id), "header_env_id": int(header_env_id)},
                )
        else:
            tid, uid = await _resolve_identity(tenant_id, user_id)
    else:
        tid, uid, header_env_id = await _resolve_internal_identity_for_mcp(tenant_id, user_id)
        if header_env_id:
            env_id = header_env_id

    # 1) 解析（解析失败一般是 markdown 格式问题，业务错误返回 dict 让 agent 直接告诉用户）
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    try:
        parse_res = await _api_call(
            "POST", "/applications/upload-doc", tenant_id=tid, user_id=uid, files=files
        )
    except RuntimeError as exc:
        return _business_error(op="解析设计文档", error_text=str(exc))
    preview = parse_res.get("data") if isinstance(parse_res, dict) else None
    if not isinstance(preview, dict):
        return _business_error(
            op="解析设计文档",
            error_text=f"文档解析返回结构异常：{parse_res!r:.300s}",
        )

    final_app_name = (app_name or preview.get("appName") or "").strip() or "未命名应用"

    # 🆕 1.5) modelCode 跨应用预检（fail-fast）—— apaas 平台 modelCode 在**同 apaas 租户内
    # 跨应用唯一**（不是应用级隔离）。dev8 这个 apaas 租户已 2652 个模型，customer_ /
    # order / user 这种通用名早被同租户其他应用占用，不预检会导致 auto-create 时 v2/appModel
    # batch 失败"模型编码重复"——应用本身建好但模型 0 个 + 表单退化"我的待办"占位
    # （实测 dev8 简单销售管理系统就是这样建坏的）。
    if env_id and env_id > 0:
        md_model_codes = []
        for m in (preview.get("models") or []):
            c = (m.get("code") or m.get("modelCode") or "").strip()
            if c:
                md_model_codes.append(c)

        if md_model_codes:
            try:
                from app.apaas_client import APaaSClient
                from app.database import AsyncSessionLocal
                from app.models import PlatformEnv
                from sqlalchemy import select

                async with AsyncSessionLocal() as db:
                    env_row = (await db.execute(
                        select(PlatformEnv).where(PlatformEnv.id == int(env_id))
                    )).scalar_one_or_none()

                if env_row and env_row.token:
                    client = APaaSClient(
                        base_url=env_row.base_url,
                        tenant_id=env_row.platform_tenant_id,
                        token=env_row.token,
                    )
                    tenant_models = await client.query_all_model_codes()
                    existing: dict[str, str] = {}  # {modelCode: app_name}
                    for tm in tenant_models or []:
                        if not isinstance(tm, dict):
                            continue
                        tc = (tm.get("code") or tm.get("modelCode") or "").strip()
                        if tc:
                            existing[tc] = (
                                tm.get("app_name") or tm.get("appName")
                                or tm.get("ownerAppName") or ""
                            )

                    conflicts: list[dict] = []
                    # 0) 把 existing 字典 key 全部 lowercase，避免大小写不一致漏判
                    existing_lc = {k.lower(): v for k, v in existing.items()}
                    for c in md_model_codes:
                        c_lower = (c or "").lower()
                        # **catch-all 铁律 #0**：末尾带 _ 直接拦
                        if c_lower.endswith("_"):
                            conflicts.append({
                                "model_code": c,
                                "used_by_app": (
                                    f"末尾带 _ 是 apaas 保留字机制自动产生格式，"
                                    f"agent 不能主动写。改用 hr_{c_lower.rstrip('_')} 等"
                                ),
                                "conflict_type": "trailing_underscore",
                            })
                            continue
                        # 租户内已占用（大小写不敏感）
                        if c_lower in existing_lc:
                            conflicts.append({
                                "model_code": c,
                                "used_by_app": existing_lc[c_lower] or "(其他应用)",
                                "conflict_type": "tenant_existing",
                            })
                            continue
                        # 撞 apaas 平台保留前缀（startswith）
                        prefix_hit = next(
                            (p for p in _APAAS_RESERVED_MODEL_PREFIXES if c_lower.startswith(p)),
                            None,
                        )
                        if prefix_hit:
                            conflicts.append({
                                "model_code": c,
                                "used_by_app": f"撞 apaas 保留前缀 `{prefix_hit}` — 创建时会自动加 _ 后缀",
                                "conflict_type": "reserved_prefix",
                            })
                            continue
                        # 撞 apaas 平台保留整词（exact）
                        if c_lower in _APAAS_RESERVED_MODEL_EXACT:
                            conflicts.append({
                                "model_code": c,
                                "used_by_app": f"撞 apaas 保留整词 `{c_lower}` — 创建时会自动加 _ 后缀",
                                "conflict_type": "reserved_exact",
                            })
                            continue

                    if conflicts:
                        # 给建议：用 app_code 前缀
                        app_code = (
                            preview.get("appCode") or preview.get("app_code") or ""
                        ).strip().lower()
                        suggested: dict[str, str] = {}
                        for cf in conflicts:
                            base = cf["model_code"].rstrip("_")
                            if app_code and not base.startswith(app_code):
                                suggested[cf["model_code"]] = f"{app_code}_{base}"
                            else:
                                # 没 app_code 就加 _v2 后缀（再不行 _v3...）
                                for v in range(2, 10):
                                    cand = f"{base}_v{v}"
                                    if cand not in existing:
                                        suggested[cf["model_code"]] = cand
                                        break

                        sample = "; ".join(
                            f"{c['model_code']}（被「{c['used_by_app']}」用）"
                            for c in conflicts[:5]
                        )
                        more = f"，等共 {len(conflicts)} 个" if len(conflicts) > 5 else ""
                        return _business_error(
                            op="modelCode 跨应用预检",
                            error_text=(
                                f"⚠️ {len(conflicts)} 个 modelCode 已被同 apaas 租户其他应用占用："
                                f"{sample}{more}。"
                                f"apaas 平台 modelCode 在**同租户内跨应用唯一**（一个 apaas 租户里"
                                f"所有应用共享 modelCode 命名空间），撞了会让 v2/appModel batch 全失败。"
                            ),
                            extra={
                                "error_code": "MODEL_CODE_CONFLICT",
                                "conflicts": conflicts,
                                "suggested_replacements": suggested,
                                "user_action_required": (
                                    f"修改 md 第四章「数据模型」，把所有冲突的 modelCode 加 "
                                    f"app_code（{app_code or '<your_app>'}）前缀。"
                                    f"建议替换：{suggested}。"
                                    f"同时第四/五章里 `字段类型 = 引用：<modelCode>` 的引用也要"
                                    f"同步改成新 code。改完后重新调 generate_app_from_doc。"
                                ),
                                "should_retry": False,
                            },
                        )
            except RuntimeError:
                raise
            except Exception as exc:
                logger.warning(
                    "modelCode 跨应用预检失败（非阻断，让 auto-create 自然撞错）: %s", exc,
                )

    # 2) auto-create（撞 apaas 应用编码冲突 / 字段保留字 / token 过期自愈失败 都在这里）
    create_body: dict = {"app_name": final_app_name, "config_preview": {"data": preview}}
    if env_id and env_id > 0:
        create_body["platform_env_id"] = int(env_id)
    try:
        create_res = await _api_call(
            "POST",
            "/applications/auto-create",
            tenant_id=tid,
            user_id=uid,
            json_body=create_body,
            # auto-create 这一步会去 apaas 真创建应用，token 过期常见。env_id=0 时
            # 让 backend 用默认环境，自愈拿不到具体 env 就 skip（让原错误冒泡）。
            token_retry_env_id=int(env_id) if env_id and env_id > 0 else None,
        )
    except RuntimeError as exc:
        return _business_error(
            op="创建应用",
            error_text=str(exc),
            extra={"env_id": int(env_id)} if env_id and env_id > 0 else None,
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
        # ai-builder 内部预览/编辑页（draft 阶段唯一能看的地方，apaas 后台还没有）
        "app_edit_url": (
            _ai_builder_ui_url(f"/chat?app_id={app_id}") if app_id else None
        ),
        # 此阶段 apaas_app_id 还是 null，apaas 后台 URL 拿不到——必须先调
        # deploy_application 真推到 apaas 平台才有
        "apaas_admin_url": None,
        "deploy_status": "draft_only",
        "next_step_hint": (
            "应用仅在 ai-builder 创建为草稿（apaas_app_id 为空）。要让真实用户能在低代码"
            "后台访问，必须再调 deploy_application 完成首次部署，那时返回的 apaas_admin_url"
            "可以直接打开 apaas 后台。**不要**把 app_edit_url 当作'部署完成的访问地址'"
            "给用户——那是 ai-builder 内部页，不是 apaas 后台。"
        ),
        # 兼容旧字段名（v0.1.x 时叫 app_view_url）
        "app_view_url": (
            _ai_builder_ui_url(f"/chat?app_id={app_id}") if app_id else None
        ),
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def list_my_applications(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """⚠️ DEPRECATED + 禁用：alias 模式下不可用。请改用 list_apaas_apps(env=<alias>)."""
    return _forbidden_in_alias_mode(
        "list_my_applications",
        "list_apaas_apps(env='<你 agent 全局记忆里的 alias>')",
    )

    tid, uid = await _resolve_identity(tenant_id, user_id)
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
    mode: str = "summary",
) -> dict:
    """查看指定应用的元信息。

    🆕 mode 参数（默认 "summary"，**强烈推荐保持默认**）：
      - "summary"：只回 app meta（id/name/code/status/apaas_app_id/admin_url 等）+ current_draft_id。
                   **不**返回 spec_markdown，避免 agent 上下文被全文撑爆。
                   做修改时拿 current_draft_id，调 patch_design_draft + apply_draft_to_live_app。
      - "full"   ：额外返回完整 spec_markdown（含所有字段/表单/权限）。
                   仅在确实需要看全文且明确知道会占大量 token 时用。

    工具参数不再接收环境字段；业务身份由请求 Header 提供。
    app_id=0 时走老 slot 反查路径：自动用用户当前编辑的应用（兼容老 prompt）。
    """
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    app_id, _ = _resolve_app_id(app_id, uid)
    # 拉应用 meta
    meta = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)

    # 反查最新 draft（按 app_id 查 design_drafts，取最新 active/applied）
    current_draft_id = None
    try:
        from app.database import AsyncSessionLocal
        from app.models.design_draft import DesignDraft
        from sqlalchemy import select as _sel, desc as _desc
        async with AsyncSessionLocal() as _d:
            row = (await _d.execute(
                _sel(DesignDraft).where(DesignDraft.app_id == app_id)
                .order_by(_desc(DesignDraft.created_at)).limit(1)
            )).scalar_one_or_none()
            if row:
                current_draft_id = row.id
    except Exception as exc:
        logger.warning("反查 current_draft_id 失败 app_id=%s: %s", app_id, exc)

    base = {
        "ok": True,
        "app_id": (meta or {}).get("id"),
        "app_name": (meta or {}).get("app_name"),
        "app_code": (meta or {}).get("app_code"),
        "status": (meta or {}).get("status"),
        "current_doc_version": (meta or {}).get("current_doc_version"),
        "current_draft_id": current_draft_id,  # 🆕 新流程改动入口
        "platform_env_id": (meta or {}).get("platform_env_id"),
        "apaas_app_id": (meta or {}).get("apaas_app_id"),
        "apaas_admin_url": (meta or {}).get("apaas_url"),
        "app_edit_url": _ai_builder_ui_url(f"/chat?app_id={app_id}"),
        "app_view_url": _ai_builder_ui_url(f"/chat?app_id={app_id}"),
    }

    if mode != "full":
        return base

    # mode="full"：额外拉 spec markdown
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
        **base,
        "spec_markdown": spec_md,
        "spec_markdown_source": spec_source,
        "spec_markdown_version": spec_version,
    }


async def _normalize_md_via_llm(target_md: str, current_spec_md: str) -> str:
    """LLM 兜底：dolphin agent 给的 md 若不符合严格标准模板，
    用 LLM 基于 current_spec_md（已知规范）+ target_md（agent 改动后）
    生成规范化的新版 md。

    避免每次都 LLM 调用 — 调用方仅在 strict parse 失败时才用此兜底。
    """
    from app.llm_client import LLMClient
    llm = LLMClient()
    prompt = f"""你是 ai-builder 设计文档规范化助手，输出严格符合 Builder 标准模板的 markdown。

## 输入
- CURRENT：当前应用规范的 markdown（Builder 标准格式，作为格式模板）
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


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def update_app_from_doc(
    md_content: str,
    app_id: int = 0,
    env: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 上传新版 md 自动 diff 出变更计划。

    ⚠️ 新流程改用 patch_design_draft + apply_draft_to_live_app —— 那条路径只需要传
    一个 patch action JSON（几百字节），不用每次重发完整新 md。
    本工具保留作"整份 md 重新提交"的兜底入口（罕见场景，比如人工大改 md）。

    md_content 不严格符合模板时（章节/表格列差异），后端会自动 LLM 规范化重试一次。

    返回 { version, change_plan_id, summary（变更摘要）}。
    """
    if env:
        if not app_id or app_id <= 0:
            return _business_error(
                op="上传新版 md", error_text="alias (env) 模式必须显式传 app_id",
            )
        tid = await _resolve_alias_tid_for_app(app_id)
        uid = 1  # alias 模式 admin (platform_admin 跨 tenant 任意通行)
    else:
        tid, uid, _env_id = await _resolve_internal_identity_for_mcp(tenant_id, user_id)
        app_id, _ = _resolve_app_id(app_id, uid)

    async def _attempt_upload(md: str) -> dict:
        files = {"file": (f"app-{app_id}-doc.md", md.encode("utf-8"), "text/markdown")}
        return await _api_call_sse_collect(
            "POST",
            f"/applications/{app_id}/upload-doc-version",
            tenant_id=tid, user_id=uid, files=files,
            token_retry_app_id=app_id,
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
        return _business_error(
            op="上传新版 md",
            error_text=sse["errors"][-1],
            app_id=app_id,
            extra={"all_errors": sse["errors"][-3:]},
        )
    done = sse.get("done") or {}
    return {
        "ok": True,
        "app_id": app_id,
        "version": done.get("version") or done.get("to_version"),
        "change_plan_id": done.get("change_plan_id"),
        "summary": done.get("summary") or done.get("change_summary"),
        "raw_done": done,
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def get_change_plan(
    plan_id: int,
    app_id: int = 0,
    env: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 查变更计划详情。

    ⚠️ 已合并进 apply_draft_to_live_app 内部 —— 新流程不需要让 agent 显式审 plan。
    本工具保留作老 agent 兼容入口。下面是原 docstring：

    查看变更计划详情：包含所有 actions（新增/修改/删除的角色、字典、模型、表单、权限）。

    🆕 推荐：传 env="<alias>" + app_id（必填）
    ⚠️ env="" 时走老 slot 反查（app_id=0 → 当前编辑应用）

    用户决策"是否执行"前应该读这个 plan。
    """
    if env:
        if not app_id or app_id <= 0:
            return _business_error(op="查变更计划", error_text="alias 模式必须显式传 app_id")
        tid = await _resolve_alias_tid_for_app(app_id)
        uid = 1  # alias 模式 admin (platform_admin 跨 tenant 任意通行)
    else:
        tid, uid = await _resolve_identity(tenant_id, user_id)
        app_id, _ = _resolve_app_id(app_id, uid)
    res = await _api_call(
        "GET", f"/applications/{app_id}/change-plans/{plan_id}", tenant_id=tid, user_id=uid
    )
    return {"ok": True, "plan": res}


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def execute_change_plan(
    plan_id: int,
    app_id: int = 0,
    env: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 执行变更计划。

    ⚠️ 已合并进 apply_draft_to_live_app 内部 —— 新流程不需要再调本工具。
    本工具保留作老 agent 兼容入口。下面是原 docstring：

    执行变更计划：把 plan 里所有 actions 落到底层（创建/修改/删除模型、表单、权限等）。

    🆕 推荐：传 env="<alias>" + app_id（必填）
    ⚠️ env="" 时走老 slot 反查（app_id=0 → 当前编辑应用）

    这是真正"动手"的工具，调用前请确认用户已经审过 change plan。
    """
    if env:
        if not app_id or app_id <= 0:
            return _business_error(op="执行变更计划", error_text="alias 模式必须显式传 app_id")
        tid = await _resolve_alias_tid_for_app(app_id)
        uid = 1  # alias 模式 admin (platform_admin 跨 tenant 任意通行)
    else:
        tid, uid = await _resolve_identity(tenant_id, user_id)
        app_id, _ = _resolve_app_id(app_id, uid)
    sse = await _api_call_sse_collect(
        "POST",
        f"/applications/{app_id}/change-plans/{plan_id}/execute",
        tenant_id=tid,
        user_id=uid,
        token_retry_app_id=app_id,
    )
    if sse["errors"]:
        return _business_error(
            op="执行变更计划",
            error_text=sse["errors"][-1],
            app_id=app_id,
            extra={
                "plan_id": plan_id,
                "all_errors": sse["errors"][-3:],
                "tail_events": sse["events"][-5:],
            },
        )
    # backend done event 含 platform_synced / sync_result / sync_errors / applied_count /
    # total_count，必须全透传给 agent —— 否则 agent 只看到 ok=True 没法判断是"已下推
    # apaas"还是"只更新了本地"，会答非所是（截图 #209 实测过：agent 自己说"不能确认底层
    # aPaaS 配置实际产生了变更"，根因就是工具吞了 platform_synced 状态）。
    done = sse.get("done") or {}
    summary_parts: list[str] = []
    applied = done.get("applied_count")
    total = done.get("total_count")
    if applied is not None and total is not None:
        summary_parts.append(f"应用了 {applied}/{total} 项变更")
    if done.get("platform_synced") is True:
        summary_parts.append("已下推 aPaaS 平台")
    elif done.get("platform_synced") is False:
        if done.get("sync_errors"):
            summary_parts.append(f"⚠️ 平台同步失败：{'；'.join(map(str, done.get('sync_errors') or []))}")
        else:
            summary_parts.append("仅本地配置更新（草稿应用未关联平台）")
    return {
        "ok": True,
        "app_id": app_id,
        "plan_id": plan_id,
        # 是否真正下推到 apaas（agent 据此判断要不要告诉用户"已生效"）
        "platform_synced": done.get("platform_synced"),
        "applied_count": applied,
        "total_count": total,
        "sync_result": done.get("sync_result"),
        "sync_errors": done.get("sync_errors") or [],
        "executed_count": len([e for e in sse["events"] if e["event"] in ("step", "step_done")]),
        "summary": "；".join(summary_parts) if summary_parts else "变更计划已执行完毕",
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def lookup_user_by_username(username: str) -> dict:
    """⚠️ DEPRECATED + 禁用：alias 模式下不可用（不再依赖 user 维度反查身份）.

    历史用途（兜底身份识别路径）：
    - 当 dolphin chat session 没注入 [SYSTEM CTX 用户身份锚点] 时，agent 主动问
      用户"您登录 ai-builder 用的账号是什么"，拿到回答后调本工具反查身份
    - 后续所有 ai-builder MCP 工具调用必须带这里返回的 user_id / tenant_id

    安全说明：本工具**不验证调用方身份**（trial 阶段权宜方案）。LLM agent 信任
    用户自报的 username。正式环境应改用 dolphin SDK /api/embed/auth 真 SSO。

    返回：
      { ok: bool, user_id, tenant_id, tenant_name, username }
      或 _business_error（用户不存在 / 用户未激活 / 多租户需选择）
    """
    return _forbidden_in_alias_mode(
        "lookup_user_by_username",
        "list_apaas_apps(env='<你 agent 全局记忆里的 alias>')",
    )

    if not username or not username.strip():
        return _business_error(op="查找用户", error_text="username 参数不能为空")
    target = username.strip()

    from app.database import AsyncSessionLocal
    from app.models import User, UserTenant, Tenant
    from app.auth import resolve_default_tenant_id_for_user
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.username == target))
        ).scalar_one_or_none()
        if not user:
            return _business_error(
                op="查找用户",
                error_text=f"ai-builder 平台没有 username={target!r} 的用户。"
                "请用户确认账号拼写，或联系管理员开通账号。",
            )
        if not user.is_active:
            return _business_error(
                op="查找用户",
                error_text=f"用户 {target!r} 已被禁用，无法操作。",
            )

        tid = await resolve_default_tenant_id_for_user(db, user.id)
        tenant_name = ""
        if tid:
            t = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
            if t:
                tenant_name = t.tenant_name or t.tenant_code or ""

        # 同步把这个 user 的身份写到 current_app slot —— 后续 _resolve_identity
        # 反查时直接命中（即使 caller 没传 tenant_id，slot 里也有）
        try:
            from app.routes.current_app import set_current_app
            if tid:
                set_current_app(user.id, tid, 0, "")
        except Exception:
            pass

        return {
            "ok": True,
            "user_id": user.id,
            "tenant_id": tid or 0,
            "tenant_name": tenant_name,
            "username": user.username,
            "summary": (
                f"已识别用户 {user.username} (user_id={user.id}, tenant_id={tid}, {tenant_name})。"
                "请在后续所有 ai-builder MCP 工具调用中显式传 user_id 和 tenant_id 这两个参数。"
            ),
        }


@mcp.tool()
async def grant_app_access(
    app_id: int = 0,
    object_type: str = "ALL",
    object_ids: list[str] | None = None,
) -> dict:
    """配置应用的访问权限对象 —— 让租户用户能在 apaas 应用市场看到 / 打开应用。

    apaas 平台默认部署完应用后**对租户用户不可见**，必须显式开一次 appAccess。
    deploy_application 内部已经自动调一次 ALL（全员可访问），所以正常流程**不需要
    再单独调本工具**；以下场景才需要主动调：
      - 用户明确说"只开放给某些角色 / 部门 / 人"（object_type=ROLE/DEPT/USER）
      - 用户说"刚部署完看不到应用"（兜底重置 ALL）
      - 调整某个旧应用的访问范围

    object_type:
      - "ALL"：开放给租户内全部用户（推荐，object_ids 留空）
      - "ROLE" / "DEPT" / "USER"：按角色/部门/用户开放，object_ids 必填

    app_id 可省略（=0）：自动用当前编辑应用。
    """
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    app_id, _ = _resolve_app_id(app_id, uid)
    try:
        res = await _api_call(
            "POST",
            f"/applications/{app_id}/grant-access",
            tenant_id=tid,
            user_id=uid,
            json_body={
                "object_type": (object_type or "ALL").upper(),
                "object_ids": list(object_ids or []),
            },
            token_retry_app_id=app_id,
        )
    except RuntimeError as exc:
        return _business_error(op="配置应用访问权限", error_text=str(exc), app_id=app_id)
    return {
        "ok": True,
        "app_id": app_id,
        "apaas_app_id": res.get("apaas_app_id"),
        "object_type": res.get("object_type"),
        "object_ids": res.get("object_ids") or [],
        "summary": res.get("message"),
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def deploy_application(
    app_id: int = 0,
    env: str = "",
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 部署 ai-builder 应用到 aPaaS 平台。

    ⚠️ 已合并进 promote_draft_to_app 内部末段 —— 新流程**不要再调本工具**。
    本工具保留作老 agent 兼容入口 + 运维"重跑部署"场景。下面是原 docstring：

    把 ai-builder 内应用部署到 aPaaS 平台 — 首次部署 + 重跑兼用（apaas_app_id null=新建，非空=复用重推）。

    🆕 推荐：传 env="<alias>" + app_id（必填）
    ⚠️ env="" 时走老 slot 反查（app_id=0 → 当前编辑应用）

    两种模式：
      A. **首次部署**（apaas_app_id=null）：
         - client.create_app 在 apaas 创建应用拿 apaas_app_id
         - run_complete_generation 推所有字段/模型/表单/权限
      B. **重跑** ⭐（apaas_app_id 非空）：
         - **复用已有 apaas_app_id 不新建**
         - run_complete_generation 完整重推（不算 diff，强制 push）
         - 救活"半拉子"应用（apaas 0 模型但 ai-builder 觉得完整）

    内部统一调 SSE GET /applications/{app_id}/generate；
    25s 早返 + 后台 SSE shield（避开 dolphin omnigate 30s timeout）。

    与 publish_application 的关系：
      - deploy_application 部署 / 重跑（都不动 version）
      - publish_application 升 version 发布新版本（要先 deploy 过）

    ⭐ 治"半拉子"应用看 `force_regenerate_apaas_app(application_id, md_content?)`：
       内置 update_app_from_doc + deploy 一键操作，比直接 deploy 更便利。
    """
    if env:
        if not app_id or app_id <= 0:
            return _business_error(op="首次部署", error_text="alias 模式必须显式传 app_id")
        tid = await _resolve_alias_tid_for_app(app_id)
        uid = 1  # alias 模式 admin (platform_admin 跨 tenant 任意通行)
    elif env_id and env_id > 0:
        from app.mcp_request_ctx import get_mcp_ctx
        ctx = get_mcp_ctx()
        if ctx and ctx.apaas_token and ctx.apaas_tenant_id:
            tid, uid, header_env_id = await _resolve_mcp_service_identity_from_header()
            if int(env_id) != int(header_env_id):
                return _business_error(
                    op="首次部署",
                    error_text=(
                        f"请求 env_id={env_id} 与 Header aPaaS tenant 绑定环境 env_id={header_env_id} 不一致，"
                        "拒绝部署以避免串租户。"
                    ),
                    app_id=app_id,
                    extra={"requested_env_id": int(env_id), "header_env_id": int(header_env_id)},
                )
        else:
            tid = await _resolve_alias_tid_for_env(int(env_id))
            uid = 1
    else:
        tid, uid, _header_env_id = await _resolve_internal_identity_for_mcp(tenant_id, user_id)
        app_id, _ = _resolve_app_id(app_id, uid)

    # SSE generate 接口要 ?token= query param（历史包袱：SSE 前端 EventSource 不能设
    # Authorization header），后端只读 query 不读 header。我们这里照旧给一份 service token。
    sse_token = _sign_service_token(uid, tid)

    # 🆕 2026-05-11：dolphin omnigate MCP 调用死设 30s timeout，但中型应用 SSE
    # generate 完整推完 model/form/permission 经常要 30-60s（实测宝洁 #244 跑 33s
    # backend 实际成功但 dolphin 返 BAD_GATEWAY context deadline exceeded）。
    # 改成：25s 内能跑完直接返完整结果；25s 没跑完 → 后台 task 继续跑剩余 SSE，
    # 工具立即返 {status:'in_progress'} 让 agent 30s 后用 get_application 查
    # apaas_app_id / status 是否已写入。
    import asyncio as _asyncio
    FAST_RETURN_TIMEOUT = 25.0

    async def _run_full_sse() -> dict:
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
        in_progress = False
    except _asyncio.TimeoutError:
        # 后台 task 继续跑（_asyncio.shield 保护不被 cancel），工具立即返
        logger.info(
            "deploy_application app_id=%s SSE generate >%.0fs 未完成，后台继续跑，工具立即返 in_progress",
            app_id, FAST_RETURN_TIMEOUT,
        )
        return {
            "ok": True,
            "app_id": app_id,
            "status": "in_progress",
            "summary": (
                f"部署已启动并在后台继续运行（generate 流 >{int(FAST_RETURN_TIMEOUT)}s 还在跑，"
                "dolphin MCP 30s timeout 限制下提前返回避免 BAD_GATEWAY）。"
                "**下一步**：等 30-60 秒后用 `get_application(app_id={app_id})` 查 "
                "`apaas_app_id` 是否已写入 + `status` 是否 = `completed`。如果是就部署成功，"
                "把 `apaas_url` 给用户作为访问地址。如果还是 in_progress 就再等一会儿再查。"
            ).format(app_id=app_id),
            "polling_hint": {
                "next_tool": "get_application",
                "next_args": {"app_id": app_id},
                "wait_seconds": 30,
            },
        }

    if sse.get("errors"):
        # 业务错误结构化返回，让 agent 必读 error_code / user_action_required
        return _business_error(
            op="首次部署",
            error_text=sse["errors"][0],
            app_id=app_id,
            extra={"all_errors": sse["errors"][:3]},
        )

    # 看是否走到了 complete 事件
    completed = any(
        (e.get("data") or {}).get("type") == "complete"
        or e.get("event") == "done"
        for e in sse.get("events") or []
    )

    # 反查应用当前状态把 apaas_app_id 顺便回报给 agent
    app_now = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)
    apaas_app_id = (app_now or {}).get("apaas_app_id") or (app_now or {}).get("apaasAppId")
    status = (app_now or {}).get("status")
    # apaas 平台后台直达链接（部署成功后 apaas_app_id 已写入，internal API 已返回 apaas_url）
    apaas_admin_url = (app_now or {}).get("apaas_url")

    return {
        "ok": completed and bool(apaas_app_id),
        "app_id": app_id,
        "apaas_app_id": apaas_app_id,
        "status": status,
        # ⭐ 给用户的访问地址用这个（apaas 真后台）
        "apaas_admin_url": apaas_admin_url,
        "events_count": len(sse.get("events") or []),
        "summary": (
            f"首次部署完成！应用已在 aPaaS 平台创建并配置完毕（apaas_app_id={apaas_app_id}）。"
            f"用户可直接打开低代码后台管理：{apaas_admin_url}。"
            "**给用户响应时，把 apaas_admin_url 作为'访问地址'链接出来，不要再用 ai-builder 内部 chat 页。**"
            if completed and apaas_app_id
            else "部署未完整完成，请用 get_application 检查 apaas_app_id 和 status，或查看后端日志。"
        ),
    }


@mcp.tool()
async def force_regenerate_apaas_app(
    application_id: int,
    md_content: str = "",
) -> dict:
    """💪 强制重跑 apaas 应用 generation pipeline（一键重跑，治"半拉子"应用）。

    ⭐ 跟 update_app_from_doc + execute_change_plan 不同：
       本工具**不算 diff**，完整重跑 SSE generate pipeline 把 spec **强制 push** 到 apaas。

    适用场景：
      - apaas 平台只建了应用骨架但 model 0 个（generate 中段失败）
      - ai-builder 内部 config_preview 完整但 apaas 实际 partial state
      - update_app_from_doc + execute_change_plan 报 "无变更需要同步" 但 apaas 实际缺东西
      - 任何 "ai-builder 觉得已完成但 apaas 实际不对" 的不同步状态

    工作流（2 步内置）：
      1. 若传 md_content → 先调 update_app_from_doc 把新 spec 覆写到 config_preview
         （内部用 upload-doc-version 解析新 md 覆写）
      2. 调 SSE GET /applications/{id}/generate 复用 apaas_app_id 完整重跑：
         - run_complete_generation 不算 diff，所有 spec 内容都重推
         - apaas_app_id 复用（不新建应用）
         - 模型/字段/表单/菜单/权限 全 batch push
         - 25s 早返 + 后台 SSE shield（避开 dolphin omnigate 30s timeout）

    使用前提：
      - app.apaas_app_id 非空（已经在 apaas 平台有应用记录）
      - app.config_preview 非空（spec 内部解析过）

    ⚠️ 跟 deploy_application 的区别：
      - deploy_application 主用于首次部署（apaas_app_id=null → create）
      - force_regenerate_apaas_app 专为"修复半拉子已部署应用"，可选传 md_content 一键更新+重跑

    返回（同 deploy_application）：
      - 25s 内跑完 → {status:"completed", summary, app_id, apaas_app_id}
      - 25s 没跑完 → {status:"in_progress", hint:"30s 后调 get_application 查状态"}
      - 撞 apaas 平台错（如模型编码重复）→ _business_error 含详细错诊断
    """
    if not application_id or application_id <= 0:
        return _business_error(
            op="force_regenerate_apaas_app",
            error_text="必须传 application_id（ai-builder 内部应用 id）",
        )

    # Step 1: 若给了 md_content，先 update_app_from_doc 覆写 spec
    if md_content and md_content.strip():
        logger.info(
            "force_regenerate_apaas_app app_id=%s 先 update spec（md_content 长度 %s）",
            application_id, len(md_content),
        )
        upd = await update_app_from_doc(
            md_content=md_content,
            app_id=application_id,
        )
        if not upd.get("ok", True):
            return _business_error(
                op="force_regenerate_apaas_app",
                error_text=f"Step 1 update_app_from_doc 失败：{upd.get('message', '')}",
                extra={"update_result": upd},
            )

    # Step 2: deploy_application 一键重跑 SSE generate（复用 apaas_app_id）
    logger.info(
        "force_regenerate_apaas_app app_id=%s Step 2 调 deploy_application 重跑 SSE generate",
        application_id,
    )
    dep = await deploy_application(
        app_id=application_id,
    )
    # 透传 deploy_application 返回，但 op 改成 force_regenerate 让用户看清楚
    if isinstance(dep, dict) and "op" in dep:
        dep["op"] = "force_regenerate_apaas_app"
    return dep


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def publish_application(
    app_id: int = 0,
    env: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 发布应用新版本。

    ⚠️ 已合并进 promote_draft_to_app / apply_draft_to_live_app 内部 —— 新流程不需要再调。
    本工具保留作运维"手动发版"场景。下面是原 docstring：

    把已部署应用发布新版本（version 升号）。

    🆕 推荐：传 env="<alias>" + app_id（必填）
    ⚠️ env="" 时走老 slot 反查（app_id=0 → 当前编辑应用）

    前置：apaas_app_id 必须非空（应用已通过 deploy_application 完成首次部署）。
    若 apaas_app_id 为空会被后端 400 拒收，应该先调 deploy_application。
    """
    if env:
        if not app_id or app_id <= 0:
            return _business_error(op="发布版本", error_text="alias 模式必须显式传 app_id")
        tid = await _resolve_alias_tid_for_app(app_id)
        uid = 1  # alias 模式 admin (platform_admin 跨 tenant 任意通行)
    else:
        tid, uid = await _resolve_identity(tenant_id, user_id)
        app_id, _ = _resolve_app_id(app_id, uid)
    try:
        res = await _api_call(
            "POST", f"/applications/{app_id}/publish",
            tenant_id=tid, user_id=uid,
            token_retry_app_id=app_id,
        )
    except RuntimeError as exc:
        return _business_error(op="应用上线", error_text=str(exc), app_id=app_id)
    # publish 完反查拿 apaas_admin_url，让 agent 给用户后台直达链接
    try:
        app_now = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)
        apaas_admin_url = (app_now or {}).get("apaas_url")
    except Exception:
        apaas_admin_url = None
    return {
        "ok": True,
        "app_id": app_id,
        "result": res,
        "apaas_admin_url": apaas_admin_url,
        "summary": (
            f"新版本发布完成！用户可直接打开低代码后台：{apaas_admin_url}"
            if apaas_admin_url
            else "新版本发布完成，但 apaas_admin_url 拿不到，可调 get_application 复查。"
        ),
    }


# ═════════════════════════════════════════════════════════════════════════
# Draft 工作流工具（P2 新增）
#
# 新流程：agent 用这一组工具替代 validate_builder_doc / parse_design_doc /
# generate_app_from_doc / deploy_application / publish_application 的散调。
#
#   save_design_draft(md)        → draft_id + preview_url
#   get_draft_summary(draft_id)  → 摘要（不返回 md 全文）
#   promote_draft_to_app(draft_id) → 创建+部署+发布，一步到位
#   patch_design_draft(draft_id, action) → 局部改（P4 实现）
#   apply_draft_to_live_app(draft_id)    → 同步到既有应用（P4 实现）
# ═════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def save_design_draft(
    md_content: str,
    parent_app_id: int = 0,
) -> dict:
    """保存设计文档。**新流程入口**，替代 validate_builder_doc + parse_design_doc。

    Agent 工作流：
      用户："帮我建一个 X 系统"
      → 你最多问 1-2 轮关键澄清；如果用户已回答业务主流程/范围/角色方案，就不要继续追问
      → 你生成完整 md_content
      → 调本工具一次，拿 draft_id + preview_url
      → 聊天里只输出"设计文档已生成 + 预览链接"，**不要贴全文**
      → 用户确认后调 promote_draft_to_app(draft_id)

    硬性契约：
    - 必须把完整 Markdown 正文作为 md_content 传入本工具。
    - 本工具不接收 /workspace/*.md 文件路径；如果你先写了文件，必须读取文件内容再传 md_content。
    - AI Chat 内部调用本工具时，会自动把 md_content 保存到右侧"设计文档"面板，并返回 HTML 效果预览链接。
      因此不要为了同一份 Builder 设计文档先调用 write_artifact 再调用本工具。
    - 禁止只生成本地文件/附件后停止，或把"/workspace/xxx.md 已生成"当作设计文档已生成。
    - 调过 get_doc_template_spec 后，下一步必须直接组织 md_content 并调用本工具；不要停在"已拿模板"。
    - 业务流程指真实业务主链路，例如"入库 → 库存 → 出库 → 盘点 → 预警"，不是"需求成稿 / 表单承载 / 权限分配 / 构建发布"。
    - 角色只生成应用内业务权限角色；普通员工/部门主管/直属上级/部门/人员管理都是平台内置组织能力，不要写入角色列表。
      需要管理员时用带应用语义的编码（如 meeting_admin、meet_mgmt_admin），不要用 sys_admin。
      表单需要组织归属时添加"所属部门"字段，审批负责人写成"发起人所属部门负责人"这类组织规则。
    - 如果返回 DOC_MODULE_PARSE_FAILED / failed_modules=forms,permissions，表示文档章节没按模板解析通过，
      不是文件传输限制；应重写对应章节后重新调用本工具。

    服务端内部自动完成：标准度校验 → md→spec_json 解析 → 落库。
    失败时返回 structured error，level=freeform 表示文档不合标准（需重写），
    level=partial 表示有警告但能用（仍可继续）。

    参数：
    - md_content：完整标准 markdown 文档
    - parent_app_id：可选；整份替换既有应用时传，否则不传（新建场景）
    """
    from app.draft_service import save_design_draft as _save
    from app.database import AsyncSessionLocal

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    async with AsyncSessionLocal() as db:
        return await _save(
            db,
            tenant_id=tid,
            user_id=uid,
            md_content=md_content,
            parent_app_id=parent_app_id or None,
        )


@mcp.tool()
async def get_draft_summary(
    draft_id: str,
) -> dict:
    """查 draft 摘要（**不返回 md 全文**，保护 agent 上下文）。

    返回 status / summary / preview_url / app_id（如已 promote） 等元信息。
    要看完整内容请用预览页 URL，不要让 agent 把 md 拉回上下文。
    """
    from app.draft_service import get_draft_summary as _get
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await _get(db, draft_id)


@mcp.tool()
async def promote_draft_to_app(
    draft_id: str,
    env: str = "",
    env_id: int = 0,
) -> dict:
    """把 draft 部署成新应用。**新流程出口**，替代 generate_app_from_doc + deploy_application + publish_application 串调。

    服务端内部自动完成：
      1. 读 draft.md_content
      2. 创建 ai-builder 应用（含 model/dict/form/permission）
      3. 推到 aPaaS 平台拿 apaas_app_id + admin_url
      4. 回填 draft.app_id / apaas_app_id / admin_url, 标 status='promoted'

    返回 {ok, draft_id, app_id, local_app_id, apaas_app_id, admin_url, status, id_guide, next_actions}。
    注意：
      - app_id/local_app_id 是 AI Builder/MCP 本地应用 ID，只能用于 get_application(app_id=...) 等本地接口。
      - apaas_app_id 是 aPaaS 平台发布应用 ID，republish_apaas_app / 自开发 / aPaaS 查询工具必须用它。
      - 给用户展示时必须同时列出两者，尤其明确“发布应用 ID = apaas_app_id”，禁止把 app_id 当 apaas_app_id。
      - 如果用户指定过目标环境，必须把环境别名传给 env；不传时才使用 MCP Header 解析出的当前环境。
    deploy 超过 25s 时 status='in_progress'，agent 等 30s 后用 get_application 复查。
    """
    from app.draft_service import promote_draft_to_app as _promote
    from app.database import AsyncSessionLocal

    resolved_tenant_id, resolved_user_id, header_env_id = await _resolve_internal_identity_for_mcp()
    effective_env_id = int(env_id) if env_id and env_id > 0 else header_env_id
    async with AsyncSessionLocal() as db:
        return await _promote(
            db,
            draft_id=draft_id,
            env=env,
            env_id=effective_env_id,
            tenant_id=resolved_tenant_id,
            user_id=resolved_user_id,
        )


@mcp.tool()
async def patch_design_draft(
    draft_id: str,
    action: dict,
) -> dict:
    """对 draft 打补丁，生成新版 draft（不修改原 draft，保留版本链）。

    支持的 op：
      - add_field / update_field / delete_field
      - add_role / delete_role
      - set_permission
      - add_dict_option

    示例 action：
      {"op": "add_field", "model": "customer",
       "field": {"code": "customer_level", "name": "客户等级",
                 "type": "下拉单选", "dictCode": "customer_level"}}
    """
    from app.draft_service import patch_design_draft as _patch
    from app.database import AsyncSessionLocal

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    async with AsyncSessionLocal() as db:
        return await _patch(db, draft_id=draft_id, action=action, user_id=uid, tenant_id=tid)


@mcp.tool()
async def apply_draft_to_live_app(
    draft_id: str,
) -> dict:
    """把新版 draft 同步到既有应用（增量更新）。

    服务端会拉取 draft 绑定的 app_id，生成变更计划并执行同步。
    这是修改既有应用的主流程出口，替代 update_app_from_doc + execute_change_plan 的散调。
    """
    from app.draft_service import apply_draft_to_live_app as _apply
    from app.database import AsyncSessionLocal

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    async with AsyncSessionLocal() as db:
        return await _apply(db, draft_id=draft_id, user_id=uid, tenant_id=tid)


def _do_validate_builder_doc(md_content: str) -> dict:
    """validate_builder_doc 的纯函数实现（无 IO，可单独单测）。"""
    from app.doc_standard_detector import detect, diagnose_weak_sections
    from app.doc_pipeline import _strip_template_scaffolding
    from app.doc_spec_standard import SECTION_KEY_TO_DISPLAY

    if not md_content or not md_content.strip():
        return {
            "ok": False,
            "score": 0,
            "level": "freeform",
            "decision": "rewrite_first",
            "passes_strict": False,
            "missing_sections": [
                SECTION_KEY_TO_DISPLAY[k]
                for k in ("app_info", "models", "permissions")
            ],
            "weak_sections": [],
            "weak_sections_detail": [],
            "signals": {},
            "advice": [
                "md_content 是空的，先调 get_doc_template_spec 拿完整 spec，"
                "再按里面的标准模板逐章写出来。"
            ],
        }

    cleaned = _strip_template_scaffolding(md_content)
    result = detect(cleaned)
    score = int(result.get("score") or 0)
    missing = result.get("missing_sections") or []
    weak = result.get("weak_sections") or []
    signals = result.get("signals") or {}

    # 关键升级：每个 weak 章节给出 actual vs expected 的列名 diff，agent 能定向修
    weak_sections_detail = diagnose_weak_sections(cleaned)

    advice: list[str] = []
    if missing:
        advice.append(
            f"缺失必填章节：{', '.join(missing)}。补齐 ## 标题 + 标准表格 "
            "（章节标题样例和列序见 get_doc_template_spec 返回）。"
        )

    # weak_sections_detail 比文字 advice 更可定位，但也保留人话版作为 backup
    for diag in weak_sections_detail:
        section = diag["section"]
        actual = diag.get("actual_headers") or []
        missing_req = diag.get("missing_required") or []
        extra = diag.get("extra_unused") or []
        full_cols = diag.get("expected_full") or []
        sub = diag.get("subsection")
        sub_hint = f"（子章节：{sub}）" if sub else ""
        parts = [f"「{section}」{sub_hint}表头不达标"]
        if actual:
            parts.append(f"实际表头={actual}")
        if missing_req:
            parts.append(f"缺少必有列={missing_req}")
        if extra:
            parts.append(f"多余/错别字={extra}")
        if full_cols:
            parts.append(f"完整列序应为={full_cols}")
        advice.append("；".join(parts))

    if (signals.get("code_compliance") or 1.0) < 0.9:
        advice.append(
            "编码字段不规范：appCode 用 kebab-case（小写字母+数字+`-`，≤17，字母开头），"
            "其它编码（角色/字典/模型/字段/表单）用 snake_case（小写字母+数字+`_`，字母开头）。"
            "禁用 apaas/xdap 前缀和数据库关键字。原文已有合法编码时必须原样保留，"
            "不要为了“更像 snake_case”主动拆词加下划线；只有非法/重复/保留字/超长时才最小改名并说明映射。"
        )
    if (signals.get("ref_integrity") or 1.0) < 0.9:
        advice.append(
            "引用不闭合：5.2/5.4 字典编码列填的字典必须在第三章声明，"
            "目标模型编码列填的模型必须在第四章 4.1 声明。"
        )
    if (signals.get("header_format") or 1.0) < 0.9:
        advice.append(
            "章节标题格式：用 `## 一、应用信息` / `## 二、角色列表` ... `## 七、权限定义` "
            "的中文数字编号（不要用「权限矩阵」——那是历史叫法）。"
        )

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
            f"未达标（{score}/100，门槛 90）：按 weak_sections_detail 里的 missing_required 修表头，再重跑。"
        )
    else:
        advice.append(
            f"严重偏离模板（{score}/100）：先调 get_doc_template_spec 拿完整 spec，"
            "按里面的 STANDARD_DOC_FORMAT 重写标准骨架再校验。"
        )

    return {
        "ok": True,
        "score": score,
        "level": result.get("level"),
        "decision": result.get("decision"),
        "passes_strict": passes,
        "missing_sections": missing,
        "weak_sections": weak,
        "weak_sections_detail": weak_sections_detail,
        "signals": signals,
        "advice": advice,
    }


@mcp.tool()
async def get_doc_template_spec() -> dict:
    """拿到 aPaaS Builder 设计文档的**完整官方标准**（章节 / 表头 / 命名规则 / 字段类型）。

    **强烈建议第一次写设计文档之前先调本工具一次**——这是 single source of truth，
    优先级高于 Skill 里贴的任何模板片段。Skill 里的模板若与本工具返回不一致，
    一律以本工具为准（守门用的 detector / parser 也是从同一份 spec 派生）。

    用法（典型 req-design 流程）：
      step 0: get_doc_template_spec()                     ← 现在
      step 1: 如果用户已回答 1-2 轮关键问题，立刻按 sections + table_headers_full 写标准 md；有审批/流转就写流程配置
      step 2: 调 save_design_draft(md_content)，不要停在"模板已获取"
      step 3: 给 preview_url，并让用户确认"开始创建 / 继续修改"

    返回：
        {
          "spec_version": "2026-05-07",
          "sections": [
            {"order": 1, "key": "app_info", "title_example": "## 一、应用信息",
             "display_name": "应用信息", "required": true},
            ...
            {"order": 7, "key": "permissions", "title_example": "## 七、权限定义", ...}
          ],
          "table_headers_full": {        # 写文档时按这个完整列序写
            "app_info": ["项目", "内容"],
            "roles": ["角色编码", "角色名称"],
            "models_field": ["模型编码", "字段编码", "字段名称", "数据库字段类型", "长度/精度"],
            "forms_main": [..14 列..],
            "forms_sub": [..15 列..],
            "permissions": [..10 列..],
            ...
          },
          "table_headers_required": {    # detector 必检的列（少了就扣分）
            ...
          },
          "component_types": [...],       # 组件类型枚举（25 个主名）
          "component_type_aliases": {...},# 用户口语 → 标准名
          "db_field_types": [...],        # 数据库类型枚举（7 个）
          "data_scopes": [...],           # 第六章数据范围枚举（4 个）
          "dict_bound_components": [...], # 5.2/5.4 字典编码列必填的组件
          "ref_bound_components": [...],  # 5.2/5.4 目标模型编码列必填的组件
          "naming_rules": {...},          # 应用编码 / snake_case 等命名正则
          "reserved_process_fields": [...],   # 流程模块保留字段（写进模型必报错）
          "reserved_generic_names": [...],    # 通用短名禁用清单
          "standard_doc_format_md": "..." # 完整人话版模板（可直接给 LLM 注入）
        }
    """
    from app.doc_spec_standard import build_template_spec
    spec = build_template_spec()
    return {
        "ok": True,
        **spec,
        "agent_next_action": {
            "do_now": "generate_complete_md_and_call_save_design_draft",
            "must_not_stop_after_this_tool": True,
            "must_not_ask_more_if_user_answered_key_scope": True,
            "clarifying_question_limit": "1-2 rounds maximum before first draft",
            "business_flow_definition": "真实业务主链路，例如入库→库存→出库→盘点→预警；不是需求成稿/表单承载/权限分配/构建发布",
            "example_for_consumables": "耗材/物资管理简化版可直接按：耗材档案、入库、领用/出库、库存台账；可选加盘点、预警。",
        },
    }


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def validate_builder_doc(md_content: str) -> dict:
    """[DEPRECATED] 校验 md 文档格式。

    ⚠️ 新流程不需要再调本工具 —— save_design_draft 内部会自动跑校验，
    校验不过会直接以 structured error 形式返回，agent 拿到 errors 转述用户即可。

    本工具保留作老 agent 兼容入口。下面是原 docstring：

    建议工作流（旧）：
      0. 第一次写文档前 → 调 get_doc_template_spec 拿完整 spec（章节 / 表头 / 命名规则）
      1. 写完 md → 调 validate_builder_doc 自检
      2. passes_strict=False → 优先按 weak_sections_detail 里的 actual vs expected 列名 diff 修，
         再按 missing_sections / advice 补章节
      3. 重复至多 3 轮；仍不通过把问题原文列给用户决定
      4. passes_strict=True 才把 md 输出给用户（或直接用 generate_app_from_doc / parse_design_doc）

    返回：
        {
          "ok": True,
          "score": 0-100,                   # 综合分
          "level": "standard|partial|freeform",
          "decision": "pure_code|hybrid_fallback|rewrite_first",
          "passes_strict": bool,            # score >= 90 且无 missing_sections，后端可纯代码解析
          "missing_sections": [str],        # 缺的必填章节中文名
          "weak_sections": [str],           # 表头不达标的章节中文名（人话清单）
          "weak_sections_detail": [          # ← 新：每个 weak 章节的 actual vs expected diff
              {
                "section": "数据模型",
                "key": "models",
                "actual_headers": [...],     # agent 实际写的表头
                "expected_required": [...],  # 必有列
                "expected_full": [...],      # 完整 14/15 列等
                "missing_required": [...],   # 缺哪几列必有列
                "extra_unused": [...],       # 多了哪几列（很可能错别字）
                "table_index": int,
                "subsection": str|null,      # 字典等子章节场景填子章节名
              }, ...
          ],
          "signals": {                       # 5 维子项打分（0~1）
              "section_coverage": ...,       # 必填章节覆盖率（30 分权重）
              "header_format": ...,          # ## N、名称 标题格式（15 分）
              "table_header_match": ...,     # 表头与标准模板匹配率（25 分）
              "code_compliance": ...,        # 编码字段命名合规（15 分）
              "ref_integrity": ...           # 字典/模型引用闭合（15 分）
          },
          "advice": [str],                  # 给 agent 的下一步修补建议（人话）
          "parse_dryrun": {                  # ← 新：让 validate 通过 = parse 一定通过
              "ok": bool,                    # parse_document(strict=True) 是否成功
              "failed_modules": [str],       # 失败模块（dicts/forms/models 等）
              "error": str|null,             # 失败时的原始错误文案
          }
        }

    关键升级（2026-05-07 后）：当 detector passes_strict=True 时再 dry-run 一次
    parse_document（strict 模式）让真后端 parser 也跑一遍。如果 parser 失败
    （历史上常见的"validate 通过但 generate_app_from_doc 失败"问题），把 parse 错误
    回写到 weak_sections_detail + 把 passes_strict 改回 False，避免 agent 自信地
    走到 generate_app_from_doc 才被打脸。
    """
    res = _do_validate_builder_doc(md_content)
    # 仅当 detector 认为通过时再 dry-run 一次 parser；不通过的 md 没必要再跑
    if res.get("passes_strict"):
        try:
            from app.doc_pipeline import parse_document, DocNotStandardError
            await parse_document(md_content)
            res["parse_dryrun"] = {"ok": True, "failed_modules": [], "error": None}
        except DocNotStandardError as exc:
            failed_modules = list(getattr(exc, "failed_modules", []) or [])
            res["parse_dryrun"] = {
                "ok": False,
                "failed_modules": failed_modules,
                "error": str(exc),
            }
            # 拉低 passes_strict + score，让 agent 不要继续走 generate_app_from_doc
            res["passes_strict"] = False
            res["score"] = min(int(res.get("score") or 0), 89)
            res["advice"].insert(0, (
                f"⚠️ detector 打分通过（{res['score']+1}+ 分），但实际后端 parser 失败！"
                f"failed_modules={failed_modules}。原始错误：{str(exc)[:300]}。"
                "这是『validate 标准 ≠ parse 标准』的边角情况。请按 failed_modules 检查："
                "(1) 章节标题是否用 ## 一、应用信息 中文数字编号格式；"
                "(2) 数据模型 4.2 的 5 列是否齐：模型编码|字段编码|字段名称|数据库字段类型|长度/精度；"
                "(3) 表单定义 5.2/5.4 的 14/15 列是否齐；"
                "(4) 字典是否每个用 `### N.M 字典名` 子章节 + 选项表；"
                "(5) 调 get_doc_template_spec 拿完整列序对照检查。"
            ))
        except Exception as exc:
            # 其它异常（比如 LLM 调用？）兜底——记下来但不阻断 agent
            res["parse_dryrun"] = {
                "ok": False,
                "failed_modules": [],
                "error": f"parse_document 试运行异常（非 DocNotStandardError）：{exc!s:.300s}",
            }
            res["advice"].append(
                f"⚠️ parse 试运行抛了非预期异常：{exc!s:.200s}（不阻断，可继续 generate_app_from_doc 试试）"
            )
    else:
        # detector 没通过的就不需要 dry-run（节省时间），placeholder 让结构完整
        res["parse_dryrun"] = {"ok": None, "failed_modules": [], "error": None}
    return res


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


# @mcp.tool()  # [DEPRECATED] unregistered 2026-05-14 — see ai-builder-架构方案-v1.md
async def submit_design_doc(
    md_content: str,
    file_name: str = "design-doc.md",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[DEPRECATED] 把 md 推到 ai-builder cache + 返回 deeplink。

    ⚠️ 已被 save_design_draft 替代 —— 新流程返回 preview_url 给用户点，作用一致但更直观。
    本工具保留作老 agent 兼容入口。下面是原 docstring：

    把当前 md 设计文档推送到 ai-builder cache，并返回一条 deeplink — agent 必须把这条
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

    tid, uid = await _resolve_identity(tenant_id, user_id)
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
# ║  dev-coding skill 工具组（V1 — 协调层模式）                                ║
# ║  ─────────────────────────────────────────────────────────────────────── ║
# ║  把 ai-builder /coding 自开发能力暴露给 dolphin 浮窗。dolphin agent 做     ║
# ║  场景识别 / 需求确认 / 创建 workspace；vibe_agent 仍负责真正写代码——      ║
# ║  V1 通过 deeplink 把用户引导到 ai-builder UI 继续协作。V2 再考虑 SSE 异步  ║
# ║  推进度回浮窗。                                                            ║
# ║                                                                            ║
# ║  设计：跟现有 17 个工具同款——内部 _api_call 调本机现有 endpoint，          ║
# ║       绝不重写业务逻辑。dev_scene_spec 是 single source of truth。          ║
# ═══════════════════════════════════════════════════════════════════════════


def _build_coding_deeplink(ws_id: str, auto_run: bool = False) -> str:
    """拼 ai-builder /coding 的 deeplink，让用户从 dolphin 跳进去继续。

    base 跟 chat deeplink 复用同一个 settings 项；空时返回空串，agent 应给提示
    让用户自己去 ai-builder 菜单「AI 编码」找到该工作区。

    auto_run=True 时加 &auto_run=1 query 参数，前端 CodingPage 检测到会从
    .coding-pending-requirement.txt 拉用户在 dolphin 整理的需求 brief 自动跑
    vibe_agent，免得让用户跨页面复制粘贴。
    """
    url = _ai_builder_ui_url(f"/coding?ws_id={ws_id}")
    if auto_run:
        url += "&auto_run=1"
    return url


def _make_ai_builder_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    normalized = path if path.startswith("/") else f"/{path}"
    if normalized.startswith("/api/"):
        base = (settings.ai_builder_api_public_base or "https://df-aigc.dfy.definesys.cn").rstrip("/")
        return f"{base}/ai-builder{normalized}"
    return _ai_builder_ui_url(normalized)


def _with_absolute_artifact_urls(payload: dict) -> dict:
    last_build = payload.get("last_build")
    if not isinstance(last_build, dict):
        return payload
    artifacts = last_build.get("artifacts")
    if not isinstance(artifacts, dict):
        return payload
    download_url = artifacts.get("download_url")
    if download_url:
        artifacts = {
            **artifacts,
            "download_url": _make_ai_builder_url(str(download_url)),
        }
        payload = {
            **payload,
            "last_build": {
                **last_build,
                "artifacts": artifacts,
            },
        }
    return payload


@mcp.tool()
async def get_dev_scene(
    scene_type: str = "",
    detail: str = "list",
) -> dict:
    """自开发场景统一入口（合并 list_dev_scenes / get_dev_scene_spec / get_dev_scene_full_workflow）。

    用法：
        detail="list"      → 列所有场景（精简，含 keywords/one_liner，用于识别）
        detail="spec"      → 单场景规范（critical_warnings / user_inputs_needed / file_outline）
        detail="workflow"  → 单场景完整开发 markdown（critical rules / 目录铁则 / 自检清单）

    典型链路：
        get_dev_scene(detail="list") → 用户确认 →
        get_dev_scene(scene_type=X, detail="spec") → 跟用户对齐参数 →
        get_dev_scene(scene_type=X, detail="workflow") → 注入 chat → create_dev_workspace
    """
    from app.dev_scene_spec import list_scene_briefs, get_scene_brief, all_scene_types, SPEC_VERSION

    if detail == "list":
        return {
            "ok": True,
            "spec_version": SPEC_VERSION,
            "scenes": list_scene_briefs(),
        }

    if not scene_type:
        return {
            "ok": False,
            "op": "get_dev_scene",
            "error_code": "MISSING_SCENE_TYPE",
            "message": f"detail={detail} 需要传 scene_type",
            "valid_scene_types": all_scene_types(),
            "should_retry": False,
        }

    if scene_type not in all_scene_types():
        return {
            "ok": False,
            "op": "get_dev_scene",
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知 scene_type: {scene_type}",
            "valid_scene_types": all_scene_types(),
            "should_retry": False,
        }

    if detail == "spec":
        return {"ok": True, "scene": get_scene_brief(scene_type)}

    if detail == "workflow":
        from app.dev_scene_workflow import get_full_workflow, has_full_workflow
        return {
            "ok": True,
            "scene_type": scene_type,
            "has_full_workflow": has_full_workflow(scene_type),
            "workflow_markdown": get_full_workflow(scene_type),
        }

    return {
        "ok": False,
        "op": "get_dev_scene",
        "error_code": "INVALID_DETAIL",
        "message": f"detail 取值非法: {detail}（应为 list|spec|workflow）",
        "should_retry": False,
    }


# @mcp.tool()  # [MERGED] -> get_dev_scene(scene_type, detail="spec")
async def get_dev_scene_spec(scene_type: str) -> dict:
    """拿到某个自开发场景的**完整规范**（关键警示 / 必问参数 / 输出文件清单 / 部署提示）。

    在 list_dev_scenes 选定 scene_type 后**必调一次**，把 critical_warnings 和
    user_inputs_needed 给用户看一遍——很多场景有静默失效的坑（比如表单组件读
    配置必须 this.widget.customComponentConfig 不是 this.customComponentConfig），
    用户提前知道能避免后续 vibe_agent 跑出来不能用。

    入参：
        scene_type: list_dev_scenes 返回的某个 scene_type 字符串值

    返回：
        {
          "ok": true,
          "scene": {
            "scene_type": "...",
            "name": "...",
            "one_liner": "...",
            "category": "frontend|backend",
            "platform": "web|mobile|both|server",
            "when_to_use": [...],
            "when_NOT_to_use": [...],
            "user_inputs_needed": [...],
            "user_inputs_optional": [...],
            "file_outline": [...],
            "typical_duration_min": [min, max],
            "critical_warnings": [...],
            "publishable": true,
            "publish_target": "aPaaS 平台",
            "build_command_hint": "npm run build"
          }
        }

    scene_type 不存在时返回 ok:false + error_code SCENE_NOT_FOUND。
    """
    from app.dev_scene_spec import get_scene_brief, all_scene_types
    scene = get_scene_brief(scene_type)
    if scene is None:
        return {
            "ok": False,
            "op": "get_dev_scene_spec",
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知的 scene_type: {scene_type}。可选值：{', '.join(all_scene_types())}",
            "valid_scene_types": all_scene_types(),
            "user_action_required": "回到 list_dev_scenes 重新选场景类型。",
            "should_retry": False,
        }
    return {"ok": True, "scene": scene}


@mcp.tool()
async def get_recent_app_context(
) -> dict:
    """**coding agent Phase 1 第一步建议调** —— 拿当前用户最近操作的 apaas 应用上下文。

    用途（场景 1: 用户先 builder 建系统再 coding 自开发）：
    - builder agent 部署应用成功后会自动写 _USER_RECENT_APP_CONTEXT cache
    - coding agent 启动时**先调本工具**：
      - 命中 → prefill 应用上下文（app_id / app_code / app_name / web_url /
        forms 列表带 form_id 和 default_tab_id）→ **跳过** list_apaas_apps_in_env /
        list_apaas_app_menus / list_apaas_form_views 几个工具调用，直接进 SPEC 阶段
      - 未命中 → 走原流程从 list_platform_envs 开始
    - 也可以用来确认"用户接力来"的场景：用户从 builder agent 完成后跳转 /ai-coding
      （deeplink 带 handoff_token），coding agent 通过 cache 直接知道做哪个 app

    返回（命中）：
        {
          "ok": true,
          "has_context": true,
          "context": {
            "apaas_app_id": "840391894029565952",
            "app_code": "lc-ops-mgmt",
            "app_name": "低代码平台运营管理系统",
            "env_id": 12,
            "web_url": "...",
            "mobile_url": "...",
            "tenant_code": "bj",
            "current_version": "1.0.8",
            "forms": [
              {"form_id": "69fcc477...", "form_code": "course", "form_name": "课程",
               "default_tab_id": "69fcc477...9d"}
            ],
            "last_action": "created" | "updated" | "attached" | "published",
            "last_actor": "builder" | "coding",
            "updated_at": 1778290000,
          },
          "next_action": "已 prefill 应用上下文，可直接进 Phase 1 SPEC（跳过 list_apaas_apps_in_env / list_apaas_app_menus）"
        }

    返回（未命中）：
        {"ok": true, "has_context": false}
    """
    return _forbidden_in_alias_mode(
        "get_recent_app_context",
        "list_apaas_apps(env='<alias>') 直接列租户应用",
    )

    from app.routes.user_coding_session import get_user_recent_app_context_dict
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    cached = get_user_recent_app_context_dict(uid)
    if not cached:
        return {
            "ok": True,
            "has_context": False,
            "next_action": "未命中 cache。走原流程：list_platform_envs → list_apaas_apps_in_env → list_apaas_app_menus → ...",
        }
    return {
        "ok": True,
        "has_context": True,
        "context": cached,
        "next_action": (
            "✅ 命中最近 app 上下文。可以**跳过** list_apaas_apps_in_env / list_apaas_app_menus，"
            "直接基于 context.forms 列表里已有的 form_id + default_tab_id 进 Phase 1 SPEC。"
            "如果用户提到的表单不在 cache forms 里（比如 builder 没查到的新表单），再调 list_apaas_form_views 补。"
        ),
    }


# @mcp.tool()  # [REMOVED 2026-05-14] paste-template 逻辑改到 skill 里
async def handoff_to_coding(
    apaas_app_id: int,
    summary: str,
    todo_list: list[str],
    apaas_app_name: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """**builder agent 调** —— 应用配置部署完，转交给 coding agent 做自开发部分。

    场景：用户说「做个销售系统含数据看板」 → builder 出设计文档 + 建应用 + 部署完成 →
    检查发现还有自开发待做（看板 / 卡片视图 / 自定义接口） → 调本工具：
    - 写 _PENDING_HANDOFFS[token] 记录上下文（todo_list / summary）
    - 顺手刷新 _USER_RECENT_APP_CONTEXT[user_id]（保证 coding agent 能 prefill）
    - 返回前端 deeplink：/ai-builder/ai-coding?handoff_token=xxx

    builder agent 收到返回后**立即在 chat 给用户**：
    > "应用「{app_name}」已部署成功 ✅
    > 你还提到要做：{todo_list 中文短描述}
    > 这部分需要写代码，我帮你接力到 AI-aPaaS-Coding 助手——
    > 👉 [点这里继续]({deeplink})"

    入参：
        apaas_app_id    刚建好的应用 id
        apaas_app_name  应用中文名
        summary         用户原始需求 + builder 已做了什么的简短总结
        todo_list       待 coding agent 做的事项列表（["运营看板", "卡片视图列表", "导出接口"]）

    返回：
        {
          "ok": true,
          "handoff_token": "hf_a1b2c3d4e5f6",
          "deeplink": "/ai-builder/ai-coding?handoff_token=hf_a1b2c3d4e5f6",
          "next_action": "立即在 chat 给用户贴 deeplink 让他点击接力"
        }
    """
    from app.routes.user_coding_session import create_handoff, set_user_recent_app_context
    return _forbidden_in_alias_mode(
        "handoff_to_coding",
        "直接告诉用户切到 ai-coding 页面，让 coding agent 通过 list_apaas_apps(env='<alias>') 自己拿应用上下文",
    )

    tid, uid = await _resolve_identity(tenant_id, user_id)
    if not apaas_app_id:
        return {
            "ok": False, "error_code": "MISSING_APP_ID",
            "message": "apaas_app_id 不能为空，必须是 builder 已建好的应用 id",
        }
    # 2026-05-09 简化：去掉 token deeplink 机制（复杂、易失败、用户体验差），
    # 改成"列待做需求 + 给纯链接，用户自己复制粘贴给 coding agent"。
    # cache 仍然要刷——coding agent 调 get_recent_app_context 时能命中 prefill。
    set_user_recent_app_context(uid, {
        "apaas_app_id": str(apaas_app_id),
        "app_name": apaas_app_name,
        "last_action": "handoff_from_builder",
        "last_actor": "builder",
    })
    coding_url = _ai_builder_ui_url("/ai-coding")

    # 整理"用户复制粘贴模板"——直接给用户能拷到 coding chat 里的话术
    paste_template_lines = [
        f'基于「{apaas_app_name or "刚建好的应用"}」做以下自开发：',
    ]
    for t in (todo_list or []):
        paste_template_lines.append(f'- {t}')
    paste_template_lines.append('')
    paste_template_lines.append(f'应用 ID = {apaas_app_id}（builder 刚建好）')
    paste_template = '\n'.join(paste_template_lines)

    return {
        "ok": True,
        "op": "handoff_to_coding",
        "coding_url": coding_url,
        "paste_template": paste_template,
        "next_action": (
            "✅ 应用已建好，cache 已刷新。**在 chat 这样回复用户**（用 markdown）：\n\n"
            "```markdown\n"
            f"✅ 应用「{apaas_app_name}」配置已部署完成。\n\n"
            f"你提到还要做这些自开发：\n"
            + '\n'.join(f'- {t}' for t in (todo_list or []))
            + "\n\n"
            f"👉 打开「低代码自开发」助手：{coding_url}\n\n"
            "把上面待做需求复制粘贴给它（应用上下文我已经传过去了，它直接知道在哪个应用上做）。\n"
            "```\n\n"
            "**不要**再生成 handoff token / deeplink 这些复杂链接——直接贴 coding_url + 待做列表给用户。"
            "coding agent 进去后调 get_recent_app_context 自动拿到 app_id / app_name。"
        ),
    }


# @mcp.tool()  # [REMOVED 2026-05-14] paste-template 逻辑改到 skill 里
async def handoff_to_builder(
    apaas_app_id: int,
    reason: str,
    request_summary: str,
    apaas_app_name: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """**coding agent 调** —— 用户提出配置态需求，coding 不能做，转交给 builder agent。

    场景：用户在 coding chat 说「再加个客户类型字段」/「加个审批流」 →
    coding agent 识别为配置态 → 调本工具转交：
    - 写 _PENDING_HANDOFFS[token]（from=coding, to=builder）
    - 返回前端 deeplink：/ai-builder/ai-copilot?handoff_token=xxx&app_id=YYY

    coding agent 在 chat 给用户：
    > "你说的「加客户类型字段」是配置态需求，需要 AI-aPaaS-Builder 来做。
    > 👉 [点这里转交]({deeplink})"

    入参：
        apaas_app_id     当前正在做的应用 id
        apaas_app_name   应用中文名
        reason           为什么要转交（"用户提到加新表单字段" / "需要加审批流"）
        request_summary  用户的原始需求陈述

    返回：含 handoff_token + deeplink。
    """
    return _forbidden_in_alias_mode(
        "handoff_to_builder",
        "直接告诉用户切到 ai-copilot 页面，让 builder agent 自己拿应用上下文",
    )

    from app.routes.user_coding_session import create_handoff, set_user_recent_app_context
    tid, uid = await _resolve_identity(tenant_id, user_id)
    if not apaas_app_id:
        return {"ok": False, "error_code": "MISSING_APP_ID", "message": "apaas_app_id 不能为空"}
    token = create_handoff(
        from_agent="coding", to_agent="builder",
        user_id=uid, apaas_app_id=int(apaas_app_id),
        app_name=apaas_app_name,
        summary=f"[coding agent 转交] 原因：{reason}\n\n用户需求：{request_summary}",
        todo_list=[reason],
    )
    set_user_recent_app_context(uid, {
        "apaas_app_id": str(apaas_app_id),
        "app_name": apaas_app_name,
        "last_action": "handoff_from_coding",
        "last_actor": "coding",
    })
    # 简化：纯链接 + 让用户自己粘贴 reason 给 builder agent
    builder_url = _ai_builder_ui_url("/ai-copilot")
    return {
        "ok": True,
        "op": "handoff_to_builder",
        "builder_url": builder_url,
        "next_action": (
            f"✅ 这是配置态需求，需要 AI-aPaaS-Builder 来做。**在 chat 给用户回复**（用 HTML <a target=_blank> 让用户点击新窗口打开）：\n\n"
            f'  👉 <a href="{builder_url}" target="_blank">打开「AI 智能搭建」助手</a>\n\n'
            f'  把"{reason}"粘贴给它（应用上下文我已经传过去，它直接知道在哪个应用上做）。\n\n'
            "**不要**用 markdown `[text](url)` —— 多数 chat 渲染会覆盖当前 tab。用 HTML `<a target=\"_blank\">` 强制新窗口。"
        ),
    }


@mcp.tool()
async def save_dev_spec(
    scene_type: str,
    project_name: str,
    display_name: str,
    spec_md: str,
    mockup_html: str = "",
    apaas_app_id: int = 0,
    apaas_app_name: str = "",
) -> dict:
    """**Phase 1 必调** —— 落盘 **双产物**（技术 SPEC + 业务可视 HTML mockup），返回 spec_token + preview_url。

    用法（看板 / 列表 / 表单 等所有 form-page/menu-page/mobile-page 场景）：
    1. 调元数据工具拿完 form_views / form_components 后
    2. 同时准备**两份**：
       - `spec_md`（技术，给 LLM 写代码用）：含真 form_id / tab_id / uuid / API 计划
       - `mockup_html`（业务，给用户审）：单文件 HTML 自包含，echarts/element-ui via cdn，
         **mock 数据用真实业务文案**，**禁止出现 form_id / uuid 这类技术 ID**
    3. 调本工具一次落两份盘，返回 spec_token + preview_url
    4. 在 chat 给用户看**业务摘要**（中文）+ **preview_url 链接**让他点开看 HTML 渲染
    5. 等用户明确表态"OK / 同意 / 走 / 进行 / 可以"
    6. 用户改 X 改 Y 时重写 spec_md + mockup_html 重调本工具（覆盖前一份）

    spec_md（技术）必含 6 段：
    - ## 1. 页面用途
    - ## 2. 数据来源（form_id 24 hex + tab_id 24 hex + 字段 uuid 32 hex 全列真值）
    - ## 3. 核心指标（看板必填）—— 公式形如 count(*) / sum / avg，禁止写死数字
    - ## 4. 图表清单（看板必填）—— 类型 / X-Y 轴 / echarts 还是 el-progress
    - ## 5. 表格列定义（如有）—— uuid 直接当 prop
    - ## 6. API 调用计划 —— listPageBusinessData N 次

    mockup_html（业务可视）写作规范：
    - 单文件 HTML，<head> CDN 引 echarts + element-ui + element-ui CSS
      （`https://unpkg.com/element-ui/lib/theme-chalk/index.css` /
       `https://unpkg.com/element-ui` /
       `https://unpkg.com/echarts@5/dist/echarts.min.js`）
    - 用 mock 数据填充图表 / 卡片 / 表格（数据值随便写，但**字段名用真实业务中文名**，
      比如「课程总数 = 128」「学习人次 = 1520」「认证通过率 = 78%」）
    - 不出现 form_id / uuid / API 端点这种技术名词
    - 总长度建议 4000-15000 字符（含 echarts 配置 + 内联 CSS）

    入参：
        scene_type     list_dev_scenes 返回的场景类型
        project_name   英文短名（kebab-case）
        display_name   中文名
        spec_md        技术 SPEC markdown（给 LLM）
        mockup_html    业务 HTML 预览（给用户）—— 看板 / 列表场景必填，
                       form-component / backend-api 等纯组件类可空
        apaas_app_id   做在哪个 apaas 应用上（必传）
        apaas_app_name 应用中文名

    返回（成功）：
        {
          "ok": true,
          "spec_token": "spec_23_a1b2c3d4",
          "preview_url": "/ai-builder/dev-spec-preview/spec_23_a1b2c3d4",  # 给用户点
          "has_mockup": true,
          ...
        }

    返回（spec 校验失败）：
        {"ok": false, "error_code": "SPEC_VALIDATION_FAILED", "missing": [...]}
    """
    from app.dev_scene_spec import all_scene_types
    if scene_type not in all_scene_types():
        return {
            "ok": False, "op": "save_dev_spec",
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知的 scene_type: {scene_type}",
            "valid_scene_types": all_scene_types(),
            "should_retry": True,
        }
    if not project_name or not project_name.strip():
        return {
            "ok": False, "op": "save_dev_spec",
            "error_code": "INVALID_PROJECT_NAME",
            "message": "project_name 不能为空",
            "should_retry": True,
        }
    if not spec_md or len(spec_md.strip()) < 100:
        return {
            "ok": False, "op": "save_dev_spec",
            "error_code": "SPEC_TOO_SHORT",
            "message": f"spec_md 太短 ({len(spec_md.strip())} 字符)，至少 100 字符。先输出完整设计再落盘。",
            "should_retry": True,
        }

    # 校验必填段
    SECTION_KEYWORDS = {
        "页面用途": ["页面用途", "## 1.", "用途"],
        "数据来源": ["数据来源", "## 2.", "数据源"],
        "API 调用计划": ["API", "调用计划", "调用规划"],
    }
    sections_found = []
    missing = []
    for sec, keywords in SECTION_KEYWORDS.items():
        if any(kw in spec_md for kw in keywords):
            sections_found.append(sec)
        else:
            missing.append(sec)
    # 看板类场景额外要求
    DASHBOARD_SCENES = {"form-page", "menu-page", "mobile-page", "form-list"}
    warnings: list[str] = []
    if scene_type in DASHBOARD_SCENES:
        if "指标" not in spec_md and "metric" not in spec_md.lower():
            warnings.append("看板/列表类页面建议明确「核心指标」段（含字段+聚合方式）")
        if "图表" not in spec_md and "echart" not in spec_md.lower() and "chart" not in spec_md.lower():
            # 可能是纯列表页（无图表）—— 不强制
            pass

    # 2026-05-08：拦截编造 ID 占位符 —— SPEC 里出现 tab_default / form_xxx /
    # course_id 这类语义字符串就是 agent 没调 list_apaas_form_views 拿真 ID。
    # 撞 4224 业务码"tabId不合法"的根源。SPEC 阶段拦截掉防止流到代码阶段。
    import re as _re
    forbidden_patterns = [
        (r'"tab_default"', '占位符 tab_default 不允许 — 调 list_apaas_form_views 拿真 default_tab_id'),
        (r'"form_default"', '占位符 form_default 不允许 — 调 list_apaas_app_menus 拿真 form_id'),
        (r'"form_id_\w+"', '占位符 form_id_xxx 不允许 — 必须是真 24 位 hex'),
        (r'"tab_id_\w+"', '占位符 tab_id_xxx 不允许 — 必须是真 24 位 hex'),
        (r"tabId:\s*['\"]\w*default\w*['\"]", '占位符 default 不允许 — tabId 必须是真 24 位 hex'),
        (r"formId:\s*['\"]\w*default\w*['\"]", '占位符 default 不允许 — formId 必须是真 24 位 hex'),
    ]
    forbidden_hits: list[str] = []
    for pat, msg in forbidden_patterns:
        if _re.search(pat, spec_md, _re.IGNORECASE):
            forbidden_hits.append(msg)

    # 数据驱动场景：要求 SPEC 至少含 1 个 24 位 hex 串（form_id 或 tab_id）。
    # 看板类至少 2 个 24 位 hex（必有多表 form_id + tab_id）。
    DATA_DRIVEN_SCENES = {"form-page", "menu-page", "mobile-page", "form-list"}
    if scene_type in DATA_DRIVEN_SCENES:
        # 24 位 hex 串模式（form_id / tab_id 都是这个长度）
        hex24_count = len(_re.findall(r'\b[a-f0-9]{24}\b', spec_md))
        # 32 位 hex 串模式（字段 uuid，可选要求 — 但 form-page 通常会列出几个字段）
        hex32_count = len(_re.findall(r'\b[a-f0-9]{32}\b', spec_md))
        if hex24_count < 2:
            forbidden_hits.append(
                f"数据驱动场景 SPEC 必须含至少 2 个 24 位 hex 串（form_id + tab_id），"
                f"当前只找到 {hex24_count} 个。先调 list_apaas_app_menus 拿 form_id + "
                f"list_apaas_form_views 拿 default_tab_id，再写 SPEC。"
            )
        if scene_type in {"form-page", "menu-page"} and hex32_count < 2:
            warnings.append(
                f"看板类 SPEC 建议列字段 uuid（32 位 hex），当前 {hex32_count} 个。"
                f"调 list_apaas_form_components 拿字段 uuid 才能渲染表格 prop / 算指标。"
            )

    if missing or forbidden_hits:
        # SPEC_VALIDATION_FAILED 是该工具本地校验错（不走 _business_error 通用分类），
        # 直接构造结构化 dict 返回，agent 必须读 forbidden_hits 修正后重调
        return {
            "ok": False,
            "op": "save_dev_spec",
            "error_code": "SPEC_VALIDATION_FAILED",
            "message": (
                "SPEC 校验失败。修补后重新调用 save_dev_spec：\n"
                + ("- 缺段：" + ", ".join(missing) + "\n" if missing else "")
                + ("- ID 编造拦截：\n  - " + "\n  - ".join(forbidden_hits) if forbidden_hits else "")
            ),
            "sections_found": sections_found,
            "missing": missing,
            "forbidden_hits": forbidden_hits,
            "warnings": warnings,
            "user_action_required": (
                "回到 step 2.5：调 list_apaas_form_views(env_id, apaas_app_id, form_id) "
                "拿每个表的真实 default_tab_id（24 位 hex），调 list_apaas_form_components 拿字段 uuid，"
                "把所有占位符替换成真实 hex 串后重新输出 SPEC + 调 save_dev_spec。"
            ),
            "should_retry": True,
        }

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()

    # 落盘到 backend 临时目录
    import uuid as _uuid
    from pathlib import Path
    from app.coding.workspace import WORKSPACE_ROOT
    # 2026-05-14: 挪进 PVC（WORKSPACE_ROOT 是 PVC 挂载点，原 .parent 在 /app 下，rollout 必丢）
    spec_dir = WORKSPACE_ROOT / ".pending-dev-specs"
    spec_dir.mkdir(parents=True, exist_ok=True)

    spec_token = f"spec_{uid}_{_uuid.uuid4().hex[:8]}"
    spec_path = spec_dir / f"{spec_token}.md"

    # 在 spec.md 顶部加 frontmatter（create_dev_workspace 路由读这个判断）
    from datetime import datetime, timezone
    payload = {
        "scene_type": scene_type,
        "project_name": project_name.strip(),
        "display_name": display_name.strip(),
        "apaas_app_id": int(apaas_app_id) if apaas_app_id else None,
        "apaas_app_name": apaas_app_name.strip() if apaas_app_name else None,
        "tenant_id": tid,
        "user_id": uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    import json as _json
    frontmatter = "---\n" + _json.dumps(payload, ensure_ascii=False, indent=2) + "\n---\n\n"
    spec_path.write_text(frontmatter + spec_md, encoding="utf-8")

    # 2026-05-09：业务用户视角的 HTML mockup 预览（双产物）。
    # mockup_html 为空时跳过——简单场景（form-component-dual / backend-api 等纯组件类）
    # 不需要 HTML 预览，业务摘要在 chat 直接说清楚就行。
    mockup_path = None
    has_mockup = False
    if mockup_html and mockup_html.strip():
        mockup_path = spec_dir / f"{spec_token}.html"
        mockup_path.write_text(mockup_html, encoding="utf-8")
        has_mockup = True

    # 前端 deeplink：用绝对 URL（dolphin chat 在 dolphin-trial 域渲染相对路径会跨域 404）
    # 2026-05-10：加 ?embed_nav=0 让 WorkbenchShell 不渲染左侧 NavRail。
    # NavRail 依赖 userStore，而 dolphin chat 跨域点击的用户通常没在 ai-builder 登录，
    # 渲染会异常；预览页本身已改为公开（spec_token 即凭证），不需要 ai-builder 登录态。
    preview_url = _ai_builder_ui_url(f"/dev-spec-preview/{spec_token}?embed_nav=0") if has_mockup else None

    return {
        "ok": True,
        "op": "save_dev_spec",
        "spec_token": spec_token,
        "scene_type": scene_type,
        "project_name": project_name.strip(),
        "display_name": display_name.strip(),
        "spec_md_length": len(spec_md),
        "mockup_html_length": len(mockup_html) if mockup_html else 0,
        "has_mockup": has_mockup,
        "preview_url": preview_url,  # agent 把这个链接贴给用户点击预览
        "validation": {
            "sections_found": sections_found,
            "missing_recommended": [],
            "warnings": warnings,
        },
        "next_action": (
            "✅ SPEC 已落盘"
            + ("（含 HTML 预览）" if has_mockup else "")
            + "。现在在 chat 中向用户展示**业务摘要**（中文表单名 / 业务术语，**不要**贴 form_id / uuid 这些技术 ID）"
            + (f'，附 **HTML 预览链接**（用 HTML <a target=_blank> 让用户点击在新窗口打开，**不要**用 markdown [text](url)，那个会覆盖当前对话页面）：\n\n  👉 <a href="{preview_url}" target="_blank">点击查看可视化预览</a>\n\n' if has_mockup else "，")
            + "明确询问：「这样设计可以开始实现了吗？同意请回复 OK / 同意 / 走 / 可以」。"
            f"用户明确同意后才调用 create_dev_workspace(spec_token='{spec_token}', ...)。"
            "用户说改 X 改 Y 时，重写 spec_md + mockup_html 后重新调 save_dev_spec（覆盖前一份 token）。"
        ),
    }


def _detect_scene_from_zip_names(names: list[str]) -> tuple[str, str]:
    """从 zip 文件名列表启发式识别 scene_type。

    返回 (scene_type, source_clue)。无法识别返回 ("", reason)。

    识别策略（按优先级）：
      1. 顶层目录名以已知 project_name 前缀开头（form-page-* / dashboard-* / backend-api-* ...）
      2. 文件结构特征（src/main/java/ → backend; src/index.js + Vue.component → form-component-dual）
      3. 无法识别 → 让 agent 显式传 scene_type
    """
    if not names:
        return "", "zip 为空"

    # 1. 顶层目录前缀匹配
    prefix_map = [
        ("form-page-", "form-page"),
        ("form_page_", "form-page"),
        ("form-list-", "form-list"),
        ("form-component-", "form-component-dual"),
        ("form_component_", "form-component-dual"),
        ("dashboard-", "dashboard-component-dual"),
        ("dashboard_", "dashboard-component-dual"),
        ("backend-api-", "backend-api"),
        ("backend-feign-", "backend-feign"),
        ("backend-scheduled-", "backend-scheduled"),
        ("mobile-page-", "mobile-page"),
        ("web-login-", "web-login"),
        ("frontend-plugin-", "plugin"),
        ("layout-", "layout"),
    ]
    top = (names[0].split("/")[0] or "").lower()
    for prefix, scene in prefix_map:
        if top.startswith(prefix):
            return scene, f"顶层目录 '{top}' 匹配前缀 '{prefix}'"

    # 2. 文件结构特征
    joined = "\n".join(names)
    if "src/main/java/" in joined or "/pom.xml" in joined:
        return "backend-api", "含 src/main/java 或 pom.xml"
    if any(n.endswith("src/index.js") for n in names):
        return "form-component-dual", "含 src/index.js"
    if any("mobile-page" in n.lower() for n in names):
        return "mobile-page", "文件名含 mobile-page"
    if any("login" in n.lower() and n.endswith(".vue") for n in names):
        return "web-login", "含 login.vue"

    return "", f"无法从 zip 顶层目录 '{top}' 或文件结构识别 scene_type，请显式传 scene_type 参数"


@mcp.tool()
async def import_zip_to_workspace(
    file_content_b64: str,
    project_name: str = "",
    scene_type: str = "",
    display_name: str = "",
    apaas_app_id: int = 0,
    apaas_app_name: str = "",
) -> dict:
    """🆕 2026-05-11：把外部 zip（base64）解压成新 workspace，给二次开发场景用。

    适用场景（V2.6 二次开发主入口）：
      - 用户在 apaas 后台下载了某自开发包 zip，想改改重发 → 调本工具解到工作区
      - 用户从同事 / Git / 外部交付一个完整 zip，想在 ai-builder 里改
      - 客户 admin 拷贝过来一个标杆模板想 fork 改

    与其他工具的关系：
      - create_dev_workspace —— 从模板脚手架起新工作区（**全新开发**）
      - import_zip_to_workspace —— 从已有 zip 起工作区（**二次开发**）⭐ 本工具
      - upload_external_zip_to_apaas —— 直接传 zip 到 apaas 资源池（**不进工作区**，不编辑）

    流程：
      1. base64 解码 zip → 校验完整性
      2. 启发式识别 scene_type（顶层目录名 form-page-* / dashboard-* 等；agent 显式传时直接用）
      3. 调内部 /coding/workspace/create 起空 workspace 拿 ws_id
      4. 解压 zip 文件，逐个 POST /coding/workspace/{ws_id}/file 写入（跳过二进制 / 超大文件）
      5. 返 ws_id 给 agent，后续用 read / glob / edit / write 改 → build → publish

    入参：
        file_content_b64  zip 文件 base64 编码（无 'data:' 前缀）
        project_name      工作区项目名（kebab-case）。不传 → 从 zip 顶层目录名提取
        scene_type        list_dev_scenes 返回的 scene_type。不传 → 启发式识别
        display_name      中文名，工作区列表显示用。不传 → 用 project_name
        apaas_app_id      可选，绑应用关联
        apaas_app_name    可选，应用中文名

    返回：
        {
          "ok": true,
          "ws_id": "...",
          "scene_type": "form-page",
          "scene_type_source": "user|auto_detected",
          "project_name": "...",
          "files_written": 24,
          "files_skipped_binary": 3,
          "files_skipped_too_large": 0,
          "deeplink": "https://.../coding?ws_id=...",
          "summary": "...",
          "next_action": "read .coding-spec.md（如有）+ glob_workspace 探索 + edit 改 → build → publish_dev_workspace"
        }

    限制：
      - zip ≤ 50MB（解码后）
      - 单文件 ≤ 1MB（超过跳过，二次开发场景没必要塞超大资源）
      - 二进制文件（图片 / 字体 / 编译产物）跳过 — 工作区文件 API 只接 utf-8 文本
    """
    import base64 as _b64
    import io as _io
    import re as _re
    import zipfile as _zf

    if not file_content_b64 or not file_content_b64.strip():
        return _business_error(op="导入 zip", error_text="file_content_b64 不能为空")
    try:
        zip_bytes = _b64.b64decode(file_content_b64.strip())
    except Exception as exc:
        return _business_error(op="导入 zip", error_text=f"base64 解码失败: {exc}")
    if len(zip_bytes) == 0:
        return _business_error(op="导入 zip", error_text="解码后 zip 为 0 字节")
    if len(zip_bytes) > 50 * 1024 * 1024:
        return _business_error(
            op="导入 zip",
            error_text=f"zip 解码后 {len(zip_bytes)//1024//1024}MB 超过 50MB 限制",
        )
    try:
        zf = _zf.ZipFile(_io.BytesIO(zip_bytes))
        names = [n for n in zf.namelist() if not n.endswith("/")]
    except _zf.BadZipFile:
        return _business_error(op="导入 zip", error_text="不是有效的 zip 文件")
    if not names:
        return _business_error(op="导入 zip", error_text="zip 内不含任何文件")

    # 识别 scene_type
    if scene_type and scene_type.strip():
        from app.dev_scene_spec import all_scene_types
        if scene_type.strip() not in all_scene_types():
            return _business_error(
                op="导入 zip",
                error_text=f"scene_type='{scene_type}' 不在 list_dev_scenes 列表里",
                extra={"valid_scene_types": all_scene_types()},
            )
        final_scene = scene_type.strip()
        scene_source = "user"
        scene_clue = "agent 显式传入"
    else:
        detected, clue = _detect_scene_from_zip_names(names)
        if not detected:
            return _business_error(
                op="导入 zip",
                error_text=clue,
                extra={
                    "sample_files": names[:15],
                    "hint": "请调 list_dev_scenes 看可选 scene_type，再带 scene_type 参数重新调本工具",
                },
            )
        final_scene = detected
        scene_source = "auto_detected"
        scene_clue = clue

    # project_name 兜底（从顶层目录名提取）
    if not (project_name or "").strip():
        top = names[0].split("/")[0] or ""
        # 清理非法字符 + 转小写
        cleaned = _re.sub(r"[^a-z0-9-]", "-", top.lower()).strip("-") or f"imported-{final_scene}"
        project_name = cleaned[:60]

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()

    # 起空 workspace
    body: dict = {
        "project_type": final_scene,
        "project_name": project_name.strip(),
        "display_name": (display_name or project_name).strip() or None,
    }
    if apaas_app_id and int(apaas_app_id) > 0:
        body["apaas_app_id"] = int(apaas_app_id)
    if apaas_app_name and apaas_app_name.strip():
        body["apaas_app_name"] = apaas_app_name.strip()

    try:
        ws_result = await _api_call(
            "POST", "/coding/workspace/create",
            tenant_id=tid, user_id=uid, json_body=body,
        )
    except RuntimeError as exc:
        return _business_error(op="创建工作区", error_text=str(exc))

    ws_id = ws_result.get("id") or ""
    if not ws_id:
        return _business_error(
            op="创建工作区",
            error_text="后端返回缺 workspace id",
            extra={"raw": ws_result},
        )

    # 检测顶层目录包装：如果所有文件共享同一顶层目录前缀，剥掉
    top_dir = names[0].split("/")[0] if "/" in names[0] else ""
    has_uniform_top = (
        bool(top_dir)
        and all(n.startswith(top_dir + "/") or n == top_dir for n in names)
    )

    # 解压 + 逐文件写入
    files_written = 0
    files_skipped_binary = 0
    files_skipped_too_large = 0
    SKIP_BINARY_EXT = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".mp4", ".mp3", ".wav", ".pdf",
        ".class", ".jar", ".pyc",
    }

    for name in names:
        rel_path = name[len(top_dir) + 1:] if has_uniform_top else name
        if not rel_path or rel_path.startswith("."):
            # 隐藏文件（.git/.DS_Store 等）跳过；.coding-spec.md 等内部文件由后端生成
            if not rel_path.startswith(".coding-spec.md"):
                continue
        # 后缀过滤
        if "." in rel_path:
            ext = "." + rel_path.rsplit(".", 1)[-1].lower()
            if ext in SKIP_BINARY_EXT:
                files_skipped_binary += 1
                continue

        try:
            raw = zf.read(name)
        except Exception as exc:
            logger.warning("import_zip read %s failed: %s", name, exc)
            files_skipped_binary += 1
            continue

        if len(raw) > 1024 * 1024:
            files_skipped_too_large += 1
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            files_skipped_binary += 1
            continue
        try:
            await _api_call(
                "POST", f"/coding/workspace/{ws_id}/file",
                tenant_id=tid, user_id=uid,
                json_body={"file_path": rel_path, "content": content},
            )
            files_written += 1
        except Exception as exc:
            logger.warning("import_zip write ws=%s path=%s failed: %s", ws_id, rel_path, exc)
            files_skipped_binary += 1

    deeplink = _build_coding_deeplink(ws_id)
    summary_parts = [
        f"已导入 zip 到工作区 {ws_id}（scene_type={final_scene}，{scene_source}）",
        f"写入 {files_written} 个文件",
    ]
    if files_skipped_binary > 0:
        summary_parts.append(f"跳过 {files_skipped_binary} 个二进制/读失败")
    if files_skipped_too_large > 0:
        summary_parts.append(f"跳过 {files_skipped_too_large} 个>1MB")

    return {
        "ok": True,
        "ws_id": ws_id,
        "scene_type": final_scene,
        "scene_type_source": scene_source,
        "scene_type_clue": scene_clue,
        "project_name": project_name,
        "display_name": ws_result.get("display_name") or project_name,
        "files_written": files_written,
        "files_skipped_binary": files_skipped_binary,
        "files_skipped_too_large": files_skipped_too_large,
        "deeplink": deeplink,
        "summary": "；".join(summary_parts) + "。",
        "next_action": (
            "下一步：(1) glob_workspace 看文件结构 (2) read .coding-spec.md（如有）"
            "/ src/index.js / src/components/*.vue 了解原代码 (3) 跟用户确认要改什么"
            "(4) edit_workspace_files 改代码 (5) build_workspace 构建 "
            "(6) publish_dev_workspace 重发资源池 (7) republish_apaas_app 让前端生效"
        ),
    }


@mcp.tool()
async def create_dev_workspace(
    scene_type: str,
    project_name: str,
    display_name: str | None = None,
    initial_requirement: str = "",
    apaas_app_id: int = 0,
    apaas_app_name: str = "",
    spec_token: str = "",
    backend_template_version: str = "",
) -> dict:
    """在 ai-builder /coding 下创建一个自开发 workspace（脚手架已就位、可以开始写代码）。

    内部调本机 POST /api/coding/workspace/create——脚手架由 df-apaas-cli 拉
    标准模板，所有 .cursor/rules/*.mdc 默认规则文件已经被复制到工作区，vibe_agent
    跑起来就能直接读。

    **强烈推荐传 initial_requirement**——把 dolphin 跟用户对齐好的需求 brief 一并
    传进来，工具会写到 workspace 的 .coding-pending-requirement.txt，deeplink 自带
    &auto_run=1，用户点进去 ai-builder /coding 时前端会自动把 brief 喂给 vibe_agent
    开跑——免去用户跨页面复制粘贴的麻烦。

    身份注入：
        tenant_id / user_id 来自 dolphin 自定义 Body 字段。漏配时 fallback 到
        admin (1, 1)——多租户场景务必在 dolphin admin 配 Body 注入真实身份，否
        则 li.l.77 跟 admin 的 workspace 会混在一起。

    入参：
        scene_type           list_dev_scenes 返回的 scene_type，会作为 project_type
                             传给 create_workspace（两者命名约定一致）
        project_name         英文短名（kebab-case），如 "form-page-home-dashboard"。
                             会成为目录名 + 部分组件 code。LLM 可按场景自行起，避免
                             和已有 workspace 重名（重名时后端会强制覆盖）
        display_name         中文名（如 "首页看板"），用户看得到的标题
        initial_requirement  跟用户对齐好的需求 brief（200-2000 字）。dolphin agent
                             应该在 step 4 收集 user_inputs_needed 后整理这段，**直接
                             传给本字段**，不要再要求用户复制粘贴

    返回（成功）：
        {
          "ok": true,
          "ws_id": "23_a1b2c3d4",
          "auto_run": true,
          "scene_type": "form-page",
          "project_name": "form-page-home-dashboard",
          "display_name": "首页看板",
          "tenant_id": 2,
          "user_id": 23,
          "deeplink": "http://127.0.0.1:5173/ai-builder/coding?ws_id=23_a1b2c3d4&auto_run=1",
          "ui_hint": "..."
        }

    返回（失败）：
        {"ok": false, "error_code": "SCENE_NOT_FOUND" | ...}
    """
    from app.dev_scene_spec import all_scene_types
    if scene_type not in all_scene_types():
        return {
            "ok": False,
            "op": "create_dev_workspace",
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知的 scene_type: {scene_type}。先调 list_dev_scenes 看可选值",
            "valid_scene_types": all_scene_types(),
            "user_action_required": "回到 list_dev_scenes 重新选场景类型。",
            "should_retry": False,
        }
    if not project_name or not project_name.strip():
        return {
            "ok": False,
            "op": "create_dev_workspace",
            "error_code": "INVALID_PROJECT_NAME",
            "message": "project_name 不能为空。建议格式：{scene_type 简写}-{业务名}，如 form-page-home-dashboard",
            "user_action_required": "按命名约定生成 project_name 后重新调用。",
            "should_retry": False,
        }

    backend_scene_types = {"backend-api", "backend-feign", "backend-scheduled"}
    normalized_backend_template_version = (backend_template_version or "").strip()
    if scene_type in backend_scene_types and normalized_backend_template_version not in {"4", "5"}:
        return {
            "ok": False,
            "op": "create_dev_workspace",
            "error_code": "MISSING_BACKEND_TEMPLATE_VERSION",
            "message": "后端自开发工作区必须先确认使用 4 版本还是 5 版本模板。",
            "user_action_required": "先问用户要 4 版本还是 5 版本；4 用旧模板，5 用新模板，然后带 backend_template_version='4' 或 '5' 重试。",
            "should_retry": False,
        }

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    body: dict = {
        "project_type": scene_type,
        "project_name": project_name.strip(),
        "display_name": (display_name or "").strip() or None,
    }
    if normalized_backend_template_version:
        body["backend_template_version"] = normalized_backend_template_version
    # 2026-05-08：审计追溯字段直传到 workspace meta
    if apaas_app_id and int(apaas_app_id) > 0:
        body["apaas_app_id"] = int(apaas_app_id)
    if apaas_app_name and apaas_app_name.strip():
        body["apaas_app_name"] = apaas_app_name.strip()
    # 2026-05-08 Phase 1 SPEC：路由层根据 spec_token 把 .pending-dev-specs/{token}.md
    # copy 到 workspace/.coding-spec.md，让 vibe_agent 写代码时能读
    if spec_token and spec_token.strip():
        body["spec_token"] = spec_token.strip()
    # dolphin_session_id 走路由层兜底（_USER_CODING_SESSION map），agent 看不到自己 session_id
    try:
        result = await _api_call(
            "POST",
            "/coding/workspace/create",
            tenant_id=tid,
            user_id=uid,
            json_body=body,
        )
    except RuntimeError as exc:
        return _business_error(
            op="create_dev_workspace",
            error_text=str(exc),
        )

    ws_id = result.get("id") or ""

    # V1.5：把整理好的需求 brief 写到 workspace 文件，前端 auto_run=1 时拉出来
    # 自动 sendMessage 给 vibe_agent。失败不致命，回退到 V1 deeplink 模式。
    auto_run = False
    if initial_requirement and initial_requirement.strip() and ws_id:
        try:
            await _api_call(
                "POST",
                f"/coding/workspace/{ws_id}/file",
                tenant_id=tid,
                user_id=uid,
                json_body={
                    "file_path": ".coding-pending-requirement.txt",
                    "content": initial_requirement.strip(),
                },
            )
            auto_run = True
        except Exception as exc:
            logger.warning(
                "create_dev_workspace: 写 pending-requirement 失败 ws_id=%s err=%s",
                ws_id, exc,
            )

    # 2026-05-13: 砍掉 IDE 入口链接 —— dolphin agent 自己继续多轮调工具完成代码
    # 实现 + 构建 + 发布，不再让用户跳到 ai-builder /coding 页面。改造背景：用户
    # 反馈 IDE 入口是不必要的步骤；dolphin agent 已具备 read/write/edit/run/publish
    # 全套 workspace 工具，可独立完成开发流程，不需要 vibe_agent 介入。
    # deeplink 字段保留返回（前端高级场景用），但 ui_hint 不再引导用户点。
    deeplink = _build_coding_deeplink(ws_id, auto_run=False)
    ui_hint = (
        "**不要给用户贴 IDE 链接**。工作区已就绪，**你（dolphin agent）现在继续在本对话里完成开发**：\n\n"
        "1. 调 `read_workspace_file(ws_id, '.coding-spec.md')` 读已注入的 SPEC（必读）\n"
        "2. 调 `read_workspace_file(ws_id, 'src/...')` 看模板初始代码（按 scene_type 不同结构不同）\n"
        "3. 调 `write_workspace_files(ws_id, [{path, content}, ...])` 按 SPEC 写实现代码\n"
        "   - 大改用 write_workspace_files（整文件覆盖）\n"
        "   - 小改用 `edit_workspace_files`（局部 find-replace，省 token）\n"
        "4. 调 `run_workspace_command(ws_id, 'npm install && npm run build')` 构建验证\n"
        "5. 出错 → 看 output 找原因 → write/edit 修 → 再 build，循环到 build 成功\n"
        "6. build 成功后调 `publish_dev_workspace(ws_id)` 上传到 aPaaS 平台\n"
        "7. 每个 step 给用户中文进度通报（如「正在写 components/MetricCard.vue...」「正在构建...」「构建成功，正在发布...」）\n\n"
        "**禁止行为**：\n"
        "- ❌ 不要让用户点进 IDE（已废除该路径）\n"
        "- ❌ 不要在 chat 贴完整代码内容（贴文件名 + 描述即可）\n"
        "- ❌ 不要等用户主动触发下一步，全流程你自己推进\n"
        f"\n当前工作区 ws_id={ws_id}，scene_type={scene_type}" + (f"，已注入 SPEC token={spec_token}" if spec_token else "") + "。"
    )

    return {
        "ok": True,
        "ws_id": ws_id,
        "auto_run": auto_run,
        "scene_type": scene_type,
        "project_name": result.get("project_name"),
        "display_name": result.get("display_name"),
        "tenant_id": tid,
        "user_id": uid,
        "status": result.get("status"),
        "deeplink": deeplink,
        "ui_hint": ui_hint,
    }


@mcp.tool()
async def get_dev_workspace_status(
    ws_id: str,
) -> dict:
    """查询自开发 workspace 的当前状态（文件列表 / build 状态 / 关联对话 / 后台命令）。

    用户在 ai-builder /coding 跟 vibe_agent 协作时，dolphin agent 偶尔可以查一下
    进度（用户问"做完了没"时调用）；不要高频轮询（每分钟不要超过 2 次），那是
    SSE 进度推送 V2 的活。

    **2026-05-13 加 last_command_run** —— run_workspace_command 慢命令异步早返后，
    agent 30s 后调本工具拿最终 status / exit_code / output_tail。

    返回：
        {
          "ok": true,
          "ws_id": "...",
          "scene_type": "form-page",
          "display_name": "首页看板",
          "status": "ready",          # creating | installing | ready | building | error
          "files_count": 12,
          "deeplink": "...",
          "last_command_run": {       # 上次 run_workspace_command 状态；无则 null
            "task_id": "cmd_...",
            "command": "npm install && npm run build",
            "status": "completed",   # running | completed | failed | cancelled | stale
            "exit_code": 0,
            "started_at": "...",
            "finished_at": "...",
            "output_tail": "...(末 2000 字符)"
          }
        }
    """
    if not ws_id:
        return {
            "ok": False,
            "op": "get_dev_workspace_status",
            "error_code": "INVALID_WS_ID",
            "message": "ws_id 不能为空",
            "user_action_required": "用 create_dev_workspace 返回的 ws_id 重新调用。",
            "should_retry": False,
        }
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    try:
        result = await _api_call(
            "GET",
            f"/coding/workspace/{ws_id}",
            tenant_id=tid,
            user_id=uid,
        )
    except RuntimeError as exc:
        return _business_error(
            op="get_dev_workspace_status",
            error_text=str(exc),
        )

    # 读 .workspace.json.last_command_run（本 pod 磁盘上的 workspace 元数据）
    # 不靠 internal endpoint —— workspace 在 ming / mcp-server pod 本地磁盘，
    # _resolve_workspace_path 直接拿到 Path 后读 meta 比绕 HTTP 快。
    last_command_run = None
    try:
        ws_path, _err = _resolve_workspace_path(ws_id, tid, uid)
        if ws_path is not None and not _err:
            from app.coding.command_runs import get_last_run, read_log_tail
            last_command_run = get_last_run(ws_path)
            # 如果 finish_run 还没写 output_tail（running 中），从实时日志文件读末段
            if last_command_run and not last_command_run.get("output_tail"):
                tail = read_log_tail(ws_path, last_command_run.get("task_id", ""))
                if tail:
                    last_command_run["output_tail"] = tail
    except Exception:
        # 读 last_command_run 失败不影响 status 主流程
        logger.debug("get_dev_workspace_status: 读 last_command_run 失败 ws_id=%s", ws_id, exc_info=True)

    return _with_absolute_artifact_urls({
        "ok": True,
        "ws_id": ws_id,
        "scene_type": result.get("project_type"),
        "project_name": result.get("project_name"),
        "display_name": result.get("display_name"),
        "status": result.get("status"),
        "last_build": result.get("last_build"),
        "files_count": len(result.get("files", []) or []),
        "deeplink": _build_coding_deeplink(ws_id),
        "last_command_run": last_command_run,
    })


# ═══════════════════════════════════════════════════════════════════════════
# ║  dev-coding V2：dolphin agent 端到端开发工具组                              ║
# ║  ─────────────────────────────────────────────────────────────────────── ║
# ║  V1/V1.5 是把用户引到 ai-builder UI 让 vibe_agent 接管。V2 让 dolphin       ║
# ║  agent 自己拥有完整开发能力——通过 batch MCP 工具直接 read / write /         ║
# ║  edit / glob / grep / run_command 操作 workspace，按 scene 规范走完         ║
# ║  开发 + build + 部署一条龙，全程不离开 dolphin 浮窗。                        ║
# ║                                                                            ║
# ║  关键设计：MCP 工具内部 batch（一次 RPC 写多文件 / 一次 edit 多处），        ║
# ║       不依赖 LLM 端 parallel tool_calls——这样 OpenAI / Claude / Qwen /     ║
# ║       DeepSeek 等任意 LLM 都能跑（dolphin 接的 LLM 不限）。                  ║
# ║                                                                            ║
# ║  实现：直接 import backend/app/coding/tools.py 的 6 个 executor 复用，       ║
# ║       不重写业务逻辑（写文件智能识别 form-component 校验、run_command       ║
# ║       智能识别 npm install/build 包成 install_deps + build_project）。      ║
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_workspace_path(ws_id: str, tid: int, uid: int):
    """返回 (ws_path: Path, error: None) 或 (None, error_dict)。

    校验权限：跟 list_accessible_workspaces 同款（meta.tenant_id 严格匹配
    + meta.user_id 个人 workspace 匹配）。给 dolphin 镜像账号身份做隔离，
    防 li.l.77 操作 admin 的工作区。
    """
    import json as _json
    from app.coding.workspace import WorkspaceManager
    ws_mgr = WorkspaceManager()
    try:
        ws_path = ws_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        return None, {
            "ok": False,
            "op": "_workspace_access",
            "error_code": "WORKSPACE_NOT_FOUND",
            "message": f"工作区 {ws_id} 不存在",
            "should_retry": False,
        }
    meta_path = ws_path / ".workspace.json"
    if meta_path.exists():
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    else:
        meta = {}
    meta_tid = meta.get("tenant_id")
    meta_uid = meta.get("user_id")
    project_id = meta.get("project_id")
    if meta_tid is not None and int(meta_tid) != int(tid):
        return None, {
            "ok": False,
            "op": "_workspace_access",
            "error_code": "TENANT_MISMATCH",
            "message": f"工作区 {ws_id} 不属于当前租户（meta tenant_id={meta_tid}，your tenant_id={tid}）",
            "user_action_required": "确认 dolphin agent 配了正确的 MCP Body 字段；或换一个本租户下的 ws_id。",
            "should_retry": False,
        }
    if project_id is None and meta_uid is not None and int(meta_uid) != int(uid):
        return None, {
            "ok": False,
            "op": "_workspace_access",
            "error_code": "USER_MISMATCH",
            "message": f"工作区 {ws_id} 不属于当前用户（meta user_id={meta_uid}，your user_id={uid}）",
            "user_action_required": "这是个人工作区，只有创建者能操作。",
            "should_retry": False,
        }
    return ws_path, None


# @mcp.tool()  # [MERGED] -> get_dev_scene(scene_type, detail="workflow")
async def get_dev_scene_full_workflow(scene_type: str) -> dict:
    """拿到某个自开发场景的**完整开发规范**（critical rules / 目录铁则 / mixin 速查
    / mode-specific 规则 / build 命令 / 自检清单）。

    **dev-coding skill V2 工作流第一步必调**——在 list_dev_scenes 选定 scene_type
    后立刻调本工具，把返回的 markdown 注入到当前 chat context（agent 应在写代码前
    完整阅读一遍）。这是给 dolphin agent 的 single source of truth，等价于
    vibe_agent 的内置 workflow prompt。

    返回：
        {
          "ok": true,
          "scene_type": "form-component-dual",
          "has_full_workflow": true,
          "workflow_markdown": "# 自开发表单组件（双端）...（约 5KB markdown，含
                                通用规范 + 目录铁则 + mixin 速查 + mode 规则 + 自检清单）"
        }

    has_full_workflow=false 时返回的是通用兜底，agent 应主要参考 get_dev_scene_spec
    的 critical_warnings + file_outline 字段。
    """
    from app.dev_scene_workflow import get_full_workflow, has_full_workflow
    from app.dev_scene_spec import all_scene_types
    if scene_type not in all_scene_types():
        return {
            "ok": False,
            "op": "get_dev_scene_full_workflow",
            "error_code": "SCENE_NOT_FOUND",
            "message": f"未知 scene_type: {scene_type}",
            "valid_scene_types": all_scene_types(),
            "should_retry": False,
        }
    return {
        "ok": True,
        "scene_type": scene_type,
        "has_full_workflow": has_full_workflow(scene_type),
        "workflow_markdown": get_full_workflow(scene_type),
    }


@mcp.tool()
async def read_workspace_file(
    ws_id: str,
    file_path: str,
) -> dict:
    """读取 workspace 内某个文件（vibe_agent.read_file 的 MCP 等价物）。

    file_path 是工作区根目录的相对路径（如 "src/page.vue" / "shared/widget.config.json"）。
    超过 10000 字符的文件会被截断（带 truncation 提示）。

    返回：
        {"ok": true, "content": "<file text>", "truncated": false}
        或 {"ok": false, "error_code": "...", "message": "..."}
    """
    if not file_path:
        return {"ok": False, "error_code": "INVALID_FILE_PATH", "message": "file_path 不能为空"}
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _read_file
    text = await _read_file({"file_path": file_path}, ws_path)
    if isinstance(text, str) and text.startswith("Error:"):
        return {
            "ok": False,
            "op": "read_workspace_file",
            "error_code": "FILE_READ_ERROR",
            "message": text,
            "should_retry": False,
        }
    truncated = "(truncated," in (text or "")
    return {"ok": True, "content": text or "", "truncated": truncated}


@mcp.tool()
async def write_workspace_files(
    ws_id: str,
    files: list[dict],
) -> dict:
    """**批量**写入多个文件到 workspace（一次 RPC 解决 30+ 文件场景）。

    这是 V2 关键工具——dolphin agent 不依赖 LLM 端 parallel tool_calls，只发**一次**
    本 MCP 调用就能写完一个完整 form-component-dual 的 14 个 vue + 几个 json/index.js。

    入参：
        files: [
          {"file_path": "src/page.vue", "content": "<vue source>"},
          {"file_path": "src/index.js", "content": "..."},
          ...
        ]

    返回：
        {
          "ok": true,
          "results": [
            {"file_path": "src/page.vue", "status": "ok"},
            {"file_path": "src/index.js", "status": "ok"},
            {"file_path": "src/foo.json", "status": "error", "error": "JSON 校验失败：..."},
          ],
          "success_count": 2,
          "error_count": 1
        }
    部分失败时仍返回 ok:true（让 agent 看 error_count 自己决定 fix 哪些）。
    """
    if not isinstance(files, list) or not files:
        return {"ok": False, "error_code": "INVALID_FILES", "message": "files 必须是非空 list"}
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _write_file
    results = []
    success = 0
    errors = 0
    for entry in files:
        if not isinstance(entry, dict):
            results.append({"file_path": "?", "status": "error", "error": "entry 必须是 dict"})
            errors += 1
            continue
        fp = entry.get("file_path", "")
        content = entry.get("content", "")
        if not fp:
            results.append({"file_path": "?", "status": "error", "error": "file_path 不能为空"})
            errors += 1
            continue
        out = await _write_file({"file_path": fp, "content": content}, ws_path)
        if isinstance(out, str) and out.startswith("Error"):
            results.append({"file_path": fp, "status": "error", "error": out})
            errors += 1
        else:
            results.append({"file_path": fp, "status": "ok"})
            success += 1
    return {
        "ok": True,
        "results": results,
        "success_count": success,
        "error_count": errors,
    }


@mcp.tool()
async def edit_workspace_files(
    ws_id: str,
    edits: list[dict],
) -> dict:
    """**批量**对多个文件做精确字符串替换（vibe_agent.edit_file 的 batch MCP 等价）。

    用于 build 失败后 fix——dolphin agent 一次性发多个修复点，比 edit 一个等一轮高效。
    每个 edit 必须 old_string 在文件内**唯一存在**，否则会报错（避免误改）。

    入参：
        edits: [
          {"file_path": "src/page.vue", "old_string": "<bug>", "new_string": "<fix>"},
          {"file_path": "shared/widget.config.json", "old_string": "...", "new_string": "..."},
        ]

    返回：
        {"ok": true, "results": [...], "success_count": 1, "error_count": 1}
    """
    if not isinstance(edits, list) or not edits:
        return {"ok": False, "error_code": "INVALID_EDITS", "message": "edits 必须是非空 list"}
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _edit_file
    results = []
    success = 0
    errors = 0
    for entry in edits:
        if not isinstance(entry, dict):
            results.append({"file_path": "?", "status": "error", "error": "entry 必须是 dict"})
            errors += 1
            continue
        fp = entry.get("file_path", "")
        old = entry.get("old_string", "")
        new = entry.get("new_string", "")
        if not fp or not old:
            results.append({
                "file_path": fp or "?",
                "status": "error",
                "error": "file_path 和 old_string 必填",
            })
            errors += 1
            continue
        out = await _edit_file(
            {"file_path": fp, "old_string": old, "new_string": new},
            ws_path,
        )
        if isinstance(out, str) and out.startswith("Error"):
            results.append({"file_path": fp, "status": "error", "error": out})
            errors += 1
        else:
            results.append({"file_path": fp, "status": "ok"})
            success += 1
    return {
        "ok": True,
        "results": results,
        "success_count": success,
        "error_count": errors,
    }


@mcp.tool()
async def glob_workspace(
    ws_id: str,
    pattern: str,
    path: str = "",
) -> dict:
    """按 glob pattern 列工作区文件（vibe_agent.glob_files 等价）。

    pattern 例: "**/*.vue" / "src/**/*.json" / "*.md"
    path: 子目录前缀（可选）

    返回：
        {"ok": true, "files": ["src/page.vue", "src/components/x.vue", ...]}
    """
    if not pattern:
        return {"ok": False, "error_code": "INVALID_PATTERN", "message": "pattern 不能为空"}
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _glob_files
    raw = await _glob_files({"pattern": pattern, "path": path}, ws_path)
    files = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    return {"ok": True, "files": files, "count": len(files)}


@mcp.tool()
async def grep_workspace(
    ws_id: str,
    pattern: str,
    path: str = "",
) -> dict:
    """在工作区内 grep 搜索（vibe_agent.grep_search 等价）。

    pattern 是正则。返回匹配行列表，每行带 file:line 前缀。
    用于：build 错日志找出错位置 / 找哪些文件用了某个旧 API。

    返回：
        {"ok": true, "matches": ["src/page.vue:23:bad code", ...]}
    """
    if not pattern:
        return {"ok": False, "error_code": "INVALID_PATTERN", "message": "pattern 不能为空"}
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err
    from app.coding.tools import _grep_search
    raw = await _grep_search({"pattern": pattern, "path": path}, ws_path)
    matches = [line for line in (raw or "").splitlines() if line.strip()]
    return {"ok": True, "matches": matches, "count": len(matches)}


@mcp.tool()
async def run_workspace_command(
    ws_id: str,
    command: str,
    timeout: int = 120,
) -> dict:
    """在 workspace 根目录跑 shell 命令（vibe_agent.run_command 等价）。

    内置智能识别：
    - "npm install && npm run build" / "npm install" / "npm run build" → 走 ai-builder
      WorkspaceManager 优化路径（私有 npm 源 + 缓存复用 + 详细 log）
    - 其他命令（mvn / pip / 自定义 shell）→ subprocess + timeout

    timeout 单位秒，默认 120；npm install 大组件、Maven 编译可能要 180。
    输出超过 10000 字符会被截断。

    ⚠️ **dolphin omnigate 30s timeout 保护（2026-05-13 加）**
    omnigate 死设 30s 强关连接，npm install/build 多数 > 30s 就会撞坑（mcp SDK
    transport 抛 ClosedResourceError 被聚合成 "unhandled errors in a TaskGroup"
    壳子返回 agent，看不到真实输出）。改造为 asyncio.shield + 20s 早返：

    返回结构（两种）：

    A) 快命令（< 20s 跑完）—— 行为完全兼容旧版：
        {"ok": True, "task_id": "cmd_...", "status": "completed",
         "output": "...", "exit_code": 0, "is_error": False}

    B) 慢命令（> 20s 没跑完，后台 shield 继续）：
        {"ok": True, "task_id": "cmd_...", "status": "in_progress",
         "summary": "命令已在后台运行...",
         "polling_hint": {"next_tool": "get_dev_workspace_status",
                          "next_args": {"ws_id": "..."}, "wait_seconds": 30}}
        agent 必须等 30s 调 get_dev_workspace_status(ws_id)，看 last_command_run.status：
        - completed + exit_code=0 → 成功
        - failed → 看 output_tail 找报错 + edit 修
        - stale → pod 重启，重跑
        **千万不要立即重试 run_workspace_command**，否则会重复跑安装/构建。
    """
    if not command:
        return {"ok": False, "error_code": "INVALID_COMMAND", "message": "command 不能为空"}
    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err

    from app.coding.tools import _run_command
    from app.coding.command_runs import (
        append_log_callback,
        finish_run,
        make_task_id,
        start_run,
    )

    # 登记 task 进 .workspace.json.last_command_run + 开日志文件
    task_id = make_task_id(ws_id)
    log_file = start_run(ws_path, task_id, command)
    progress_cb = append_log_callback(log_file)

    import asyncio as _asyncio
    import re as _re

    def _parse_exit_code(text: str) -> tuple[int, bool]:
        exit_code = 0
        m = _re.search(r"\[exit code:\s*(-?\d+)\]", text or "")
        if m:
            try:
                exit_code = int(m.group(1))
            except ValueError:
                pass
        is_err = (text or "").lstrip().startswith("Error")
        if is_err and exit_code == 0:
            exit_code = 1
        return exit_code, is_err

    async def _run_and_persist() -> str:
        try:
            output = await _run_command(
                {"command": command}, ws_path, progress_callback=progress_cb
            )
            exit_code, is_err = _parse_exit_code(output or "")
            status = "failed" if (exit_code != 0 or is_err) else "completed"
            finish_run(
                ws_path, task_id,
                status=status, exit_code=exit_code, output=output or "",
            )
            return output or ""
        except _asyncio.CancelledError:
            finish_run(ws_path, task_id, status="cancelled", exit_code=None, output="")
            raise
        except Exception as exc:
            err_text = f"Error: {exc}"
            finish_run(ws_path, task_id, status="failed", exit_code=1, output=err_text)
            raise

    # 20s 快返阈值：比 deploy_application 25s 更激进留 buffer，omnigate 30s 内必须返
    FAST_RETURN_TIMEOUT = 20.0
    cmd_task = _asyncio.create_task(_run_and_persist())

    try:
        output = await _asyncio.wait_for(
            _asyncio.shield(cmd_task), timeout=FAST_RETURN_TIMEOUT
        )
        # 快命令分支：完整返回，行为兼容旧版（agent 老 prompt 也能正常 parse）
        text = output or ""
        exit_code, is_err = _parse_exit_code(text)
        return {
            "ok": True,
            "task_id": task_id,
            "status": "completed",
            "output": text,
            "exit_code": exit_code,
            "is_error": is_err,
        }
    except _asyncio.TimeoutError:
        # 慢命令：shield 保护后台 task 继续跑，工具立即返
        logger.info(
            "run_workspace_command ws_id=%s task_id=%s 命令 >%.0fs 未完成"
            "（dolphin omnigate 30s timeout 保护），后台继续，agent 应轮询 get_dev_workspace_status",
            ws_id, task_id, FAST_RETURN_TIMEOUT,
        )
        return {
            "ok": True,
            "task_id": task_id,
            "status": "in_progress",
            "summary": (
                f"命令已在后台运行（task_id={task_id}，>{int(FAST_RETURN_TIMEOUT)}s 未完，"
                "dolphin MCP 30s timeout 限制下提前返回避免连接被强关）。\n"
                f"**下一步**：等 30-60 秒调 get_dev_workspace_status(ws_id=\"{ws_id}\") 查 "
                "last_command_run：\n"
                "- status=completed + exit_code=0 → 成功，看 output_tail 验证\n"
                "- status=failed → 看 output_tail 找报错并 edit 修\n"
                "- status=stale → workspace pod 重启，需重跑\n"
                "**不要立即重试 run_workspace_command**，否则会重复跑安装/构建。"
            ),
            "polling_hint": {
                "next_tool": "get_dev_workspace_status",
                "next_args": {"ws_id": ws_id},
                "wait_seconds": 30,
            },
        }


@mcp.tool()
async def build_dev_workspace(
    ws_id: str,
) -> dict:
    """只打包自开发 workspace，不上传、不 attach、不 republish，也不需要 env。

    适用场景：
    - 用户只想验证代码能不能打包；
    - 后端自开发包只想先产出 jar/zip；
    - 发布前先做一次标准构建检查。

    跟其他工具的区别：
    - run_workspace_command：手动跑任意命令，结果不保证是平台上传格式；
    - build_dev_workspace：标准构建 + 标准打包，只产出本地制品；
    - publish_dev_workspace：打包后继续上传平台、关联应用、重发应用，需要 env。
    """
    if not ws_id:
        return {"ok": False, "error_code": "INVALID_WS_ID", "message": "ws_id 不能为空"}

    tid, uid, _env_id = await _resolve_internal_identity_for_mcp()
    ws_path, err = _resolve_workspace_path(ws_id, tid, uid)
    if err:
        return err

    from app.coding.workspace import ProjectType, WorkspaceManager

    ws_mgr = WorkspaceManager()
    meta = ws_mgr.get_workspace_info(ws_id)
    project_type = str(meta.get("project_type") or "")

    try:
        artifacts: list[dict] = []
        if project_type in (
            ProjectType.FORM_COMPONENT_DUAL.value,
            ProjectType.DASHBOARD_COMPONENT_DUAL.value,
        ):
            for path, file_type in await ws_mgr.build_and_package_dual(ws_id):
                p = Path(path)
                artifacts.append({
                    "path": str(p),
                    "file_name": p.name,
                    "file_type": file_type,
                    "kind": "zip",
                    "size": p.stat().st_size if p.exists() else None,
                })
        else:
            package_path = Path(await ws_mgr.build_and_package(ws_id))
            artifacts.append({
                "path": str(package_path),
                "file_name": package_path.name,
                "file_type": "BACKENDENGINE" if project_type in (
                    ProjectType.BACKEND_API.value,
                    ProjectType.BACKEND_FEIGN.value,
                    ProjectType.BACKEND_SCHEDULED.value,
                ) else None,
                "kind": "zip",
                "size": package_path.stat().st_size if package_path.exists() else None,
            })

            if project_type in (
                ProjectType.BACKEND_API.value,
                ProjectType.BACKEND_FEIGN.value,
                ProjectType.BACKEND_SCHEDULED.value,
            ):
                output_dir = ws_mgr.get_build_output_dir(ws_id)
                jar_files = [p for p in output_dir.glob("*.jar") if not p.name.endswith(".original")]
                for jar in jar_files or list(output_dir.glob("*.jar")):
                    artifacts.append({
                        "path": str(jar),
                        "file_name": jar.name,
                        "file_type": "BACKENDENGINE",
                        "kind": "jar",
                        "size": jar.stat().st_size if jar.exists() else None,
                    })

        return {
            "ok": True,
            "ws_id": ws_id,
            "project_type": project_type,
            "artifacts": artifacts,
            "message": "打包成功；仅产出本地制品，未上传平台、未关联应用、未重发应用。",
            "next_tools": ["publish_dev_workspace"],
        }
    except Exception as exc:
        return _business_error(
            op="build_dev_workspace",
            error_text=str(exc),
            extra={
                "ws_id": ws_id,
                "project_type": project_type,
                "message": "打包失败；本工具不需要 env，失败原因通常是代码编译错误或主服务镜像缺少构建依赖。",
            },
        )


@mcp.tool()
async def publish_dev_workspace(
    ws_id: str,
    apaas_app_id: str = "",
    auto_attach: bool = True,
    auto_republish: bool = True,
    create_menu_name: str = "",
    create_menu_order: int = 0,
) -> dict:
    """把自开发 workspace build 产物 **一条龙**部署到 aPaaS：
    build & 上传到资源池 → 自动 attach 到应用 → 自动 republish 应用 → 可选建菜单。

    覆盖 V2.6 全 12 类 fileType：
      - form-component-dual / dashboard-component-dual → PC + 移动 双类型
      - form-page / menu-page / web-login → FRONTENGINE
      - form-list → FRONTLISTVIEW；layout → FRONTLAYOUT；mobile-page → MFRONTENGINE
      - plugin → FRONTTENANTCOMPONENT
      - backend-* → BACKENDENGINE / BACKPROPERTIES / BACKENDENGINEPKG

    入参：
        ws_id            必填，workspace id
        apaas_app_id     绑哪个应用（auto_attach / auto_republish 必填）。
                         **是 18-19 位长数字 snowflake**，不是 app_code。
                         不知道就先 list_apaas_apps 自己查，不要问用户。
        auto_attach      上传成功后自动 attach 到应用（默认 True）
        auto_republish   attach 成功后自动 republish 应用（默认 True）
        create_menu_name 非空 → 同时建一个自开发菜单（菜单中文名），默认""不建
        create_menu_order 新建菜单的 menuOrder（建菜单时用）

    返回成功：
        {
          "ok": true,
          "kit_id": "840353197380861952",       # 上传到资源池的 kit id
          "action": "create" | "update",        # 上传是新增还是更新
          "attached_to_app": true,              # auto_attach 结果
          "menu_id": "..." or null,             # 如建了菜单
          "republished": true,                  # auto_republish 结果
          "platform_app_url": "https://apaas-.../app/.../..."
        }

    **更新 vs 新增**：同 outputName 重 publish 走 update；不同名走 add。
    """
    if not ws_id:
        return {"ok": False, "error_code": "INVALID_WS_ID", "message": "ws_id 不能为空"}

    # 1) 内部上传接口暂时仍需要 platform_env_id；不暴露给工具参数，按 Header 身份反查。
    env_id = await _current_platform_env_id_for_header_identity()
    if not env_id or env_id <= 0:
        return {
            "ok": False,
            "error_code": "ENV_REQUIRED",
            "message": (
                "当前 Header 中的 aPaaS 租户 ID 没有关联到本部署唯一 aPaaS 平台配置，"
                "请检查 APAAS_BASE_URL 与租户绑定配置。"
            ),
            "should_retry": False,
        }

    # 2) auto_attach / auto_republish 需要 apaas_app_id
    apaas_app_id = (apaas_app_id or "").strip()
    chain_enabled = auto_attach or auto_republish or (create_menu_name and create_menu_name.strip())
    if chain_enabled and not apaas_app_id:
        return {
            "ok": False,
            "error_code": "APAAS_APP_ID_REQUIRED",
            "message": "auto_attach / auto_republish / create_menu_name 需要 apaas_app_id（18-19 位 snowflake）。",
            "next_action": "调 list_apaas_apps 找到目标应用，取其 apaas_app_id 再调本工具。",
            "should_retry": True,
        }
    if apaas_app_id and _looks_like_app_code_not_id(apaas_app_id):
        return _hint_use_list_apaas_apps(apaas_app_id)

    # 3) 算 tenant 上下文
    tid = await _resolve_alias_tid_for_env(int(env_id))
    uid = 1

    # ───────────── step 1: build + upload to platform pool ─────────────
    try:
        upload_result = await _api_call(
            "POST",
            f"/coding/workspace/{ws_id}/upload-to-platform",
            tenant_id=tid,
            user_id=uid,
            json_body={"env_id": int(env_id)},
            timeout=300.0,
            token_retry_env_id=int(env_id),
        )
    except RuntimeError as exc:
        return _business_error(
            op="publish_dev_workspace",
            error_text=str(exc),
            extra={"ws_id": ws_id, "env_id": int(env_id), "stage": "upload"},
        )

    kit_id = str(upload_result.get("kit_id") or upload_result.get("id") or "")
    output_name = str(upload_result.get("outputName") or upload_result.get("output_name") or "")
    file_name = str(upload_result.get("fileName") or upload_result.get("file_name") or "")

    result: dict = {
        "ok": True,
        "ws_id": ws_id,
        "stage": "uploaded",
        "kit_id": kit_id,
        "fileName": file_name,
        "outputName": output_name,
        "action": upload_result.get("action"),
        "attached_to_app": False,
        "republished": False,
        "menu_id": None,
        "platform_app_url": upload_result.get("platform_app_url"),
    }

    if not chain_enabled:
        result["message"] = "上传成功（未自动 attach/republish——auto_* 全 False）"
        return result

    # ───────────── step 2: enable self-dev config（幂等，已 ENABLE 直接成功）─────────────
    enable_resp = await enable_apaas_self_dev_config(
        apaas_app_id=apaas_app_id,
    )
    if not enable_resp.get("ok"):
        result["stage"] = "enable_failed"
        result["ok"] = False
        result["enable_error"] = enable_resp
        return result

    # ───────────── step 3: attach kit to app ─────────────
    if auto_attach and file_name:
        attach_resp = await attach_dev_packages_to_apaas_app(
            apaas_app_id=apaas_app_id,
            file_names=[file_name],
        )
        if not attach_resp.get("ok"):
            result["stage"] = "attach_failed"
            result["ok"] = False
            result["attach_error"] = attach_resp
            return result
        result["attached_to_app"] = True
        result["stage"] = "attached"

    # ───────────── step 4: create self-dev menu (optional) ─────────────
    if create_menu_name and create_menu_name.strip():
        # component_name 推断：apaas.json 里组件名 / package.json 的 name
        # outputName 是 zip 名（无 .zip），通常等于 project_name；
        # 真组件注册名是 apaas-custom-<biz>，需 workspace meta 反查。
        # MVP：直接用 outputName 当 component_name 后缀，agent 不满意可手动调
        # create_apaas_self_dev_menu 重建。
        guessed_component = output_name or file_name.replace(".zip", "")
        if not guessed_component.startswith("apaas-custom-"):
            guessed_component = f"apaas-custom-{guessed_component}"
        menu_resp = await create_apaas_self_dev_menu(
            apaas_app_id=apaas_app_id,
            menu_name=create_menu_name.strip(),
            component_name=guessed_component,
            menu_order=int(create_menu_order or 0),
        )
        if not menu_resp.get("ok"):
            result["stage"] = "menu_create_failed"
            result["ok"] = False
            result["menu_error"] = menu_resp
            return result
        result["menu_id"] = str(menu_resp.get("menu_id") or menu_resp.get("id") or "")

    # ───────────── step 5: republish app（含版本号策略 + patch+1 fallback）─────────────
    if auto_republish:
        rep_resp = await republish_apaas_app(
            apaas_app_id=apaas_app_id,
            abstract="自开发资源更新自动重发（publish_dev_workspace 一条龙）",
        )
        if not rep_resp.get("ok"):
            result["stage"] = "republish_failed"
            result["ok"] = False
            result["republish_error"] = rep_resp
            return result
        result["republished"] = True
        result["republished_version"] = rep_resp.get("version")
        result["stage"] = "republished"

    parts = ["上传"]
    if result["attached_to_app"]:
        parts.append("attach")
    if result["menu_id"]:
        parts.append("建菜单")
    if result["republished"]:
        parts.append(f"republish→{result.get('republished_version')}")
    result["message"] = "publish 一条龙完成：" + " + ".join(parts)
    return result


@mcp.tool()
async def attach_dev_component_to_form_field(
    apaas_app_id: str = "",
    form_id: str = "",
    field_uuid: str = "",
    component_code: str = "",
    republish: bool = True,
) -> dict:
    """把刚 publish 的自开发组件挂到表单的具体字段上（让该字段用自定义组件渲染）。

    场景：用户说"做一个星级评分组件，挂到客户表单的'满意度'字段上"。
    流程：先 publish_dev_workspace 把组件发到 apaas，本工具再把组件挂到字段。

    前置：
    1. publish_dev_workspace 已成功，组件已 attach 到应用 + republish；
    2. 你已通过 get_apaas_form_detail 拿到目标字段的 uuid；
    3. 你知道组件的 code——就是你写代码时在 apaas.json
       `customWidgetList[i].code` 里自己定的字符串，必须 'FORM_CUSTOM_' 开头。
       例：FORM_CUSTOM_ATTACHMENT_CAROUSEL / FORM_CUSTOM_STAR_RATING。

    入参：
        apaas_app_id     18-19 位 snowflake 应用 id
        form_id          目标表单 id（24 hex，从 get_apaas_app_overview menus 拿）
        field_uuid       目标字段 uuid（从 get_apaas_form_detail components 拿）
        component_code   组件 code（'FORM_CUSTOM_' 开头），就是 apaas.json
                         customWidgetList[i].code 的值。**这不是 Vue 组件名也不是 zip 名**。
        republish        改完是否自动 republish（默认 True；不重发用户看不到效果）

    返回成功：
        {
          "ok": true,
          "form_id": "...",
          "field_uuid": "...",
          "old_component_type": "FORM_RATE",
          "new_component_type": "FORM_CUSTOM_STAR_RATING",
          "republished": true
        }
    """
    if not apaas_app_id or _looks_like_app_code_not_id(apaas_app_id):
        return _hint_use_list_apaas_apps(apaas_app_id or "")
    if not form_id or not form_id.strip():
        return {
            "ok": False, "error_code": "INVALID_FORM_ID",
            "message": "form_id 不能为空。从 get_apaas_app_overview menus 找目标菜单的 form_id。",
        }
    if not field_uuid or not field_uuid.strip():
        return {
            "ok": False, "error_code": "INVALID_FIELD_UUID",
            "message": "field_uuid 不能为空。先调 get_apaas_form_detail(form_id, include=['components']) 拿目标字段 uuid。",
        }
    cc = (component_code or "").strip()
    if not cc.startswith("FORM_CUSTOM_"):
        return {
            "ok": False, "error_code": "INVALID_COMPONENT_CODE",
            "message": (
                f"component_code='{cc}' 必须 'FORM_CUSTOM_' 开头（全大写下划线）。\n"
                f"该值是你写组件时在 src/apaas.json 的 customWidgetList[i].code 里自己定的，"
                f"例：'FORM_CUSTOM_ATTACHMENT_CAROUSEL'。\n"
                f"**不是** Vue 组件名（apaas-custom-xxx），**不是** zip 包名（form-component-custom-xxx）。"
            ),
        }

    apaas_app_id = apaas_app_id.strip()
    form_id = form_id.strip()
    field_uuid = field_uuid.strip()

    async def _q(client) -> dict:
        return await client.set_field_custom_component(
            apaas_app_id, form_id, field_uuid, cc,
        )

    ok, payload = await _dispatch_apaas_call(
        "", 0, 0, 0, op="挂自定义组件到字段", fn=_q,
    )
    if not ok:
        return payload

    result: dict = {
        "ok": True,
        "form_id": form_id,
        "field_uuid": field_uuid,
        "old_component_type": (payload or {}).get("old_component_type"),
        "new_component_type": cc,
        "raw": payload,
        "republished": False,
    }

    if republish:
        rep = await republish_apaas_app(
            apaas_app_id=apaas_app_id,
            abstract=f"挂自定义组件 {cc} 到字段 {field_uuid}",
        )
        if not rep.get("ok"):
            result["ok"] = False
            result["error_code"] = "REPUBLISH_FAILED_AFTER_ATTACH"
            result["message"] = "componentType 已改写到表单，但 republish 失败 → 用户暂时看不到效果。手动调 force_regenerate_apaas_app 或让用户在 apaas 平台手发版本。"
            result["republish_error"] = rep
            return result
        result["republished"] = True
        result["republished_version"] = rep.get("version")

    result["message"] = (
        f"字段 {field_uuid} componentType 已改为 {cc}"
        + (f" + 应用已重发到 {result.get('republished_version')}" if result["republished"] else "")
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════
# ║  dev-coding V2.1：aPaaS 平台元数据查询工具组                                ║
# ║  ─────────────────────────────────────────────────────────────────────── ║
# ║  解决 form-page / form-list / backend-api 场景的"用户只知道应用名，不知道   ║
# ║  formId/字段编码"问题。3 个工具让 dolphin agent 在写代码前先把应用结构      ║
# ║  拉到 chat context，写出来的代码才能调对真实表单接口、字段名 / 字典 code 都  ║
# ║  对得上。                                                                  ║
# ║                                                                            ║
# ║  跟现有 list_apaas_models_in_env（配置态用、不含 fields）的区别：            ║
# ║  V2.1 工具是给"代码态写页面"设计的——返回带字段定义的结构化 JSON，agent    ║
# ║  能直接据此生成 form-page 的 v-for / 字段绑定 / 字典下拉等代码。            ║
# ═══════════════════════════════════════════════════════════════════════════


# @mcp.tool()  # [MERGED] -> get_apaas_app_overview(include=["models"], detail="full")
async def list_apaas_app_models(
    env: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出 aPaaS 平台某个应用下的所有数据模型（**含字段定义**）。

    dev-coding 写 form-page / form-list 必备的第一步——拿到应用下数据模型清单
    + 每个模型的字段（含 dataType / uiComponent / dictionaryCode 等），就能写出
    跟真实表单字段名对得上的 Vue 组件代码。

    跟 list_apaas_models_in_env 的区别：那个是配置态用（不返字段）；本工具
    给 dev-coding 用，**返回完整字段嵌套**。

    入参：
        env_id        平台环境 ID（先调 list_platform_envs 让用户选）
        apaas_app_id  aPaaS 平台内部应用 ID（字符串，长数字如 "836534627324657664"）

    返回：
        {
          "ok": true,
          "env_id": 2,
          "apaas_app_id": "836534627324657664",
          "models": [
            {
              "model_id": "...",
              "model_code": "order",
              "model_name": "订单",
              "model_type": "main|sub|process",
              "fields": [
                {
                  "field_code": "order_no",
                  "field_name": "订单号",
                  "data_type": "varchar",
                  "ui_component": "单行文本",
                  "dict_code": null,
                  "ref_form_id": null,
                  "required": true,
                  "length": 100
                },
                ...
              ],
              "field_count": 12
            },
            ...
          ],
          "total": 5
        }

    ⚠️ 编码边界：
      - 返回的 model_code 是 aPaaS 运行态/平台对象编码，用于开发时对接真实接口字段。
      - 它不等于设计文档里的“模型编码”。设计文档只能使用 snake_case 设计态编码。
      - 不要把 mc... 或 app$xxx 反写回第四章/第五章；SQL 表名/物理表名只能单独作为
        运行态映射说明。
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {
            "ok": False,
            "error_code": "INVALID_APAAS_APP_ID",
            "message": "apaas_app_id 不能为空（aPaaS 平台内部应用 ID，从 list_apaas_apps_in_env 拿）",
            "should_retry": False,
        }
    apaas_app_id = apaas_app_id.strip()

    async def _q(client) -> list:
        return await client.query_models(apaas_app_id)

    ok, payload = await _dispatch_apaas_call(
        env, env_id, tenant_id, user_id, op="拿应用模型详情", fn=_q,
    )
    if not ok:
        return payload

    models: list[dict] = []
    for m in payload or []:
        if not isinstance(m, dict):
            continue
        raw_fields = m.get("fields") or m.get("dataModelFields") or []
        fields: list[dict] = []
        for f in raw_fields if isinstance(raw_fields, list) else []:
            if not isinstance(f, dict):
                continue
            fields.append({
                "field_code": str(f.get("fieldCode", f.get("code", "")) or ""),
                "field_name": str(f.get("fieldName", f.get("name", "")) or ""),
                "data_type": str(f.get("dataType", f.get("dbDataType", "")) or ""),
                "ui_component": str(f.get("componentType", f.get("uiComponent", "")) or ""),
                "dict_code": (f.get("dictionaryCode") or f.get("dictCode") or None),
                "ref_form_id": (f.get("referenceFormId") or f.get("refFormId") or None),
                "required": bool(f.get("required", f.get("isRequired", False))),
                "length": f.get("length") or f.get("dataLength"),
            })
        models.append({
            "model_id": str(m.get("id", m.get("dataModelId", "")) or ""),
            "model_code": str(m.get("modelCode", m.get("code", "")) or ""),
            "model_code_kind": "apaas_runtime_code",
            "design_doc_code_rule": "设计文档模型编码必须是 snake_case；不要把 mc... 或 app$xxx 反写回设计文档",
            "model_name": str(m.get("modelName", m.get("name", "")) or ""),
            "model_type": str(m.get("modelType", "") or ""),
            "fields": fields,
            "field_count": len(fields),
        })

    return {
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id,
        "agent_notes": [
            "models[].model_code 是 aPaaS 线上运行态对象编码，用于代码对接平台接口，不是设计文档模型编码。",
            "设计文档模型编码仍必须是 snake_case；不要把 mc... 或 app$xxx 写回设计文档。",
        ],
        "models": models,
        "total": len(models),
    }


# @mcp.tool()  # [MERGED] -> get_apaas_app_overview(include=["dicts"], detail="full")
async def list_apaas_app_dicts(
    env: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    with_options: bool = False,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出 aPaaS 应用下的所有数据字典（下拉选项 / 单选框等的来源）。

    form-page 里的下拉选择、状态字段渲染都要按字典 code 拼组件——本工具返回
    应用下所有字典清单（dict_code / dict_name / options_count）。

    with_options=True 时一次性把所有字典的选项也拉回来（慢一点，但 agent 能
    直接用 v-for 渲染下拉）；False 时只返清单，agent 用到具体字典再查。

    入参：
        env_id        环境 ID
        apaas_app_id  aPaaS 应用 ID
        with_options  是否同时拉每个字典的选项（默认 False，加快首次拉取）

    返回：
        {
          "ok": true,
          "env_id": 2,
          "apaas_app_id": "...",
          "dicts": [
            {
              "dict_id": "...",
              "dict_code": "order_status",
              "dict_name": "订单状态",
              "options": [{"code": "draft", "name": "草稿"}, ...]   # 仅 with_options=True 时
            }
          ],
          "total": 8
        }
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {
            "ok": False,
            "error_code": "INVALID_APAAS_APP_ID",
            "message": "apaas_app_id 不能为空",
            "should_retry": False,
        }
    apaas_app_id = apaas_app_id.strip()

    async def _q(client) -> dict:
        dicts_raw = await client.query_dicts(apaas_app_id)
        dicts_normalized: list[dict] = []
        if not isinstance(dicts_raw, list):
            return {"dicts": []}
        for d in dicts_raw:
            if not isinstance(d, dict):
                continue
            entry = {
                "dict_id": str(d.get("id") or d.get("dictionaryId") or ""),
                "dict_code": str(d.get("dictionaryCode") or d.get("code") or ""),
                "dict_name": str(d.get("dictionaryName") or d.get("name") or ""),
            }
            if with_options and entry["dict_id"]:
                try:
                    opts = await client.query_dict_options(apaas_app_id, entry["dict_id"])
                    entry["options"] = [
                        {
                            "code": str(o.get("valueCode") or o.get("code") or ""),
                            "name": str(o.get("valueName") or o.get("name") or ""),
                        }
                        for o in (opts or [])
                        if isinstance(o, dict)
                    ]
                except Exception as exc:
                    logger.warning("query_dict_options 失败 dict_id=%s err=%s", entry["dict_id"], exc)
                    entry["options"] = []
            dicts_normalized.append(entry)
        return {"dicts": dicts_normalized}

    ok, payload = await _dispatch_apaas_call(
        env, env_id, tenant_id, user_id, op="拿应用字典", fn=_q,
    )
    if not ok:
        return payload

    dicts = (payload or {}).get("dicts", [])
    return {
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id,
        "dicts": dicts,
        "total": len(dicts),
    }


def _looks_like_app_code_not_id(s: str) -> bool:
    """检测传进来的"apaas_app_id"实际像 app_code（英文短串）还是真的 id（18-19 位数字）。

    apaas 平台真正的 apaas_app_id 是 snowflake：18-19 位纯数字字符串，如 836534627324657664。
    app_code 是建应用时取的英文短串，如 consumables-mgmt / sales-mgmt / lc-ops-mgmt。

    Agent 经常把 URL 里的 /app/<tenant>/<app_code>/ 误当 apaas_app_id 传进来 → 平台查无结果。
    """
    s = (s or "").strip()
    if not s:
        return False
    # 纯数字且 ≥ 12 位（snowflake 长度区间）→ 像真 id
    if s.isdigit() and len(s) >= 12:
        return False
    # 含非数字字符 → 多半是 app_code
    return True


def _hint_use_list_apaas_apps(suspected_app_code: str) -> dict:
    """统一的"你传错了 apaas_app_id，先调 list_apaas_apps 自己找"提示。"""
    return {
        "ok": False,
        "error_code": "APAAS_APP_ID_LOOKS_LIKE_APP_CODE",
        "message": (
            f"`apaas_app_id` 参数收到的是 '{suspected_app_code}'，看起来像 app_code（英文短串）"
            f"而不是 apaas_app_id（18-19 位纯数字 snowflake）。"
            f"apaas 平台所有元数据接口都要长数字 id，不接受 app_code。"
        ),
        "next_action": (
            f"立即调 list_apaas_apps(env='<alias>') 列租户下所有应用，"
            f"在返回结果里按 app_code 等于 '{suspected_app_code}' 找到对应那条，"
            f"取它的 `apaas_app_id`（长数字）再重新调当前工具。"
            f"**不要**回头问用户应用 ID——用户没义务知道。"
        ),
        "user_action_required": None,
        "should_retry": True,
    }


@mcp.tool()
async def get_apaas_app_overview(
    apaas_app_id: str = "",
    include: list[str] | None = None,
    detail: str = "brief",
) -> dict:
    """**一次性**拿到 aPaaS 应用全貌（合并 list_apaas_app_models / list_apaas_app_dicts / list_apaas_app_menus）。

    入参：
        apaas_app_id  必填
        include       列表，子集 of ["models","dicts","menus"]，默认 ["models","dicts"]
        detail        "brief" → models 不含 fields / dicts 不含 options（默认，省 token）
                      "full"  → models 含完整字段 / dicts 含 options

    返回（按 include 包含相应键）：
        {
          "ok": true,
          "apaas_app_id": "...",
          "models": [{model_code, model_name, model_type, field_count, fields?}],
          "dicts":  [{dict_code, dict_name, dict_id, options?}],
          "menus":  [...扁平化菜单树（含 form_id）...],
          "counts": {"models": 5, "dicts": 8, "menus": 38}
        }

    ⚠️ 编码边界：
      - 本工具返回的 models[].model_code 来自 aPaaS 线上接口，是“运行态/平台对象编码”，
        页面里可能显示为 mc...。
      - 设计文档第四章/第五章的“模型编码 / 目标模型编码 / 绑定主表模型”仍必须使用
        设计态 snake_case 编码，例如 assemble_workhour。
      - SQL/物理表名可能是 app$xxx 形态，但它也不是设计文档模型编码。不要建议用户把
        模型编码改成 mc... 或 app$xxx；如需说明 SQL 表名，只能作为运行态映射单独说明。
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {
            "ok": False,
            "error_code": "INVALID_APAAS_APP_ID",
            "message": "apaas_app_id 不能为空",
            "should_retry": False,
        }
    apaas_app_id = apaas_app_id.strip()
    if _looks_like_app_code_not_id(apaas_app_id):
        return _hint_use_list_apaas_apps(apaas_app_id)
    inc = set(include or ["models", "dicts"])
    if detail not in ("brief", "full"):
        return {
            "ok": False,
            "error_code": "INVALID_DETAIL",
            "message": "detail 必须是 brief 或 full",
            "should_retry": False,
        }
    full = detail == "full"

    import asyncio as _asyncio

    async def _q(client) -> dict:
        tasks = {}
        if "models" in inc:
            tasks["models"] = client.query_models(apaas_app_id)
        if "dicts" in inc:
            tasks["dicts"] = client.query_dicts(apaas_app_id)
        if "menus" in inc:
            tasks["menus"] = client.query_menus(apaas_app_id)
        keys = list(tasks.keys())
        results = await _asyncio.gather(*tasks.values(), return_exceptions=True)
        raw = dict(zip(keys, results))

        out: dict = {}

        if "models" in inc:
            mr = raw.get("models")
            models: list[dict] = []
            if not isinstance(mr, Exception) and isinstance(mr, list):
                for m in mr:
                    if not isinstance(m, dict):
                        continue
                    raw_fields = m.get("fields") or m.get("dataModelFields") or []
                    fc = len(raw_fields) if isinstance(raw_fields, list) else 0
                    entry = {
                        "model_id": str(m.get("id", m.get("dataModelId", "")) or ""),
                        "model_code": str(m.get("modelCode", m.get("code", "")) or ""),
                        "model_name": str(m.get("modelName", m.get("name", "")) or ""),
                        "model_type": str(m.get("modelType", "") or ""),
                        "field_count": fc,
                    }
                    if full:
                        fields: list[dict] = []
                        for f in raw_fields if isinstance(raw_fields, list) else []:
                            if not isinstance(f, dict):
                                continue
                            fields.append({
                                "field_code": str(f.get("fieldCode", f.get("code", "")) or ""),
                                "field_name": str(f.get("fieldName", f.get("name", "")) or ""),
                                "data_type": str(f.get("dataType", f.get("dbDataType", "")) or ""),
                                "ui_component": str(f.get("componentType", f.get("uiComponent", "")) or ""),
                                "dict_code": (f.get("dictionaryCode") or f.get("dictCode") or None),
                                "ref_form_id": (f.get("referenceFormId") or f.get("refFormId") or None),
                                "required": bool(f.get("required", f.get("isRequired", False))),
                                "length": f.get("length") or f.get("dataLength"),
                            })
                        entry["fields"] = fields
                    models.append(entry)
            out["models"] = models

        if "dicts" in inc:
            dr = raw.get("dicts")
            dicts_n: list[dict] = []
            if not isinstance(dr, Exception) and isinstance(dr, list):
                for d in dr:
                    if not isinstance(d, dict):
                        continue
                    entry = {
                        "dict_id": str(d.get("id") or d.get("dictionaryId") or ""),
                        "dict_code": str(d.get("dictionaryCode") or d.get("code") or ""),
                        "dict_name": str(d.get("dictionaryName") or d.get("name") or ""),
                    }
                    if full and entry["dict_id"]:
                        try:
                            opts = await client.query_dict_options(apaas_app_id, entry["dict_id"])
                            entry["options"] = [
                                {
                                    "code": str(o.get("valueCode") or o.get("code") or ""),
                                    "name": str(o.get("valueName") or o.get("name") or ""),
                                }
                                for o in (opts or [])
                                if isinstance(o, dict)
                            ]
                        except Exception as exc:
                            logger.warning("query_dict_options 失败 dict_id=%s err=%s", entry["dict_id"], exc)
                            entry["options"] = []
                    dicts_n.append(entry)
            out["dicts"] = dicts_n

        if "menus" in inc:
            mn = raw.get("menus")
            out["menus"] = _flatten_app_menus(mn or []) if not isinstance(mn, Exception) else []

        return out

    ok, payload = await _dispatch_apaas_call(
        "", 0, 0, 0, op="拿应用全貌", fn=_q,
    )
    if not ok:
        return payload

    result: dict = {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "agent_notes": [
            "models[].model_code 是 aPaaS 线上运行态对象编码，可能是 mc...；它不是设计文档第四章的模型编码。",
            "设计文档的模型编码/目标模型编码/绑定主表模型只能写 snake_case，例如 assemble_workhour。",
            "不要建议把设计文档模型编码改成 mc... 或 app$xxx；SQL/物理表名需要作为运行态映射单独说明。",
        ],
    }
    counts: dict = {}
    for k in ("models", "dicts", "menus"):
        if k in payload:
            result[k] = payload[k]
            counts[k] = len(payload[k])
    result["counts"] = counts
    return result


# ═══════════════════════════════════════════════════════════════════════════
# ║  dev-coding V2.2：apaas 自开发配置 + 重新发布工具组                          ║
# ║  ─────────────────────────────────────────────────────────────────────── ║
# ║  publish_dev_workspace 把 zip 上传到 apaas 平台后，还需要 3 步才能让用户     ║
# ║  在 apaas 真后台看到自开发组件：                                            ║
# ║    1) enable_apaas_self_dev_config  开启应用的「自开发配置」开关             ║
# ║    2) attach_dev_packages_to_apaas_app 把上传的 zip 关联到应用              ║
# ║    3) republish_apaas_app  应用重新发布版本（自开发变更必须 redeploy 生效）  ║
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def enable_apaas_self_dev_config(
    apaas_app_id: str = "",
    status: str = "ENABLE",
) -> dict:
    """开启 / 关闭 aPaaS 应用的「自开发配置」开关（apaas 平台 → 应用 → 高级设置）。

    publish_dev_workspace 把自开发包上传到 apaas 平台后，**必须先调本工具开启**
    应用的自开发配置，再调 attach_dev_packages_to_apaas_app 把 zip 关联到应用，
    最后 republish_apaas_app 重新发布——三步少一步前端用户都看不到组件。

    入参：
        apaas_app_id  aPaaS 应用 ID（字符串）
        status        ENABLE | DISABLE，默认 ENABLE

    返回：{"ok": true, "status": "ENABLE", "message": "操作成功"}
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {
            "ok": False, "error_code": "INVALID_APAAS_APP_ID",
            "message": "apaas_app_id 不能为空",
        }
    apaas_app_id = apaas_app_id.strip()
    if status not in ("ENABLE", "DISABLE"):
        return {
            "ok": False, "error_code": "INVALID_STATUS",
            "message": "status 必须是 ENABLE 或 DISABLE",
        }

    async def _q(client) -> dict:
        return await client.enable_self_dev_config(apaas_app_id, status=status)

    ok, payload = await _dispatch_apaas_call(
        "", 0, 0, 0, op="开启自开发配置", fn=_q,
    )
    if not ok:
        return payload
    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "status": status,
        "message": (payload or {}).get("message", "操作成功"),
    }


@mcp.tool()
async def list_apaas_dev_kits(
    scope: str = "app",
    apaas_app_id: str = "",
    file_name_filter: str = "",
    file_type_filter: str = "",
    key_word: str = "",
    page_size: int = 50,
) -> dict:
    """列出 apaas 自开发包 zip（合并 list_apaas_app_dev_kits + list_apaas_resource_pool_kits）。

    scope:
        "app"   → 单应用视角，只列绑到 apaas_app_id 的 zip（apaas_app_id 必填）
        "pool"  → 全资源池视角，跨应用 + 跨 fileType，用于"update vs create"判断

    入参：
        apaas_app_id      scope="app" 必填
        file_name_filter  scope="app" 用，按 fileName 模糊匹配
        file_type_filter  scope="pool" 用，过滤 fileType（V2.6 全 12 类）
        key_word          scope="pool" 用，按 fileName / outputName 模糊匹配
        page_size         scope="pool" 分页大小

    返回 {ok, scope, kits:[{id, fileName, fileType, fileTypeLabel?, version?, ...}], total, supported_file_types?}
    """
    scope = (scope or "app").strip().lower()
    if scope not in ("app", "pool"):
        return {
            "ok": False,
            "error_code": "INVALID_SCOPE",
            "message": "scope 必须是 'app' 或 'pool'",
            "should_retry": False,
        }

    if scope == "pool":
        valid_filter = (file_type_filter or "").strip().upper()
        if valid_filter and valid_filter not in _PLATFORM_FILE_TYPES_V2_6:
            return {
                "ok": False,
                "error_code": "INVALID_FILE_TYPE",
                "message": f"file_type_filter='{file_type_filter}' 不在 V2.6 全 12 类里",
                "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
            }

        async def _qp(client) -> list:
            import time as _time
            url = f"{client.base_url.rstrip('/')}/xdap-app/selfdevelopment/query/allDevelopmentKit"
            body = {"keyWord": (key_word or "").strip(), "page": 1, "pageSize": int(page_size)}
            if valid_filter:
                body["fileType"] = valid_filter
            async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
                resp = await http.post(
                    url,
                    headers={
                        "xdaptenantid": client.tenant_id,
                        "xdaptoken": client.token,
                        "xdaptimestamp": str(int(_time.time() * 1000)),
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            try:
                data = resp.json()
            except Exception:
                return []
            if data.get("code") != "ok":
                if "unauthorized" in str(data.get("message", "")).lower() or resp.status_code == 401:
                    raise RuntimeError("apaas token expired, retry needed")
                return []
            return data.get("table") or []

        ok, raw = await _dispatch_apaas_call(
            "", 0, 0, 0, op="列资源池自开发包", fn=_qp,
        )
        if not ok:
            return raw
        kits_pool = []
        for k in raw or []:
            if not isinstance(k, dict):
                continue
            ft = str(k.get("fileType") or "")
            kits_pool.append({
                "id": str(k.get("id") or ""),
                "fileName": str(k.get("fileName") or ""),
                "fileType": ft,
                "fileTypeLabel": _PLATFORM_FILE_TYPES_V2_6.get(ft, ft),
                "version": str(k.get("versionCode") or k.get("version") or ""),
                "size": k.get("size"),
                "userName": k.get("userName"),
                "createTime": k.get("createTime"),
                "description": k.get("description"),
            })
        return {
            "ok": True,
            "scope": "pool",
            "file_type_filter": valid_filter or None,
            "key_word": (key_word or "").strip() or None,
            "kits": kits_pool,
            "total": len(kits_pool),
            "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
        }

    # === scope == "app" ===
    """列出 apaas 应用可关联的自开发包（zip）—— 含 id / fileName / fileType。

    publish_dev_workspace 上传的 zip 会进入"自开发资源池"，本工具按 appId
    维度列出来（apaas 平台 UI 上「添加自开发资源」按钮触发的下拉就是它）。

    file_name_filter 留空时返全部；传字串时按 fileName 模糊匹配。

    返回：
        {
          "ok": true,
          "kits": [
            {"id": "840353197380861952", "fileName": "form-page-xxx.zip",
             "fileType": "FRONTCOMPONENT", "userName": "apaas-builder",
             "createTime": "..."},
            ...
          ],
          "total": 5
        }
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    apaas_app_id = apaas_app_id.strip()

    async def _q(client) -> list:
        return await client.query_app_dev_kits(apaas_app_id, file_name=file_name_filter)

    ok, kits = await _dispatch_apaas_call(
        "", 0, 0, 0, op="列自开发包", fn=_q,
    )
    if not ok:
        return kits
    normalized = []
    for k in kits or []:
        if not isinstance(k, dict):
            continue
        normalized.append({
            "id": str(k.get("id") or ""),
            "fileName": str(k.get("fileName") or ""),
            "fileType": str(k.get("fileType") or ""),
            "size": k.get("size"),
            "userName": k.get("userName"),
            "createTime": k.get("createTime"),
        })
    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "kits": normalized,
        "total": len(normalized),
    }


@mcp.tool()
async def attach_dev_packages_to_apaas_app(
    apaas_app_id: str = "",
    file_names: list[str] | None = None,
) -> dict:
    """把已上传到 apaas 平台的自开发包（zip）关联到应用的「自开发资源」列表。

    支持 V2.6 全 12 类 fileType（FRONTENGINE / FRONTCOMPONENT / FRONTLAYOUT /
    FRONTLISTVIEW / MFRONTENGINE / MFRONTCOMPONENT / FRONTTENANTCOMPONENT /
    BACKENDENGINE / BACKPROPERTIES / BACKENDENGINEPKG / DEPORTAL_SELF_PACKAGE /
    DEPORTAL_MOBILE_SELF_PACKAGE）——只看 fileName，跟 fileType 无关。

    工具内部两步：
      1) 调 selfdevelopment/query/likeDevelopmentKit 按 fileName 反查每个 zip 的 id
      2) 调 apaasSourceRelation/save，body 是
         {"objectType":"DEVELOPMENT_KIT","appId":X,"objectIds":[id1,id2]}

    前置：先调 enable_apaas_self_dev_config 开启自开发配置（不开 save 后无效）。
    后续：调 republish_apaas_app 重新发布版本让变更对前端用户生效。

    入参：
        apaas_app_id  应用 ID
        file_names    要关联的 zip 文件名列表，如 ["form-page-home-dashboard.zip"]
                      （从 publish_dev_workspace 返回的 message 里能拿到）

    返回（成功）：
        {"ok": true, "attached": [{"fileName": "...", "id": "..."}, ...],
         "missing": [], "message": "已关联 N 个自开发包"}

    返回（部分失败 / 名字没匹配上）：
        {"ok": true, "attached": [...], "missing": ["xxx.zip"], ...}
        attached 不空时仍 ok:true；agent 应给用户报告 missing 让他确认是不是
        zip 名字写错或 publish_dev_workspace 还没跑过

    返回（apaas 平台失败）：
        {"ok": false, "error_code": "BUSINESS_ERROR", "message": "..."}
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    apaas_app_id = apaas_app_id.strip()
    if not isinstance(file_names, list) or not file_names:
        return {
            "ok": False, "error_code": "INVALID_FILE_NAMES",
            "message": "file_names 必须是非空 list（zip 文件名，如 form-page-home-dashboard.zip）",
        }
    targets = [str(f).strip() for f in file_names if f and str(f).strip()]
    if not targets:
        return {"ok": False, "error_code": "INVALID_FILE_NAMES", "message": "file_names 全部为空"}


    async def _q(client) -> dict:
        # step 1: 列 app 可关联的全部 zip
        kits = await client.query_app_dev_kits(apaas_app_id)
        kit_by_name: dict[str, str] = {}
        for k in kits or []:
            if not isinstance(k, dict):
                continue
            fn = str(k.get("fileName") or "")
            kid = str(k.get("id") or "")
            if fn and kid:
                kit_by_name[fn] = kid

        attached: list[dict] = []
        missing: list[str] = []
        ids_to_attach: list[str] = []
        for name in targets:
            kid = kit_by_name.get(name)
            if kid:
                attached.append({"fileName": name, "id": kid})
                ids_to_attach.append(kid)
            else:
                missing.append(name)

        if not ids_to_attach:
            # 一个都没匹配上
            return {
                "_no_match": True,
                "missing": missing,
                "available_kit_count": len(kit_by_name),
                "available_first_5": list(kit_by_name.keys())[:5],
            }

        # step 2: save 关联
        save_result = await client.attach_apaas_source_relation(apaas_app_id, ids_to_attach)
        return {
            "attached": attached,
            "missing": missing,
            "save_message": (save_result or {}).get("message", "操作成功"),
        }

    ok, result = await _dispatch_apaas_call(
        "", 0, 0, 0, op="关联自开发资源", fn=_q,
    )
    if not ok:
        return result

    # 一个都没匹配上：返 ok:false 让 agent 报告用户
    if (result or {}).get("_no_match"):
        return {
            "ok": False,
            "error_code": "FILE_NAMES_NOT_FOUND",
            "message": (
                f"file_names {targets} 在该应用的自开发包池里一个都没找到。"
                f"可关联的包共 {result.get('available_kit_count', 0)} 个，"
                f"前 5 个 fileName: {result.get('available_first_5', [])}"
            ),
            "missing": result.get("missing", []),
            "user_action_required": (
                "确认 publish_dev_workspace 已成功上传过这些 zip + 文件名拼写正确"
                "（含 .zip 后缀）。或先调 list_apaas_app_dev_kits 看实际可关联的列表。"
            ),
            "should_retry": False,
        }

    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "attached": result.get("attached", []),
        "missing": result.get("missing", []),
        "message": f"已关联 {len(result.get('attached', []))} 个自开发包"
                   + (f"；{len(result.get('missing', []))} 个未找到" if result.get("missing") else ""),
    }


@mcp.tool()
async def republish_apaas_app(
    apaas_app_id: str = "",
    abstract: str = "自开发资源更新自动重发",
    version: str = "",
) -> dict:
    """重新发布 aPaaS 应用版本（自开发变更必须 redeploy 才生效）。

    版本号策略（apaas 平台行为反推 + 用户实测确认）：
      - apaas detail.currentVersion 是**下次发布的预备版本号**（不是已发布版本）
      - 平台前端"发布应用"按钮直接用 currentVersion 发，不 +1
      - 发布成功后 apaas 自动把 currentVersion 跳到下一个值（如 1.0.7 → 1.0.8）
      - 所以这里**直接用 currentVersion 发**，遇"应用版本错误"再 fallback patch +1

    入参：
        apaas_app_id  应用 ID
        abstract      版本摘要（用户看得到，建议带变更说明）
        version       可选——显式指定版本号（如 "1.0.8"）。空则用 currentVersion

    返回：{"ok": true, "version": "1.0.8", "message": "应用发布成功"}
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {
            "ok": False, "error_code": "INVALID_APAAS_APP_ID",
            "message": "apaas_app_id 不能为空",
        }
    apaas_app_id = apaas_app_id.strip()
    explicit_version = (version or "").strip()

    def _bump_patch(v: str) -> str:
        """1.0.7 → 1.0.8。失败返回原值。"""
        try:
            parts = [int(p) for p in v.split(".")]
            parts[-1] += 1
            return ".".join(str(p) for p in parts)
        except (ValueError, IndexError):
            return v

    async def _q(client) -> dict:
        if explicit_version:
            target = explicit_version
            attempted_strategy = "explicit"
        else:
            app_detail = await client.query_app_detail(apaas_app_id)
            target = (
                app_detail.get("currentVersion")
                or app_detail.get("appVersion")
                or app_detail.get("version")
                or "1.0.0"
            )
            attempted_strategy = "currentVersion"

        # 主路径：按 apaas 前端逻辑发 currentVersion
        try:
            result = await client.deploy_app(apaas_app_id, target, abstract=abstract)
            return {"version": target, "strategy": attempted_strategy, "raw": result}
        except Exception as e1:
            # apaas 返"应用版本错误"等版本相关业务错时 → patch +1 重试一次
            if "版本" in str(e1) or "version" in str(e1).lower():
                bumped = _bump_patch(target)
                if bumped != target:
                    try:
                        result = await client.deploy_app(apaas_app_id, bumped, abstract=abstract)
                        return {
                            "version": bumped,
                            "strategy": f"{attempted_strategy}+bump",
                            "raw": result,
                            "fallback_note": f"目标 {target} 失败，patch+1 到 {bumped} 成功",
                        }
                    except Exception as e2:
                        # 两次都失败，把两次错都回报
                        raise Exception(
                            f"版本 {target} 和 {bumped} 都发布失败。"
                            f"原始错误：{e1}；fallback 错误：{e2}"
                        )
            raise

    ok, result = await _dispatch_apaas_call(
        "", 0, 0, 0, op="重新发布应用", fn=_q,
    )
    if not ok:
        return result
    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "version": (result or {}).get("version"),
        "strategy": (result or {}).get("strategy"),
        "fallback_note": (result or {}).get("fallback_note"),
        "message": f"应用已发布到版本 {(result or {}).get('version')}",
    }


def _flatten_app_menus(nodes, parent_path: str = "", depth: int = 0, out: list | None = None) -> list:
    """把 manageAppMenu 返回的树形菜单扁平化成 list（agent 用着方便）。

    apaas 平台菜单嵌套字段是 `submenus`（实测从 GET /xdap-app/menu/query/manageAppMenu
    response 拿到），用户给的真实 JSON 显示最深 3 层。其它候选字段名作为兼容。
    """
    out = out if out is not None else []
    if not isinstance(nodes, list):
        return out
    for n in nodes:
        if not isinstance(n, dict):
            continue
        name = str(n.get("menuName") or n.get("name") or "")
        path_now = f"{parent_path}/{name}" if parent_path else name
        menu_type = str(n.get("menuType") or n.get("type") or "")
        out.append({
            "menu_id": str(n.get("id") or n.get("menuId") or ""),
            "menu_name": name,
            "menu_type": menu_type,                     # MENU / GROUP / MODEL / REPORT / MENU_TYPE_DASHBOARD / TODO ...
            "form_id": str(n.get("formId") or ""),      # MENU/MODEL/REPORT 类菜单有 formId，写代码 url 用这个
            "dashboard_id": str(n.get("dashboardId") or ""),  # 看板类菜单（MENU_TYPE_DASHBOARD）的关联 ID
            "process_id": str(n.get("processId") or ""),       # 带流程的菜单关联 ID
            "process_version": str(n.get("processVersion") or ""),
            "datasource_id": str(n.get("datasourceId") or ""),
            "datasource_code": str(n.get("datasourceCode") or ""),
            "menu_model_type": str(n.get("menuModelType") or ""),  # DATABASE / FORM / ...
            "menu_order": n.get("menuOrder", 0),
            "is_effective": bool(n.get("isEffective", False)),
            "path": path_now,
            "parent_id": str(n.get("parentId") or ""),
            "depth": depth,
            "has_children": bool(n.get("submenus") or n.get("children") or n.get("subMenus") or n.get("menuList")),
        })
        # 关键：apaas 平台用的是 `submenus`，不是 children/subMenus
        children = n.get("submenus") or n.get("children") or n.get("subMenus") or n.get("menuList")
        if children:
            _flatten_app_menus(children, path_now, depth + 1, out)
    return out


# @mcp.tool()  # [MERGED] -> get_apaas_app_overview(include=["menus"])
async def list_apaas_app_menus(
    env: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出 aPaaS 应用的菜单树（**含每个菜单关联的 formId / formCode**）。

    这是 V2.1 元数据查询的关键补充——之前的 list_apaas_app_models 给的是数据
    模型字段，但 form-page 写代码调真接口需要的是**表单的 formId**（同一个
    model 可能挂在多个 form 上，model_code != form_id）。本工具按 manageAppMenu
    endpoint 拿到应用的菜单树，每个菜单节点带 form_id / form_code / form_name /
    datasource_model_id 关联，agent 写代码时直接 `this.$request({url:
    \\`/xdap/api/runtime/${appId}/${formId}/list\\`})` 就能调对接口。

    **dolphin agent 工作流推荐位置**：step 2.5d（list_apaas_app_models 之后）
    并行调本工具，把"模型字段"和"菜单 formId"两条线对齐。

    返回（树形完整扁平化，**含全部子菜单层级**）：
        {
          "ok": true,
          "menus": [
            {
              "menu_id": "624735458923905024",
              "menu_name": "可视化工作台",
              "menu_type": "MENU_TYPE_DASHBOARD",   # 顶层看板
              "form_id": "",
              "dashboard_id": "66ec36bf6331be7ce1097ba8",
              "path": "可视化工作台",
              "depth": 0, "has_children": false, "parent_id": ""
            },
            {
              "menu_id": "623608536827428864",
              "menu_name": "01.基础管理",
              "menu_type": "GROUP",        # 分组菜单本身没 form_id
              "path": "01.基础管理",
              "depth": 0, "has_children": true, "parent_id": ""
            },
            {
              "menu_id": "740140918262202368",
              "menu_name": "模板管理",
              "menu_type": "GROUP",
              "path": "01.基础管理/模板管理",
              "depth": 1, "has_children": true,
              "parent_id": "623608536827428864"
            },
            {
              "menu_id": "800743105270644736",
              "menu_name": "里程碑模板管理",
              "menu_type": "MENU",
              "form_id": "696c93b03e5209310e0e906d",   # ← 真实 form_id 在叶子菜单
              "path": "01.基础管理/模板管理/里程碑模板管理",
              "depth": 2, "has_children": false,
              "parent_id": "740140918262202368"
            },
            ...
          ],
          "total": 38   # 含所有层级
        }

    field 速查：
      - `menu_type=GROUP`  → 分组节点，自己没 form_id，看子菜单
      - `menu_type=MENU` / `MODEL` / `REPORT`  → 业务菜单，**form_id 在这层**
      - `menu_type=MENU_TYPE_DASHBOARD`  → 看板，用 dashboard_id（不是 form_id）
      - `menu_type=TODO/MY_SUBMIT/MY_PARTICIPATE/...`  → 平台内置菜单，无 form_id
      - `process_id` 不空 → 该表单挂了流程
      - `depth` 字段方便 agent 按层级过滤（depth=0 顶层；leaf 用 has_children=false）
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {
            "ok": False, "error_code": "INVALID_APAAS_APP_ID",
            "message": "apaas_app_id 不能为空",
        }
    apaas_app_id = apaas_app_id.strip()

    async def _q(client) -> list:
        return await client.query_menus(apaas_app_id)

    ok, raw = await _dispatch_apaas_call(
        env, env_id, tenant_id, user_id, op="列应用菜单", fn=_q,
    )
    if not ok:
        return raw

    menus = _flatten_app_menus(raw or [])
    return {
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id,
        "menus": menus,
        "total": len(menus),
    }


@mcp.tool()
async def create_apaas_self_dev_menu(
    apaas_app_id: str = "",
    menu_name: str = "",
    component_name: str = "",
    parent_id: str = "",
    menu_icon: str = "userInfo",
    icon_color: str = "#027AFF",
    menu_display: str = "PC",
    menu_order: int = 0,
) -> dict:
    """在 aPaaS 应用菜单里创建一个**自开发页面菜单**（menuType=CUSTOM），让前端
    用户能从菜单进入自开发组件页面。

    这是 V2.2 部署链路 publish_dev_workspace → enable_apaas_self_dev_config →
    attach_dev_packages_to_apaas_app → republish_apaas_app 之后的**第 5 步**：
    没建菜单的话用户在 apaas 平台前台看不到入口，自开发包白部署。

    入参：
        apaas_app_id    应用 ID
        menu_name       菜单中文名（用户看到的）—— 如「项目分析图表」
        component_name  自开发组件注册名 —— 必须 apaas-custom- 开头
                        （form-page 场景就是 src/index.js 注册的 Vue.component(name) 那个 name，
                         一般跟 workspace 的 project_name 对应：
                         project_name="form-page-home-dashboard" → component_name="apaas-custom-home-dashboard"）
        parent_id       挂哪个父菜单下；空 = 顶层（默认）。父菜单 ID 从
                        list_apaas_app_menus 拿（找 menu_type=GROUP 的 menu_id）
        menu_icon       图标名（默认 'userInfo'，apaas 内置图标库）
        icon_color      图标颜色（默认 #027AFF 蓝）
        menu_display    PC / MOBILE / ALL（默认 PC）
        menu_order      菜单排序（数字越小越靠前，默认 0）

    返回：
        {"ok": true, "menu_name": "...", "component_name": "...", "message": "..."}

    ⚠️ 顺序提醒（自开发完整部署链路）：
      1. publish_dev_workspace             — 上传 zip 到资源池
      2. enable_apaas_self_dev_config      — 开应用自开发开关
      3. attach_dev_packages_to_apaas_app  — zip 绑到应用
      4. **本工具 create_apaas_self_dev_menu** — 加菜单入口（**易漏！**）
      5. republish_apaas_app               — 重发版本生效

    跳过本步用户找不到入口（应用菜单里没"项目分析图表"这种条目）。
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    if not menu_name or not menu_name.strip():
        return {"ok": False, "error_code": "INVALID_MENU_NAME", "message": "menu_name 不能为空"}
    if not component_name or not component_name.strip():
        return {
            "ok": False, "error_code": "INVALID_COMPONENT_NAME",
            "message": "component_name 不能为空",
            "user_action_required": "传 src/index.js 注册的 Vue.component(name) 那个 name，必须 apaas-custom- 开头",
        }
    component_name = component_name.strip()
    if not component_name.startswith("apaas-custom-"):
        return {
            "ok": False, "error_code": "INVALID_COMPONENT_NAME",
            "message": f"component_name 必须以 apaas-custom- 开头（实际：{component_name}）",
            "user_action_required": "改成 apaas-custom-{业务名}，跟 form-page workflow 注册组件名规范一致",
        }
    if menu_display not in ("PC", "MOBILE", "ALL"):
        return {
            "ok": False, "error_code": "INVALID_MENU_DISPLAY",
            "message": f"menu_display 必须是 PC/MOBILE/ALL，实际：{menu_display}",
        }

    apaas_app_id = apaas_app_id.strip()

    async def _q(client) -> dict:
        return await client.create_self_dev_menu(
            app_id=apaas_app_id,
            menu_name=menu_name.strip(),
            link_url=component_name,
            parent_id=(parent_id or "").strip(),
            menu_icon=menu_icon,
            icon_color=icon_color,
            menu_display=menu_display,
            menu_order=menu_order,
        )

    ok, result = await _dispatch_apaas_call(
        "", 0, 0, 0, op="创建自开发菜单", fn=_q,
    )
    if not ok:
        return result

    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "menu_name": menu_name,
        "component_name": component_name,
        "parent_id": parent_id or None,
        "message": (result or {}).get("message", "菜单创建成功"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# ║  dev-coding V2.5：表单运行时元数据查询（tabId / 组件 uuid）                  ║
# ║  ─────────────────────────────────────────────────────────────────────── ║
# ║  补全 dolphin agent 写 form-page 代码闭环：用户中文表单名 → form_id（已有  ║
# ║  list_apaas_app_menus）→ **tab_id（本组工具）** → **组件 uuid 映射（本组  ║
# ║  工具）** → 写 vue 调 listPageBusinessData。                               ║
# ║                                                                            ║
# ║  关键认知：**列表数据接口返回行的 key 是组件 uuid 不是字段名**——必须先调   ║
# ║  list_apaas_form_components 拿 uuid → label / chooseOptions 映射，agent    ║
# ║  写表头 / 渲染下拉才能用对。                                               ║
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_apaas_form_detail(
    apaas_app_id: str = "",
    form_id: str = "",
    include: list[str] | None = None,
) -> dict:
    """拿 aPaaS 表单详情（合并 list_apaas_form_views + list_apaas_form_components）。

    入参：
        apaas_app_id, form_id  必填
        include  ["views","components"] 子集，默认两者全要

    返回（按 include 包含相应键）：
        views:      [{tab_id, tab_name}]，listPageBusinessData 必传的 tabId
        components: [{uuid, label, component_type, bo_code, choose_options, ...}]，
                    前端渲染列/下拉用的 uuid→label 映射
        default_tab_id: views 第一项的 tab_id

    list_apaas_form_views / list_apaas_form_components 合并入口。
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    if not form_id or not form_id.strip():
        return {"ok": False, "error_code": "INVALID_FORM_ID", "message": "form_id 不能为空"}
    apaas_app_id = apaas_app_id.strip()
    form_id = form_id.strip()
    if _looks_like_app_code_not_id(apaas_app_id):
        return _hint_use_list_apaas_apps(apaas_app_id)
    inc = set(include or ["views", "components"])

    import asyncio as _asyncio

    async def _q(client) -> dict:
        tasks = {}
        if "views" in inc:
            tasks["views"] = client.query_form_views(apaas_app_id, form_id)
        if "components" in inc:
            tasks["components"] = client.query_form_components(apaas_app_id, form_id)
        keys = list(tasks.keys())
        results = await _asyncio.gather(*tasks.values(), return_exceptions=True)
        raw = dict(zip(keys, results))
        out: dict = {}

        if "views" in inc:
            vr = raw.get("views")
            views: list[dict] = []
            if not isinstance(vr, Exception) and isinstance(vr, list):
                for v in vr:
                    if not isinstance(v, dict):
                        continue
                    views.append({
                        "tab_id": str(v.get("tabId") or v.get("id") or ""),
                        "tab_name": str(v.get("tabName") or v.get("name") or v.get("viewName") or v.get("title") or ""),
                    })
            out["views"] = views

        if "components" in inc:
            cr = raw.get("components")
            comps: list[dict] = []
            if not isinstance(cr, Exception) and isinstance(cr, list):
                for c in cr:
                    if not isinstance(c, dict):
                        continue
                    choose_opts = c.get("chooseOptions") or []
                    norm_choose = [
                        {"id": str(o.get("id") or ""), "label": str(o.get("label") or "")}
                        for o in choose_opts if isinstance(o, dict)
                    ]
                    dict_opts = c.get("dictionaryChooseOptions") or []
                    norm_dict = [
                        {"code": str(o.get("valueCode") or o.get("code") or ""),
                         "name": str(o.get("valueName") or o.get("name") or o.get("label") or "")}
                        for o in dict_opts if isinstance(o, dict)
                    ]
                    comps.append({
                        "uuid": str(c.get("uuid") or ""),
                        "label": str(c.get("label") or c.get("name") or ""),
                        "component_type": str(c.get("componentType") or ""),
                        "bo_code": str(c.get("boCode") or ""),
                        "business_object_component_type": str(c.get("businessObjectComponentType") or ""),
                        "required": bool(c.get("required", False)),
                        "choose_options": norm_choose,
                        "dictionary_choose_options": norm_dict,
                    })
            out["components"] = comps

        return out

    ok, payload = await _dispatch_apaas_call(
        "", 0, 0, 0, op="拿表单详情", fn=_q,
    )
    if not ok:
        return payload

    result: dict = {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "form_id": form_id,
    }
    if "views" in payload:
        result["views"] = payload["views"]
        result["default_tab_id"] = payload["views"][0]["tab_id"] if payload["views"] else None
    if "components" in payload:
        result["components"] = payload["components"]
    return result


async def _legacy_list_apaas_form_views_unused(
    env: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    form_id: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """[MERGED] 旧 list_apaas_form_views，保留实现但不再注册到 MCP。改用 get_apaas_form_detail(include=["views"]).

    listPageBusinessData 接口必须传 tabId（一个表单多个视图：'全部' / '我的' /
    '待办' 等），所以是 form-page 数据查询的**前置必调**步骤。

    在 dolphin agent 工作流：
      step 2.5 用户说"用项目管理表单的数据" →
      list_apaas_app_menus 找到"项目管理"菜单 → 拿 form_id →
      **本工具拿 tab_id**（一般取第一个，或问用户选）→
      list_apaas_form_components 拿字段 uuid 映射 → 写 vue 代码

    入参：
        env_id        环境 ID
        apaas_app_id  应用 ID
        form_id       表单 ID（从 list_apaas_app_menus 返回的 form_id 拿）

    返回：
        {
          "ok": true,
          "views": [
            {"tab_id": "tab_001", "tab_name": "全部数据"},
            {"tab_id": "tab_002", "tab_name": "我的工单"}
          ],
          "default_tab_id": "tab_001"   # 第一个视图，agent 不确定时直接用
        }
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    if not form_id or not form_id.strip():
        return {"ok": False, "error_code": "INVALID_FORM_ID", "message": "form_id 不能为空，先调 list_apaas_app_menus 拿"}
    apaas_app_id = apaas_app_id.strip()
    form_id = form_id.strip()

    async def _q(client) -> list:
        return await client.query_form_views(apaas_app_id, form_id)

    ok, raw = await _dispatch_apaas_call(
        env, env_id, tenant_id, user_id, op="列表单视图", fn=_q,
    )
    if not ok:
        return raw

    views = []
    for v in raw or []:
        if not isinstance(v, dict):
            continue
        views.append({
            "tab_id": str(v.get("tabId") or v.get("id") or ""),
            "tab_name": str(v.get("tabName") or v.get("name") or v.get("viewName") or v.get("title") or ""),
        })
    return {
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id,
        "form_id": form_id,
        "views": views,
        "default_tab_id": views[0]["tab_id"] if views else None,
        "total": len(views),
    }


# @mcp.tool()  # [MERGED] -> get_apaas_form_detail(include=["components"])
async def list_apaas_form_components(
    env: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    form_id: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出表单的所有组件（**uuid → label 映射 + 下拉选项**）。

    listPageBusinessData 返回的行数据 key 是组件 **uuid**（不是字段名 / boCode），
    所以前端 vue 渲染表格列、下拉选项、详情字段都得用本工具的映射：
      `<el-table-column :prop="comp.uuid" :label="comp.label" />`

    跟 list_apaas_app_models 区别：
      - list_apaas_app_models：数据模型层 modelField（boCode / dataType）
      - **list_apaas_form_components：表单组件层 uuid（前端真实用的 key）**
      两套数据都要拿——models 用于建模视角，components 用于写运行时代码。

    入参：
        env_id, apaas_app_id, form_id

    返回：
        {
          "ok": true,
          "components": [
            {
              "uuid": "comp_uuid_001",          # ← 列表数据 key
              "label": "工单标题",                # ← 表头中文
              "component_type": "FORM_INPUT",
              "bo_code": "title",
              "required": true,
              "choose_options": [],              # 下拉选项（FORM_SELECT_INPUT 时有）
              "dictionary_choose_options": []    # 字典选项
            },
            {
              "uuid": "comp_uuid_002",
              "label": "优先级",
              "component_type": "FORM_SELECT_INPUT",
              "choose_options": [
                {"id": "high", "label": "高"},
                {"id": "medium", "label": "中"},
                {"id": "low", "label": "低"}
              ]
            }
          ],
          "total": 12
        }
    """
    if not apaas_app_id or not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
    if not form_id or not form_id.strip():
        return {"ok": False, "error_code": "INVALID_FORM_ID", "message": "form_id 不能为空"}
    apaas_app_id = apaas_app_id.strip()
    form_id = form_id.strip()

    async def _q(client) -> list:
        return await client.query_form_components(apaas_app_id, form_id)

    ok, raw = await _dispatch_apaas_call(
        env, env_id, tenant_id, user_id, op="列表单组件", fn=_q,
    )
    if not ok:
        return raw

    comps = []
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        # 规整下拉选项格式
        choose_opts = c.get("chooseOptions") or []
        norm_choose = [
            {"id": str(o.get("id") or ""), "label": str(o.get("label") or "")}
            for o in choose_opts if isinstance(o, dict)
        ]
        dict_opts = c.get("dictionaryChooseOptions") or []
        norm_dict = [
            {"code": str(o.get("valueCode") or o.get("code") or ""),
             "name": str(o.get("valueName") or o.get("name") or o.get("label") or "")}
            for o in dict_opts if isinstance(o, dict)
        ]
        comps.append({
            "uuid": str(c.get("uuid") or ""),
            "label": str(c.get("label") or c.get("name") or ""),
            "component_type": str(c.get("componentType") or ""),
            "bo_code": str(c.get("boCode") or ""),
            "business_object_component_type": str(c.get("businessObjectComponentType") or ""),
            "required": bool(c.get("required", False)),
            "choose_options": norm_choose,
            "dictionary_choose_options": norm_dict,
        })
    return {
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id,
        "form_id": form_id,
        "components": comps,
        "total": len(comps),
    }


# ═══════════════════════════════════════════════════════════════════════════
# ║  V2.6：12 类全 fileType 支持 + "更新 vs 新增" 决策辅助                       ║
# ║  ─────────────────────────────────────────────────────────────────────── ║
# ║  list_apaas_resource_pool_kits — 全资源池查重（跨应用，按 fileType 过滤）    ║
# ║  upload_external_zip_to_apaas  — 直传外部 zip（不走 workspace）             ║
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


# @mcp.tool()  # [MERGED] -> list_apaas_dev_kits(scope="pool", ...)
async def list_apaas_resource_pool_kits(
    env: str = "",
    env_id: int = 0,
    file_type_filter: str = "",
    key_word: str = "",
    page_size: int = 50,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """**全资源池**列出 apaas 平台上所有自开发包（跨应用、跨 fileType）—— 给 agent
    在 publish 前判断"这个名字是更新还是新增"用。

    跟 list_apaas_app_dev_kits 的关键区别：那个是**单应用**视角（只列绑到指定 app
    的 zip），本工具是**全租户资源池**视角（跨应用，包括没绑任何 app 的 zip）。

    用途（agent 常用）：
      - 用户说"更新一下我之前那个评分组件" → 用 key_word="form-component-rating"
        查，命中 → 走 publish_dev_workspace 自动 update（同 project_name）
      - 用户说"新建一个组件叫 XXX" → 用 key_word="form-component-xxx" 查，
        没命中 → 起 workspace + publish 即可
      - 想看资源池里有哪些仪表板组件 → file_type_filter="DEPORTAL_SELF_PACKAGE"

    入参：
        env_id           平台环境 ID
        file_type_filter 可选，过滤 fileType（V2.6 全 12 类之一）。空 = 全部
        key_word         可选，按 fileName / outputName 模糊匹配（不带 .zip 后缀）
        page_size        每页条数，默认 50

    返回：
        {
          "ok": true,
          "kits": [
            {
              "id": "840353197380861952",
              "fileName": "form-component-rating.zip",
              "fileType": "FRONTCOMPONENT",
              "fileTypeLabel": "Web端自开发组件",
              "version": "1.0.0",
              "userName": "apaas-builder",
              "createTime": "..."
            },
            ...
          ],
          "total": 12,
          "supported_file_types": {"FRONTENGINE": "Web端自开发页面", ...}
        }

    返回 supported_file_types 是 V2.6 全 12 类索引，让 agent 知道平台支持什么。
    """
    valid_filter = (file_type_filter or "").strip().upper()
    if valid_filter and valid_filter not in _PLATFORM_FILE_TYPES_V2_6:
        return {
            "ok": False,
            "error_code": "INVALID_FILE_TYPE",
            "message": (
                f"file_type_filter='{file_type_filter}' 不在 V2.6 全 12 类里。"
                f"合法值：{list(_PLATFORM_FILE_TYPES_V2_6.keys())}"
            ),
            "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
        }
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)

    async def _q(client) -> list:
        # APaaSClient 没有现成方法，直接 raw POST 到 selfdevelopment/query/allDevelopmentKit
        import time as _time
        url = f"{client.base_url.rstrip('/')}/xdap-app/selfdevelopment/query/allDevelopmentKit"
        body = {"keyWord": (key_word or "").strip(), "page": 1, "pageSize": int(page_size)}
        if valid_filter:
            body["fileType"] = valid_filter
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
            resp = await http.post(
                url,
                headers={
                    "xdaptenantid": client.tenant_id,
                    "xdaptoken": client.token,
                    "xdaptimestamp": str(int(_time.time() * 1000)),
                    "Content-Type": "application/json",
                },
                json=body,
            )
        try:
            data = resp.json()
        except Exception:
            return []
        if data.get("code") != "ok":
            # 沿 _with_apaas_client 的 token 自愈链路：抛带"unauthorized"信号让上层重试
            if "unauthorized" in str(data.get("message", "")).lower() or resp.status_code == 401:
                raise RuntimeError("apaas token expired, retry needed")
            return []
        return data.get("table") or []

    ok, raw = await _dispatch_apaas_call(
        env, env_id, tenant_id, user_id, op="列资源池自开发包", fn=_q,
    )
    if not ok:
        return raw

    kits = []
    for k in raw or []:
        if not isinstance(k, dict):
            continue
        ft = str(k.get("fileType") or "")
        kits.append({
            "id": str(k.get("id") or ""),
            "fileName": str(k.get("fileName") or ""),
            "fileType": ft,
            "fileTypeLabel": _PLATFORM_FILE_TYPES_V2_6.get(ft, ft),
            "version": str(k.get("versionCode") or k.get("version") or ""),
            "size": k.get("size"),
            "userName": k.get("userName"),
            "createTime": k.get("createTime"),
            "description": k.get("description"),
        })
    return {
        "ok": True,
        "env_id": env_id,
        "file_type_filter": valid_filter or None,
        "key_word": (key_word or "").strip() or None,
        "kits": kits,
        "total": len(kits),
        "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
    }


@mcp.tool()
async def upload_external_zip_to_apaas(
    file_name: str = "",
    file_content_b64: str = "",
    file_type: str = "",
    description: str = "",
    apaas_app_id: str = "",
) -> dict:
    """直接上传一个外部 zip 到 apaas 平台（不走 workspace），覆盖 V2.6 全 12 类
    fileType。

    用例：
      - 用户已经在别处（IDE / 旧脚手架）build 好一个 zip，让 agent 直接传到平台
      - dashboard 组件平台暂没自动脚手架，用户给个 zip 让 agent 上传 +
        关联 + 重发
      - 修一个老 plugin / 后端配置 zip

    自动判断 update vs create（跟 publish_dev_workspace 同款逻辑）：
      先 selfdevelopment/query/allDevelopmentKit 按 file_name 反查，
      命中 → update/developmentKit；没命中 → add/developmentKit。

    入参：
        file_name        zip 文件名（含 .zip 后缀），平台拿这个做查重 + 显示
        file_content_b64 zip 文件 base64 编码内容（不要前缀 data:application/zip;base64,）
        file_type        V2.6 全 12 类之一
        description      可选，平台侧描述
        apaas_app_id     可选，传了就上传后**自动绑到这个应用**的自开发资源里
                         （省一步 attach_dev_packages_to_apaas_app）

    返回：
        {"ok": true, "action": "update"|"create", "fileName": "...",
         "kit_id": "...", "attached_to_app": true/false, "message": "..."}

    限制：
      - 实际 zip 内容传输走 base64，建议 < 8MB（base64 膨胀 33%）。更大走 publish_dev_workspace
        + workspace 本地路径流式上传。
      - file_type 必须是 _PLATFORM_FILE_TYPES_V2_6 里的合法 key（不区分大小写，
        统一规整成大写）。
    """
    import base64
    import time as _time
    import uuid as _uuid

    valid_ft = (file_type or "").strip().upper()
    if valid_ft not in _PLATFORM_FILE_TYPES_V2_6:
        return {
            "ok": False,
            "error_code": "INVALID_FILE_TYPE",
            "message": (
                f"file_type='{file_type}' 不在 V2.6 全 12 类里。"
                f"合法值：{list(_PLATFORM_FILE_TYPES_V2_6.keys())}"
            ),
            "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
        }
    fname = (file_name or "").strip()
    if not fname:
        return {"ok": False, "error_code": "INVALID_FILE_NAME", "message": "file_name 不能为空"}
    if "/" in fname or "\\" in fname:
        return {"ok": False, "error_code": "INVALID_FILE_NAME", "message": "file_name 只能是文件名，不能含路径分隔符"}
    if not file_content_b64 or not file_content_b64.strip():
        return {"ok": False, "error_code": "INVALID_CONTENT", "message": "file_content_b64 不能为空"}

    try:
        zip_bytes = base64.b64decode(file_content_b64.strip())
    except Exception as e:
        return {"ok": False, "error_code": "INVALID_BASE64", "message": f"base64 解码失败: {e}"}

    if len(zip_bytes) == 0:
        return {"ok": False, "error_code": "INVALID_CONTENT", "message": "解码后 zip 内容为 0 字节"}
    if len(zip_bytes) > 50 * 1024 * 1024:
        return {
            "ok": False,
            "error_code": "FILE_TOO_LARGE",
            "message": f"解码后 zip = {len(zip_bytes) // 1024 // 1024}MB > 50MB；走 publish_dev_workspace 流式路径",
        }

    async def _q(client) -> dict:
        # 1) 查重
        query_url = f"{client.base_url.rstrip('/')}/xdap-app/selfdevelopment/query/allDevelopmentKit"
        # keyWord 去 .zip 后缀做模糊查
        kw = fname[:-4] if fname.lower().endswith(".zip") else fname
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
                qresp = await http.post(
                    query_url,
                    headers={
                        "xdaptenantid": client.tenant_id,
                        "xdaptoken": client.token,
                        "xdaptimestamp": str(int(_time.time() * 1000)),
                        "Content-Type": "application/json",
                    },
                    json={"keyWord": kw, "page": 1, "pageSize": 50},
                )
            qdata = qresp.json() if qresp.content else {}
        except Exception:
            qdata = {}
        existing_kit = None
        for k in (qdata.get("table") or []):
            if isinstance(k, dict) and k.get("fileName") == fname:
                existing_kit = k
                break

        # 2) 构造 form
        from datetime import datetime as _dt
        eff_desc = description or f"由 dolphin agent 上传"
        if existing_kit:
            ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            eff_desc = f"{eff_desc}（更新于 {ts}）"
        form = {
            "fileType": valid_ft,
            "description": eff_desc,
            "uploadId": str(int(_time.time() * 1000)),
            "versionCode": _uuid.uuid4().hex,
            "useScope": "全部应用",
            "internalResource": "false",
            "effectiveScope": "SINGLE_APPLICATION",
        }
        if existing_kit:
            for key in ("id", "ossObjectName", "fileName", "yeahMonthDate"):
                val = existing_kit.get(key)
                if val is not None:
                    form[key] = str(val)
            if existing_kit.get("useScope"):
                form["useScope"] = existing_kit["useScope"]
            if existing_kit.get("effectiveScope"):
                form["effectiveScope"] = existing_kit["effectiveScope"]

        action = "update" if existing_kit else "create"
        target = (
            f"{client.base_url.rstrip('/')}/xdap-app/selfdevelopment/"
            + ("update/developmentKit" if existing_kit else "add/developmentKit")
        )
        async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
            uresp = await http.post(
                target,
                headers={
                    "xdaptenantid": client.tenant_id,
                    "xdaptoken": client.token,
                    "xdaptimestamp": str(int(_time.time() * 1000)),
                },
                files={"file": (fname, zip_bytes, "application/zip")},
                data=form,
            )
        try:
            udata = uresp.json()
        except Exception:
            raise RuntimeError(f"平台响应非 JSON, status={uresp.status_code}")

        if udata.get("code") not in ("ok", 200):
            msg = (udata.get("message") or "上传失败").lower()
            if "unauthorized" in msg or uresp.status_code == 401:
                raise RuntimeError("apaas token expired, retry needed")
            raise RuntimeError(udata.get("message") or "平台拒绝上传")

        kit_id = ""
        # 上传成功后再查一次拿 kit_id（add 接口不一定回 id）
        try:
            async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
                q2 = await http.post(
                    query_url,
                    headers={
                        "xdaptenantid": client.tenant_id,
                        "xdaptoken": client.token,
                        "xdaptimestamp": str(int(_time.time() * 1000)),
                        "Content-Type": "application/json",
                    },
                    json={"keyWord": kw, "page": 1, "pageSize": 50},
                )
            for k in (q2.json().get("table") or []):
                if isinstance(k, dict) and k.get("fileName") == fname:
                    kit_id = str(k.get("id") or "")
                    break
        except Exception:
            pass

        # 3) 可选：自动绑到 app
        attached = False
        if apaas_app_id and kit_id:
            try:
                await client.attach_apaas_source_relation(apaas_app_id, [kit_id])
                attached = True
            except Exception as exc:
                logger.warning("upload_external_zip 上传成功但绑应用失败: %s", exc)

        return {
            "action": action,
            "fileName": fname,
            "fileType": valid_ft,
            "fileTypeLabel": _PLATFORM_FILE_TYPES_V2_6[valid_ft],
            "kit_id": kit_id,
            "attached_to_app": attached,
            "platform_message": udata.get("message") or "操作成功",
        }

    ok, result = await _dispatch_apaas_call(
        "", 0, 0, 0, op="直传外部 zip 到资源池", fn=_q,
    )
    if not ok:
        return result
    return {"ok": True, **result}


# ─────────────────────────── 工具注册：统一主入口 + split 兼容 ───────────────────────────


def _registered_tool_names(server) -> set[str]:
    tool_manager = getattr(server, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", None)
    return set(tools) if isinstance(tools, dict) else set()


def _register_tools_once(server, fns: list, label: str) -> None:
    existing = _registered_tool_names(server)
    added: list[str] = []
    skipped: list[str] = []
    for fn in fns:
        name = getattr(fn, "__name__", "")
        if not name:
            continue
        if name in existing:
            skipped.append(name)
            continue
        server.tool()(fn)
        existing.add(name)
        added.append(name)
    logger.info("MCP register %s: added=%d skipped=%d", label, len(added), len(skipped))


# 老生命周期工具保留在统一主入口，避免 AI Chat / 外部 MCP 看不到生成→部署→发布三件套。
_LEGACY_COMPAT_FNS = [
    parse_design_doc,
    list_platform_envs,
    list_apaas_apps_in_env,
    check_app_code_conflict,
    check_model_codes,
    list_apaas_models_in_env,
    save_app_design_doc,
    generate_app_from_doc,
    list_my_applications,
    update_app_from_doc,
    get_change_plan,
    execute_change_plan,
    lookup_user_by_username,
    deploy_application,
    publish_application,
    validate_builder_doc,
    submit_design_doc,
    get_dev_scene_spec,
    get_dev_scene_full_workflow,
    list_apaas_app_models,
    list_apaas_app_dicts,
    list_apaas_app_menus,
    list_apaas_form_components,
    list_apaas_resource_pool_kits,
]

_BUILDER_FNS = [
    # draft 工作流 4 件套
    save_design_draft, get_draft_summary, patch_design_draft,
    promote_draft_to_app, apply_draft_to_live_app, get_doc_template_spec,
    # 应用查询 + 权限
    list_apaas_apps, get_application, get_apaas_app_overview, get_apaas_form_detail,
    list_apaas_dev_kits, grant_app_access, force_regenerate_apaas_app,
    # 应用级发布动作：builder/coding 最终都落到 apaas 发版语义，builder 也需要有一份
    republish_apaas_app,
    # 2026-05-14 砍掉 5 个自开发相关工具：让 builder agent 物理上做不了 dev 任务，
    # 强制走 handoff 到 coding agent，由 coding 的 publish_dev_workspace 内部完成
    # enable + attach + republish 全流程：
    #   - enable_apaas_self_dev_config
    #   - attach_dev_packages_to_apaas_app
    #   - republish_apaas_app
    #   - create_apaas_self_dev_menu
    #   - upload_external_zip_to_apaas
]
_CODING_FNS = [
    # 应用查询（4）：定位应用 + 拿 schema
    list_apaas_apps,                  # ⭐ 从 app_code/URL/名 定位 apaas_app_id
    get_recent_app_context,           # builder 接力 cache prefill
    get_apaas_app_overview,           # 模型 / 字典 / 菜单 全貌
    get_apaas_form_detail,            # 表单字段 uuid → label / componentType
    # 场景 + 方案（2）
    get_dev_scene,                    # list / spec / workflow 三档
    save_dev_spec,                    # 落 spec + 可选 mockup HTML
    # 沙箱（3）
    create_dev_workspace,
    import_zip_to_workspace,
    get_dev_workspace_status,
    # 文件 + 命令（6）
    read_workspace_file,
    write_workspace_files,
    edit_workspace_files,
    glob_workspace,
    grep_workspace,
    run_workspace_command,
    # 打包 / 发布 + 挂字段（3）
    build_dev_workspace,                    # 只打包：不需要 env，不上传、不 attach、不 republish
    publish_dev_workspace,                  # 一条龙：上传 + enable + attach + 可选建菜单 + republish
    attach_dev_component_to_form_field,     # ⭐ 把已发布自定义组件挂到表单字段
    # 2026-05-16：补回高频原子发布动作，避免人工 / agent 退回 legacy full
    enable_apaas_self_dev_config,
    attach_dev_packages_to_apaas_app,
    republish_apaas_app,
    create_apaas_self_dev_menu,
    upload_external_zip_to_apaas,
]

_register_tools_once(mcp, [*_LEGACY_COMPAT_FNS, *_BUILDER_FNS, *_CODING_FNS], "main-unified")
_register_tools_once(mcp_builder, _BUILDER_FNS, "builder-compat")
_register_tools_once(mcp_coding, _CODING_FNS, "coding-compat")
logger.info("MCP split servers registered: builder=%d, coding=%d", len(_BUILDER_FNS), len(_CODING_FNS))


# ─────────────────────────── Phase 3 · Vibe Coding 9 工具 ───────────────────────────
# 文件独立在 backend/app/vibe_coding_mcp.py，import 一次只注册到 mcp_vibe。
# 详见 docs/refactor-mcp-server/04-vibe-coding-mcp-tools-spec.md
try:
    from app import vibe_coding_mcp  # noqa: F401
    logger.info("Vibe Coding MCP tools loaded (+9 tools)")
except Exception as _vc_exc:
    logger.warning("Vibe Coding MCP tools 加载失败: %s", _vc_exc)


try:
    from app.design_mcp import (
        list_design_principles,
        get_design_principle,
        list_design_systems,
        get_design_system,
    )
    _register_tools_once(
        mcp,
        [list_design_principles, get_design_principle, list_design_systems, get_design_system],
        "main-design",
    )
except Exception as _design_exc:
    logger.warning("Open Design tools 注册到主 MCP 失败: %s", _design_exc)


def _log_main_mcp_tools() -> None:
    names = _registered_tool_names(mcp)
    logger.info("Main MCP unified registry ready: count=%d", len(names))


_log_main_mcp_tools()


def _hide_legacy_identity_params(*servers) -> None:
    """Do not expose old caller-provided identity args in MCP tool schemas.

    Runtime functions still keep defaults for backward compatibility if an old
    client sends them, but tools/list must not advertise tenant_id/user_id
    anymore. Identity is resolved from request headers.
    """
    hidden = {"tenant_id", "user_id"}
    for server in servers:
        tool_manager = getattr(server, "_tool_manager", None)
        tools = getattr(tool_manager, "_tools", None)
        if not isinstance(tools, dict):
            continue
        changed = []
        for name, tool in tools.items():
            params = getattr(tool, "parameters", None)
            if not isinstance(params, dict):
                continue
            props = params.get("properties")
            if not isinstance(props, dict):
                continue
            removed = sorted(hidden.intersection(props))
            if not removed:
                continue
            for key in removed:
                props.pop(key, None)
            required = params.get("required")
            if isinstance(required, list):
                params["required"] = [key for key in required if key not in hidden]
            changed.append(f"{name}:{','.join(removed)}")
        if changed:
            logger.info("Hidden legacy MCP identity params on %s: %s", getattr(server, "name", "?"), changed)


_hide_legacy_identity_params(mcp, mcp_builder, mcp_coding, mcp_vibe)

# 注：Open Design 4 工具走**独立 FastMCP 实例**（backend/app/design_mcp.py），
# mount 到独立路径 /api/mcp-design/mcp。零侵入本主 MCP service，
# 现有 dolphin agent 配的工具列表不受影响。详见 main.py mount 段。
