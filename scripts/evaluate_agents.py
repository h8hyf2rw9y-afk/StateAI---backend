"""
A lightweight evaluation runner for the AI agents (Lead Intelligence,
Follow-up) against the demo contacts (Carlos, Gabriela, Carolina, Sergio).
Deliberately NOT a pytest test and NOT run automatically by `uv run
pytest` — it makes real LLM calls through whatever provider/model
LLM_PROVIDER/OLLAMA_MODEL/ANTHROPIC_MODEL currently resolve to (see
app/ai/llm/factory.py), which on CPU-only hardware can take minutes.

This script records facts about each run — provider, model, agent,
prompt/agent version, duration, schema validity, and the raw structured
output — and prints them. It never judges whether an answer is "good":
that's a human/product decision, and any deterministic fact-checking
belongs in tests/test_golden_contacts.py instead (CRM facts, not AI
opinions). Comparing prompts/models/providers over time means re-running
this after changing the relevant environment variable(s) and diffing the
output, not asking this script to declare a winner.

Usage:
    uv run python scripts/evaluate_agents.py
    uv run python scripts/evaluate_agents.py --agents lead_intelligence
    uv run python scripts/evaluate_agents.py --contacts carlos-mendoza,gabriela-ortiz
    uv run python scripts/evaluate_agents.py --output eval_results.json

Requires whichever provider is configured to actually be reachable (e.g.
a local Ollama server running with OLLAMA_MODEL pulled, or a valid
ANTHROPIC_API_KEY if LLM_PROVIDER=anthropic) — this script does not mock
anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# Run directly (`python scripts/evaluate_agents.py`), Python puts only this
# file's own directory on sys.path — add the repo root so `app`/`scripts`
# resolve the same as `-m scripts.evaluate_agents` would.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.gateway import AIGateway  # noqa: E402
from app.ai.llm.errors import LLMError  # noqa: E402
from app.ai.llm.factory import build_default_provider  # noqa: E402
from app.ai.registry import list_agents  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.schemas.user import CurrentUser  # noqa: E402
from scripts.seed_demo_data import det_id, run_seed  # noqa: E402

DEFAULT_CONTACT_KEYS = ["carlos-mendoza", "gabriela-ortiz", "carolina-reyes", "sergio-navarro"]


def _evaluate_one(session, provider, agent_id: str, contact_key: str, organization_id) -> dict[str, Any]:
    contact = session.get(Contact, det_id(f"contact:{contact_key}"))
    if contact is None:
        return {"agent": agent_id, "contact": contact_key, "schema_valid": False, "error": "contact not found in demo data"}

    # A CurrentUser scoped to the demo org — AIGateway/get_lead_context only
    # check this object's organization_id against the contact's, so no real
    # `users` row is needed for this direct, script-level call.
    user = CurrentUser(id=uuid.uuid4(), email="eval@proppilot.app", organization_id=organization_id, role="owner", provider="email")

    started = time.monotonic()
    try:
        execution = AIGateway(session, provider).run(agent_id, user, contact.id)
    except LLMError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "agent": agent_id, "contact": contact_key, "provider": provider.provider_name, "model": provider.model_name,
            "duration_ms": duration_ms, "schema_valid": False, "error": str(exc),
        }

    return {
        "agent": agent_id,
        "contact": contact_key,
        "provider": execution.metadata.provider,
        "model": execution.metadata.model,
        "agent_version": execution.metadata.agent_version,
        "prompt_version": execution.metadata.prompt_version,
        "duration_ms": execution.metadata.duration_ms,
        "schema_valid": True,
        "output": json.loads(execution.result.model_dump_json()),
    }


def _print_row(row: dict[str, Any]) -> None:
    status = "OK" if row["schema_valid"] else "FAILED"
    duration = row.get("duration_ms", "-")
    print(f"\n[{status}] agent={row['agent']} contact={row['contact']} provider={row.get('provider', '-')} "
          f"model={row.get('model', '-')} duration_ms={duration}")
    if row["schema_valid"]:
        print(json.dumps(row["output"], indent=2, ensure_ascii=False))
    else:
        print(f"  error: {row.get('error')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agents", default=",".join(a.agent_id for a in list_agents()),
        help="Comma-separated agent_ids to evaluate (default: all registered agents).",
    )
    parser.add_argument(
        "--contacts", default=",".join(DEFAULT_CONTACT_KEYS),
        help="Comma-separated demo contact keys to evaluate against (default: the four standard demo contacts).",
    )
    parser.add_argument("--output", default=None, help="Optional path to also write the full results as JSON.")
    args = parser.parse_args()

    agent_ids = [a.strip() for a in args.agents.split(",") if a.strip()]
    contact_keys = [c.strip() for c in args.contacts.split(",") if c.strip()]

    provider = build_default_provider()
    print(f"Evaluating agents={agent_ids} contacts={contact_keys} via provider={provider.provider_name} model={provider.model_name}")

    session = SessionLocal()
    try:
        org = run_seed(session)  # idempotent — guarantees the demo contacts exist without touching anything else
        results = [
            _evaluate_one(session, provider, agent_id, contact_key, org.id)
            for agent_id in agent_ids
            for contact_key in contact_keys
        ]
    finally:
        session.close()

    for row in results:
        _print_row(row)

    succeeded = sum(1 for r in results if r["schema_valid"])
    print(f"\n{succeeded}/{len(results)} runs produced schema-valid output.")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Full results written to {args.output}")


if __name__ == "__main__":
    main()
