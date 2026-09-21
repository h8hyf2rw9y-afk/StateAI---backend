import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.common import ORMModel
from app.schemas.enums import (
    RenovaCaseStatus,
    RenovaDeedsStatus,
    RenovaDwellingType,
    RenovaMaritalStatus,
    RenovaSource,
)

# --- Field types -----------------------------------------------------------
# Limits are "reasonable, not clever": long enough for real WhatsApp-derived
# notes, short enough that a pasted conversation dump or a hostile payload
# can't bloat a row. Money is Decimal (never float), non-negative, and capped
# to what the Numeric(14, 2) column can hold.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]

# NSS / credit number: letters, digits and hyphens only, so validation can
# never need to echo the value back. (A Mexican NSS is 11 digits and an
# Infonavit credit number 10, but other institutions differ — kept loose.)
SecretIdentifier = Annotated[SecretStr, Field(min_length=4, max_length=30)]
_SECRET_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9\-]+$")

_OPTIONAL_TEXT_FIELDS = (
    "spouse_name",
    "spouse_phone",
    "deeds_holder_name",
    "debt_owed_to",
    "conditions",
    "sale_reason",
    "key_questions",
    "general_situation",
    "notes",
)

# Columns that are NOT NULL in the database: a PATCH may change them but must
# never explicitly null them.
_REQUIRED_COLUMNS = ("owner_name", "owner_phone", "entry_date", "assigned_user_id", "source", "status", "has_deeds", "currency")

DEBT_FIELDS = ("property_tax_debt", "other_debt", "water_debt", "electricity_debt", "gas_debt")
FINANCIAL_FIELDS = (
    "final_offer",
    "market_value",
    *DEBT_FIELDS,
    "debt_owed_to",
    "owner_expected_amount",
    "currency",
)


def sum_debts(values: list[Decimal | None]) -> Decimal | None:
    """
    total_debt = property_tax + other + water + electricity + gas. Derived,
    never stored. None when NO debt has been captured at all (so the UI can
    show "—" instead of a misleading $0), otherwise a plain sum treating the
    not-yet-captured ones as zero.
    """
    captured = [v for v in values if v is not None]
    if not captured:
        return None
    return sum(captured, Decimal("0"))


