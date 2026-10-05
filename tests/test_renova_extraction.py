"""
The shared Renova extraction layer (app/services/renova_extraction.py):
the one place that says which RenovaCase fields a general-purpose LLM may
ever be asked to extract from free text, and the one redaction pattern
both Quick Notes and the Renova Chat interpreter rely on to keep a pasted
NSS/credit/phone number out of a prompt. These tests exist so a future
edit that accidentally widens either boundary fails here, not in review.
"""

from app.schemas.renova_quick_notes import RenovaQuickNotesExtraction
from app.services.renova_extraction import (
    LLM_EXTRACTABLE_RENOVA_FIELDS,
    RENOVA_FIELDS_NEVER_SENT_TO_LLM,
    redact_protected_numbers,
)


def test_the_two_allow_lists_never_overlap():
    assert LLM_EXTRACTABLE_RENOVA_FIELDS.isdisjoint(RENOVA_FIELDS_NEVER_SENT_TO_LLM)


def test_quick_notes_schema_matches_the_llm_extractable_allow_list_exactly():
    """If a future edit adds a field to RenovaQuickNotesExtraction without adding it here (or vice versa), this fails."""
    assert set(RenovaQuickNotesExtraction.model_fields) == LLM_EXTRACTABLE_RENOVA_FIELDS


def test_quick_notes_schema_never_contains_a_never_send_field():
    assert set(RenovaQuickNotesExtraction.model_fields).isdisjoint(RENOVA_FIELDS_NEVER_SENT_TO_LLM)


def test_redacts_a_bare_long_digit_run():
    # A single trailing separator is part of the match (it's an optional
    # character after each digit, including the last one) -- pre-existing
    # behavior of both original regexes, unchanged here.
    assert redact_protected_numbers("mi nss es 12345678901 gracias", "[X]") == "mi nss es [X]gracias"


def test_redacts_digits_hyphenated_across_a_run_of_at_least_six():
    assert redact_protected_numbers("tel 234-5678", "[X]") == "tel [X]"


def test_does_not_redact_short_numbers_like_a_bedroom_count():
    assert redact_protected_numbers("tiene 3 recamaras y 2 banos", "[X]") == "tiene 3 recamaras y 2 banos"


def test_each_caller_keeps_its_own_placeholder():
    from app.renova_chat.interpreter import sanitize_question
    from app.services.renova_quick_notes_service import sanitize_redacted_note

    assert sanitize_question("nss 12345678901") == "nss [dato protegido]"
    assert sanitize_redacted_note("nss 12345678901") == "nss [NUMERO_PROTEGIDO]"
