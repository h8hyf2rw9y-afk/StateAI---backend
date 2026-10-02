import uuid

from pydantic import BaseModel

from app.schemas.common import ORMModel
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


class OrganizationCreate(BaseModel):
    """
    POST /me/organization's body — see app/api/routes/me.py. `name` is
    optional: a brand-new signup has no organization to name one after yet,
    so the route derives a reasonable default from the caller's own JWT
    claims (first_name/last_name or email) when this is omitted, rather
    than requiring a new form field just for onboarding to work.
    """

    name: str | None = None


class OrganizationRead(ORMModel):
    """GET /organization — just enough for the Settings page to show the real organization name (CurrentUser itself only carries organization_id, not its name, to keep get_current_org_user's per-request lookup a single-row fetch)."""

    id: uuid.UUID
    name: str
