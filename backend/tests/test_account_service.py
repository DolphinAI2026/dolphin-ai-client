import hashlib
from app.auth import get_password_hash, verify_password


def test_new_hash_is_bcrypt_and_verifies():
    h = get_password_hash("ruijing2026")
    assert h.startswith("$2")  # bcrypt 前缀
    assert verify_password("ruijing2026", h) is True
    assert verify_password("wrong", h) is False


def test_legacy_sha256_still_verifies():
    # 旧账号库里是裸 sha256 hexdigest
    legacy = hashlib.sha256("oldpw".encode()).hexdigest()
    assert verify_password("oldpw", legacy) is True
    assert verify_password("wrong", legacy) is False
