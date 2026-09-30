import re
import unicodedata

from app.ai.llm.base import LLMProvider
from app.schemas.renova_chat import ParsedRenovaQuestion

_PROTECTED_NUMBER_RE = re.compile(r"(?<!\d)(?:\d[\s-]?){6,20}(?!\d)")

SYSTEM_PROMPT = """
You classify short Spanish or English questions for a read-only real-estate CRM assistant.
Return only the requested structured object. You never receive database records and you never answer the question.

Choose exactly one intent:
- active_count: how many Renova prospects are active.
- active_list: list/show active Renova prospects.
- archived_count: how many Renova cases are explicitly marked as archived.
- archived_list: list/show Renova cases explicitly marked as archived.
- pipeline_summary: counts or overview of Renova pipeline stages.
- case_summary: general information about one named owner/case.
- total_debt: total known debt for one named owner/case.
- debt_breakdown: debt amounts by category for one named owner/case.
- phone: phone/cell number for one named owner. A generic "número de Juan" means phone.
- address: address/location for one named owner.
- status: current Renova pipeline status for one named owner.
- entry_date: intake/registration date for one named owner.
- market_value: market value for one named owner.
- final_offer: final offer for one named owner.
- expected_amount: amount the owner expects to receive.
- protected_data: NSS, credit/account number, or INE request.
- help: asks what the assistant can do.
- unsupported: anything else, including writes, edits, deletion, reports, traditional CRM, or legal/financial advice.

Set owner_name only when the user names a person. Preserve the written name, but remove filler words.
If the question uses "él", "ella", "esa persona", "su" or omits a name, leave owner_name null; the backend may use its safe current-case context.
Never treat an NSS, credit number, account number or INE as a phone request.
Archived means the explicit archived marker; do not infer it from rejected or cancelled status.
""".strip()


def _normalized_words(question: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", question.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return set(re.findall(r"[a-z]+", ascii_text))


def _deterministic_archived_intent(
    question: str, previous_intent: str | None
) -> ParsedRenovaQuestion | None:
    """Resolve unambiguous archive queries without relying on the classifier."""
    words = _normalized_words(question)
    mentions_archived = any(word.startswith("archivad") for word in words) or "archived" in words
    list_words = {
        "cuales",
        "quienes",
        "lista",
        "listar",
        "muestra",
        "muestrame",
        "ensena",
        "ensename",
        "nombres",
        "list",
        "show",
        "which",
    }

    if mentions_archived:
        intent = "archived_list" if words & list_words else "archived_count"
        return ParsedRenovaQuestion(intent=intent)

    follow_up = words <= {"cuales", "quienes", "son", "muestra", "muestrame", "los", "las"}
    if previous_intent in {"archived_count", "archived_list"} and follow_up and words & list_words:
        return ParsedRenovaQuestion(intent="archived_list")
    return None


def sanitize_question(question: str) -> str:
    """Keep pasted NSS/credit/phone-like digit strings out of the LLM and chat history."""
    return _PROTECTED_NUMBER_RE.sub("[dato protegido]", question)


def interpret_question(
    llm: LLMProvider, question: str, *, previous_intent: str | None = None
) -> ParsedRenovaQuestion:
    deterministic = _deterministic_archived_intent(question, previous_intent)
    if deterministic is not None:
        return deterministic
    return llm.generate_structured(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=question,
        response_model=ParsedRenovaQuestion,
        max_tokens=160,
    )
