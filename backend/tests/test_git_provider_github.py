"""Unit tests for GitHubProvider — mock httpx.AsyncClient via monkeypatch."""
from __future__ import annotations
import base64

import pytest

from app.git.provider import github as github_module
from app.git.provider.base import GitFile
from app.git.provider.github import GitHubProvider


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | list | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
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
    monkeypatch.setattr(github_module.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_get_repo_returns_metadata(patched_httpx):
    patched_httpx.responses = [
        _FakeResponse(200, {"id": 12345, "full_name": "acme/widgets"}),
    ]
    provider = GitHubProvider(access_token="ghp_test")
    meta = await provider.get_repo("acme/widgets")
    assert meta == {"id": 12345, "full_name": "acme/widgets"}
    call = patched_httpx.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://api.github.com/repos/acme/widgets"
    assert call["headers"]["Authorization"] == "token ghp_test"
    assert call["headers"]["Accept"] == "application/vnd.github+json"


@pytest.mark.asyncio
async def test_get_repo_returns_none_on_404(patched_httpx):
    patched_httpx.responses = [_FakeResponse(404, text="Not Found")]
    provider = GitHubProvider(access_token="ghp_test")
    assert await provider.get_repo("nope/missing") is None


@pytest.mark.asyncio
async def test_create_repo_calls_org_endpoint(patched_httpx):
    patched_httpx.responses = [
        _FakeResponse(201, {"full_name": "acme/widgets", "id": 1}),
    ]
    provider = GitHubProvider(access_token="ghp_test")
    full_path = await provider.create_repo(
        group_or_org="acme", name="widgets", description="hi",
    )
    assert full_path == "acme/widgets"
    call = patched_httpx.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.github.com/orgs/acme/repos"
    assert call["json"] == {
        "name": "widgets",
        "description": "hi",
        "private": True,
        "auto_init": True,
    }


@pytest.mark.asyncio
async def test_commit_files_single_file_create(patched_httpx):
    """File doesn't exist (404) on a branch that already exists -> PUT without sha."""
    patched_httpx.responses = [
        # _ensure_branch: GET refs/heads/feature -> 200 (already exists)
        _FakeResponse(200, {"object": {"sha": "branchsha"}}),
        # GET /contents -> 404 (file doesn't exist yet)
        _FakeResponse(404, text="not found"),
        # PUT /contents -> 201 commit
        _FakeResponse(201, {"commit": {"sha": "newcommit", "html_url": "https://github.com/acme/widgets/commit/newcommit"}}),
    ]
    provider = GitHubProvider(access_token="ghp_test")
    info = await provider.commit_files(
        repo_full_path="acme/widgets",
        branch="feature",
        message="add file",
        files=[GitFile(path="docs/a.txt", content="hello world")],
    )
    assert info.sha == "newcommit"
    assert info.url.endswith("/commit/newcommit")

    # Final call: PUT /contents/docs/a.txt with base64 content & no sha
    put_call = patched_httpx.calls[-1]
    assert put_call["method"] == "PUT"
    assert put_call["url"] == "https://api.github.com/repos/acme/widgets/contents/docs/a.txt"
    body = put_call["json"]
    assert body["message"] == "add file"
    assert body["branch"] == "feature"
    assert body["content"] == base64.b64encode(b"hello world").decode("ascii")
    assert "sha" not in body  # not an update


@pytest.mark.asyncio
async def test_commit_files_single_file_update_includes_sha(patched_httpx):
    """File exists -> PUT must include the sha for update mode."""
    patched_httpx.responses = [
        # _ensure_branch: GET refs/heads/main -> 200
        _FakeResponse(200, {"object": {"sha": "mainsha"}}),
        # GET /contents -> 200 (file exists; sha = oldsha)
        _FakeResponse(200, {"sha": "oldsha", "content": "..."}),
        # PUT /contents -> 200 commit
        _FakeResponse(200, {"commit": {"sha": "updatedcommit", "html_url": "https://x/commit/updatedcommit"}}),
    ]
    provider = GitHubProvider(access_token="ghp_test")
    await provider.commit_files(
        repo_full_path="acme/widgets",
        branch="main",
        message="update file",
        files=[GitFile(path="README.md", content="updated content")],
    )
    put_call = patched_httpx.calls[-1]
    assert put_call["json"]["sha"] == "oldsha"


@pytest.mark.asyncio
async def test_commit_files_creates_branch_when_missing(patched_httpx):
    """Branch missing -> GET main, POST refs to create branch, then proceed."""
    patched_httpx.responses = [
        # _ensure_branch: GET refs/heads/feature -> 404
        _FakeResponse(404, text="no branch"),
        # GET refs/heads/main -> 200
        _FakeResponse(200, {"object": {"sha": "mainsha"}}),
        # POST git/refs -> 201
        _FakeResponse(201, {"ref": "refs/heads/feature"}),
        # GET /contents -> 404
        _FakeResponse(404, text="no file"),
        # PUT /contents -> 201
        _FakeResponse(201, {"commit": {"sha": "newsha", "html_url": ""}}),
    ]
    provider = GitHubProvider(access_token="ghp_test")
    await provider.commit_files(
        repo_full_path="acme/widgets",
        branch="feature",
        message="bootstrap",
        files=[GitFile(path="x.txt", content="data")],
    )
    # 3rd call should be POST refs creating the new branch
    create_branch_call = patched_httpx.calls[2]
    assert create_branch_call["method"] == "POST"
    assert create_branch_call["url"].endswith("/git/refs")
    assert create_branch_call["json"] == {
        "ref": "refs/heads/feature", "sha": "mainsha",
    }


@pytest.mark.asyncio
async def test_create_pull_request_returns_number_and_url(patched_httpx):
    patched_httpx.responses = [
        _FakeResponse(201, {
            "id": 9876543210,
            "number": 42,
            "html_url": "https://github.com/acme/widgets/pull/42",
            "state": "open",
        }),
    ]
    provider = GitHubProvider(access_token="ghp_test")
    pr = await provider.create_pull_request(
        repo_full_path="acme/widgets",
        source_branch="feature",
        target_branch="main",
        title="Title",
        description="Body",
    )
    assert pr.id == "9876543210"
    assert pr.number == 42
    assert pr.url == "https://github.com/acme/widgets/pull/42"
    assert pr.state == "open"
    body = patched_httpx.calls[0]["json"]
    assert body == {
        "title": "Title",
        "body": "Body",
        "head": "feature",
        "base": "main",
    }


@pytest.mark.asyncio
async def test_add_tag_posts_refs(patched_httpx):
    patched_httpx.responses = [_FakeResponse(201, {"ref": "refs/tags/v1.0"})]
    provider = GitHubProvider(access_token="ghp_test")
    name = await provider.add_tag(
        repo_full_path="acme/widgets", tag="v1.0", ref="abcdef",
    )
    assert name == "v1.0"
    call = patched_httpx.calls[0]
    assert call["url"].endswith("/git/refs")
    assert call["json"] == {"ref": "refs/tags/v1.0", "sha": "abcdef"}


@pytest.mark.asyncio
async def test_add_pr_comment_posts_to_issues_endpoint(patched_httpx):
    patched_httpx.responses = [_FakeResponse(201, {"id": 1})]
    provider = GitHubProvider(access_token="ghp_test")
    await provider.add_pr_comment(
        repo_full_path="acme/widgets", pr_number=42, body="LGTM",
    )
    call = patched_httpx.calls[0]
    assert call["url"] == "https://api.github.com/repos/acme/widgets/issues/42/comments"
    assert call["json"] == {"body": "LGTM"}
