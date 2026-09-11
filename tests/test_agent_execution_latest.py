"""
GET /ai/agent-executions/latest — "PERSISTENT AI AGENT RESULTS PER CLIENT +
SMART REFRESH". Restoring a client's previous analysis on switch, and
detecting when it's gone stale relative to the contact's current CRM data.
See app/api/routes/agent_executions.py, app/services/agent_execution_service.py
(get_latest_succeeded), and app/services/lead_context_service.py
(compute_context_fingerprint).

Entirely offline via FakeLLMProvider, same pattern as test_agent_execution.py.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes.ai import _get_llm_provider
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.follow_up import FollowUpRecommendation
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis
from app.schemas.user import CurrentUser
from tests.test_agent_execution import FakeLLMProvider, _create_contact, _valid_analysis


def _run_lead_intelligence(client: TestClient, contact_id: str, *, response=None) -> None:
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=response or _valid_analysis())
    try:
        result = client.post(f"/api/v1/ai/lead-intelligence/{contact_id}")
        assert result.status_code == 200
    finally:
        del app.dependency_overrides[_get_llm_provider]


def test_returns_null_when_no_execution_exists_yet(client: TestClient):
    contact = _create_contact(client)
    response = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    )
    assert response.status_code == 200
    assert response.json() is None


def test_returns_the_latest_succeeded_execution_and_it_starts_fresh(client: TestClient):
    contact = _create_contact(client)
    _run_lead_intelligence(client, contact["id"])

    response = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    )
    body = response.json()
    assert body is not None
    assert body["contact_id"] == contact["id"]
    assert body["agent_name"] == "lead_intelligence"
    assert body["status"] == "succeeded"
    assert body["is_stale"] is False


def test_a_failed_retry_does_not_shadow_the_last_real_success(client: TestClient):
    contact = _create_contact(client)
    _run_lead_intelligence(client, contact["id"])

    from app.ai.llm.errors import LLMTimeoutError

    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMTimeoutError("slow"))
    try:
        failed = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
        assert failed.status_code == 504
    finally:
        del app.dependency_overrides[_get_llm_provider]

    body = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert body is not None
    assert body["status"] == "succeeded"


def test_the_agents_are_independent_per_contact_and_per_agent_type(client: TestClient):
    """Client A's Lead Intelligence result must never appear as Client B's, and Follow-up must stay independent of Lead Intelligence for the same contact — the identity is (contact_id, agent_type), never just one or the other."""
    contact_a = _create_contact(client)
    contact_b = client.post(
        "/api/v1/contacts", json={"first_name": "Beatriz", "last_name": "Lopez", "phone": "+52 81 5500 9999"}
    ).json()

    _run_lead_intelligence(client, contact_a["id"])

    # Contact B has never been analyzed — must be null, never A's result.
    b_result = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact_b["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert b_result is None

    # Follow-up for contact A has never been run either — a different
    # agent_type for the SAME contact must also be independently empty.
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(
        response=FollowUpRecommendation(
            should_follow_up=True, confidence=0.7, priority="medium", recommended_channel="whatsapp",
            recommended_action="send_message", reason="Recent interest.", suggested_message="Hola!",
        )
    )
    try:
        follow_up_a = client.get(
            "/api/v1/ai/agent-executions/latest", params={"contact_id": contact_a["id"], "agent_name": "follow_up"}
        ).json()
    finally:
        del app.dependency_overrides[_get_llm_provider]
    assert follow_up_a is None

    a_result = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact_a["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert a_result is not None
    assert a_result["contact_id"] == contact_a["id"]


def test_organizations_cannot_see_each_others_latest_execution(db_session: Session):
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    user_b_row = User(id=uuid.uuid4(), organization_id=org_b.id, role="owner")
    db_session.add(user_b_row)
    db_session.commit()
    user_b = CurrentUser(id=user_b_row.id, email="b@example.com", organization_id=org_b.id, role="owner", provider="email")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_b
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        client_b = TestClient(app)
        contact_b = _create_contact(client_b)
        client_b.post(f"/api/v1/ai/lead-intelligence/{contact_b['id']}")
        contact_b_id = contact_b["id"]
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        # Org A's token, but org B's contact_id — must not leak org B's result.
        result = client_a.get(
            "/api/v1/ai/agent-executions/latest", params={"contact_id": contact_b_id, "agent_name": "lead_intelligence"}
        ).json()
        assert result is None
    finally:
        app.dependency_overrides.clear()


def test_a_relevant_crm_change_marks_the_stored_result_stale(client: TestClient):
    contact = _create_contact(client)
    _run_lead_intelligence(client, contact["id"])

    # A new Buyer Requirement is exactly the kind of data every agent's
    # LeadContext includes — this must flip the stored result to stale.
    created = client.post(f"/api/v1/contacts/{contact['id']}/buyer-requirements", json={"property_type": "house"})
    assert created.status_code == 201

    body = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert body["is_stale"] is True


def test_an_unrelated_organization_change_does_not_mark_anything_stale(client: TestClient):
    """Be conservative: a completely unrelated contact's data changing must not flip this contact's result to stale."""
    contact = _create_contact(client)
    _run_lead_intelligence(client, contact["id"])

    other_contact = client.post(
        "/api/v1/contacts", json={"first_name": "Otro", "last_name": "Cliente", "phone": "+52 81 5500 1111"}
    ).json()
    client.post(f"/api/v1/contacts/{other_contact['id']}/buyer-requirements", json={"property_type": "house"})

    body = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert body["is_stale"] is False


def test_manual_refresh_creates_a_new_execution_and_the_result_is_fresh_again(client: TestClient):
    contact = _create_contact(client)
    _run_lead_intelligence(client, contact["id"])
    client.post(f"/api/v1/contacts/{contact['id']}/buyer-requirements", json={"property_type": "house"})

    stale = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert stale["is_stale"] is True
    first_execution_id = stale["id"]

    # The manual Refresh action is just calling the same real POST endpoint again.
    _run_lead_intelligence(client, contact["id"])

    refreshed = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert refreshed["is_stale"] is False
    assert refreshed["id"] != first_execution_id

    all_executions = client.get(
        "/api/v1/ai/agent-executions", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert len(all_executions) == 2  # a real new AgentExecution row, not an overwrite


def test_multiple_historical_executions_return_the_latest_one(client: TestClient):
    contact = _create_contact(client)
    _run_lead_intelligence(
        client, contact["id"],
        response=LeadIntelligenceAnalysis(
            priority="low", confidence=0.5, reasoning="First pass.", positive_signals=[], risk_signals=[],
            recommended_next_action="no_action_needed", insufficient_data=False,
        ),
    )
    _run_lead_intelligence(
        client, contact["id"],
        response=LeadIntelligenceAnalysis(
            priority="high", confidence=0.9, reasoning="Second pass, more recent.", positive_signals=[], risk_signals=[],
            recommended_next_action="call", insufficient_data=False,
        ),
    )

    body = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    ).json()
    assert body["output"]["analysis"]["priority"] == "high"
    assert body["output"]["analysis"]["reasoning"] == "Second pass, more recent."


def test_reading_the_latest_execution_never_invokes_the_llm_provider(client: TestClient):
    """
    No override for _get_llm_provider is installed for this call — if the
    route depended on it at all (i.e. re-ran the agent instead of reading
    the stored row), this would raise a 503 "not configured" in this test
    environment, since no real Ollama/API key is configured. A clean 200
    here is itself the proof that restoring a result performs no LLM call.
    """
    contact = _create_contact(client)
    _run_lead_intelligence(client, contact["id"])

    response = client.get(
        "/api/v1/ai/agent-executions/latest", params={"contact_id": contact["id"], "agent_name": "lead_intelligence"}
    )
    assert response.status_code == 200
    assert response.json()["is_stale"] is False
