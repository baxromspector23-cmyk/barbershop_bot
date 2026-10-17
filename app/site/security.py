from __future__ import annotations

import hashlib
import hmac
import secrets

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    """Hash a password with stdlib hashlib.scrypt and a 16-byte random salt."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def is_valid_hash_format(stored: str) -> bool:
    """Return True if stored looks like a valid scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex> string."""
    if not isinstance(stored, str) or not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_dk = bytes.fromhex(parts[5])
    except (ValueError, TypeError):
        return False

    if n < 1024 or n > 65536 or (n & (n - 1)) != 0:
        return False
    if r < 1 or r > 32:
        return False
    if p < 1 or p > 16:
        return False
    if len(salt) < 16 or len(salt) > 64:
        return False
    if len(expected_dk) < 16 or len(expected_dk) > 64:
        return False
    return True


def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored scrypt hash in constant time. Never raises on malformed input."""
    if not isinstance(password, str) or not password:
        return False
    if not is_valid_hash_format(stored):
        return False
    try:
        parts = stored.split("$")
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_dk = bytes.fromhex(parts[5])
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=64 * 1024 * 1024,
            dklen=len(expected_dk),
        )
        return hmac.compare_digest(dk, expected_dk)
    except Exception:
        return False
