"""GitConnection 凭证加解密 + provider 工厂"""
from __future__ import annotations
import os
from typing import Protocol
from cryptography.fernet import Fernet

from app.models.collaboration import GitConnection, TenantGitConnection
from app.git.provider.base import GitProvider
from app.git.provider.gitlab import GitLabProvider
from app.git.provider.github import GitHubProvider


def _fernet() -> Fernet:
    """读取 BUILDER_FERNET_KEY；缺失则退回到 dev fallback。

    生产必须配 BUILDER_FERNET_KEY（base64 32 bytes）。dev fallback 仅本地兜底，
    不安全。
    """
    key = os.environ.get("BUILDER_FERNET_KEY")
    if not key:
        # dev fallback - 32-byte base64 dummy（仅本地）
        key = "dGVzdC1mYWxsYmFjay1rZXktMzItYnl0ZXMtZGV2PT0="
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plain: str) -> str:
    """加密明文 token，返回 base64 ciphertext 字符串"""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(enc: str) -> str:
    """解密 base64 ciphertext，返回明文"""
    return _fernet().decrypt(enc.encode()).decode()


class GitCredential(Protocol):
    provider: str
    host: str
    access_token_enc: str


def make_provider(conn: GitCredential) -> GitProvider:
    """根据 GitConnection.provider 构造对应 GitProvider 实例"""
    token = decrypt_token(conn.access_token_enc)
    if conn.provider == "gitlab":
        return GitLabProvider(host=conn.host, access_token=token)
    elif conn.provider == "github":
        return GitHubProvider(access_token=token)
    raise ValueError(f"unknown git provider: {conn.provider}")
