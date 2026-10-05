from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.core.config import settings
from app.models.renova_case import RenovaCase
from app.models.renova_chat import RenovaChatConversation, RenovaChatMessage
from app.renova_chat.fields import (
    DWELLING_LABELS,
    RENOVA_CASE_FIELD_RESOLVERS,
    STATUS_LABELS,
    format_money,
    format_property_tax_debt,
)
from app.renova_chat.filters import build_filter_clause, describe_filter
from app.renova_chat.interpreter import interpret_question, sanitize_question
from app.repositories.renova_chat_repo import RenovaChatRepository
from app.schemas.renova_case import DEBT_FIELDS, sum_debts
from app.schemas.renova_chat import ParsedRenovaQuestion, RenovaChatQuestion, RenovaCaseFilter
from app.schemas.user import CurrentUser

# Intents resolved through RENOVA_CASE_FIELD_RESOLVERS (app/renova_chat/fields.py)
# instead of their own bespoke branch -- the 7 pre-existing ones keep their
# own intent name for backward compatibility, "case_field" is the new,
# single mechanism for everything added in Read V2. Both paths call the
# exact same resolver, so there is only one implementation per field.
_FIXED_FIELD_INTENTS = {
    "phone", "address", "status", "entry_date", "market_value", "final_offer", "expected_amount",
}

ACTIVE_STATUSES = (
    "new",
    "reviewing",
    "offer_preparation",
    "offer_sent",
    "negotiating",
    "accepted",
)

TERMINAL_STATUSES = (
    "purchased",
    "rejected",
    "cancelled",
)

