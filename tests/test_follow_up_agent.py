"""
The Follow-up Agent (app/ai/follow_up_agent.py) and its route. Entirely
deterministic and offline — every test here uses FakeLLMProvider instead of
a real Ollama/Anthropic call, so this file needs no local Ollama and never
touches the network. See tests/test_follow_up_agent_ollama_integration.py
for the real-LLM smoke test, which requires an explicit opt-in.

Numbered comments below map directly to the 14 required scenarios from the
Follow-up Agent brief.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.follow_up_agent import FollowUpAgent
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.api.routes.ai import _get_llm_provider
from app.main import app
from app.models.activity import Activity
from app.models.buyer_requirement import BuyerRequirement
from app.models.contact import Contact
from app.models.organization import Organization
from app.models.property import Property
from app.models.property_interest import PropertyInterest
from app.schemas.follow_up import FollowUpRecommendation
from app.schemas.user import CurrentUser


class FakeLLMProvider(LLMProvider):
    """Same pattern as tests/test_lead_intelligence_agent.py's — see there for why."""

    def __init__(self, *, response: FollowUpRecommendation | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, str]] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def generate_structured(self, *, system_prompt, user_prompt, response_model, max_tokens=1024):
        self.calls.append((system_prompt, user_prompt))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _needs_follow_up(**overrides) -> FollowUpRecommendation:
    fields = {
        "should_follow_up": True,
        "priority": "high",
        "recommended_channel": "whatsapp",
        "recommended_action": "send_properties",
        "reason": "No contact in 6 days despite an active buyer requirement and two viewed properties in budget.",
        "suggested_message": "Hola Carlos, ¿cómo estás? Encontré un par de opciones que se ajustan a lo que buscas, ¿te las comparto?",
        "confidence": 0.87,
    }
    fields.update(overrides)
    return FollowUpRecommendation(**fields)


def _no_follow_up(**overrides) -> FollowUpRecommendation:
    fields = {
        "should_follow_up": False,
        "priority": "low",
        "recommended_channel": "none",
        "recommended_action": "no_action",
        "reason": "The advisor followed up yesterday and is still waiting on a reasonable reply window.",
        "suggested_message": None,
        "confidence": 0.75,
    }
    fields.update(overrides)
    return FollowUpRecommendation(**fields)


def _make_contact(db_session: Session, organization_id, **overrides) -> Contact:
    fields = {"organization_id": organization_id, "first_name": "Luis", "last_name": "Cantu", "phone": "+52 81 5500 7777"}
    fields.update(overrides)
    contact = Contact(**fields)
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)
    return contact


def _occurred(day_in_august_2026: int) -> datetime:
    return datetime(2026, 8, day_in_august_2026, 9, 0, tzinfo=timezone.utc)


# --- FollowUpRecommendation schema (spec items 7, 8, 9) ------------------------------------------


def test_schema_accepts_a_well_formed_follow_up_payload():
    rec = _needs_follow_up()
    assert rec.should_follow_up is True
    assert rec.recommended_channel == "whatsapp"
    assert 0.0 <= rec.confidence <= 1.0


def test_schema_accepts_a_well_formed_no_follow_up_payload_with_null_message():
    rec = _no_follow_up()
    assert rec.should_follow_up is False
    assert rec.recommended_channel == "none"
    assert rec.suggested_message is None


def test_schema_accepts_confidence_at_the_boundaries():
    assert _needs_follow_up(confidence=0.0).confidence == 0.0
    assert _needs_follow_up(confidence=1.0).confidence == 1.0


def test_schema_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        _needs_follow_up(confidence=1.5)
    with pytest.raises(ValidationError):
        _needs_follow_up(confidence=-0.1)


def test_schema_rejects_confidence_given_as_a_percentage():
    """The exact failure mode discovered testing Lead Intelligence against real Ollama models."""
    with pytest.raises(ValidationError):
        _needs_follow_up(confidence=80)


def test_schema_rejects_an_unknown_channel():
    with pytest.raises(ValidationError):
        _needs_follow_up(recommended_channel="carrier_pigeon")


def test_schema_rejects_an_unknown_action():
    with pytest.raises(ValidationError):
        _needs_follow_up(recommended_action="send_gift_basket")


def test_schema_rejects_an_unknown_priority():
    with pytest.raises(ValidationError):
        _needs_follow_up(priority="urgent")


# --- Agent: context retrieval, authorization, reasoning inputs -----------------------------------


