"""
Exercises the real get_current_claims (JWT verification) logic against a
locally-generated ES256 keypair — no live Supabase project needed. The
JWKS *fetch* itself is stubbed out (get_signing_key_from_jwt is
monkeypatched to return our test key directly) so this tests exactly the
verification rules — algorithm, signature, audience, issuer, expiry — that
matter, without depending on network access.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import security
from app.core.config import settings


@pytest.fixture()
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _make_token(private_key, *, claims_overrides: dict | None = None, expired: bool = False) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(uuid.uuid4()),
        "email": "agent@example.com",
        "app_metadata": {"provider": "email"},
        "aud": settings.supabase_jwt_aud,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": (now - timedelta(minutes=5)) if expired else (now + timedelta(hours=1)),
    }
    if claims_overrides:
        claims.update(claims_overrides)
    return jwt.encode(claims, private_key, algorithm="ES256")


def _patch_jwk_client(monkeypatch, public_key) -> None:
    fake_signing_key = SimpleNamespace(key=public_key, algorithm_name="ES256")
    monkeypatch.setattr(security._jwk_client, "get_signing_key_from_jwt", lambda token: fake_signing_key)


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_valid_token_is_accepted(monkeypatch, keypair):
    private_key, public_key = keypair
    _patch_jwk_client(monkeypatch, public_key)

    claims = security.get_current_claims(_credentials(_make_token(private_key)))

    assert claims["email"] == "agent@example.com"
    assert claims["app_metadata"]["provider"] == "email"


def test_expired_token_is_rejected(monkeypatch, keypair):
    private_key, public_key = keypair
    _patch_jwk_client(monkeypatch, public_key)
    token = _make_token(private_key, expired=True)

    with pytest.raises(HTTPException) as exc_info:
        security.get_current_claims(_credentials(token))
    assert exc_info.value.status_code == 401


def test_wrong_audience_is_rejected(monkeypatch, keypair):
    private_key, public_key = keypair
    _patch_jwk_client(monkeypatch, public_key)
    token = _make_token(private_key, claims_overrides={"aud": "wrong-audience"})

    with pytest.raises(HTTPException) as exc_info:
        security.get_current_claims(_credentials(token))
    assert exc_info.value.status_code == 401


def test_wrong_issuer_is_rejected(monkeypatch, keypair):
    private_key, public_key = keypair
    _patch_jwk_client(monkeypatch, public_key)
    token = _make_token(private_key, claims_overrides={"iss": "https://evil.example.com/auth/v1"})

    with pytest.raises(HTTPException) as exc_info:
        security.get_current_claims(_credentials(token))
    assert exc_info.value.status_code == 401


def test_token_signed_by_a_different_key_is_rejected(monkeypatch, keypair):
    _, public_key = keypair  # the key we tell the app to trust
    forged_key = ec.generate_private_key(ec.SECP256R1())  # NOT the trusted key
    _patch_jwk_client(monkeypatch, public_key)
    token = _make_token(forged_key)

    with pytest.raises(HTTPException) as exc_info:
        security.get_current_claims(_credentials(token))
    assert exc_info.value.status_code == 401


def test_missing_credentials_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        security.get_current_claims(None)
    assert exc_info.value.status_code == 401
