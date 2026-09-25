import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin

# Every monetary column, in one place: each gets a non-negative CHECK below
# and is what app/schemas/renova_case.py sums for `total_debt`.
MONEY_COLUMNS = (
    "final_offer",
    "market_value",
    "property_tax_debt",
    "other_debt",
    "water_debt",
    "electricity_debt",
    "gas_debt",
    "owner_expected_amount",
)


class RenovaCase(Base, UUIDPKMixin, TimestampMixin):
    """
    One Renova evaluation file: a potential purchase of a property for
    house-flipping, captured from a conversation (initially WhatsApp) with
    the owner.

    This is NOT a Contact, a lead, a Buyer Requirement, a Property Interest,
    an Opportunity, or an inventory Property, and it deliberately has no
    foreign key to any of them (or to contact_roles): Renova is a different
    business model that only shares the *Leads page* in the UI. The owner's
    identity lives right here as plain columns, so nothing a Renova case
    holds can ever appear in the traditional CRM's lists, AI context, or
    matching — and vice versa. The only relations are to the organization
    (isolation) and to the responsible advisor / creator (`users`).

    Sensitive data: `nss_encrypted` and `credit_number_encrypted` hold Fernet
    ciphertext only (app/core/crypto.py) — never the plaintext, never
    returned by any endpoint in full, never written to AuditLog, never read
    by an AI agent. "Credit number" is spelled out everywhere (the source
    material's "NC" is ambiguous). Marital/spouse data and every money field
    are likewise never sent to AI agents.

    Money is Numeric(14, 2) (never float), MXN by default, optional while a
    case is still being evaluated. `total_debt` is derived on read, not
    stored — see RenovaCaseRead.
    """

    __tablename__ = "renova_cases"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL (not CASCADE / not NOT NULL): deleting a user account must not
    # erase a purchase-evaluation file. The API still requires an advisor on
    # create — this only governs what happens if that user is removed later.
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- Registro ---------------------------------------------------------
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Soft enums (app/schemas/enums.py): source, status.
    source: Mapped[str] = mapped_column(nullable=False, default="whatsapp", server_default="whatsapp")
    status: Mapped[str] = mapped_column(nullable=False, default="new", server_default="new")

    # --- Propietario ------------------------------------------------------
    owner_name: Mapped[str] = mapped_column(nullable=False)
    owner_phone: Mapped[str] = mapped_column(nullable=False)
    # Soft enum: marital status when the owner ACQUIRED the property.
    marital_status: Mapped[str | None] = mapped_column(nullable=True)
    spouse_name: Mapped[str | None] = mapped_column(nullable=True)
    spouse_phone: Mapped[str | None] = mapped_column(nullable=True)
    # SENSITIVE — ciphertext only. See the class docstring.
    nss_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ine_front_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ine_back_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Ubicación --------------------------------------------------------
    # Plain columns on the case (a Renova property is not an inventory
    # Property — see the class docstring). All optional while a case is being
    # captured. Added in migration b81f4c2e7a63.
    street_address: Mapped[str | None] = mapped_column(nullable=True)  # "Calle y número"
    neighborhood: Mapped[str | None] = mapped_column(nullable=True)  # "Colonia"
    municipality: Mapped[str | None] = mapped_column(nullable=True)  # "Municipio"
    postal_code: Mapped[str | None] = mapped_column(nullable=True)  # 5-digit Mexican CP

    # --- Inmueble ---------------------------------------------------------
    # Soft enums: dwelling_type (base type — "house"/"apartment" only),
    # occupancy_status ("Situación actual"), has_deeds. `is_duplex` is a
    # separate boolean CONFIGURATION, not a third dwelling_type value: a
    # duplex is still fundamentally a house or an apartment, so "Casa" +
    # is_duplex=True and "Departamento" + is_duplex=True are both valid and
    # distinct from a plain "Casa"/"Departamento" (see migration
    # b2f7a4c9d310, which also carries forward any case previously saved with
    # the old dwelling_type="duplex" value).
    dwelling_type: Mapped[str | None] = mapped_column(nullable=True)
    is_duplex: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    occupancy_status: Mapped[str | None] = mapped_column(nullable=True)
    floors: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)  # half-baths are common
    bedrooms: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_deeds: Mapped[str] = mapped_column(nullable=False, default="unknown", server_default="unknown")
    deeds_holder_name: Mapped[str | None] = mapped_column(nullable=True)

    # --- Finanzas ---------------------------------------------------------
    currency: Mapped[str] = mapped_column(nullable=False, default="MXN", server_default="MXN")
    final_offer: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    property_tax_debt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    other_debt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    water_debt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    electricity_debt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    gas_debt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    debt_owed_to: Mapped[str | None] = mapped_column(nullable=True)
    owner_expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # --- Motivación y evaluación -----------------------------------------
    sale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_questions: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_situation: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        *(CheckConstraint(f"{col} IS NULL OR {col} >= 0", name=f"ck_renova_cases_{col}_non_negative") for col in MONEY_COLUMNS),
        CheckConstraint("floors IS NULL OR floors >= 0", name="ck_renova_cases_floors_non_negative"),
        CheckConstraint("bathrooms IS NULL OR bathrooms >= 0", name="ck_renova_cases_bathrooms_non_negative"),
        CheckConstraint("bedrooms IS NULL OR bedrooms >= 0", name="ck_renova_cases_bedrooms_non_negative"),
        Index("ix_renova_cases_organization_id", "organization_id"),
        Index("ix_renova_cases_org_status", "organization_id", "status"),
        Index("ix_renova_cases_org_assigned_user", "organization_id", "assigned_user_id"),
        Index("ix_renova_cases_org_entry_date", "organization_id", "entry_date"),
    )
