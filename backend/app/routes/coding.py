"""
Coding API 路由 - aPaaS Vibe Coding 接口
"""

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Annotated, AsyncIterator, Any
from urllib.parse import urlencode, urlparse, urlunparse
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Header, Response
from fastapi.responses import StreamingResponse, JSONResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.crypto import decrypt_password
from app.database import get_db
from app.models import User, Conversation, Message, Project, ProjectMember, LLMConfig
from app.deps import get_auth_context, AuthContext
from app.coding.scenes import SceneType, get_scene, get_all_scenes, get_scenes_by_category
from app.coding.generator import CodingGenerator
from app.coding.prompts import AGENT_SYSTEM_PROMPT
from app.coding.workspace import WorkspaceManager, ProjectType
from app.coding.apaas_tools import call_apaas_with_relogin
from app.llm_client import LLMClient
from app.apaas_client import APaaSClient
from app.config import settings
from app.coding.verifier import ComponentVerifier
from app.routes.llm_configs import list_llm_configs_for_purpose
from app.project_access import project_role_at_least, require_project_access
from app.routes.applications.extension import (
    _load_app_and_env,
    _ensure_env_token,
    publish_extension_update,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coding", tags=["coding"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

IDE_EXCLUDED_GLOBS = (
    "**/node_modules",
    "**/dist",
    "**/coverage",
    "**/.git",
    "**/.idea",
    "**/.DS_Store",
    "**/*.zip",
)

CODING_LLM_CONFIG_PREFIX = "llmcfg:"


def _normalize_ide_theme(theme: Optional[str]) -> str:
    return "light" if theme == "light" else "dark"


def _ide_color_theme(theme: Optional[str]) -> str:
    return "Default Light Modern" if _normalize_ide_theme(theme) == "light" else "Default Dark Modern"


def _event_stream_response(
    generator: AsyncIterator[str] | AsyncIterator[dict[str, Any]],
    *,
    ping: int | None = None,
) -> EventSourceResponse:
    """统一 SSE 响应头，尽量避免云上反向代理缓冲流式输出。"""
    kwargs: dict[str, Any] = {"headers": SSE_HEADERS}
    if ping is not None:
        kwargs["ping"] = ping
    return EventSourceResponse(generator, **kwargs)


def _ensure_vibe_workspace_file(ws_path: Path, ide_theme: Optional[str] = None) -> Path:
    """为 Web IDE 生成轻量 workspace，避免直接打开庞大目录造成白屏或卡顿。"""
    workspace_file = ws_path / ".vibe-ide.code-workspace"
    workspace_payload = {
        "folders": [{"path": str(ws_path.resolve())}],
        "settings": {
            "files.exclude": {pattern: True for pattern in IDE_EXCLUDED_GLOBS},
            "search.exclude": {pattern: True for pattern in IDE_EXCLUDED_GLOBS},
            "files.watcherExclude": {pattern: True for pattern in IDE_EXCLUDED_GLOBS},
            "explorer.autoReveal": False,
            "git.autoRepositoryDetection": "openEditors",
            "workbench.colorTheme": _ide_color_theme(ide_theme),
        },
    }
    serialized = json.dumps(workspace_payload, ensure_ascii=False, indent=2)
    if not workspace_file.exists() or workspace_file.read_text(encoding="utf-8") != serialized:
        workspace_file.write_text(serialized, encoding="utf-8")
    return workspace_file


def _ensure_cursor_rules(ws_path: Path):
    """确保工作区包含 .cursor/rules 下的开发规范文件（hash 缓存避免重复 IO）。"""
    rules_dir = ws_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    template_dir = Path(__file__).parent.parent.parent / "templates" / "cursor-rules"
    if template_dir.exists():
        import shutil
        import hashlib
        for rule_file in template_dir.glob("*.mdc"):
            target = rules_dir / rule_file.name
            if not target.exists():
                shutil.copy2(rule_file, target)
            elif target.stat().st_mtime < rule_file.stat().st_mtime:
                # 仅当源文件更新时才比较内容 hash
                src_hash = hashlib.md5(rule_file.read_bytes()).hexdigest()
                tgt_hash = hashlib.md5(target.read_bytes()).hexdigest()
                if src_hash != tgt_hash:
                    shutil.copy2(rule_file, target)

    canonical_rule = rules_dir / "apaas-form-component-dev.mdc"
    duplicate_rule = rules_dir / "form-component-dev-guide.mdc"
    try:
        if canonical_rule.exists() and duplicate_rule.exists():
            duplicate_rule.unlink()
        elif duplicate_rule.exists() and not canonical_rule.exists():
            duplicate_rule.rename(canonical_rule)
    except OSError:
        logger.warning("Failed to reconcile duplicate form-component rule files in %s", rules_dir, exc_info=True)


def _load_workspace_chat_payload(
    ws_id: str,
    *,
    filename: str,
    conversation_id: Optional[int] = None,
) -> dict[str, list[dict[str, Any]]]:
    try:
        ws_path = workspace_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        return {"messages": [], "stream_messages": []}

    history_file = ws_path / ".vscode" / filename
    if not history_file.exists():
        return {"messages": [], "stream_messages": []}

    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
    except Exception:
        return {"messages": [], "stream_messages": []}

    file_conversation_id = data.get("conversation_id")
    if conversation_id and file_conversation_id not in (None, conversation_id):
        return {"messages": [], "stream_messages": []}

    messages = data.get("messages") or []
    if not isinstance(messages, list):
        messages = []

    stream_messages = data.get("stream_messages") or []
    if not isinstance(stream_messages, list):
        stream_messages = []

    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        normalized.append({"role": role, "content": content})

    normalized_stream_messages: list[dict[str, Any]] = []
    for message in stream_messages:
        if not isinstance(message, dict):
            continue
        msg_type = str(message.get("type") or "").strip()
        content = message.get("content")
        if msg_type not in {"user", "thinking", "tool", "file_write", "file_edit", "command", "status", "error"}:
            continue
        if not isinstance(content, str):
            content = ""
        normalized_item: dict[str, Any] = {
            "type": msg_type,
            "content": content,
        }
        for field in ("fileName", "fileContent", "collapsed", "timestamp"):
            if field in message:
                normalized_item[field] = message[field]
        normalized_stream_messages.append(normalized_item)

    return {"messages": normalized, "stream_messages": normalized_stream_messages}


def _write_ruijing_extension_config(
    ws_path: Path,
    ws_id: str,
    ide_token: str,
    api_base: str,
    model: str,
    conversation_id: Optional[int] = None,
):
    """为睿鲸AI VS Code 扩展生成配置文件，替代 URL query params 传递配置。"""
    vscode_dir = ws_path / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    config_file = vscode_dir / "ruijing-ai.json"
    harness_api_base = _derive_harness_api_base(api_base)
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


def _build_public_api_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _browser_origin_from_request(request: Request) -> str:
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin.rstrip("/")

    referer = (request.headers.get("referer") or "").strip()
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    return ""


def _align_local_code_server_base_url(request: Request, base_url: str) -> str:
    """Keep local Builder and code-server on the same browser host.

    Mixing localhost and 127.0.0.1 puts the embedded workbench in a third-party
    context in some browsers, which breaks VS Code Web storage during startup.
    """
    normalized = (base_url or "").rstrip("/")
    if not normalized:
        return ""

    parsed_code_server = urlparse(normalized)
    if not parsed_code_server.scheme or not parsed_code_server.netloc:
        return normalized

    browser_origin = _browser_origin_from_request(request)
    parsed_origin = urlparse(browser_origin)
    local_hosts = {"127.0.0.1", "localhost"}
    code_server_host = (parsed_code_server.hostname or "").strip().lower()
    browser_host = (parsed_origin.hostname or "").strip().lower()

    if code_server_host not in local_hosts or browser_host not in local_hosts:
        return normalized

    port = parsed_code_server.port
    netloc = parsed_origin.hostname or parsed_code_server.hostname or ""
    if port:
        netloc = f"{netloc}:{port}"
    elif parsed_code_server.netloc.endswith(":"):
        netloc = f"{netloc}:"

    return urlunparse(parsed_code_server._replace(netloc=netloc)).rstrip("/")


def _derive_harness_api_base(api_base: str) -> str:
    """把 coding IDE API base 映射成 harness IDE API base。"""
    return (api_base or "").replace("/api/coding/", "/api/harness/coding/")


def _infer_public_builder_prefix(request: Request) -> str:
    forwarded_prefix = (request.headers.get("x-forwarded-prefix") or "").strip()
    if forwarded_prefix:
        return forwarded_prefix.rstrip("/")

    referer = (request.headers.get("referer") or "").strip()
    if referer:
        parsed = urlparse(referer)
        parts = [p for p in (parsed.path or "").split("/") if p]
        if parts and parts[0] not in {"api", "ide"}:
            return f"/{parts[0]}"

    code_server_base = _align_local_code_server_base_url(request, settings.code_server_base_url)
    if not code_server_base:
        return ""

    parsed = urlparse(code_server_base)
    code_server_path = (parsed.path or "").rstrip("/")
    if code_server_path.endswith("/ide"):
        return code_server_path[:-4]
    return ""


def _infer_code_server_base_url(request: Request) -> str:
    configured = _align_local_code_server_base_url(request, settings.code_server_base_url)
    if configured:
        return configured

    public_base = _build_public_api_base(request)
    public_prefix = _infer_public_builder_prefix(request)
    return f"{public_base}{public_prefix}/ide".rstrip("/")


def _build_ide_proxy_api_base(request: Request, ws_id: str) -> str:
    """为 code-server 场景优先生成同源代理地址，避免浏览器被 CSP 拦截直连后端。"""
    public_base = _build_public_api_base(request)
    public_prefix = _infer_public_builder_prefix(request)
    code_server_base = _infer_code_server_base_url(request)

    request_host = (request.url.hostname or "").strip().lower()
    code_server_host = (urlparse(code_server_base).hostname or "").strip().lower()
    local_hosts = {"127.0.0.1", "localhost"}
    backend_port = request.url.port

    if request_host in local_hosts and code_server_host in local_hosts and backend_port:
        return f"{code_server_base}/proxy/{backend_port}/api/coding/workspace/{ws_id}/ide"

    return f"{public_base}{public_prefix}/api/coding/workspace/{ws_id}/ide"


def _create_ide_access_token(ctx: AuthContext, ws_id: str) -> str:
    payload = {
        "sub": str(ctx.user.id),
        "tid": ctx.tenant_id,
        "type": "ide_access",
        "ws": ws_id,
        "exp": datetime.utcnow() + timedelta(hours=8),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _verify_ide_access_token(token: str, ws_id: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="无效或已过期的 IDE 访问令牌")

    if payload.get("type") != "ide_access" or payload.get("ws") != ws_id:
        raise HTTPException(status_code=403, detail="IDE 访问令牌与当前工作区不匹配")

    return payload


def _code_server_chat_images_dir() -> Path:
    return Path.home() / ".local" / "share" / "code-server" / "User" / "workspaceStorage" / "vscode-chat-images"


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    match = re.match(r"^data:([^;]+);base64,(.+)$", data_url, re.DOTALL)
    if not match:
        raise ValueError("invalid data url")
    media_type, encoded = match.groups()
    try:
        return media_type, base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError("invalid base64 image data") from exc


def _image_extension_from_media_type(media_type: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get(media_type.lower(), ".png")


def _is_safe_chat_image_name(name: str) -> bool:
    return bool(re.match(r"^[\w.\- ]+\.(png|jpg|jpeg|webp|gif)$", name or "", re.IGNORECASE))


def _latest_chat_image_path() -> Optional[Path]:
    image_dir = _code_server_chat_images_dir()
    if not image_dir.exists():
        return None
    candidates = [
        path for path in image_dir.iterdir()
        if path.is_file() and re.search(r"\.(png|jpg|jpeg|webp|gif)$", path.name, re.IGNORECASE)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _extract_ocr_signal_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []

    normalized = [re.sub(r"\s+", " ", (line or "")).strip() for line in lines]
    focused_patterns = [
        re.compile(r"(TypeError|ReferenceError|SyntaxError|RangeError|Unhandled|Uncaught)", re.IGNORECASE),
        re.compile(r"(Cannot read properties|Unexpected token|undefined)", re.IGNORECASE),
    ]
    weak_patterns = [
        re.compile(r"\.js:\d+", re.IGNORECASE),
        re.compile(r"(failed|not found|404|500)", re.IGNORECASE),
    ]

    signals: list[str] = []
    seen: set[str] = set()

    def _append_snippet(snippet: str):
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not snippet or len(snippet) < 12:
            return
        key = snippet.lower()
        if key in seen:
            return
        seen.add(key)
        signals.append(snippet[:400])

    for idx, line in enumerate(normalized):
        if not any(pattern.search(line) for pattern in focused_patterns):
            continue
        parts = [part for part in normalized[idx:idx + 4] if part]
        _append_snippet(" ".join(parts))
        if len(signals) >= 6:
            return signals

    for idx, line in enumerate(normalized):
        if not any(pattern.search(line) for pattern in weak_patterns):
            continue
        parts = [part for part in normalized[max(0, idx - 1):idx + 3] if part]
        _append_snippet(" ".join(parts))
        if len(signals) >= 8:
            return signals

    return signals


def _extract_ocr_diagnostics(text: str, signal_lines: list[str]) -> list[str]:
    corpus = re.sub(r"\s+", " ", text or "").strip()
    diagnostics: list[str] = []
    seen: set[str] = set()

    def _add(message: str):
        normalized = re.sub(r"\s+", " ", message).strip()
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        diagnostics.append(normalized)

    compact = corpus.replace(" ", "")
    patterns = [
        (re.compile(r"TypeError[\s:：]*Cannot(?:.{0,60})read(?:.{0,80})properties(?:.{0,40})undefined(?:.{0,80})reading(?:.{0,40})zh-?\s*CN", re.IGNORECASE),
         "TypeError: Cannot read properties of undefined (reading 'zh-CN')"),
        (re.compile(r"SyntaxError\s*[:：]?\s*Unexpected\s+token\s*['\"]?<['\"]?", re.IGNORECASE),
         "SyntaxError: Unexpected token '<'"),
        (re.compile(r"TypeError[\s:：]*Cannot(?:.{0,60})read(?:.{0,80})properties(?:.{0,40})undefined(?:.{0,80})reading(?:.{0,40})default", re.IGNORECASE),
         "TypeError: Cannot read properties of undefined (reading 'default')"),
    ]

    for pattern, message in patterns:
        if pattern.search(corpus) or (
            message.endswith("'zh-CN')") and "typeerror" in compact.lower() and "reading'zh-cn'" in compact.lower()
        ) or (
            message.endswith("'default')") and "typeerror" in compact.lower() and "reading'default'" in compact.lower()
        ):
            _add(message)

    for line in signal_lines:
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean:
            continue
        if re.search(r"(TypeError|ReferenceError|SyntaxError|RangeError|Error|Exception)", clean, re.IGNORECASE):
            _add(clean)
        if len(diagnostics) >= 5:
            break

    return diagnostics[:5]


async def _run_local_image_ocr(image_path: Path) -> dict[str, Any]:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "ocr_image.swift"
    if not script_path.exists():
        raise RuntimeError("OCR script not found")

    process = await asyncio.create_subprocess_exec(
        "swift",
        str(script_path),
        str(image_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="ignore").strip() or "OCR process failed"
        raise RuntimeError(detail)

    try:
        return json.loads(stdout.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Invalid OCR output") from exc


def _build_openai_chat_completions_url() -> str:
    base = settings.llm_api_base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


def _build_chat_completions_url(base_url: str) -> str:
    """Normalize a configured base_url into an OpenAI-compatible chat/completions endpoint."""
    base = (base_url or "").rstrip("/")
    if not base:
        return _build_openai_chat_completions_url()
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/responses"):
        return f"{base[: -len('/responses')]}/chat/completions"
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


def _llm_config_model_id(config: LLMConfig) -> str:
    return f"{CODING_LLM_CONFIG_PREFIX}{config.id}"


def _parse_coding_llm_config_id(model_name: str | None) -> Optional[int]:
    needle = (model_name or "").strip()
    if not needle.startswith(CODING_LLM_CONFIG_PREFIX):
        return None
    try:
        return int(needle[len(CODING_LLM_CONFIG_PREFIX):])
    except ValueError:
        return None


def _serialize_coding_llm_config(config: LLMConfig) -> dict[str, str]:
    return {
        "id": _llm_config_model_id(config),
        "name": f"{config.config_name} ({config.model})",
        "provider": config.provider,
    }


async def _list_tenant_coding_model_configs(db: AsyncSession, tenant_id: int | None) -> list[LLMConfig]:
    if not tenant_id:
        return []
    try:
        return await list_llm_configs_for_purpose(db, tenant_id, "coding")
    except Exception as exc:
        logger.warning("读取租户 coding 模型配置失败 tenant_id=%s: %s", tenant_id, exc)
        return []


async def _resolve_tenant_coding_model_config(
    db: AsyncSession,
    tenant_id: int | None,
    selected_model: str | None,
) -> Optional[LLMConfig]:
    configs = await _list_tenant_coding_model_configs(db, tenant_id)
    if not configs:
        return None

    needle = (selected_model or "").strip()
    if needle:
        if needle.startswith(CODING_LLM_CONFIG_PREFIX):
            try:
                config_id = int(needle[len(CODING_LLM_CONFIG_PREFIX):])
            except ValueError:
                config_id = None
            if config_id is not None:
                for config in configs:
                    if config.id == config_id:
                        return config

        needle_lower = needle.lower()
        for config in configs:
            if (
                needle_lower == _llm_config_model_id(config).lower()
                or needle_lower == (config.model or "").lower()
                or needle_lower == (config.config_name or "").lower()
            ):
                return config

        for config in configs:
            haystacks = [
                (config.model or "").lower(),
                (config.config_name or "").lower(),
                f"{config.config_name} ({config.model})".lower(),
            ]
            if any(needle_lower in haystack for haystack in haystacks if haystack):
                return config

    return next((config for config in configs if config.is_default), configs[0])


async def _get_default_coding_model_id(db: AsyncSession, tenant_id: int | None) -> str:
    config = await _resolve_tenant_coding_model_config(db, tenant_id, None)
    if config:
        return _llm_config_model_id(config)
    # 不再兜底到内置 minimax(settings.llm_model):没配模型就返回空,
    # 下游 load_coding_llm_config 解析不到会抛 NoLLMConfigError,提示去平台管理添加。
    return ""


async def _resolve_effective_coding_model(
    db: AsyncSession,
    tenant_id: int | None,
    *,
    requested_model: str | None = None,
    selected_llm_config_id: int | None = None,
) -> tuple[str, Optional[int]]:
    if requested_model:
        requested_config = await _resolve_tenant_coding_model_config(db, tenant_id, requested_model)
        if requested_config:
            return _llm_config_model_id(requested_config), requested_config.id
        return requested_model.strip(), None

    if selected_llm_config_id:
        selected_model = f"{CODING_LLM_CONFIG_PREFIX}{selected_llm_config_id}"
        selected_config = await _resolve_tenant_coding_model_config(db, tenant_id, selected_model)
        if selected_config:
            return _llm_config_model_id(selected_config), selected_config.id

    default_model = await _get_default_coding_model_id(db, tenant_id)
    return default_model, _parse_coding_llm_config_id(default_model)


# IDE Coding 模型路由表
_CODING_MODEL_ROUTES: dict = {}


def _init_coding_model_routes():
    """从 settings 构建模型路由表（启动时调用一次）"""
    global _CODING_MODEL_ROUTES
    routes = {}

    # 默认模型（MiniMax）
    routes["default"] = {
        "url": _build_openai_chat_completions_url(),
        "api_key": settings.llm_api_key,
    }

    # DeepSeek
    if settings.coding_model_deepseek_base_url and settings.coding_model_deepseek_api_key:
        base = settings.coding_model_deepseek_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["deepseek"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_deepseek_api_key,
            "model": settings.coding_model_deepseek_model,
        }

    # Qwen
    if settings.coding_model_qwen_base_url and settings.coding_model_qwen_api_key:
        base = settings.coding_model_qwen_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["qwen"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_qwen_api_key,
            "model": settings.coding_model_qwen_model,
        }

    # GPT-5.3-Codex (via jiekou.ai, /responses endpoint)
    if settings.coding_model_codex_base_url and settings.coding_model_codex_api_key:
        base = settings.coding_model_codex_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["codex"] = {
            "url": f"{base}/chat/completions",  # 会在代理中被转换为 /responses
            "api_key": settings.coding_model_codex_api_key,
            "model": settings.coding_model_codex_model,
        }

    # GPT-5.4 (via jiekou.ai)
    if settings.coding_model_gpt54_base_url and settings.coding_model_gpt54_api_key:
        base = settings.coding_model_gpt54_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["gpt"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_gpt54_api_key,
            "model": settings.coding_model_gpt54_model,
        }

    # Claude Sonnet 4.6 (via jiekou.ai)
    if settings.coding_model_sonnet_base_url and settings.coding_model_sonnet_api_key:
        base = settings.coding_model_sonnet_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["sonnet"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_sonnet_api_key,
            "model": settings.coding_model_sonnet_model,
        }

    # Claude Opus 4.6 (via jiekou.ai)
    if settings.coding_model_opus_base_url and settings.coding_model_opus_api_key:
        base = settings.coding_model_opus_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["opus"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_opus_api_key,
            "model": settings.coding_model_opus_model,
        }

    _CODING_MODEL_ROUTES = routes


def _resolve_coding_model(model_name: str) -> tuple:
    """根据前端传入的 model 名称，返回 (upstream_url, api_key)"""
    if not _CODING_MODEL_ROUTES:
        _init_coding_model_routes()

    model_lower = (model_name or "").lower()

    # 按关键词匹配模型路由
    for key, route in _CODING_MODEL_ROUTES.items():
        if key != "default" and key in model_lower:
            return route["url"], route["api_key"]

    # 默认走 MiniMax
    default = _CODING_MODEL_ROUTES.get("default", {})
    return default.get("url", _build_openai_chat_completions_url()), default.get("api_key", settings.llm_api_key)


async def _codex_responses_proxy(
    upstream_url: str, headers: dict, payload: dict, api_key: str, stream: bool
) -> Response:
    """Codex 模型适配：chat/completions → /responses 格式转换

    前端发 chat/completions 格式，后端转成 /responses 格式调用 Codex，
    再把响应转回 chat/completions 格式返回给前端。
    """
    # 1. 构建 /responses 请求 URL
    responses_url = upstream_url.replace("/chat/completions", "/responses")

    # 2. 把 messages 转成 /responses 的 input 格式
    messages = payload.get("messages", [])
    # 合并所有消息为一个 input 字符串（Codex /responses 用 input 字段）
    input_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            input_parts.append(f"[System]: {content}")
        elif role == "user":
            input_parts.append(content)
        elif role == "assistant":
            input_parts.append(f"[Assistant]: {content}")
    input_text = "\n\n".join(input_parts)

    codex_payload = {
        "model": payload.get("model", "gpt-5.3-codex"),
        "input": input_text,
    }

    # 3. 调用 /responses 端点（Codex 不支持流式）
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            resp = await client.post(
                responses_url, headers=headers, json=codex_payload
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"调用 Codex 失败: {exc}")

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])

    # 4. 把 /responses 响应转成 chat/completions 格式
    data = resp.json()
    content = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                content += c.get("text", "")

    usage = data.get("usage", {})
    openai_response = {
        "id": data.get("id", ""),
        "object": "chat.completion",
        "model": data.get("model", payload.get("model")),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
        },
    }

    # 如果前端要求流式，模拟一个 SSE 流（Codex 不支持真流式）
    if stream:
        import json as _json

        async def _fake_stream():
            chunk = {
                "id": openai_response["id"],
                "object": "chat.completion.chunk",
                "model": openai_response["model"],
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": "stop"}],
            }
            yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(_fake_stream(), media_type="text/event-stream")

    return JSONResponse(content=openai_response)


# ============================================================
# 请求/响应模型
# ============================================================

class CreateWorkspaceRequest(BaseModel):
    """创建工作区请求"""
    project_type: str   # form-component, form-page, form-list, backend-api
    project_name: str   # 项目名称
    display_name: Optional[str] = None  # 展示名称
    project_id: Optional[int] = None  # 关联项目ID


class WriteFileRequest(BaseModel):
    """写入文件请求"""
    file_path: str
    content: str


class IDEFileEdit(BaseModel):
    """Web IDE 内 Chat 应用文件修改。"""
    path: str
    content: Optional[str] = None
    action: Optional[str] = "write"


class IDEApplyEditsRequest(BaseModel):
    edits: list[IDEFileEdit]


class AutoPipelineRequest(BaseModel):
    """自动化 Pipeline 请求（对话式开发）"""
    message: str                           # 用户需求描述
    workspace_id: Optional[str] = None     # 已有工作区（迭代修改）
    conversation_id: Optional[int] = None  # 已有对话
    selected_model: Optional[str] = None   # 当前会话选中的 coding 模型（llmcfg:<id>）
    app_id: Optional[str] = None           # aPaaS 应用ID (deprecated, use project_id)
    project_id: Optional[int] = None       # 关联项目ID（优先使用项目的平台配置）


# ============================================================
# 场景相关接口
# ============================================================

@router.get("/scenes")
async def list_scenes(category: Optional[str] = None):
    """获取所有支持的开发场景"""
    if category:
        scenes = get_scenes_by_category(category)
    else:
        scenes = get_all_scenes()
    return [
        {
            "type": s.type.value,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "platform": s.platform,
        }
        for s in scenes
    ]


# ============================================================
# 对话相关接口
# ============================================================

@router.get("/conversations")
async def list_coding_conversations(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取Coding类型的对话列表"""
    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "coding",
        )
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "workspace_id": c.workspace_id,
            "selected_llm_config_id": c.selected_llm_config_id,
            "coding_app_id": c.coding_app_id,  # 绑定应用,前端据此恢复「在应用上定制」绑定
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_coding_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除一个 coding 会话(含消息)。若有关联工作区,best-effort 一并清理。

    架构语义: 会话是主单位,workspace 随会话删。Conversation.workspace_id 单值 1:1,
    不存在多会话共享同一 workspace 的情况。工作区目录已不存在(孤儿会话)等情况
    **不报错** —— 保证孤儿会话也能删掉,修掉「点 × 没反应、删不掉」的逻辑缺口。
    """
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == ctx.user.id,
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.agent_type == "coding",
            )
        )
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    ws_id = conv.workspace_id
    if ws_id:
        try:
            await workspace_mgr.delete_workspace(ws_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[delete_conversation] 清理工作区 %s 失败(忽略,继续删会话): %s", ws_id, exc)

    await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await db.delete(conv)
    await db.commit()
    return {"status": "ok"}


@router.get("/conversations/{conversation_id}/messages")
async def get_coding_messages(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取Coding对话的消息列表"""
    # 验证对话属于当前用户
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == ctx.user.id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


# ============================================================
# 工作区相关接口
# ============================================================

workspace_mgr = WorkspaceManager()


def _workspace_permissions(access_role: str) -> dict[str, bool]:
    return {
        "edit": project_role_at_least(access_role, "member"),
        "delete": project_role_at_least(access_role, "admin"),
        "publish": project_role_at_least(access_role, "admin"),
        "upload_to_platform": project_role_at_least(access_role, "admin"),
    }


def _decorate_workspace_access(meta: dict[str, Any], access_role: str) -> dict[str, Any]:
    return {
        **meta,
        "access_role": access_role,
        "permissions": _workspace_permissions(access_role),
    }


async def _ensure_workspace_access(
    ws_id: str,
    ctx: AuthContext,
    db: AsyncSession,
    *,
    minimum_project_role: str = "member",
) -> dict[str, Any]:
    try:
        meta = workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")

    project_id = meta.get("project_id")
    if project_id:
        access = await require_project_access(
            db,
            project_id=int(project_id),
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role=minimum_project_role,
        )
        return _decorate_workspace_access(meta, access.role)

    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该工作区")

    return _decorate_workspace_access(meta, "owner")


@router.post("/workspace/create")
async def create_workspace(
    req: CreateWorkspaceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建新工作区（脚手架初始化）"""
    try:
        project_type = ProjectType(req.project_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的项目类型: {req.project_type}，可选: {[t.value for t in ProjectType]}"
        )

    access_role = "owner"
    if req.project_id:
        project_access = await require_project_access(
            db,
            project_id=req.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )
        access_role = project_access.role

    meta = workspace_mgr.create_workspace(
        project_type=project_type,
        project_name=req.project_name,
        display_name=req.display_name,
        user_id=ctx.user.id,
        project_id=req.project_id,
        tenant_id=ctx.tenant_id,
    )
    meta["files"] = workspace_mgr.list_files(meta["id"])
    return _decorate_workspace_access(meta, access_role)


# 2026-05-19 image #25: 允许上传已有的自开发包 zip 进行二次调整。
# 流程：先用 workspace_mgr 创建一个空 ws（拿到 id + dir + meta），
# 然后清空脚手架内容，把 zip 解压到 ws 根目录，重写 .workspace.json
# 保留 meta 字段（id/user_id/tenant_id/project_id 等）。
@router.post("/workspace/import-zip")
async def import_zip_to_workspace_endpoint(
    file: UploadFile = File(...),
    project_type: Optional[str] = Query(None, description="可选：手动指定 form-component-dual / form-page / form-list 等；不传则从 package.json 自动检测"),
    project_id: Optional[int] = Query(None),
    display_name: Optional[str] = Query(None, description="工作区展示名，默认取 zip 内 package.json.name"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """上传已有的自开发包 zip，解压成新的 coding workspace 供 AI 二次调整。

    入参：
      file          multipart 文件（必须是 .zip）
      project_type  可选，未传时从 zip 内 package.json + 目录结构自动检测
      project_id    可选，关联到某个 project
      display_name  可选，工作区展示名

    返回：workspace meta + files
    """
    import io
    import json as _json
    import shutil
    import zipfile

    # 1. 读取 + 校验 zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "只接受 .zip 文件")
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(400, f"zip 太大 ({len(raw)} bytes > 30MB)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
        names = zf.namelist()
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是合法的 zip 文件")
    if not names:
        raise HTTPException(400, "zip 内为空")

    # 2. 检测 zip 内 single-root prefix（如 form-component-upload-src/）+ 检测 project_type
    def _strip_common_prefix(paths: list[str]) -> str:
        roots = {p.split("/", 1)[0] for p in paths if "/" in p}
        single_root = next(iter(roots)) if len(roots) == 1 and all(p.startswith(next(iter(roots)) + "/") or p == next(iter(roots)) for p in paths) else ""
        return single_root + "/" if single_root else ""

    strip_prefix = _strip_common_prefix(names)

    # 找 package.json 用于自动检测 project_type + name
    pkg_json: dict = {}
    for n in names:
        rel = n[len(strip_prefix):] if strip_prefix and n.startswith(strip_prefix) else n
        if rel == "package.json":
            try:
                pkg_json = _json.loads(zf.read(n).decode("utf-8"))
            except Exception:
                pkg_json = {}
            break

    detected_type = project_type or ""
    if not detected_type:
        # 用 package.json 的 apaas.scene 或 name prefix 判断
        apaas_meta = pkg_json.get("apaas") or {}
        if isinstance(apaas_meta, dict):
            scene = (apaas_meta.get("scene") or apaas_meta.get("type") or "").lower()
            if scene:
                detected_type = scene
        # fallback：根据目录命名/文件存在判断
        if not detected_type:
            joined = " ".join(names).lower()
            if "form-component" in joined or "widget.config.json" in joined:
                detected_type = "form-component-dual"
            elif "form-page-local" in joined or "form-page" in joined:
                detected_type = "form-page"
            elif "form-list" in joined or "form-view" in joined:
                detected_type = "form-list"
            else:
                detected_type = "form-component-dual"  # 兜底

    try:
        pt = ProjectType(detected_type)
    except ValueError:
        raise HTTPException(400, f"无法识别 project_type={detected_type!r}，请显式指定")

    pkg_name = (pkg_json.get("name") or "").strip()
    inferred_name = pkg_name or strip_prefix.rstrip("/") or f"imported-{pt.value}"
    final_display = display_name or pkg_name or inferred_name

    # 3. 复用 workspace_mgr 创建空壳（拿到 id + dir + meta；不要 access check 是空 zip 时不会 leak）
    if project_id:
        await require_project_access(
            db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id, minimum_role="member",
        )

    meta = workspace_mgr.create_workspace(
        project_type=pt, project_name=inferred_name, display_name=final_display,
        user_id=ctx.user.id, project_id=project_id, tenant_id=ctx.tenant_id,
    )
    ws_id = meta["id"]
    ws_path = workspace_mgr.get_workspace_path(ws_id)

    # 4. 删脚手架内容（保留 .workspace.json），解压 zip
    ws_meta_path = ws_path / ".workspace.json"
    saved_meta = ws_meta_path.read_text(encoding="utf-8") if ws_meta_path.exists() else None
    for child in ws_path.iterdir():
        if child.name == ".workspace.json":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except FileNotFoundError:
                pass

    extracted_count = 0
    for member in zf.infolist():
        if member.is_dir():
            continue
        rel = member.filename[len(strip_prefix):] if strip_prefix and member.filename.startswith(strip_prefix) else member.filename
        if not rel or rel.startswith(("..", "/")) or ".." in rel.split("/"):
            continue
        target = ws_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        extracted_count += 1

    # 重写 meta（status: ready, imported=True）
    if saved_meta:
        try:
            meta_dict = _json.loads(saved_meta)
            meta_dict["status"] = "ready"
            meta_dict["imported_from_zip"] = file.filename
            ws_meta_path.write_text(_json.dumps(meta_dict, ensure_ascii=False, indent=2))
        except Exception:
            pass

    meta = workspace_mgr.get_workspace_info(ws_id)
    meta["imported_file_count"] = extracted_count
    return _decorate_workspace_access(meta, "owner")


@router.post("/workspace/{ws_id}/install")
async def install_workspace_deps(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """安装工作区依赖（npm install）"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        result = await workspace_mgr.install_deps(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.post("/workspace/{ws_id}/build")
async def build_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """构建工作区项目"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        result = await workspace_mgr.build_project(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/download")
async def download_workspace_zip(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    type: str = Query(default="dist", description="下载类型: dist=构建产物, src=源代码"),
):
    """下载工作区打包文件（zip）"""
    import zipfile
    import io
    from fastapi.responses import StreamingResponse

    info = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")

    ws_path = workspace_mgr.get_workspace_path(ws_id)
    project_name = info.get("project_name", ws_id)

    if type == "dist":
        # 下载构建产物
        output_path = workspace_mgr.get_build_output_dir(ws_id)
        if not workspace_mgr._has_build_artifacts(output_path):
            raise HTTPException(status_code=400, detail="请先构建项目")
        target_path = output_path
        zip_name = f"{project_name}.zip"
    else:
        # 下载源代码（排除 node_modules 和 dist）
        target_path = ws_path
        zip_name = f"{project_name}-src.zip"

    # 创建 zip
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in target_path.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(target_path)
                rel_str = str(rel)
                # 排除 node_modules、dist（源码模式）、.DS_Store 等
                if any(part in rel_str for part in ['node_modules', '.DS_Store']):
                    continue
                if type == "src" and rel_str.startswith("dist"):
                    continue
                zf.write(file_path, rel)

        # dist 模式下，额外加入 apaas.json 和 static 目录（平台需要它们来识别组件）
        if type == "dist":
            apaas_json = ws_path / "src" / "apaas.json"
            if apaas_json.exists() and not (target_path / "apaas.json").exists():
                zf.write(apaas_json, "apaas.json")

            # 加入 static/custom/组件名/ 目录（平台需要此目录结构）
            # 从 apaas.json 的 copyAssets 读取，或用 project_name 兜底
            import json as _json
            try:
                apaas_cfg = _json.loads(apaas_json.read_text())
                copy_assets = apaas_cfg.get("copyAssets", [])
            except Exception:
                copy_assets = []

            # 创建 static 目录占位（空目录需要加一个 entry）
            if copy_assets:
                for asset_path in copy_assets:
                    # public/form-component/xxx -> static/form-component/xxx/
                    static_dir = asset_path.replace("public/", "static/", 1)
                    zf.writestr(f"{static_dir}/", "")
            else:
                zf.writestr(f"static/custom/{project_name}/", "")

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'}
    )


@router.get("/workspace/{ws_id}")
async def get_workspace_info(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取工作区信息"""
    return await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")


@router.get("/workspace/{ws_id}/ide-url")
async def get_workspace_ide_url(
    ws_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    conversation_id: Optional[int] = Query(default=None, description="可选，会话ID，用于把上下文带入 Vibe IDE"),
    theme: Optional[str] = Query(default=None, description="light/dark，用于同步 aPaaS Builder 与 Web IDE 主题"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """获取工作区的 Web IDE (code-server) URL"""
    base_url = _infer_code_server_base_url(request)
    workspace_meta = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")

    effective_conversation_id = conversation_id
    effective_conversation: Optional[Conversation] = None
    if db is not None:
        is_project_workspace = bool(workspace_meta.get("project_id"))
        if effective_conversation_id is None:
            conditions = [
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.workspace_id == ws_id,
                Conversation.agent_type == "coding",
            ]
            if not is_project_workspace:
                conditions.append(Conversation.user_id == ctx.user.id)
            stmt = select(Conversation).where(*conditions).order_by(Conversation.updated_at.desc()).limit(1)
        else:
            conditions = [
                Conversation.id == effective_conversation_id,
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.workspace_id == ws_id,
                Conversation.agent_type == "coding",
            ]
            if not is_project_workspace:
                conditions.append(Conversation.user_id == ctx.user.id)
            stmt = select(Conversation).where(*conditions).limit(1)
        result = await db.execute(stmt)
        effective_conversation = result.scalar_one_or_none()
        if effective_conversation:
            effective_conversation_id = effective_conversation.id
        else:
            effective_conversation_id = None

    normalized_theme = _normalize_ide_theme(theme)
    _ensure_vibe_workspace_file(ws_path, normalized_theme)  # 仍然生成 workspace 文件（保留 exclude 配置）
    _ensure_cursor_rules(ws_path)  # 复制 .cursor/rules 开发规范到工作区
    ide_token = _create_ide_access_token(ctx, ws_id)
    api_base = _build_ide_proxy_api_base(request, ws_id)
    harness_api_base = _derive_harness_api_base(api_base)
    ide_model = settings.llm_model
    if db is not None:
        ide_model, _ = await _resolve_effective_coding_model(
            db,
            ctx.tenant_id,
            selected_llm_config_id=effective_conversation.selected_llm_config_id if effective_conversation else None,
        )

    # 为睿鲸AI VS Code 扩展写入配置文件
    _write_ruijing_extension_config(
        ws_path,
        ws_id,
        ide_token,
        api_base,
        ide_model,
        conversation_id=conversation_id,
    )

    query_params = {
        "folder": str(ws_path.resolve()),  # 用 folder 替代 workspace，更可靠地打开目录
        "vibe_workspace_id": ws_id,
        "vibe_api_base": api_base,
        "vibe_harness_api_base": harness_api_base,
        "vibe_ide_token": ide_token,
        "vibe_model": ide_model,
        "vibe_ui_theme": normalized_theme,
    }
    if effective_conversation_id and db is not None:
        history = await _get_conversation_history(db, effective_conversation_id)
        ide_context = _build_ide_conversation_context(history)
        query_params["vibe_conversation_id"] = str(effective_conversation_id)
        if ide_context:
            query_params["vibe_context"] = ide_context

    base_url = base_url.rstrip("/")
    ide_url = f"{base_url}/?{urlencode(query_params)}"
    return {"ide_url": ide_url}


class IDEImageOCRItem(BaseModel):
    name: Optional[str] = None
    data_url: Optional[str] = None


class IDEImageOCRRequest(BaseModel):
    images: list[IDEImageOCRItem] = []


class IDEPipelineRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    selected_model: Optional[str] = None
    project_id: Optional[int] = None


@router.get("/models")
async def ide_available_models_simple():
    """返回可用的 Coding 模型列表（无需 workspace 认证，供 Chat 面板模型选择器使用）"""
    if not _CODING_MODEL_ROUTES:
        _init_coding_model_routes()
    models = []
    for key, route in _CODING_MODEL_ROUTES.items():
        if key == "default":
            models.append({"id": settings.llm_model, "name": f"MiniMax ({settings.llm_model})", "provider": "minimax"})
        else:
            models.append({"id": route.get("model", key), "name": f"{key.title()} ({route.get('model', key)})", "provider": key})
    return {"models": models}


@router.get("/workspace/{ws_id}/ide/models")
async def ide_available_models(
    ws_id: str,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """返回可用的 Coding 模型列表（不暴露 API Key）"""
    ide_token = x_vibe_ide_token or token
    token_payload: dict[str, Any] = {}
    if ide_token:
        token_payload = _verify_ide_access_token(ide_token, ws_id)

    tenant_id = token_payload.get("tid")
    if db is not None and tenant_id:
        tenant_configs = await _list_tenant_coding_model_configs(db, int(tenant_id))
        if tenant_configs:
            return {"models": [_serialize_coding_llm_config(config) for config in tenant_configs]}

    if not _CODING_MODEL_ROUTES:
        _init_coding_model_routes()

    models = []
    for key, route in _CODING_MODEL_ROUTES.items():
        if key == "default":
            models.append({"id": settings.llm_model, "name": f"MiniMax ({settings.llm_model})", "provider": "minimax"})
        else:
            models.append({"id": route.get("model", key), "name": f"{key.title()} ({route.get('model', key)})", "provider": key})
    return {"models": models}


@router.get("/workspace/{ws_id}/ide/symbols")
async def ide_symbol_search(
    ws_id: str,
    q: str = Query(default="", description="Symbol name to search for"),
    limit: int = Query(default=20, ge=1, le=100),
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
):
    """搜索工作区代码符号（函数、类、组件定义）。"""
    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌")
    _verify_ide_access_token(ide_token, ws_id)

    if not q.strip():
        return {"symbols": []}

    from app.coding.indexer import SymbolIndexer

    try:
        ws_path = workspace_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workspace {ws_id} not found")

    indexer = SymbolIndexer.get_or_create(ws_id, ws_path)
    matches = indexer.query(q.strip(), limit=limit)
    return {"symbols": [s.to_dict() for s in matches]}


def _resolve_ide_edit_path(root: Path, file_path: str) -> tuple[str, Path]:
    clean_path = (file_path or "").strip().replace("\\", "/").lstrip("/")
    if not clean_path or ".." in Path(clean_path).parts:
        raise ValueError("Invalid target path")

    root_resolved = root.resolve()
    target = (root_resolved / clean_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Invalid target path") from exc
    return clean_path, target


def _apply_ide_edits_to_path(root: Path, edits: list[IDEFileEdit]) -> dict[str, list[dict[str, str]]]:
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for edit in edits[:12]:
        try:
            rel_path, target = _resolve_ide_edit_path(root, edit.path)
        except ValueError as exc:
            skipped.append({"path": edit.path or "(empty)", "reason": str(exc)})
            continue

        action = (edit.action or "write").strip().lower()
        try:
            if action == "delete":
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                applied.append({"path": rel_path, "action": "delete"})
                continue

            if not isinstance(edit.content, str):
                skipped.append({"path": rel_path, "reason": "Missing full file content"})
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content, encoding="utf-8")
            applied.append({"path": rel_path, "action": "create" if action == "create" else "write"})
        except OSError as exc:
            skipped.append({"path": rel_path, "reason": str(exc)})

    return {"applied": applied, "skipped": skipped}


@router.post("/workspace/{ws_id}/ide/apply-edits")
async def ide_apply_file_edits(
    ws_id: str,
    req: IDEApplyEditsRequest,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
):
    """让 Web IDE Chat 通过后端安全写入文件，避免依赖 code-server 压缩后的内部变量名。"""
    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")
    token_payload = _verify_ide_access_token(ide_token, ws_id)

    try:
        workspace_path = workspace_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return _apply_ide_edits_to_path(workspace_path, req.edits)


@router.post("/workspace/{ws_id}/ide/pipeline")
async def ide_coding_pipeline(
    ws_id: str,
    req: IDEPipelineRequest,
    request: Request,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """IDE 内聊天统一走 Coding Pipeline，而不是直接调 chat/completions。"""
    from app.coding.pipeline import PipelineParams, run_coding_pipeline

    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")

    token_payload = _verify_ide_access_token(ide_token, ws_id)
    try:
        user_id = int(token_payload.get("sub"))
        tenant_id = int(token_payload.get("tid"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="无效的 IDE 访问令牌")

    api_base = _build_ide_proxy_api_base(request, ws_id)
    api_base_pattern = api_base.replace(ws_id, "{ws_id}") if ws_id in api_base else api_base

    params = PipelineParams(
        message=req.message,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=ws_id,
        conversation_id=req.conversation_id,
        selected_model=req.selected_model,
        project_id=req.project_id,
        code_server_base_url=settings.code_server_base_url or "",
        api_base_builder=api_base_pattern,
        ide_token=ide_token,
    )

    async def pipeline_events():
        async for event in run_coding_pipeline(params, db):
            yield _sse(event)

    return _event_stream_response(pipeline_events(), ping=15)


@router.post("/workspace/{ws_id}/ide/chat/completions")
async def ide_chat_completions_proxy(
    ws_id: str,
    request: Request,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """Web IDE Chat 代理：由后端持有真实 LLM API key，浏览器只持有短时 IDE token。"""
    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")

    token_payload = _verify_ide_access_token(ide_token, ws_id)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的请求体")

    tenant_config = None
    if db is not None:
        tenant_config = await _resolve_tenant_coding_model_config(
            db,
            token_payload.get("tid"),
            payload.get("model", ""),
        )
        if tenant_config and "gpt-5.5" in (tenant_config.model or "").lower():
            fallback_config = await _resolve_tenant_coding_model_config(
                db,
                token_payload.get("tid"),
                "gpt-5.4",
            )
            if fallback_config and fallback_config.id != tenant_config.id:
                logger.warning(
                    "IDE model %s is not available in current gateway, fallback to %s",
                    tenant_config.model,
                    fallback_config.model,
                )
                tenant_config = fallback_config

    if tenant_config:
        payload["model"] = tenant_config.model
        upstream_url = _build_chat_completions_url(tenant_config.base_url)
        api_key = decrypt_password(tenant_config.api_key_enc)
    else:
        if "gpt-5.5" in (payload.get("model") or "").lower():
            payload["model"] = settings.coding_model_gpt54_model or "gpt-5.4"
        upstream_url, api_key = _resolve_coding_model(payload.get("model", ""))
    upstream_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    stream = bool(payload.get("stream"))

    # 清理不兼容参数：tool_choice 在没有 tools 时部分模型会报错
    if "tool_choice" in payload and "tools" not in payload:
        payload.pop("tool_choice", None)

    # Codex 模型走 /responses 端点（非 chat/completions），需要格式转换
    model_name = (payload.get("model") or "").lower()
    if "codex" in model_name and "chat/completions" in upstream_url:
        return await _codex_responses_proxy(upstream_url, upstream_headers, payload, api_key, stream)

    if stream:
        async def _stream() -> AsyncIterator[bytes]:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
                async with client.stream(
                    "POST",
                    upstream_url,
                    headers=upstream_headers,
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="ignore") or f"LLM API {resp.status_code}"
                        raise HTTPException(status_code=resp.status_code, detail=detail)
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform"},
        )

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(
                upstream_url,
                headers=upstream_headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"调用 LLM 失败: {exc}")

    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    return JSONResponse(status_code=resp.status_code, content={"detail": resp.text})


@router.post("/workspace/{ws_id}/ide/completions")
async def ide_inline_completions(
    ws_id: str,
    request: Request,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """行内代码补全端点：接收 prefix/suffix，返回补全建议。"""
    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌")
    token_payload = _verify_ide_access_token(ide_token, ws_id)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的请求体")

    prefix = payload.get("prefix", "")
    suffix = payload.get("suffix", "")
    language = payload.get("language", "")
    file_path = payload.get("file_path", "")
    max_tokens = min(payload.get("max_tokens", 256), 512)
    apaas_context = payload.get("apaas_context", "")

    if not prefix.strip():
        return JSONResponse(content={"completions": []})

    # Resolve model — prefer fast models for completion
    request_model = payload.get("model", "")
    tenant_config = None
    if db is not None:
        tenant_config = await _resolve_tenant_coding_model_config(
            db, token_payload.get("tid"), request_model,
        )

    if tenant_config:
        upstream_url = _build_chat_completions_url(tenant_config.base_url)
        api_key = decrypt_password(tenant_config.api_key_enc)
        model_name = tenant_config.model
    else:
        # Prefer DeepSeek/Qwen for low-latency completions
        fast_model = request_model
        if not fast_model:
            for candidate in ["deepseek", "qwen"]:
                if candidate in _CODING_MODEL_ROUTES:
                    route = _CODING_MODEL_ROUTES[candidate]
                    fast_model = route.get("model", "")
                    break
        upstream_url, api_key = _resolve_coding_model(fast_model or "")
        model_name = fast_model or _CODING_MODEL_ROUTES.get("default", {}).get("model", "MiniMax-M2.7")

    # Build FIM-style or standard completion prompt
    system_msg = f"You are a code completion assistant for {language} files on aPaaS low-code platform. " \
                 f"Complete the code at the cursor position. Output ONLY the completion text, nothing else. " \
                 f"Do not repeat existing code. Do not add explanations or markdown."
    if apaas_context:
        system_msg += f"\n\n{apaas_context}"

    user_msg = f"File: {file_path}\nLanguage: {language}\n\n" \
               f"Code before cursor:\n```\n{prefix[-3000:]}\n```\n\n"
    if suffix.strip():
        user_msg += f"Code after cursor:\n```\n{suffix[:1000]}\n```\n\n"
    user_msg += "Complete the code at the cursor position:"

    llm_payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": False,
    }
    # Clean incompatible params
    if "tool_choice" in llm_payload:
        llm_payload.pop("tool_choice", None)

    upstream_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(upstream_url, headers=upstream_headers, json=llm_payload)
    except (httpx.HTTPError, Exception) as exc:
        logger.warning(f"Inline completion LLM error: {exc}")
        return JSONResponse(content={"completions": []})

    if resp.status_code != 200:
        return JSONResponse(content={"completions": []})

    try:
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Strip markdown code fences if model wrapped it
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        completions = [{"text": content}] if content.strip() else []
        return JSONResponse(content={"completions": completions})
    except Exception:
        return JSONResponse(content={"completions": []})


@router.post("/workspace/{ws_id}/ide/image-context")
async def ide_image_context_proxy(
    ws_id: str,
    req: IDEImageOCRRequest,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
):
    """Web IDE 图片上下文代理：对粘贴到 Chat 的图片做本地 OCR，返回可注入给模型的文字上下文。"""
    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")

    _verify_ide_access_token(ide_token, ws_id)

    if not req.images:
        raise HTTPException(status_code=400, detail="缺少图片输入")

    results: list[dict[str, Any]] = []
    chat_images_dir = _code_server_chat_images_dir()

    for image in req.images[:4]:
        source_name = (image.name or "").strip()
        temp_path: Optional[Path] = None
        try:
            if image.data_url:
                media_type, raw = _decode_data_url(image.data_url)
                suffix = _image_extension_from_media_type(media_type)
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
                    fh.write(raw)
                    temp_path = Path(fh.name)
                image_path = temp_path
            else:
                if source_name == "__latest__":
                    latest = _latest_chat_image_path()
                    if not latest or not latest.exists():
                        results.append({
                            "name": "latest-chat-image",
                            "text": "",
                            "lines": [],
                            "error": "no recent chat image found",
                        })
                        continue
                    image_path = latest
                    source_name = latest.name
                else:
                    if not source_name or not _is_safe_chat_image_name(source_name):
                        results.append({
                            "name": source_name or "unknown",
                            "text": "",
                            "lines": [],
                            "error": "invalid image name",
                        })
                        continue
                    image_path = chat_images_dir / Path(source_name).name
                    if not image_path.exists():
                        results.append({
                            "name": source_name,
                            "text": "",
                            "lines": [],
                            "error": "image not found in code-server storage",
                        })
                        continue

            ocr = await _run_local_image_ocr(image_path)
            lines = [line for line in (ocr.get("lines") or []) if isinstance(line, str)]
            text = ocr.get("text") if isinstance(ocr.get("text"), str) else "\n".join(lines)
            signal_lines = _extract_ocr_signal_lines(lines)
            diagnostics = _extract_ocr_diagnostics(text, signal_lines)
            results.append({
                "name": source_name or image_path.name,
                "text": text[:8000],
                "lines": lines[:120],
                "line_count": len(lines),
                "signal_lines": signal_lines,
                "diagnostics": diagnostics,
                "source": "local_ocr",
            })
        except asyncio.TimeoutError:
            results.append({
                "name": source_name or (temp_path.name if temp_path else "unknown"),
                "text": "",
                "lines": [],
                "error": "ocr timeout",
            })
        except Exception as exc:
            results.append({
                "name": source_name or (temp_path.name if temp_path else "unknown"),
                "text": "",
                "lines": [],
                "error": str(exc),
            })
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    return {"images": results}


@router.get("/workspace/{ws_id}/files")
async def list_workspace_files(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出工作区文件"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        return workspace_mgr.list_files(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


async def _read_class_file_decompiled(ws_id: str, file_path: str) -> dict:
    """.class 文件按字节没法预览,反编译成文本返回(CFR 优先, javap 兜底)。"""
    from app.coding.class_decompiler import DecompileError, decompile_class_file

    ws_path = workspace_mgr.get_workspace_path(ws_id)
    target = (ws_path / file_path).resolve()
    if not str(target).startswith(str(ws_path.resolve())):
        raise HTTPException(status_code=400, detail="文件路径越界")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    try:
        result = await asyncio.to_thread(decompile_class_file, target)
    except DecompileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "path": file_path,
        "content": result.text,
        "decompiled": True,
        "decompiler": result.tool,
    }


@router.get("/workspace/{ws_id}/file")
async def read_workspace_file(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """读取工作区文件内容;.class 返回反编译文本(decompiled: true)"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    if file_path.lower().endswith(".class"):
        return await _read_class_file_decompiled(ws_id, file_path)
    try:
        content = workspace_mgr.read_file(ws_id, file_path)
        return {"path": file_path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspace/{ws_id}/raw")
async def download_workspace_file_raw(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """以原始字节返回工作区单文件，供二进制文件（zip/图片/字体等）下载。"""
    from fastapi.responses import FileResponse

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    target = (ws_path / file_path).resolve()
    if not str(target).startswith(str(ws_path.resolve())):
        raise HTTPException(status_code=400, detail="文件路径越界")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    return FileResponse(str(target), filename=target.name)


@router.post("/workspace/{ws_id}/file")
async def write_workspace_file(
    ws_id: str,
    req: WriteFileRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """写入文件到工作区"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        workspace_mgr.write_file(ws_id, req.file_path, req.content)
        return {"status": "ok", "path": req.file_path}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspaces")
async def list_workspaces(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前用户的所有工作区"""
    owned_result = await db.execute(
        select(Project.id).where(
            Project.tenant_id == ctx.tenant_id,
            Project.user_id == ctx.user.id,
        )
    )
    member_result = await db.execute(
        select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.user.id)
    )
    project_ids = {row[0] for row in owned_result.all()}
    project_ids.update(row[0] for row in member_result.all())

    workspaces = workspace_mgr.list_accessible_workspaces(
        ctx.user.id, list(project_ids), tenant_id=ctx.tenant_id
    )

    # 租户隔离收紧:list_accessible_workspaces 对「缺 tenant_id 的老 workspace」按 user_id 兜底放行,
    # 导致同一用户(如 admin)切租户后仍看到别租户的老自开发资产(「切了租户数据没变」)。
    # 这里用 workspace 关联会话的 tenant_id 推断真实归属:别租户的剔除,本租户的回填 .workspace.json
    # (回填后下次走严格过滤,自愈)。无会话的孤儿 workspace 维持 user_id 归属(仅本人可见,非跨用户泄漏)。
    legacy_ids = [str(ws.get("id")) for ws in workspaces if ws.get("tenant_id") in (None, "")]
    if legacy_ids:
        owner_rows = await db.execute(
            select(Conversation.workspace_id, Conversation.tenant_id).where(
                Conversation.workspace_id.in_(legacy_ids),
                Conversation.tenant_id.isnot(None),
            )
        )
        ws_owner_tenant: dict[str, int] = {}
        for ws_id_val, tenant_val in owner_rows.all():
            if ws_id_val and tenant_val is not None:
                ws_owner_tenant.setdefault(str(ws_id_val), int(tenant_val))
        kept: list[dict[str, Any]] = []
        for ws in workspaces:
            if ws.get("tenant_id") in (None, ""):
                owner_tenant = ws_owner_tenant.get(str(ws.get("id")))
                if owner_tenant is not None and owner_tenant != ctx.tenant_id:
                    continue  # 属于别的租户 → 隐藏
                if owner_tenant == ctx.tenant_id:
                    if workspace_mgr.stamp_tenant_id(str(ws.get("id")), ctx.tenant_id):
                        ws["tenant_id"] = ctx.tenant_id  # 回填,UI 也立即一致
            kept.append(ws)
        workspaces = kept

    decorated: list[dict[str, Any]] = []
    for ws in workspaces:
        project_id = ws.get("project_id")
        if project_id:
            access = await require_project_access(
                db,
                project_id=int(project_id),
                user_id=ctx.user.id,
                tenant_id=ctx.tenant_id,
            )
            decorated.append(_decorate_workspace_access(ws, access.role))
        else:
            decorated.append(_decorate_workspace_access(ws, "owner"))
    return decorated


@router.get("/workspace/{ws_id}/conversation")
async def get_workspace_conversation(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取工作区关联的对话及消息"""
    workspace_meta = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    conditions = [
        Conversation.tenant_id == ctx.tenant_id,
        Conversation.workspace_id == ws_id,
        Conversation.agent_type == "coding",
    ]
    if not workspace_meta.get("project_id"):
        conditions.append(Conversation.user_id == ctx.user.id)
    stmt = select(Conversation).where(*conditions).order_by(Conversation.updated_at.desc()).limit(10)
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    if not conversations:
        return {"conversation_id": None, "selected_llm_config_id": None, "messages": []}

    selected_conv = conversations[0]
    selected_messages: list[Message] = []

    for conv in conversations:
        msg_stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
        )
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()
        if not selected_messages:
            selected_conv = conv
            selected_messages = messages

        has_assistant_reply = any(
            m.role == "assistant" and isinstance(m.content, str) and m.content.strip()
            for m in messages
        )
        has_multi_message_history = len(messages) >= 2
        if has_assistant_reply or has_multi_message_history:
            selected_conv = conv
            selected_messages = messages
            break

    replay_payload = _load_workspace_chat_payload(
        ws_id,
        filename="chat-replay.json",
        conversation_id=selected_conv.id,
    )
    if not replay_payload["messages"] and not replay_payload["stream_messages"]:
        replay_payload = _load_workspace_chat_payload(
            ws_id,
            filename="chat-history.json",
            conversation_id=selected_conv.id,
        )

    response_messages = replay_payload["messages"] or [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in selected_messages
    ]

    return {
        "conversation_id": selected_conv.id,
        "selected_llm_config_id": selected_conv.selected_llm_config_id,
        "messages": response_messages,
        "stream_messages": replay_payload["stream_messages"],
    }


@router.delete("/workspace/{ws_id}")
async def delete_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除工作区：先停掉所有 npm run serve 进程，再删除工作区文件夹。"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    await workspace_mgr.delete_workspace(ws_id)
    return {"status": "ok"}


# ============================================================
# 辅助函数
# ============================================================

async def _get_conversation_history(
    db: AsyncSession, conversation_id: int
) -> list:
    """获取对话历史"""
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


def _summarize_history_content(content: str, max_chars: int = 220) -> str:
    if not content:
        return ""

    text = str(content)
    text = text.replace("\r\n", "\n")
    text = text.replace("</think>", "").replace("<think>", "")
    text = text.replace("[TOOL_CALL]", "").replace("[/TOOL_CALL]", "")
    text = re.sub(r"```[\s\S]*?```", "[代码片段已省略]", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(text) > max_chars:
        text = text[:max_chars] + "...[截断]"
    return text


def _build_ide_conversation_context(history: list[dict[str, str]], max_messages: int = 6) -> str:
    if not history:
        return ""

    recent_messages = history[-max_messages:]
    lines: list[str] = []
    for item in recent_messages:
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        label = "用户" if role == "user" else "AI"
        summary = _summarize_history_content(item.get("content", ""))
        if not summary:
            continue
        lines.append(f"{label}: {summary}")

    return "\n".join(lines)[:1800]


# ============================================================
# 文件上传接口
# ============================================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    workspace_id: Optional[str] = Query(None),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """
    上传文件（图片/文档）用于对话附件。
    - 图片: 保存到工作区或临时目录，返回文件路径
    - 文本文档(.md, .txt): 读取并返回文本内容
    - 其他文档(.pdf, .docx): 尝试提取文本，否则返回文件路径
    """
    import os
    import tempfile

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    content_bytes = await file.read()
    filename = file.filename
    content_type = file.content_type or "application/octet-stream"
    ext = os.path.splitext(filename)[1].lower()

    # Determine save directory
    if workspace_id:
        workspace_meta = await _ensure_workspace_access(workspace_id, ctx, db, minimum_project_role="member")
        save_dir = os.path.join(workspace_meta["disk_path"], "uploads")
    else:
        save_dir = os.path.join(tempfile.gettempdir(), "coding_uploads")

    os.makedirs(save_dir, exist_ok=True)

    # Generate unique filename to avoid conflicts
    import uuid
    unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_path = os.path.join(save_dir, unique_name)

    with open(file_path, "wb") as f:
        f.write(content_bytes)

    result = {
        "filename": filename,
        "content_type": content_type,
        "file_path": file_path,
    }

    # For text-based documents, extract content
    if ext in (".md", ".txt"):
        try:
            text_content = content_bytes.decode("utf-8")
            result["content"] = text_content
        except UnicodeDecodeError:
            pass  # Binary file, just return path
    elif ext == ".docx":
        try:
            from docx import Document as DocxDocument
            import io
            doc = DocxDocument(io.BytesIO(content_bytes))
            text_content = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            result["content"] = text_content
        except ImportError:
            logger.info("python-docx not installed, returning file path only for .docx")
        except Exception as e:
            logger.warning(f"Failed to extract .docx content: {e}")
    elif ext == ".pdf":
        try:
            from markitdown import MarkItDown
            mid = MarkItDown()
            md_result = mid.convert(file_path)
            result["content"] = md_result.text_content
        except ImportError:
            logger.info("markitdown not installed, returning file path only for .pdf")
        except Exception as e:
            logger.warning(f"Failed to extract PDF content: {e}")

    return result


# ============================================================
# 自动化 Pipeline（对话式开发）
# ============================================================

workspace_mgr = WorkspaceManager()


@router.post("/auto-pipeline")
async def auto_pipeline(
    req: AutoPipelineRequest,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    自动化 Pipeline（对话式组件开发）— 兼容入口。

    内部委托给 app.coding.pipeline.run_coding_pipeline，
    新前端应直接调用 /api/harness/coding/pipeline。
    """
    from app.coding.pipeline import PipelineParams, run_coding_pipeline

    if req.workspace_id:
        await _ensure_workspace_access(req.workspace_id, ctx, db, minimum_project_role="member")
    if req.project_id:
        await require_project_access(
            db,
            project_id=req.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )

    # 预计算 request-scoped 值
    api_base = _build_ide_proxy_api_base(request, req.workspace_id or "__placeholder__")
    api_base_pattern = api_base.replace(req.workspace_id or "__placeholder__", "{ws_id}")

    params = PipelineParams(
        message=req.message,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        workspace_id=req.workspace_id,
        conversation_id=req.conversation_id,
        selected_model=req.selected_model,
        project_id=req.project_id,
        code_server_base_url=settings.code_server_base_url or "",
        api_base_builder=api_base_pattern,
    )

    async def pipeline_events():
        async for event in run_coding_pipeline(params, db):
            yield _sse(event)

    return _event_stream_response(pipeline_events(), ping=15)


@router.post("/workspace/{ws_id}/serve")
async def manage_serve(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    action: str = Query(default="start", description="start 或 stop"),
):
    """启动或停止工作区的 serve 进程"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_mgr = WorkspaceManager()
    if action == "start":
        result = await ws_mgr.start_serve(ws_id)
    elif action == "stop":
        result = await ws_mgr.stop_serve(ws_id)
    else:
        raise HTTPException(status_code=400, detail="action 必须是 start 或 stop")
    return result


@router.get("/workspace/{ws_id}/serve-status")
async def get_serve_status(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """查询 serve 运行状态"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_mgr = WorkspaceManager()
    return ws_mgr.is_serve_running(ws_id)


@router.post("/workspace/{ws_id}/publish")
async def publish_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """构建 + 打包 zip（一键发布）"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    ws_mgr = WorkspaceManager()
    try:
        zip_path = await ws_mgr.build_and_package(ws_id)
        # 返回下载链接
        from fastapi.responses import FileResponse
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=zip_path.split("/")[-1] if isinstance(zip_path, str) else zip_path.name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# project_type → 平台 fileType 映射
_PROJECT_TYPE_TO_FILE_TYPE = {
    "form-component-dual": "FRONTCOMPONENT",
    "menu-page": "FRONTENGINE",
    "form-page": "FRONTENGINE",
    "form-list": "FRONTLISTVIEW",
    "layout": "FRONTLAYOUT",
    "mobile-page": "MFRONTENGINE",
    "plugin": "FRONTTENANTCOMPONENT",
    "backend-api": "BACKENDENGINE",
    "backend-feign": "BACKENDENGINE",
    "backend-scheduled": "BACKENDENGINE",
}


class UploadToPlatformRequest(BaseModel):
    env_id: int


async def _query_existing_development_kits(
    base_url: str,
    tenant_id: str,
    token: str,
    key_word: str,
) -> list[dict]:
    """查询平台已有的自开发组件列表（模糊匹配 keyWord）。

    接口: POST /xdap-app/selfdevelopment/query/allDevelopmentKit
    keyWord 直接使用完整文件名（含 .zip）或 outputName 前缀，平台做模糊匹配。

    返回 table 原始列表；调用方自行按 fileName 精准匹配。
    查询失败（网络/非 JSON/code != ok）统一返回空列表，调用方走新增分支。
    """
    import time as _time
    query_url = f"{base_url.rstrip('/')}/xdap-app/selfdevelopment/query/allDevelopmentKit"
    logger.info(f"[upload-to-platform] 查询已有组件 keyWord={key_word!r}")
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        try:
            resp = await http.post(
                query_url,
                headers={
                    "xdaptenantid": tenant_id,
                    "xdaptoken": token,
                    "xdaptimestamp": str(int(_time.time() * 1000)),
                    "Content-Type": "application/json",
                },
                json={"keyWord": key_word, "page": 1, "pageSize": 50},
            )
        except httpx.RequestError as e:
            logger.warning(f"[upload-to-platform] 查询已有组件失败: {e}")
            return []
    try:
        data = resp.json()
    except Exception:
        logger.warning(f"[upload-to-platform] 查询响应非 JSON: status={resp.status_code}")
        return []
    if data.get("code") != "ok":
        logger.warning(f"[upload-to-platform] 查询失败 code={data.get('code')} msg={data.get('message')}")
        return []
    table = data.get("table") or []
    kits = [item for item in table if isinstance(item, dict)]
    logger.info(f"[upload-to-platform] 查询到 {len(kits)} 条: {[k.get('fileName') for k in kits]}")
    return kits


def _find_kit_by_filename(kits: list[dict], file_name: str) -> Optional[dict]:
    """在查询返回的 table 中按 fileName 精准匹配。"""
    for item in kits:
        if item.get("fileName") == file_name:
            return item
    return None


def _build_upload_form_data(
    *,
    file_type: str,
    description: str,
    version_code: str,
    upload_id: str,
    existing_kit: Optional[dict] = None,
) -> dict:
    """构造上传的表单字段。

    - 新增：返回 fileType / description / uploadId / versionCode / useScope 等基础字段
    - 更新：在基础字段上追加 id / ossObjectName / fileName / yeahMonthDate 等从查询结果继承的字段；
            description 自动追加"更新于 YYYY-MM-DD HH:MM:SS"便于在平台侧辨认版本
    """
    effective_description = description
    if existing_kit:
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        effective_description = f"{description}（更新于 {ts}）"

    form: dict = {
        "fileType": file_type,
        "description": effective_description,
        "uploadId": upload_id,
        "versionCode": version_code,
        "useScope": "全部应用",
        "internalResource": "false",
        "effectiveScope": "SINGLE_APPLICATION",
    }
    if existing_kit:
        # 更新场景：复用平台已有的 id / ossObjectName / fileName / yeahMonthDate 等
        for key in ("id", "ossObjectName", "fileName", "yeahMonthDate"):
            val = existing_kit.get(key)
            if val is not None:
                form[key] = str(val)
        # 复用 useScope / effectiveScope / internalResource（平台可能有不同配置）
        if existing_kit.get("useScope"):
            form["useScope"] = existing_kit["useScope"]
        if existing_kit.get("effectiveScope"):
            form["effectiveScope"] = existing_kit["effectiveScope"]
        if "internalResource" in existing_kit:
            form["internalResource"] = str(existing_kit["internalResource"]).lower()
    return form


async def _build_and_upload_kits(*, ws_mgr, ws_id: str, env, db) -> dict:
    """构建 workspace → 上传 developmentKit(组件库)→ 用 fileName 反查 kit_id。

    供 deploy-to-app 复用。调用方需先确保 env.token 有效(deploy_to_app 用
    extension._ensure_env_token);故本函数内不再做 401 自愈。
    返回 {kit_ids, file_type, project_type, display_name, file_names}。
    """
    import time as _t
    import uuid as _u

    ws_path = ws_mgr.get_workspace_path(ws_id)
    meta = ws_mgr._read_meta(ws_path)
    project_type = meta.get("project_type", "")
    display_name = meta.get("display_name") or meta.get("project_name", ws_id)

    # 1. 构建 + 打包(双端两包 / 后端 jar / 其余单 zip)
    if project_type == ProjectType.FORM_COMPONENT_DUAL.value:
        packages = await ws_mgr.build_and_package_dual(ws_id)  # [(path, fileType), ...]
    else:
        ft = _PROJECT_TYPE_TO_FILE_TYPE.get(project_type)
        if not ft:
            raise HTTPException(status_code=400, detail=f"不支持上传的项目类型: {project_type}")
        if project_type in {"backend-api", "backend-feign", "backend-scheduled"}:
            out_dir = ws_mgr._get_build_output_dir(ws_path)
            jars = [j for j in out_dir.glob("*.jar") if not j.name.endswith(".original")]
            if not jars:
                raise HTTPException(status_code=500, detail="未找到编译产物 JAR,请先在 IDE 构建项目")
            packages = [(str(jars[0]), ft)]
        else:
            packages = [(await ws_mgr.build_and_package(ws_id), ft)]

    add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
    update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"
    file_names = [Path(p).name for p, _ in packages]
    key_word = file_names[0][:-4] if file_names[0].endswith(".zip") else file_names[0]
    existing = await _query_existing_development_kits(
        env.base_url, env.platform_tenant_id, env.token, key_word,
    )

    # 2. 逐包上传(update-if-exists)
    for zip_str, ft in packages:
        fp = Path(zip_str)
        kit = _find_kit_by_filename(existing, fp.name)
        form_data = _build_upload_form_data(
            file_type=ft, description=f"{display_name} - 由 apaas-builder 装回",
            version_code=_u.uuid4().hex, upload_id=str(int(_t.time() * 1000)), existing_kit=kit,
        )
        target = update_url if kit else add_url
        ct = "application/java-archive" if fp.suffix == ".jar" else "application/zip"
        async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
            r = await http.post(target, headers={
                "xdaptenantid": env.platform_tenant_id, "xdaptoken": env.token,
                "xdaptimestamp": str(int(_t.time() * 1000)),
            }, files={"file": (fp.name, fp.read_bytes(), ct)}, data=form_data)
        try:
            rj = r.json()
        except Exception:
            raise HTTPException(status_code=502, detail=f"平台上传响应非 JSON (status={r.status_code})")
        if rj.get("code") not in ("ok", 200):
            raise HTTPException(status_code=500, detail=rj.get("message") or rj.get("msg") or "上传失败")

    # 3. 反查 kit_id(add/update 响应不一定带 id)
    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=env.token)
    kits = await client.query_app_dev_kits("", file_name=key_word)
    kit_ids = [str(k["id"]) for fn in file_names for k in kits if k.get("fileName") == fn and k.get("id")]

    # 页面类建菜单的 link_url = 自开发组件注册名(取 workspace apaas.json 的 outputName)
    try:
        _cfg = ws_mgr._read_apaas_config(ws_path)
        register_name = ws_mgr._resolve_output_name(_cfg, display_name) if isinstance(_cfg, dict) else display_name
    except Exception:
        register_name = display_name

    return {
        "kit_ids": kit_ids,
        "file_type": packages[0][1],
        "project_type": project_type,
        "display_name": display_name,
        "file_names": file_names,
        "register_name": register_name,
    }


@router.post("/workspace/{ws_id}/upload-to-platform")
async def upload_workspace_to_platform(
    ws_id: str,
    body: UploadToPlatformRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """构建 + 打包 zip，然后上传到指定的平台环境"""
    import time
    import uuid
    from app.models import PlatformEnv

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")

    # 1. 查询平台环境（验证属于当前 tenant）
    result = await db.execute(
        select(PlatformEnv).where(PlatformEnv.id == body.env_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="平台环境不存在")
    if ctx.tenant_id and env.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该平台环境")
    if not env.token:
        raise HTTPException(status_code=400, detail="平台环境未登录，请先在环境管理中连接")

    # 1b. 确保 token 有效，过期则用保存的账号密码自动重新登录
    async def _refresh_env_token(env, db) -> str:
        if not env.username or not env.password_enc:
            raise HTTPException(status_code=400, detail="平台 token 已过期且未保存登录凭证，请在环境管理中重新连接")
        try:
            password = decrypt_password(env.password_enc)
            apaas = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await apaas.login(env.username, password)
            new_token = login_result.get("token") if isinstance(login_result, dict) else None
            if not new_token:
                raise Exception("登录返回中未包含 token")
            env.token = new_token
            env.status = "connected"
            await db.commit()
            return new_token
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"平台 token 已过期，自动重新登录失败: {e}")

    # 2. 构建 + 打包
    ws_mgr = WorkspaceManager()
    ws_path = ws_mgr.get_workspace_path(ws_id)
    meta = ws_mgr._read_meta(ws_path)
    project_type = meta.get("project_type", "")
    display_name = meta.get("display_name") or meta.get("project_name", ws_id)

    # 双端模板：构建两个包，各自上传
    if project_type == ProjectType.FORM_COMPONENT_DUAL.value:
        try:
            dual_packages = await ws_mgr.build_and_package_dual(ws_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"双端构建失败: {e}")

        add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
        update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"

        async def _do_upload_file(token: str, file_path: Path, ft: str, existing_kit: Optional[dict]):
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            form_data = _build_upload_form_data(
                file_type=ft,
                description=f"{display_name} - 由 apaas-builder 上传",
                version_code=uuid.uuid4().hex,
                upload_id=str(int(time.time() * 1000)),
                existing_kit=existing_kit,
            )
            target_url = update_url if existing_kit else add_url
            async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
                return await http.post(
                    target_url,
                    headers={
                        "xdaptenantid": env.platform_tenant_id,
                        "xdaptoken": token,
                        "xdaptimestamp": str(int(time.time() * 1000)),
                    },
                    files={"file": (file_path.name, file_bytes, "application/zip")},
                    data=form_data,
                )

        # 双端：用 PC outputName（无 .zip / 无 -m 后缀）作为 keyWord 一次查询，
        # PC 包 form-xxx.zip 和 mobile 包 form-xxx-m.zip 都能被模糊命中
        web_file_name = next(
            (Path(p).name for p, ft in dual_packages if ft == "FRONTCOMPONENT"),
            None,
        )
        default_name = web_file_name or (Path(dual_packages[0][0]).name if dual_packages else "")
        # 去掉 .zip 后缀做 keyWord（平台模糊匹配，不能带后缀）
        query_keyword = default_name[:-4] if default_name.endswith(".zip") else default_name
        existing_kits = await _query_existing_development_kits(
            env.base_url, env.platform_tenant_id, env.token, query_keyword,
        )

        upload_results = []
        for zip_path_str, ft in dual_packages:
            file_path = Path(zip_path_str)
            existing_kit = _find_kit_by_filename(existing_kits, file_path.name)
            action = "update" if existing_kit else "create"
            logger.info(
                f"[upload-to-platform] {file_path.name} → {action}"
                + (f" (id={existing_kit.get('id')})" if existing_kit else "")
            )

            try:
                response = await _do_upload_file(env.token, file_path, ft, existing_kit)
            except httpx.RequestError as e:
                logger.exception(f"[upload-to-platform] 上传 {file_path.name} 失败: {target_url}")
                err_detail = str(e) or repr(e)
                raise HTTPException(
                    status_code=502,
                    detail=f"上传 {file_path.name} 请求失败: {type(e).__name__}: {err_detail}（目标 URL: {target_url}）",
                )
            try:
                resp_data = response.json()
            except Exception:
                raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

            def _is_unauthorized(data: dict) -> bool:
                msg = (data.get("message") or data.get("msg") or "").lower()
                code = data.get("code")
                return response.status_code == 401 or code == 401 or "unauthorized" in msg

            if _is_unauthorized(resp_data):
                new_token = await _refresh_env_token(env, db)
                # token 刷新后整个列表重新查一次，避免 mobile 包那条还在用过期 token 的结果
                existing_kits = await _query_existing_development_kits(
                    env.base_url, env.platform_tenant_id, new_token, query_keyword,
                )
                existing_kit = _find_kit_by_filename(existing_kits, file_path.name)
                try:
                    response = await _do_upload_file(new_token, file_path, ft, existing_kit)
                    resp_data = response.json()
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"刷新 token 后重试失败: {e}")

            upload_results.append({
                "file": file_path.name,
                "fileType": ft,
                "action": action,
                "response": resp_data,
            })

        action_summary = ", ".join(
            f"{r['file']}({'更新' if r['action'] == 'update' else '新增'})" for r in upload_results
        )
        return {
            "status": "ok",
            "message": f"双端上传完成：{action_summary}",
            "results": upload_results,
        }

    # 单端项目：原有逻辑
    try:
        zip_path = await ws_mgr.build_and_package(ws_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构建失败: {e}")

    file_type = _PROJECT_TYPE_TO_FILE_TYPE.get(project_type)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"不支持上传的项目类型: {project_type}")

    # 4. 上传到平台（token 过期时自动刷新后重试一次）
    add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
    update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"

    # 后端项目：直接上传 JAR 文件（平台要求 application/java-archive）
    _backend_project_types = {"backend-api", "backend-feign", "backend-scheduled"}
    if project_type in _backend_project_types:
        output_dir = ws_mgr._get_build_output_dir(ws_path)
        jar_files = [j for j in output_dir.glob("*.jar") if not j.name.endswith(".original")]
        if not jar_files:
            raise HTTPException(status_code=500, detail="未找到编译产物 JAR，请先在 IDE 中构建项目")
        upload_file_path = jar_files[0]
        upload_content_type = "application/java-archive"
    else:
        upload_file_path = Path(zip_path)
        upload_content_type = "application/zip"

    async def _do_upload(token: str, existing_kit: Optional[dict]):
        with open(upload_file_path, "rb") as f:
            file_bytes = f.read()
        form_data = _build_upload_form_data(
            file_type=file_type,
            description=f"{display_name} - 由 apaas-builder 上传",
            version_code=uuid.uuid4().hex,
            upload_id=str(int(time.time() * 1000)),
            existing_kit=existing_kit,
        )
        target_url = update_url if existing_kit else add_url
        async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
            return await http.post(
                target_url,
                headers={
                    "xdaptenantid": env.platform_tenant_id,
                    "xdaptoken": token,
                    "xdaptimestamp": str(int(time.time() * 1000)),
                },
                files={"file": (upload_file_path.name, file_bytes, upload_content_type)},
                data=form_data,
            )

    # 先查询平台是否已有同名组件（keyWord 去掉 .zip 后缀，平台模糊匹配）
    single_file_name = upload_file_path.name
    single_query_keyword = single_file_name[:-4] if single_file_name.endswith(".zip") else single_file_name
    existing_kits = await _query_existing_development_kits(
        env.base_url, env.platform_tenant_id, env.token, single_query_keyword,
    )
    existing_kit = _find_kit_by_filename(existing_kits, single_file_name)
    action = "update" if existing_kit else "create"

    try:
        response = await _do_upload(env.token, existing_kit)
    except httpx.RequestError as e:
        logger.exception(f"[upload-to-platform] 单端上传失败 base_url={env.base_url}")
        err_detail = str(e) or repr(e)
        raise HTTPException(
            status_code=502,
            detail=f"上传请求失败: {type(e).__name__}: {err_detail}（目标平台 base_url: {env.base_url}）",
        )

    # 5. 解析响应；若 token 过期则刷新后重试一次
    try:
        resp_data = response.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

    def _is_unauthorized(data: dict) -> bool:
        msg = (data.get("message") or data.get("msg") or "").lower()
        code = data.get("code")
        return response.status_code == 401 or code == 401 or "unauthorized" in msg

    if _is_unauthorized(resp_data):
        new_token = await _refresh_env_token(env, db)
        # token 刷新后重新查询
        existing_kits = await _query_existing_development_kits(
            env.base_url, env.platform_tenant_id, new_token, single_query_keyword,
        )
        existing_kit = _find_kit_by_filename(existing_kits, upload_file_path.name)
        try:
            response = await _do_upload(new_token, existing_kit)
            resp_data = response.json()
        except httpx.RequestError as e:
            logger.exception(f"[upload-to-platform] 单端 token 刷新后重试上传失败 base_url={env.base_url}")
            err_detail = str(e) or repr(e)
            raise HTTPException(
                status_code=502,
                detail=f"上传请求失败: {type(e).__name__}: {err_detail}（目标平台 base_url: {env.base_url}）",
            )
        except Exception:
            raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

    code = resp_data.get("code")
    if code == "ok" or code == 200:
        action_label = "更新" if action == "update" else "新增"
        return {"status": "ok", "message": f"上传成功（{action_label}）", "action": action}
    else:
        msg = resp_data.get("message") or resp_data.get("msg") or "上传失败"
        raise HTTPException(status_code=500, detail=msg)


class DeployToAppRequest(BaseModel):
    local_app_id: Optional[int] = None   # bound 模式传本地 app_id;lib 模式不传


_PAGE_TYPES = {"menu-page", "form-page", "mobile-page"}


async def _deploy_to_app_impl(ws_id: str, local_app_id, ctx, db) -> dict:
    """装回应用编排:upload → (bound) enable→attach→页面建菜单→republish。

    - bound(传 local_app_id):部署到该应用并重发。
    - lib(不传):只上传到自开发资产库(组件库),不 attach。
    两个 id 别混:attach/menu 走平台 apaas_app_id;republish/广播走本地 app_id。
    """
    from app.models import PlatformEnv

    ws_mgr = WorkspaceManager()

    # ── lib:只上传到组件库 ──
    if not local_app_id:
        env = (await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )).scalars().first()
        if not env:
            raise HTTPException(status_code=400, detail="租户未配置平台环境")
        env.token = await _ensure_env_token(env, db)
        up = await _build_and_upload_kits(ws_mgr=ws_mgr, ws_id=ws_id, env=env, db=db)
        return {
            "status": "uploaded_only",
            "kits": up["file_names"],
            "hint": "已传到自开发资产库,可在表单设计器引用 / 去 Builder 关联到应用",
        }

    # ── bound:部署到应用 ──
    app, env = await _load_app_and_env(local_app_id, ctx, db)
    if not getattr(app, "apaas_app_id", None):
        raise HTTPException(status_code=400, detail="应用尚未部署到平台(无 apaas_app_id),无法装回")
    if env is None:
        raise HTTPException(status_code=400, detail="租户未配置平台环境")
    env.token = await _ensure_env_token(env, db)
    apaas_app_id = str(app.apaas_app_id)

    up = await _build_and_upload_kits(ws_mgr=ws_mgr, ws_id=ws_id, env=env, db=db)
    if not up["kit_ids"]:
        raise HTTPException(status_code=502, detail="上传成功但反查不到 kit id,无法关联到应用")

    # 所有 apaas write 走 call_apaas_with_relogin:token 过期 → 自动重登重试一次,
    # 不再把 401「Unauthorized」抛给用户(铁律:apaas 调用别裸调)。
    env_id = env.id
    await call_apaas_with_relogin(env_id, db, lambda c: c.enable_self_dev_config(apaas_app_id, "ENABLE"))
    await call_apaas_with_relogin(env_id, db, lambda c: c.attach_apaas_source_relation(apaas_app_id, object_ids=up["kit_ids"]))

    menu = None
    if up["project_type"] in _PAGE_TYPES:
        register = up.get("register_name") or up["display_name"]
        await call_apaas_with_relogin(env_id, db, lambda c: c.create_self_dev_menu(apaas_app_id, menu_name=up["display_name"], link_url=register))
        menu = up["display_name"]

    # republish:取当前版本 → deploy_app;版本冲突则 patch+1 重试
    detail = await call_apaas_with_relogin(env_id, db, lambda c: c.query_app_detail(apaas_app_id))
    version = str(detail.get("currentVersion") or detail.get("version") or "1.0.0")
    try:
        await call_apaas_with_relogin(env_id, db, lambda c: c.deploy_app(apaas_app_id, version, abstract="自开发装回自动重发"))
    except Exception as e:
        if "版本" in str(e) or "version" in str(e).lower():
            parts = version.split(".")
            try:
                parts[-1] = str(int(parts[-1]) + 1)
            except (ValueError, IndexError):
                raise
            version = ".".join(parts)
            await call_apaas_with_relogin(env_id, db, lambda c: c.deploy_app(apaas_app_id, version, abstract="自开发装回自动重发"))
        else:
            raise

    await publish_extension_update(app.id, "republish_done", {"kits": up["file_names"]})
    return {
        "status": "installed",
        "app": {"local_app_id": app.id, "name": getattr(app, "name", "")},
        "menu": menu,
        "version": version,
        "kits": up["file_names"],
    }


@router.post("/workspace/{ws_id}/deploy-to-app")
async def deploy_to_app(
    ws_id: str,
    body: DeployToAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """装回应用 / 发布到资产库:见 _deploy_to_app_impl。"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    return await _deploy_to_app_impl(ws_id, body.local_app_id, ctx, db)


@router.get("/workspace/{ws_id}/debug/screenshot/{filename}")
async def get_debug_screenshot(
    ws_id: str,
    filename: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve debug screenshot image"""
    import re
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    # Sanitize filename to prevent directory traversal
    if not re.match(r'^[\w\-\.]+\.(png|jpg|jpeg)$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    screenshot_path = workspace_mgr.get_workspace_path(ws_id) / "debug" / "screenshots" / filename
    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    from fastapi.responses import FileResponse
    return FileResponse(str(screenshot_path), media_type="image/png")


class DebugRequest(BaseModel):
    """Debug 请求（参数可选，优先从项目配置读取，回退到用户平台连接信息）"""
    platform_url: Optional[str] = None
    tenant_id: Optional[str] = None
    app_id: Optional[str] = None
    project_id: Optional[int] = None
    debug_mode: str = "app"  # "platform"（设计态） or "app"（运行态）
    form_id: Optional[str] = None   # 用户指定的表单ID（为空则自动创建）
    menu_id: Optional[str] = None   # 用户指定的菜单ID


@router.post("/workspace/{ws_id}/debug")
async def debug_workspace(
    ws_id: str,
    req: DebugRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """启动 Debug 模式：确保 serve 运行 + 启动 Puppeteer 注入组件到平台"""
    ws_mgr = WorkspaceManager()
    workspace_meta = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")

    # 1. 确保 serve 在运行
    serve_info = ws_mgr.is_serve_running(ws_id)
    if not serve_info["running"]:
        serve_result = await ws_mgr.start_serve(ws_id)
        if serve_result["status"] != "ok":
            raise HTTPException(status_code=500, detail=f"启动 serve 失败: {serve_result.get('message', '')}")
        serve_port = serve_result["port"]
    else:
        serve_port = serve_info["port"]

    # 2. 读取 apaas.json 获取组件信息
    ws_path = ws_mgr.get_workspace_path(ws_id)
    apaas_json_path = ws_path / "src" / "apaas.json"
    if not apaas_json_path.exists():
        raise HTTPException(status_code=400, detail="apaas.json 不存在")

    import json as _json
    apaas_config = _json.loads(apaas_json_path.read_text())
    output_name = apaas_config.get("outputName", "")
    custom_widget_list = apaas_config.get("customWidgetList", [])

    # 3. 从项目配置 / 请求参数 / 用户平台连接信息获取 debug 参数
    user = ctx.user
    project = None
    _project_id = req.project_id
    if not _project_id:
        # Try to get project_id from workspace metadata
        _project_id = workspace_meta.get("project_id")
    if _project_id:
        access = await require_project_access(
            db,
            project_id=int(_project_id),
            user_id=user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )
        project = access.project

    if project and project.platform_url:
        _platform_url = req.platform_url or _get_platform_frontend_url(project.platform_url)
        _tenant_id = req.tenant_id or user.apaas_tenant_id or project.platform_tenant_id or ""
        _app_id = req.app_id or project.platform_app_id or "806997227284201472"
    else:
        _platform_url = req.platform_url or _get_user_platform_url(user)
        _tenant_id = req.tenant_id or user.apaas_tenant_id or ""
        _app_id = req.app_id or "806997227284201472"

    # 4. 获取 app_code（用于应用 debug 模式）
    _app_code = ""
    if project:
        _app_code = getattr(project, 'platform_app_code', '') or ''

    # 获取 platform_token 和 platform_backend_url（自动创建表单需要）
    _apaas_token = ""
    _platform_backend_url = ""
    if project:
        _apaas_token = getattr(project, 'platform_token', '') or ''
        _platform_backend_url = getattr(project, 'platform_url', '') or ''

    # 从组件配置中提取组件名称
    _component_name = ""
    if custom_widget_list:
        _component_name = custom_widget_list[0].get("name", "") or custom_widget_list[0].get("code", "")

    # 5. 启动 Puppeteer debug（后台进程）
    debug_result = await ws_mgr.start_debug(
        ws_id=ws_id,
        serve_port=serve_port,
        platform_url=_platform_url,
        tenant_id=_tenant_id,
        app_id=_app_id,
        output_name=output_name,
        custom_widget_list=custom_widget_list,
        debug_mode=req.debug_mode,
        app_code=_app_code,
        form_id=req.form_id or "",
        menu_id=req.menu_id or "",
        component_name=_component_name,
        apaas_token=_apaas_token,
        platform_backend_url=_platform_backend_url,
    )

    return debug_result


def _get_platform_frontend_url(backend_url: str) -> str:
    """从平台后端 URL 推导出平台前端 URL"""
    base = backend_url or ""
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else ""


def _get_user_platform_url(user) -> str:
    """从用户的平台连接信息推导出平台前端 URL"""
    base = user.apaas_base_url or settings.apaas_base_url or ""
    # apaas_base_url 通常是后端地址，平台前端地址由它推导。
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else ""


def _sse(data: dict) -> str:
    """SSE 事件格式化"""
    return json.dumps(data, ensure_ascii=False)


async def _extract_project_name(generator: CodingGenerator, message: str) -> str:
    """从用户需求中提取项目名称，优先使用 LLM 翻译，关键字表仅作快速缓存"""
    import re
    import uuid

    # 快速缓存：高频词直接命中，避免不必要的 LLM 调用
    _KEYWORD_CACHE = {
        "甘特图": "gantt-chart", "审批流程": "approval-flow", "审批": "approval",
        "进度条": "progress-bar", "评分": "star-rating", "颜色选择器": "color-picker",
        "颜色选择": "color-picker", "标签输入": "tag-input", "图表分析": "chart-analysis",
        "图表": "chart", "日期范围": "date-range", "日期选择": "date-picker",
        "文件上传": "file-upload", "上传": "file-upload", "头像": "avatar",
        "签名": "signature", "二维码": "qrcode", "富文本": "rich-text",
        "组织架构树": "org-tree", "组织架构": "org-tree", "组织树": "org-tree",
        "部门树": "dept-tree", "树形选择": "tree-select", "级联": "cascader",
        "数据表格": "data-table", "看板": "kanban", "弹窗选择": "popup-select",
        "人员选择": "person-select", "水印": "watermark", "倒计时": "countdown",
        "步骤条": "steps", "时间轴": "timeline", "轮播": "carousel",
        "地图选点": "map-picker", "地图": "map-view",
        "供应商管理": "supplier-mgmt", "采购管理": "purchase-mgmt",
        "客户管理": "customer-mgmt", "工单管理": "work-order-mgmt",
        "派工管理": "dispatch-mgmt", "智能派工": "smart-dispatch",
        "订单管理": "order-mgmt", "库存管理": "inventory-mgmt",
        "考勤管理": "attendance-mgmt", "设备管理": "device-mgmt",
        "项目管理": "project-mgmt", "任务管理": "task-mgmt",
        "合同管理": "contract-mgmt", "费用管理": "expense-mgmt",
        "预算管理": "budget-mgmt", "报表": "report", "仪表盘": "dashboard",
        "布局": "app-layout", "登录页": "login-page",
    }

    def _slugify(text: str) -> str:
        s = (text or "").strip().lower()
        s = s.replace("&", "and")
        s = re.sub(r"[^a-z0-9\s-]", "-", s)
        s = re.sub(r"[\s_]+", "-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        s = re.sub(r"^[^a-z]+", "", s)
        return s[:48].strip("-")

    _INVALID = {"custom", "custom-dev", "component", "page", "module", "widget", ""}

    async def _llm_to_slug(text: str) -> str:
        if not text or not text.strip():
            return ""
        try:
            llm = LLMClient()
            resp = await llm.chat_completion([
                {
                    "role": "system",
                    "content": (
                        "根据用户描述，提取核心功能名称并转换为简短的英文 kebab-case 项目名（2-4段）。"
                        "例如：'国际手机号输入' → 'intl-phone-input'，'评分组件' → 'star-rating'，'供应商管理页面' → 'supplier-mgmt'。"
                        "只返回 kebab-case 名称本身，不要任何解释或标点。"
                    ),
                },
                {"role": "user", "content": text.strip()},
            ], max_tokens=40)
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            match = re.search(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\b", content.lower())
            slug = _slugify(match.group(1)) if match else ""
            return slug if slug not in _INVALID else ""
        except Exception as e:
            logger.warning(f"LLM 提取项目名失败: {e}")
            return ""

    msg = (message or "").strip()
    msg_lower = msg.lower()

    # 1. 消息中已经包含英文 kebab-case（用户直接写了名字）
    explicit = re.search(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b", msg_lower)
    if explicit and explicit.group(1) not in _INVALID:
        return explicit.group(1)

    # 2. 关键字缓存快速命中（按长度降序，优先匹配更长的词）
    for kw, slug in sorted(_KEYWORD_CACHE.items(), key=lambda x: len(x[0]), reverse=True):
        if kw in msg:
            return slug

    # 3. LLM 直接从完整消息提取（主要路径）
    slug = await _llm_to_slug(msg)
    if slug:
        return slug

    # 4. 兜底：随机短码，保证唯一性，不使用有误导性的固定名称
    return f"component-{uuid.uuid4().hex[:6]}"


def _extract_display_name(message: str, project_type: str, fallback_name: str) -> str:
    """提取适合在工作区列表中展示的名称"""
    import re

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
        '',
        display_name,
    ).strip("，。,.!！?？：: ")

    suffix_map = {
        "form-component-dual": "组件",
        "form-page": "页面",
        "menu-page": "页面",
        "mobile-page": "页面",
        "form-list": "列表",
        "layout": "布局",
        "plugin": "插件",
        "backend-api": "接口",
    }
    suffix = suffix_map.get(project_type, "")
    if suffix and not any(token in display_name for token in ("组件", "页面", "选择器", "弹窗", "布局", "插件", "接口", "模块", "登录页")):
        display_name = f"{display_name}{suffix}"

    return (display_name or fallback_name)[:48]


async def _is_new_component_intent(generator: CodingGenerator, message: str, ws_id: str, ws_mgr: WorkspaceManager) -> bool:
    """判断用户消息是要修改当前组件还是做一个全新的组件"""
    import re

    # 快速关键词判断（不调 LLM）
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

    # 都有或都没有，用 LLM 判断
    try:
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
