"""Phase 1 execution guards: idempotency, single-flight, cooldown and limits."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.llm.errors import LLMTimeoutError
from app.api.routes.ai import _get_llm_provider
from app.core.config import settings
from app.main import app
from app.schemas.follow_up import FollowUpRecommendation
from app.schemas.user import CurrentUser
from app.services.agent_execution_service import AgentExecutionService
from tests.test_agent_execution import FakeLLMProvider, _create_contact, _valid_analysis


class CountingProvider(FakeLLMProvider):
    def __init__(self, *, response=None, error=None):
        super().__init__(response=response, error=error)
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        return super().generate_structured(**kwargs)


def _post(client: TestClient, contact_id: str, key: str):
    return client.post(
        f"/api/v1/ai/lead-intelligence/{contact_id}",
        headers={"Idempotency-Key": key},
    )


def test_same_idempotency_key_replays_success_without_calling_llm_twice(client: TestClient):
    contact = _create_contact(client)
    provider = CountingProvider(response=_valid_analysis())
    app.dependency_overrides[_get_llm_provider] = lambda: provider
    try:
        first = _post(client, contact["id"], "request-12345678")
        second = _post(client, contact["id"], "request-12345678")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert provider.calls == 1
    assert len(client.get("/api/v1/ai/agent-executions").json()) == 1


def test_existing_run_returns_202_and_the_same_execution_id(
    client: TestClient, db_session: Session, current_user: CurrentUser
):
    contact = _create_contact(client)
    reserved = AgentExecutionService(db_session).begin(
        organization_id=current_user.organization_id,
        agent_name="lead_intelligence",
        agent_version="1.0.0",
        contact_id=uuid.UUID(contact["id"]),
        user_id=current_user.id,
        provider="fake",
        model="fake-model-v1",
        idempotency_key="original-12345678",
    )
    provider = CountingProvider(response=_valid_analysis())
    app.dependency_overrides[_get_llm_provider] = lambda: provider
    try:
        response = _post(client, contact["id"], "duplicate-12345678")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 202
    assert response.json() == {
        "status": "running",
        "execution_id": str(reserved.execution.id),
        "retry_after_seconds": 2,
    }
    assert provider.calls == 0


def test_different_agent_can_run_for_the_same_contact_while_one_is_active(
    client: TestClient, db_session: Session, current_user: CurrentUser
):
    contact = _create_contact(client)
    AgentExecutionService(db_session).begin(
        organization_id=current_user.organization_id,
        agent_name="lead_intelligence",
        agent_version="1.0.0",
        contact_id=uuid.UUID(contact["id"]),
        user_id=current_user.id,
        provider="fake",
        model="fake-model-v1",
        idempotency_key="lead-active-12345678",
    )
    provider = CountingProvider(
        response=FollowUpRecommendation(
            should_follow_up=True,
            priority="high",
            recommended_channel="whatsapp",
            recommended_action="follow_up",
            reason="Recent interest.",
            suggested_message="Hola",
            confidence=0.8,
        )
    )
    app.dependency_overrides[_get_llm_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/ai/follow-up/{contact['id']}",
            headers={"Idempotency-Key": "follow-up-12345678"},
        )
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 200
    assert provider.calls == 1


def test_idempotency_key_cannot_be_reused_for_a_different_contact(client: TestClient):
    first = _create_contact(client)
    second = client.post(
        "/api/v1/contacts",
        json={"first_name": "B", "last_name": "Client", "phone": "+52 81 5500 9090"},
    ).json()
    provider = CountingProvider(response=_valid_analysis())
    app.dependency_overrides[_get_llm_provider] = lambda: provider
    try:
        assert _post(client, first["id"], "shared-key-12345678").status_code == 200
        response = _post(client, second["id"], "shared-key-12345678")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert provider.calls == 1


def test_cooldown_returns_retry_after_without_second_llm_call(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ai_agent_cooldown_seconds", 60)
    contact = _create_contact(client)
    provider = CountingProvider(response=_valid_analysis())
    app.dependency_overrides[_get_llm_provider] = lambda: provider
    try:
        assert _post(client, contact["id"], "cooldown-a-12345").status_code == 200
        response = _post(client, contact["id"], "cooldown-b-12345")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "AI_COOLDOWN"
    assert response.json()["error"]["retry_after"] > 0
    assert int(response.headers["Retry-After"]) > 0
    assert provider.calls == 1


def test_user_rate_limit_is_organization_scoped_and_blocks_provider(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ai_user_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "ai_agent_cooldown_seconds", 0)
    first_contact = _create_contact(client)
    second_contact = client.post(
        "/api/v1/contacts",
        json={"first_name": "Ana", "last_name": "Ruiz", "phone": "+52 81 5500 9988"},
    ).json()
    provider = CountingProvider(response=_valid_analysis())
    app.dependency_overrides[_get_llm_provider] = lambda: provider
    try:
        assert _post(client, first_contact["id"], "limit-a-12345678").status_code == 200
        response = _post(client, second_contact["id"], "limit-b-12345678")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "AI_USER_RATE_LIMIT"
    assert provider.calls == 1


def test_failed_run_releases_single_flight_for_a_new_request(client: TestClient):
    contact = _create_contact(client)
    failing = CountingProvider(error=LLMTimeoutError("slow"))
    app.dependency_overrides[_get_llm_provider] = lambda: failing
    try:
        assert _post(client, contact["id"], "failed-a-12345678").status_code == 504
    finally:
        del app.dependency_overrides[_get_llm_provider]

    succeeding = CountingProvider(response=_valid_analysis())
    app.dependency_overrides[_get_llm_provider] = lambda: succeeding
    try:
        response = _post(client, contact["id"], "success-b-12345678")
    finally:
        del app.dependency_overrides[_get_llm_provider]

    assert response.status_code == 200
    assert succeeding.calls == 1
    statuses = [item["status"] for item in client.get("/api/v1/ai/agent-executions").json()]
    assert statuses == ["succeeded", "failed"]
