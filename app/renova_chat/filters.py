"""
The Renova Chat "filtered read" mechanism (Read V2): turns one
RenovaCaseFilter (app/schemas/renova_chat.py) into a SQLAlchemy WHERE
clause, deterministically, with no string formatting into SQL anywhere.

`RenovaCaseFilter.field`/`.operator` are already closed Pydantic Literals,
so the model can never name an arbitrary column or operator -- but a
*valid* field and a *valid* operator can still be the WRONG pairing (e.g.
"is_duplex" with "equals" instead of "is_true"), or an `equals` value that
isn't one of the real enum values. `_VALID_OPERATORS_BY_FIELD` and
`build_filter_clause` are the second, semantic layer of validation: an
invalid combination returns None rather than guessing, and
RenovaChatService treats that exactly like an unsupported question.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement

from app.models.renova_case import RenovaCase
from app.schemas.enums import RENOVA_CASE_STATUSES, RENOVA_DEEDS_STATUSES
from app.schemas.renova_chat import RenovaCaseFilter

_VALID_OPERATORS_BY_FIELD: dict[str, tuple[str, ...]] = {
    "status": ("equals",),
    "municipality": ("equals",),
    "is_duplex": ("is_true", "is_false"),
    "has_deeds": ("equals",),
    "has_property_tax_debt": ("exists",),
    "has_water_debt": ("exists",),
    "has_electricity_debt": ("exists",),
    "has_gas_debt": ("exists",),
    "has_other_debt": ("exists",),
}

_DEBT_COLUMNS: dict[str, str] = {
    "has_property_tax_debt": "property_tax_debt",
    "has_water_debt": "water_debt",
    "has_electricity_debt": "electricity_debt",
    "has_gas_debt": "gas_debt",
    "has_other_debt": "other_debt",
}


def build_filter_clause(filter_: RenovaCaseFilter) -> ColumnElement[bool] | None:
    """Returns the WHERE clause for one valid filter, or None if the field/operator/value combination isn't valid."""
    allowed_operators = _VALID_OPERATORS_BY_FIELD.get(filter_.field)
    if allowed_operators is None or filter_.operator not in allowed_operators:
        return None

    if filter_.field == "status":
        if filter_.value not in RENOVA_CASE_STATUSES:
            return None
        return RenovaCase.status == filter_.value

    if filter_.field == "municipality":
        if not filter_.value:
            return None
        return RenovaCase.municipality.ilike(f"%{filter_.value}%")

    if filter_.field == "is_duplex":
        return RenovaCase.is_duplex.is_(filter_.operator == "is_true")

    if filter_.field == "has_deeds":
        if filter_.value not in RENOVA_DEEDS_STATUSES:
            return None
        return RenovaCase.has_deeds == filter_.value

    column = getattr(RenovaCase, _DEBT_COLUMNS[filter_.field])
    return column.isnot(None)


def describe_filter(filter_: RenovaCaseFilter) -> str:
    """A short Spanish phrase for the filter, used in list/count answers (e.g. "en Negociando", "con adeudo de agua")."""
    if filter_.field == "status":
        from app.renova_chat.fields import STATUS_LABELS

        return f"en {STATUS_LABELS.get(filter_.value or '', filter_.value)}"
    if filter_.field == "municipality":
        return f"en {filter_.value}"
    if filter_.field == "is_duplex":
        return "con casa dúplex" if filter_.operator == "is_true" else "sin casa dúplex"
    if filter_.field == "has_deeds":
        from app.renova_chat.fields import DEEDS_LABELS

        return f"con escrituras: {DEEDS_LABELS.get(filter_.value or '', filter_.value)}"
    labels = {
        "has_property_tax_debt": "con adeudo de predial",
        "has_water_debt": "con adeudo de agua",
        "has_electricity_debt": "con adeudo de luz",
        "has_gas_debt": "con adeudo de gas",
        "has_other_debt": "con otro adeudo",
    }
    return labels.get(filter_.field, filter_.field)
