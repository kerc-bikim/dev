"""비밀번호 해싱.

표준 라이브러리의 scrypt 를 쓴다. 의존성을 늘리지 않고 KDF 를 쓰기 위한 선택이다.
저장 형식은 파라미터를 함께 담아, 나중에 비용을 올려도 기존 해시를 검증할 수 있게 한다.

    scrypt$n$r$p$<salt-hex>$<hash-hex>
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import string

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    if not password:
        raise ValueError("비밀번호가 비어 있다")
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_BYTES)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n_raw, r_raw, p_raw, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def generate_password(length: int = 20) -> str:
    """초기 관리자 비밀번호 생성. 사람이 옮겨 적을 수 있는 문자만 쓴다."""
    alphabet = string.ascii_letters + string.digits + "!@#%^*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))
