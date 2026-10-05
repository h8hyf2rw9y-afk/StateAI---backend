"""
The Renova Chat "readable field" mechanism (Read V2): ONE dict mapping
every allow-listed RenovaReadableField (app/schemas/renova_chat.py) to the
function that turns one case into the answer sentence for it.

This is the single source of truth both the classifier's system prompt
(app/renova_chat/interpreter.py, which lists these exact names so the LLM
never has to invent a column name) and RenovaChatService._answer() read
from. Adding a new readable field is one new dict entry here -- never a
new Literal value in three places plus a new `if` branch, which is the
"50 brittle intents" failure mode this phase exists to avoid.

Every resolver takes the ORM object directly. None of them is ever called
with anything but a case that has already been org-scoped and resolved by
RenovaChatService -- this module has no database access of its own and
never will; it only formats what it's handed. NSS, credit_number, and
both INE sides have no resolver here and never will (see
app/services/renova_extraction.py's RENOVA_FIELDS_NEVER_SENT_TO_LLM --
the same boundary, enforced in the read direction by simple omission:
there is no column name in this dict with no entry for them).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

from app.models.renova_case import RenovaCase

NOT_REGISTERED = "No está registrado."

STATUS_LABELS: dict[str, str] = {
    "draft": "Borrador",
    "new": "Nuevo",
    "reviewing": "En revisión",
    "offer_preparation": "Preparación de oferta",
    "offer_sent": "Oferta enviada",
    "negotiating": "Negociando",
    "accepted": "Aceptado",
    "purchased": "Comprado",
    "rejected": "Rechazado",
    "cancelled": "Cancelado",
}
DWELLING_LABELS: dict[str, str] = {"house": "Casa", "apartment": "Departamento"}
OCCUPANCY_LABELS: dict[str, str] = {
    "lives_there": "Vive ahí",
    "vacant": "Deshabitada",
    "rented": "Rentada",
    "lent": "Prestada",
    "other": "Otra",
}
DEEDS_LABELS: dict[str, str] = {"yes": "Sí", "no": "No", "unknown": "Desconocido"}
MARITAL_LABELS: dict[str, str] = {
    "single": "Soltero(a)",
    "married_conjugal_partnership": "Casado(a) — sociedad conyugal",
    "married_separate_property": "Casado(a) — separación de bienes",
    "divorced": "Divorciado(a)",
    "widowed": "Viudo(a)",
    "common_law": "Unión libre",
    "unknown": "No especificado",
}
SOURCE_LABELS: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "phone": "Teléfono",
    "referral": "Referido",
    "website": "Sitio web",
    "other": "Otro",
}


def format_money(value: Decimal | None, currency: str = "MXN") -> str:
    if value is None:
        return "No está registrado"
    symbol = "$" if currency == "MXN" else f"{currency} "
    return f"{symbol}{value:,.2f}"


def format_property_tax_debt(case: RenovaCase) -> str:
    """A YEARS figure is never shown as a peso amount, and vice versa -- mirrors the frontend's formatRenovaPropertyTaxDebt."""
    if case.property_tax_debt is None:
        return "No está registrado"
    if case.property_tax_debt_unit == "years":
        years = case.property_tax_debt
        whole = int(years) if years == years.to_integral_value() else years
        return f"{whole} {'año' if whole == 1 else 'años'}"
    return format_money(case.property_tax_debt, case.currency)


def _address(case: RenovaCase) -> str:
    parts = [case.street_address, case.neighborhood, case.municipality, case.postal_code]
    return ", ".join(part for part in parts if part)


def _debt_field(label: str, column: str) -> Callable[[RenovaCase], str]:
    def resolver(case: RenovaCase) -> str:
        value = getattr(case, column)
        if value is None:
            return f"{case.owner_name} no tiene {label} registrado."
        return f"El adeudo de {label} de {case.owner_name} es {format_money(value, case.currency)}."

    return resolver


def _enum_field(label: str, column: str, labels: dict[str, str]) -> Callable[[RenovaCase], str]:
    def resolver(case: RenovaCase) -> str:
        value = getattr(case, column)
        if not value:
            return f"{label} de {case.owner_name} no está registrado(a)."
        return f"{label} de {case.owner_name}: {labels.get(value, value)}."

    return resolver


