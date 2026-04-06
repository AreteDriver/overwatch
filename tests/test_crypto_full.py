"""Comprehensive tests for overwatch.crypto — targeting 90%+ coverage."""

from __future__ import annotations

import builtins
import importlib
import logging
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from overwatch.crypto import decrypt, encrypt, hash_value

# ---------------------------------------------------------------------------
# 1. No encryption key (default pass-through)
# ---------------------------------------------------------------------------


class TestPassThrough:
    """When _fernet is None, encrypt/decrypt are identity functions."""

    def test_encrypt_returns_plaintext(self):
        with patch("overwatch.crypto._fernet", None):
            assert encrypt("hello world") == "hello world"

    def test_decrypt_returns_ciphertext(self):
        with patch("overwatch.crypto._fernet", None):
            assert decrypt("some-cipher-text") == "some-cipher-text"

    def test_encrypt_empty_string(self):
        with patch("overwatch.crypto._fernet", None):
            assert encrypt("") == ""

    def test_decrypt_empty_string(self):
        with patch("overwatch.crypto._fernet", None):
            assert decrypt("") == ""


# ---------------------------------------------------------------------------
# 2. hash_value deterministic
# ---------------------------------------------------------------------------


class TestHashValue:
    def test_deterministic(self):
        """Same input always produces the same hash."""
        h1 = hash_value("sensor-alpha")
        h2 = hash_value("sensor-alpha")
        assert h1 == h2

    def test_different_inputs(self):
        """Different inputs produce different hashes."""
        assert hash_value("input-a") != hash_value("input-b")

    def test_length(self):
        """Hash is truncated to 16 hex characters."""
        assert len(hash_value("anything")) == 16

    def test_hex_chars(self):
        """Hash contains only hex characters."""
        h = hash_value("test-value")
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# 3. With real Fernet key
# ---------------------------------------------------------------------------


class TestWithFernet:
    """Patch _fernet to a real Fernet instance and exercise encrypt/decrypt."""

    @pytest.fixture(autouse=True)
    def _fernet_key(self):
        key = Fernet.generate_key()
        self.fernet = Fernet(key)

    def test_encrypt_changes_value(self):
        with patch("overwatch.crypto._fernet", self.fernet):
            ct = encrypt("secret-data")
            assert ct != "secret-data"

    def test_round_trip(self):
        with patch("overwatch.crypto._fernet", self.fernet):
            ct = encrypt("round-trip-test")
            pt = decrypt(ct)
            assert pt == "round-trip-test"

    def test_decrypt_invalid_ciphertext_returns_input(self):
        """Graceful fallback: invalid ciphertext is returned unchanged."""
        with patch("overwatch.crypto._fernet", self.fernet):
            result = decrypt("not-valid-fernet-token")
            assert result == "not-valid-fernet-token"

    def test_encrypt_unicode(self):
        with patch("overwatch.crypto._fernet", self.fernet):
            ct = encrypt("données secrètes 🔒")
            pt = decrypt(ct)
            assert pt == "données secrètes 🔒"

    def test_encrypt_long_string(self):
        long_str = "x" * 10_000
        with patch("overwatch.crypto._fernet", self.fernet):
            ct = encrypt(long_str)
            assert decrypt(ct) == long_str


# ---------------------------------------------------------------------------
# 4. Module-level import: invalid key
# ---------------------------------------------------------------------------


class TestModuleLevelInvalidKey:
    def test_invalid_key_logs_error(self, caplog):
        """An invalid ENCRYPTION_KEY logs an error but does not crash."""
        import overwatch.config

        orig = overwatch.config.ENCRYPTION_KEY
        try:
            overwatch.config.ENCRYPTION_KEY = "not-a-valid-fernet-key"
            with caplog.at_level(logging.ERROR, logger="overwatch.crypto"):
                importlib.reload(importlib.import_module("overwatch.crypto"))
            assert any("Invalid encryption key" in r.message for r in caplog.records)
        finally:
            overwatch.config.ENCRYPTION_KEY = orig
            importlib.reload(importlib.import_module("overwatch.crypto"))


# ---------------------------------------------------------------------------
# 5. Module-level import: cryptography package missing
# ---------------------------------------------------------------------------


class TestModuleLevelMissingPackage:
    def test_missing_cryptography_logs_warning(self, caplog):
        """When cryptography is not installed, a warning is logged."""
        import sys

        import overwatch.config

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "cryptography.fernet":
                raise ImportError("No module named 'cryptography'")
            return real_import(name, *args, **kwargs)

        orig = overwatch.config.ENCRYPTION_KEY
        try:
            overwatch.config.ENCRYPTION_KEY = "some-key-value"
            with (
                patch("builtins.__import__", side_effect=fake_import),
                caplog.at_level(logging.WARNING, logger="overwatch.crypto"),
            ):
                # Remove cached cryptography module so the import path is hit
                saved = sys.modules.pop("cryptography.fernet", None)
                try:
                    importlib.reload(importlib.import_module("overwatch.crypto"))
                finally:
                    if saved is not None:
                        sys.modules["cryptography.fernet"] = saved
            assert any("cryptography" in r.message for r in caplog.records)
        finally:
            overwatch.config.ENCRYPTION_KEY = orig
            importlib.reload(importlib.import_module("overwatch.crypto"))
