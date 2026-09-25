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
    RenovaOccupancyStatus,
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

# NSS / credit number are IDENTIFIERS (never numbers: leading zeros matter),
# captured as digits, optionally grouped with spaces or hyphens for readability
# ("12 34-56"), and normalized to bare digits BEFORE validation and encryption.
# Validation messages are static — they never contain what was typed.
#   * NSS: exactly 11 digits (the IMSS social-security number).
#   * Credit number: digits only, 6-20 of them. Infonavit uses 10, but other
#     institutions differ, so only a sane range is enforced.
NSS_LENGTH = 11
CREDIT_NUMBER_MIN_LENGTH = 6
CREDIT_NUMBER_MAX_LENGTH = 20
_MAX_RAW_SECRET_LENGTH = 60  # before normalization, so a hostile payload is cut off early
SecretIdentifier = SecretStr
_SEPARATORS_RE = re.compile(r"[\s\-]")
_DIGITS_RE = re.compile(r"^[0-9]+$")

# Mexican postal code: exactly five digits.
PostalCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{5}$")]

_OPTIONAL_TEXT_FIELDS = (
    "street_address",
    "neighborhood",
    "municipality",
    "postal_code",
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
_REQUIRED_COLUMNS = (
    "owner_name",
    "owner_phone",
    "entry_date",
    "assigned_user_id",
    "source",
    "status",
    "has_deeds",
    "currency",
    "is_duplex",
)

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
    """
    pydantic can't apply `pattern` to a SecretStr, so normalization and the
    format check live here. Anything that is not digits — including a masked
    display value like "•••••••4821" or a placeholder of asterisks — is
    rejected, so a mask can never be stored as if it were the real number.
    """

    @field_validator("nss", "credit_number", mode="before", check_fields=False)
    @classmethod
    def _normalize(cls, value):
        if value is None:
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            raise ValueError("Must be text made of digits.")
        if len(raw) > _MAX_RAW_SECRET_LENGTH:
            raise ValueError("Value is too long.")
        return _SEPARATORS_RE.sub("", raw)

    @field_validator("nss", mode="after", check_fields=False)
    @classmethod
    def _valid_nss(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            digits = value.get_secret_value()
            if not _DIGITS_RE.match(digits) or len(digits) != NSS_LENGTH:
                raise ValueError(f"NSS must contain exactly {NSS_LENGTH} digits.")
        return value

    @field_validator("credit_number", mode="after", check_fields=False)
    @classmethod
    def _valid_credit_number(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            digits = value.get_secret_value()
            if not _DIGITS_RE.match(digits) or not CREDIT_NUMBER_MIN_LENGTH <= len(digits) <= CREDIT_NUMBER_MAX_LENGTH:
                raise ValueError(
                    f"Credit number must contain {CREDIT_NUMBER_MIN_LENGTH} to {CREDIT_NUMBER_MAX_LENGTH} digits."
                )
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
    # Ubicación
    street_address: ShortText | None = None
    neighborhood: ShortText | None = None
    municipality: ShortText | None = None
    postal_code: PostalCode | None = None
    # Inmueble
    dwelling_type: RenovaDwellingType | None = None
    is_duplex: bool = False
    occupancy_status: RenovaOccupancyStatus | None = None
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
    street_address: ShortText | None = None
    neighborhood: ShortText | None = None
    municipality: ShortText | None = None
    postal_code: PostalCode | None = None
    dwelling_type: RenovaDwellingType | None = None
    is_duplex: bool | None = None
    occupancy_status: RenovaOccupancyStatus | None = None
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
    is_duplex: bool
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
    street_address: str | None
    neighborhood: str | None
    municipality: str | None
    postal_code: str | None
    occupancy_status: str | None
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
    has_nss: bool = False
    has_credit_number: bool = False


class RenovaSensitiveData(BaseModel):
    """
    The ONLY schema that carries the full NSS / credit number. Returned solely
    by GET /renova/cases/{id}/sensitive-data (authorized, audited, no-store) —
    never part of any other response, listing, snapshot or log.
    """

    nss: str | None = None
    credit_number: str | None = None

    def __repr__(self) -> str:  # never let a stray print/log show the values
        return "RenovaSensitiveData(nss=<hidden>, credit_number=<hidden>)"

    __str__ = __repr__


class RenovaIneImage(BaseModel):
    # A JPEG/PNG/WebP data URL. The service validates decoded bytes and size.
    image: str

    def __repr__(self) -> str:
        return "RenovaIneImage(image=<hidden>)"

    __str__ = __repr__
