import pytest
from pydantic import ValidationError

from app.schemas.buyer_requirement import BuyerRequirementCreate, LocationCreate
from app.schemas.contact import ContactCreate


def test_contact_requires_email_or_phone():
    with pytest.raises(ValidationError):
        ContactCreate(first_name="Juan", last_name="Perez")


def test_contact_accepts_phone_only():
    contact = ContactCreate(first_name="Juan", last_name="Perez", phone="+52 811 000 0000")
    assert contact.phone == "+52 811 000 0000"


def test_contact_rejects_unknown_source():
    with pytest.raises(ValidationError):
        ContactCreate(first_name="Juan", last_name="Perez", phone="+52 811 000 0000", source="tiktok")


def test_buyer_requirement_rejects_inverted_budget_range():
    with pytest.raises(ValidationError):
        BuyerRequirementCreate(budget_min=5_000_000, budget_max=4_000_000)


def test_buyer_requirement_accepts_valid_budget_range():
    requirement = BuyerRequirementCreate(budget_min=4_000_000, budget_max=5_000_000, property_type="house")
    assert requirement.budget_min < requirement.budget_max


def test_buyer_requirement_rejects_unknown_property_type():
    with pytest.raises(ValidationError):
        BuyerRequirementCreate(property_type="castle")


def test_location_requires_city_or_neighborhood():
    with pytest.raises(ValidationError):
        LocationCreate(state="Nuevo Leon")


def test_location_accepts_neighborhood_only():
    location = LocationCreate(neighborhood="San Pedro")
    assert location.neighborhood == "San Pedro"
