"""密码加密/解密工具 — 使用 Fernet 对称加密"""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

# 历史默认 key:桌面早期版本(ALLOW_DEFAULT_ENCRYPTION_KEY 旁路时代)用它加密过环境密码。
# 撤旁路改成每实例高熵 ENCRYPTION_KEY 后(commit 799d666e),旧密文必须用它兜底解,
# 否则用户更新后老环境凭据解不开 → apaas relogin 失败 → 登录失败 / queryAppList 401
# (2026-06-18 同事更新到 0.2.14 后踩到)。加密始终用当前 key,旧密文一旦重存即迁移。
_LEGACY_KEYS = ("default-key-change-in-production-32b",)


def _fernet_for(key: str) -> Fernet:
    """从任意 key 字符串 sha256 派生 32 字节 Fernet key。"""
    key_bytes = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def _get_fernet() -> Fernet:
    from app.config import settings
    return _fernet_for(settings.encryption_key)


def encrypt_password(plain: str) -> str:
    """加密密码(始终用当前 ENCRYPTION_KEY)。"""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """解密密码。

    先用当前 ENCRYPTION_KEY 解;解不开时回退历史默认 key —— 兼容「换 key 之前存的
    旧密文」(撤加密旁路 799d666e 之后,旧默认-key 加密的环境凭据否则永远解不开)。
    全失败时抛 InvalidToken(保持原有语义)。
    """
    from app.config import settings
    token = encrypted.encode()
    last_exc: Exception | None = None
    for key in (settings.encryption_key, *_LEGACY_KEYS):
        if not key:
            continue
        try:
            return _fernet_for(key).decrypt(token).decode()
        except InvalidToken as exc:
            last_exc = exc
    raise last_exc if last_exc is not None else InvalidToken()
