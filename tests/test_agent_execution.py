"""
AgentExecution persistence (app/models/agent_execution.py,
app/services/agent_execution_service.py) — wired into app/api/routes/ai.py's
_run_and_record, not into AIGateway itself (see that function's docstring).
Entirely offline via FakeLLMProvider, same pattern as
tests/test_follow_up_agent.py.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMTimeoutError
from app.api.routes.ai import _get_llm_provider
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.main import app
from app.models.organization import Organization, User
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis
from app.schemas.user import CurrentUser


class FakeLLMProvider(LLMProvider):
    def __init__(self, *, response=None, error: Exception | None = None):
        self._response = response
        self._error = error

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    def generate_structured(self, *, system_prompt, user_prompt, response_model, max_tokens=1024):
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _valid_analysis() -> LeadIntelligenceAnalysis:
    return LeadIntelligenceAnalysis(
        priority="high", confidence=0.8, reasoning="Active buyer requirement and recent activity.",
        positive_signals=[], risk_signals=[], recommended_next_action="call", insufficient_data=False,
    )


def _create_contact(client: TestClient) -> dict:
    return client.post(
        "/api/v1/contacts", json={"first_name": "Luis", "last_name": "Cantu", "phone": "+52 81 5500 7777"}
    ).json()


def test_successful_run_persists_an_agent_execution(client: TestClient, current_user: CurrentUser):
    contact = _create_contact(client)
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        response = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]
    assert response.status_code == 200

    executions = client.get("/api/v1/ai/agent-executions").json()
    assert len(executions) == 1
    execution = executions[0]
    assert execution["status"] == "succeeded"
    assert execution["agent_name"] == "lead_intelligence"
    assert execution["agent_version"]  # non-empty, traceable
    assert execution["contact_id"] == contact["id"]
    assert execution["user_id"] == str(current_user.id)
    assert execution["provider"] == "fake"
    assert execution["model"] == "fake-model-v1"
    assert execution["duration_ms"] >= 0
    assert execution["output"]["analysis"]["priority"] == "high"
    assert execution["human_action"] is None


def test_failed_run_persists_an_agent_execution_with_failed_status(client: TestClient):
    contact = _create_contact(client)
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(error=LLMTimeoutError("slow"))
    try:
        response = client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]
    assert response.status_code == 504

    executions = client.get("/api/v1/ai/agent-executions").json()
    assert len(executions) == 1
    assert executions[0]["status"] == "failed"
    assert executions[0]["output"]["error"] == "LLMTimeoutError"
    assert "slow" in executions[0]["output"]["message"]


def test_a_cross_organization_contact_does_not_create_an_agent_execution(client: TestClient):
    """A 404 from context authorization is an authorization outcome, not an AI one — see AIGateway.run()'s own documented behavior, extended here to persistence."""
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        response = client.post(f"/api/v1/ai/lead-intelligence/{uuid.uuid4()}")
    finally:
        del app.dependency_overrides[_get_llm_provider]
    assert response.status_code == 404
    assert client.get("/api/v1/ai/agent-executions").json() == []


def test_agent_executions_can_be_filtered_by_contact(client: TestClient):
    contact_a = _create_contact(client)
    contact_b = client.post(
        "/api/v1/contacts", json={"first_name": "Ana", "last_name": "Ruiz", "phone": "+52 81 5500 8888"}
    ).json()
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        client.post(f"/api/v1/ai/lead-intelligence/{contact_a['id']}")
        client.post(f"/api/v1/ai/lead-intelligence/{contact_b['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    filtered = client.get("/api/v1/ai/agent-executions", params={"contact_id": contact_a["id"]}).json()
    assert len(filtered) == 1
    assert filtered[0]["contact_id"] == contact_a["id"]


def test_set_human_action_records_when_an_advisor_acts_on_a_recommendation(client: TestClient):
    contact = _create_contact(client)
    app.dependency_overrides[_get_llm_provider] = lambda: FakeLLMProvider(response=_valid_analysis())
    try:
        client.post(f"/api/v1/ai/lead-intelligence/{contact['id']}")
    finally:
        del app.dependency_overrides[_get_llm_provider]
    execution_id = client.get("/api/v1/ai/agent-executions").json()[0]["id"]

    updated = client.patch(f"/api/v1/ai/agent-executions/{execution_id}", json={"human_action": "acted_on"})
    assert updated.status_code == 200
    assert updated.json()["human_action"] == "acted_on"
    assert updated.json()["human_action_at"] is not None


def test_agent_executions_are_isolated_by_organization(db_session: Session):
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
        execution_b_id = client_b.get("/api/v1/ai/agent-executions").json()[0]["id"]
    finally:
        app.dependency_overrides.clear()

    user_a = CurrentUser(id=uuid.uuid4(), email="a@example.com", organization_id=org_a.id, role="owner", provider="email")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_org_user] = lambda: user_a
    try:
        client_a = TestClient(app)
        assert client_a.get("/api/v1/ai/agent-executions").json() == []
        assert client_a.get(f"/api/v1/ai/agent-executions/{execution_b_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
