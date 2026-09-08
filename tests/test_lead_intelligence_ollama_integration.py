"""
The real-local-Ollama smoke test (Step 11 of the Ollama migration): runs
the actual Lead Intelligence Agent, through a real OllamaProvider, against
four demo contacts with different scenarios (Carlos, Gabriela, Carolina,
Sergio). Skipped automatically unless a live Ollama server answers at
settings.ollama_base_url — the normal test suite and CI never depend on
Ollama being installed or running.

Run explicitly once Ollama is up and the configured model is pulled:

    ollama pull llama3.1   # or whatever OLLAMA_MODEL is set to
    ollama serve           # if not already running as a service
    uv run pytest tests/test_lead_intelligence_ollama_integration.py -v -s
"""

import uuid

import httpx
import pytest

from app.ai.lead_intelligence_agent import LeadIntelligenceAgent
from app.ai.llm.ollama_provider import OllamaProvider
from app.core.config import settings
from app.models.contact import Contact
from app.schemas.user import CurrentUser
from scripts.seed_demo_data import det_id, run_seed


def _ollama_is_reachable() -> bool:
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=1.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_is_reachable(),
    reason=f"No Ollama server reachable at {settings.ollama_base_url} — skipping real-local-LLM test",
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

    provider = OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout=120.0)
    result = LeadIntelligenceAgent(db_session, provider).analyze(user, contact.id)

    assert result.contact_id == contact.id
    assert result.analysis.priority in ("high", "medium", "low")
    assert result.analysis.recommended_next_action
    print(f"\n--- {contact_key} (via Ollama, model={provider.model_name}) ---")
    print(result.model_dump_json(indent=2))
