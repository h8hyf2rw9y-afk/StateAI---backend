"""
NSS / credit number handling in Renova: normalization and validation, the
cipher itself, the authorized reveal endpoint (auth, organization isolation,
roles, no-store, audit without values) and the PATCH semantics that protect
stored ciphertext. All identifiers are obviously synthetic.
"""

import json
import logging
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import settings
from app.core.security import get_current_org_user
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, User
from app.models.renova_case import RenovaCase
from app.schemas.renova_case import RenovaSensitiveData
from app.schemas.user import CurrentUser

URL = "/api/v1/renova/cases"
NSS = "00123456789"  # leading zeros must survive
CREDIT = "0098765432"


def _body(user: CurrentUser, **overrides) -> dict:
    body = {
        "assigned_user_id": str(user.id),
        "entry_date": "2026-09-20",
        "owner_name": "María López",
        "owner_phone": "+52 81 5555 0101",
    }
    body.update(overrides)
    return body


def _create(client: TestClient, user: CurrentUser, **overrides) -> dict:
    response = client.post(URL, json=_body(user, nss=NSS, credit_number=CREDIT, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _act_as(user: CurrentUser) -> None:
    app.dependency_overrides[get_current_org_user] = lambda: user


def _user_in_org(db: Session, organization_id: uuid.UUID, role: str) -> CurrentUser:
    user_id = uuid.uuid4()
    db.add(User(id=user_id, organization_id=organization_id, role=role))
    db.commit()
    return CurrentUser(id=user_id, email=f"{role}@example.com", organization_id=organization_id, role=role, provider="email")  # type: ignore[arg-type]


# --- the cipher ----------------------------------------------------------------------


def test_ciphertext_differs_from_the_plaintext_and_from_a_second_encryption():
    first, second = crypto.encrypt_secret(NSS), crypto.encrypt_secret(NSS)

    assert NSS not in first
    assert first != second  # fresh IV each time
    assert crypto.reveal_secret(first) == NSS and crypto.reveal_secret(second) == NSS


def test_leading_zeros_survive_a_round_trip():
    assert crypto.reveal_secret(crypto.encrypt_secret("000123")) == "000123"


def test_a_wrong_key_fails_in_a_controlled_way(monkeypatch):
    token = crypto.encrypt_secret(NSS)
    monkeypatch.setattr(settings, "renova_encryption_key", Fernet.generate_key().decode())

    with pytest.raises(crypto.SecretDecryptionError) as error:
        crypto.reveal_secret(token)
    assert NSS not in str(error.value) and token not in str(error.value)
    assert crypto.decrypt_secret(token) is None


def test_tampered_ciphertext_is_detected():
    token = crypto.encrypt_secret(NSS)
    tampered = token[:-6] + ("AAAAAA" if not token.endswith("AAAAAA") else "BBBBBB")

    with pytest.raises(crypto.SecretDecryptionError):
        crypto.reveal_secret(tampered)


def test_without_a_key_encrypting_and_revealing_fail_with_the_static_error(monkeypatch):
    token = crypto.encrypt_secret(NSS)
    monkeypatch.setattr(settings, "renova_encryption_key", None)

    with pytest.raises(crypto.EncryptionNotConfiguredError):
        crypto.encrypt_secret(NSS)
    with pytest.raises(crypto.EncryptionNotConfiguredError):
        crypto.reveal_secret(token)


def test_a_malformed_key_is_treated_as_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "renova_encryption_key", "definitely-not-a-fernet-key")

    with pytest.raises(crypto.EncryptionNotConfiguredError):
        crypto.encrypt_secret(NSS)


def test_the_encryption_key_is_never_exposed_by_the_api(client: TestClient, current_user: CurrentUser):
    created = _create(client, current_user)
    key = settings.renova_encryption_key
    responses = [
        client.get(f"{URL}/{created['id']}"),
        client.get(f"{URL}/{created['id']}/sensitive-data"),
        client.get(URL),
    ]

    assert all(key not in r.text for r in responses)


# --- normalization and validation ------------------------------------------------------


@pytest.mark.parametrize("typed", ["00123456789", "001 2345 6789", "001-23456-789", "  00123456789  "])
def test_nss_is_normalized_to_bare_digits_and_keeps_leading_zeros(client, current_user, typed):
    created = client.post(URL, json=_body(current_user, nss=typed))

    assert created.status_code == 201, created.text
    revealed = client.get(f"{URL}/{created.json()['id']}/sensitive-data").json()
    assert revealed["nss"] == "00123456789"


@pytest.mark.parametrize("bad", ["1234567890", "123456789012", "0012345678A", "••••••••••4821", "***********", "", "   "])
def test_invalid_nss_is_rejected_without_echoing_it(client, current_user, bad):
    response = client.post(URL, json=_body(current_user, nss=bad))

    assert response.status_code == 422
    if bad.strip():
        assert bad not in response.text
    assert "11 digits" in response.text or "nss" in response.text.lower()


@pytest.mark.parametrize("bad", ["12345", "1" * 21, "12345ABC90", "••••••7104", "**********"])
def test_invalid_credit_number_is_rejected_without_echoing_it(client, current_user, bad):
    response = client.post(URL, json=_body(current_user, credit_number=bad))

    assert response.status_code == 422
    assert bad not in response.text


def test_credit_number_accepts_a_reasonable_range_of_digits_and_separators(client, current_user):
    for typed, expected in [("0098 7654 32", "0098765432"), ("123456", "123456"), ("1" * 20, "1" * 20)]:
        created = client.post(URL, json=_body(current_user, credit_number=typed))
        assert created.status_code == 201, created.text
        assert client.get(f"{URL}/{created.json()['id']}/sensitive-data").json()["credit_number"] == expected


def test_a_masked_value_sent_back_in_a_patch_is_rejected_and_the_stored_value_survives(client, current_user):
    created = _create(client, current_user)

    for masked in (created["nss_masked"], "••••6789", "*******6789"):
        response = client.patch(f"{URL}/{created['id']}", json={"nss": masked})
        assert response.status_code == 422
    revealed = client.get(f"{URL}/{created['id']}/sensitive-data").json()
    assert revealed == {"nss": NSS, "credit_number": CREDIT}


# --- storage ----------------------------------------------------------------------------


def test_both_values_are_encrypted_before_they_are_persisted(client, current_user, db_session):
    created = _create(client, current_user)

    row = db_session.get(RenovaCase, uuid.UUID(created["id"]))
    assert row.nss_encrypted != NSS and NSS not in row.nss_encrypted
    assert row.credit_number_encrypted != CREDIT and CREDIT not in row.credit_number_encrypted
    assert crypto.reveal_secret(row.nss_encrypted) == NSS
    assert crypto.reveal_secret(row.credit_number_encrypted) == CREDIT


def test_missing_key_gives_a_clear_503_not_a_500_and_stores_nothing(client, current_user, db_session, monkeypatch):
    monkeypatch.setattr(settings, "renova_encryption_key", None)

    response = client.post(URL, json=_body(current_user, nss=NSS, credit_number=CREDIT))

    assert response.status_code == 503
    assert "not configured" in response.json()["error"]["message"].lower()
    assert NSS not in response.text and CREDIT not in response.text
    assert db_session.query(RenovaCase).count() == 0


# --- API responses ---------------------------------------------------------------------


def test_detail_returns_masks_and_flags_but_never_the_values(client, current_user):
    created = _create(client, current_user)

    detail = client.get(f"{URL}/{created['id']}").json()

    assert detail["has_nss"] is True and detail["has_credit_number"] is True
    assert detail["nss_masked"] == "•" * 7 + NSS[-4:]
    assert detail["credit_number_masked"] == "•" * 6 + CREDIT[-4:]
    raw = json.dumps(detail)
    assert NSS not in raw and CREDIT not in raw and "nss_encrypted" not in raw


def test_a_case_without_values_reports_false_flags(client, current_user):
    detail = client.post(URL, json=_body(current_user)).json()

    assert detail["has_nss"] is False and detail["has_credit_number"] is False
    assert detail["nss_masked"] is None


def test_listing_exposes_neither_values_nor_ciphertext_nor_column_names(client, current_user, db_session):
    created = _create(client, current_user)
    row = db_session.get(RenovaCase, uuid.UUID(created["id"]))

    text = client.get(URL).text

    for forbidden in (NSS, CREDIT, NSS[-4:], row.nss_encrypted, "nss_encrypted", "credit_number_encrypted", "has_nss"):
        assert forbidden not in text


# --- the reveal endpoint ---------------------------------------------------------------


def test_reveal_returns_exactly_the_two_values_with_no_store_headers(client, current_user):
    created = _create(client, current_user)

    response = client.get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 200
    assert response.json() == {"nss": NSS, "credit_number": CREDIT}
    assert response.headers["cache-control"] == "no-store"


def test_reveal_of_a_case_without_values_returns_nulls(client, current_user):
    created = client.post(URL, json=_body(current_user)).json()

    assert client.get(f"{URL}/{created['id']}/sensitive-data").json() == {"nss": None, "credit_number": None}


def test_reveal_requires_authentication(client, current_user):
    created = _create(client, current_user)
    app.dependency_overrides.pop(get_current_org_user)

    response = TestClient(app).get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 401
    assert NSS not in response.text


def test_reveal_is_scoped_to_the_callers_organization(client, current_user, db_session):
    created = _create(client, current_user)
    other_org = Organization(name="Otra Inmobiliaria")
    db_session.add(other_org)
    db_session.commit()
    outsider = _user_in_org(db_session, other_org.id, "owner")
    _act_as(outsider)

    response = client.get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 404
    assert NSS not in response.text and CREDIT not in response.text


def test_the_assigned_advisor_can_reveal(client, current_user):
    created = _create(client, current_user)  # current_user is an agent AND the assigned advisor

    assert client.get(f"{URL}/{created['id']}/sensitive-data").status_code == 200


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owners_and_admins_can_reveal_any_case_of_their_organization(client, current_user, db_session, role):
    created = _create(client, current_user)
    _act_as(_user_in_org(db_session, current_user.organization_id, role))

    response = client.get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 200 and response.json()["nss"] == NSS


def test_an_unassigned_agent_cannot_reveal_and_learns_nothing(client, current_user, db_session):
    created = _create(client, current_user)
    _act_as(_user_in_org(db_session, current_user.organization_id, "agent"))

    response = client.get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 403
    assert NSS not in response.text and CREDIT not in response.text
    # ...but can still read the masks like any org member.
    assert client.get(f"{URL}/{created['id']}").json()["nss_masked"].endswith(NSS[-4:])


def test_reveal_without_a_key_is_a_controlled_503(client, current_user, monkeypatch):
    created = _create(client, current_user)
    monkeypatch.setattr(settings, "renova_encryption_key", None)

    response = client.get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 503
    assert NSS not in response.text


def test_reveal_with_a_different_key_is_a_controlled_409(client, current_user, monkeypatch):
    created = _create(client, current_user)
    monkeypatch.setattr(settings, "renova_encryption_key", Fernet.generate_key().decode())

    response = client.get(f"{URL}/{created['id']}/sensitive-data")

    assert response.status_code == 409
    assert NSS not in response.text


def test_reveal_of_tampered_ciphertext_is_a_controlled_409(client, current_user, db_session):
    created = _create(client, current_user)
    row = db_session.get(RenovaCase, uuid.UUID(created["id"]))
    row.nss_encrypted = row.nss_encrypted[:-6] + "AAAAAA"
    db_session.commit()

    assert client.get(f"{URL}/{created['id']}/sensitive-data").status_code == 409


# --- audit -----------------------------------------------------------------------------


def test_a_reveal_is_audited_with_actor_case_and_time_but_no_values(client, current_user, db_session):
    created = _create(client, current_user)
    client.get(f"{URL}/{created['id']}/sensitive-data")

    row = db_session.query(AuditLog).filter(AuditLog.action == "RENOVA_SENSITIVE_DATA_VIEWED").one()

    assert row.actor_user_id == current_user.id
    assert row.organization_id == current_user.organization_id
    assert row.entity_id == uuid.UUID(created["id"]) and row.entity_type == "renova_case"
    assert row.created_at is not None
    assert row.before_data is None and row.after_data is None


def test_a_denied_reveal_is_not_recorded_as_a_view(client, current_user, db_session):
    created = _create(client, current_user)
    _act_as(_user_in_org(db_session, current_user.organization_id, "agent"))
    client.get(f"{URL}/{created['id']}/sensitive-data")

    assert db_session.query(AuditLog).filter(AuditLog.action == "RENOVA_SENSITIVE_DATA_VIEWED").count() == 0


def test_replacing_or_removing_a_value_is_audited_by_field_name_only(client, current_user, db_session):
    created = _create(client, current_user)
    client.patch(f"{URL}/{created['id']}", json={"nss": "99887766554"})
    client.patch(f"{URL}/{created['id']}", json={"credit_number": None})

    rows = db_session.query(AuditLog).filter(AuditLog.action == "RENOVA_SENSITIVE_DATA_CHANGED").all()
    assert [r.after_data["sensitive_fields_changed"] for r in rows] == [["nss"], ["credit_number"]]
    everything = json.dumps(
        [{"b": r.before_data, "a": r.after_data} for r in db_session.query(AuditLog).all()], default=str
    )
    for secret in (NSS, CREDIT, "99887766554", NSS[-4:], CREDIT[-4:], "6554"):
        assert secret not in everything


def test_no_log_line_contains_the_values_across_create_reveal_and_replace(client, current_user, caplog):
    caplog.set_level(logging.DEBUG)
    created = _create(client, current_user)
    client.get(f"{URL}/{created['id']}/sensitive-data")
    client.patch(f"{URL}/{created['id']}", json={"nss": "99887766554"})
    client.patch(f"{URL}/{created['id']}", json={"nss": "bad••••"})

    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (NSS, CREDIT, "99887766554"):
        assert secret not in logged


def test_the_reveal_schema_never_prints_its_values():
    data = RenovaSensitiveData(nss=NSS, credit_number=CREDIT)

    assert NSS not in repr(data) and NSS not in str(data) and CREDIT not in repr(data)


# --- PATCH semantics ----------------------------------------------------------------------


def test_a_patch_without_sensitive_fields_keeps_the_stored_ciphertext_untouched(client, current_user, db_session):
    created = _create(client, current_user)
    before = db_session.get(RenovaCase, uuid.UUID(created["id"]))
    before_tokens = (before.nss_encrypted, before.credit_number_encrypted)

    client.patch(f"{URL}/{created['id']}", json={"notes": "solo notas", "final_offer": "100"})

    db_session.expire_all()
    after = db_session.get(RenovaCase, uuid.UUID(created["id"]))
    assert (after.nss_encrypted, after.credit_number_encrypted) == before_tokens
    assert client.get(f"{URL}/{created['id']}/sensitive-data").json() == {"nss": NSS, "credit_number": CREDIT}


def test_a_patch_with_a_new_value_replaces_it_with_new_ciphertext(client, current_user, db_session):
    created = _create(client, current_user)
    old_token = db_session.get(RenovaCase, uuid.UUID(created["id"])).nss_encrypted

    response = client.patch(f"{URL}/{created['id']}", json={"nss": "99887766554"})

    assert response.status_code == 200
    assert response.json()["nss_masked"] == "•" * 7 + "6554"
    db_session.expire_all()
    row = db_session.get(RenovaCase, uuid.UUID(created["id"]))
    assert row.nss_encrypted != old_token and "99887766554" not in row.nss_encrypted
    assert client.get(f"{URL}/{created['id']}/sensitive-data").json()["nss"] == "99887766554"


def test_an_explicit_null_removes_only_that_value(client, current_user):
    created = _create(client, current_user)

    removed = client.patch(f"{URL}/{created['id']}", json={"credit_number": None}).json()

    assert removed["has_credit_number"] is False and removed["has_nss"] is True
    assert client.get(f"{URL}/{created['id']}/sensitive-data").json() == {"nss": NSS, "credit_number": None}
