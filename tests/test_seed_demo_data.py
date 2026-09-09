"""
Verifies scripts/seed_demo_data.py is truly idempotent: running it twice
against the same database must not create any duplicate rows, and a row's
id (and created_at) must stay stable across runs.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.appointment import Appointment
from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact, ContactRole
from app.models.opportunity import Opportunity
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from app.models.task import Task
from scripts.seed_demo_data import ACTIVITIES, APPOINTMENTS, CONTACTS, OPPORTUNITIES, TASKS, det_id, run_seed


def _counts(db_session: Session) -> dict[str, int]:
    return {
        "contacts": db_session.scalar(select(func.count()).select_from(Contact)),
        "contact_roles": db_session.scalar(select(func.count()).select_from(ContactRole)),
        "properties": db_session.scalar(select(func.count()).select_from(Property)),
        "buyer_requirements": db_session.scalar(select(func.count()).select_from(BuyerRequirement)),
        "property_interests": db_session.scalar(select(func.count()).select_from(PropertyInterest)),
        "activities": db_session.scalar(select(func.count()).select_from(Activity)),
        "opportunities": db_session.scalar(select(func.count()).select_from(Opportunity)),
        "tasks": db_session.scalar(select(func.count()).select_from(Task)),
        "appointments": db_session.scalar(select(func.count()).select_from(Appointment)),
    }


def test_seed_matches_expected_counts(db_session: Session):
    run_seed(db_session)
    counts = _counts(db_session)

    assert counts["contacts"] == 20
    assert counts["properties"] == 14
    assert counts["buyer_requirements"] == 13
    assert counts["property_interests"] == 10
    # 20 "buyer" + Ricardo's extra "investor" + Fernando's extra "seller" (he's
    # both buying a new home and selling his current one — see OPPORTUNITIES).
    assert counts["contact_roles"] == 22
    assert counts["activities"] == sum(len(entries) for entries in ACTIVITIES.values())
    assert set(ACTIVITIES.keys()) == {c["key"] for c in CONTACTS}  # every contact has a timeline
    assert counts["opportunities"] == len(OPPORTUNITIES)
    assert counts["tasks"] == len(TASKS)
    assert counts["appointments"] == len(APPOINTMENTS)


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


def test_seed_won_and_lost_opportunities_have_closed_at(db_session: Session):
    """Seeding writes rows directly (not through OpportunityService), so closed_at must be backfilled by hand for won/lost — this confirms that actually happened."""
    run_seed(db_session)

    won = db_session.get(Opportunity, det_id("opportunity:sergio-navarro:won"))
    assert won is not None and won.stage == "won" and won.closed_at is not None

    lost = db_session.get(Opportunity, det_id("opportunity:gabriela-ortiz:lost"))
    assert lost is not None and lost.stage == "lost" and lost.closed_at is not None and lost.lost_reason


def test_seed_gabriela_has_two_opportunities_over_time(db_session: Session):
    """The exact "a contact may have multiple opportunities over time" scenario — her rejected opportunity and her new active search are separate rows, not one overwritten."""
    run_seed(db_session)

    lost = db_session.get(Opportunity, det_id("opportunity:gabriela-ortiz:lost"))
    active = db_session.get(Opportunity, det_id("opportunity:gabriela-ortiz:buy"))
    assert lost.contact_id == active.contact_id
    assert lost.stage == "lost"
    assert active.stage == "search"


def test_seed_fernando_has_both_a_buy_and_a_sell_opportunity(db_session: Session):
    """Buying a new home while selling his current one — both reference the same contact, distinct opportunity_type."""
    run_seed(db_session)

    buy = db_session.get(Opportunity, det_id("opportunity:fernando-vargas:buy"))
    sell = db_session.get(Opportunity, det_id("opportunity:fernando-vargas:sell"))
    assert buy.contact_id == sell.contact_id
    assert buy.opportunity_type == "buy"
    assert sell.opportunity_type == "sell"


def test_seed_overdue_task_scenario(db_session: Session):
    from datetime import datetime, timezone

    run_seed(db_session)
    task = db_session.get(Task, det_id("task:carlos-mendoza:follow-up"))
    assert task is not None
    assert task.status == "pending"
    assert task.due_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)
    assert task.opportunity_id == det_id("opportunity:carlos-mendoza:buy")


def test_seed_upcoming_appointment_scenario(db_session: Session):
    from datetime import datetime, timezone

    run_seed(db_session)
    appointment = db_session.get(Appointment, det_id("appointment:natalia-ramirez:second-viewing"))
    assert appointment is not None
    assert appointment.start_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    assert appointment.opportunity_id == det_id("opportunity:natalia-ramirez:buy")


def test_seed_opportunity_has_linked_activity_history(db_session: Session):
    """"Meaningful activity history" — Paola's opportunity has several of her existing activities linked via opportunity_id, not a duplicated/separate history."""
    run_seed(db_session)
    opportunity_id = det_id("opportunity:paola-rodriguez:buy")
    linked = db_session.scalars(select(Activity).where(Activity.opportunity_id == opportunity_id)).all()
    assert len(linked) >= 2


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