def _text_field(label: str, column: str) -> Callable[[RenovaCase], str]:
    def resolver(case: RenovaCase) -> str:
        value = getattr(case, column)
        if not value:
            return f"No tengo {label} registrado para {case.owner_name}."
        return f"{label.capitalize()} de {case.owner_name}: {value}"

    return resolver


def _optional_int_field(label: str, column: str, unit: str) -> Callable[[RenovaCase], str]:
    def resolver(case: RenovaCase) -> str:
        value = getattr(case, column)
        if value is None:
            return f"{case.owner_name} no tiene {label} registrado(a)."
        return f"{case.owner_name} tiene {value} {unit}."

    return resolver


def _bool_field(label_true: str, label_false: str, column: str) -> Callable[[RenovaCase], str]:
    def resolver(case: RenovaCase) -> str:
        return label_true.format(name=case.owner_name) if getattr(case, column) else label_false.format(name=case.owner_name)

    return resolver


# The single source of truth: RenovaReadableField -> formatter. Every key
# here must also be a value of RenovaReadableField in
# app/schemas/renova_chat.py (see tests/test_renova_chat_fields.py).
RENOVA_CASE_FIELD_RESOLVERS: dict[str, Callable[[RenovaCase], str]] = {
    # Kept for the 7 pre-existing fixed intents, which route here too.
    "phone": lambda case: f"El teléfono de {case.owner_name} es {case.owner_phone}.",
    "address": lambda case: (
        f"La dirección registrada de {case.owner_name} es {_address(case)}."
        if _address(case)
        else f"{case.owner_name} no tiene una dirección registrada."
    ),
    "status": lambda case: f"{case.owner_name} está en la etapa “{STATUS_LABELS.get(case.status, case.status)}” de Renova.",
    "entry_date": lambda case: f"{case.owner_name} ingresó a Renova el {case.entry_date.strftime('%d/%m/%Y')}.",
    "market_value": lambda case: f"El valor de mercado registrado de {case.owner_name} es {format_money(case.market_value, case.currency)}.",
    "final_offer": lambda case: f"La propuesta final registrada para {case.owner_name} es {format_money(case.final_offer, case.currency)}.",
    "expected_amount": lambda case: f"{case.owner_name} espera recibir {format_money(case.owner_expected_amount, case.currency)}.",
    # New in Read V2.
    "dwelling_type": _enum_field("El tipo de vivienda", "dwelling_type", DWELLING_LABELS),
    "is_duplex": _bool_field("La propiedad de {name} es dúplex.", "La propiedad de {name} no es dúplex.", "is_duplex"),
    "occupancy_status": _enum_field("La situación actual", "occupancy_status", OCCUPANCY_LABELS),
    "floors": _optional_int_field("plantas", "floors", "plantas"),
    "bathrooms": _optional_int_field("baños", "bathrooms", "baños"),
    "bedrooms": _optional_int_field("recámaras", "bedrooms", "recámaras"),
    "conditions": _text_field("las condiciones de la casa", "conditions"),
    "has_deeds": _enum_field("Escrituras", "has_deeds", DEEDS_LABELS),
    "deeds_holder_name": _text_field("a nombre de quién están las escrituras", "deeds_holder_name"),
    "sale_reason": _text_field("el motivo de venta", "sale_reason"),
    "general_situation": _text_field("la situación general", "general_situation"),
    "notes": _text_field("notas", "notes"),
    "marital_status": _enum_field("El estado civil", "marital_status", MARITAL_LABELS),
    "spouse_name": _text_field("el nombre del cónyuge", "spouse_name"),
    "source": _enum_field("El origen del lead", "source", SOURCE_LABELS),
    "property_tax_debt": lambda case: f"El adeudo de predial de {case.owner_name} es {format_property_tax_debt(case)}.",
    "water_debt": _debt_field("agua", "water_debt"),
    "electricity_debt": _debt_field("luz", "electricity_debt"),
    "gas_debt": _debt_field("gas", "gas_debt"),
    "other_debt": _debt_field("otros adeudos", "other_debt"),
}