def test_agent_recommends_follow_up_for_an_active_buyer_with_stale_contact(db_session: Session, organization_id, current_user):
    """Spec scenario 1: an active buyer with no recent contact."""
    contact = _make_contact(db_session, organization_id)
    db_session.add(BuyerRequirement(organization_id=organization_id, contact_id=contact.id, status="active", budget_max=4000000))
    db_session.add(
        Activity(
            organization_id=organization_id, contact_id=contact.id, activity_type="whatsapp",
            direction="outbound", occurred_at=_occurred(1), notes="Primer contacto",
        )
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_needs_follow_up())

    result = FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    assert result.contact_id == contact.id
    assert result.recommendation.should_follow_up is True
    assert result.recommendation.suggested_message
    assert len(fake.calls) == 1


def test_agent_recommends_no_follow_up_for_a_recently_contacted_lead(db_session: Session, organization_id, current_user):
    """Spec scenario 2."""
    contact = _make_contact(db_session, organization_id)
    db_session.add(
        Activity(
            organization_id=organization_id, contact_id=contact.id, activity_type="call",
            direction="outbound", occurred_at=_occurred(28), notes="Llamada de seguimiento reciente",
        )
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_no_follow_up())

    result = FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    assert result.recommendation.should_follow_up is False
    assert result.recommendation.recommended_channel == "none"
    assert result.recommendation.suggested_message is None


def test_agent_prompt_reflects_days_without_response(db_session: Session, organization_id, current_user):
    """Spec scenario 3: prompt must carry the timing facts the model needs to reason about, not a precomputed verdict."""
    contact = _make_contact(db_session, organization_id)
    db_session.add(
        Activity(
            organization_id=organization_id, contact_id=contact.id, activity_type="whatsapp",
            direction="outbound", occurred_at=_occurred(1), notes="Mensaje sin respuesta",
        )
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_needs_follow_up())

    FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    user_prompt = fake.calls[0][1]
    assert '"direction": "outbound"' in user_prompt
    assert '"days_since_last_activity"' in user_prompt


def test_agent_includes_both_the_rejected_interest_and_the_new_search(db_session: Session, organization_id, current_user):
    """Spec scenario 4: Gabriela's Case A -> Case B pattern — both facts must reach the prompt together."""
    contact = _make_contact(db_session, organization_id, first_name="Gabriela", last_name="Ortiz")
    prop = Property(organization_id=organization_id, title="Departamento Del Valle", property_type="apartment", status="active", price=3400000)
    db_session.add(prop)
    db_session.commit()
    db_session.add_all(
        [
            PropertyInterest(organization_id=organization_id, contact_id=contact.id, property_id=prop.id, status="not_interested"),
            BuyerRequirement(organization_id=organization_id, contact_id=contact.id, status="active", property_type="apartment"),
        ]
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_needs_follow_up(recommended_action="send_properties"))

    FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    user_prompt = fake.calls[0][1]
    assert "not_interested" in user_prompt
    assert '"status": "active"' in user_prompt  # the buyer_requirement's status


def test_agent_prompt_reflects_recent_strong_engagement(db_session: Session, organization_id, current_user):
    """Spec scenario 5."""
    contact = _make_contact(db_session, organization_id)
    db_session.add_all(
        [
            Activity(organization_id=organization_id, contact_id=contact.id, activity_type="call", occurred_at=_occurred(1), notes="a"),
            Activity(organization_id=organization_id, contact_id=contact.id, activity_type="whatsapp", occurred_at=_occurred(2), notes="b"),
            Activity(organization_id=organization_id, contact_id=contact.id, activity_type="property_viewing", occurred_at=_occurred(3), notes="c"),
        ]
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_needs_follow_up())

    FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    assert '"activity_count": 3' in fake.calls[0][1]


def test_agent_handles_a_contact_with_no_activity_history(db_session: Session, organization_id, current_user):
    """Spec scenario 6: insufficient activity information — the agent must still build a valid context, not crash."""
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_needs_follow_up(reason="Brand-new contact with no prior interaction on record."))

    result = FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    assert result.contact_id == contact.id
    assert '"activity_count": 0' in fake.calls[0][1]


