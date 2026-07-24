"""Fernet encryption helpers for TOTP Base32 secrets.

Never log plaintext secrets, ciphertext, provisioning URIs, or OTP codes.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

TOTP_ENCRYPTION_NOT_CONFIGURED_MESSAGE = "TOTP encryption is not configured"
TOTP_ENCRYPTION_INVALID_KEY_MESSAGE = "TOTP encryption key is invalid"
TOTP_SECRET_DECRYPT_FAILED_MESSAGE = "Unable to decrypt TOTP secret"


class TotpEncryptionError(Exception):
    """Raised when TOTP secret encryption/decryption cannot proceed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _configured_key() -> str:
    raw = current_app.config.get("TOTP_ENCRYPTION_KEY", "")
    if raw is None:
        return ""
    return str(raw).strip()


def _fernet_from_config() -> Fernet:
    key = _configured_key()
    if not key:
        raise TotpEncryptionError(TOTP_ENCRYPTION_NOT_CONFIGURED_MESSAGE)
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (TypeError, ValueError) as exc:
        raise TotpEncryptionError(TOTP_ENCRYPTION_INVALID_KEY_MESSAGE) from exc


def encrypt_totp_secret(plaintext_base32: str) -> str:
    """Encrypt a Base32 TOTP secret for database storage."""
    fernet = _fernet_from_config()
    token = fernet.encrypt(plaintext_base32.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_totp_secret(secret_encrypted: str) -> str:
    """Decrypt a stored Fernet ciphertext back to the Base32 secret."""
    fernet = _fernet_from_config()
    try:
        plaintext = fernet.decrypt(secret_encrypted.encode("utf-8"))
    except InvalidToken as exc:
        raise TotpEncryptionError(TOTP_SECRET_DECRYPT_FAILED_MESSAGE) from exc
    return plaintext.decode("utf-8")
