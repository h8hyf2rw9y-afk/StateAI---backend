import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.organization import User
from app.schemas.user import CurrentUser

bearer_scheme = HTTPBearer(auto_error=False)

# One client for the process lifetime — it caches Supabase's public keys
# internally and re-fetches them on a cache miss (e.g. after key rotation).
_jwk_client = PyJWKClient(settings.jwks_url)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    Verifies a Supabase Auth access token against the project's JWKS
    endpoint (asymmetric signing keys — see the plan for why this is used
    instead of the legacy shared-secret approach) and returns its claims.

    This is the actual security boundary for this backend: unlike the
    frontend's proxy.ts (an optimistic, UX-only check), every claim here is
    cryptographically verified against Supabase's own public keys.
    """
    if credentials is None:
        raise _UNAUTHENTICATED

    token = credentials.credentials
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[signing_key.algorithm_name],
            audience=settings.supabase_jwt_aud,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError:
        # Never leak *why* verification failed (expired vs. malformed vs.
        # wrong signature) — that's internal detail, not the caller's business.
        raise _UNAUTHENTICATED

    return claims


def get_current_org_user(
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """
    Resolves a verified token to (user_id, organization_id, role) by
    looking up this app's own `users` bridge row. Every protected route
    depends on this (not get_current_claims directly) so every query can be
    scoped by organization_id — see the repositories.
    """
    sub = claims.get("sub")
    if not sub:
        raise _UNAUTHENTICATED

    user_id = uuid.UUID(sub)
    user_row = db.get(User, user_id)
    if user_row is None:
        # A real, valid Supabase session — just not provisioned into an
        # organization yet. Distinct from 401 on purpose: the caller IS who
        # they say they are, they just can't use the CRM yet.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not yet assigned to an organization.",
        )

    app_metadata = claims.get("app_metadata") or {}
    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        organization_id=user_row.organization_id,
        role=user_row.role,  # type: ignore[arg-type]
        provider=app_metadata.get("provider"),
    )
