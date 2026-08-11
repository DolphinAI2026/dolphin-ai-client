from __future__ import annotations

import pytest

from app.system_assistant.control_plane_capabilities import ControlPlaneCapabilityClient
from app.system_assistant.capability_projection import ProjectionCache, ProjectionCacheEntry


def _page(items, *, page=1, total=None, revision="rev-1", etag=None, status=200):
    return {
        "status": status,
        "headers": {"ETag": etag or revision},
        "body": {
            "capabilities": items,
            "total": len(items) if total is None else total,
            "page": page,
            "pageSize": 200,
            "projectionRevision": revision,
        },
    }


def _capability(number: int, *, code=None, risk="L0"):
    return {
        "capabilityId": f"cap-{number}",
        "code": code or f"code.{number}",
        "objectVersionNumber": 1,
        "status": "ENABLED",
        "riskLevel": risk,
    }


@pytest.mark.asyncio
async def test_pagination_freezes_revision_and_sends_etag_only_on_first_page():
    calls = []

    async def get_page(page, headers):
        calls.append((page, dict(headers)))
        if page == 1:
            return _page([_capability(1)], total=2)
        return _page([_capability(2)], page=2, total=2)

    result = await ControlPlaneCapabilityClient(get_page=get_page).load()

    assert result.status == "ready"
    assert [page for page, _ in calls] == [1, 2]
    assert "If-None-Match" not in calls[0][1]
    assert "If-None-Match" not in calls[1][1]
    assert len(result.items) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_page",
    [
        _page([_capability(2)], page=2, total=3),
        {"status": 304, "headers": {}, "body": {}},
        _page([_capability(2)], page=2, total=2, revision="rev-2"),
        _page([_capability(2)], page=2, total=2, etag="wrong"),
    ],
)
async def test_any_later_page_barrier_failure_discards_entire_batch(bad_page):
    async def get_page(page, headers):
        if page == 1:
            return _page([_capability(1)], total=2)
        return bad_page

    result = await ControlPlaneCapabilityClient(get_page=get_page).load()

    assert result.status == "unavailable"
    assert result.items == []


@pytest.mark.asyncio
async def test_duplicate_capability_id_or_code_is_unavailable():
    async def get_page(_page_number, _headers):
        return _page([_capability(1), _capability(1, code="code.other")], total=2)

    result = await ControlPlaneCapabilityClient(get_page=get_page).load()

    assert result.status == "unavailable"


@pytest.mark.asyncio
async def test_capability_id_and_code_must_be_strings():
    async def get_page(_page_number, _headers):
        item = _capability(1)
        item["capabilityId"] = 1
        return _page([item], total=1)

    result = await ControlPlaneCapabilityClient(get_page=get_page).load()

    assert result.status == "unavailable"


@pytest.mark.asyncio
async def test_304_reuses_only_fresh_complete_cache_and_missing_cache_is_unavailable():
    calls = []

    async def first_get(page, headers):
        calls.append((page, headers))
        return _page([_capability(1)], total=1)

    client = ControlPlaneCapabilityClient(get_page=first_get)
    assert (await client.load()).status == "ready"

    async def not_modified(page, headers):
        calls.append((page, headers))
        return {"status": 304, "headers": {"ETag": "rev-1"}, "body": {}}

    client.get_page = not_modified
    result = await client.load()
    assert result.status == "not_modified"
    assert len(result.items) == 1

    uncached = ControlPlaneCapabilityClient(get_page=not_modified, cache=ProjectionCache())
    assert (await uncached.load()).status == "unavailable"


@pytest.mark.asyncio
async def test_explicit_etag_without_fresh_complete_cache_is_not_sent():
    calls = []

    async def get_page(page, headers):
        calls.append((page, headers))
        return _page([_capability(1)], total=1)

    result = await ControlPlaneCapabilityClient(get_page=get_page, cache=ProjectionCache()).load(
        etag="stale-etag"
    )

    assert result.status == "ready"
    assert calls[0][1] == {}


@pytest.mark.asyncio
async def test_expired_complete_cache_is_not_sent_or_reused_for_304(monkeypatch):
    cache = ProjectionCache()
    cache.swap(
        "tenant-1",
        ProjectionCacheEntry([_capability(1)], "rev-1", "rev-1", stored_at=-1000),
    )
    calls = []

    async def not_modified(page, headers):
        calls.append((page, headers))
        return {"status": 304, "headers": {"ETag": "rev-1"}, "body": {}}

    result = await ControlPlaneCapabilityClient(
        tenant_id="tenant-1", get_page=not_modified, cache=cache
    ).load()

    assert result.status == "unavailable"
    assert calls == [(1, {})]


@pytest.mark.asyncio
async def test_get_retries_once_after_server_error_with_fixed_delay():
    attempts = 0
    pauses = []

    async def get_page(_page_number, _headers):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"status": 503, "headers": {}, "body": {}}
        return _page([_capability(1)], total=1)

    async def sleep(delay):
        pauses.append(delay)

    result = await ControlPlaneCapabilityClient(get_page=get_page, sleep=sleep).load()

    assert result.status == "ready"
    assert attempts == 2
    assert pauses == [0.2]
