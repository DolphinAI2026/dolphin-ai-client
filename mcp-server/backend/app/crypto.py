"""密码加密/解密工具 — 使用 Fernet 对称加密"""
import base64
import hashlib
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    from app.config import settings
    # 从配置的 key 派生 32 字节 Fernet key
    key_bytes = hashlib.sha256(settings.encryption_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_password(plain: str) -> str:
    """加密密码"""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """解密密码"""
    return _get_fernet().decrypt(encrypted.encode()).decode()


def migrate_base64_to_fernet(base64_enc: str) -> str:
    """将旧的 base64 编码迁移为 Fernet 加密"""
    try:
        plain = base64.b64decode(base64_enc).decode()
        return encrypt_password(plain)
    except Exception:
        return base64_enc  # 已经是 Fernet 格式或无效，原样返回
