import uuid

from pydantic import BaseModel

from app.schemas.enums import UserRole


class CurrentUser(BaseModel):
    """
    The authenticated caller, assembled from a verified Supabase JWT's
    claims plus this app's own `users` bridge row. See app/core/security.py.
    """

    id: uuid.UUID  # Supabase auth.users.id == our users.id
    email: str | None
    organization_id: uuid.UUID
    role: UserRole
    provider: str | None  # from the JWT's app_metadata.provider — "email" or "google"
