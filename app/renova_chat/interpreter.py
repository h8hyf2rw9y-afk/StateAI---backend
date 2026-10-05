import re
import unicodedata

from app.ai.llm.base import LLMProvider
from app.schemas.renova_chat import ParsedRenovaQuestion
from app.services.renova_extraction import redact_protected_numbers

SYSTEM_PROMPT = """
You classify short Spanish or English questions for a read-only real-estate CRM assistant.
Return only the requested structured object. You never receive database records and you never answer the question.

Choose exactly one intent:
- active_count: how many Renova prospects are active.
- active_list: list/show active Renova prospects.
- archived_count: how many Renova cases are explicitly marked as archived.
- archived_list: list/show Renova cases explicitly marked as archived.
- pipeline_summary: counts or overview of Renova pipeline stages.
- case_summary: general information about one named owner/case ("resume a X", "qué sabemos de X").
- total_debt: total known debt for one named owner/case.
- debt_breakdown: debt amounts by category for one named owner/case.
- phone: phone/cell number for one named owner. A generic "número de Juan" means phone.
- address: address/location for one named owner.
- status: current Renova pipeline status for one named owner.
- entry_date: intake/registration date for one named owner.
- market_value: market value for one named owner.
- final_offer: THE PROPOSAL for one named owner — what Renova is offering overall, in any shape
  ("cuál es la propuesta", "qué le ofrecemos", "cuánto espera recibir y cuánto le estamos ofreciendo" --
  compound questions mixing expectation and offer also go here, not to case_field).
- expected_amount: amount the owner expects to receive (DIFFERENT from final_offer: this is what the
  owner wants, not what Renova proposes).
- case_field: any OTHER single fact about one named owner/case. Set `field` to exactly one of:
  dwelling_type, is_duplex, occupancy_status, floors, bathrooms, bedrooms, conditions, has_deeds,
  deeds_holder_name, sale_reason, general_situation, notes, marital_status, spouse_name, source,
  property_tax_debt, water_debt, electricity_debt, gas_debt, other_debt,
  proposal_type, debt_coverage_amount, owner_cash_offer, total_proposal_value.
  Examples: "¿cuántas recámaras tiene?" -> field bedrooms. "¿es dúplex?" -> field is_duplex.
  "¿por qué quiere vender?" -> field sale_reason. "¿qué notas tengo?" -> field notes.
  "¿tiene escrituras?" -> field has_deeds. "¿a nombre de quién están las escrituras?" -> field deeds_holder_name.
  "¿está casado?" -> field marital_status. "¿cómo se llama su esposa?" -> field spouse_name.
  "¿de dónde llegó?" -> field source. "¿cuánto debe de agua/luz/gas/predial?" -> field water_debt/electricity_debt/gas_debt/property_tax_debt.
  "¿cuánto le damos directamente/en efectivo?" -> field owner_cash_offer.
  "¿cuánto de su deuda vamos a cubrir?" -> field debt_coverage_amount.
  "¿cuál es el valor total de la propuesta?" -> field total_proposal_value.
  "¿la propuesta es únicamente cubrir la deuda?" -> field proposal_type.
- filtered_count: how many cases match ONE condition (not "active"/"archived", which have their own intents above).
- filtered_list: which cases match ONE condition.
  For filtered_count/filtered_list set `filter` to exactly one {field, operator, value}:
    field "status", operator "equals", value one of: draft, new, reviewing, offer_preparation, offer_sent,
      negotiating, accepted, purchased, rejected, cancelled (map Spanish names: nuevo=new, en revisión=reviewing,
      preparación de oferta=offer_preparation, oferta enviada=offer_sent, negociando=negotiating,
      aceptado=accepted, comprado=purchased, rechazado=rejected, cancelado=cancelled).
    field "municipality", operator "equals", value the place name as written (e.g. "Santa Catarina", "Apodaca").
    field "is_duplex", operator "is_true" or "is_false" (no value needed).
    field "has_deeds", operator "equals", value one of: yes, no, unknown (sí tienen escrituras=yes, no tienen=no).
    field "has_property_tax_debt" / "has_water_debt" / "has_electricity_debt" / "has_gas_debt" / "has_other_debt",
      operator "exists" (no value needed) -- for "quién debe predial/agua/luz/gas/otro adeudo".
    field "proposal_type", operator "equals", value one of: debt_only, debt_plus_cash, cash_only, or the
      sentinel "unclassified" for a proposal that still needs classifying ("propuestas incompletas"/"sin clasificar").
      "propuesta de solo deuda" = debt_only. "reciben dinero además de que cubrimos su deuda" = debt_plus_cash.
  Examples: "¿qué leads están negociando?" -> filtered_list, filter {field status, operator equals, value negotiating}.
  "¿cuántos están negociando?" -> filtered_count, same filter. "¿quién debe predial?" -> filtered_list,
  filter {field has_property_tax_debt, operator exists}. "¿qué clientes tienen propuesta de solo deuda?" ->
  filtered_list, filter {field proposal_type, operator equals, value debt_only}. "¿qué propuestas están
  incompletas?" -> filtered_list, filter {field proposal_type, operator equals, value unclassified}.
- protected_data: NSS, credit/account number, or INE request.
- help: asks what the assistant can do.
- unsupported: anything else, including writes, edits, deletion, reports, traditional CRM, or legal/financial advice.

Set owner_name only when the user names a person, and only for intents about ONE case (not filtered_count/filtered_list/active_*/archived_*/pipeline_summary, which are never about one named owner).
Preserve the written name, but remove filler words.
If the question uses "él", "ella", "esa persona", "su" or omits a name, leave owner_name null; the backend may use its safe current-case context.
Never treat an NSS, credit number, account number or INE as a phone request, and never set `field` to anything about NSS, credit number or INE -- use protected_data instead.
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
    """Keep pasted NSS/credit/phone-like digit strings out of the LLM and chat history. See app/services/renova_extraction.py."""
    return redact_protected_numbers(question, "[dato protegido]")


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
        # Bumped from 160: the output schema grew a nested `filter` object
        # and a `field` string; still small relative to any real case data.
        max_tokens=220,
    )
