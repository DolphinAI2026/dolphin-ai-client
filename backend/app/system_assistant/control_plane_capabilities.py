"""Read and validate the tenant capability projection from Control Plane.

The loader deliberately builds a complete batch in local variables and swaps it
into the bounded in-memory cache only after every page passes the revision and
ETag barriers.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

import httpx

from app.builder_ai_management import _management_base_url
from app.config import settings
from app.system_assistant.telemetry import governance_telemetry

from .capability_projection import ProjectionCache, ProjectionCacheEntry

PAGE_SIZE_LIMIT = 200
TOTAL_TIMEOUT_SECONDS = 5.0
GET_RETRY_DELAY_SECONDS = 0.2
CAPABILITY_ENDPOINT = "/internal/builder-ai/system-assistant/capabilities"
remote_capability_cache = ProjectionCache(ttl_seconds=settings.system_assistant_projection_cache_seconds)


class ProjectionUnavailable(Exception):
    """Raised internally for a malformed or incomplete remote batch."""


@dataclass(frozen=True)
class ProjectionLoadResult:
    status: str
    items: list[dict[str, Any]] = field(default_factory=list)
    projection_revision: str | None = None
    etag: str | None = None
    reason: str | None = None
    request_sequence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def capabilities(self) -> list[dict[str, Any]]:
        return self.items

    @property
    def available(self) -> bool:
        return self.status in {"ready", "not_modified"}


GetPage = Callable[[int, Mapping[str, str]], Awaitable[Any] | Any]


def _field(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return default


def _headers(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        raw = value.get("headers") or {}
    else:
        raw = getattr(value, "headers", {}) or {}
    return {str(k).lower(): str(v) for k, v in dict(raw).items()}


def _status(value: Any) -> int:
    if isinstance(value, Mapping):
        return int(value.get("status", 200))
    return int(getattr(value, "status_code", 200))


def _body(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        body = value.get("body", value)
        if isinstance(body, Mapping):
            return body
        raise ProjectionUnavailable("response body is not an object")
    try:
        parsed = value.json()
    except Exception as error:  # pragma: no cover - httpx-specific guard
        raise ProjectionUnavailable("response body is not JSON") from error
    if not isinstance(parsed, Mapping):
        raise ProjectionUnavailable("response body is not an object")
    return parsed


class ControlPlaneCapabilityClient:
    """Paginated, barrier-checked Control Plane capability client."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        tenant_id: str | int | None = None,
        token: str | None = None,
        user: Any | None = None,
        get_page: GetPage | None = None,
        cache: ProjectionCache | None = None,
        timeout_seconds: float = TOTAL_TIMEOUT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = (base_url or _management_base_url()).rstrip("/")
        self.tenant_id = str(tenant_id) if tenant_id is not None else ""
        if token is None and user is not None:
            from app.code_runtime.auth import remote_builder_access_token

            token = remote_builder_access_token(user)
        self.token = token or ""
        self.get_page = get_page
        self.cache = cache or remote_capability_cache
        self.timeout_seconds = float(timeout_seconds)
        self._sleep = sleep

    async def _http_get(self, page: int, headers: Mapping[str, str], timeout: float) -> Any:
        params = {"profile": "system_assistant", "page": page, "pageSize": PAGE_SIZE_LIMIT}
        request_headers = dict(headers)
        request_headers.setdefault("Authorization", f"Bearer {self.token}")
        if self.tenant_id:
            request_headers.setdefault("X-Tenant-Id", self.tenant_id)
        request_headers.setdefault("X-Builder-Internal-Token-Id", settings.builder_ai_internal_current_token_id)
        request_headers.setdefault("X-Builder-Internal-Token", settings.builder_ai_internal_current_token)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            return await client.get(CAPABILITY_ENDPOINT, params=params, headers=request_headers)

    async def _get_with_retry(self, page: int, headers: Mapping[str, str], deadline: float) -> Any:
        last_error: Exception | None = None
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProjectionUnavailable("projection request timed out")
            try:
                response = self.get_page(page, headers) if self.get_page is not None else self._http_get(page, headers, remaining)
                if inspect.isawaitable(response):
                    response = await asyncio.wait_for(response, timeout=remaining)
                status = _status(response)
                if status < 500 or attempt:
                    return response
            except Exception as error:
                last_error = error
                if attempt:
                    raise ProjectionUnavailable("projection request failed") from error
            if deadline - time.monotonic() < GET_RETRY_DELAY_SECONDS:
                break
            await self._sleep(GET_RETRY_DELAY_SECONDS)
        raise ProjectionUnavailable("projection request failed") from last_error

    async def load(self, *, tenant_id: str | int | None = None, etag: str | None = None) -> ProjectionLoadResult:
        key = str(self.tenant_id if tenant_id is None else tenant_id)
        cached = self.cache.get_entry(key)
        requested_etag = etag or (cached.etag if cached else None)
        headers = {"If-None-Match": requested_etag} if requested_etag else {}
        deadline = time.monotonic() + self.timeout_seconds
        calls: list[dict[str, Any]] = []
        try:
            first = await self._get_with_retry(1, headers, deadline)
            first_status = _status(first)
            calls.append({"page": 1, "status": first_status, "if_none_match": requested_etag})
            first_headers = _headers(first)
            first_etag = first_headers.get("etag")
            if first_status == 304:
                if cached is None or not self.cache.is_fresh(key) or first_etag != cached.etag:
                    raise ProjectionUnavailable("304 without a fresh matching complete cache")
                governance_telemetry.record_projection("304")
                return ProjectionLoadResult("not_modified", list(cached.items), cached.revision, cached.etag, request_sequence=calls)
            if first_status != 200:
                raise ProjectionUnavailable(f"unexpected HTTP status {first_status}")

            body = _body(first)
            total = _field(body, "total")
            page_size = _field(body, "pageSize", "page_size")
            revision = _field(body, "projectionRevision", "projection_revision")
            if not isinstance(total, int) or total < 0 or not isinstance(page_size, int) or not 0 < page_size <= PAGE_SIZE_LIMIT:
                raise ProjectionUnavailable("invalid pagination metadata")
            if _field(body, "page") != 1 or not isinstance(revision, str) or not revision.strip():
                raise ProjectionUnavailable("invalid first page barrier")
            if first_etag != revision:
                raise ProjectionUnavailable("first page ETag drift")
            items = list(_field(body, "capabilities", "items", default=[]))
            seen_ids: set[str] = set()
            seen_codes: set[str] = set()
            self._validate_items(items, seen_ids, seen_codes)
            if len(items) > total:
                raise ProjectionUnavailable("page exceeds total")

            page = 2
            while len(items) < total:
                response = await self._get_with_retry(page, {}, deadline)
                status = _status(response)
                calls.append({"page": page, "status": status, "if_none_match": None})
                if status != 200:
                    raise ProjectionUnavailable("later page must be 200")
                response_headers = _headers(response)
                response_body = _body(response)
                if (
                    _field(response_body, "page") != page
                    or _field(response_body, "total") != total
                    or _field(response_body, "pageSize", "page_size") != page_size
                    or _field(response_body, "projectionRevision", "projection_revision") != revision
                    or response_headers.get("etag") != revision
                ):
                    raise ProjectionUnavailable("pagination barrier drift")
                page_items = list(_field(response_body, "capabilities", "items", default=[]))
                self._validate_items(page_items, seen_ids, seen_codes)
                if not page_items:
                    raise ProjectionUnavailable("incomplete empty page")
                items.extend(page_items)
                if len(items) > total:
                    raise ProjectionUnavailable("total drift")
                page += 1
            entry = ProjectionCacheEntry(items=items, revision=revision, etag=revision, stored_at=time.monotonic())
            self.cache.swap(key, entry)
            governance_telemetry.record_projection("success")
            return ProjectionLoadResult("ready", items, revision, revision, request_sequence=calls)
        except Exception as error:
            governance_telemetry.record_projection("failure")
            return ProjectionLoadResult("unavailable", reason=str(error), request_sequence=calls)

    @staticmethod
    def _validate_items(items: list[Any], ids: set[str], codes: set[str]) -> None:
        for item in items:
            if not isinstance(item, Mapping):
                raise ProjectionUnavailable("capability item is not an object")
            capability_id = _field(item, "capabilityId", "capability_id")
            code = _field(item, "code", "capabilityCode", "capability_code")
            if not capability_id or not code or str(capability_id) in ids or str(code) in codes:
                raise ProjectionUnavailable("duplicate or missing capability id/code")
            ids.add(str(capability_id))
            codes.add(str(code))


async def load_projection(**kwargs: Any) -> ProjectionLoadResult:
    """Convenience entrypoint for one complete tenant projection load."""
    return await ControlPlaneCapabilityClient(**kwargs).load()


fetch_capability_projection = load_projection


async def load_projection_if_enabled(policy: str, **kwargs: Any) -> ProjectionLoadResult | None:
    """Legacy keeps the phase-A path and never contacts Control Plane."""
    from .policy import validate_governance_policy

    mode = validate_governance_policy(policy)
    if mode == "legacy":
        return None
    return await load_projection(**kwargs)
