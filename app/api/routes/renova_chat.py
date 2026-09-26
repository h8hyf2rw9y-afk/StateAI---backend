import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMConfigError, LLMInvalidOutputError, LLMProviderError, LLMTimeoutError
from app.ai.llm.factory import build_default_provider
from app.core.database import get_db
from app.core.security import get_current_org_user
from app.schemas.renova_chat import (
    RenovaChatConversationCreate,
    RenovaChatConversationRead,
    RenovaChatMessageRead,
    RenovaChatQuestion,
    RenovaChatTurn,
)
from app.schemas.user import CurrentUser
from app.services.renova_chat_service import RenovaChatService

router = APIRouter(prefix="/renova/chat", tags=["renova-chat"])


def get_renova_chat_llm() -> LLMProvider:
    try:
        return build_default_provider()
    except LLMConfigError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El asistente no está configurado.") from exc


@router.get("/conversations", response_model=list[RenovaChatConversationRead])
def list_conversations(
    current_user: CurrentUser = Depends(get_current_org_user), db: Session = Depends(get_db)
):
    return RenovaChatService(db).list_conversations(current_user)


@router.post("/conversations", response_model=RenovaChatConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    data: RenovaChatConversationCreate,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
):
    return RenovaChatService(db).create_conversation(current_user, data.title)


@router.get("/conversations/{conversation_id}/messages", response_model=list[RenovaChatMessageRead])
def list_messages(
    conversation_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
):
    return RenovaChatService(db).get_messages(current_user, conversation_id)


@router.post("/conversations/{conversation_id}/messages", response_model=RenovaChatTurn)
def ask_question(
    conversation_id: uuid.UUID,
    data: RenovaChatQuestion,
    current_user: CurrentUser = Depends(get_current_org_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(get_renova_chat_llm),
):
    try:
        conversation, user_message, assistant_message = RenovaChatService(db).ask(
            current_user, conversation_id, data, llm
        )
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "El asistente tardó demasiado en responder.") from exc
    except LLMInvalidOutputError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "El asistente no entendió la consulta. Inténtalo de otra forma.") from exc
    except LLMProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "El asistente no está disponible en este momento.") from exc
    return RenovaChatTurn(
        conversation=conversation,
        user_message=user_message,
        assistant_message=assistant_message,
    )
