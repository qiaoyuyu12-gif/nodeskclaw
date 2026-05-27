"""密码哈希工具：PBKDF2-HMAC-SHA256，供 auth_service 和 admin service 共用。"""

import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    """生成 PBKDF2-HMAC-SHA256 哈希，格式为 salt$dk_hex。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """验证明文密码与存储哈希是否匹配。"""
    parts = hashed.split("$", 1)
    if len(parts) != 2:
        return False
    salt, stored_dk = parts
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return hmac.compare_digest(dk.hex(), stored_dk)
