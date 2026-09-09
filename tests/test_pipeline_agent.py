"""
The Pipeline Agent (app/ai/pipeline_agent.py) and its route. Entirely
deterministic and offline — every test here uses FakeLLMProvider instead of
a real Ollama/Anthropic call, so this file needs no local Ollama and never
touches the network. See tests/test_pipeline_agent_ollama_integration.py
for the real-LLM smoke test, which requires an explicit opt-in.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.ai.pipeline_agent import PipelineAgent
from app.api.routes.ai import _get_llm_provider
from app.main import app
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.task import Task
from app.schemas.pipeline import ImmediateAction, OpportunityRecommendation, PipelineAnalysis, RiskFlag
from app.schemas.user import CurrentUser


class FakeLLMProvider(LLMProvider):
    """Same pattern as tests/test_lead_intelligence_agent.py's — see there for why."""

    def __init__(self, *, response: PipelineAnalysis | None = None, error: Exception | None = None):
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


def _valid_analysis(**overrides) -> PipelineAnalysis:
    fields = {
        "overall_priority": "medium",
        "summary": "One active opportunity in negotiation, no immediate risks.",
        "opportunities": [],
        "immediate_actions": [],
        "risk_flags": [],
        "confidence": 0.75,
    }
    fields.update(overrides)
    return PipelineAnalysis(**fields)


def _make_contact(db_session: Session, organization_id, **overrides) -> Contact:
    fields = {"organization_id": organization_id, "first_name": "Luis", "last_name": "Cantu", "phone": "+52 81 5500 7777"}
    fields.update(overrides)
    contact = Contact(**fields)
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)
    return contact


def _make_opportunity(db_session: Session, organization_id, contact_id, **overrides) -> Opportunity:
    fields = {"organization_id": organization_id, "contact_id": contact_id, "opportunity_type": "buy", "stage": "qualification", "title": "Test opportunity"}
    fields.update(overrides)
    opportunity = Opportunity(**fields)
    db_session.add(opportunity)
    db_session.commit()
    db_session.refresh(opportunity)
    return opportunity


def _in_days(n: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=n)


# --- PipelineAnalysis schema -----------------------------------------------------------


def test_analysis_schema_accepts_a_well_formed_payload():
    analysis = _valid_analysis()
    assert analysis.overall_priority == "medium"
    assert 0.0 <= analysis.confidence <= 1.0


def test_analysis_schema_accepts_nested_opportunity_action_and_risk_items():
    opp_id = uuid.uuid4()
    analysis = _valid_analysis(
        opportunities=[
            OpportunityRecommendation(
                opportunity_id=opp_id, priority="high", status_assessment="In negotiation, active.",
                reason="Recent activity and offer stage.", recommended_action="negotiate", confidence=0.8,
            )
        ],
        immediate_actions=[
            ImmediateAction(opportunity_id=opp_id, action="follow_up", reason="No contact in 5 days.", urgency="high")
        ],
        risk_flags=[
            RiskFlag(opportunity_id=opp_id, risk="High value with no recent activity.", reason="expected_value is 6M, last activity 12 days ago.", severity="high")
        ],
    )
    assert analysis.opportunities[0].opportunity_id == opp_id
    assert analysis.immediate_actions[0].urgency == "high"
    assert analysis.risk_flags[0].severity == "high"


def test_analysis_schema_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        _valid_analysis(confidence=1.5)


def test_analysis_schema_rejects_unknown_overall_priority():
    with pytest.raises(ValidationError):
        _valid_analysis(overall_priority="urgent")  # not a LeadPriority value


def test_opportunity_recommendation_rejects_unknown_action():
    with pytest.raises(ValidationError):
        OpportunityRecommendation(
            opportunity_id=uuid.uuid4(), priority="high", status_assessment="x", reason="x",
            recommended_action="send_carrier_pigeon", confidence=0.5,
        )


def test_risk_flag_rejects_confidence_like_severity_out_of_enum():
    with pytest.raises(ValidationError):
        RiskFlag(opportunity_id=uuid.uuid4(), risk="x", reason="x", severity="critical")  # not a LeadPriority value


# --- Agent: context retrieval, authorization, prompt construction -----------------------------


def test_agent_returns_validated_result_for_a_contact_with_no_opportunities(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_analysis())

    result = PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert result.contact_id == contact.id
    assert result.model == "fake-model-v1"
    assert result.analysis.opportunities == []
    assert len(fake.calls) == 1


