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

from overwatch.config import ENCRYPTION_KEY

log = logging.getLogger(__name__)

_fernet = None

if ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(ENCRYPTION_KEY.encode())
        log.info("Field encryption enabled")
    except ImportError:
        log.warning(
            "OVERWATCH_ENCRYPTION_KEY set but 'cryptography' not installed. "
            "Install with: pip install cryptography"
        )
    except Exception as exc:
        log.error("Invalid encryption key: %s", exc)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext, or plaintext if no key."""
    if _fernet is None:
        return plaintext
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a string. Returns plaintext, or the input unchanged if no key."""
    if _fernet is None:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        # If decryption fails, it's likely unencrypted data from before key was set
        return ciphertext


def hash_value(value: str) -> str:
    """One-way hash for values that don't need decryption (e.g. source dedup)."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]
