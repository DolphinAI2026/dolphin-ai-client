"""
Coding API 路由 - aPaaS Vibe Coding 接口
"""

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Annotated, AsyncIterator, Any
from urllib.parse import urlencode, urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Header, Response
from fastapi.responses import StreamingResponse, JSONResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.crypto import decrypt_password
from app.database import get_db
from app.models import User, Conversation, Message, Project, LLMConfig
from app.deps import get_auth_context, AuthContext
from app.coding.scenes import SceneType, get_scene, get_all_scenes, get_scenes_by_category
from app.coding.generator import CodingGenerator, parse_files_from_response, CodeGenerationResult
from app.coding.templates import get_project_template
from app.coding.prompts import get_scene_prompt, AGENT_SYSTEM_PROMPT
from app.coding.workspace import WorkspaceManager, ProjectType
from app.llm_client import LLMClient
from app.apaas_client import APaaSClient
from app.config import settings
from app.coding.verifier import ComponentVerifier
from app.routes.llm_configs import list_llm_configs_for_purpose

try:
    from app.coding.vibe_agent import VibeCodingAgent
    _VIBE_AGENT_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    if exc.name == "claude_agent_sdk":
        VibeCodingAgent = None
        _VIBE_AGENT_IMPORT_ERROR = exc
    else:
        raise

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


def _ensure_vibe_workspace_file(ws_path: Path) -> Path:
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


def _derive_harness_api_base(api_base: str) -> str:
    """把 coding IDE API base 映射成 harness IDE API base。"""
    return (api_base or "").replace("/api/coding/", "/api/harness/coding/")


def _infer_public_builder_prefix(request: Request) -> str:
    forwarded_prefix = (request.headers.get("x-forwarded-prefix") or "").strip()
    if forwarded_prefix:
        return forwarded_prefix.rstrip("/")

    code_server_base = (settings.code_server_base_url or "").rstrip("/")
    if not code_server_base:
        return ""

    parsed = urlparse(code_server_base)
    code_server_path = (parsed.path or "").rstrip("/")
    if code_server_path.endswith("/ide"):
        return code_server_path[:-4]
    return ""


def _build_ide_proxy_api_base(request: Request, ws_id: str) -> str:
    """为 code-server 场景优先生成同源代理地址，避免浏览器被 CSP 拦截直连后端。"""
    public_base = _build_public_api_base(request)
    public_prefix = _infer_public_builder_prefix(request)
    code_server_base = (settings.code_server_base_url or "").rstrip("/")
    if not code_server_base:
        return f"{public_base}{public_prefix}/api/coding/workspace/{ws_id}/ide"

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
    return settings.llm_model


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

class GenerateRequest(BaseModel):
    """代码生成请求"""
    scene_type: Optional[str] = None  # 场景类型，为空则自动识别
    requirement: str                   # 用户需求描述
    conversation_id: Optional[int] = None  # 关联的对话ID
    app_id: Optional[str] = None      # 关联的aPaaS应用ID（来自builder）
    module_name: Optional[str] = None  # 模块名称


class DetectSceneRequest(BaseModel):
    """场景识别请求"""
    requirement: str


class TemplateRequest(BaseModel):
    """模板生成请求"""
    scene_type: str
    module_name: str


class CodingChatRequest(BaseModel):
    """Coding对话请求（流式）"""
    scene_type: Optional[str] = None
    message: str
    conversation_id: Optional[int] = None
    app_id: Optional[str] = None
    workspace_id: Optional[str] = None  # 关联的工作区ID


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


