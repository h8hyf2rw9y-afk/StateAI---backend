from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.core.config import settings
from app.models.renova_case import RenovaCase
from app.models.renova_chat import RenovaChatConversation, RenovaChatMessage
from app.renova_chat.interpreter import interpret_question, sanitize_question
from app.repositories.renova_chat_repo import RenovaChatRepository
from app.schemas.renova_case import DEBT_FIELDS, sum_debts
from app.schemas.renova_chat import ParsedRenovaQuestion, RenovaChatQuestion
from app.schemas.user import CurrentUser

ACTIVE_STATUSES = (
    "new",
    "reviewing",
    "offer_preparation",
    "offer_sent",
    "negotiating",
    "accepted",
)

STATUS_LABELS = {
    "draft": "Borrador",
    "new": "Nuevo",
    "reviewing": "En revisión",
    "offer_preparation": "Preparación de oferta",
    "offer_sent": "Oferta enviada",
    "negotiating": "Negociando",
    "accepted": "Aceptado",
    "purchased": "Comprado",
    "rejected": "Rechazado",
    "cancelled": "Cancelado",
}


def _money(value: Decimal | None, currency: str = "MXN") -> str:
    if value is None:
        return "No está registrado"
    symbol = "$" if currency == "MXN" else f"{currency} "
    return f"{symbol}{value:,.2f}"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RenovaChatService:
    """
    Read-only Q&A over allow-listed Renova fields.

    The LLM only classifies the user's text. It never receives case rows,
    query results, message history, NSS, credit numbers or INE images. Every
    answer is formatted deterministically from an organization-scoped query.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RenovaChatRepository(db)

    def list_conversations(self, current_user: CurrentUser) -> list[RenovaChatConversation]:
        return self.repo.list_conversations(current_user.organization_id, current_user.id)

    def create_conversation(self, current_user: CurrentUser, title: str | None = None) -> RenovaChatConversation:
        conversation = self.repo.create_conversation(
            current_user.organization_id, current_user.id, title or "Nueva conversación"
        )
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def get_messages(self, current_user: CurrentUser, conversation_id: uuid.UUID) -> list[RenovaChatMessage]:
        conversation = self._conversation(current_user, conversation_id)
        return self.repo.list_messages(conversation.id)

    def ask(
        self,
        current_user: CurrentUser,
        conversation_id: uuid.UUID,
        question: RenovaChatQuestion,
        llm: LLMProvider,
    ) -> tuple[RenovaChatConversation, RenovaChatMessage, RenovaChatMessage]:
        conversation = self._conversation(current_user, conversation_id)
        if self.repo.count_recent_user_messages(current_user.organization_id, current_user.id) >= settings.ai_user_rate_limit_per_minute:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                {
                    "code": "RATE_LIMITED",
                    "message": "Has enviado varias consultas en poco tiempo. Espera un minuto e inténtalo de nuevo.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )
        safe_question = sanitize_question(question.content)
        parsed = interpret_question(llm, safe_question)
        matched_case = self._resolve_case(current_user.organization_id, parsed, conversation)
        answer = self._answer(current_user.organization_id, parsed, matched_case)

        if matched_case is not None:
            conversation.context_case_id = matched_case.id
        if conversation.title == "Nueva conversación":
            conversation.title = self._title(safe_question)

        user_message = self.repo.add_message(conversation.id, role="user", content=safe_question)
        assistant_message = self.repo.add_message(
            conversation.id,
            role="assistant",
            content=answer,
            intent=parsed.intent,
            referenced_case_id=matched_case.id if matched_case else None,
        )
        self.repo.touch(conversation)
        self.db.commit()
        for obj in (conversation, user_message, assistant_message):
            self.db.refresh(obj)
        return conversation, user_message, assistant_message

    def _conversation(self, current_user: CurrentUser, conversation_id: uuid.UUID) -> RenovaChatConversation:
        conversation = self.repo.get_conversation(
            current_user.organization_id, current_user.id, conversation_id
        )
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
        return conversation

    @staticmethod
    def _title(text: str) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= 60 else f"{compact[:57].rstrip()}…"

    def _resolve_case(
        self,
        organization_id: uuid.UUID,
        parsed: ParsedRenovaQuestion,
        conversation: RenovaChatConversation,
    ) -> RenovaCase | None:
        case_intents = {
            "case_summary", "total_debt", "debt_breakdown", "phone", "address", "status",
            "entry_date", "market_value", "final_offer", "expected_amount",
        }
        if parsed.intent not in case_intents:
            return None

        name = (parsed.owner_name or "").strip()
        if not name:
            if conversation.context_case_id is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Indica el nombre del propietario para hacer esa consulta.",
                )
            return self.db.execute(
                select(RenovaCase).where(
                    RenovaCase.id == conversation.context_case_id,
                    RenovaCase.organization_id == organization_id,
                )
            ).scalar_one_or_none()

        pattern = f"%{_escape_like(name)}%"
        matches = list(
            self.db.execute(
                select(RenovaCase)
                .where(
                    RenovaCase.organization_id == organization_id,
                    RenovaCase.owner_name.ilike(pattern, escape="\\"),
                )
                .order_by(RenovaCase.entry_date.desc())
                .limit(6)
            ).scalars().all()
        )
        exact = [case for case in matches if case.owner_name.casefold() == name.casefold()]
        if len(exact) == 1:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No encontré un expediente de Renova para {name}.")
        names = ", ".join(case.owner_name for case in matches[:5])
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Encontré varios propietarios que coinciden: {names}. Escribe el nombre completo.",
        )

    def _answer(self, organization_id: uuid.UUID, parsed: ParsedRenovaQuestion, case: RenovaCase | None) -> str:
        if parsed.intent == "help":
            return (
                "Puedo consultar los leads activos de Renova, resumir el pipeline y buscar por propietario: "
                "teléfono, dirección, etapa, fecha de ingreso, deuda registrada, valor de mercado, oferta final "
                "y monto esperado. En esta versión no modifico expedientes."
            )
        if parsed.intent == "protected_data":
            return (
                "Por seguridad no consulto NSS, número de crédito ni imágenes del INE desde el chat. "
                "Abre el expediente autorizado del cliente para revelar esos datos."
            )
        if parsed.intent == "unsupported":
            return (
                "Esa consulta todavía no está disponible. Por ahora solo puedo leer información básica de "
                "expedientes y del pipeline de Renova; no creo, edito ni elimino datos."
            )
        if parsed.intent == "active_count":
            count = self.db.scalar(
                select(func.count()).select_from(RenovaCase).where(
                    RenovaCase.organization_id == organization_id,
                    RenovaCase.status.in_(ACTIVE_STATUSES),
                )
            ) or 0
            return f"Tienes {count} lead{'s' if count != 1 else ''} activo{'s' if count != 1 else ''} en Renova."
        if parsed.intent == "active_list":
            total = self.db.scalar(
                select(func.count()).select_from(RenovaCase).where(
                    RenovaCase.organization_id == organization_id,
                    RenovaCase.status.in_(ACTIVE_STATUSES),
                )
            ) or 0
            cases = list(self.db.execute(
                select(RenovaCase).where(
                    RenovaCase.organization_id == organization_id,
                    RenovaCase.status.in_(ACTIVE_STATUSES),
                ).order_by(RenovaCase.entry_date.desc()).limit(20)
            ).scalars().all())
            if not cases:
                return "No tienes leads activos en Renova."
            items = "; ".join(f"{c.owner_name} — {STATUS_LABELS.get(c.status, c.status)}" for c in cases)
            suffix = " Mostré los 20 más recientes." if total > 20 else ""
            return f"Leads activos ({total}): {items}.{suffix}"
        if parsed.intent == "pipeline_summary":
            statuses = list(self.db.execute(
                select(RenovaCase.status).where(RenovaCase.organization_id == organization_id)
            ).scalars().all())
            if not statuses:
                return "Todavía no hay expedientes en el pipeline de Renova."
            counts = Counter(statuses)
            ordered = [key for key in STATUS_LABELS if counts[key]]
            summary = "; ".join(f"{STATUS_LABELS[key]}: {counts[key]}" for key in ordered)
            return f"Tu pipeline de Renova tiene {len(statuses)} expedientes. {summary}."

        assert case is not None
        name = case.owner_name
        if parsed.intent == "phone":
            return f"El teléfono de {name} es {case.owner_phone}."
        if parsed.intent == "address":
            parts = [case.street_address, case.neighborhood, case.municipality, case.postal_code]
            address = ", ".join(part for part in parts if part)
            return f"La dirección registrada de {name} es {address}." if address else f"{name} no tiene una dirección registrada."
        if parsed.intent == "status":
            return f"{name} está en la etapa “{STATUS_LABELS.get(case.status, case.status)}” de Renova."
        if parsed.intent == "entry_date":
            return f"{name} ingresó a Renova el {case.entry_date.strftime('%d/%m/%Y')}."
        if parsed.intent == "total_debt":
            total = sum_debts([getattr(case, field) for field in DEBT_FIELDS])
            if total is None:
                return f"{name} no tiene montos de adeudo registrados."
            return f"La deuda total conocida de {name} es {_money(total, case.currency)}."
        if parsed.intent == "debt_breakdown":
            labels = {
                "property_tax_debt": "predial", "other_debt": "otros adeudos", "water_debt": "agua",
                "electricity_debt": "luz", "gas_debt": "gas",
            }
            captured = [f"{labels[field]}: {_money(getattr(case, field), case.currency)}" for field in DEBT_FIELDS if getattr(case, field) is not None]
            if not captured:
                return f"{name} no tiene montos de adeudo registrados."
            total = sum_debts([getattr(case, field) for field in DEBT_FIELDS])
            return f"Adeudos de {name}: {'; '.join(captured)}. Total conocido: {_money(total, case.currency)}."
        if parsed.intent == "market_value":
            return f"El valor de mercado registrado de {name} es {_money(case.market_value, case.currency)}."
        if parsed.intent == "final_offer":
            return f"La propuesta final registrada para {name} es {_money(case.final_offer, case.currency)}."
        if parsed.intent == "expected_amount":
            return f"{name} espera recibir {_money(case.owner_expected_amount, case.currency)}."
        return self._case_summary(case)

    @staticmethod
    def _case_summary(case: RenovaCase) -> str:
        total = sum_debts([getattr(case, field) for field in DEBT_FIELDS])
        address = ", ".join(
            part for part in (case.street_address, case.neighborhood, case.municipality, case.postal_code) if part
        ) or "No registrada"
        return (
            f"{case.owner_name}: etapa {STATUS_LABELS.get(case.status, case.status)}; "
            f"teléfono {case.owner_phone}; dirección {address}; deuda total conocida {_money(total, case.currency)}; "
            f"valor de mercado {_money(case.market_value, case.currency)}; "
            f"propuesta final {_money(case.final_offer, case.currency)}."
        )
