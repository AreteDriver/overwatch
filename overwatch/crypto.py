"""Field-level encryption for sensitive data at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) for symmetric encryption.
Generate a key:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Set via OVERWATCH_ENCRYPTION_KEY env var.

When no key is set, encrypt/decrypt are pass-through (no-ops).
"""

from __future__ import annotations

import hashlib
import logging

import overwatch.config

log = logging.getLogger(__name__)

# Lazy singleton — initialized on first use rather than at import time.
# This avoids side effects during module import and makes the module
# testable without importlib.reload gymnastics.
_fernet = None


def _get_fernet():
    """Return a cached Fernet instance, or None if no key / bad key / missing package.

    Thread-safe for CPython because the GIL protects the singleton assignment.
    For other interpreters, the worst case is a redundant Fernet() construction.
    """
    global _fernet
    if _fernet is not None:
        return _fernet

    if overwatch.config.ENCRYPTION_KEY:
        try:
            from cryptography.fernet import Fernet

            _fernet = Fernet(overwatch.config.ENCRYPTION_KEY.encode())
            log.info("Field encryption enabled")
        except ImportError:
            log.warning(
                "OVERWATCH_ENCRYPTION_KEY set but 'cryptography' not installed. "
                "Install with: pip install cryptography"
            )
        except Exception as exc:
            log.error("Invalid encryption key: %s", exc)

    return _fernet


def _reset_fernet() -> None:
    """Reset the cached Fernet instance (for testing only)."""
    global _fernet
    _fernet = None


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext, or plaintext if no key."""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()  # type: ignore[no-any-return,union-attr]


def decrypt(ciphertext: str) -> str:
    """Decrypt a string. Returns plaintext, or the input unchanged if no key."""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()  # type: ignore[no-any-return,union-attr]
    except Exception:
        # If decryption fails, it's likely unencrypted data from before key was set
        return ciphertext


def hash_value(value: str) -> str:
    """One-way hash for values that don't need decryption (e.g. source dedup)."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]
