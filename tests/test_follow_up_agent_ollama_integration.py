"""
The real-local-Ollama smoke test for the Follow-up Agent — same gating
pattern as tests/test_lead_intelligence_ollama_integration.py (see that
file's docstring for why the opt-in env var exists, not just an Ollama
reachability check). The normal test suite and CI never depend on this
file at all.

Only the structural contract and reasonable output constraints are
asserted — never a hardcoded expected conclusion. Whether Carlos "should"
get a follow-up is for the model to decide from the real CRM data, not for
this test to assume.

Run explicitly once Ollama is up and the configured model is pulled:

    ollama pull llama3.2   # or whatever OLLAMA_MODEL is set to
    ollama serve           # if not already running as a service
    RUN_OLLAMA_INTEGRATION_TESTS=1 uv run pytest tests/test_follow_up_agent_ollama_integration.py -v -s
"""

import os
import uuid

import httpx
import pytest

from app.ai.follow_up_agent import FollowUpAgent
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
def test_agent_recommends_for_a_real_demo_contact_via_ollama(db_session, demo_org_and_contacts, contact_key):
    org, contacts = demo_org_and_contacts
    contact = contacts[contact_key]
    user = CurrentUser(id=uuid.uuid4(), email="demo@proppilot.app", organization_id=org.id, role="owner", provider="email")

    # 240s: even the smaller default model varies contact-to-contact on
    # CPU-only inference — Carlos's larger context needed noticeably longer
    # than the other three demo contacts during real testing, close enough
    # to a 180s ceiling to occasionally miss it. See the Lead Intelligence
    # real-Ollama test's comment for why CPU-only inference needs room at all.
    provider = OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model, timeout=240.0)
    result = FollowUpAgent(db_session, provider).recommend(user, contact.id)

    rec = result.recommendation
    assert result.contact_id == contact.id
    assert rec.priority in ("high", "medium", "low")
    assert rec.recommended_channel in ("whatsapp", "email", "call", "none")
    assert rec.recommended_action
    assert 0.0 <= rec.confidence <= 1.0
    # The one cross-field consistency this test does check: if the model says
    # no follow-up is needed, it should not also be recommending an active
    # channel — this reflects the prompt's own instruction, not a schema-level
    # constraint (see app/schemas/follow_up.py's docstring for why that's a
    # prompt-level rule and not a hard validator).
    if not rec.should_follow_up:
        assert rec.recommended_channel == "none"
    print(f"\n--- {contact_key} (via Ollama, model={provider.model_name}) ---")
    print(result.model_dump_json(indent=2))
