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
from app.schemas.renova_follow_up import RenovaFollowUpSummary
from app.schemas.enums import (
    RenovaCaseStatus,
    RenovaDeedsStatus,
    RenovaDwellingType,
    RenovaMaritalStatus,
    RenovaOccupancyStatus,
    RenovaProposalType,
    RenovaPropertyTaxDebtUnit,
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
    "property_tax_debt_unit",
    "archived",
)

DEBT_FIELDS = ("property_tax_debt", "other_debt", "water_debt", "electricity_debt", "gas_debt")
FINANCIAL_FIELDS = (
    "final_offer",
    "proposal_type",
    "debt_coverage_amount",
    "owner_cash_offer",
    "market_value",
    *DEBT_FIELDS,
    "property_tax_debt_unit",
    "debt_owed_to",
    "owner_expected_amount",
    "currency",
)

PROPERTY_TAX_DEBT_MAX_YEARS = 60


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


class _PropertyTaxDebtUnitMixin(BaseModel):
    """
    When `property_tax_debt_unit` is explicitly "years" IN THIS SAME
    request, `property_tax_debt` must be a whole, reasonable number of years
    — not a peso amount with cents. Only checked when both fields are present
    together: a PATCH that sends just one of the two is left alone (the
    other's current stored value is unknown at validation time), same as
    every other partial-update field in this schema.
    """

    @model_validator(mode="after")
    def _valid_property_tax_debt_for_its_unit(self):
        unit = getattr(self, "property_tax_debt_unit", None)
        value = getattr(self, "property_tax_debt", None)
        if unit == "years" and value is not None:
            if value != value.to_integral_value():
                raise ValueError("Years must be a whole number.")
            if value > PROPERTY_TAX_DEBT_MAX_YEARS:
                raise ValueError(f"Years must be {PROPERTY_TAX_DEBT_MAX_YEARS} or fewer.")
        return self


class _ProposalModalityMixin(BaseModel):
    """
    Renova's structured proposal (RenovaCase.proposal_type +
    debt_coverage_amount + owner_cash_offer — see RENOVA_PROPOSAL_TYPES).
    Only checked when `proposal_type` is present IN THIS SAME request,
    using whichever of the two amounts are ALSO present here — same
    partial-PATCH limitation as _PropertyTaxDebtUnitMixin above. The real
    form always submits all three together, so this covers every
    request that actually sets or changes a proposal.
    """

    @model_validator(mode="after")
    def _valid_proposal_for_its_type(self):
        proposal_type = getattr(self, "proposal_type", None)
        if proposal_type is None:
            return self
        zero = Decimal("0")
        coverage = getattr(self, "debt_coverage_amount", None)
        cash = getattr(self, "owner_cash_offer", None)
        if proposal_type == "debt_only":
            if coverage is None or coverage <= zero:
                raise ValueError("debt_only requires a positive debt_coverage_amount.")
            if cash is not None and cash > zero:
                raise ValueError("debt_only cannot include a positive owner_cash_offer.")
        elif proposal_type == "debt_plus_cash":
            if coverage is None or coverage <= zero:
                raise ValueError("debt_plus_cash requires a positive debt_coverage_amount.")
            if cash is None or cash <= zero:
                raise ValueError("debt_plus_cash requires a positive owner_cash_offer.")
        elif proposal_type == "cash_only":
            if cash is None or cash <= zero:
                raise ValueError("cash_only requires a positive owner_cash_offer.")
            if coverage is not None and coverage > zero:
                raise ValueError("cash_only cannot include a positive debt_coverage_amount.")
        return self


class RenovaCaseBase(_ProposalModalityMixin, _PropertyTaxDebtUnitMixin, _BlankToNoneMixin):
    # Registro
    assigned_user_id: uuid.UUID
    entry_date: date
    source: RenovaSource = "whatsapp"
    status: RenovaCaseStatus = "new"
    # Hides this case from the default Leads -> Renova list. Only ever
    # meaningful once status is "rejected"/"cancelled" — see
    # RenovaCaseService.update, which enforces that and never trusts a
    # client-supplied True on a case in an active stage.
    archived: bool = False
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
    # Legacy total — see RenovaCase.final_offer's own docstring. Settable
    # directly only for a case that stays unclassified (proposal_type
    # null); once proposal_type is set, RenovaCaseService overwrites this
    # with total_proposal_value regardless of what a request sends here.
    final_offer: Money | None = None
    proposal_type: RenovaProposalType | None = None
    debt_coverage_amount: Money | None = None
    owner_cash_offer: Money | None = None
    market_value: Money | None = None
    property_tax_debt: Money | None = None
    property_tax_debt_unit: RenovaPropertyTaxDebtUnit = "mxn"
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


