"""
app/renova_chat/filters.py: turning one allow-listed RenovaCaseFilter into
a deterministic SQLAlchemy clause. No database access here either -- these
tests build the clause and execute it directly against db_session so the
SQL semantics are checked without going through the chat endpoint at all
(see tests/test_renova_chat.py for the end-to-end filtered_count/
filtered_list behavior through the real HTTP + LLM-mock path).
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.renova_case import RenovaCase
from app.renova_chat.filters import build_filter_clause, describe_filter
from app.schemas.renova_chat import RenovaCaseFilter


def _case(organization_id: uuid.UUID, **overrides) -> RenovaCase:
    values = {
        "organization_id": organization_id,
        "entry_date": date(2026, 9, 20),
        "owner_name": "Caso de prueba",
        "owner_phone": "81 0000 0000",
        "status": "new",
        "is_duplex": False,
        "has_deeds": "unknown",
    }
    values.update(overrides)
    return RenovaCase(**values)


def _ids(db_session: Session, clause) -> set[str]:
    stmt = select(RenovaCase.id).where(clause)
    return {str(row) for row in db_session.execute(stmt).scalars().all()}


def test_status_equals(db_session: Session, current_user):
    negotiating = _case(current_user.organization_id, owner_name="Raúl", status="negotiating")
    accepted = _case(current_user.organization_id, owner_name="Andrea", status="accepted")
    db_session.add_all([negotiating, accepted])
    db_session.commit()

    clause = build_filter_clause(RenovaCaseFilter(field="status", operator="equals", value="negotiating"))
    assert clause is not None
    assert _ids(db_session, clause) == {str(negotiating.id)}


def test_municipality_equals_is_case_insensitive_partial_match(db_session: Session, current_user):
    case = _case(current_user.organization_id, municipality="Santa Catarina")
    db_session.add(case)
    db_session.commit()

    clause = build_filter_clause(RenovaCaseFilter(field="municipality", operator="equals", value="santa catarina"))
    assert _ids(db_session, clause) == {str(case.id)}
    assert _ids(db_session, build_filter_clause(RenovaCaseFilter(field="municipality", operator="equals", value="Apodaca"))) == set()


def test_is_duplex_true_and_false(db_session: Session, current_user):
    duplex = _case(current_user.organization_id, owner_name="Dúplex", is_duplex=True)
    plain = _case(current_user.organization_id, owner_name="Normal", is_duplex=False)
    db_session.add_all([duplex, plain])
    db_session.commit()

    is_true = build_filter_clause(RenovaCaseFilter(field="is_duplex", operator="is_true"))
    is_false = build_filter_clause(RenovaCaseFilter(field="is_duplex", operator="is_false"))
    assert _ids(db_session, is_true) == {str(duplex.id)}
    assert _ids(db_session, is_false) == {str(plain.id)}


def test_has_deeds_equals(db_session: Session, current_user):
    yes = _case(current_user.organization_id, owner_name="Con escrituras", has_deeds="yes")
    no = _case(current_user.organization_id, owner_name="Sin escrituras", has_deeds="no")
    db_session.add_all([yes, no])
    db_session.commit()

    assert _ids(db_session, build_filter_clause(RenovaCaseFilter(field="has_deeds", operator="equals", value="yes"))) == {str(yes.id)}
    assert _ids(db_session, build_filter_clause(RenovaCaseFilter(field="has_deeds", operator="equals", value="no"))) == {str(no.id)}


def test_debt_exists_filters(db_session: Session, current_user):
    with_water = _case(current_user.organization_id, owner_name="Con agua", water_debt=Decimal("500"))
    without_water = _case(current_user.organization_id, owner_name="Sin agua", water_debt=None)
    db_session.add_all([with_water, without_water])
    db_session.commit()

    clause = build_filter_clause(RenovaCaseFilter(field="has_water_debt", operator="exists"))
    assert _ids(db_session, clause) == {str(with_water.id)}


def test_arbitrary_operator_for_a_field_is_rejected():
    # The Literal already forbids a truly arbitrary string, but every real
    # combination that isn't semantically valid must also be rejected --
    # not every (field, operator) pair that both individually exist is a
    # valid pairing.
    assert build_filter_clause(RenovaCaseFilter(field="is_duplex", operator="equals", value="true")) is None
    assert build_filter_clause(RenovaCaseFilter(field="municipality", operator="is_true")) is None
    assert build_filter_clause(RenovaCaseFilter(field="has_water_debt", operator="equals", value="yes")) is None


def test_an_invalid_equals_value_is_rejected_not_guessed():
    assert build_filter_clause(RenovaCaseFilter(field="status", operator="equals", value="not_a_real_status")) is None
    assert build_filter_clause(RenovaCaseFilter(field="has_deeds", operator="equals", value="maybe")) is None


def test_a_blank_municipality_value_is_rejected():
    assert build_filter_clause(RenovaCaseFilter(field="municipality", operator="equals", value=None)) is None
    assert build_filter_clause(RenovaCaseFilter(field="municipality", operator="equals", value="")) is None


def test_describe_filter_is_human_readable_spanish():
    assert describe_filter(RenovaCaseFilter(field="status", operator="equals", value="negotiating")) == "en Negociando"
    assert describe_filter(RenovaCaseFilter(field="municipality", operator="equals", value="Apodaca")) == "en Apodaca"
    assert describe_filter(RenovaCaseFilter(field="is_duplex", operator="is_true")) == "con casa dúplex"
    assert describe_filter(RenovaCaseFilter(field="has_water_debt", operator="exists")) == "con adeudo de agua"
