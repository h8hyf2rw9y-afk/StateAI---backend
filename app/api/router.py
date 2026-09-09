from fastapi import APIRouter

from app.api.routes import (
    activities,
    agent_executions,
    ai,
    appointments,
    audit_logs,
    buyer_requirements,
    calendar_connections,
    contacts,
    features,
    me,
    notifications,
    properties,
    property_interests,
    tasks,
)

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
api_router.include_router(agent_executions.router)
api_router.include_router(features.router)
api_router.include_router(audit_logs.router)
api_router.include_router(tasks.router)
api_router.include_router(appointments.router)
api_router.include_router(calendar_connections.router)
api_router.include_router(notifications.router)
