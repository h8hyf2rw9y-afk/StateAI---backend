from app.ai.llm.base import LLMProvider
from app.schemas.renova_quick_notes import RenovaQuickNotesExtraction
from app.services.renova_extraction import redact_protected_numbers

SYSTEM_PROMPT = """
You extract structured fields from informal Spanish call notes for a Mexican real-estate acquisition form.
Return only the requested structured object. Never invent a value; use null when uncertain.

Field meanings:
- owner_name: the client's/person's name, even when it appears alone at the beginning.
- street_address: street and exterior/interior number.
- neighborhood: colonia, fraccionamiento or privada.
- municipality: municipio or city/municipality name.
- postal_code: five-digit Mexican postal code.
- dwelling_type: house for casa/vivienda, apartment for departamento/depa.
- is_duplex, floors, bathrooms, bedrooms: property configuration.
- debt and amount fields: digits only as decimal strings, without currency symbols or separators.
- property_tax_debt_unit: years only when the note states years; otherwise mxn.
- sale_reason: why the owner wants or needs to sell.
- proposal_type / debt_coverage_amount / owner_cash_offer: Renova's proposal has three distinct shapes.
  * "debt_only": Renova only settles the owner's debt; no cash goes to the owner. Set debt_coverage_amount
    to that debt figure and leave owner_cash_offer null. A note saying ONLY debt is covered ("solo cubrimos
    la deuda/el crédito", "no se le entrega efectivo") is debt_only — NEVER invent a zero or any peso total
    for it; it is a complete proposal exactly as described, not a missing one.
  * "debt_plus_cash": Renova settles debt AND pays the owner cash directly ("le cubrimos X de deuda y le
    damos/ofrecemos Y", "Y libres además de cubrir la deuda"). Set both amounts.
  * "cash_only": Renova pays the owner cash with no debt settlement mentioned. Set owner_cash_offer only.
  * If the note does not describe a proposal at all, leave proposal_type null — do not guess a type just
    because some unrelated debt or money figure is mentioned elsewhere in the note.

Protected placeholders such as [NSS_PROTEGIDO], [CREDITO_PROTEGIDO], [TELEFONO_PROTEGIDO]
and [NUMERO_PROTEGIDO] identify omitted private values. Never copy a placeholder into an output field.

Use Mexican location context when it is explicit enough. For example:
Input: "Pedro, dirección Cardo 2010, [NSS_PROTEGIDO], Salinas Victoria, Privadas Reales, [TELEFONO_PROTEGIDO]"
Output meaning: owner_name Pedro; street_address Cardo 2010; municipality Salinas Victoria; neighborhood Privadas Reales.

Input: "Ana López. Casa dúplex de 2 plantas, 3 recámaras y 1.5 baños en calle Río Pánuco 120, colonia Del Valle, municipio San Pedro."
Output meaning: owner_name Ana López; dwelling_type house; is_duplex true; floors 2; bedrooms 3; bathrooms 1.5; street_address Río Pánuco 120; neighborhood Del Valle; municipality San Pedro.

Input: "Le cubrimos 320 mil de deuda y le damos 140 mil."
Output meaning: proposal_type debt_plus_cash; debt_coverage_amount 320000; owner_cash_offer 140000.

Input: "La propuesta es únicamente liquidar los 320 mil de deuda. No se le entrega efectivo, solo se cubre el crédito."
Output meaning: proposal_type debt_only; debt_coverage_amount 320000; owner_cash_offer null.
""".strip()


def sanitize_redacted_note(content: str) -> str:
    """Guarantee that long numeric identifiers cannot reach the provider. See app/services/renova_extraction.py."""
    return redact_protected_numbers(content, "[NUMERO_PROTEGIDO]")


class RenovaQuickNotesService:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def extract(self, content: str) -> RenovaQuickNotesExtraction:
        return self.llm.generate_structured(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=sanitize_redacted_note(content),
            response_model=RenovaQuickNotesExtraction,
            max_tokens=700,
        )
