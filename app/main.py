import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import health
from app.automation.scheduler import start_scheduler, stop_scheduler
from app.core.config import settings
from app.core.errors import RequestIDMiddleware, register_exception_handlers

# Without this, Python's logging module has no configured handler and
# silently drops anything below WARNING — which meant every logger.info()
# call in this codebase (app.ai.gateway's "executed successfully" line
# included) was invisible even when the app ran, discovered while verifying
# the AI Gateway live. WARNING/ERROR already surfaced via Python's built-in
# last-resort handler, which is why failure logs were visible before this.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Starts the Phase 5 automation scheduler (app/automation/scheduler.py)
    once, when the app actually starts serving requests — not at import
    time (which would also fire during `pytest`'s test-client construction,
    where a background thread scanning for overdue tasks on every test's
    fresh in-memory database would be pure noise, not a fix). Stopped
    cleanly on shutdown so a dev-server reload doesn't accumulate orphaned
    background threads.
    """
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="StateAI / PropPilot API", version="0.1.0", lifespan=lifespan)

# Order matters: Starlette applies middleware outermost-first in the order
# added, so CORS still wraps every response (including one built by an
# exception handler) while RequestIDMiddleware still runs for every request
# that reaches this app, error or not — see app/core/errors.py.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(api_router, prefix="/api/v1")
