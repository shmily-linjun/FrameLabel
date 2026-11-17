"""Password hashing helpers for the local operator accounts.

The operator accounts are a local identity convention, not a security
boundary: the account database and the annotation files live on the same
machine and can be edited by anyone who can write them.  PBKDF2-HMAC-SHA256
with a random per-user salt is used so that a copied database does not expose
plaintext passwords, but nothing here should be described as tamper-proof.
"""

from __future__ import annotations

import hashlib
import hmac
import os

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 260_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 256


class PasswordError(ValueError):
    """Raised when a password does not satisfy the local policy."""


def validate_password(password: object) -> str:
    """Return a normalized password or raise :class:`PasswordError`."""
    if not isinstance(password, str):
        raise PasswordError("Password must be a string.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )
    return password


def hash_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = PBKDF2_ITERATIONS,
) -> tuple[str, str, int]:
    """Hash ``password`` and return ``(hash_hex, salt_hex, iterations)``."""
    password = validate_password(password)
    if salt is None:
        salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return digest.hex(), salt.hex(), iterations


def verify_password(
    password: object,
    hash_hex: str,
    salt_hex: str,
    iterations: int,
) -> bool:
    """Constant-time check of ``password`` against the stored hash."""
    if not isinstance(password, str) or not hash_hex or not salt_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        rounds = int(iterations)
    except (TypeError, ValueError):
        return False
    if rounds <= 0 or not salt or not expected:
        return False
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        rounds,
    )
    return hmac.compare_digest(digest, expected)
