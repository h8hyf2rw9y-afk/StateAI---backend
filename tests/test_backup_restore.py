"""
Backups (app/backup/snapshot.py) and the selective Renova restore
(app/backup/restore.py), end to end against the in-memory test database.
All people and identifiers are synthetic.
"""

import gzip
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.backup.restore import apply_renova_restore, plan_renova_restore
from app.backup.snapshot import list_backups, load_snapshot, prune_backups, take_snapshot, write_snapshot
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
from app.models.renova_case import RenovaCase
from app.models.renova_follow_up import RenovaFollowUpActivity


def _user(db, organization_id, email, role="renova_agent"):
    user = User(id=uuid.uuid4(), organization_id=organization_id, role=role, email=email)
    db.add(user)
    db.commit()
    return user


def _case(db, owner, name, **overrides):
    values = dict(
        organization_id=owner.organization_id,
        assigned_user_id=owner.id,
        created_by_user_id=owner.id,
        entry_date=date(2026, 9, 20),
        source="whatsapp",
        status="negotiating",
        owner_name=name,
        owner_phone="81 0000 0000",
        currency="MXN",
        final_offer=Decimal("830000.00"),
        street_address="Av la Maestranza 116",
    )
    values.update(overrides)
    case = RenovaCase(**values)
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@pytest.fixture()
def world(db_session, organization_id):
    ana = _user(db_session, organization_id, "ana@gmail.com")
    beto = _user(db_session, organization_id, "beto@gmail.com")
    ana_case = _case(db_session, ana, "Rola")
    ana_case_2 = _case(db_session, ana, "Yessy", final_offer=Decimal("736226.50"))
    beto_case = _case(db_session, beto, "Caso de Beto")
    follow_up = RenovaFollowUpActivity(
        organization_id=organization_id,
        renova_case_id=ana_case.id,
        actor_user_id=ana.id,
        activity_type="call",
        result="interested",
        occurred_at=datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc),
        attempt_number=2,
        notes="Llamar después de las 5",
    )
    db_session.add(follow_up)
    db_session.commit()
    engine = db_session.get_bind()
    return {"db": db_session, "engine": engine, "ana": ana, "beto": beto, "ana_case": ana_case,
            "ana_case_2": ana_case_2, "beto_case": beto_case, "follow_up": follow_up}


def _backup(world, tmp_path):
    path = write_snapshot(take_snapshot(world["engine"]), tmp_path)
    return load_snapshot(path)


# --- snapshots -----------------------------------------------------------------


def test_snapshot_has_every_table_and_round_trips(world, tmp_path):
    path = write_snapshot(take_snapshot(world["engine"]), tmp_path)
    snapshot = load_snapshot(path)

    assert snapshot["row_counts"]["renova_cases"] == 3
    assert snapshot["row_counts"]["renova_follow_up_activities"] == 1
    assert snapshot["row_counts"]["users"] >= 2
    rola = next(r for r in snapshot["tables"]["renova_cases"]["rows"] if r["owner_name"] == "Rola")
    assert rola["id"] == str(world["ana_case"].id)
    assert rola["final_offer"] == "830000"
    assert path.with_name(path.name + ".sha256").exists()


def test_a_damaged_backup_is_refused(world, tmp_path):
    path = write_snapshot(take_snapshot(world["engine"]), tmp_path)
    data = gzip.decompress(path.read_bytes()).replace(b"Rola", b"Xola")
    path.write_bytes(gzip.compress(data))
    with pytest.raises(ValueError, match="does not match its .sha256"):
        load_snapshot(path)


def test_labels_and_retention(world, tmp_path):
    for i in range(4):
        snap = take_snapshot(world["engine"])
        snap["created_at"] = datetime(2026, 10, 1 + i, tzinfo=timezone.utc).isoformat()
        write_snapshot(snap, tmp_path, label="antes de migración" if i == 3 else None)
    assert list_backups(tmp_path)[-1].name.endswith("-antes-de-migraci-n.json.gz")
    removed = prune_backups(tmp_path, keep=2)
    assert len(removed) == 2 and len(list_backups(tmp_path)) == 2
    assert not any(p.name.endswith(".sha256") and not p.with_suffix("").exists() for p in tmp_path.iterdir())


# --- restore ---------------------------------------------------------------------


