"""crypto.decrypt_password 的 legacy-key 兜底。

回归:桌面撤加密旁路(799d666e, ALLOW_DEFAULT→每实例高熵 ENCRYPTION_KEY)后,
旧版本用默认 key 加密的环境密码,更新后用新 key 解不开 → apaas relogin 失败 →
登录失败/401。decrypt_password 现回退历史默认 key 兜底解。
"""
import base64
import hashlib

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app import crypto
from app.config import settings

LEGACY = "default-key-change-in-production-32b"
NEW = "x9k2-high-entropy-per-instance-key-abc123def456"


def _enc_with(key: str, plain: str) -> str:
    f = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
    return f.encrypt(plain.encode()).decode()


def test_decrypt_recovers_legacy_default_key_ciphertext(monkeypatch):
    # 旧默认 key 加密的密文,当前换成新 key 后仍能解(兜底)——这正是同事的场景
    blob = _enc_with(LEGACY, "secret-pw")
    monkeypatch.setattr(settings, "encryption_key", NEW)
    assert crypto.decrypt_password(blob) == "secret-pw"


def test_encrypt_decrypt_roundtrip_current_key(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", NEW)
    blob = crypto.encrypt_password("hello-世界")
    assert crypto.decrypt_password(blob) == "hello-世界"


def test_encrypt_always_uses_current_key_not_legacy(monkeypatch):
    # 新加密始终用当前 key(不是 legacy)→ 用 legacy key 解不开,确保新密文走安全 key
    monkeypatch.setattr(settings, "encryption_key", NEW)
    blob = crypto.encrypt_password("hello")
    legacy_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(LEGACY.encode()).digest()))
    with pytest.raises(InvalidToken):
        legacy_fernet.decrypt(blob.encode())


def test_decrypt_bad_ciphertext_raises(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", NEW)
    with pytest.raises(Exception):
        crypto.decrypt_password("not-a-valid-fernet-token")