def test_agent_analyzes_a_contact_with_one_active_opportunity(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id, stage="negotiation")
    fake = FakeLLMProvider(
        response=_valid_analysis(
            opportunities=[
                OpportunityRecommendation(
                    opportunity_id=opportunity.id, priority="high", status_assessment="In negotiation.",
                    reason="Active negotiation stage.", recommended_action="negotiate", confidence=0.8,
                )
            ]
        )
    )

    result = PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert len(result.analysis.opportunities) == 1
    assert result.analysis.opportunities[0].opportunity_id == opportunity.id
    assert str(opportunity.id) in fake.calls[0][1]  # the opportunity's own id reached the prompt


def test_agent_analyzes_a_contact_with_multiple_opportunities(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    buy = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="buy", stage="search")
    sell = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="sell", stage="listing")
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    user_prompt = fake.calls[0][1]
    assert str(buy.id) in user_prompt
    assert str(sell.id) in user_prompt
    assert '"opportunity_type": "buy"' in user_prompt
    assert '"opportunity_type": "sell"' in user_prompt


def test_agent_analyzes_a_won_opportunity(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="won", closed_at=datetime.now(timezone.utc))
    fake = FakeLLMProvider(response=_valid_analysis(summary="One opportunity, already won."))

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"stage": "won"' in fake.calls[0][1]
    assert '"is_active": false' in fake.calls[0][1]