class _BlankToNoneMixin(BaseModel):
    """Empty/whitespace-only optional text arrives from forms as ""; store it as NULL instead."""

    @field_validator(*_OPTIONAL_TEXT_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class _SecretFormatMixin(BaseModel):
    """pydantic can't apply `pattern` to a SecretStr, so the format check lives here — and its error message deliberately never includes the value."""

    @field_validator("nss", "credit_number", mode="after", check_fields=False)
    @classmethod
    def _valid_format(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not _SECRET_IDENTIFIER_RE.match(value.get_secret_value()):
            raise ValueError("Only letters, digits and hyphens are allowed.")
        return value


class RenovaCaseBase(_BlankToNoneMixin):
    # Registro
    assigned_user_id: uuid.UUID
    entry_date: date
    source: RenovaSource = "whatsapp"
    status: RenovaCaseStatus = "new"
    # Propietario
    owner_name: Name
    owner_phone: Phone
    marital_status: RenovaMaritalStatus | None = None
    spouse_name: Name | None = None
    spouse_phone: Phone | None = None
    # Inmueble
    dwelling_type: RenovaDwellingType | None = None
    floors: int | None = Field(default=None, ge=0, le=100)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=99, max_digits=3, decimal_places=1)
    bedrooms: int | None = Field(default=None, ge=0, le=99)
    conditions: LongText | None = None
    has_deeds: RenovaDeedsStatus = "unknown"
    deeds_holder_name: Name | None = None
    # Finanzas
    currency: str = Field(default="MXN", pattern=r"^[A-Z]{3}$")
    final_offer: Money | None = None
    market_value: Money | None = None
    property_tax_debt: Money | None = None
    other_debt: Money | None = None
    water_debt: Money | None = None
    electricity_debt: Money | None = None
    gas_debt: Money | None = None
    debt_owed_to: ShortText | None = None
    owner_expected_amount: Money | None = None
    # Motivación y evaluación
    sale_reason: LongText | None = None
    key_questions: LongText | None = None
    general_situation: LongText | None = None
    notes: LongText | None = None


class RenovaCaseCreate(_SecretFormatMixin, RenovaCaseBase):
    """
    `nss` / `credit_number` are write-only and SecretStr, so they print as
    '**********' in any repr/log and are never part of a Read schema — the
    only way back out is the masked display.
    """

    nss: SecretIdentifier | None = None
    credit_number: SecretIdentifier | None = None


class RenovaCaseUpdate(_SecretFormatMixin, _BlankToNoneMixin):
    """
    All fields optional — PATCH semantics (see ContactUpdate). Sending
    `nss`/`credit_number` as null clears the stored value; omitting them
    leaves it untouched.
    """

    assigned_user_id: uuid.UUID | None = None
    entry_date: date | None = None
    source: RenovaSource | None = None
    status: RenovaCaseStatus | None = None
    owner_name: Name | None = None
    owner_phone: Phone | None = None
    marital_status: RenovaMaritalStatus | None = None
    spouse_name: Name | None = None
    spouse_phone: Phone | None = None
    nss: SecretIdentifier | None = None
    credit_number: SecretIdentifier | None = None
    dwelling_type: RenovaDwellingType | None = None
    floors: int | None = Field(default=None, ge=0, le=100)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=99, max_digits=3, decimal_places=1)
    bedrooms: int | None = Field(default=None, ge=0, le=99)
    conditions: LongText | None = None
    has_deeds: RenovaDeedsStatus | None = None
    deeds_holder_name: Name | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    final_offer: Money | None = None
    market_value: Money | None = None
    property_tax_debt: Money | None = None
    other_debt: Money | None = None
    water_debt: Money | None = None
    electricity_debt: Money | None = None
    gas_debt: Money | None = None
    debt_owed_to: ShortText | None = None
    owner_expected_amount: Money | None = None
    sale_reason: LongText | None = None
    key_questions: LongText | None = None
    general_situation: LongText | None = None
    notes: LongText | None = None

    @model_validator(mode="after")
    def _no_null_for_required_columns(self) -> "RenovaCaseUpdate":
        for field in _REQUIRED_COLUMNS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class _RenovaCaseFields(ORMModel):
    """Fields shared by the list item and the full read — never anything sensitive."""

    id: uuid.UUID
    organization_id: uuid.UUID
    assigned_user_id: uuid.UUID | None
    entry_date: date
    source: str
    status: str
    owner_name: str
    owner_phone: str
    dwelling_type: str | None
    currency: str
    final_offer: Decimal | None
    market_value: Decimal | None
    property_tax_debt: Decimal | None
    other_debt: Decimal | None
    water_debt: Decimal | None
    electricity_debt: Decimal | None
    gas_debt: Decimal | None
    owner_expected_amount: Decimal | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debt(self) -> Decimal | None:
        return sum_debts([getattr(self, f) for f in DEBT_FIELDS])


class RenovaCaseListItem(_RenovaCaseFields):
    """
    The lean row the Leads → Renova table needs. Deliberately excludes the
    spouse, deeds, narrative and (of course) NSS / credit-number fields —
    not even masked: a listing never carries sensitive data.
    """


class RenovaCaseRead(_RenovaCaseFields):
    """
    The detail/create/update response. NSS and credit number appear ONLY as
    masked strings ("••••1234"; null when nothing is stored) — the full
    values are unrecoverable through the API by design.
    """

    created_by_user_id: uuid.UUID | None
    marital_status: str | None
    spouse_name: str | None
    spouse_phone: str | None
    floors: int | None
    bathrooms: Decimal | None
    bedrooms: int | None
    conditions: str | None
    has_deeds: str
    deeds_holder_name: str | None
    debt_owed_to: str | None
    sale_reason: str | None
    key_questions: str | None
    general_situation: str | None
    notes: str | None
    # Not ORM attributes: filled in by RenovaCaseService from the encrypted
    # columns via app/core/crypto.mask_encrypted.
    nss_masked: str | None = None
    credit_number_masked: str | None = None
