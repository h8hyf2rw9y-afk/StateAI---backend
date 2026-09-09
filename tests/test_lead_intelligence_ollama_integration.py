"""
The real-local-Ollama smoke test (Step 11 of the Ollama migration): runs
the actual Lead Intelligence Agent, through a real OllamaProvider, against
four demo contacts with different scenarios (Carlos, Gabriela, Carolina,
Sergio). This can take many minutes per contact on CPU-only hardware, so it
is gated on an explicit opt-in env var, not just on Ollama being reachable
— on a machine where Ollama happens to already be running for something
else, a plain `uv run pytest` must stay fast and must not silently balloon
into a 20-minute run of real LLM calls. The normal test suite and CI never
depend on this file at all.

Run explicitly once Ollama is up and the configured model is pulled:

    ollama pull llama3.2   # or whatever OLLAMA_MODEL is set to
    ollama serve           # if not already running as a service
    RUN_OLLAMA_INTEGRATION_TESTS=1 uv run pytest tests/test_lead_intelligence_ollama_integration.py -v -s
"""

import os
import uuid

import httpx
import pytest

from app.ai.lead_intelligence_agent import LeadIntelligenceAgent
from app.ai.llm.ollama_provider import OllamaProvider
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

    # A generous ceiling, not the expected time: on CPU-only hardware (no
    # GPU — see `ollama ps`'s PROCESSOR column) schema-constrained JSON
    # generation is slow enough that the default OllamaProvider timeout
    # (60s) isn't safe here, even with the smaller default model.
    provider = OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout=180.0)
    result = LeadIntelligenceAgent(db_session, provider).analyze(user, contact.id)

    assert result.contact_id == contact.id
    assert result.analysis.priority in ("high", "medium", "low")
    assert result.analysis.recommended_next_action
    print(f"\n--- {contact_key} (via Ollama, model={provider.model_name}) ---")
    print(result.model_dump_json(indent=2))
