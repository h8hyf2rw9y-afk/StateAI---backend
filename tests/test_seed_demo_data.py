"""
Verifies scripts/seed_demo_data.py is truly idempotent: running it twice
against the same database must not create any duplicate rows, and a row's
id (and created_at) must stay stable across runs.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact, ContactRole
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from scripts.seed_demo_data import CONTACTS, det_id, run_seed


def _counts(db_session: Session) -> dict[str, int]:
    return {
        "contacts": db_session.scalar(select(func.count()).select_from(Contact)),
        "contact_roles": db_session.scalar(select(func.count()).select_from(ContactRole)),
        "properties": db_session.scalar(select(func.count()).select_from(Property)),
        "buyer_requirements": db_session.scalar(select(func.count()).select_from(BuyerRequirement)),
        "property_interests": db_session.scalar(select(func.count()).select_from(PropertyInterest)),
    }


def test_seed_matches_expected_counts(db_session: Session):
    run_seed(db_session)
    counts = _counts(db_session)

    assert counts["contacts"] == 20
    assert counts["properties"] == 14
    assert counts["buyer_requirements"] == 13
    assert counts["property_interests"] == 10
    assert counts["contact_roles"] == 21  # 20 "buyer" + Ricardo's extra "investor"


def test_seed_is_idempotent(db_session: Session):
    run_seed(db_session)
    first_run_counts = _counts(db_session)
    alejandro_id_first = db_session.get(Contact, det_id("contact:alejandro-torres")).id
    alejandro_created_at_first = db_session.get(Contact, det_id("contact:alejandro-torres")).created_at

    run_seed(db_session)
    second_run_counts = _counts(db_session)
    alejandro = db_session.get(Contact, det_id("contact:alejandro-torres"))

    assert second_run_counts == first_run_counts
    assert alejandro.id == alejandro_id_first
    assert alejandro.created_at == alejandro_created_at_first


def test_every_contact_has_email_or_phone(db_session: Session):
    run_seed(db_session)
    for c in CONTACTS:
        contact = db_session.get(Contact, det_id(f"contact:{c['key']}"))
        assert contact is not None
        assert contact.email or contact.phone


def test_gabriela_transition_case(db_session: Session):
    """The critical Property Interest -> Not Interested -> Buyer Requirement test case from the brief."""
    run_seed(db_session)

    interest = db_session.get(
        PropertyInterest, det_id("property-interest:gabriela-ortiz:departamento-del-valle")
    )
    assert interest is not None
    assert interest.status == "not_interested"

    requirement = db_session.get(BuyerRequirement, det_id("buyer-requirement:gabriela-ortiz:1"))
    assert requirement is not None
    assert requirement.status == "active"
    assert requirement.contact_id == interest.contact_id


def test_sergio_requirement_history_preserved(db_session: Session):
    """Sergio's changed requirements: the old row is kept (status=cancelled), not overwritten."""
    run_seed(db_session)

    old = db_session.get(BuyerRequirement, det_id("buyer-requirement:sergio-navarro:1"))
    new = db_session.get(BuyerRequirement, det_id("buyer-requirement:sergio-navarro:2"))

    assert old is not None and old.status == "cancelled"
    assert new is not None and new.status == "active"
    assert old.contact_id == new.contact_id
    assert old.budget_min != new.budget_min
