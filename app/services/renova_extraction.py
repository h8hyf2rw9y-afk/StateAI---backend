"""
Shared Renova natural-language extraction primitives.

Used today by Quick Notes (app/services/renova_quick_notes_service.py) and
by the Renova Chat interpreter (app/renova_chat/interpreter.py), so the two
systems don't grow two independently-drifting answers to "how do we keep a
protected number out of an LLM prompt." A future Renova Chat CREATE flow
(see the Chat V2 architecture audit) is expected to need the same
redaction and the same allow-list, which is why both live here instead of
inside either caller.

This module is NOT a general-purpose extraction engine. It holds exactly
two things, both safety-critical and both small enough to read in one
sitting: the redaction pattern, and the explicit list of which RenovaCase
fields may ever be handed to a general-purpose LLM in free text form.
"""

import re

# Matches a run of 6-20 digits, optionally separated by whitespace, hyphens
# or parentheses -- covers an NSS, a credit/account number, and a phone
# number in any grouping a person might type them in. Shared by Quick
# Notes' redaction and the chat interpreter's redaction so a looser rule
# adopted in one can never silently become a stricter (weaker) rule in the
# other. Each caller still chooses its OWN placeholder text below, since
# that's already part of each system's tested, user-visible behavior.
PROTECTED_NUMBER_RE = re.compile(r"(?<!\d)(?:\d[\s()-]?){6,20}(?!\d)")


def redact_protected_numbers(text: str, placeholder: str) -> str:
    """Replace every matched digit run with `placeholder`. Never logs or returns what was redacted."""
    return PROTECTED_NUMBER_RE.sub(placeholder, text)


# Every RenovaCase field a general-purpose LLM may ever be asked to EXTRACT
# from free text (Quick Notes today; a future Chat CREATE flow tomorrow).
# This is exactly RenovaQuickNotesExtraction's own field set, named here so
# a reviewer sees the boundary in one place instead of having to infer it
# from which fields a Pydantic schema happens to omit. See
# tests/test_renova_extraction.py, which fails if that schema ever drifts
# from this list in either direction.
LLM_EXTRACTABLE_RENOVA_FIELDS: frozenset[str] = frozenset({
    "owner_name",
    "street_address",
    "neighborhood",
    "municipality",
    "postal_code",
    "dwelling_type",
    "is_duplex",
    "floors",
    "bathrooms",
    "bedrooms",
    "property_tax_debt",
    "property_tax_debt_unit",
    "other_debt",
    "water_debt",
    "electricity_debt",
    "gas_debt",
    "owner_expected_amount",
    "market_value",
    "proposal_type",
    "debt_coverage_amount",
    "owner_cash_offer",
    "sale_reason",
})

# The converse: fields that must NEVER be extracted from free text by a
# general LLM, and must never appear inside an LLM prompt or an
# LLM-produced schema, no matter how the extraction layer evolves. NSS and
# credit_number are the encrypted identifiers (see RenovaCase's own
# docstring); owner_phone and spouse_phone are deliberately handled by
# fully local, non-LLM regex extraction today (see
# features/renova/lib/quick-notes.ts's extractQuickNotes) rather than ever
# being offered to a model; the two INE sides are images, never text, and
# are out of scope for any text-extraction layer entirely.
RENOVA_FIELDS_NEVER_SENT_TO_LLM: frozenset[str] = frozenset({
    "nss",
    "credit_number",
    "owner_phone",
    "spouse_phone",
    "ine_front",
    "ine_back",
})
