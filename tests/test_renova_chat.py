import uuid
from datetime import date
from decimal import Decimal

from app.ai.llm.base import LLMProvider
from app.api.routes.renova_chat import get_renova_chat_llm
from app.core.config import settings
from app.models.organization import Organization, User
from app.models.renova_case import RenovaCase
from app.schemas.user import CurrentUser


class FakeChatLLM(LLMProvider):
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.prompts: list[tuple[str, str]] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-chat"

    def generate_structured(self, *, system_prompt, user_prompt, response_model, max_tokens=1024):
        self.prompts.append((system_prompt, user_prompt))
        return response_model.model_validate(self.outputs.pop(0))


def _case(current_user: CurrentUser, **overrides) -> RenovaCase:
    values = {
        "organization_id": current_user.organization_id,
        "assigned_user_id": current_user.id,
        "created_by_user_id": current_user.id,
        "entry_date": date(2026, 9, 20),
        "source": "whatsapp",
        "status": "new",
        "owner_name": "Juan Carlos Pérez",
        "owner_phone": "81 1234 5678",
        "street_address": "Calle Roble 14",
        "neighborhood": "Centro",
        "municipality": "Monterrey",
        "postal_code": "64000",
        "currency": "MXN",
        "property_tax_debt": Decimal("12000"),
        "other_debt": Decimal("320000"),
        "water_debt": Decimal("800"),
        "electricity_debt": None,
        "gas_debt": None,
        "market_value": Decimal("700000"),
        "final_offer": Decimal("460000"),
        "owner_expected_amount": Decimal("140000"),
        "has_deeds": "yes",
    }
    values.update(overrides)
    return RenovaCase(**values)


def _conversation(client) -> str:
    response = client.post("/api/v1/renova/chat/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]


def _ask(client, conversation_id: str, content: str):
    return client.post(
        f"/api/v1/renova/chat/conversations/{conversation_id}/messages",
        json={"content": content},
    )


def test_renova_chat_routes_are_registered_in_openapi(client):
    """Fail loudly if main stops mounting the Renova chat router."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/renova/chat/conversations" in paths
    assert {"get", "post"} <= set(paths["/api/v1/renova/chat/conversations"])


def test_chat_answers_active_count_from_org_scoped_data(client, db_session, current_user):
    db_session.add_all([
        _case(current_user),
        _case(current_user, owner_name="María", status="accepted"),
        _case(current_user, owner_name="Pedro", status="purchased"),
    ])
    other_org = Organization(name="Other")
    db_session.add(other_org)
    db_session.flush()
    other_user = User(id=uuid.uuid4(), organization_id=other_org.id, role="agent")
    db_session.add(other_user)
    db_session.flush()
    db_session.add(_case(CurrentUser(id=other_user.id, email=None, organization_id=other_org.id, role="agent", provider=None), owner_name="Ajeno"))
    db_session.commit()

    fake = FakeChatLLM([{"intent": "active_count", "owner_name": None}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    response = _ask(client, _conversation(client), "¿Cuántos leads activos tengo?")

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Tienes 2 leads activos en Renova."


def test_chat_reads_allowlisted_case_fields_and_keeps_case_context(client, db_session, current_user):
    db_session.add(_case(current_user))
    db_session.commit()
    fake = FakeChatLLM([
        {"intent": "phone", "owner_name": "Juan Carlos"},
        {"intent": "address", "owner_name": None},
        {"intent": "total_debt", "owner_name": None},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    phone = _ask(client, conversation_id, "¿Cuál es el número de Juan Carlos?")
    address = _ask(client, conversation_id, "¿Y cuál es su dirección?")
    debt = _ask(client, conversation_id, "¿Cuánto debe en total?")

    assert "81 1234 5678" in phone.json()["assistant_message"]["content"]
    assert "Calle Roble 14, Centro, Monterrey, 64000" in address.json()["assistant_message"]["content"]
    assert "$332,800.00" in debt.json()["assistant_message"]["content"]
    messages = client.get(f"/api/v1/renova/chat/conversations/{conversation_id}/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"] * 3


def test_llm_only_receives_question_not_renova_records(client, db_session, current_user):
    db_session.add(_case(current_user, notes="PRIVATE_DATABASE_NOTE", owner_phone="SECRET_PHONE"))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "phone", "owner_name": "Juan Carlos"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Dame el teléfono de Juan Carlos")

    assert response.status_code == 200
    combined_prompt = "\n".join(fake.prompts[0])
    assert "PRIVATE_DATABASE_NOTE" not in combined_prompt
    assert "SECRET_PHONE" not in combined_prompt


def test_protected_data_is_never_returned_or_stored(client, db_session, current_user):
    db_session.add(_case(current_user))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "protected_data", "owner_name": "Juan Carlos"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    response = _ask(client, conversation_id, "Dame el NSS de Juan Carlos")

    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "no consulto NSS" in content
    assert "expediente autorizado" in content


def test_pasted_identifier_is_redacted_before_llm_and_history(client):
    pasted_nss = "12345678901"
    fake = FakeChatLLM([{"intent": "protected_data", "owner_name": "Juan Carlos"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    response = _ask(client, conversation_id, f"El NSS de Juan Carlos es {pasted_nss}, ¿lo tienes?")

    assert response.status_code == 200
    assert pasted_nss not in fake.prompts[0][1]
    assert "[dato protegido]" in fake.prompts[0][1]
    messages = client.get(f"/api/v1/renova/chat/conversations/{conversation_id}/messages").json()
    assert pasted_nss not in " ".join(message["content"] for message in messages)


def test_conversation_is_private_to_its_user(client, db_session, current_user):
    conversation_id = _conversation(client)
    second = User(id=uuid.uuid4(), organization_id=current_user.organization_id, role="agent")
    db_session.add(second)
    db_session.commit()
    other = CurrentUser(id=second.id, email=None, organization_id=current_user.organization_id, role="agent", provider=None)
    from app.core.security import get_current_org_user

    client.app.dependency_overrides[get_current_org_user] = lambda: other
    response = client.get(f"/api/v1/renova/chat/conversations/{conversation_id}/messages")
    assert response.status_code == 404


def test_chat_rate_limits_repeated_llm_calls(client, monkeypatch):
    monkeypatch.setattr(settings, "ai_user_rate_limit_per_minute", 1)
    fake = FakeChatLLM([{"intent": "active_count", "owner_name": None}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    assert _ask(client, conversation_id, "¿Cuántos leads activos tengo?").status_code == 200
    limited = _ask(client, conversation_id, "¿Y ahora?")

    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert len(fake.prompts) == 1
