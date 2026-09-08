"""
The Lead Intelligence Agent (app/ai/lead_intelligence_agent.py) and its
route. Entirely deterministic and offline — every test here uses
FakeLLMProvider instead of a real Anthropic call, so this file needs no
ANTHROPIC_API_KEY and never touches the network. See
tests/test_lead_intelligence_integration.py for the real-LLM smoke test,
which is skipped unless that key is actually configured.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.lead_intelligence_agent import LeadIntelligenceAgent
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMInvalidOutputError, LLMTimeoutError
from app.api.routes.ai import _get_llm_provider
from app.main import app
from app.models.activity import Activity
from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact
from app.models.organization import Organization
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis
from app.schemas.user import CurrentUser


class FakeLLMProvider(LLMProvider):
    """
    A stand-in LLMProvider for tests — never calls a network. Give it either
    a canned `response` to return, or an `error` to raise, so tests can
    exercise both the happy path and every failure mode the agent/route are
    expected to handle. Records every call so tests can assert what the
    agent actually sent the "model".
    """

    def __init__(self, *, response: LeadIntelligenceAnalysis | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def generate_structured(self, *, system_prompt, user_prompt, response_model, max_tokens=1024):
        self.calls.append((system_prompt, user_prompt))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _valid_analysis(**overrides) -> LeadIntelligenceAnalysis:
    fields = {
        "priority": "high",
        "confidence": 0.8,
        "reasoning": "Recent activity and an active buyer requirement suggest strong ongoing intent.",
        "positive_signals": ["2 activities in the last week", "has_active_buyer_requirement is true"],
        "risk_signals": [],
        "recommended_next_action": "call",
        "insufficient_data": False,
    }
    fields.update(overrides)
    return LeadIntelligenceAnalysis(**fields)


def _make_contact(db_session: Session, organization_id, **overrides) -> Contact:
    fields = {"organization_id": organization_id, "first_name": "Luis", "last_name": "Cantu", "phone": "+52 81 5500 7777"}
    fields.update(overrides)
    contact = Contact(**fields)
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)
    return contact


# --- LeadIntelligenceAnalysis schema -----------------------------------------------------------


def test_analysis_schema_accepts_a_well_formed_payload():
    analysis = _valid_analysis()
    assert analysis.priority == "high"
    assert 0.0 <= analysis.confidence <= 1.0


def test_analysis_schema_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        _valid_analysis(confidence=1.5)


def test_analysis_schema_rejects_unknown_priority():
    with pytest.raises(ValidationError):
        _valid_analysis(priority="urgent")


def test_analysis_schema_rejects_unknown_recommended_action():
    with pytest.raises(ValidationError):
        _valid_analysis(recommended_next_action="send_carrier_pigeon")


# --- Agent: context retrieval, authorization, prompt construction -----------------------------


def test_agent_returns_validated_result_for_a_normal_contact(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_analysis())

    result = LeadIntelligenceAgent(db_session, fake).analyze(current_user, contact.id)

    assert result.contact_id == contact.id
    assert result.model == "fake-model-v1"
    assert result.analysis.priority == "high"
    assert len(fake.calls) == 1


def test_agent_raises_404_for_a_nonexistent_contact_without_calling_the_llm(db_session: Session, current_user):
    fake = FakeLLMProvider(response=_valid_analysis())

    with pytest.raises(HTTPException) as exc_info:
        LeadIntelligenceAgent(db_session, fake).analyze(current_user, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert fake.calls == []  # never reached the LLM — the 404 happens at context retrieval


def test_agent_enforces_organization_isolation(db_session: Session):
    """A user in org A must not be able to run the agent against org B's contact."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    contact_b = _make_contact(db_session, org_b.id, first_name="Ajeno", last_name="Contact")
    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    fake = FakeLLMProvider(response=_valid_analysis())

    with pytest.raises(HTTPException) as exc_info:
        LeadIntelligenceAgent(db_session, fake).analyze(user_a, contact_b.id)

    assert exc_info.value.status_code == 404
    assert fake.calls == []


def test_agent_prompt_includes_the_contact_and_key_context_facts(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id, first_name="Carolina", last_name="Reyes")
    prop = Property(organization_id=organization_id, title="Casa Contry", property_type="house", status="active", price=6000000)
    db_session.add(prop)
    db_session.commit()
    db_session.add_all(
        [
            PropertyInterest(organization_id=organization_id, contact_id=contact.id, property_id=prop.id, status="interested"),
            BuyerRequirement(organization_id=organization_id, contact_id=contact.id, status="active", budget_max=6500000),
        ]
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_valid_analysis())

    LeadIntelligenceAgent(db_session, fake).analyze(current_user, contact.id)

    system_prompt, user_prompt = fake.calls[0]
    assert "real-estate CRM intelligence assistant" in system_prompt
    assert "Carolina" in user_prompt
    assert "Casa Contry" in user_prompt
    assert "6500000" in user_prompt or "6500000.00" in user_prompt


def test_agent_propagates_llm_timeout(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMTimeoutError("slow"))

    with pytest.raises(LLMTimeoutError):
        LeadIntelligenceAgent(db_session, fake).analyze(current_user, contact.id)


def test_agent_propagates_llm_invalid_output(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))

    with pytest.raises(LLMInvalidOutputError):
        LeadIntelligenceAgent(db_session, fake).analyze(current_user, contact.id)


def test_agent_analyzes_a_contact_with_activities_only(db_session: Session, organization_id, current_user):
    """Partial data (activities but no requirement/interest) still reaches the LLM as valid context."""
    contact = _make_contact(db_session, organization_id)
    db_session.add(
        Activity(
            organization_id=organization_id,
            contact_id=contact.id,
            activity_type="whatsapp",
            occurred_at=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
            notes="Primer mensaje",
        )
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_valid_analysis(priority="medium"))

    result = LeadIntelligenceAgent(db_session, fake).analyze(current_user, contact.id)

    assert result.analysis.priority == "medium"
    assert '"activity_count": 1' in fake.calls[0][1]


# --- Route --------------------------------------------------------------------------------------


def test_route_returns_analysis_when_provider_is_overridden(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Ivan", "last_name": "Solis", "phone": "+52 81 5500 8888"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        response = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 200
    body = response.json()
    assert body["contact_id"] == contact["id"]
    assert body["analysis"]["priority"] == "high"
    assert body["model"] == "fake-model-v1"


def test_route_returns_503_when_no_provider_is_configured(client: TestClient, monkeypatch):
    """Without ANTHROPIC_API_KEY set, the real dependency (not overridden here) must fail as a clean 503, not a 500."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Nadia", "last_name": "Cruz", "phone": "+52 81 5500 9999"}
    ).json()

    response = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")

    assert response.status_code == 503


def test_route_returns_504_on_llm_timeout(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Beto", "last_name": "Longoria", "phone": "+52 81 5500 1111"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMTimeoutError("slow"))
    try:
        response = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 504


def test_route_returns_502_on_invalid_llm_output(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Paty", "last_name": "Villa", "phone": "+52 81 5500 2222"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))
    try:
        response = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 502


def test_route_returns_404_for_a_contact_in_another_organization(db_session: Session, organization_id):
    from app.core.database import get_db
    from app.core.security import get_current_org_user

    other_org = Organization(name="Other Org")
    db_session.add(other_org)
    db_session.commit()
    contact = _make_contact(db_session, other_org.id, first_name="Fuera", last_name="Deorg")

    user = CurrentUser(id=uuid.uuid4(), email="u@example.com", organization_id=organization_id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        test_client = TestClient(app)
        response = test_client.post(f"/api/v1/ai/lead-intelligence/{contact.id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
