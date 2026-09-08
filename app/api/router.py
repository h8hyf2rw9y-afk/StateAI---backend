from fastapi import APIRouter

from app.api.routes import activities, ai, buyer_requirements, contacts, me, properties, property_interests

# Health lives outside this router — mounted at the app root in main.py,
# unversioned, since uptime checks/load balancers shouldn't care about API versioning.
api_router = APIRouter()
api_router.include_router(me.router)
api_router.include_router(contacts.router)
api_router.include_router(properties.router)
api_router.include_router(buyer_requirements.router)
api_router.include_router(property_interests.router)
api_router.include_router(activities.router)
api_router.include_router(ai.router)
