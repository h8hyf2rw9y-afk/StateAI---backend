import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.schemas.common import ORMModel
from app.schemas.enums import UserRole


class MemberRenovaCaseCounts(BaseModel):
    """How many Renova cases are assigned to one member, by the same three buckets as the Leads -> Renova tabs."""

    active: int = 0
    closed: int = 0
    archived: int = 0


class OrganizationMemberRead(ORMModel):
    """One row of the admin "Usuarios" list. Never anything from auth beyond the email copied at sign-up."""

    id: uuid.UUID
    email: str | None
    role: str
    is_active: bool
    deactivated_at: datetime | None
    created_at: datetime
    renova_cases: MemberRenovaCaseCounts = MemberRenovaCaseCounts()


class OrganizationMemberUpdate(BaseModel):
    is_active: bool | None = None
    role: UserRole | None = None

    @model_validator(mode="after")
    def has_a_change(self) -> "OrganizationMemberUpdate":
        if self.is_active is None and self.role is None:
            raise ValueError("At least one member change is required.")
        return self
