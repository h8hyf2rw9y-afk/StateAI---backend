"""
Verifies scripts/seed_demo_data.py is truly idempotent: running it twice
against the same database must not create any duplicate rows, and a row's
id (and created_at) must stay stable across runs.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact, ContactRole
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from scripts.seed_demo_data import ACTIVITIES, CONTACTS, det_id, run_seed


def _counts(db_session: Session) -> dict[str, int]:
    return {
        "contacts": db_session.scalar(select(func.count()).select_from(Contact)),
        "contact_roles": db_session.scalar(select(func.count()).select_from(ContactRole)),
        "properties": db_session.scalar(select(func.count()).select_from(Property)),
        "buyer_requirements": db_session.scalar(select(func.count()).select_from(BuyerRequirement)),
        "property_interests": db_session.scalar(select(func.count()).select_from(PropertyInterest)),
        "activities": db_session.scalar(select(func.count()).select_from(Activity)),
    }


def test_seed_matches_expected_counts(db_session: Session):
    run_seed(db_session)
    counts = _counts(db_session)

    assert counts["contacts"] == 20
    assert counts["properties"] == 14
    assert counts["buyer_requirements"] == 13
    assert counts["property_interests"] == 10
    assert counts["contact_roles"] == 21  # 20 "buyer" + Ricardo's extra "investor"
    assert counts["activities"] == sum(len(entries) for entries in ACTIVITIES.values())
    assert set(ACTIVITIES.keys()) == {c["key"] for c in CONTACTS}  # every contact has a timeline


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


def test_carlos_activity_timeline_is_chronological(db_session: Session):
    run_seed(db_session)
    entries = ACTIVITIES["carlos-mendoza"]

    activities = [db_session.get(Activity, det_id(f"activity:carlos-mendoza:{i}")) for i in range(1, len(entries) + 1)]
    assert all(a is not None for a in activities)
    occurred_ats = [a.occurred_at for a in activities]
    assert occurred_ats == sorted(occurred_ats)  # stored oldest-first, matching ACTIVITIES' ordering


def test_gabriela_activity_timeline_marks_the_transition(db_session: Session):
    """Her last two activities are the rejection (with a property) then the pivot to a buyer search (without one)."""
    run_seed(db_session)
    contact = db_session.get(Contact, det_id("contact:gabriela-ortiz"))
    entries = ACTIVITIES["gabriela-ortiz"]

    last_two = [
        db_session.get(Activity, det_id(f"activity:gabriela-ortiz:{len(entries) - 1}")),
        db_session.get(Activity, det_id(f"activity:gabriela-ortiz:{len(entries)}")),
    ]
    assert all(a.contact_id == contact.id for a in last_two)
    assert last_two[0].property_id is not None  # the rejection, tied to the property
    assert last_two[1].property_id is None  # the pivot to a general buyer search
