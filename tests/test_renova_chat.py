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
        _case(current_user, owner_name="Archivado", status="accepted", archived=True),
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


def test_pipeline_summary_separates_active_and_terminal_statuses(
    client, db_session, current_user
):
    db_session.add_all([
        _case(current_user, owner_name="Nuevo", status="new"),
        _case(current_user, owner_name="En revisión", status="reviewing"),
        _case(current_user, owner_name="Preparando", status="offer_preparation"),
        _case(current_user, owner_name="Comprado", status="purchased"),
        _case(current_user, owner_name="Rechazado", status="rejected"),
        _case(current_user, owner_name="Cancelado", status="cancelled"),
        _case(current_user, owner_name="Borrador", status="draft"),
        _case(
            current_user,
            owner_name="Activo archivado",
            status="accepted",
            archived=True,
        ),
    ])
    other_org = Organization(name="Other pipeline org")
    db_session.add(other_org)
    db_session.flush()
    other_user = User(id=uuid.uuid4(), organization_id=other_org.id, role="agent")
    db_session.add(other_user)
    db_session.flush()
    other_current_user = CurrentUser(
        id=other_user.id,
        email=None,
        organization_id=other_org.id,
        role="agent",
        provider=None,
    )
    db_session.add_all([
        _case(other_current_user, owner_name="Nuevo ajeno", status="new"),
        _case(other_current_user, owner_name="Rechazado ajeno", status="rejected"),
    ])
    db_session.commit()

    fake = FakeChatLLM([{"intent": "pipeline_summary", "owner_name": None}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Dame el resumen del pipeline")

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == (
        "Tu pipeline activo de Renova tiene 3 expedientes. "
        "Nuevo: 1; En revisión: 1; Preparación de oferta: 1. "
        "Fuera del pipeline activo: Comprado: 1; Rechazado: 1; Cancelado: 1."
    )


def test_pipeline_summary_handles_empty_active_stages_and_ignores_drafts(
    client, db_session, current_user
):
    db_session.add(_case(current_user, owner_name="Sólo borrador", status="draft"))
    other_org = Organization(name="Other empty pipeline org")
    db_session.add(other_org)
    db_session.flush()
    other_user = User(id=uuid.uuid4(), organization_id=other_org.id, role="agent")
    db_session.add(other_user)
    db_session.flush()
    other_current_user = CurrentUser(
        id=other_user.id,
        email=None,
        organization_id=other_org.id,
        role="agent",
        provider=None,
    )
    db_session.add(_case(other_current_user, owner_name="Activo ajeno", status="new"))
    db_session.commit()

    fake = FakeChatLLM([{"intent": "pipeline_summary", "owner_name": None}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Cómo está mi pipeline?")

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == (
        "No tienes expedientes activos en el pipeline de Renova."
    )


def test_chat_counts_and_lists_only_explicitly_archived_cases(
    client, db_session, current_user
):
    db_session.add_all([
        _case(
            current_user,
            owner_name="Ana Archivada",
            status="rejected",
            archived=True,
            nss_encrypted="SECRET_NSS_TOKEN",
            credit_number_encrypted="SECRET_CREDIT_TOKEN",
            ine_front_encrypted="SECRET_INE_TOKEN",
        ),
        _case(
            current_user,
            owner_name="Beatriz Archivada",
            status="cancelled",
            archived=True,
        ),
        _case(
            current_user,
            owner_name="Roberto No Archivado",
            status="rejected",
            archived=False,
        ),
    ])
    other_org = Organization(name="Other archived org")
    db_session.add(other_org)
    db_session.flush()
    other_user = User(id=uuid.uuid4(), organization_id=other_org.id, role="agent")
    db_session.add(other_user)
    db_session.flush()
    other_current_user = CurrentUser(
        id=other_user.id,
        email=None,
        organization_id=other_org.id,
        role="agent",
        provider=None,
    )
    db_session.add(
        _case(
            other_current_user,
            owner_name="Expediente Ajeno",
            status="cancelled",
            archived=True,
        )
    )
    db_session.commit()

    # These fallback outputs would be wrong. Explicit archive language must
    # bypass the classifier and the follow-up must use conversation context.
    fake = FakeChatLLM([
        {"intent": "active_list", "owner_name": None},
        {"intent": "help", "owner_name": None},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    count = _ask(client, conversation_id, "¿Tengo leads archivados?")
    archived_list = _ask(client, conversation_id, "¿Cuáles son?")

    assert count.status_code == 200
    assert count.json()["assistant_message"]["content"] == (
        "Tienes 2 expedientes archivados en Renova."
    )
    assert archived_list.status_code == 200
    content = archived_list.json()["assistant_message"]["content"]
    assert "Expedientes archivados (2)" in content
    assert "Ana Archivada — Rechazado" in content
    assert "Beatriz Archivada — Cancelado" in content
    assert "Roberto No Archivado" not in content
    assert "Expediente Ajeno" not in content
    assert "SECRET_NSS_TOKEN" not in content
    assert "SECRET_CREDIT_TOKEN" not in content
    assert "SECRET_INE_TOKEN" not in content
    assert fake.prompts == []


def test_chat_reports_when_there_are_no_explicitly_archived_cases(
    client, db_session, current_user
):
    db_session.add(
        _case(
            current_user,
            owner_name="Rechazado sin archivar",
            status="rejected",
            archived=False,
        )
    )
    db_session.commit()
    fake = FakeChatLLM([])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Muéstrame los archivados")

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == (
        "No tienes expedientes archivados en Renova."
    )
    assert fake.prompts == []


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


# --- Read V2: case_field + conversation context -------------------------------


def test_case_field_resolves_new_fields_and_keeps_context_across_turns(client, db_session, current_user):
    db_session.add(_case(
        current_user, owner_name="Martha González", bedrooms=3, bathrooms=Decimal("2"),
        dwelling_type="house", is_duplex=True, sale_reason="Ya no puede pagar la casa",
    ))
    db_session.commit()
    fake = FakeChatLLM([
        {"intent": "case_summary", "owner_name": "Martha González"},
        {"intent": "case_field", "owner_name": None, "field": "bedrooms"},
        {"intent": "case_field", "owner_name": None, "field": "bathrooms"},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    summary = _ask(client, conversation_id, "Resume a Martha González.")
    bedrooms = _ask(client, conversation_id, "¿Cuántas recámaras tiene?")
    bathrooms = _ask(client, conversation_id, "¿Y baños?")

    assert "Martha González" in summary.json()["assistant_message"]["content"]
    assert "3 recámaras" in bedrooms.json()["assistant_message"]["content"]
    assert "2" in bathrooms.json()["assistant_message"]["content"] and "baños" in bathrooms.json()["assistant_message"]["content"]


def test_case_field_covers_dwelling_duplex_deeds_and_notes_end_to_end(client, db_session, current_user):
    db_session.add(_case(
        current_user, owner_name="Pedro", dwelling_type="apartment", is_duplex=False,
        has_deeds="no", notes="Llamó el martes por la tarde.",
    ))
    db_session.commit()
    fake = FakeChatLLM([
        {"intent": "case_field", "owner_name": "Pedro", "field": "dwelling_type"},
        {"intent": "case_field", "owner_name": "Pedro", "field": "is_duplex"},
        {"intent": "case_field", "owner_name": "Pedro", "field": "has_deeds"},
        {"intent": "case_field", "owner_name": "Pedro", "field": "notes"},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    dwelling = _ask(client, conversation_id, "¿Qué tipo de vivienda tiene Pedro?")
    duplex = _ask(client, conversation_id, "¿La casa de Pedro es dúplex?")
    deeds = _ask(client, conversation_id, "¿Tiene escrituras?")
    notes = _ask(client, conversation_id, "¿Qué notas tengo de Pedro?")

    assert "Departamento" in dwelling.json()["assistant_message"]["content"]
    assert "no es dúplex" in duplex.json()["assistant_message"]["content"]
    assert "No" in deeds.json()["assistant_message"]["content"]
    assert "Llamó el martes por la tarde." in notes.json()["assistant_message"]["content"]


def test_notes_contents_never_reach_the_llm_prompt(client, db_session, current_user):
    db_session.add(_case(current_user, owner_name="Pedro", notes="DATO_PRIVADO_EN_NOTAS"))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "case_field", "owner_name": "Pedro", "field": "notes"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Qué notas tengo de Pedro?")

    assert "DATO_PRIVADO_EN_NOTAS" in response.json()["assistant_message"]["content"]
    assert "DATO_PRIVADO_EN_NOTAS" not in "\n".join(fake.prompts[0])


def test_case_field_with_no_name_and_no_context_asks_for_the_owner(client):
    fake = FakeChatLLM([{"intent": "case_field", "owner_name": None, "field": "bedrooms"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Cuántas recámaras tiene?")

    assert response.status_code == 400


def test_case_field_with_a_null_field_gives_a_safe_message(client, db_session, current_user):
    db_session.add(_case(current_user, owner_name="Pedro"))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "case_field", "owner_name": "Pedro", "field": None}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Cuéntame algo de Pedro.")

    assert response.status_code == 200
    assert "No entendí" in response.json()["assistant_message"]["content"]


# --- Read V2: filtered_count / filtered_list ----------------------------------


def test_filtered_count_and_list_by_status_share_the_same_filter(client, db_session, current_user):
    db_session.add_all([
        _case(current_user, owner_name="Raúl", status="negotiating"),
        _case(current_user, owner_name="Martha", status="negotiating"),
        _case(current_user, owner_name="Andrea", status="accepted"),
    ])
    db_session.commit()
    status_filter = {"field": "status", "operator": "equals", "value": "negotiating"}
    fake = FakeChatLLM([
        {"intent": "filtered_count", "owner_name": None, "filter": status_filter},
        {"intent": "filtered_list", "owner_name": None, "filter": status_filter},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    count = _ask(client, conversation_id, "¿Cuántos están negociando?")
    listing = _ask(client, conversation_id, "¿Qué leads están negociando?")

    assert count.json()["assistant_message"]["content"] == "Tienes 2 leads en Negociando."
    content = listing.json()["assistant_message"]["content"]
    assert "Hay 2 leads en Negociando" in content
    assert "Raúl" in content and "Martha" in content and "Andrea" not in content


def test_filtered_list_new_status(client, db_session, current_user):
    db_session.add_all([
        _case(current_user, owner_name="Carlos", status="new"),
        _case(current_user, owner_name="Andrea", status="accepted"),
    ])
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "status", "operator": "equals", "value": "new"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Enséñame los nuevos.")

    content = response.json()["assistant_message"]["content"]
    assert "Carlos" in content and "Andrea" not in content


def test_filtered_by_municipality(client, db_session, current_user):
    db_session.add_all([
        _case(current_user, owner_name="En Apodaca", municipality="Apodaca"),
        _case(current_user, owner_name="En Monterrey", municipality="Monterrey"),
    ])
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "municipality", "operator": "equals", "value": "Apodaca"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Enséñame los de Apodaca.")

    content = response.json()["assistant_message"]["content"]
    assert "En Apodaca" in content and "En Monterrey" not in content


def test_filtered_by_duplex(client, db_session, current_user):
    db_session.add_all([
        _case(current_user, owner_name="Dúplex", is_duplex=True),
        _case(current_user, owner_name="Normal", is_duplex=False),
    ])
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "is_duplex", "operator": "is_true"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Quiénes tienen casa dúplex?")

    content = response.json()["assistant_message"]["content"]
    assert "Dúplex" in content and "Normal" not in content


def test_filtered_by_has_deeds_and_lacks_deeds(client, db_session, current_user):
    db_session.add_all([
        _case(current_user, owner_name="Con escrituras", has_deeds="yes"),
        _case(current_user, owner_name="Sin escrituras", has_deeds="no"),
    ])
    db_session.commit()
    fake = FakeChatLLM([
        {"intent": "filtered_list", "owner_name": None, "filter": {"field": "has_deeds", "operator": "equals", "value": "no"}},
        {"intent": "filtered_list", "owner_name": None, "filter": {"field": "has_deeds", "operator": "equals", "value": "yes"}},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    lacks = _ask(client, conversation_id, "¿Quiénes no tienen escrituras?")
    has = _ask(client, conversation_id, "¿Qué leads sí tienen escrituras?")

    assert "Sin escrituras" in lacks.json()["assistant_message"]["content"]
    assert "Con escrituras" in has.json()["assistant_message"]["content"]


def test_filtered_by_property_tax_and_water_debt_existence(client, db_session, current_user):
    # _case()'s own defaults carry non-null property_tax_debt/water_debt
    # (used by other tests in this file), so every case below explicitly
    # nulls whichever debts it should NOT have.
    db_session.add_all([
        _case(current_user, owner_name="Debe predial", property_tax_debt=Decimal("12000"), water_debt=None),
        _case(current_user, owner_name="Debe agua", property_tax_debt=None, water_debt=Decimal("500")),
        _case(current_user, owner_name="Sin adeudos", property_tax_debt=None, water_debt=None),
    ])
    db_session.commit()
    fake = FakeChatLLM([
        {"intent": "filtered_list", "owner_name": None, "filter": {"field": "has_property_tax_debt", "operator": "exists"}},
        {"intent": "filtered_list", "owner_name": None, "filter": {"field": "has_water_debt", "operator": "exists"}},
    ])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake
    conversation_id = _conversation(client)

    predial = _ask(client, conversation_id, "¿Quién debe predial?")
    agua = _ask(client, conversation_id, "¿Qué clientes tienen adeudo de agua?")

    assert "Debe predial" in predial.json()["assistant_message"]["content"]
    assert "Debe agua" not in predial.json()["assistant_message"]["content"]
    assert "Debe agua" in agua.json()["assistant_message"]["content"]


def test_filtered_results_never_include_archived_cases(client, db_session, current_user):
    db_session.add_all([
        _case(current_user, owner_name="Activo", status="rejected"),
        _case(current_user, owner_name="Archivado", status="rejected", archived=True),
    ])
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "status", "operator": "equals", "value": "rejected"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Qué leads están rechazados?")

    content = response.json()["assistant_message"]["content"]
    assert "Activo" in content and "Archivado" not in content


def test_filtered_list_states_when_it_truncates(client, db_session, current_user):
    db_session.add_all([_case(current_user, owner_name=f"Lead {i}", status="new") for i in range(25)])
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "status", "operator": "equals", "value": "new"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "Enséñame los nuevos.")

    content = response.json()["assistant_message"]["content"]
    assert content.startswith("Hay 25 leads en Nuevo")
    assert "Mostré los 20 más recientes." in content


def test_filtered_count_with_no_matches(client, db_session, current_user):
    db_session.add(_case(current_user, owner_name="Único", status="new"))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_count", "owner_name": None, "filter": {"field": "status", "operator": "equals", "value": "accepted"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Cuántos están aceptados?")

    assert response.json()["assistant_message"]["content"] == "Tienes 0 leads en Aceptado."


def test_an_invalid_filter_combination_gives_a_safe_message_not_a_crash(client, db_session, current_user):
    db_session.add(_case(current_user, owner_name="Pedro"))
    db_session.commit()
    # is_duplex never takes "equals" -- see app/renova_chat/filters.py's _VALID_OPERATORS_BY_FIELD.
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "is_duplex", "operator": "equals", "value": "true"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "pregunta rara")

    assert response.status_code == 200
    assert "No entendí ese filtro" in response.json()["assistant_message"]["content"]


def test_filtered_queries_are_organization_scoped(client, db_session, current_user):
    db_session.add(_case(current_user, owner_name="Mío", status="negotiating"))
    other_org = Organization(name="Other")
    db_session.add(other_org)
    db_session.flush()
    other_user = User(id=uuid.uuid4(), organization_id=other_org.id, role="agent")
    db_session.add(other_user)
    db_session.flush()
    db_session.add(_case(
        CurrentUser(id=other_user.id, email=None, organization_id=other_org.id, role="agent", provider=None),
        owner_name="Ajeno", status="negotiating",
    ))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "filtered_list", "owner_name": None, "filter": {"field": "status", "operator": "equals", "value": "negotiating"}}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Qué leads están negociando?")

    content = response.json()["assistant_message"]["content"]
    assert "Mío" in content and "Ajeno" not in content


# --- debt_breakdown / case_summary ---------------------------------------------


def test_debt_breakdown_shows_property_tax_in_years_not_as_money(client, db_session, current_user):
    """Regression: debt_breakdown used to format a years-only predial figure as if it were pesos."""
    db_session.add(_case(
        current_user, owner_name="Pedro", property_tax_debt=Decimal("4"), property_tax_debt_unit="years",
        water_debt=Decimal("500"),
    ))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "debt_breakdown", "owner_name": "Pedro"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Cómo se desglosa la deuda de Pedro?")

    content = response.json()["assistant_message"]["content"]
    assert "predial: 4 años" in content
    assert "$4" not in content


def test_case_summary_includes_present_fields_and_skips_absent_ones(client, db_session, current_user):
    db_session.add(_case(
        current_user, owner_name="Pedro", dwelling_type="house", is_duplex=True, bedrooms=3,
        sale_reason="Ya no puede pagar la casa", market_value=None, final_offer=None,
        owner_expected_amount=None, other_debt=None, water_debt=None, electricity_debt=None, gas_debt=None,
        property_tax_debt=None,
    ))
    db_session.commit()
    fake = FakeChatLLM([{"intent": "case_summary", "owner_name": "Pedro"}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Qué sabemos de Pedro?")

    content = response.json()["assistant_message"]["content"]
    assert "Casa dúplex" in content
    assert "3 recámaras" in content
    assert "Ya no puede pagar la casa" in content
    assert "No está registrado" not in content
    assert content.count("No registrad") == 0


def test_help_describes_expanded_read_capabilities_and_still_denies_writes(client, db_session, current_user):
    fake = FakeChatLLM([{"intent": "help", "owner_name": None}])
    client.app.dependency_overrides[get_renova_chat_llm] = lambda: fake

    response = _ask(client, _conversation(client), "¿Qué puedes hacer?")

    content = response.json()["assistant_message"]["content"]
    assert "recámaras" in content
    assert "escrituras" in content
    assert "no creo, edito ni elimino" in content
