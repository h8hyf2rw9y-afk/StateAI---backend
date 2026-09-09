"""
Global, structured error handling — every error response this API returns
(validation, not-found, forbidden, conflicting writes, or a genuine bug)
has the same shape:

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

instead of whatever shape happened to bubble up (FastAPI's default
{"detail": ...}, a raw SQLAlchemy traceback, ...). Two things make this
possible: `RequestIDMiddleware` below stamps every request with an id
(also returned as the `X-Request-ID` response header, and included in the
server-side log line for anything that goes wrong — the thing you'd hand a
user asking "what happened?" so it can be found in the logs), and
`register_exception_handlers` maps every exception type this app can raise
to that same envelope.

Never leaks: a stack trace, raw SQL, a filesystem path, or any exception
detail beyond a short, safe message — see handle_unexpected_error and
handle_integrity_error, both of which log the real exception server-side
(via logger.exception/logger.warning) but only ever return a generic
message to the client.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("app.errors")

REQUEST_ID_HEADER = "X-Request-ID"

# Only the codes this app actually returns today (see every HTTPException
# raised across app/services/*.py and app/api/routes/*.py) — falls back to
# a generic "ERROR" for anything not listed, so adding a new status code
# somewhere never requires touching this file.
_STATUS_CODE_NAMES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
    status.HTTP_502_BAD_GATEWAY: "BAD_GATEWAY",
    status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
    status.HTTP_504_GATEWAY_TIMEOUT: "GATEWAY_TIMEOUT",
}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Stamps `request.state.request_id` (a fresh uuid4) on every request and echoes it back as the `X-Request-ID` response header — including on error responses, via the handlers below."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _request_id(request: Request) -> str:
    # Falls back to a fresh id in the (untested-in-practice) case a handler
    # runs before RequestIDMiddleware got to set one.
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={REQUEST_ID_HEADER: request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        """Every existing `raise HTTPException(...)` across this codebase (404/403/422/502/503/504/...) lands here — same status code as before, now in the shared envelope."""
        request_id = _request_id(request)
        code = _STATUS_CODE_NAMES.get(exc.status_code, "ERROR")
        return _error_response(exc.status_code, code, str(exc.detail), request_id)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """A malformed request body/query (missing required field, wrong type, a failed Pydantic model_validator like ContactBase's email-or-phone check)."""
        request_id = _request_id(request)
        # exc.errors()[i]["loc"] is like ("body", "email") — dropping the
        # first segment ("body"/"query"/"path") keeps the message about the
        # field the caller actually sent, not FastAPI's internal location shape.
        details = "; ".join(f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors())
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", details or "Invalid request.", request_id
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        """A database constraint (unique/foreign key/check) rejected the write — e.g. a race-condition double-submit past an in-memory duplicate check (see app/repositories/buyer_requirement_repo.py's add_location comment). Never echoes exc itself: it can contain raw SQL and literal values."""
        request_id = _request_id(request)
        logger.warning("integrity_error request_id=%s path=%s", request_id, request.url.path)
        return _error_response(
            status.HTTP_409_CONFLICT, "CONFLICT", "This action conflicts with existing data.", request_id
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Last resort — a genuine bug. Full traceback goes to the server log only; the response never includes it."""
        request_id = _request_id(request)
        logger.exception("unhandled_error request_id=%s path=%s", request_id, request.url.path)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "An unexpected error occurred.", request_id
        )
