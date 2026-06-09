"""Webhook 入口处理：验签 + provider-specific event 解析"""
from __future__ import annotations
import hmac
import hashlib
from dataclasses import dataclass
from typing import Optional


@dataclass
class WebhookEvent:
    """规整化的 webhook 事件（跨 provider 抽象）"""
    provider: str       # 'github' | 'gitlab'
    event_type: str     # 'push' | 'pr_opened' | 'pr_synchronized' | 'pr_merged' | 'unknown'
    repo_full_path: str
    branch: Optional[str] = None         # for push events
    pr_number: Optional[int] = None      # for pr events
    pr_title: Optional[str] = None
    pr_description: Optional[str] = None
    pr_source_branch: Optional[str] = None
    pr_target_branch: Optional[str] = None
    actor_username: Optional[str] = None
    raw_payload: Optional[dict] = None


def verify_signature_github(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """验证 X-Hub-Signature-256 header（GitHub webhook 签名）"""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    given_sig = signature_header[len("sha256="):]
    return hmac.compare_digest(expected_sig, given_sig)


def verify_signature_gitlab(payload_bytes: bytes, token_header: str, secret: str) -> bool:
    """GitLab 用 X-Gitlab-Token header（明文 secret 比对）"""
    if not token_header:
        return False
    return hmac.compare_digest(token_header, secret)


def parse_github_event(headers: dict, payload: dict) -> WebhookEvent:
    event = headers.get("x-github-event") or headers.get("X-GitHub-Event") or ""
    repo = payload.get("repository", {}).get("full_name", "")
    actor = payload.get("sender", {}).get("login")

    if event == "push":
        ref = payload.get("ref", "")  # e.g. 'refs/heads/main'
        branch = ref.split("/")[-1] if "/" in ref else ref
        return WebhookEvent(provider="github", event_type="push", repo_full_path=repo,
                            branch=branch, actor_username=actor, raw_payload=payload)

    if event == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        et = "unknown"
        if action == "opened":
            et = "pr_opened"
        elif action == "synchronize":
            et = "pr_synchronized"
        elif action == "closed" and pr.get("merged"):
            et = "pr_merged"
        return WebhookEvent(
            provider="github", event_type=et, repo_full_path=repo,
            pr_number=pr.get("number"),
            pr_title=pr.get("title"),
            pr_description=pr.get("body"),
            pr_source_branch=pr.get("head", {}).get("ref"),
            pr_target_branch=pr.get("base", {}).get("ref"),
            actor_username=actor, raw_payload=payload,
        )

    return WebhookEvent(provider="github", event_type="unknown", repo_full_path=repo,
                        actor_username=actor, raw_payload=payload)


def parse_gitlab_event(headers: dict, payload: dict) -> WebhookEvent:
    event_kind = payload.get("object_kind", "") or headers.get("x-gitlab-event", "").lower()
    repo = payload.get("project", {}).get("path_with_namespace", "")
    actor = (payload.get("user") or {}).get("username") or payload.get("user_username")

    if event_kind == "push":
        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if "/" in ref else ref
        return WebhookEvent(provider="gitlab", event_type="push", repo_full_path=repo,
                            branch=branch, actor_username=actor, raw_payload=payload)

    if event_kind == "merge_request":
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action")
        et = "unknown"
        if action == "open":
            et = "pr_opened"
        elif action == "update":
            et = "pr_synchronized"
        elif action == "merge":
            et = "pr_merged"
        return WebhookEvent(
            provider="gitlab", event_type=et, repo_full_path=repo,
            pr_number=attrs.get("iid"),
            pr_title=attrs.get("title"),
            pr_description=attrs.get("description"),
            pr_source_branch=attrs.get("source_branch"),
            pr_target_branch=attrs.get("target_branch"),
            actor_username=actor, raw_payload=payload,
        )

    return WebhookEvent(provider="gitlab", event_type="unknown", repo_full_path=repo,
                        actor_username=actor, raw_payload=payload)


def parse_event(provider: str, headers: dict, payload: dict) -> WebhookEvent:
    if provider == "github":
        return parse_github_event(headers, payload)
    if provider == "gitlab":
        return parse_gitlab_event(headers, payload)
    return WebhookEvent(provider=provider, event_type="unknown", repo_full_path="", raw_payload=payload)
