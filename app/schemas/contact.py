import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.schemas.common import ORMModel
from app.schemas.enums import ContactRoleKey, ContactSource, PreferredContactMethod


class ContactBase(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    preferred_contact_method: PreferredContactMethod | None = None
    source: ContactSource | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> "ContactBase":
        if not self.email and not self.phone:
            raise ValueError("At least one of email or phone is required.")
        return self


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    """All fields optional — PATCH semantics. Deliberately doesn't reuse the email/phone validator: a partial update shouldn't have to resend both."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    preferred_contact_method: PreferredContactMethod | None = None
    source: ContactSource | None = None
    notes: str | None = None


class RoleRead(ORMModel):
    role_key: str


class ContactRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    preferred_contact_method: str | None
    source: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleRead] = []


class ContactRoleAssign(BaseModel):
    role_key: ContactRoleKey
