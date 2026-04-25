"""Phase D Task 1 — webhook 签名验证 + event 解析（纯函数单测）"""
from __future__ import annotations
import hashlib
import hmac
import json

from app.git.webhook import (
    verify_signature_github,
    verify_signature_gitlab,
    parse_event,
    parse_github_event,
    parse_gitlab_event,
)


def test_github_signature_verify_pass():
    secret = "supersecret"
    payload = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signature_github(payload, sig, secret) is True


def test_github_signature_verify_fail_wrong_secret():
    secret = "supersecret"
    payload = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(b"other-secret", payload, hashlib.sha256).hexdigest()
    assert verify_signature_github(payload, sig, secret) is False


def test_github_signature_verify_fail_missing_prefix():
    """没有 sha256= 前缀直接拒"""
    secret = "supersecret"
    payload = b"{}"
    bad_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()  # 无前缀
    assert verify_signature_github(payload, bad_sig, secret) is False
    assert verify_signature_github(payload, "", secret) is False


def test_gitlab_token_compare_pass():
    assert verify_signature_gitlab(b"any payload", "tok-abc", "tok-abc") is True


def test_gitlab_token_compare_fail():
    assert verify_signature_gitlab(b"any payload", "wrong", "tok-abc") is False
    assert verify_signature_gitlab(b"any payload", "", "tok-abc") is False


def test_parse_github_push_event():
    headers = {"x-github-event": "push"}
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets"},
        "sender": {"login": "alice"},
    }
    ev = parse_event("github", headers, payload)
    assert ev.provider == "github"
    assert ev.event_type == "push"
    assert ev.repo_full_path == "acme/widgets"
    assert ev.branch == "main"
    assert ev.actor_username == "alice"
    assert ev.raw_payload is payload


def test_parse_github_pr_opened_event():
    headers = {"x-github-event": "pull_request"}
    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/widgets"},
        "sender": {"login": "bob"},
        "pull_request": {
            "number": 42,
            "title": "Add foo",
            "body": "desc",
            "head": {"ref": "feature/foo"},
            "base": {"ref": "main"},
        },
    }
    ev = parse_event("github", headers, payload)
    assert ev.event_type == "pr_opened"
    assert ev.pr_number == 42
    assert ev.pr_title == "Add foo"
    assert ev.pr_source_branch == "feature/foo"
    assert ev.pr_target_branch == "main"


def test_parse_github_pr_merged_event():
    headers = {"x-github-event": "pull_request"}
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/widgets"},
        "sender": {"login": "bob"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "title": "x",
            "body": "y",
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            "merge_commit_sha": "abc123",
        },
    }
    ev = parse_event("github", headers, payload)
    assert ev.event_type == "pr_merged"
    assert ev.pr_number == 7


def test_parse_github_pr_review_approved():
    headers = {"x-github-event": "pull_request_review"}
    payload = {
        "repository": {"full_name": "acme/widgets"},
        "sender": {"login": "carol"},
        "pull_request": {"number": 9},
        "review": {"state": "approved", "body": "lgtm"},
    }
    ev = parse_event("github", headers, payload)
    assert ev.event_type == "pr_review"
    assert ev.review_action == "approve"
    assert ev.review_body == "lgtm"


def test_parse_gitlab_push_event():
    payload = {
        "object_kind": "push",
        "ref": "refs/heads/main",
        "project": {"path_with_namespace": "grp/proj"},
        "user_username": "dave",
    }
    ev = parse_event("gitlab", {}, payload)
    assert ev.provider == "gitlab"
    assert ev.event_type == "push"
    assert ev.branch == "main"
    assert ev.repo_full_path == "grp/proj"


def test_parse_gitlab_merge_request_open():
    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "grp/proj"},
        "user": {"username": "eve"},
        "object_attributes": {
            "action": "open",
            "iid": 5,
            "title": "MR title",
            "description": "MR body",
            "source_branch": "feat/x",
            "target_branch": "main",
        },
    }
    ev = parse_event("gitlab", {}, payload)
    assert ev.event_type == "pr_opened"
    assert ev.pr_number == 5
    assert ev.pr_source_branch == "feat/x"


def test_parse_unknown_provider_returns_unknown():
    ev = parse_event("bitbucket", {}, {"x": 1})
    assert ev.event_type == "unknown"
    assert ev.provider == "bitbucket"
