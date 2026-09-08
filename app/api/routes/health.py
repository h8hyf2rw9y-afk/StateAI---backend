from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Unauthenticated — just confirms the server is up (uptime checks, quick sanity check while developing)."""
    return {"status": "ok"}
