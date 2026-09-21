"""
Field-level encryption for Renova's most sensitive owner data (NSS and
credit number).

Deliberately thin: no custom cryptography. Values are encrypted with
`cryptography.fernet` (AES-128-CBC + HMAC-SHA256, authenticated) using a key
from the environment (settings.renova_encryption_key). `MultiFernet` is used
so several comma-separated keys can be configured — the first encrypts, all
decrypt — which is what makes key rotation possible without re-encrypting
every row at once.

Rules this module enforces for every caller:
  * There is NO plaintext fallback. With no key configured, `encrypt` raises
    `EncryptionNotConfiguredError`; the service turns that into a 503 and the
    value is never stored.
  * Error messages and reprs never contain the value being protected.
  * `decrypt` never raises on a bad/rotated-away token — it returns None, so a
    key problem degrades a masked display to "unknown" instead of 500-ing a
    detail page (and never logs the token).
  * Nothing here (or anywhere) exposes a way for an API to return the full
    value: reads only ever get `mask_secret(...)`.

This data must never reach an AI agent, an audit snapshot, a log line, or a
public fixture — see app/services/renova_case_service.py and
tests/test_renova_privacy.py.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


class EncryptionNotConfiguredError(RuntimeError):
    """Raised instead of ever storing a sensitive value unencrypted. Its message is static on purpose."""

    def __init__(self) -> None:
        super().__init__("Sensitive-field encryption is not configured.")


def _build_cipher(raw_keys: str | None) -> MultiFernet | None:
    if not raw_keys:
        return None
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not keys:
        return None
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError):
        # A malformed key is a deployment error, not something to explain
        # with the key's own contents — treated exactly like "not configured".
        return None


def encrypt_secret(plaintext: str) -> str:
    cipher = _build_cipher(settings.renova_encryption_key)
    if cipher is None:
        raise EncryptionNotConfiguredError()
    return cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str | None:
    cipher = _build_cipher(settings.renova_encryption_key)
    if cipher is None:
        return None
    try:
        return cipher.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_secret(plaintext: str | None) -> str:
    """
    "••••1234" — the last four characters only, and nothing at all when the
    value is 4 characters or shorter (revealing a whole short value defeats
    the point). `None` (couldn't decrypt) masks to a bare "••••".
    """
    if not plaintext or len(plaintext) <= 4:
        return "••••"
    return "••••" + plaintext[-4:]


def mask_encrypted(token: str | None) -> str | None:
    """Masked display for a stored ciphertext; None when nothing is stored (so the UI can tell 'empty' from 'set')."""
    if not token:
        return None
    return mask_secret(decrypt_secret(token))