def test_agent_analyzes_a_lost_opportunity(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(
        db_session, organization_id, contact.id, stage="lost", lost_reason="price", closed_at=datetime.now(timezone.utc)
    )
    fake = FakeLLMProvider(response=_valid_analysis(summary="One opportunity, lost on price."))

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"stage": "lost"' in fake.calls[0][1]
    assert '"lost_reason": "price"' in fake.calls[0][1]


def test_agent_analyzes_active_and_lost_opportunities_together(db_session: Session, organization_id, current_user):
    """The lost opportunity must not disappear just because an active one also exists — history stays visible."""
    contact = _make_contact(db_session, organization_id)
    lost = _make_opportunity(db_session, organization_id, contact.id, stage="lost", lost_reason="chose_another_property", closed_at=datetime.now(timezone.utc))
    active = _make_opportunity(db_session, organization_id, contact.id, stage="search")
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    user_prompt = fake.calls[0][1]
    assert str(lost.id) in user_prompt
    assert str(active.id) in user_prompt


def test_agent_analyzes_an_opportunity_with_an_overdue_task(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id)
    db_session.add(
        Task(
            organization_id=organization_id, opportunity_id=opportunity.id, assigned_to_user_id=current_user.id,
            title="Overdue follow-up", task_type="follow_up", status="pending", priority="high", due_at=_in_days(-3),
        )
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"overdue_task_count": 1' in fake.calls[0][1]


def test_agent_analyzes_an_opportunity_with_an_upcoming_appointment(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id, opportunity_type="sell")
    start = _in_days(2)
    db_session.add(
        Appointment(
            organization_id=organization_id, opportunity_id=opportunity.id, contact_id=contact.id,
            title="Showing", appointment_type="showing", status="confirmed", start_at=start, end_at=start + timedelta(hours=1),
        )
    )
    db_session.commit()
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"upcoming_appointment_count": 1' in fake.calls[0][1]


def test_agent_analyzes_an_opportunity_in_negotiation(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="negotiation")
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"stage": "negotiation"' in fake.calls[0][1]


def test_agent_analyzes_an_opportunity_with_an_offer(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="offer")
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"stage": "offer"' in fake.calls[0][1]


def test_agent_analyzes_a_stale_opportunity(db_session: Session, organization_id, current_user):
    """'Stale' isn't a stored field — the agent must be able to see the raw signals (old created_at, no recent activity) and reason from them itself."""
    contact = _make_contact(db_session, organization_id)
    _make_opportunity(db_session, organization_id, contact.id, stage="showing", created_at=datetime.now(timezone.utc) - timedelta(days=40))
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    assert '"activity_count": 0' in fake.calls[0][1]  # no activity at all reaches the model as a plain fact, not a pre-judged label


def test_agent_raises_404_for_a_nonexistent_contact_without_calling_the_llm(db_session: Session, current_user):
    fake = FakeLLMProvider(response=_valid_analysis())

    with pytest.raises(HTTPException) as exc_info:
        PipelineAgent(db_session, fake).analyze(current_user, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert fake.calls == []


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
        PipelineAgent(db_session, fake).analyze(user_a, contact_b.id)

    assert exc_info.value.status_code == 404
    assert fake.calls == []


def test_agent_isolates_opportunities_from_another_organization(db_session: Session):
    """Belt-and-suspenders: even the pipeline data itself is never visible across organizations."""
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.commit()

    contact_a = _make_contact(db_session, org_a.id)
    contact_b = _make_contact(db_session, org_b.id, first_name="Ajeno", last_name="Contact")
    other_opportunity = _make_opportunity(db_session, org_b.id, contact_b.id)
    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(user_a, contact_a.id)

    assert str(other_opportunity.id) not in fake.calls[0][1]


def test_agent_prompt_includes_pipeline_analyst_instructions(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_analysis())

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    system_prompt = fake.calls[0][0]
    assert "real-estate CRM pipeline analyst" in system_prompt


def test_agent_propagates_llm_timeout(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMTimeoutError("slow"))

    with pytest.raises(LLMTimeoutError):
        PipelineAgent(db_session, fake).analyze(current_user, contact.id)


def test_agent_propagates_llm_invalid_output(db_session: Session, organization_id, current_user):
    """Malformed LLM output (fails Pydantic validation against PipelineAnalysis) surfaces as LLMInvalidOutputError, same as the other two agents."""
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))

    with pytest.raises(LLMInvalidOutputError):
        PipelineAgent(db_session, fake).analyze(current_user, contact.id)


def test_agent_propagates_llm_provider_error(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMProviderError("Is Ollama running?"))

    with pytest.raises(LLMProviderError):
        PipelineAgent(db_session, fake).analyze(current_user, contact.id)


def test_agent_does_not_modify_any_crm_data(db_session: Session, organization_id, current_user):
    """Read-only by construction: running the agent must not change the opportunity's own row."""
    contact = _make_contact(db_session, organization_id)
    opportunity = _make_opportunity(db_session, organization_id, contact.id, stage="negotiation")
    fake = FakeLLMProvider(
        response=_valid_analysis(
            opportunities=[
                OpportunityRecommendation(
                    opportunity_id=opportunity.id, priority="high", status_assessment="x", reason="x",
                    recommended_action="negotiate", confidence=0.8,
                )
            ]
        )
    )

    PipelineAgent(db_session, fake).analyze(current_user, contact.id)

    db_session.refresh(opportunity)
    assert opportunity.stage == "negotiation"  # untouched


# --- Route --------------------------------------------------------------------------------------


def test_route_returns_analysis_when_provider_is_overridden(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Ivan", "last_name": "Solis", "phone": "+52 81 5500 8888"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        response = client.post(f"/api/v1/ai/pipeline/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 200
    body = response.json()
    assert body["contact_id"] == contact["id"]
    assert body["analysis"]["overall_priority"] == "medium"
    assert body["model"] == "fake-model-v1"


def test_route_returns_503_when_anthropic_is_selected_without_a_key(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Nadia", "last_name": "Cruz", "phone": "+52 81 5500 9999"}
    ).json()

    response = client.post(f"/api/v1/ai/pipeline/{contact['id']}")

    assert response.status_code == 503


def test_route_returns_504_on_llm_timeout(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Beto", "last_name": "Longoria", "phone": "+52 81 5500 1111"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMTimeoutError("slow"))
    try:
        response = client.post(f"/api/v1/ai/pipeline/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 504


def test_route_returns_502_on_invalid_llm_output(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Paty", "last_name": "Villa", "phone": "+52 81 5500 2222"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))
    try:
        response = client.post(f"/api/v1/ai/pipeline/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 502


def test_route_returns_502_on_llm_provider_error(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Memo", "last_name": "Ibarra", "phone": "+52 81 5500 3333"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMProviderError("Is Ollama running?"))
    try:
        response = client.post(f"/api/v1/ai/pipeline/{contact['id']}")
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
        response = test_client.post(f"/api/v1/ai/pipeline/{contact.id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_route_persists_an_agent_execution(client: TestClient):
    """Reuses the existing AgentExecution mechanism (app/api/routes/ai.py's _run_and_record) — no new persistence code needed for a third agent."""
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Rosa", "last_name": "Elizondo", "phone": "+52 81 5500 4444"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        response = client.post(f"/api/v1/ai/pipeline/{contact['id']}")
        assert response.status_code == 200
        executions = client.get("/api/v1/ai/agent-executions", params={"agent_name": "pipeline"}).json()
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert len(executions) == 1
    assert executions[0]["status"] == "succeeded"
    assert executions[0]["contact_id"] == contact["id"]
