"""
The real-local-Ollama smoke test for the Pipeline Agent — same pattern as
tests/test_lead_intelligence_ollama_integration.py: runs the actual
PipelineAgent, through a real OllamaProvider, against the same four demo
contacts (Carlos, Gabriela, Carolina, Sergio). Can take minutes per contact
on CPU-only hardware, so it is gated on an explicit opt-in env var — a
plain `uv run pytest` must stay fast and must never silently balloon into
real LLM calls. The normal test suite and CI never depend on this file at all.

Run explicitly once Ollama is up and the configured model is pulled:

    ollama pull llama3.2   # or whatever OLLAMA_MODEL is set to
    ollama serve           # if not already running as a service
    RUN_OLLAMA_INTEGRATION_TESTS=1 uv run pytest tests/test_pipeline_agent_ollama_integration.py -v -s
"""

import os
import time
import uuid

import httpx
import pytest

from app.ai.llm.ollama_provider import OllamaProvider
from app.ai.pipeline_agent import PipelineAgent
from app.core.config import settings
from app.models.contact import Contact
from app.schemas.user import CurrentUser
from scripts.seed_demo_data import det_id, run_seed

_OPT_IN_ENV_VAR = "RUN_OLLAMA_INTEGRATION_TESTS"


def _ollama_is_reachable() -> bool:
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=1.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


if not os.environ.get(_OPT_IN_ENV_VAR):
    pytestmark = pytest.mark.skip(
        reason=f"Set {_OPT_IN_ENV_VAR}=1 to run this real-local-LLM test — it makes real, possibly slow Ollama calls."
    )
else:
    pytestmark = pytest.mark.skipif(
        not _ollama_is_reachable(),
        reason=f"{_OPT_IN_ENV_VAR}=1 but no Ollama server reachable at {settings.ollama_base_url}",
    )


@pytest.fixture()
def demo_org_and_contacts(db_session):
    org = run_seed(db_session)
    contacts = {
        key: db_session.get(Contact, det_id(f"contact:{key}"))
        for key in ["carlos-mendoza", "gabriela-ortiz", "carolina-reyes", "sergio-navarro"]
    }
    assert all(contacts.values()), "one of the expected demo contacts wasn't found — did the demo seed data change?"
    return org, contacts


@pytest.mark.parametrize("contact_key", ["carlos-mendoza", "gabriela-ortiz", "carolina-reyes", "sergio-navarro"])
def test_agent_analyzes_a_real_demo_contact_via_ollama(db_session, demo_org_and_contacts, contact_key):
    org, contacts = demo_org_and_contacts
    contact = contacts[contact_key]
    # A CurrentUser scoped to the demo org — get_lead_context only checks
    # this object's organization_id against the contact's, so no real
    # `users` row is needed for this direct, in-process call.
    user = CurrentUser(id=uuid.uuid4(), email="demo@proppilot.app", organization_id=org.id, role="owner", provider="email")

    # A generous ceiling, not the expected time — same reasoning as the
    # Lead Intelligence integration test: CPU-only hardware, schema-
    # constrained JSON generation, and this agent's output can be larger
    # (several opportunities/actions/risks, not one judgment).
    provider = OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout=240.0)

    started = time.monotonic()
    result = PipelineAgent(db_session, provider).analyze(user, contact.id)
    duration_s = time.monotonic() - started

    assert result.contact_id == contact.id
    assert result.analysis.overall_priority in ("high", "medium", "low")
    assert 0.0 <= result.analysis.confidence <= 1.0
    for item in result.analysis.opportunities:
        assert 0.0 <= item.confidence <= 1.0

    print(f"\n--- {contact_key} (via Ollama, model={provider.model_name}) — {duration_s:.1f}s ---")
    print(f"overall_priority={result.analysis.overall_priority} confidence={result.analysis.confidence}")
    print(f"opportunities analyzed: {len(result.analysis.opportunities)}")
    print(f"immediate_actions: {len(result.analysis.immediate_actions)}")
    print(f"risk_flags: {len(result.analysis.risk_flags)}")
    print(result.model_dump_json(indent=2))
