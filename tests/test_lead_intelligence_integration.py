"""
The one test in this suite that makes a real Anthropic API call. Skipped
entirely unless an ANTHROPIC_API_KEY resolves through settings (process
environment or the local .env file — same source app.core.config.settings
itself reads) — CI and the normal `uv run pytest` run never depend on it or
on network access. Run explicitly with a real key to validate the agent
end-to-end against a real model response:

    ANTHROPIC_API_KEY=sk-ant-... uv run pytest tests/test_lead_intelligence_integration.py -v -s
"""

import pytest

from app.ai.lead_intelligence_agent import LeadIntelligenceAgent
from app.ai.llm.factory import build_default_provider
from app.core.config import settings
from app.models.contact import Contact
from app.schemas.lead_intelligence import LeadIntelligenceAnalysis

pytestmark = pytest.mark.skipif(
    not settings.anthropic_api_key, reason="ANTHROPIC_API_KEY not configured — skipping real-LLM integration test"
)


def test_agent_produces_a_real_valid_analysis(db_session, organization_id, current_user):
    contact = Contact(
        organization_id=organization_id, first_name="Integration", last_name="Test", phone="+52 81 5500 0000"
    )
    db_session.add(contact)
    db_session.commit()
    db_session.refresh(contact)

    provider = build_default_provider()
    result = LeadIntelligenceAgent(db_session, provider).analyze(current_user, contact.id)

    assert isinstance(result.analysis, LeadIntelligenceAnalysis)
    assert result.analysis.priority in ("high", "medium", "low")
    print("\n--- real LLM analysis ---")
    print(result.model_dump_json(indent=2))
