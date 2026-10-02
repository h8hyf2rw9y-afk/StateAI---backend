from fastapi.testclient import TestClient

from app.ai.llm.base import LLMProvider
from app.ai.llm.errors import LLMProviderError
from app.api.routes.renova import get_renova_quick_notes_llm
from app.main import app
from app.schemas.renova_quick_notes import RenovaQuickNotesExtraction


class FakeQuickNotesProvider(LLMProvider):
    def __init__(self, response: RenovaQuickNotesExtraction | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.user_prompt = ""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-quick-notes"

    def generate_structured(self, *, system_prompt, user_prompt, response_model, max_tokens=1024):
        self.user_prompt = user_prompt
        assert response_model is RenovaQuickNotesExtraction
        assert "Pedro" in system_prompt
        if self.error:
            raise self.error
        return self.response


def test_quick_notes_extracts_natural_fields_and_never_sends_long_numbers_to_llm(client: TestClient):
    provider = FakeQuickNotesProvider(
        RenovaQuickNotesExtraction(
            owner_name="Pedro",
            street_address="Cardo 2010",
            municipality="Salinas Victoria",
            neighborhood="Privadas Reales",
        )
    )
    app.dependency_overrides[get_renova_quick_notes_llm] = lambda: provider
    try:
        response = client.post(
            "/api/v1/renova/quick-notes/extract",
            json={
                "content": "Pedro, dirección Cardo 2010, número de seguro social 12345678910, "
                "Salinas Victoria, Privadas Reales, número teléfono 8125455785"
            },
        )
    finally:
        app.dependency_overrides.pop(get_renova_quick_notes_llm, None)

    assert response.status_code == 200
    assert response.json()["owner_name"] == "Pedro"
    assert response.json()["street_address"] == "Cardo 2010"
    assert response.json()["municipality"] == "Salinas Victoria"
    assert response.json()["neighborhood"] == "Privadas Reales"
    assert "12345678910" not in provider.user_prompt
    assert "8125455785" not in provider.user_prompt
    assert provider.user_prompt.count("[NUMERO_PROTEGIDO]") == 2
    assert response.headers["cache-control"] == "no-store"


def test_quick_notes_requires_a_non_empty_bounded_note(client: TestClient):
    provider = FakeQuickNotesProvider(RenovaQuickNotesExtraction())
    app.dependency_overrides[get_renova_quick_notes_llm] = lambda: provider
    try:
        assert client.post("/api/v1/renova/quick-notes/extract", json={"content": "   "}).status_code == 422
        assert client.post("/api/v1/renova/quick-notes/extract", json={"content": "x" * 5001}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_renova_quick_notes_llm, None)


def test_quick_notes_maps_provider_failure_without_leaking_details(client: TestClient):
    provider = FakeQuickNotesProvider(error=LLMProviderError("private provider detail"))
    app.dependency_overrides[get_renova_quick_notes_llm] = lambda: provider
    try:
        response = client.post("/api/v1/renova/quick-notes/extract", json={"content": "Pedro, dirección Cardo 2010"})
    finally:
        app.dependency_overrides.pop(get_renova_quick_notes_llm, None)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "Quick Notes no está disponible en este momento."
    assert "private provider detail" not in response.text


def test_quick_notes_response_schema_contains_no_protected_fields(client: TestClient):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["RenovaQuickNotesExtraction"]["properties"]
    assert "nss" not in schema
    assert "credit_number" not in schema
    assert "owner_phone" not in schema