def test_agent_raises_404_for_a_nonexistent_contact_without_calling_the_llm(db_session: Session, current_user):
    """Spec scenario 12."""
    fake = FakeLLMProvider(response=_needs_follow_up())

    with pytest.raises(HTTPException) as exc_info:
        FollowUpAgent(db_session, fake).recommend(current_user, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert fake.calls == []


def test_agent_enforces_organization_isolation(db_session: Session):
    """Spec scenario 11: a user in org A must not be able to run the agent against org B's contact."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    contact_b = _make_contact(db_session, org_b.id, first_name="Ajeno", last_name="Contact")
    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    fake = FakeLLMProvider(response=_needs_follow_up())

    with pytest.raises(HTTPException) as exc_info:
        FollowUpAgent(db_session, fake).recommend(user_a, contact_b.id)

    assert exc_info.value.status_code == 404
    assert fake.calls == []


def test_agent_propagates_llm_invalid_output(db_session: Session, organization_id, current_user):
    """Spec scenario 10: malformed LLM response."""
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))

    with pytest.raises(LLMInvalidOutputError):
        FollowUpAgent(db_session, fake).recommend(current_user, contact.id)


def test_agent_propagates_llm_provider_error(db_session: Session, organization_id, current_user):
    """Spec scenario 13: Ollama-unavailable and similar provider failures propagate through the same LLMError family the provider layer already raises (see tests/test_ollama_provider.py for that layer's own coverage)."""
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMProviderError("Is Ollama running?"))

    with pytest.raises(LLMProviderError):
        FollowUpAgent(db_session, fake).recommend(current_user, contact.id)


def test_agent_propagates_llm_timeout(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMTimeoutError("slow"))

    with pytest.raises(LLMTimeoutError):
        FollowUpAgent(db_session, fake).recommend(current_user, contact.id)


def test_agent_does_not_modify_any_crm_data(db_session: Session, organization_id, current_user):
    """Spec scenario 14: the agent is read-only — no Contact/Activity/BuyerRequirement row is created, changed, or removed."""
    contact = _make_contact(db_session, organization_id)
    db_session.add(
        Activity(organization_id=organization_id, contact_id=contact.id, activity_type="call", occurred_at=_occurred(1), notes="x")
    )
    db_session.commit()
    contacts_before = db_session.scalar(select(func.count()).select_from(Contact))
    activities_before = db_session.scalar(select(func.count()).select_from(Activity))
    requirements_before = db_session.scalar(select(func.count()).select_from(BuyerRequirement))
    fake = FakeLLMProvider(response=_needs_follow_up())

    FollowUpAgent(db_session, fake).recommend(current_user, contact.id)

    assert db_session.scalar(select(func.count()).select_from(Contact)) == contacts_before
    assert db_session.scalar(select(func.count()).select_from(Activity)) == activities_before
    assert db_session.scalar(select(func.count()).select_from(BuyerRequirement)) == requirements_before


# --- Route ----------------------------------------------------------------------------------------


def test_route_returns_recommendation_when_provider_is_overridden(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Ivan", "last_name": "Solis", "phone": "+52 81 5500 8888"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_needs_follow_up())
    try:
        response = client.post(f"/api/v1/ai/follow-up/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 200
    body = response.json()
    assert body["contact_id"] == contact["id"]
    assert body["recommendation"]["should_follow_up"] is True
    assert body["recommendation"]["recommended_channel"] == "whatsapp"
    assert body["model"] == "fake-model-v1"


def test_route_returns_503_when_anthropic_is_selected_without_a_key(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Nadia", "last_name": "Cruz", "phone": "+52 81 5500 9999"}
    ).json()

    response = client.post(f"/api/v1/ai/follow-up/{contact['id']}")

    assert response.status_code == 503


def test_route_returns_504_on_llm_timeout(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Beto", "last_name": "Longoria", "phone": "+52 81 5500 1111"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMTimeoutError("slow"))
    try:
        response = client.post(f"/api/v1/ai/follow-up/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 504


def test_route_returns_502_on_invalid_llm_output(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Paty", "last_name": "Villa", "phone": "+52 81 5500 2222"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))
    try:
        response = client.post(f"/api/v1/ai/follow-up/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 502


def test_route_returns_502_on_llm_provider_error(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Mario", "last_name": "Reyes", "phone": "+52 81 5500 3333"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMProviderError("Is Ollama running?"))
    try:
        response = client.post(f"/api/v1/ai/follow-up/{contact['id']}")
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
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_needs_follow_up())
    try:
        test_client = TestClient(app)
        response = test_client.post(f"/api/v1/ai/follow-up/{contact.id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
