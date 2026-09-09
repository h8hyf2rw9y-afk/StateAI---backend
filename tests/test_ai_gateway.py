"""
The AI Gateway (app/ai/gateway.py) and Agent Registry (app/ai/registry.py).
Entirely offline via FakeLLMProvider — no real Ollama/Anthropic call.
"""

import logging
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ai.gateway import AIGateway, ExecutionMetadata, GatewayExecution
from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMInvalidOutputError, LLMTimeoutError
from app.ai.registry import AGENT_REGISTRY, get_agent, list_agents
from app.models.contact import Contact
from app.schemas.follow_up import FollowUpRecommendation, FollowUpResult
from app.schemas.lead_context import LeadContext
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis, LeadIntelligenceResult
from app.schemas.pipeline import PipelineAnalysis, PipelineResult
from app.schemas.user import CurrentUser


class FakeLLMProvider(LLMProvider):
    def __init__(self, *, response=None, error: Exception | None = None):
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


def _valid_lead_intelligence_analysis() -> LeadIntelligenceAnalysis:
    return LeadIntelligenceAnalysis(
        priority="high", confidence=0.8, reasoning="Active buyer requirement and recent activity.",
        positive_signals=[], risk_signals=[], recommended_next_action="call", insufficient_data=False,
    )


def _valid_follow_up_recommendation() -> FollowUpRecommendation:
    return FollowUpRecommendation(
        should_follow_up=True, priority="high", recommended_channel="whatsapp", recommended_action="follow_up",
        reason="No contact in 6 days despite an active requirement.", suggested_message="Hola, ¿cómo estás?",
        confidence=0.85,
    )


def _valid_pipeline_analysis() -> PipelineAnalysis:
    return PipelineAnalysis(
        overall_priority="medium", summary="One active opportunity, no immediate risks detected.",
        opportunities=[], immediate_actions=[], risk_flags=[], confidence=0.7,
    )


def _make_contact(db_session: Session, organization_id, **overrides) -> Contact:
    fields = {"organization_id": organization_id, "first_name": "Luis", "last_name": "Cantu", "phone": "+52 81 5500 7777"}
    fields.update(overrides)
    contact = Contact(**fields)
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)
    return contact


# --- Registry --------------------------------------------------------------------------------------


def test_registry_contains_all_three_agents():
    assert set(AGENT_REGISTRY) == {"lead_intelligence", "follow_up", "pipeline"}


def test_get_agent_returns_the_right_descriptor():
    descriptor = get_agent("lead_intelligence")
    assert descriptor.agent_id == "lead_intelligence"
    assert descriptor.input_type is LeadContext
    assert descriptor.output_type is LeadIntelligenceResult
    assert descriptor.version and descriptor.prompt_version


def test_get_agent_returns_the_right_descriptor_for_pipeline():
    from app.schemas.pipeline import PipelineResult

    descriptor = get_agent("pipeline")
    assert descriptor.agent_id == "pipeline"
    assert descriptor.input_type is LeadContext
    assert descriptor.output_type is PipelineResult
    assert descriptor.version and descriptor.prompt_version


def test_get_agent_raises_for_an_unknown_id():
    with pytest.raises(KeyError):
        get_agent("sales_copilot")


def test_list_agents_returns_every_registered_agent():
    ids = {descriptor.agent_id for descriptor in list_agents()}
    assert ids == {"lead_intelligence", "follow_up", "pipeline"}


# --- Gateway: happy path, metadata, error propagation -----------------------------------------------


def test_gateway_runs_lead_intelligence_and_returns_metadata(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_lead_intelligence_analysis())

    execution = AIGateway(db_session, fake).run("lead_intelligence", current_user, contact.id)

    assert isinstance(execution, GatewayExecution)
    assert isinstance(execution.result, LeadIntelligenceResult)
    assert execution.result.contact_id == contact.id
    assert isinstance(execution.metadata, ExecutionMetadata)
    assert execution.metadata.agent == "lead_intelligence"
    assert execution.metadata.provider == "fake"
    assert execution.metadata.model == "fake-model-v1"
    assert execution.metadata.success is True
    assert execution.metadata.duration_ms >= 0
    assert execution.metadata.prompt_version  # traceable, non-empty


def test_gateway_runs_follow_up_and_returns_metadata(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_follow_up_recommendation())

    execution = AIGateway(db_session, fake).run("follow_up", current_user, contact.id)

    assert isinstance(execution.result, FollowUpResult)
    assert execution.metadata.agent == "follow_up"
    assert execution.metadata.success is True


def test_gateway_runs_pipeline_and_returns_metadata(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_pipeline_analysis())

    execution = AIGateway(db_session, fake).run("pipeline", current_user, contact.id)

    assert isinstance(execution.result, PipelineResult)
    assert execution.result.contact_id == contact.id
    assert execution.metadata.agent == "pipeline"
    assert execution.metadata.success is True


def test_gateway_metadata_reflects_the_providers_own_identity(db_session: Session, organization_id, current_user):
    """The gateway never decides the provider/model itself — it only reports whatever the injected LLMProvider identifies as."""
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_lead_intelligence_analysis())

    execution = AIGateway(db_session, fake).run("lead_intelligence", current_user, contact.id)

    assert execution.metadata.provider == fake.provider_name
    assert execution.metadata.model == fake.model_name


def test_gateway_propagates_llm_errors_without_swallowing_them(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMTimeoutError("slow"))

    with pytest.raises(LLMTimeoutError):
        AIGateway(db_session, fake).run("lead_intelligence", current_user, contact.id)


def test_gateway_logs_a_warning_on_llm_failure(db_session: Session, organization_id, current_user, caplog):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(error=LLMInvalidOutputError("bad shape"))

    with caplog.at_level(logging.WARNING, logger="app.ai.gateway"):
        with pytest.raises(LLMInvalidOutputError):
            AIGateway(db_session, fake).run("follow_up", current_user, contact.id)

    assert any("ai_gateway.failed" in record.message for record in caplog.records)


def test_gateway_does_not_log_execution_metadata_for_an_unauthorized_contact(db_session: Session, current_user, caplog):
    """A 404 from context authorization is not an AI execution outcome — the gateway must not log it as one."""
    fake = FakeLLMProvider(response=_valid_lead_intelligence_analysis())

    with caplog.at_level(logging.INFO, logger="app.ai.gateway"):
        with pytest.raises(HTTPException) as exc_info:
            AIGateway(db_session, fake).run("lead_intelligence", current_user, uuid.uuid4())

    assert exc_info.value.status_code == 404
    assert fake.calls == []
    assert not any("ai_gateway" in record.message for record in caplog.records)


def test_gateway_raises_for_an_unregistered_agent(db_session: Session, organization_id, current_user):
    contact = _make_contact(db_session, organization_id)
    fake = FakeLLMProvider(response=_valid_lead_intelligence_analysis())

    with pytest.raises(KeyError):
        AIGateway(db_session, fake).run("sales_copilot", current_user, contact.id)
    assert fake.calls == []
