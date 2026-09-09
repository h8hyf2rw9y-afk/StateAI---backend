import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import health
from app.core.config import settings

# Without this, Python's logging module has no configured handler and
# silently drops anything below WARNING — which meant every logger.info()
# call in this codebase (app.ai.gateway's "executed successfully" line
# included) was invisible even when the app ran, discovered while verifying
# the AI Gateway live. WARNING/ERROR already surfaced via Python's built-in
# last-resort handler, which is why failure logs were visible before this.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="StateAI / PropPilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(api_router, prefix="/api/v1")