def test_restore_brings_back_a_deleted_case_and_its_follow_up_with_the_same_ids(world, tmp_path):
    db = world["db"]
    snapshot = _backup(world, tmp_path)
    case_id, follow_up_id = world["ana_case"].id, world["follow_up"].id
    db.delete(world["ana_case"])
    db.commit()
    assert db.get(RenovaCase, case_id) is None and db.get(RenovaFollowUpActivity, follow_up_id) is None

    plan = plan_renova_restore(snapshot, world["engine"], advisor_email="ANA@gmail.com")
    assert plan.count("renova_cases", "missing") == 1
    assert plan.count("renova_cases", "same") == 1  # Yessy is untouched
    assert plan.count("renova_follow_up_activities", "missing") == 1
    assert all(row.backup_row["owner_name"] != "Caso de Beto" for row in plan.rows if row.table == "renova_cases")

    result = apply_renova_restore(plan, world["engine"])
    assert result == {"inserted": 2, "overwritten": 0}

    db.expire_all()
    restored = db.get(RenovaCase, case_id)
    assert restored.owner_name == "Rola" and restored.final_offer == Decimal("830000.00")
    assert restored.entry_date == date(2026, 9, 20)
    follow_up = db.get(RenovaFollowUpActivity, follow_up_id)
    assert follow_up.notes == "Llamar después de las 5" and follow_up.attempt_number == 2
    audit = db.execute(select(AuditLog).where(AuditLog.entity_id == case_id)).scalars().all()
    assert [a.action for a in audit] == ["RENOVA_CASE_RESTORED_FROM_BACKUP"]


def test_an_untouched_advisor_plan_is_all_same_and_restores_nothing(world, tmp_path):
    snapshot = _backup(world, tmp_path)
    plan = plan_renova_restore(snapshot, world["engine"], advisor_email="ana@gmail.com")
    assert {row.status for row in plan.rows} == {"same"}
    assert apply_renova_restore(plan, world["engine"]) == {"inserted": 0, "overwritten": 0}


def test_without_overwrite_newer_edits_are_kept_with_it_they_are_reverted(world, tmp_path):
    db = world["db"]
    snapshot = _backup(world, tmp_path)
    world["ana_case"].final_offer = Decimal("900000.00")
    db.commit()

    plan = plan_renova_restore(snapshot, world["engine"], advisor_email="ana@gmail.com")
    changed = [row for row in plan.rows if row.status == "changed"]
    assert [row.label for row in changed] == ["Rola"]
    assert changed[0].changed_fields == ["final_offer"]

    apply_renova_restore(plan, world["engine"])
    db.expire_all()
    assert db.get(RenovaCase, world["ana_case"].id).final_offer == Decimal("900000.00")

    apply_renova_restore(plan, world["engine"], overwrite=True)
    db.expire_all()
    assert db.get(RenovaCase, world["ana_case"].id).final_offer == Decimal("830000.00")


def test_restore_by_case_id_touches_only_that_case(world, tmp_path):
    db = world["db"]
    snapshot = _backup(world, tmp_path)
    db.delete(world["beto_case"])
    db.delete(world["ana_case_2"])
    db.commit()

    plan = plan_renova_restore(snapshot, world["engine"], case_ids=[str(world["beto_case"].id)])
    assert [(row.label, row.status) for row in plan.rows] == [("Caso de Beto", "missing")]
    apply_renova_restore(plan, world["engine"])
    db.expire_all()
    assert db.get(RenovaCase, world["beto_case"].id) is not None
    assert db.get(RenovaCase, world["ana_case_2"].id) is None


def test_restore_needs_a_target_and_a_known_advisor(world, tmp_path):
    snapshot = _backup(world, tmp_path)
    with pytest.raises(ValueError, match="advisor email or at least one case id"):
        plan_renova_restore(snapshot, world["engine"])
    with pytest.raises(ValueError, match="No user with email"):
        plan_renova_restore(snapshot, world["engine"], advisor_email="nadie@gmail.com")


def test_other_organizations_are_never_in_an_advisors_plan(world, tmp_path, db_session):
    other = Organization(name="Otra")
    db_session.add(other)
    db_session.commit()
    stranger = _user(db_session, other.id, "extra@gmail.com")
    _case(db_session, stranger, "Ajeno")
    snapshot = _backup(world, tmp_path)
    plan = plan_renova_restore(snapshot, world["engine"], advisor_email="ana@gmail.com")
    assert "Ajeno" not in {row.label for row in plan.rows}
