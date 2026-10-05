"""
app/renova_chat/fields.py: the single dict mapping every allow-listed
RenovaReadableField to its formatter. These tests cover the dict directly
(no LLM, no HTTP) -- app/tests/test_renova_chat.py covers it end to end
through the actual chat endpoint.
"""

from datetime import date
from decimal import Decimal

from app.models.renova_case import RenovaCase
from app.renova_chat.fields import RENOVA_CASE_FIELD_RESOLVERS, format_property_tax_debt
from app.schemas.renova_chat import RenovaReadableField
from app.services.renova_extraction import RENOVA_FIELDS_NEVER_SENT_TO_LLM

import typing


def _readable_field_literal_values() -> set[str]:
    return set(typing.get_args(RenovaReadableField))


def _case(**overrides) -> RenovaCase:
    values = {
        "owner_name": "Martha González",
        "owner_phone": "81 1234 5678",
        "entry_date": date(2026, 9, 20),
        "status": "negotiating",
        "currency": "MXN",
    }
    values.update(overrides)
    return RenovaCase(**values)


def test_every_readable_field_literal_has_exactly_one_resolver():
    assert set(RENOVA_CASE_FIELD_RESOLVERS.keys()) == _readable_field_literal_values()


def test_no_resolver_exists_for_a_field_that_must_never_reach_an_llm():
    """Not that the LLM can't choose it (the Literal already prevents that) -- there's structurally nowhere for it to resolve to."""
    assert RENOVA_FIELDS_NEVER_SENT_TO_LLM.isdisjoint(RENOVA_CASE_FIELD_RESOLVERS.keys())


def test_bedrooms_bathrooms_floors():
    case = _case(bedrooms=3, bathrooms=Decimal("2.5"), floors=2)
    assert "3 recámaras" in RENOVA_CASE_FIELD_RESOLVERS["bedrooms"](case)
    assert "2.5 baños" in RENOVA_CASE_FIELD_RESOLVERS["bathrooms"](case)
    assert "2 plantas" in RENOVA_CASE_FIELD_RESOLVERS["floors"](case)


def test_bedrooms_absent():
    case = _case(bedrooms=None)
    assert "no tiene" in RENOVA_CASE_FIELD_RESOLVERS["bedrooms"](case)


def test_dwelling_type_and_duplex():
    case = _case(dwelling_type="house", is_duplex=True)
    assert "Casa" in RENOVA_CASE_FIELD_RESOLVERS["dwelling_type"](case)
    assert "dúplex" in RENOVA_CASE_FIELD_RESOLVERS["is_duplex"](case).lower()
    assert "no es dúplex" in RENOVA_CASE_FIELD_RESOLVERS["is_duplex"](_case(is_duplex=False))


def test_occupancy_status():
    case = _case(occupancy_status="rented")
    assert "Rentada" in RENOVA_CASE_FIELD_RESOLVERS["occupancy_status"](case)


def test_has_deeds_and_deeds_holder():
    case = _case(has_deeds="yes", deeds_holder_name="Martha González")
    assert "Sí" in RENOVA_CASE_FIELD_RESOLVERS["has_deeds"](case)
    assert "Martha González" in RENOVA_CASE_FIELD_RESOLVERS["deeds_holder_name"](case)
    no_deeds = _case(has_deeds="no")
    assert "No" in RENOVA_CASE_FIELD_RESOLVERS["has_deeds"](no_deeds)


def test_sale_reason_general_situation_notes_conditions():
    case = _case(
        sale_reason="Ya no puede pagar la casa",
        general_situation="Se muda con su hijo",
        notes="Llamó dos veces esta semana",
        conditions="Requiere pintura",
    )
    assert "Ya no puede pagar la casa" in RENOVA_CASE_FIELD_RESOLVERS["sale_reason"](case)
    assert "Se muda con su hijo" in RENOVA_CASE_FIELD_RESOLVERS["general_situation"](case)
    assert "Llamó dos veces esta semana" in RENOVA_CASE_FIELD_RESOLVERS["notes"](case)
    assert "Requiere pintura" in RENOVA_CASE_FIELD_RESOLVERS["conditions"](case)


def test_notes_absent_says_so_without_inventing_content():
    case = _case(notes=None)
    assert "no tengo" in RENOVA_CASE_FIELD_RESOLVERS["notes"](case).lower()


def test_marital_status_and_spouse():
    case = _case(marital_status="married_conjugal_partnership", spouse_name="Juan Pérez")
    assert "sociedad conyugal" in RENOVA_CASE_FIELD_RESOLVERS["marital_status"](case)
    assert "Juan Pérez" in RENOVA_CASE_FIELD_RESOLVERS["spouse_name"](case)


def test_source():
    case = _case(source="referral")
    assert "Referido" in RENOVA_CASE_FIELD_RESOLVERS["source"](case)


def test_existing_fixed_fields_still_resolve_through_the_same_dict():
    case = _case(owner_phone="8111112222", status="accepted")
    assert "8111112222" in RENOVA_CASE_FIELD_RESOLVERS["phone"](case)
    assert "Aceptado" in RENOVA_CASE_FIELD_RESOLVERS["status"](case)


def test_targeted_debt_fields():
    case = _case(water_debt=Decimal("800"), electricity_debt=None)
    assert "$800.00" in RENOVA_CASE_FIELD_RESOLVERS["water_debt"](case)
    assert "no tiene" in RENOVA_CASE_FIELD_RESOLVERS["electricity_debt"](case)


def test_property_tax_debt_formats_as_money_when_unit_is_mxn():
    case = _case(property_tax_debt=Decimal("12000"), property_tax_debt_unit="mxn")
    assert format_property_tax_debt(case) == "$12,000.00"
    assert "$12,000.00" in RENOVA_CASE_FIELD_RESOLVERS["property_tax_debt"](case)


def test_property_tax_debt_formats_as_years_when_unit_is_years_never_as_money():
    case = _case(property_tax_debt=Decimal("4"), property_tax_debt_unit="years")
    formatted = format_property_tax_debt(case)
    assert formatted == "4 años"
    assert "$" not in formatted
    assert "$" not in RENOVA_CASE_FIELD_RESOLVERS["property_tax_debt"](case)


def test_property_tax_debt_singular_year():
    case = _case(property_tax_debt=Decimal("1"), property_tax_debt_unit="years")
    assert format_property_tax_debt(case) == "1 año"


def test_property_tax_debt_absent_is_distinguished_from_zero():
    absent = _case(property_tax_debt=None)
    zero = _case(property_tax_debt=Decimal("0"), property_tax_debt_unit="mxn")
    assert format_property_tax_debt(absent) == "No está registrado"
    assert format_property_tax_debt(zero) == "$0.00"
