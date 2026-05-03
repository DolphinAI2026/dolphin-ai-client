from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.coding.preview_runtime import (
    LocalPreviewRuntime,
    PreviewRuntimeState,
    PreviewRuntimeStatus,
    detect_preview_project,
)
from app.deps import AuthContext, get_auth_context
from app.routes.online_coding import (
    ONLINE_CODING_ROOT,
    _find_workspace_dir,
    _is_repo_imported,
    _repo_path,
)

router = APIRouter(prefix="/online-coding", tags=["online-coding-runtime"])

_PREVIEW_RUNTIME: LocalPreviewRuntime | None = None
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _get_preview_runtime(request: Request) -> LocalPreviewRuntime:
    global _PREVIEW_RUNTIME
    api_base_url = _api_base_url(request)
    if _PREVIEW_RUNTIME is None:
        _PREVIEW_RUNTIME = LocalPreviewRuntime(
            api_base_url=api_base_url,
            runtime_root=ONLINE_CODING_ROOT / ".preview-runtime",
        )
    else:
        _PREVIEW_RUNTIME.api_base_url = api_base_url
    return _PREVIEW_RUNTIME


def _api_base_url(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/api"


def _preview_state_payload(state: PreviewRuntimeState) -> dict:
    payload = asdict(state)
    payload["status"] = state.status.value
    payload["working_dir"] = str(state.working_dir)
    payload["log_path"] = str(state.log_path) if state.log_path else None
    payload["started_at"] = state.started_at.isoformat() if state.started_at else None
    payload["updated_at"] = state.updated_at.isoformat() if state.updated_at else None
    return payload


def _detect_payload(workspace_id: str, repo_dir: Path) -> dict:
    detected = detect_preview_project(workspace_id, repo_dir)
    payload = asdict(detected)
    payload["status"] = detected.status.value
    payload["package_manager"] = detected.package_manager.value
    payload["workspace_path"] = str(detected.workspace_path)
    payload["working_dir"] = str(detected.working_dir)
    return payload


def _preview_proxy_prefix(workspace_id: str) -> str:
    encoded_workspace_id = quote(workspace_id, safe="")
    return f"/api/online-coding/workspaces/{encoded_workspace_id}/preview"


def _append_port_query(location: str, port: int) -> str:
    parsed = urlsplit(location)
    if not any(item.startswith("port=") for item in parsed.query.split("&")):
        query = f"{parsed.query}&port={port}" if parsed.query else f"port={port}"
    else:
        query = parsed.query
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _rewrite_preview_location(location: str | None, workspace_id: str, port: int) -> str | None:
    if not location or not location.startswith("/"):
        return location
    if location.startswith("/api/online-coding/"):
        return location
    rewritten = f"{_preview_proxy_prefix(workspace_id)}{location}"
    return _append_port_query(rewritten, port)


def _rewrite_preview_body(body: bytes, content_type: str, workspace_id: str, target_path: str) -> bytes:
    lowered = (content_type or "").lower()
    if not any(marker in lowered for marker in ("text/html", "javascript", "text/css")):
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    prefix = _preview_proxy_prefix(workspace_id)
    base_segment = target_path.split("/", 1)[0] if target_path else ""
    absolute_bases = [
        f"/{base_segment}/",
    ] if base_segment else []
    absolute_bases.extend(["/@vite/", "/@id/", "/src/", "/node_modules/", "/assets/"])

    for base in dict.fromkeys(absolute_bases):
        text = text.replace(f'"{base}', f'"{prefix}{base}')
        text = text.replace(f"'{base}", f"'{prefix}{base}")
        text = text.replace(f"({base}", f"({prefix}{base}")
        text = text.replace(f"url({base}", f"url({prefix}{base}")
    return text.encode("utf-8")


def _get_online_repo_for_user(workspace_id: str, ctx: AuthContext) -> tuple[Path, dict]:
    ws_dir, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")
    if not _is_repo_imported(meta):
        raise HTTPException(status_code=400, detail="仓库导入成功后才能启动预览")
    repo_dir = _repo_path(ws_dir)
    if not repo_dir.exists():
        raise HTTPException(status_code=404, detail="仓库目录不存在")
    return repo_dir, meta


@router.get("/workspaces/{workspace_id}/runtime/detect")
async def detect_online_coding_preview_runtime(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    repo_dir, _ = _get_online_repo_for_user(workspace_id, ctx)
    return _detect_payload(workspace_id, repo_dir)


@router.post("/workspaces/{workspace_id}/runtime/start")
async def start_online_coding_preview_runtime(
    workspace_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    repo_dir, _ = _get_online_repo_for_user(workspace_id, ctx)
    detected = detect_preview_project(workspace_id, repo_dir)
    state = await _get_preview_runtime(request).start(detected)
    return {
        "project": _detect_payload(workspace_id, repo_dir),
        "runtime": _preview_state_payload(state),
    }


@router.get("/workspaces/{workspace_id}/runtime/status")
async def get_online_coding_preview_runtime_status(
    workspace_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    _get_online_repo_for_user(workspace_id, ctx)
    state = _get_preview_runtime(request).status(workspace_id)
    return _preview_state_payload(state)


@router.post("/workspaces/{workspace_id}/runtime/stop")
async def stop_online_coding_preview_runtime(
    workspace_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    _get_online_repo_for_user(workspace_id, ctx)
    state = await _get_preview_runtime(request).stop(workspace_id)
    return _preview_state_payload(state)


@router.get("/workspaces/{workspace_id}/runtime/logs")
async def get_online_coding_preview_runtime_logs(
    workspace_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    max_bytes: int = Query(default=16_000, ge=1_000, le=120_000),
):
    _get_online_repo_for_user(workspace_id, ctx)
    logs = _get_preview_runtime(request).tail_logs(workspace_id, max_bytes=max_bytes)
    return {"workspace_id": workspace_id, "logs": logs}


@router.api_route(
    "/workspaces/{workspace_id}/preview",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@router.api_route(
    "/workspaces/{workspace_id}/preview/{preview_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_online_coding_preview(
    workspace_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    preview_path: str = "",
    port: Optional[int] = Query(default=None),
):
    """Proxy preview traffic to the local MVP runner.

    This is intentionally minimal for the internal process runner. The
    production Docker/K8s runner should replace this with a signed URL or
    ingress/subdomain based proxy.

    生产环境实际走 *.vibe-first.cn 子域反代到 sandbox 容器，不再用此端点；
    保留是为了本地 LocalPreviewRuntime 兼容。鉴权要求登录用户且为 workspace 所有者。
    """
    _get_online_repo_for_user(workspace_id, ctx)
    state = _get_preview_runtime(request).status(workspace_id)
    if state.status != PreviewRuntimeStatus.RUNNING or not state.port:
        raise HTTPException(status_code=404, detail="预览服务未运行")
    if port is not None and port != state.port:
        raise HTTPException(status_code=403, detail="预览端口与当前工作区不匹配")

    query_items = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "port"
    ]
    query = f"?{urlencode(query_items)}" if query_items else ""
    target_path = preview_path or ""
    target_url = f"http://127.0.0.1:{state.port}/{target_path}{query}"
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "host"
    }
    body = await request.body()

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        upstream = await client.request(
            request.method,
            target_url,
            headers=headers,
            content=body,
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
    }
    response_headers["location"] = (
        _rewrite_preview_location(response_headers.get("location"), workspace_id, state.port)
        or response_headers.get("location", "")
    )
    response_headers = {
        key: value
        for key, value in response_headers.items()
        if value and key.lower() != "content-length"
    }
    content_type = upstream.headers.get("content-type", "")
    body_content = _rewrite_preview_body(
        upstream.content,
        content_type,
        workspace_id,
        target_path,
    )
    return Response(
        content=body_content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=content_type,
    )