# STATUS_LABELS and money/property-tax formatting now live in
# app/renova_chat/fields.py (imported above) -- the single source both the
# fixed-field intents and the new "case_field" mechanism read from.


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
        parsed = interpret_question(
            llm,
            safe_question,
            previous_intent=self.repo.last_assistant_intent(conversation.id),
        )
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
            "entry_date", "market_value", "final_offer", "expected_amount", "case_field",
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
                "Puedo consultar los leads activos de Renova, resumir el pipeline, contar y listar expedientes "
                "archivados, y buscar por propietario: teléfono, dirección, etapa, fecha de ingreso, tipo de "
                "vivienda, dúplex, situación actual, plantas, baños, recámaras, condiciones, escrituras, motivo "
                "de venta, situación general, notas, estado civil, cónyuge, origen del lead, valor de mercado, "
                "oferta final, monto esperado y adeudos (predial, agua, luz, gas, otros). También puedo contar o "
                "listar leads por estado, municipio, dúplex, escrituras o adeudo registrado. "
                "Por ahora no creo, edito ni elimino expedientes desde el chat."
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
            count = self._count(*self._active_filter(organization_id))
            return f"Tienes {count} lead{'s' if count != 1 else ''} activo{'s' if count != 1 else ''} en Renova."
        if parsed.intent == "active_list":
            return self._list_cases(
                self._active_filter(organization_id),
                label="Leads activos",
                empty_message="No tienes leads activos en Renova.",
            )
        if parsed.intent == "archived_count":
            count = self._count(*self._archived_filter(organization_id))
            return (
                f"Tienes {count} expediente{'s' if count != 1 else ''} "
                f"archivado{'s' if count != 1 else ''} en Renova."
            )
        if parsed.intent == "archived_list":
            return self._list_cases(
                self._archived_filter(organization_id),
                label="Expedientes archivados",
                empty_message="No tienes expedientes archivados en Renova.",
            )
        if parsed.intent == "pipeline_summary":
            active_counts = dict(
                self.db.execute(
                    select(RenovaCase.status, func.count())
                    .where(
                        RenovaCase.organization_id == organization_id,
                        RenovaCase.status.in_(ACTIVE_STATUSES),
                        RenovaCase.archived.is_(False),
                    )
                    .group_by(RenovaCase.status)
                ).all()
            )
            terminal_counts = dict(
                self.db.execute(
                    select(RenovaCase.status, func.count())
                    .where(
                        RenovaCase.organization_id == organization_id,
                        RenovaCase.status.in_(TERMINAL_STATUSES),
                    )
                    .group_by(RenovaCase.status)
                ).all()
            )

            active_total = sum(active_counts.values())
            if active_total:
                active_summary = "; ".join(
                    f"{STATUS_LABELS[status_key]}: {active_counts[status_key]}"
                    for status_key in ACTIVE_STATUSES
                    if active_counts.get(status_key)
                )
                answer = (
                    f"Tu pipeline activo de Renova tiene {active_total} "
                    f"expediente{'s' if active_total != 1 else ''}. {active_summary}."
                )
            else:
                answer = "No tienes expedientes activos en el pipeline de Renova."

            terminal_summary = "; ".join(
                f"{STATUS_LABELS[status_key]}: {terminal_counts[status_key]}"
                for status_key in TERMINAL_STATUSES
                if terminal_counts.get(status_key)
            )
            if terminal_summary:
                answer += f" Fuera del pipeline activo: {terminal_summary}."
            return answer

        if parsed.intent in ("filtered_count", "filtered_list"):
            return self._filtered_answer(organization_id, parsed)

        assert case is not None
        name = case.owner_name
        if parsed.intent in _FIXED_FIELD_INTENTS:
            return RENOVA_CASE_FIELD_RESOLVERS[parsed.intent](case)
        if parsed.intent == "case_field":
            if parsed.field is None:
                return "No entendí qué dato de ese expediente quieres consultar. ¿Puedes reformular la pregunta?"
            resolver = RENOVA_CASE_FIELD_RESOLVERS.get(parsed.field)
            if resolver is None:
                # Unreachable while RenovaReadableField stays a closed Literal
                # matching RENOVA_CASE_FIELD_RESOLVERS's keys (see
                # tests/test_renova_chat_fields.py) -- kept as a defensive,
                # honest failure rather than silently answering nothing.
                return "No entendí qué dato de ese expediente quieres consultar. ¿Puedes reformular la pregunta?"
            return resolver(case)
        if parsed.intent == "total_debt":
            total = sum_debts([getattr(case, field) for field in DEBT_FIELDS])
            if total is None:
                return f"{name} no tiene montos de adeudo registrados."
            return f"La deuda total conocida de {name} es {format_money(total, case.currency)}."
        if parsed.intent == "debt_breakdown":
            labels = {
                "property_tax_debt": "predial", "other_debt": "otros adeudos", "water_debt": "agua",
                "electricity_debt": "luz", "gas_debt": "gas",
            }
            # property_tax_debt is formatted through format_property_tax_debt
            # specifically so a years-only figure is never shown as pesos.
            captured = [
                f"{labels[field]}: "
                f"{format_property_tax_debt(case) if field == 'property_tax_debt' else format_money(getattr(case, field), case.currency)}"
                for field in DEBT_FIELDS
                if getattr(case, field) is not None
            ]
            if not captured:
                return f"{name} no tiene montos de adeudo registrados."
            total = sum_debts([getattr(case, field) for field in DEBT_FIELDS])
            return f"Adeudos de {name}: {'; '.join(captured)}. Total conocido: {format_money(total, case.currency)}."
        return self._case_summary(case)

    @staticmethod
    def _case_summary(case: RenovaCase) -> str:
        """
        A concise advisor-facing summary: owner, status, contact,
        property/location, known debts, expected amount and sale reason --
        skipping anything not captured yet rather than padding the answer
        with "No está registrado" for every absent field.
        """
        parts = [f"{case.owner_name}: etapa {STATUS_LABELS.get(case.status, case.status)}", f"teléfono {case.owner_phone}"]

        address = ", ".join(
            part for part in (case.street_address, case.neighborhood, case.municipality, case.postal_code) if part
        )
        if address:
            parts.append(f"dirección {address}")

        dwelling_bits = []
        if case.dwelling_type:
            dwelling_bits.append(DWELLING_LABELS.get(case.dwelling_type, case.dwelling_type))
        if case.is_duplex:
            dwelling_bits.append("dúplex")
        if dwelling_bits:
            parts.append(" ".join(dwelling_bits))

        config_bits = []
        if case.floors is not None:
            config_bits.append(f"{case.floors} plantas")
        if case.bedrooms is not None:
            config_bits.append(f"{case.bedrooms} recámaras")
        if case.bathrooms is not None:
            config_bits.append(f"{case.bathrooms} baños")
        if config_bits:
            parts.append(", ".join(config_bits))

        total = sum_debts([getattr(case, field) for field in DEBT_FIELDS])
        if total is not None:
            parts.append(f"deuda total conocida {format_money(total, case.currency)}")
        if case.market_value is not None:
            parts.append(f"valor de mercado {format_money(case.market_value, case.currency)}")
        if case.final_offer is not None:
            parts.append(f"propuesta final {format_money(case.final_offer, case.currency)}")
        if case.owner_expected_amount is not None:
            parts.append(f"espera recibir {format_money(case.owner_expected_amount, case.currency)}")
        if case.sale_reason:
            parts.append(f"motivo de venta: {case.sale_reason}")

        return "; ".join(parts) + "."

    def _filtered_answer(self, organization_id: uuid.UUID, parsed: ParsedRenovaQuestion) -> str:
        if parsed.filter is None:
            return "No entendí ese filtro. ¿Puedes reformular la pregunta?"
        clause = build_filter_clause(parsed.filter)
        if clause is None:
            return "No entendí ese filtro. ¿Puedes reformular la pregunta?"

        filters = (RenovaCase.organization_id == organization_id, RenovaCase.archived.is_(False), clause)
        description = describe_filter(parsed.filter)

        if parsed.intent == "filtered_count":
            count = self._count(*filters)
            return f"Tienes {count} lead{'s' if count != 1 else ''} {description}."

        return self._list_filtered_cases(filters, description=description)

    def _list_filtered_cases(self, filters: tuple, *, description: str, limit: int = 20) -> str:
        total = self._count(*filters)
        if total == 0:
            return f"No tengo leads {description}."
        cases = list(
            self.db.execute(
                select(RenovaCase).where(*filters).order_by(RenovaCase.entry_date.desc()).limit(limit)
            ).scalars().all()
        )
        bullets = "\n".join(f"• {c.owner_name}" for c in cases)
        suffix = f"\n\nMostré los {limit} más recientes." if total > limit else ""
        return f"Hay {total} lead{'s' if total != 1 else ''} {description}:\n\n{bullets}{suffix}"

    @staticmethod
    def _active_filter(organization_id: uuid.UUID) -> tuple:
        return (
            RenovaCase.organization_id == organization_id,
            RenovaCase.status.in_(ACTIVE_STATUSES),
            RenovaCase.archived.is_(False),
        )

    @staticmethod
    def _archived_filter(organization_id: uuid.UUID) -> tuple:
        return (RenovaCase.organization_id == organization_id, RenovaCase.archived.is_(True))

    def _count(self, *filters) -> int:
        return self.db.scalar(select(func.count()).select_from(RenovaCase).where(*filters)) or 0

    def _list_cases(self, filters: tuple, *, label: str, empty_message: str, limit: int = 20) -> str:
        """Shared by active_list/archived_list: a total count plus up to `limit` of the newest matching cases."""
        total = self._count(*filters)
        cases = list(
            self.db.execute(
                select(RenovaCase).where(*filters).order_by(RenovaCase.entry_date.desc()).limit(limit)
            ).scalars().all()
        )
        if not cases:
            return empty_message
        items = "; ".join(f"{c.owner_name} — {STATUS_LABELS.get(c.status, c.status)}" for c in cases)
        suffix = f" Mostré los {limit} más recientes." if total > limit else ""
        return f"{label} ({total}): {items}.{suffix}"
