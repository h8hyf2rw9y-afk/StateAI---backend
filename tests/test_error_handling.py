"""
Global error handling (app/core/errors.py): every error response shares the
{"error": {"code", "message", "request_id"}} envelope, a request_id is
always present (including as the X-Request-ID header), and nothing leaks a
stack trace, raw SQL, or internal detail.
"""

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app


def _assert_envelope(body: dict, *, code: str) -> None:
    assert set(body.keys()) == {"error"}
    error = body["error"]
    assert set(error.keys()) == {"code", "message", "request_id"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and len(error["request_id"]) > 0


def test_not_found_uses_the_error_envelope(client: TestClient):
    import uuid

    response = client.get(f"/api/v1/contacts/{uuid.uuid4()}")
    assert response.status_code == 404
    _assert_envelope(response.json(), code="NOT_FOUND")
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_validation_error_uses_the_error_envelope_and_names_the_bad_field(client: TestClient):
    response = client.post("/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez"})  # no email or phone
    assert response.status_code == 422
    body = response.json()
    _assert_envelope(body, code="VALIDATION_ERROR")
    assert "email" in body["error"]["message"] or "phone" in body["error"]["message"]


def test_forbidden_uses_the_error_envelope(client: TestClient):
    contact = client.post(
        "/api/v1/contacts", json={"first_name": "Juan", "last_name": "Perez", "phone": "+52 811 000 0000"}
    ).json()
    response = client.delete(f"/api/v1/contacts/{contact['id']}")  # default role "agent" -> 403
    assert response.status_code == 403
    _assert_envelope(response.json(), code="FORBIDDEN")


def test_unauthenticated_uses_the_error_envelope():
    with TestClient(app) as unauthenticated_client:
        response = unauthenticated_client.get("/api/v1/me")
    assert response.status_code == 401
    _assert_envelope(response.json(), code="UNAUTHORIZED")


def test_every_response_carries_a_request_id_header(client: TestClient):
    response = client.get("/api/v1/features")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers


def test_unexpected_error_returns_a_generic_500_envelope_without_leaking_details(client: TestClient):
    """
    A genuine bug (simulated here) must never reach the client as a stack
    trace or raw exception text. Uses its own TestClient with
    raise_server_exceptions=False: Starlette's ServerErrorMiddleware always
    sends our handler's response *and* re-raises the original exception
    afterward (so it still reaches server-side logs/loggers) — the default
    `client` fixture's TestClient would otherwise surface that re-raise as a
    test failure instead of letting us inspect the response it already
    sent. No need to restore get_db's override afterward — the `client`
    fixture's own teardown clears all overrides once this test returns.
    """

    class ExplodingSession:
        def __getattr__(self, name):
            raise RuntimeError("simulated internal failure: /etc/secret/path leaked if this reached the client")

    def broken_get_db():
        yield ExplodingSession()

    app.dependency_overrides[get_db] = broken_get_db
    lenient_client = TestClient(app, raise_server_exceptions=False)
    response = lenient_client.get("/api/v1/features")

    assert response.status_code == 500
    body = response.json()
    _assert_envelope(body, code="INTERNAL_ERROR")
    assert "secret" not in body["error"]["message"]
    assert "RuntimeError" not in body["error"]["message"]
    assert body["error"]["message"] == "An unexpected error occurred."