class AutoPipelineRequest(BaseModel):
    """自动化 Pipeline 请求（对话式开发）"""
    message: str                           # 用户需求描述
    workspace_id: Optional[str] = None     # 已有工作区（迭代修改）
    conversation_id: Optional[int] = None  # 已有对话
    selected_model: Optional[str] = None   # 当前会话选中的 coding 模型（llmcfg:<id>）
    app_id: Optional[str] = None           # aPaaS 应用ID (deprecated, use project_id)
    project_id: Optional[int] = None       # 关联项目ID（优先使用项目的平台配置）
    project_type: Optional[str] = None     # 前端指定的项目类型（menu-page 等）
    quick_create: bool = False             # 快速模式：只创建工作区+脚手架，跳过 agent/install/serve


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


@router.post("/detect-scene")
async def detect_scene(
    req: DetectSceneRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """根据用户需求自动识别开发场景"""
    generator = CodingGenerator()
    scene_type = await generator.detect_scene(req.requirement)
    scene_info = get_scene(scene_type)
    return {
        "scene_type": scene_type.value,
        "scene_name": scene_info.name,
        "scene_description": scene_info.description,
        "conventions": scene_info.required_conventions,
    }


# ============================================================
# 模板相关接口
# ============================================================

@router.post("/template")
async def generate_template(
    req: TemplateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """生成项目模板骨架"""
    try:
        scene_type = SceneType(req.scene_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支持的场景类型: {req.scene_type}")

    files = get_project_template(scene_type, req.module_name)
    return {
        "scene_type": req.scene_type,
        "module_name": req.module_name,
        "files": [
            {"path": path, "content": content}
            for path, content in files.items()
        ],
    }


# ============================================================
# 代码生成接口
# ============================================================

@router.post("/generate")
async def generate_code(
    req: GenerateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """非流式代码生成"""
    user = ctx.user
    generator = CodingGenerator()

    # 确定场景类型
    if req.scene_type:
        try:
            scene_type = SceneType(req.scene_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"不支持的场景类型: {req.scene_type}")
    else:
        scene_type = await generator.detect_scene(req.requirement)

    # 获取对话历史
    history = []
    if req.conversation_id:
        history = await _get_conversation_history(db, req.conversation_id)

    # 获取应用上下文（如果关联了builder应用）
    app_context = None
    if req.app_id and user.apaas_token:
        app_context = await _get_app_context(user, req.app_id)

    # 生成代码
    result = await generator.generate(
        scene_type=scene_type,
        user_requirement=req.requirement,
        conversation_history=history,
        app_context=app_context,
    )

    # 保存到对话
    if req.conversation_id:
        await _save_coding_message(db, req.conversation_id, "user", req.requirement)
        assistant_content = json.dumps(result.to_dict(), ensure_ascii=False)
        await _save_coding_message(db, req.conversation_id, "assistant", assistant_content)

    return result.to_dict()


@router.post("/generate-stream")
async def generate_code_stream(
    req: CodingChatRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """流式代码生成（SSE）"""
    user = ctx.user
    generator = CodingGenerator()

    # 确定场景类型
    if req.scene_type:
        try:
            scene_type = SceneType(req.scene_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"不支持的场景类型: {req.scene_type}")
    else:
        scene_type = await generator.detect_scene(req.message)

    # 获取对话历史
    history = []
    if req.conversation_id:
        history = await _get_conversation_history(db, req.conversation_id)

    # 获取应用上下文
    app_context = None
    if req.app_id and user.apaas_token:
        app_context = await _get_app_context(user, req.app_id)

    # 获取工作区上下文
    workspace_context = None
    if req.workspace_id:
        workspace_context = _build_workspace_context(req.workspace_id)

    # 创建或获取对话
    conversation_id = req.conversation_id
    if not conversation_id:
        conv = Conversation(
            title=req.message[:50],
            user_id=user.id,
            tenant_id=ctx.tenant_id,
            agent_type="coding",
            workspace_id=req.workspace_id,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conversation_id = conv.id

    # 保存用户消息
    await _save_coding_message(db, conversation_id, "user", req.message)

    async def event_generator():
        full_response = ""
        # 先发送场景信息
        yield json.dumps({
            "type": "scene_detected",
            "scene_type": scene_type.value,
            "scene_name": get_scene(scene_type).name,
            "conversation_id": conversation_id,
        }, ensure_ascii=False)

        # 流式输出代码
        async for chunk in generator.generate_stream(
            scene_type=scene_type,
            user_requirement=req.message,
            conversation_history=history,
            app_context=app_context,
            workspace_context=workspace_context,
        ):
            full_response += chunk
            yield json.dumps({
                "type": "content",
                "content": chunk,
            }, ensure_ascii=False)

        # 保存助手回复
        await _save_coding_message(db, conversation_id, "assistant", full_response)

        yield json.dumps({
            "type": "done",
            "conversation_id": conversation_id,
        }, ensure_ascii=False)

    return _event_stream_response(event_generator())


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
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]


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


@router.post("/workspace/create")
async def create_workspace(
    req: CreateWorkspaceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """创建新工作区（脚手架初始化）"""
    try:
        project_type = ProjectType(req.project_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的项目类型: {req.project_type}，可选: {[t.value for t in ProjectType]}"
        )

    meta = workspace_mgr.create_workspace(
        project_type=project_type,
        project_name=req.project_name,
        display_name=req.display_name,
        user_id=ctx.user.id,
        project_id=req.project_id,
    )
    meta["files"] = workspace_mgr.list_files(meta["id"])
    return meta


@router.post("/workspace/{ws_id}/install")
async def install_workspace_deps(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """安装工作区依赖（npm install）"""
    try:
        result = await workspace_mgr.install_deps(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.post("/workspace/{ws_id}/build")
async def build_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """构建工作区项目"""
    try:
        result = await workspace_mgr.build_project(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/download")
async def download_workspace_zip(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    type: str = Query(default="dist", description="下载类型: dist=构建产物, src=源代码"),
):
    """下载工作区打包文件（zip）"""
    import zipfile
    import io
    from fastapi.responses import StreamingResponse

    try:
        info = workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")

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
):
    """获取工作区信息"""
    try:
        return workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/ide-url")
async def get_workspace_ide_url(
    ws_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    conversation_id: Optional[int] = Query(default=None, description="可选，会话ID，用于把上下文带入 Vibe IDE"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """获取工作区的 Web IDE (code-server) URL"""
    base_url = settings.code_server_base_url
    if not base_url:
        raise HTTPException(status_code=501, detail="Web IDE 未配置，请在 .env 中设置 CODE_SERVER_BASE_URL")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")

    effective_conversation_id = conversation_id
    effective_conversation: Optional[Conversation] = None
    if db is not None:
        if effective_conversation_id is None:
            stmt = (
                select(Conversation)
                .where(
                    Conversation.user_id == ctx.user.id,
                    Conversation.tenant_id == ctx.tenant_id,
                    Conversation.workspace_id == ws_id,
                    Conversation.agent_type == "coding",
                )
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )
        else:
            stmt = (
                select(Conversation)
                .where(
                    Conversation.id == effective_conversation_id,
                    Conversation.user_id == ctx.user.id,
                    Conversation.tenant_id == ctx.tenant_id,
                    Conversation.workspace_id == ws_id,
                    Conversation.agent_type == "coding",
                )
                .limit(1)
            )
        result = await db.execute(stmt)
        effective_conversation = result.scalar_one_or_none()
        if effective_conversation:
            effective_conversation_id = effective_conversation.id
        else:
            effective_conversation_id = None

    _ensure_vibe_workspace_file(ws_path)  # 仍然生成 workspace 文件（保留 exclude 配置）
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
    project_type: Optional[str] = None
    quick_create: bool = False


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


@router.get("/skills")
async def list_skills(
    keyword: str = Query(default=""),
    skill_type: Optional[str] = Query(default=None),
):
    """列出可用技能（Skills 2.0）。"""
    from app.coding.skills_v2 import SkillRegistry, SkillType

    registry = SkillRegistry.get_instance()
    st = SkillType(skill_type) if skill_type else None
    results = registry.query(keyword=keyword, skill_type=st)
    return {"skills": [s.model_dump() for s in results]}


@router.post("/skills/{skill_name}/execute")
async def execute_skill(
    skill_name: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """执行一个 Skill 的 action。"""
    from app.coding.skills_v2 import SkillRegistry

    registry = SkillRegistry.get_instance()
    skill = registry.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    if not skill.actions:
        raise HTTPException(status_code=400, detail=f"Skill '{skill_name}' has no executable actions")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    action_name = payload.get("action", skill.actions[0].name)
    action = next((a for a in skill.actions if a.name == action_name), None)
    if not action:
        raise HTTPException(status_code=400, detail=f"Action '{action_name}' not found in skill '{skill_name}'")

    # Dynamic import and call
    try:
        module_path, func_name = action.entry.rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)

        args = payload.get("args", {})
        result = await func(**args) if args else await func()
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"Skill execution failed: {skill_name}.{action_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        project_type=req.project_type,
        quick_create=req.quick_create,
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

    if tenant_config:
        payload["model"] = tenant_config.model
        upstream_url = _build_chat_completions_url(tenant_config.base_url)
        api_key = decrypt_password(tenant_config.api_key_enc)
    else:
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
):
    """列出工作区文件"""
    try:
        return workspace_mgr.list_files(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/file")
async def read_workspace_file(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """读取工作区文件内容"""
    try:
        content = workspace_mgr.read_file(ws_id, file_path)
        return {"path": file_path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/workspace/{ws_id}/file")
async def write_workspace_file(
    ws_id: str,
    req: WriteFileRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """写入文件到工作区"""
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
):
    """列出当前用户的所有工作区"""
    return workspace_mgr.list_user_workspaces(ctx.user.id)


@router.get("/workspace/{ws_id}/conversation")
async def get_workspace_conversation(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取工作区关联的对话及消息"""
    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.workspace_id == ws_id,
            Conversation.agent_type == "coding",
        )
        .order_by(Conversation.updated_at.desc())
        .limit(10)
    )
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
):
    """删除工作区"""
    workspace_mgr.delete_workspace(ws_id)
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


async def _save_coding_message(
    db: AsyncSession, conversation_id: int, role: str, content: str
):
    """保存对话消息"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
    )
    db.add(msg)
    await db.commit()


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


def _build_workspace_context(ws_id: str) -> dict:
    """构建工作区上下文，用于告知 AI 现有文件结构和关键文件内容"""
    try:
        info = workspace_mgr.get_workspace_info(ws_id)
        files = info.get("files", [])
        project_type = (info.get("project_type", "") or "").lower()
        rule_files = [
            fp for fp in files
            if fp.startswith(".cursor/rules/") and fp.endswith(".mdc")
        ]

        # 按项目类型挑选关键文件，避免把表单组件规则错误带到布局/后端项目
        if project_type in {"form-component", "mobile-component"}:
            key_extensions = ('.vue', '.widget.config.js', '.editor.config.js')
            key_names = ('apaas.json', 'form-widget.mixin.js')
        elif project_type == "form-list":
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'index.js')
        elif project_type == "plugin":
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'admin.js', 'app.js', 'mobile.js', 'extension.js', 'tab-config.js')
        elif project_type == "layout":
            key_extensions = ('.vue',)
            key_names = ('apaas.json', 'index.js')
        elif project_type in {"menu-page", "form-page", "mobile-page"}:
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'index.js')
        elif project_type in {"backend-api", "backend-feign", "backend-scheduled"}:
            key_extensions = ('.java', '.xml', '.yml', '.yaml', '.properties', '.md')
            key_names = ('pom.xml', 'application.yml', 'application.yaml', 'application.properties')
        else:
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'index.js')

        key_file_paths = list(rule_files)
        for fp in files:
            basename = fp.split('/')[-1] if '/' in fp else fp
            if fp in key_file_paths:
                continue
            if any(fp.endswith(ext) for ext in key_extensions):
                key_file_paths.append(fp)
            elif basename in key_names:
                key_file_paths.append(fp)

        key_files = {}
        for fp in key_file_paths:
            try:
                content = workspace_mgr.read_file(ws_id, fp)
                # 跳过过大的文件（如 mixin > 800行），只传摘要
                lines = content.split('\n')
                if len(lines) > 300:
                    # 对于大文件只传前50行 + 最后20行
                    content = '\n'.join(lines[:50]) + '\n// ... (省略中间部分) ...\n' + '\n'.join(lines[-20:])
                key_files[fp] = content
            except Exception:
                pass

        return {
            "workspace_id": ws_id,
            "project_name": info.get("project_name", ""),
            "project_type": info.get("project_type", ""),
            "files": files,
            "key_files": key_files,
        }
    except Exception as e:
        logger.warning(f"构建工作区上下文失败: {e}")
        return None


async def _get_app_context(user: User, app_id: str) -> dict:
    """从aPaaS平台获取应用上下文（模型、字典等）"""
    try:
        client = APaaSClient(
            tenant_id=user.apaas_tenant_id,
            token=user.apaas_token,
        )
        models = await client.query_models(app_id)
        dicts = await client.query_dicts(app_id)
        menus = await client.query_menus(app_id)

        return {
            "app_id": app_id,
            "models": [
                {
                    "name": m.get("modelName"),
                    "code": m.get("modelCode"),
                    "fields": [
                        {"name": f.get("fieldName"), "code": f.get("fieldCode"), "type": f.get("fieldType")}
                        for f in m.get("fields", m.get("dataModelFields", []))
                    ],
                }
                for m in models
            ],
            "dicts": [
                {"name": d.get("dictionaryName"), "code": d.get("dictionaryCode")}
                for d in dicts
            ],
            "menus": [
                {"name": m.get("menuName"), "id": m.get("id")}
                for m in menus
            ],
        }
    except Exception as e:
        logger.warning(f"获取应用上下文失败: {e}")
        return None


# ============================================================
# 文件上传接口
# ============================================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    workspace_id: Optional[str] = Query(None),
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
        ws_mgr_temp = WorkspaceManager()
        try:
            ws_info = ws_mgr_temp.get_workspace_info(workspace_id)
            save_dir = os.path.join(ws_info["path"], "uploads")
        except Exception:
            save_dir = os.path.join(tempfile.gettempdir(), "coding_uploads")
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
# 打包 & 下载接口
# ============================================================

@router.post("/workspace/{ws_id}/build")
async def build_workspace(
    ws_id: str,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
):
    """在工作区执行 mvn clean package 打包"""
    import subprocess

    ws_mgr_temp = WorkspaceManager()
    try:
        ws_info = ws_mgr_temp.get_workspace_info(ws_id)
        ws_path = ws_info["path"]
    except Exception:
        raise HTTPException(status_code=404, detail="工作区不存在")

    pom_path = os.path.join(ws_path, "pom.xml")
    if not os.path.exists(pom_path):
        raise HTTPException(status_code=400, detail="工作区没有 pom.xml，无法打包")

    try:
        result = subprocess.run(
            ["mvn", "clean", "package", "-DskipTests", "-q"],
            cwd=ws_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr[-2000:] if result.stderr else "Unknown build error",
                "output": result.stdout[-1000:] if result.stdout else "",
            }

        # Find the built JAR/WAR
        target_dir = os.path.join(ws_path, "target")
        artifacts = []
        if os.path.isdir(target_dir):
            for f in os.listdir(target_dir):
                if f.endswith((".jar", ".war")) and not f.endswith("-sources.jar"):
                    fp = os.path.join(target_dir, f)
                    artifacts.append({
                        "filename": f,
                        "path": fp,
                        "size": os.path.getsize(fp),
                    })

        return {
            "success": True,
            "artifacts": artifacts,
            "output": result.stdout[-500:] if result.stdout else "Build successful",
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="打包超时（5分钟），请检查项目配置")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打包失败: {e}")


@router.get("/workspace/{ws_id}/download")
async def download_artifact(
    ws_id: str,
    filename: str = Query(..., description="要下载的文件名"),
):
    """下载工作区中的打包产物"""
    from fastapi.responses import FileResponse

    ws_mgr_temp = WorkspaceManager()
    try:
        ws_info = ws_mgr_temp.get_workspace_info(ws_id)
        ws_path = ws_info["path"]
    except Exception:
        raise HTTPException(status_code=404, detail="工作区不存在")

    # 安全检查：只允许下载 target/ 目录下的文件
    safe_name = os.path.basename(filename)
    file_path = os.path.join(ws_path, "target", safe_name)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")

    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type="application/octet-stream",
    )


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
        project_type=req.project_type,
        quick_create=req.quick_create,
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
    action: str = Query(default="start", description="start 或 stop"),
):
    """启动或停止工作区的 serve 进程"""
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
):
    """查询 serve 运行状态"""
    ws_mgr = WorkspaceManager()
    return ws_mgr.is_serve_running(ws_id)



@router.post("/workspace/{ws_id}/publish")
async def publish_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """构建 + 打包 zip（一键发布）"""
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
    "form-component": "FRONTCOMPONENT",
    "menu-page": "FRONTENGINE",
    "form-page": "FRONTENGINE",
    "form-list": "FRONTLISTVIEW",
    "layout": "FRONTLAYOUT",
    "mobile-page": "MFRONTENGINE",
    "mobile-component": "MFRONTCOMPONENT",
    "plugin": "FRONTTENANTCOMPONENT",
    "backend-api": "BACKENDENGINE",
    "backend-feign": "BACKENDENGINE",
    "backend-scheduled": "BACKENDENGINE",
}


class UploadToPlatformRequest(BaseModel):
    env_id: int


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
    try:
        zip_path = await ws_mgr.build_and_package(ws_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构建失败: {e}")

    # 3. 读取 workspace 元信息（project_type、display_name）
    ws_path = ws_mgr.get_workspace_path(ws_id)
    meta = ws_mgr._read_meta(ws_path)
    project_type = meta.get("project_type", "")
    display_name = meta.get("display_name") or meta.get("project_name", ws_id)
    file_type = _PROJECT_TYPE_TO_FILE_TYPE.get(project_type)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"不支持上传的项目类型: {project_type}")

    # 4. 上传到平台（token 过期时自动刷新后重试一次）
    upload_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"

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

    async def _do_upload(token: str):
        with open(upload_file_path, "rb") as f:
            file_bytes = f.read()
        async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
            return await http.post(
                upload_url,
                headers={
                    "xdaptenantid": env.platform_tenant_id,
                    "xdaptoken": token,
                    "xdaptimestamp": str(int(time.time() * 1000)),
                },
                files={"file": (upload_file_path.name, file_bytes, upload_content_type)},
                data={
                    "fileType": file_type,
                    "description": f"{display_name} - 由 apaas-builder 上传",
                    "uploadId": str(int(time.time() * 1000)),
                    "versionCode": uuid.uuid4().hex,
                    "useScope": "全部应用",
                    "internalResource": "false",
                    "effectiveScope": "SINGLE_APPLICATION",
                },
            )

    try:
        response = await _do_upload(env.token)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"上传请求失败: {e}")

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
        try:
            response = await _do_upload(new_token)
            resp_data = response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"上传请求失败: {e}")
        except Exception:
            raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

    code = resp_data.get("code")
    if code == "ok" or code == 200:
        return {"status": "ok", "message": "上传成功"}
    else:
        msg = resp_data.get("message") or resp_data.get("msg") or "上传失败"
        raise HTTPException(status_code=500, detail=msg)


@router.get("/workspace/{ws_id}/debug/screenshot/{filename}")
async def get_debug_screenshot(ws_id: str, filename: str):
    """Serve debug screenshot image"""
    import re
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
        ws_info_meta = ws_mgr.get_workspace_info(ws_id)
        _project_id = ws_info_meta.get("project_id")
    if _project_id:
        result = await db.execute(
            select(Project).where(Project.id == _project_id, Project.user_id == user.id)
        )
        project = result.scalar_one_or_none()

    if project and project.platform_url:
        _platform_url = req.platform_url or _get_platform_frontend_url(project.platform_url)
        _tenant_id = req.tenant_id or project.platform_tenant_id or settings.apaas_tenant_id
        _app_id = req.app_id or project.platform_app_id or "806997227284201472"
    else:
        _platform_url = req.platform_url or _get_user_platform_url(user)
        _tenant_id = req.tenant_id or user.apaas_tenant_id or settings.apaas_tenant_id
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
    return base + "platform/" if base else "https://apaas-dev8.dfy.definesys.cn/platform/"


def _get_user_platform_url(user) -> str:
    """从用户的平台连接信息推导出平台前端 URL"""
    base = user.apaas_base_url or settings.apaas_base_url or ""
    # apaas_base_url 通常是后端地址如 https://apaas-dev8.dfy.definesys.cn/backend
    # 平台前端地址是 https://apaas-dev8.dfy.definesys.cn/platform/
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else "https://apaas-dev8.dfy.definesys.cn/platform/"


def _sse(data: dict) -> str:
    """SSE 事件格式化"""
    return json.dumps(data, ensure_ascii=False)


def _append_agent_event_to_history(history_parts: list[str], event: dict[str, Any]):
    """将 Agent 的关键执行输出整理成可持久化的文本记录。"""
    event_type = event.get("type")

    if event_type == "content":
        content = event.get("content")
        if isinstance(content, str) and content:
            history_parts.append(content)
        return

    if event_type == "agent_tool":
        tool_name = event.get("tool_display") or event.get("tool") or "工具"
        preview = event.get("input_preview") or ""
        if preview:
            history_parts.append(f"\n🔧 **{tool_name}** `{preview}`\n")
        else:
            history_parts.append(f"\n🔧 **{tool_name}**\n")
        return

    if event_type == "agent_result":
        preview = event.get("output_preview")
        if event.get("is_error"):
            history_parts.append(f"> ❌ {preview or '执行失败'}\n\n")
        elif isinstance(preview, str) and preview and preview != "(empty)":
            clipped = preview[:300] + "..." if len(preview) > 300 else preview
            history_parts.append(f"> ✅ {clipped}\n\n")
        else:
            history_parts.append("> ✅ 完成\n\n")
        return

    if event_type == "agent_command_output":
        chunk = event.get("chunk")
        if isinstance(chunk, str) and chunk:
            history_parts.append(chunk)
        return

    if event_type == "agent_done":
        turns = event.get("num_turns") or "?"
        history_parts.append(f"\n---\n✨ **Agent 完成** ({turns} 轮对话)\n")
        return

    if event_type == "agent_error":
        message = event.get("message") or "发生未知错误"
        history_parts.append(f"\n❌ **Agent 错误**: {message}\n")


def _scene_to_project_type(scene_type: SceneType) -> str:
    """场景类型转项目类型"""
    mapping = {
        SceneType.WEB_COMPONENT: "form-component",
        SceneType.WEB_PAGE: "form-page",
        SceneType.WEB_LIST_VIEW: "form-list",
        SceneType.WEB_LAYOUT: "layout",
        SceneType.WEB_PLUGIN: "plugin",
        SceneType.BACKEND_API: "backend-api",
        SceneType.MOBILE_COMPONENT: "mobile-component",
        SceneType.MOBILE_PAGE: "mobile-page",
        SceneType.SCRIPT_JS: "script",
        SceneType.SCRIPT_PYTHON: "script",
        SceneType.SCRIPT_GROOVY: "script",
        SceneType.BUSINESS_DIALOG: "script",
        SceneType.WEB_LOGIN: "web-login",
        SceneType.UI_STYLE: "ui-style",
        SceneType.LIST_CUSTOM_MODULE: "list-custom-module",
    }
    return mapping.get(scene_type, "form-component")


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
        "form-component": "组件",
        "mobile-component": "组件",
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


# ========== 组件预览 ==========

from fastapi.responses import HTMLResponse, FileResponse as StaticFileResponse
from app.coding.preview import generate_preview_html


@router.post("/workspace/{ws_id}/preview")
async def preview_workspace(ws_id: str):
    """触发构建（如需）并返回预览 URL"""
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 按需构建
    ws_mgr = WorkspaceManager()
    build_result = await ws_mgr.build_if_needed(ws_id)
    if build_result.get("status") == "error":
        raise HTTPException(status_code=500, detail=f"构建失败: {build_result.get('message', '')}")

    # 读取 apaas.json
    apaas_json_path = ws_path / "src" / "apaas.json"
    apaas_config = {}
    if apaas_json_path.exists():
        with open(apaas_json_path, "r", encoding="utf-8") as f:
            apaas_config = json.load(f)

    workspace_meta = {}
    workspace_meta_path = ws_path / ".workspace.json"
    if workspace_meta_path.exists():
        with open(workspace_meta_path, "r", encoding="utf-8") as f:
            workspace_meta = json.load(f)
    output_name = apaas_config.get("outputName") or workspace_meta.get("project_name") or ws_id
    template_type = apaas_config.get("templateType", "FORM_COMPONENT")
    project_type = workspace_meta.get("project_type", "")

    return {
        "status": "ok",
        "preview_url": f"/api/coding/workspace/{ws_id}/preview/sandbox",
        "output_name": output_name,
        "template_type": template_type,
        "project_type": project_type,
        "build_message": build_result.get("message", ""),
    }


@router.get("/workspace/{ws_id}/preview/sandbox")
async def preview_sandbox(ws_id: str):
    """返回预览沙箱 HTML 页面"""
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 读取 apaas.json
    apaas_json_path = ws_path / "src" / "apaas.json"
    apaas_config = {}
    if apaas_json_path.exists():
        with open(apaas_json_path, "r", encoding="utf-8") as f:
            apaas_config = json.load(f)

    workspace_meta = {}
    workspace_meta_path = ws_path / ".workspace.json"
    if workspace_meta_path.exists():
        with open(workspace_meta_path, "r", encoding="utf-8") as f:
            workspace_meta = json.load(f)
    output_name = apaas_config.get("outputName") or workspace_meta.get("project_name") or ws_id
    template_type = apaas_config.get("templateType", "FORM_COMPONENT")
    project_type = workspace_meta.get("project_type", "")
    dist_base_url = f"/api/coding/workspace/{ws_id}/preview/dist"

    html = generate_preview_html(
        template_type,
        apaas_config,
        dist_base_url,
        output_name,
        project_type=project_type,
    )
    return HTMLResponse(content=html)


@router.get("/workspace/{ws_id}/preview/dist/{filename:path}")
async def preview_dist_file(ws_id: str, filename: str):
    """静态服务预览构建产物目录下的文件"""
    output_dir = workspace_mgr.get_build_output_dir(ws_id)
    file_path = output_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # 安全检查：确保文件在构建产物目录下
    try:
        file_path.resolve().relative_to(output_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    # 确定 MIME 类型
    suffix = file_path.suffix.lower()
    media_types = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".map": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return StaticFileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )
