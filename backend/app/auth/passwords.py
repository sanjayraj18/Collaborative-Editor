"""Password hashing with scrypt (stdlib, memory-hard).

Replaces passlib+bcrypt: passlib 1.7.4 is unmaintained and breaks against
bcrypt>=4. scrypt ships in hashlib, so this costs no dependency.

Encoded form:  scrypt$<n>$<r>$<p>$<b64 salt>$<b64 key>
The parameters live inside the hash so cost can be raised later without
invalidating existing passwords (see needs_rehash).
"""

from __future__ import annotations

import base64
import hmac
import secrets
from hashlib import scrypt
from typing import Final

ALGORITHM: Final[str] = "scrypt"

SCRYPT_N: Final[int] = 2**15
SCRYPT_R: Final[int] = 8
SCRYPT_P: Final[int] = 1

SALT_BYTES: Final[int] = 16
KEY_BYTES: Final[int] = 32
MAX_PASSWORD_BYTES: Final[int] = 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # OpenSSL's default maxmem ceiling is exactly 128*2**15*8 = 32 MiB, which
    # our parameters sit on top of, so it must be raised explicitly.
    return scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=KEY_BYTES,
        maxmem=128 * n * r * 2,
    )


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds {MAX_PASSWORD_BYTES} bytes")

    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(
        [ALGORITHM, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(key)]
    )


def verify_password(password: str, encoded: str) -> bool:
    """False for every failure. Never raises, never distinguishes."""
    if not password or not encoded:
        return False
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False

    try:
        algorithm, n_raw, r_raw, p_raw, salt_b64, key_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        n, r, p = int(n_raw), int(r_raw), int(p_raw)
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(key_b64, validate=True)
    except (ValueError, TypeError):
        return False

    if n < 2 or n & (n - 1) or r < 1 or p < 1 or not salt or not expected:
        return False

    try:
        candidate = _derive(password, salt, n, r, p)
    except (ValueError, MemoryError):
        return False

    return hmac.compare_digest(candidate, expected)


def needs_rehash(encoded: str) -> bool:
    try:
        algorithm, n_raw, r_raw, p_raw, _, _ = encoded.split("$")
    except ValueError:
        return True
    if algorithm != ALGORITHM:
        return True
    try:
        return (int(n_raw), int(r_raw), int(p_raw)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    except ValueError:
        return True


# Verifying against this on the user-not-found path makes that branch cost
# the same as a wrong-password branch, closing the enumeration timing channel.
DUMMY_HASH: Final[str] = hash_password(secrets.token_urlsafe(32))
