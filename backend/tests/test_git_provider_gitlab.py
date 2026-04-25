"""Unit tests for GitLabProvider — mock httpx.AsyncClient via monkeypatch.

Verify that the provider issues the correct REST v4 calls without doing real network IO.
"""
from __future__ import annotations

import pytest

from app.git.provider import gitlab as gitlab_module
from app.git.provider.base import GitFile
from app.git.provider.gitlab import GitLabProvider


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | list | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Captures every `request` call so tests can assert on them."""

    # class-level so callers configure responses before the `with` block
    responses: list[_FakeResponse] = []
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method, url, **kwargs):
        type(self).calls.append({"method": method, "url": url, **kwargs})
        if not type(self).responses:
            return _FakeResponse(200, {})
        # pop next; if only one left, keep reusing it as default
        if len(type(self).responses) == 1:
            return type(self).responses[0]
        return type(self).responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    yield
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []


@pytest.fixture
def patched_httpx(monkeypatch):
    monkeypatch.setattr(gitlab_module.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_get_repo_returns_metadata(patched_httpx):
    patched_httpx.responses = [
        _FakeResponse(200, {"id": 42, "path_with_namespace": "acme/widgets"}),
    ]
    provider = GitLabProvider(host="https://gitlab.example.com", access_token="glpat-x")
    meta = await provider.get_repo("acme/widgets")
    assert meta == {"id": 42, "path_with_namespace": "acme/widgets"}
    # URL-encoded path
    assert patched_httpx.calls[0]["method"] == "GET"
    assert "acme%2Fwidgets" in patched_httpx.calls[0]["url"]
    assert patched_httpx.calls[0]["url"].startswith(
        "https://gitlab.example.com/api/v4/projects/"
    )
    # Auth header
    assert patched_httpx.calls[0]["headers"]["PRIVATE-TOKEN"] == "glpat-x"


@pytest.mark.asyncio
async def test_get_repo_returns_none_on_404(patched_httpx):
    patched_httpx.responses = [_FakeResponse(404, text="not found")]
    provider = GitLabProvider(host="https://gitlab.example.com", access_token="glpat-x")
    assert await provider.get_repo("nope/missing") is None


@pytest.mark.asyncio
async def test_create_repo_calls_namespace_lookup(patched_httpx):
    # 1st call: GET group lookup; 2nd call: POST /projects
    patched_httpx.responses = [
        _FakeResponse(200, {"id": 7, "name": "acme"}),
        _FakeResponse(201, {"path_with_namespace": "acme/widgets"}),
    ]
    provider = GitLabProvider(host="https://gitlab.com", access_token="t")
    full_path = await provider.create_repo(
        group_or_org="acme", name="widgets", description="hello",
    )
    assert full_path == "acme/widgets"
    assert len(patched_httpx.calls) == 2
    assert patched_httpx.calls[0]["method"] == "GET"
    assert "/groups/acme" in patched_httpx.calls[0]["url"]
    assert patched_httpx.calls[1]["method"] == "POST"
    assert patched_httpx.calls[1]["url"].endswith("/projects")
    body = patched_httpx.calls[1]["json"]
    assert body["name"] == "widgets"
    assert body["namespace_id"] == 7
    assert body["visibility"] == "private"
    assert body["default_branch"] == "main"


@pytest.mark.asyncio
async def test_commit_files_uses_commits_api(patched_httpx):
    # Sequence:
    # 1) GET branch (exists -> 200)
    # 2) GET file (exists -> 200, action=update)
    # 3) POST commits
    patched_httpx.responses = [
        _FakeResponse(200, {"name": "main"}),
        _FakeResponse(200, {"file_path": "a.txt"}),
        _FakeResponse(201, {"id": "abc123sha", "web_url": "https://gitlab.com/x/y/-/commit/abc123sha"}),
    ]
    provider = GitLabProvider(host="https://gitlab.com", access_token="t")
    info = await provider.commit_files(
        repo_full_path="acme/widgets",
        branch="main",
        message="chore: update",
        files=[GitFile(path="a.txt", content="hello")],
    )
    assert info.sha == "abc123sha"
    assert info.url.endswith("abc123sha")
    # Last call must be POST .../commits with proper actions payload
    last = patched_httpx.calls[-1]
    assert last["method"] == "POST"
    assert last["url"].endswith("/repository/commits")
    payload = last["json"]
    assert payload["branch"] == "main"
    assert payload["commit_message"] == "chore: update"
    assert payload["actions"] == [
        {"action": "update", "file_path": "a.txt", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_commit_files_creates_branch_when_missing(patched_httpx):
    # 1) GET branch -> 404; 2) POST create branch; 3) GET file -> 404; 4) POST commits
    patched_httpx.responses = [
        _FakeResponse(404, text="no branch"),
        _FakeResponse(201, {"name": "feature"}),
        _FakeResponse(404, text="no file"),
        _FakeResponse(201, {"id": "newsha", "web_url": ""}),
    ]
    provider = GitLabProvider(host="https://gitlab.com", access_token="t")
    info = await provider.commit_files(
        repo_full_path="acme/widgets",
        branch="feature",
        message="add",
        files=[GitFile(path="b.txt", content="data")],
    )
    assert info.sha == "newsha"
    # Second call should be POST to create branch
    assert patched_httpx.calls[1]["method"] == "POST"
    assert patched_httpx.calls[1]["url"].endswith("/repository/branches")
    assert patched_httpx.calls[1]["params"] == {"branch": "feature", "ref": "main"}
    # Last action should be `create`
    assert patched_httpx.calls[-1]["json"]["actions"][0]["action"] == "create"


@pytest.mark.asyncio
async def test_create_pull_request_returns_iid(patched_httpx):
    patched_httpx.responses = [
        _FakeResponse(201, {
            "id": 99999,
            "iid": 7,
            "web_url": "https://gitlab.com/acme/widgets/-/merge_requests/7",
            "state": "opened",
        }),
    ]
    provider = GitLabProvider(host="https://gitlab.com", access_token="t")
    pr = await provider.create_pull_request(
        repo_full_path="acme/widgets",
        source_branch="feature",
        target_branch="main",
        title="My MR",
        description="desc",
    )
    assert pr.id == "99999"
    assert pr.number == 7
    assert pr.url.endswith("/merge_requests/7")
    assert pr.state == "opened"
    body = patched_httpx.calls[0]["json"]
    assert body == {
        "source_branch": "feature",
        "target_branch": "main",
        "title": "My MR",
        "description": "desc",
    }