class RenovaCaseUpdate(_ProposalModalityMixin, _PropertyTaxDebtUnitMixin, _SecretFormatMixin, _BlankToNoneMixin):
    """
    All fields optional — PATCH semantics (see ContactUpdate). Sending
    `nss`/`credit_number` as null clears the stored value; omitting them
    leaves it untouched.
    """

    assigned_user_id: uuid.UUID | None = None
    entry_date: date | None = None
    source: RenovaSource | None = None
    status: RenovaCaseStatus | None = None
    archived: bool | None = None
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
    proposal_type: RenovaProposalType | None = None
    debt_coverage_amount: Money | None = None
    owner_cash_offer: Money | None = None
    market_value: Money | None = None
    property_tax_debt: Money | None = None
    property_tax_debt_unit: RenovaPropertyTaxDebtUnit | None = None
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
    archived: bool
    owner_name: str
    owner_phone: str
    # Moved here (from RenovaCaseRead-only) so the Leads -> Renova table can
    # show a "Dirección" column without a second request — a list row was
    # deliberately address-less before this; that's no longer the design.
    street_address: str | None
    neighborhood: str | None
    municipality: str | None
    postal_code: str | None
    dwelling_type: str | None
    is_duplex: bool
    currency: str
    final_offer: Decimal | None
    proposal_type: str | None
    debt_coverage_amount: Decimal | None
    owner_cash_offer: Decimal | None
    market_value: Decimal | None
    property_tax_debt: Decimal | None
    property_tax_debt_unit: str
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
        # property_tax_debt is only a peso figure — and only summable —
        # when captured in MXN. When it's a number of YEARS owed instead
        # (property_tax_debt_unit == "years"), it's excluded here entirely;
        # years and pesos can't be added together.
        debts = [self.property_tax_debt if self.property_tax_debt_unit == "mxn" else None]
        debts += [getattr(self, f) for f in DEBT_FIELDS if f != "property_tax_debt"]
        return sum_debts(debts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_proposal_value(self) -> Decimal | None:
        """
        debt_coverage_amount + owner_cash_offer, computed exactly once,
        here — the ONLY place this is calculated; the frontend, the share
        card and Renova Chat all display this value, never recompute it.
        None (not zero) when NEITHER amount has been captured at all, so a
        case that simply has no proposal yet never reads as "$0 proposal".
        A proposal with a real $0 cash side (debt_only) still sums fine:
        the amount that IS present is never treated as absent.
        """
        coverage = self.debt_coverage_amount
        cash = self.owner_cash_offer
        if coverage is None and cash is None:
            return None
        return (coverage or Decimal("0")) + (cash or Decimal("0"))


class RenovaCaseListItem(_RenovaCaseFields):
    """
    The lean row the Leads → Renova table needs. Deliberately excludes the
    spouse, deeds, narrative and (of course) NSS / credit-number fields —
    not even masked: a listing never carries sensitive data.
    """

    follow_up: RenovaFollowUpSummary = Field(default_factory=RenovaFollowUpSummary)


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


class RenovaCaseBucketCounts(BaseModel):
    """
    GET /renova/cases/counts — one cheap grouped query, never the case rows
    themselves, so the three Leads -> Renova tabs can show a count without
    fetching (let alone filtering client-side) every case in an
    organization that might have hundreds.
    """

    active: int
    closed: int
    rejected: int
    cancelled: int
    archived: int


class RenovaPipelineCase(ORMModel):
    """
    One card on the Renova Kanban board (GET /renova/pipeline) — as lean as
    RenovaCaseListItem, and for the same reason: never NSS, credit number,
    INE images or any ciphertext, not even masked. Field names are exactly
    the model's own (final_offer, other_debt, property_tax_debt_unit, …) —
    no renamed aliases.
    """

    id: uuid.UUID
    owner_name: str
    owner_phone: str
    status: str
    assigned_user_id: uuid.UUID | None
    dwelling_type: str | None
    is_duplex: bool
    final_offer: Decimal | None
    market_value: Decimal | None
    other_debt: Decimal | None
    property_tax_debt: Decimal | None
    property_tax_debt_unit: str
    owner_expected_amount: Decimal | None
    updated_at: datetime


class RenovaPipelineStage(BaseModel):
    """One Kanban column: a status from RENOVA_PIPELINE_STAGES and its cards, in that stage's order."""

    status: str
    cases: list[RenovaPipelineCase]


class RenovaPipelineResponse(BaseModel):
    """Every active-flow case, already grouped by stage in board order — one request, no client-side pagination gaps."""

    stages: list[RenovaPipelineStage]


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
